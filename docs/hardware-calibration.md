# WaveGuard Hardware Calibration & Demo Guide (Role C)

This guide documents the reference calibration and 3-minute demo reset procedure for the physical shoreline node (`LUDINGTON-01`).

---

## 1. Ultrasonic Sensor Calibration

The HC-SR04 ultrasonic sensor measures the round-trip flight time of 40 kHz acoustic sound bursts:

$$\text{Distance (cm)} = \frac{\text{Echo Duration (µs)} \times 0.0343}{2}$$

The backend derives the physical water level using a baseline reference distance:

$$\text{water\_level\_cm} = \text{reference\_distance\_cm} - \text{measured\_distance\_cm}$$

### Step-by-Step Calibration
1. **Empty / Baseline Level:** 
   * Fill your water tray with ~2 to 3 cm of calm baseline water.
   * Secure the sensor mount directly above the water.
   * Check the raw distance output in the Arduino Serial Monitor at 115200 baud:
     ```text
     READING,1791043200,18.50,0.95
     ```
   * Set `REFERENCE_DISTANCE_CM=20.0` in your backend `.env` (or match your measured calm distance plus 2.0 cm).
2. **Quality Score Verification:**
   * Sensor quality reads **0.95** when surface echoes return within physical tray bounds (2 cm to 60 cm).
   * If quality drops to **0.00**, check that the sensor is pointing perpendicular to the water without tilt.

---

## 2. Fast 3-Minute Hackathon Demo Procedure

To repeat the demonstration smoothly for judges:

### Step 1: Baseline Safe State (0:00 - 0:45)
* Keep water calm.
* Arduino sends steady readings (~18 cm).
* Green LED is illuminated on the breadboard.
* Dashboard shows `LUDINGTON-01` at baseline water level with `SAFE` status.

### Step 2: Localized Wave / Disturbance (0:45 - 1:30)
* Gently agitate the water in the tray using your hand or a small block.
* Distance fluctuates between 14 cm and 22 cm.
* Dashboard marks a single-node anomaly and triggers `WATCH` mode.
* The physical **Yellow LED** turns ON, Green turns OFF.

### Step 3: Full Seiche / Surge Simulation (1:30 - 2:30)
* Trigger the multi-node `seiche` scenario from the frontend controls (or press a surge displacement).
* As physical water waves oscillate and correlate with simulated nodes (`MUSKEGON-02` and `HOLLAND-03`), the backend escalates to `WARNING`.
* The physical **Red LED** turns ON and the **Piezo Buzzer pulses an audible emergency siren**.
* IBM watsonx Granite displays the emergency incident report and public alert text.

### Step 4: Reset (2:30 - 3:00)
* Press the **Normal** scenario button on the dashboard or let the water settle.
* Backend issues `STATE,SAFE\n`.
* Red LED and buzzer extinguish; Green LED illuminates.
* Ready for the next judge!
