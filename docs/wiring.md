# WaveGuard Hardware Wiring Guide (Role C)

This document provides the exact pin connections, resistor values, and breadboard wiring layout for the **WaveGuard Physical Shoreline Node** (`LUDINGTON-01`) using an **Arduino Uno Starter Kit**.

---

## 1. Components Checklist

| Component | Quantity | Purpose |
| :--- | :--- | :--- |
| **Arduino Uno** | 1 | Microcontroller board |
| **HC-SR04 Ultrasonic Sensor** | 1 | Water surface distance measurement |
| **Green LED** | 1 | `SAFE` normal shoreline state indicator |
| **Yellow LED** | 1 | `WATCH` localized surge/anomaly indicator |
| **Red LED** | 1 | `WARNING` critical seiche/surge alert indicator |
| **220Ω - 330Ω Resistors** | 3 | Current limiting for LEDs |
| **Piezo Buzzer** | 1 | Audible pulsing siren during `WARNING` state |
| **Half or Full Breadboard** | 1 | Circuit prototyping |
| **Jumper Wires (M-M, M-F)** | ~12 | Connections |
| **Water Tray / Container** | 1 | Demo water basin |

---

## 2. Arduino Uno Pin Assignment Table

| Component Pin | Arduino Uno Pin | Wire Type | Notes |
| :--- | :--- | :--- | :--- |
| **HC-SR04 VCC** | `5V` | Jumper to 5V rail | Ultrasonic power supply |
| **HC-SR04 GND** | `GND` | Jumper to GND rail | Ground |
| **HC-SR04 TRIG** | `Digital 9` | Direct pin connection | 10µs trigger pulse output |
| **HC-SR04 ECHO** | `Digital 10` | Direct pin connection | Pulse-width echo input |
| **Green LED Anode (+)** | `Digital 4` | Via 220Ω resistor | Turns ON for `STATE,SAFE` |
| **Green LED Cathode (-)** | `GND` | Direct to GND rail | Flat edge / short leg |
| **Yellow LED Anode (+)** | `Digital 5` | Via 220Ω resistor | Turns ON for `STATE,WATCH` |
| **Yellow LED Cathode (-)** | `GND` | Direct to GND rail | Flat edge / short leg |
| **Red LED Anode (+)** | `Digital 6` | Via 220Ω resistor | Solid for `STATE,WARNING`, flashing for `STATE,SURGE` |
| **Red LED Cathode (-)** | `GND` | Direct to GND rail | Flat edge / short leg |
| **Piezo Buzzer (+)** | `Digital 7` | Direct pin connection | Positive leg (or red wire) |
| **Piezo Buzzer (-)** | `GND` | Direct to GND rail | Negative leg |

> [!NOTE]
> Serial communication uses the default USB port at **115,200 baud** (Arduino pins 0 and 1 are left free).

---

## 3. Circuit Schematic / ASCII Breadboard Layout

```text
               +--------------------------------------+
               |             ARDUINO UNO              |
               |                                      |
               |   5V   GND   D4   D5   D6   D7   D9  D10 |
               +---|-----|-----|----|----|----|---|---|---+
                   |     |     |    |    |    |   |   |
  =================|=====|=====|====|====|====|===|===|==========
  BREADBOARD POWER RAILS:
  [ 5V Rail (+) ] <+
  [ GND Rail (-) ] <-----+
                         |
  HC-SR04 ULTRASONIC:    |
    VCC  ----------------+ (5V Rail)
    GND  ----------------+ (GND Rail)
    TRIG ---------------------------------------------+ (D9)
    ECHO -------------------------------------------------+ (D10)

  LEDS (Current-limited):
    GREEN  LED:  (D4) ----[ 220Ω Resistor ]---->|----+ (GND Rail)
    YELLOW LED:  (D5) ----[ 220Ω Resistor ]---->|----+ (GND Rail)
    RED    LED:  (D6) ----[ 220Ω Resistor ]---->|----+ (GND Rail)

  PIEZO BUZZER:
    BUZZER (+):  (D7) -------------------------[+]
    BUZZER (-):  ------------------------------[-]----+ (GND Rail)
  ================================================================
```

---

## 4. Physical Water Tray Mounting Instructions

1. **Mounting Height:** Position the HC-SR04 sensor **18 to 22 cm** directly above the flat base of the water tray or container.
2. **Orientation:** The two ultrasonic transducer "eyes" must point **straight down perpendicular** to the water surface to ensure sound waves reflect back without scattering.
3. **Splash Protection:** Keep the breadboard, Arduino Uno board, and resistors outside the container or raised on a dry stand. Only the sensor face should face the water.
4. **Reference Distance:** 
   The backend default reference distance is **20.0 cm**:
   $$\text{Water Level (cm)} = \text{Reference Distance (20.0 cm)} - \text{Measured Distance (cm)}$$
   * When the tray has baseline calm water (~15 cm from sensor), the water level reads **+5.0 cm** (`SAFE`).
   * When water surges or a wave is created (~8 cm from sensor), the water level rises to **+12.0 cm** (`WARNING`).

---

## 5. Quick Hardware Smoke Test

1. Connect the Arduino Uno to your laptop via USB cable.
2. Open the **Arduino IDE** and select `Tools -> Board -> Arduino Uno` and `Tools -> Port -> /dev/cu.usbmodem...`.
3. Upload `arduino/waveguard_node/waveguard_node.ino`.
4. Open the **Serial Monitor** at **115200 baud**.
5. You should see continuous output formatted as:
   ```text
   READING,1791043200,16.42,0.95
   READING,1791043201,16.40,0.95
   ```
6. Type the following test commands into the Serial Monitor input bar and press Enter:
   * `STATE,WATCH` $\rightarrow$ Green turns off, Yellow turns ON.
   * `STATE,WARNING` $\rightarrow$ Yellow turns off, Red turns ON, and Buzzer pulses!
   * `STATE,SURGE` $\rightarrow$ Red FLASHES in time with the pulsing buzzer (sudden-surge warning).
   * `STATE,SAFE` $\rightarrow$ Red turns off, Buzzer stops, Green turns ON.
