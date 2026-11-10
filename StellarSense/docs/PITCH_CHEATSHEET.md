# 🏆 StellarSense — 3-Minute Hackathon Pitch & Defense Runbook

**Event:** Space Tech / Aerospace IoT Hackathon  
**Target Audience:** Hackathon Judges, Aerospace Systems Engineers & Industry Evaluators  
**System Under Test:** StellarSense Autonomous CubeSat Health Monitor & Ground Station Telemetry System  
**Presentation Time:** Strict 3 Minutes (180 Seconds) + 2 Minutes Q&A Defense  
**Revision:** 2.0.0-RELEASE  

---

## 1. Golden Rules of Live Hackathon Demonstrations

1. **Keep Both Units Visible:** Place the Satellite Flight Computer on the left and the Ground Station Receiver next to your laptop on the right.
2. **Never Show Code First; Show Physical Reflexes First:** Judges award top marks for physical hardware-in-the-loop interaction, responsive UI twins, and autonomous fail-safe behavior.
3. **Speak in Aerospace Terminology:** Use terms like *LEO pass*, *FDIR*, *C&DH*, *ADCS complementary fusion*, *True RMS vibration*, *link budget*, and *SEU watchdog*.
4. **Always Have the 1-Click Simulation Mode Ready:** If someone trips over a USB cable or RF interference spikes in the convention center, one click on `[SIMULATION PASS]` continues the entire demo without skipping a beat.

---

## 2. Timed 3-Minute Winning Pitch Script

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        3-MINUTE PRESENTATION TIMELINE                                  │
├─────────────────┬──────────────────────────────────┬───────────────────────────────────┤
│ Timestamp       │ Presentation Focus               │ Hardware & Dashboard Action       │
├─────────────────┼──────────────────────────────────┼───────────────────────────────────┤
│ [0:00 - 0:40]   │ The LEO Problem & Hook           │ Gesture to physical satellite OBC │
│ [0:40 - 1:15]   │ Architecture & 3D Digital Twin   │ Pick up satellite, tilt physical  │
│ [1:15 - 2:15]   │ Live Chaos & Fault Injections    │ Heat probe, knock board, spin it  │
│ [2:15 - 2:40]   │ Self-Healing & Telecommands      │ Auto-recovery & CMD:TARE demo     │
│ [2:40 - 3:00]   │ Flight Software Polish & Close   │ Show CSV export & test readiness  │
└─────────────────┴──────────────────────────────────┴───────────────────────────────────┘
```

---

### [0:00 - 0:40] The Aerospace Problem & The Hook

> *"Good morning, judges! In modern CubeSat constellations, hardware failure in Low Earth Orbit means immediate loss of mission. Spacecraft endure brutal thermal swings between solar exposure and eclipse, severe micro-vibrations from reaction wheels, and electrical brownout hazards.*
>
> *Because ground station contact passes in LEO last only 5 to 10 minutes, satellites cannot wait for ground control to tell them something is wrong. They require **autonomous onboard reflexes**.*
>
> *This is **StellarSense** — an industry-grade autonomous miniature satellite health monitoring and ground telemetry system featuring dual-core FreeRTOS architecture, digital signal processing, and a multi-tier Fault Detection, Isolation, and Recovery (FDIR) engine."*

---

### [0:40 - 1:15] Architecture & Real-Time 3D Digital Twin

*(Point to the two hardware breadboards on the table)*

> *"On my left is our Satellite Flight Computer, powered by a dual-core ESP32. It integrates 5 physical sensor nodes across thermal, power, and structural dynamics, downlinking telemetry over a 433 MHz LoRa radio link with hardware CRC.*
>
> *On my right is our Ground Station receiver, streaming telemetry into our Mission Control workstation over the zero-install W3C Web Serial API.*
>
> *(Pick up the physical Satellite Unit in your hand and tilt it in the air)*
>
> *Notice our dashboard: this is a **real-time 3D Satellite Digital Twin** rendered with Three.js. As I pitch and roll the physical spacecraft in my hand, our secondary MPU-6050 runs a complementary sensor fusion filter, combining 3-axis gyro rates with accelerometer horizon vectors to deliver sub-50ms orientation tracking with zero drift. Our rolling strip charts continuously track core temperature, dual-axis power, and dynamic vibration."*

---

### [1:15 - 2:15] Live Physical Fault Injection (The Climax)

> *"Now, judges, let’s test the autonomous reflexes of the satellite flight computer under three simultaneous orbital emergencies.*

#### 1. Thermal Excursion (TCS Anomaly):
*(Firmly pinch the DS18B20 metal temperature probe between your thumb and index finger)*
> *"Watch our core temperature rise as we simulate direct solar exposure. As my body heat crosses 33°C, the flight computer instantly asserts a **Master Caution**: the onboard Yellow LED illuminates, the OLED flags `CAUTION`, and our Mission Control dashboard chimes with an audible amber caution banner.*
>
> *(Hold the probe tighter until temperature approaches 38°C)*
>
> *If temperature exceeds 38°C, the satellite escalates to a **Critical Emergency**: the Red LED flashes at 10 Hz, the high-decibel piezo siren pulses, and ground control receives an emergency telemetry beacon with an automated incident timeline entry.*

#### 2. Structural Flutter / Vibration Anomaly:
*(Firmly knock or tap the breadboard table with your knuckles)*
> *"Next, watch structural dynamics: our primary MPU-6050 runs a discrete True RMS digital signal processing algorithm, filtering out static 1G gravity to measure dynamic acceleration energy. A hard tap spikes vibration above 0.25g, instantly triggering acoustic flutter alerts on the dashboard.*

#### 3. Attitude Tip-Off & Tumble Anomaly (ADCS Anomaly):
*(Rapidly spin the satellite unit in your hand)*
> *"Finally, if the satellite experiences tip-off tumble during separation, our dynamic tumble velocity meter spikes above 30 degrees per second, flagging an uncontrolled attitude state."*

---

### [2:15 - 2:40] Autonomous Self-Healing & Gemma 4 Flight Director

*(Release the temperature probe and set the satellite flat on the table)*

> *"Notice what happens now: **Autonomous Self-Healing** powered by our **Gemma 4 Autonomous Flight Director**.*
>
> *Our system doesn't just display data — it integrates an open-weight **Gemma 4 Small Language Model Agent** adhering to the **Agent Skill Open Standard v1.0** (`satellite-fdir`).
>
> *(Point to the Gemma 4 Flight Copilot HUD on the dashboard)*
>
> *Gemma 4 continuously digests multi-sensor telemetry through a custom sliding-window model harness, extracting real-time temporal derivatives ($dT/dt, dV/dt, dI/dt$). When our thermal or power metrics fluctuate, Gemma 4 performs an aerospace **Failure Mode and Effects Analysis (FMEA)**, distinguishing external heat from electrical shorts.
>
> *Even more powerful: **Gemma 4 takes real-world action via tools**. Watch the action feed: Gemma 4 autonomously issues a `CMD:RATE:1200` telecommand to throttle the radio transmitter and conserve bus power during thermal stress, or `CMD:TARE` to re-zero the gyroscope when tumbling exceeds limits.*
>
> *As the probe cools below 32.2°C and vibrations settle below 0.20g, our dual-threshold deadband hysteresis clears: the Ground Station buzzer silences, the Green Nominal LED engages, and Gemma 4 logs full mission recovery."*

---

### [2:40 - 3:00] Aerospace Robustness & Closing

> *"StellarSense is engineered for real spaceflight robustness:
> - Disconnecting an $I^2C$ sensor executes an autonomous 9-clock bus clearance without hanging the MCU.
> - Transmitting LoRa packets runs on Core 0 FreeRTOS, eliminating blocking CPU freezes.
> - Ground alerts are driven by a single 5V active buzzer on Ground Station `D13` with transistor isolation.
> - Gemma 4 edge inference runs 100% locally on the laptop without internet access.
> - And our entire architecture is validated by an automated mission assurance test suite with **87/87 tests passing (100% pass rate across 6 tiers)**.
>
> StellarSense bridges physical embedded aerospace hardware with cutting-edge open-weight AI agents, turning miniature satellites from fragile experiments into resilient, self-healing orbital platforms. Thank you — we welcome your questions!"*

---

## 3. Physical Demo Quick Reference Cue Sheet

| Timing | Physical Action | Onboard Satellite Reaction | Mission Control Dashboard Reaction |
|:---:|:---|:---|:---|
| **0:45** | Pick up and tilt Satellite Unit. | OLED reflects attitude angles; complementary filter updates. | 3D Three.js CubeSat smoothly tilts in space matching your hand. |
| **1:20** | Pinch DS18B20 probe between fingers. | Temperature exceeds 33.0°C; **Yellow LED turns ON**; OLED displays `[WARN!!]`. | Ground Station buzzer chirps; Thermal chart rises; Master Caution banner flashes amber; two-tone chime sounds. |
| **1:45** | Squeeze probe tighter ($> 38.0^\circ\text{C}$). | **Red LED flashes @ 10 Hz**; OLED displays `[FAULT!]`. | Ground Station buzzer sounds loud alternating alarm siren; Master Warning flashes red; incident log records critical event. |
| **1:55** | Knock / tap table firmly. | DSP computes dynamic True RMS energy ($> 0.25\text{g}$). | Vibration chart trace turns amber/red; structural gauge spikes. |
| **2:05** | Rotate satellite rapidly in hand. | Gyroscope registers $> 30.0^\circ/\text{s}$ angular rate. | Dynamic tumble velocity readout turns red; ADCS badge flags tumble. |
| **2:20** | Release probe & let it cool flat on table. | Temperature falls $< 32.2^\circ\text{C}$; **Green LED illuminates steady**. | Ground Station buzzer silences; Annunciator clears to green; audio silences; log notes `RECOVERY: Subsystems nominal`. |
| **2:35** | Click `[CMD:TARE]` on Dashboard. | Core 0 captures LoRa telecommand; Core 1 zeros pitch and roll. | 3D model re-levels to horizon; pitch/roll gauges reset to 0.0°. |

---

## 4. Judge Q&A Defense Cheat Sheet (Tough Technical Inquiries)

#### Q1: "Why did you use two separate MPU-6050 IMUs instead of combining them into one?"
> **Answer:** *"In aerospace avionics, structural acoustic monitoring and attitude determination operate in fundamentally conflicting dynamic domains.  
> MPU-6050 #1 is dedicated to **high-frequency structural vibration and resonance monitoring**, operating with high-pass filtering to isolate dynamic $g_{\text{RMS}}$ micro-vibrations without gravity bias.  
> MPU-6050 #2 is dedicated to **ADCS attitude determination**, utilizing a complementary sensor fusion filter ($96\%$ gyro integration $+ 4\%$ accelerometer horizon vector) with a 100-sample stationary boot calibration to deliver stable, drift-free pitch and roll angles. Multiplexing both on a single $I^2C$ bus via physical `AD0` pin toggling (`0x68` and `0x69`) provides dual-instrument capability at zero address conflict."*

---

#### Q2: "How does the ESP32 communicate with your web dashboard without a local Node.js or Python backend server?"
> **Answer:** *"We utilize the **W3C Web Serial API** (`navigator.serial`) native to Chromium browsers. It opens an asynchronous, bidirectional, hardware-level UART stream directly to the ESP32 Ground Station @ 115200 baud.  
> This eliminates flaky local server proxies, requires zero user software installation, and is **100% immune to venue Wi-Fi blocks, port restrictions, or captive portals**."*

---

#### Q3: "What prevents the ESP32 from freezing if a sensor disconnects or an $I^2C$ slave hangs the bus?"
> **Answer:** *"Standard Arduino libraries block indefinitely in while loops if an $I^2C$ device holds SDA LOW. StellarSense implements three defensive layers:  
> 1. `Wire.setTimeOut(25)`: Hardware timeout forces an abort if any transaction exceeds 25ms.  
> 2. **Autonomous Bus Clearance:** If a transaction fails, the MCU reconfigures SCL/SDA as GPIOs, generates 9 clock pulses on SCL to flush stuck slave shift registers, issues a STOP condition, and re-initializes the bus.  
> 3. **Graceful Sensor Isolation:** The driver detects disconnects (e.g. DS18B20 returning $-127^\circ\text{C}$), clears its bit in the `hw` telemetry bitmask, injects synthetic fallback estimates, and maintains uninterrupted LoRa downlink."*

---

#### Q4: "Why use 433 MHz LoRa rather than standard 2.4 GHz Wi-Fi or Bluetooth?"
> **Answer:** *"Sub-GHz LoRa (433 MHz) is vastly superior for space-to-ground links:  
> 1. **Path Loss:** Free-space path loss at 433 MHz is approximately **15 dB lower** than 2.4 GHz, yielding over 5 times the operational range for identical transmit power.  
> 2. **Sensitivity:** Chirp Spread Spectrum (CSS) modulation achieves receiver sensitivity down to **-124.5 dBm**, allowing reception even when signals are buried $7.5\text{ dB}$ below the thermal noise floor.  
> 3. **Interference Immunity:** Hackathon venues are saturated with hundreds of Wi-Fi beacons and Bluetooth devices. Our 433 MHz carrier with a private sync word (`0xF3`) provides a completely isolated, interference-free RF link."*

---

#### Q5: "How did you eliminate the blocking LoRa transmission freeze?"
> **Answer:** *"Transmitting a 135-byte JSON frame over LoRa at SF7/125kHz requires approximately $250\text{ ms}$ of RF airtime. Naive sketches freeze the CPU during `LoRa.endPacket()`.  
> We partitioned the OBC firmware using **FreeRTOS dual-core task affinity**:  
> - Core 1 (APP_CPU) runs the deterministic 20 Hz Sensor DSP and FDIR loop with zero delays.  
> - Core 0 (PRO_CPU) runs a dedicated background task (`loraTask`) that receives telemetry from Core 1 via a thread-safe FreeRTOS Queue and handles the blocking RF transmission without stalling sensor sampling or attitude integration."*

---

#### Q6: "Why is your vibration calculation 'True RMS' rather than standard averaging?"
> **Answer:** *"Most hobbyist sketches take an Exponential Moving Average of dynamic acceleration magnitude ($|\Delta \vec{a}|$). Mathematically, that computes the **Mean Absolute Dynamic Deviation (MAD)**, not RMS.  
> For sinusoidal structural vibrations, MAD yields $\frac{2}{\pi} A \approx 0.637 A$, whereas True RMS is $\frac{1}{\sqrt{2}} A \approx 0.707 A$. The naive approach systematically **under-reports vibration energy by ~10%**, risking undetected flutter.  
> StellarSense averages the **squared** dynamic acceleration ($\text{EMA}(|\Delta \vec{a}|^2)$) and extracts the square root: $\text{RMS} = \sqrt{\text{MeanSquare}}$. This strictly matches the ISO and ECSS mechanical vibration definition."*

---

#### Q7: "How do you avoid alarm fluttering when temperature is right on the 33°C boundary?"
> **Answer:** *"We implemented **dual-threshold deadband hysteresis and 3-sample persistence debouncing**:  
> - A Caution alert triggers at $\ge 33.0^\circ\text{C}$, but will NOT clear until temperature drops below $32.2^\circ\text{C}$ (a $0.8^\circ\text{C}$ deadband).  
> - Furthermore, the condition must persist for $\ge 3$ consecutive frames ($150\text{ ms}$).  
> This completely eliminates the 20 Hz relay flutter and log spamming common in single-threshold implementations."*

---

#### Q8: "What if there is severe RF interference or a broken wire during judging?"
> **Answer:** *"We built an autonomous **1-Click Orbital Simulation & Chaos Mode** directly into the Mission Control UI. It synthesizes full 6-DOF orbital passes with realistic sensor harmonics, and provides chaos buttons to inject thermal runaway, battery sags, and structural flutter on demand. We are 100% prepared for any hardware contingency."*

---

#### Q9: "Why didn't you put a Raspberry Pi or GPU directly on the satellite module for AI?"
> **Answer:** *"That was a deliberate, realistic aerospace engineering design decision:  
> 1. **Power Budget:** A Raspberry Pi consumes **5W to 15W**. A typical 1U miniature satellite (CubeSat) has a total solar harvesting budget of only **1.5W to 3W**. Flying a Pi would cause an immediate power bus brownout and drain the battery in minutes. The ESP32 running FreeRTOS consumes only **0.15W to 0.4W**, which is spaceflight realistic.  
> 2. **Thermal Vacuum Physics:** In an orbital vacuum, there is zero air for fans or convective cooling. A Raspberry Pi running heavy neural compute would overheat, throttle, and thermally latch up within minutes without heavy, expensive radiator panels.  
> 3. **Hard Real-Time Determinism:** Linux is not a hard real-time operating system; flight computers require deterministic microsecond response (FreeRTOS) for sensor sampling and attitude stabilization.  
> 4. **NASA / ESA Aerospace Architecture:** In real space missions (Mars Exploration Rovers, LEO constellations, James Webb), onboard flight computers run low-power RTOS, while heavy AI reasoning and Small Language Models (Gemma 4) run at the **Ground Control Edge**, ingesting raw RF telemetry downlinks, executing automated Failure Mode and Effects Analysis (FMEA), and autonomously uplinking corrective telecommands. That is the exact mission architecture we built."*
