# 🛰️ StellarSense Aerospace Systems Engineering & Architecture Specification

**System:** StellarSense Miniature Satellite Health Monitor & Ground Station Telemetry System  
**Document Classification:** Spacecraft Avionics, Digital Signal Processing & Systems Engineering Specification  
**Standard Compliance:** ECSS-E-ST-50C (Space Engineering: Communications) & NASA-STD-8739.8 (Software Assurance)  
**Target Hardware:** Dual ESP32-WROOM-32 (240 MHz Dual-Core Xtensa LX6), Semtech SX1278 (Ra-02 433 MHz LoRa)  
**Revision:** 2.0.0-RELEASE  

---

## 1. Executive Architecture & Mission Profile

StellarSense is a high-reliability, fault-tolerant health monitoring and telemetry avionics subsystem designed for CubeSats (1U–3U) and SmallSats operating in Low Earth Orbit (LEO).

During orbital flight, spacecraft endure extreme thermal cycles ($-40^\circ\text{C}$ in eclipse to $+85^\circ\text{C}$ in direct solar exposure), severe structural vibrations from reaction wheel imbalances, and high-energy single-event upsets (SEUs). Because ground contact windows in LEO typically last only 5 to 10 minutes per pass, the satellite flight computer must execute **autonomous, real-time Fault Detection, Isolation, and Recovery (FDIR)** on orbit without waiting for ground telecommand intervention.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        STELLARSENSE END-TO-END SYSTEM TOPOLOGY                         │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                    SATELLITE ON-BOARD FLIGHT COMPUTER (OBC)                      │  │
│  │                                                                                  │  │
│  │   +-------------------------+  I2C Fast Mode (400kHz)  +---------------------+   │  │
│  │   | INA219 Power Bus (0x40) | <======================> | MPU-6050 #1 (0x68)  |   │  │
│  │   | 0-26V Voltage / Current |                          | Vib DSP (AD0->GND)  |   │  │
│  │   +-------------------------+                          +---------------------+   │  │
│  │   +-------------------------+                          +---------------------+   │  │
│  │   | SSD1306 OLED HUD (0x3C) |                          | MPU-6050 #2 (0x69)  |   │  │
│  │   | 128x64 Avionics Matrix  |                          | ADCS (AD0->3.3V)    |   │  │
│  │   +-------------------------+                          +---------------------+   │  │
│  │                                                                                  │  │
│  │   +-------------------------+  1-Wire Digital (GPIO 4) +---------------------+   │  │
│  │   | DS18B20 Thermal Probe   | -----------------------> | Status LEDs & Siren |   │  │
│  │   | 1Hz Decoupled Polling   |                          | D25, D32, D33, D13  |   │  │
│  │   +-------------------------+                          +---------------------+   │  │
│  │                                                                                  │  │
│  │   +--------------------------------------------------------------------------+   │  │
│  │   | FreeRTOS Core 1: Sensor DSP Engine (True RMS) & FDIR Hysteresis Engine   |   │  │
│  │   | FreeRTOS Core 0: LoRa TX Queue Consumer & Non-Blocking Downlink Handler  |   │  │
│  │   +--------------------------------------------------------------------------+   │  │
│  │                                       │ (SPI Bus: D18, D19, D23, D27, D14, D26)  │  │
│  │                                       ▼                                          │  │
│  │                        [Ra-02 SX1278 LoRa 433 MHz Transceiver]                   │  │
│  └───────────────────────────────────────┬──────────────────────────────────────────┘  │
│                                          │                                             │
│                                          ▼ 433.0 MHz LoRa RF Carrier                   │
│                                            (SF7, BW 125kHz, CR 4/5, Sync 0xF3, CRC)    │
│                                          │                                             │
│  ┌───────────────────────────────────────┴──────────────────────────────────────────┐  │
│  │                         GROUND STATION RECEIVER UNIT                             │  │
│  │                                                                                  │  │
│  │   [Ra-02 SX1278 433 MHz Receiver]                                                │  │
│  │          │ SPI Interface                                                         │  │
│  │   [ESP32 Ground Station Processor]                                               │  │
│  │          ├── Hardware CRC Verification & Packet Demodulation                     │  │
│  │          ├── RF Link Metric Injection (RSSI, SNR, rx_count, dropped_pkts)        │  │
│  │          ├── 40ms Pulse-Stretched Visual RX Activity LED (GPIO 2)                │  │
│  │          └── Bidirectional Telecommand Ingestion & LoRa Uplink                   │  │
│  └───────────────────────────────────────┬──────────────────────────────────────────┘  │
│                                          │                                             │
│                                          ▼ USB Virtual COM Port (115200 Baud, 8N1)     │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                      MISSION CONTROL TELEMETRY DASHBOARD                         │  │
│  │                                                                                  │  │
│  │   ├── W3C Web Serial API Direct Stream Consumer (Zero-Install HTML5/JS)          │  │
│  │   ├── Three.js Interactive 3D Satellite Digital Twin (Attitude & Solar Array)    │  │
│  │   ├── Chart.js 60-Second Rolling Strip Charts (Temp, Power Bus, Vibration RMS)   │  │
│  │   ├── Web Audio Tactical Synthesizer (Master Caution Chime & Warning Siren)      │  │
│  │   ├── Autonomous FDIR Annunciator (EPS, TCS, ADCS, COMMS, Structure Badges)      │  │
│  │   └── RFC-Compliant Blob CSV Flight Exporter & Historical Replay Engine          │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. On-Board Computer (OBC) FreeRTOS Dual-Core Architecture

The ESP32 microcontroller features two independent 32-bit Xtensa LX6 CPU cores operating at $240\text{ MHz}$. StellarSense harnesses this asymmetric multiprocessing (AMP) capability to partition real-time digital signal processing from RF communications.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        ESP32 DUAL-CORE TASK PARTITIONING MATRIX                        │
├────────────────────────────────────┬───────────────────────────────────────────────────┤
│          CORE 1 (APP_CPU)          │                 CORE 0 (PRO_CPU)                  │
│     Real-Time DSP & FDIR Engine    │             RF Communications Engine              │
├────────────────────────────────────┼───────────────────────────────────────────────────┤
│ - Base Task: loop()                │ - Base Task: loraTask()                           │
│ - Execution Rate: 20 Hz (50ms)     │ - Execution Rate: Event-driven / Queue Consumer   │
│ - FreeRTOS Priority: Priority 1    │ - FreeRTOS Priority: Priority 1                   │
│ - Stack Depth: 8192 Bytes          │ - Stack Depth: 4096 Bytes                         │
│ - Watchdog: Hardware TWDT (4s)     │ - Watchdog: Monitored via Task Yields             │
├────────────────────────────────────┴───────────────────────────────────────────────────┤
│                             INTER-CORE SYNCHRONIZATION                                 │
│                                                                                        │
│  Core 1 (Producer)                 FreeRTOS IPC                    Core 0 (Consumer)   │
│ ┌───────────────────┐        ┌───────────────────────┐        ┌───────────────────────┐│
│ │ pushTelemetry()   ├───────>│ QueueHandle_t         ├───────>│ xQueueReceive()       ││
│ │ Non-blocking      │        │ telemetryQueue        │        │ Blocking wait (50ms)  ││
│ │ (timeout = 0)     │        │ Depth = 4 Payloads    │        │ Serializes JSON       ││
│ └───────────────────┘        └───────────────────────┘        │ Transmits LoRa RF     ││
│                                                               └───────────┬───────────┘│
│                                                                           │            │
│  Core 1 (Consumer)                 Atomic Volatile Flags                  │            │
│ ┌───────────────────┐        ┌───────────────────────┐                    │            │
│ │ loop() Checks:    │<───────┤ cmdTareRequested      │<───────────────────┤            │
│ │ - tareAttitude()  │        │ cmdFdirResetRequested │  LoRa.parsePacket()│            │
│ │ - Reset Debounce  │        └───────────────────────┘  Captures Uplink   │            │
│ └───────────────────┘                                   Telecommands       │           │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Core 1 (APP_CPU): Sensor DSP, FDIR & Avionics Loop
- **Deterministic 20 Hz Sampling:** Executes every $50.0\text{ ms}$ driven by non-blocking timestamp scheduling.
- **High-Rate Sensor Polling:** Reads INA219 power bus, MPU-6050 #1 vibration accelerometer, and MPU-6050 #2 attitude gyro/accelerometer.
- **True RMS Vibration DSP:** Applies real-time squared dynamic acceleration filtering.
- **Attitude Sensor Fusion:** Executes complementary filtering for pitch and roll angles.
- **FDIR Evaluation:** Executes dual-threshold hysteresis and 3-sample persistence debouncing.
- **Local HUD & Alarms:** Refreshes 0.96" OLED screen at 5 Hz and updates buzzer/LED annunciators at 10 Hz.

### 2.2 Core 0 (PRO_CPU): Background LoRa RF Transceiver Task
- **Non-Blocking RF Downlink:** Sits in an event loop waiting on `telemetryQueue`. When a new `TelemetryPayload` arrives, Core 0 formats clean JSON into a static buffer and invokes `LoRa.beginPacket()` $\rightarrow$ `LoRa.print()` $\rightarrow$ `LoRa.endPacket()`.
- **Elimination of CPU Freezes:** Because the $220\text{ ms} - 287\text{ ms}$ blocking transmission airtime occurs on Core 0, **Core 1 experiences zero jitter**, maintaining continuous 20 Hz sensor DSP and attitude integration.
- **Uplink Telecommand Capture:** Between downlink transmissions, Core 0 polls `LoRa.parsePacket()`. Incoming commands (`CMD:PING`, `CMD:FDIR_RESET`, `CMD:TARE`, `CMD:RATE`) are decoded and dispatched via atomic flags.

---

## 3. Digital Signal Processing (DSP) Mathematical Formulations

### 3.1 True RMS Structural Vibration Formulation

In spacecraft structural dynamics, solar array deployment, launch acoustics, and reaction wheel degradation generate high-frequency micro-vibrations ($10\text{ Hz} - 100\text{ Hz}$).

#### The Mathematical Flaw in Naive Vibration Metrics:
The baseline firmware implemented dynamic acceleration extraction followed by a linear Exponential Moving Average (EMA):
$$|\Delta \vec{a}[k]| = \frac{\sqrt{(a_x[k]-a_x[k-1])^2 + (a_y[k]-a_y[k-1])^2 + (a_z[k]-a_z[k-1])^2}}{g_0}$$
$$\text{LinearEMA}[k] = (1 - \alpha) \cdot \text{LinearEMA}[k-1] + \alpha \cdot |\Delta \vec{a}[k]|$$

This naive formulation computes the **Mean Absolute Dynamic Deviation (MAD)**, NOT the Root Mean Square (RMS).
For a sinusoidal vibration $a(t) = A \sin(\omega t)$:
- $\text{True RMS} = \frac{A}{\sqrt{2}} \approx 0.7071 A$
- $\text{Mean Absolute} = \frac{2}{\pi} A \approx 0.6366 A$

The baseline algorithm introduced a **systematic 10.0% under-reporting of structural vibration energy**, creating a severe flight risk where critical flutter resonance could occur without triggering FDIR alarms!

#### StellarSense True RMS Mathematical Derivation:
StellarSense implements an exact discrete True RMS estimator:
1. **Dynamic Acceleration Vector Difference:**
   $$\Delta a_x[k] = a_x[k] - a_x[k-1]$$
   $$\Delta a_y[k] = a_y[k] - a_y[k-1]$$
   $$\Delta a_z[k] = a_z[k] - a_z[k-1]$$
   $$\text{dynamicG}[k] = \frac{\sqrt{\Delta a_x[k]^2 + \Delta a_y[k]^2 + \Delta a_z[k]^2}}{9.80665\text{ m/s}^2}$$
   *Note: Taking vector differences intrinsically eliminates static $1.0\text{g}$ Earth gravity, isolating purely dynamic structural oscillations.*

2. **Exponential Moving Average on Squared Energy:**
   $$\text{MeanSquare}[k] = (1 - \alpha) \cdot \text{MeanSquare}[k-1] + \alpha \cdot (\text{dynamicG}[k])^2$$
   $$\text{where } \alpha = 0.15 \implies \text{EMA time constant } \tau = \frac{\Delta t}{\alpha} = \frac{0.05\text{ s}}{0.15} \approx 0.333\text{ seconds}$$

3. **True RMS Square-Root Extraction:**
   $$\text{Vibration}_{\text{RMS}}[k] = \sqrt{\text{MeanSquare}[k]}$$

This formulation guarantees mathematical equivalence to continuous-time RMS $\sqrt{\frac{1}{T}\int_0^T a^2(t)\,dt}$, providing precise acceleration energy quantification across bench taps, motor jitter, and acoustic resonance.

---

### 3.2 ADCS Complementary Attitude Fusion & Gyroscope Calibration

#### Stationary Zero-Rate Gyroscope Bias Calibration:
Low-cost MEMS gyroscopes exhibit static zero-rate biases (typically $1.5^\circ/\text{s}$ to $6.0^\circ/\text{s}$). Integrating raw uncalibrated rates leads to immediate, continuous attitude drift.

During the 2-second boot initialization, StellarSense takes $N = 100$ stationary samples:
$$\omega_{\text{bias},x} = \frac{1}{N} \sum_{i=1}^N \omega_{\text{raw},x}[i], \quad \omega_{\text{bias},y} = \frac{1}{N} \sum_{i=1}^N \omega_{\text{raw},y}[i]$$

All subsequent runtime angular rate measurements subtract this calibrated bias:
$$\omega_{\text{cal},x}[k] = \omega_{\text{raw},x}[k] - \omega_{\text{bias},x}, \quad \omega_{\text{cal},y}[k] = \omega_{\text{raw},y}[k] - \omega_{\text{bias},y}$$

#### Complementary Attitude Fusion Filter:
1. **Accelerometer Horizon Vector Extraction:**
   $$\theta_{\text{acc}}[k] = \arctan2\left(a_y[k], \sqrt{a_x[k]^2 + a_z[k]^2}\right) \times \frac{180^\circ}{\pi}$$
   $$\phi_{\text{acc}}[k] = \arctan2\left(-a_x[k], a_z[k]\right) \times \frac{180^\circ}{\pi}$$

2. **Complementary Discrete Fusion:**
   $$\theta[k] = \alpha_{\text{att}} \cdot (\theta[k-1] + \omega_{\text{cal},y}[k] \cdot \Delta t) + (1 - \alpha_{\text{att}}) \cdot \theta_{\text{acc}}[k]$$
   $$\phi[k] = \alpha_{\text{att}} \cdot (\phi[k-1] + \omega_{\text{cal},x}[k] \cdot \Delta t) + (1 - \alpha_{\text{att}}) \cdot \phi_{\text{acc}}[k]$$
   $$\text{where } \alpha_{\text{att}} = 0.96 \text{ and } \Delta t = 0.05\text{ s}$$

- **High-Frequency Gyro Integration (96% Weight):** Rejects linear vibration noise and sudden translational accelerations.
- **Low-Frequency Accelerometer Horizon Correction (4% Weight):** Completely prevents long-term numerical gyro drift.

#### Dynamic 3D Tumble Velocity:
$$\omega_{\text{tumble}}[k] = \sqrt{\omega_{\text{cal},x}[k]^2 + \omega_{\text{cal},y}[k]^2 + \omega_{\text{cal},z}[k]^2} \quad [^\circ/\text{s}]$$
Tumble rates exceeding $30.0^\circ/\text{s}$ trigger ADCS anomaly alerts on Mission Control.

---

### 3.3 Decoupled 1-Wire Thermal Conversion State Machine

Maxim DS18B20 digital thermometers require $187.5\text{ ms}$ to complete a 10-bit temperature conversion. Triggering temperature requests in the 50ms DSP loop aborts in-progress ADC conversions on genuine silicon.

StellarSense decouples thermal sensing into a deterministic 1 Hz asynchronous state machine:
```
Time t = 0 ms:     tempSensor.requestTemperatures();  // Initiates 187.5ms conversion
                   tempConversionPending = true;
Time t = 200 ms:   float readT = tempSensor.getTempCByIndex(0); // Harvests completed ADC
                   tempConversionPending = false;
                   telemetryTemp = 0.8 * telemetryTemp + 0.2 * readT; // Smooths reading
Time t = 1000 ms:  Repeat cycle...
```

- **Runtime Disconnect Defense:** If the probe jumper wire wiggles loose, `getTempCByIndex(0)` returns $-127.0^\circ\text{C}$ (`DEVICE_DISCONNECTED_C`).
- StellarSense maintains a consecutive error counter: after 3 consecutive $-127^\circ\text{C}$ readings, `statusTemp` is cleared to `false`, isolating the sensor and engaging fallback estimation without freezing or crashing the OBC.

---

## 4. Autonomous FDIR State Machine Architecture

StellarSense implements a three-tier hierarchical Fault Detection, Isolation, and Recovery (FDIR) state machine.

```
       ┌────────────────────────────────────────────────────────┐
       │                 LEVEL 0: STATE_NOMINAL                 │
       │    Green LED ON | Buzzer Silent | OLED [NOMINAL]       │
       └──────────────┬──────────────────────────▲──────────────┘
                      │                          │
        Breach >= 3   │                          │ All Clear <= Clear Thresholds
        Frames        │                          │ (0.8°C, 0.10V, 0.05g Deadbands)
                      ▼                          │
       ┌─────────────────────────────────────────┴──────────────┐
       │                 LEVEL 1: STATE_CAUTION                 │
       │   Yellow LED ON | 100ms Chirp / 800ms | OLED [WARN!!]  │
       └──────────────┬──────────────────────────▲──────────────┘
                      │                          │
        Critical >= 3 │                          │ Critical Cleared <= Clear Bounds
        Frames        │                          │ (1.0°C, 0.15V, 0.12g Deadbands)
                      ▼                          │
       ┌─────────────────────────────────────────┴──────────────┐
       │                 LEVEL 2: STATE_CRITICAL                │
       │    Red LED 10Hz | 10Hz Siren Pulse | OLED [FAULT!]     │
       └────────────────────────────────────────────────────────┘
```

### 4.1 Dual-Threshold Deadband Hysteresis Specification

To prevent high-frequency state flutter and log flooding when physical metrics hover near boundary thresholds, StellarSense enforces distinct Assertion and De-Assertion thresholds:

| Subsystem Domain | Metric | Caution Trigger (Assert) | Caution Clear (De-assert) | Critical Trigger (Assert) | Critical Clear (De-assert) | Hysteresis Deadband ($\Delta$) |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **Thermal (TCS)** | Core Temperature ($T$) | $\ge 33.00^\circ\text{C}$ | $\le 32.20^\circ\text{C}$ | $\ge 38.00^\circ\text{C}$ | $\le 37.00^\circ\text{C}$ | $\mathbf{0.80^\circ\text{C} / 1.00^\circ\text{C}}$ |
| **Electrical (EPS)**| Bus Voltage ($V$) | $\le 4.60\text{ V}$ | $\ge 4.70\text{ V}$ | $\le 4.20\text{ V}$ | $\ge 4.35\text{ V}$ | $\mathbf{0.10\text{ V} / 0.15\text{ V}}$ |
| **Electrical (EPS)**| Bus Current ($I$) | $\ge 650.0\text{ mA}$ | $\le 550.0\text{ mA}$ | $\ge 950.0\text{ mA}$ | $\le 800.0\text{ mA}$ | $\mathbf{100.0\text{ mA} / 150.0\text{ mA}}$ |
| **Structural (PLD)**| Vibration RMS ($A_{\text{vib}}$)| $\ge 0.250\text{ g}$ | $\le 0.200\text{ g}$ | $\ge 0.700\text{ g}$ | $\le 0.580\text{ g}$ | $\mathbf{0.050\text{ g} / 0.120\text{ g}}$ |

### 4.2 3-Sample Persistence Debounce Filtering
Single-sample noise spikes (such as an ADC quantization glitch or breadboard electrostatic transient) are suppressed:
$$\text{Persistence Filter: Requires } N \ge 3 \text{ consecutive frames (}150\text{ ms at }20\text{ Hz)} \text{ in breach before escalating state.}$$

If a transient glitch breaches a threshold for only 1 or 2 frames, the persistence accumulator resets to zero without triggering audible alarms or logging false incidents.

### 4.3 Telemetry Sensor Health Diagnostic Bitmask (`hw`)
The flight computer encodes physical sensor availability into a 1-byte telemetry bitmask:
```
Bit 0 (0x01): OLED SSD1306 Operational
Bit 1 (0x02): INA219 EPS Power Monitor Operational
Bit 2 (0x04): MPU-6050 #1 Vibration IMU Operational
Bit 3 (0x08): MPU-6050 #2 ADCS IMU Operational
Bit 4 (0x10): DS18B20 Temperature Probe Operational
Bit 5 (0x20): Ra-02 SX1278 LoRa Transceiver Operational
```
When all systems are operational, `hw = 63` (`0x3F`). Disconnecting a sensor immediately flags its bit as `0`, allowing the Mission Control HUD to render instant subsystem health diagnostic matrices.

---

## 5. RF Link Budget & Communications Engineering

### 5.1 Semtech SX1278 Ra-02 Configuration

| Parameter | Configuration | Engineering Unit | Value |
|:---|:---|:---:|:---:|
| **Carrier Frequency ($f_c$)** | ISM Sub-GHz | MHz | 433.000 |
| **RF Output Power ($P_{TX}$)** | PA_BOOST Pin | dBm (mW) | +17.0 dBm (50 mW) |
| **Modulation Bandwidth ($BW$)** | Standard LoRa | kHz | 125.0 |
| **Spreading Factor ($SF$)** | 128 chips/symbol | - | SF7 |
| **Coding Rate ($CR$)** | Forward Error Correction | - | 4/5 (20% Overhead) |
| **Preamble Length** | Synchronization symbols | symbols | 8 |
| **Sync Word** | Private Network Key | hex | 0xF3 |
| **Hardware CRC** | PHY-level packet check | boolean | ENABLED |

### 5.2 Mathematical Link Budget Formulation

The received signal power $P_{RX}$ is governed by the Friis Transmission Equation:
$$P_{RX} = P_{TX} + G_{TX} + G_{RX} - \text{FSPL} - L_{\text{misc}}$$

Where:
- Transmit Power $P_{TX} = +17.0\text{ dBm}$
- Transmit Antenna Gain $G_{TX} = +2.15\text{ dBi}$ (Quarter-wave resonant monopole)
- Receive Antenna Gain $G_{RX} = +2.15\text{ dBi}$
- Miscellaneous Losses $L_{\text{misc}} \approx 2.0\text{ dB}$ (Cable, connector, and breadboard mismatch)

Free-Space Path Loss ($\text{FSPL}$):
$$\text{FSPL}(\text{dB}) = 20 \log_{10}(d) + 20 \log_{10}(f_{\text{MHz}}) - 27.55$$
$$\text{At } 433\text{ MHz}: \quad \text{FSPL}(d) = 20 \log_{10}(d) + 20 \log_{10}(433) - 27.55 = 20 \log_{10}(d) + 25.18\text{ dB}$$

#### Receiver Thermal Noise Floor ($N_0$):
$$N_0 = -174\text{ dBm/Hz} + 10 \log_{10}(BW) + NF$$
$$N_0 = -174 + 10 \log_{10}(125000) + 6.0\text{ dB (Typical SX1278 Noise Figure)} = -117.03\text{ dBm}$$

#### Receiver Sensitivity ($S$):
For LoRa SF7, the Semtech modem demodulates signals with a Signal-to-Noise Ratio (SNR) down to $SNR_{\text{limit}} = -7.5\text{ dB}$:
$$S = N_0 + SNR_{\text{limit}} = -117.03\text{ dBm} + (-7.5\text{ dB}) = -124.53\text{ dBm}$$

#### Link Margin Analysis Across Operational Distances:

$$\text{Link Margin } M = P_{RX} - S$$

| Distance ($d$) | Operational Context | Path Loss ($\text{FSPL}$) | Received Power ($P_{RX}$) | Receiver Sensitivity ($S$) | Link Margin ($M$) | Link Reliability Status |
|:---:|:---|:---:|:---:|:---:|:---:|:---|
| **10 m** | Hackathon Demo Booth | 45.18 dB | -25.88 dBm | -124.53 dBm | **+98.65 dB** | **Rock Solid (Zero Bit Errors)** |
| **100 m** | Campus / Indoor Hall | 65.18 dB | -45.88 dBm | -124.53 dBm | **+78.65 dB** | **Full Wall Penetration** |
| **1.0 km** | Urban Line-of-Sight | 85.18 dB | -65.88 dBm | -124.53 dBm | **+58.65 dB** | **High Margin** |
| **10.0 km**| Horizon / Rural Link | 105.18 dB| -85.88 dBm | -124.53 dBm | **+38.65 dB** | **Operational with Standard Antenna** |
| **50.0 km**| LEO CubeSat Nadir Pass| 119.16 dB| -99.86 dBm | -124.53 dBm | **+24.67 dB** | **Spacecraft Downlink Compliant** |

---

## 6. Spacecraft Failure-Modes & Effects Analysis (FMEA)

The Failure Modes and Effects Analysis matrix below outlines flight anomalies, severity ratings, onboard autonomous mitigations, and ground recovery actions:

| Failure Mode ID | Subsystem / Component | Potential Failure Mechanism | Severity (Catastrophic / Critical / Minor) | Autonomous Onboard Detection & Mitigation | Ground Station / Mission Control Action |
|:---|:---|:---|:---:|:---|:---|
| **FMEA-01** | $I^2C$ Bus | Slave device locks SDA line LOW during clock stretch glitch. | **Critical** | `Wire.setTimeOut(25)` triggers; OBC aborts transaction and executes 9-clock SCL pulse bus clearance routine. | Telemetry records `hw` bitmask drop; dashboard logs $I^2C$ bus recovery event. |
| **FMEA-02** | TCS / Temp | DS18B20 jumper wire wiggles loose during mechanical vibration. | **Minor** | Consecutive error counter detects $-127.0^\circ\text{C}$; clears `statusTemp = false`, isolates probe, injects synthetic fallback. | Dashboard flags `TCS: DEGRADED` badge; prompt crew to inspect physical probe wiring. |
| **FMEA-03** | EPS / Power | INA219 jumper disconnects or supply rail brownout occurs. | **Critical** | FDIR differentiates between true zero voltage (0.00V) and bus disconnection before triggering brownout alarm. | Dashboard annunciates `EPS: CRITICAL` if voltage $< 4.20\text{V}$; logs battery drain profile. |
| **FMEA-04** | COMMS / RF | RF burst interference flips bit in LoRa packet header or payload. | **Minor** | SX1278 Hardware CRC catches parity violation at PHY layer; modem drops corrupted frame. | Ground Station increments `totalPacketsDropped` and computes rolling packet loss %. |
| **FMEA-05** | ADCS / IMU | MPU-6050 static gyro bias accumulates integration error. | **Minor** | 100-sample stationary boot calibration subtracts bias; 4% accelerometer horizon vector continuously pins drift. | Operator sends `CMD:TARE` telecommand to instantly re-zero attitude reference frame. |
| **FMEA-06** | Avionics / MCU | Single-Event Upset (SEU) traps CPU in infinite deadlock loop. | **Critical** | Hardware Task Watchdog Timer (`esp_task_wdt`) times out after 4.0 seconds; forces automatic hardware reboot. | Ground Station detects reboot banner `status: READY`; telemetry packet counter resets to 1. |
| **FMEA-07** | FDIR / Health | Finger heat or ambient draft hovers temperature at $33.0^\circ\text{C}$. | **Minor** | Dual deadband hysteresis ($0.8^\circ\text{C}$) and 3-sample persistence suppress state chattering and alarm flutter. | Dashboard displays steady amber `CAUTION` badge without repeated audio chimes. |
| **FMEA-08** | RF Link | Satellite enters orbital eclipse or passes below ground horizon. | **Critical** | OBC Core 0 non-blocking queue prevents CPU freeze; satellite continues autonomous health monitoring. | Ground Station LOS Watchdog flags `LOSS OF SIGNAL` after 3.0s; auto-recovers upon re-acquisition. |
