/*
 * WaveGuard Shoreline Node Firmware
 * Target: Arduino Uno
 * Role: Physical water-level sensor node and alert controller (Role C)
 * 
 * Hardware:
 *   - HC-SR04 Ultrasonic Distance Sensor
 *   - Green LED (SAFE indicator)
 *   - Yellow LED (WATCH indicator)
 *   - Red LED (WARNING indicator)
 *   - Piezo Buzzer (Pulsing WARNING siren)
 *
 * Serial Interface:
 *   - Baud Rate: 115200 bps
 *   - Output:  READING,<unix_timestamp>,<distance_cm>,<quality>
 *   - Input:   STATE,SAFE | STATE,WATCH | STATE,WARNING | STATE,SURGE | TIME,<unix_epoch>
 */

#ifdef ARDUINO_UNO_Q
// On the Arduino UNO Q the USB port belongs to the board's Linux side, and plain
// Serial is pins 0/1. Including the RouterBridge makes `Serial` an alias of its
// `Monitor`, which reaches the PC over USB. Classic Uno boards are unaffected.
#include <Arduino_RouterBridge.h>
#endif

// ================= Pin Configuration =================
const int PIN_TRIG       = 9;   // HC-SR04 Trigger pin
const int PIN_ECHO       = 10;  // HC-SR04 Echo pin
const int PIN_LED_GREEN  = 4;   // Green LED (SAFE)
const int PIN_LED_YELLOW = 5;   // Yellow LED (WATCH)
const int PIN_LED_RED    = 6;   // Red LED (WARNING)
const int PIN_BUZZER     = 7;   // Piezo Buzzer

// ================= Operational Parameters =============
const unsigned long SAMPLE_INTERVAL_MS = 1000;   // 1 Hz stable sampling rate
const unsigned long SURGE_PULSE_MS     = 150;    // Sudden surge: fast 150ms ON / 150ms OFF siren (red flashes with it)
const unsigned long SEICHE_PULSE_MS    = 600;    // Seiche warning: slower 600ms ON / 600ms OFF siren
const float MIN_VALID_DISTANCE_CM      = 2.0;    // HC-SR04 physical minimum
const float MAX_VALID_DISTANCE_CM      = 120.0;  // Maximum expected tray/shoreline distance (bench setups sit ~70 cm high)
const unsigned long ECHO_TIMEOUT_US    = 25000;  // ~4.3m max timeout (~25ms)
const unsigned long ECHO_START_TIMEOUT_US  = 5000;   // ECHO normally rises ~0.5 ms after TRIG
const unsigned long ECHO_SETTLE_TIMEOUT_US = 100000; // Unanswered pings can hold ECHO high for tens of ms
const int PINGS_PER_READING            = 3;      // Median of 3 pings per reported reading
const unsigned long PING_SPACING_MS    = 70;     // HC-SR04 needs ~60 ms between pings

// ================= System State =======================
enum SystemState {
  STATE_SAFE,
  STATE_WATCH,
  STATE_WARNING,
  STATE_SURGE    // Sudden-surge warning: red flashes with the siren
};

SystemState currentState = STATE_SAFE;

// Base timestamp tracking (default starts around Oct 2026 epoch if not synced)
unsigned long baseEpochSeconds = 1791043200UL;
unsigned long epochSyncMillis  = 0;

// Timing trackers
unsigned long lastSampleMillis = 0;
unsigned long lastBuzzerMillis = 0;
bool buzzerPulseState = false;

// Serial input buffer
String inputBuffer = "";

// ================= Setup ==============================
void setup() {
  // Initialize Serial at the contract speed (115200 baud)
#ifdef ARDUINO_UNO_Q
  Bridge.begin();
#endif
  Serial.begin(115200);
  while (!Serial && millis() < 3000); // Allow USB serial to stabilize

  // Configure Pin Modes
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);

  // Initial pin states (Ensure trigger is LOW, start in SAFE state)
  digitalWrite(PIN_TRIG, LOW);
  updateHardwareAlerts();

  epochSyncMillis = millis();
}

// ================= Main Loop ==========================
void loop() {
  unsigned long currentMillis = millis();

  // 1. Process incoming commands from backend
  processSerialCommands();

  // 2. Sample ultrasonic sensor at stable interval
  if (currentMillis - lastSampleMillis >= SAMPLE_INTERVAL_MS) {
    lastSampleMillis = currentMillis;
    takeAndEmitReading(currentMillis);
  }

  // 3. Handle non-blocking warning buzzer pulsation
  handleBuzzer(currentMillis);
}

// ================= Ultrasonic Measurement =============
// Wait without stalling the warning buzzer rhythm.
void waitServicingBuzzer(unsigned long ms) {
  unsigned long start = millis();
  while (millis() - start < ms) {
    handleBuzzer(millis());
  }
}

// One ping, timed with micros(). The UNO Q (Zephyr) core's pulseIn() treats its
// timeout as milliseconds and counts in ~100 µs ticks, which turned missed echoes
// into ~993 cm readings and quantized real distances to 1.7 cm steps.
// Returns the echo pulse width in µs, or 0 when no echo arrived in time.
unsigned long pingEchoUs() {
  // A previous unanswered ping can hold ECHO high; let it finish first.
  unsigned long settleStart = micros();
  while (digitalRead(PIN_ECHO) == HIGH) {
    if (micros() - settleStart > ECHO_SETTLE_TIMEOUT_US) return 0;
  }

  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  unsigned long waitStart = micros();
  while (digitalRead(PIN_ECHO) == LOW) {
    if (micros() - waitStart > ECHO_START_TIMEOUT_US) return 0;
  }
  unsigned long pulseStart = micros();
  while (digitalRead(PIN_ECHO) == HIGH) {
    if (micros() - pulseStart > ECHO_TIMEOUT_US) return 0;
  }
  return micros() - pulseStart;
}

// Median of the pings that returned an echo, or 0 when none did.
unsigned long measureEchoUs() {
  unsigned long echoes[PINGS_PER_READING];
  int count = 0;
  for (int ping = 0; ping < PINGS_PER_READING; ping++) {
    if (ping > 0) waitServicingBuzzer(PING_SPACING_MS);
    unsigned long echoUs = pingEchoUs();
    if (echoUs > 0) echoes[count++] = echoUs;
  }
  if (count == 0) return 0;

  // Insertion sort; at most PINGS_PER_READING values.
  for (int i = 1; i < count; i++) {
    unsigned long value = echoes[i];
    int j = i - 1;
    while (j >= 0 && echoes[j] > value) {
      echoes[j + 1] = echoes[j];
      j--;
    }
    echoes[j + 1] = value;
  }
  return echoes[count / 2];
}

void takeAndEmitReading(unsigned long currentMillis) {
  // Measure round-trip echo duration in microseconds
  unsigned long durationUs = measureEchoUs();

  float distanceCm = 0.0;
  float quality = 0.0;

  if (durationUs == 0) {
    // Timeout or out of range
    distanceCm = 0.0;
    quality = 0.0;
  } else {
    // Speed of sound: ~0.0343 cm/µs -> distance = (duration * 0.0343) / 2
    distanceCm = (durationUs * 0.0343) / 2.0;

    // Quality estimation based on realistic sensor limits
    if (distanceCm >= MIN_VALID_DISTANCE_CM && distanceCm <= MAX_VALID_DISTANCE_CM) {
      // High quality reading within physical water tray boundary
      quality = 0.95;
    } else if (distanceCm > MAX_VALID_DISTANCE_CM && distanceCm <= 200.0) {
      // Possible reflection error or water drained far
      quality = 0.50;
    } else {
      // Unreliable or out of bounds
      quality = 0.10;
    }
  }

  // Calculate current timestamp (seconds)
  unsigned long currentUnixTime = baseEpochSeconds + ((currentMillis - epochSyncMillis) / 1000);

  // Emit serial message according to contract:
  // READING,<unix_timestamp>,<distance_cm>,<quality>
  Serial.print("READING,");
  Serial.print(currentUnixTime);
  Serial.print(",");
  Serial.print(distanceCm, 2);
  Serial.print(",");
  Serial.println(quality, 2);
}

// ================= Serial Command Parsing =============
void processSerialCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        inputBuffer.trim();
        parseCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      inputBuffer += c;
      // Prevent buffer overflow
      if (inputBuffer.length() > 64) {
        inputBuffer = "";
      }
    }
  }
}

void parseCommand(String cmd) {
  cmd.toUpperCase();

  if (cmd.startsWith("STATE,")) {
    String stateStr = cmd.substring(6);
    stateStr.trim();

    if (stateStr == "SAFE") {
      currentState = STATE_SAFE;
    } else if (stateStr == "WATCH") {
      currentState = STATE_WATCH;
    } else if (stateStr == "WARNING") {
      currentState = STATE_WARNING;
    } else if (stateStr == "SURGE") {
      currentState = STATE_SURGE;
    }
    updateHardwareAlerts();
  } else if (cmd.startsWith("TIME,")) {
    // Optional timestamp synchronization from backend: TIME,<epoch_seconds>
    String timeStr = cmd.substring(5);
    timeStr.trim();
    unsigned long newEpoch = strtoul(timeStr.c_str(), NULL, 10);
    if (newEpoch > 0) {
      baseEpochSeconds = newEpoch;
      epochSyncMillis = millis();
    }
  }
}

// ================= Alert Hardware Actuation ===========
void updateHardwareAlerts() {
  switch (currentState) {
    case STATE_SAFE:
      digitalWrite(PIN_LED_GREEN, HIGH);
      digitalWrite(PIN_LED_YELLOW, LOW);
      digitalWrite(PIN_LED_RED, LOW);
      silenceBuzzer();
      break;

    case STATE_WATCH:
      digitalWrite(PIN_LED_GREEN, LOW);
      digitalWrite(PIN_LED_YELLOW, HIGH);
      digitalWrite(PIN_LED_RED, LOW);
      silenceBuzzer();
      break;

    case STATE_WARNING:
    case STATE_SURGE:
      digitalWrite(PIN_LED_GREEN, LOW);
      digitalWrite(PIN_LED_YELLOW, LOW);
      digitalWrite(PIN_LED_RED, HIGH);
      // Buzzer (and the SURGE red flash) is handled by the handleBuzzer() pulse loop
      break;
  }
}

void handleBuzzer(unsigned long currentMillis) {
  if (currentState != STATE_WARNING && currentState != STATE_SURGE) {
    silenceBuzzer();
    return;
  }

  // Non-blocking pulsing siren for WARNING and SURGE states
  unsigned long pulseMs = (currentState == STATE_SURGE) ? SURGE_PULSE_MS : SEICHE_PULSE_MS;
  if (currentMillis - lastBuzzerMillis >= pulseMs) {
    lastBuzzerMillis = currentMillis;
    buzzerPulseState = !buzzerPulseState;

    // SURGE: red flashes in step with the siren instead of staying solid
    if (currentState == STATE_SURGE) {
      digitalWrite(PIN_LED_RED, buzzerPulseState ? HIGH : LOW);
    }

    if (buzzerPulseState) {
      // Compatible with both Active Buzzers and Passive Buzzers
      digitalWrite(PIN_BUZZER, HIGH);
      tone(PIN_BUZZER, 1200); // 1.2 kHz tone for passive buzzers
    } else {
      silenceBuzzer();
    }
  }
}

void silenceBuzzer() {
  digitalWrite(PIN_BUZZER, LOW);
  noTone(PIN_BUZZER);
  buzzerPulseState = false;
}
