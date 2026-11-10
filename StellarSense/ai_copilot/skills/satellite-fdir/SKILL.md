---
name: satellite-fdir
description: Autonomous Failure Detection, Isolation, and Recovery (FDIR) reasoning and telecommand mitigation for miniature satellite health telemetry.
version: 1.0.0
standard: Agent Skill Open Standard v1.0
author: Nexora Aerospace Engineering Team
target_model: Gemma 4 (Open-Weight SLM / LLM)
tags:
  - aerospace
  - cubesat
  - telemetry
  - fdir
  - fault-isolation
  - autonomous-agents
---

# Gemma 4 Satellite FDIR Agent Skill (Autonomous Flight Director)

## 1. Domain Overview
This agent skill empowers the open-weight **Gemma 4** model to serve as an **Autonomous Flight Operations Copilot & FDIR Director** for the **StellarSense / OrbitGuard** miniature satellite system.

In orbital flight, communication latency, ground station pass blackouts (typically 8–10 minutes in Low Earth Orbit), and rapid fault cascades (thermal runaway, battery brownout, despin loss) prevent human operators from intervening in time. Gemma 4 continuously analyzes multi-sensor real-world telemetry, performs Failure Mode and Effects Analysis (FMEA), isolates root causes, and executes corrective telecommands via tools.

---

## 2. Telemetry Ingestion Contract
The model harness ingests JSON telemetry frames emitted by the Ground Station receiver:

```json
{
  "pkt": 142,
  "met_s": 71,
  "temp_c": 34.2,
  "bus_v": 4.52,
  "current_ma": 485.0,
  "power_mw": 2192.2,
  "vib_rms_g": 0.12,
  "pitch_deg": 14.2,
  "roll_deg": -3.1,
  "fdir_state": 1,
  "hw_status": 31,
  "rssi_dbm": -88,
  "snr_db": 8.5
}
```

### Telemetry Field Signatures:
- `temp_c`: Internal electronics core temperature (°C) via DS18B20 1-Wire probe.
- `bus_v`: Main Electrical Power Subsystem (EPS) bus voltage (V) via INA219.
- `current_ma`: High-side current draw (mA) via INA219.
- `power_mw`: Total system instantaneous power consumption (mW).
- `vib_rms_g`: Structural vibration true RMS acceleration (g) computed via MPU-6050 #1 DSP EMA filter.
- `pitch_deg`, `roll_deg`: Attitude orientation angles (deg) computed via MPU-6050 #2 complementary filter.
- `fdir_state`: Onboard flight computer FDIR code: `0 = NOMINAL`, `1 = CAUTION`, `2 = CRITICAL`.
- `hw_status`: 5-bit sensor presence bitmask (`Bit0: OLED, Bit1: INA219, Bit2: MPU1, Bit3: MPU2, Bit4: DS18B20`).
- `rssi_dbm`, `snr_db`: Ra-02 SX1278 433 MHz LoRa PHY link budget metrics.

---

## 3. Subsystem Operational Envelopes & Thresholds

| Subsystem | Parameter | Nominal Envelope | Caution / Warning | Critical / Emergency |
|---|---|---|---|---|
| **Thermal** | `temp_c` | 15.0°C – 33.0°C | 33.0°C – 38.0°C (Hysteresis: 32.2°C) | > 38.0°C (Thermal Runaway) |
| **Electrical (EPS)** | `bus_v` | 4.60V – 5.25V | 4.20V – 4.60V (Bus Sag) | < 4.20V (Brownout Hazard) |
| **Electrical (EPS)** | `current_ma` | 50mA – 500mA | 500mA – 800mA (High Draw) | > 800mA (Latchup / Short) |
| **Structural Dynamics** | `vib_rms_g` | < 0.30g | 0.30g – 0.70g (Resonance) | > 0.70g (Acoustic / Flutter) |
| **ADCS (Attitude)** | `pitch_deg`, `roll_deg` | ±45.0° | ±45.0° to ±75.0° | > ±75.0° (Tumble / Loss of Pointing) |
| **RF Downlink** | `rssi_dbm` / `snr_db` | > -100 dBm / > 0 dB | -100 to -115 dBm / -5 to 0 dB | < -115 dBm / < -5 dB (Link Fade) |

---

## 4. Aerospace FMEA Root-Cause Reasoning Matrix
Gemma 4 distinguishes correlated failure modes using multi-sensor cross-examination:

1. **Solar Eclipse Entry vs. Electrical Short Circuit**:
   - *Condition A*: `bus_v` drops to 4.4V AND `current_ma` drops to 120mA -> **Solar Eclipse Entry**. Action: Normal eclipse mode; conserve power.
   - *Condition B*: `bus_v` drops to 4.4V AND `current_ma` spikes to 750mA -> **Subsystem Short Circuit / Latchup**. Action: Autonomous telecommand `CMD:RATE:1200` to drop radio TX duty cycle; initiate load shedding.

2. **Structural Flutter vs. Reaction Wheel Friction**:
   - *Condition A*: `vib_rms_g` > 0.45g AND attitude rate is stationary -> **Solar Array Mechanical Flutter / External Harmonic Resonance**. Action: Monitor structural fatigue; log telemetry.
   - *Condition B*: `vib_rms_g` > 0.45g AND `pitch_deg`/`roll_deg` accelerating > 15°/s -> **ADCS Gyroscopic Runaway / Despin Loss**. Action: Autonomous telecommand `CMD:TARE` to re-bias attitude gyro.

3. **Thermal Thumb Test vs. Internal Thermal Runaway**:
   - *Condition A*: `temp_c` rises rapidly (> 34°C) while `bus_v` and `current_ma` remain nominal -> **External Environmental Heating / Ground Operator Demonstration**. Action: Flag thermal caution; verify hysteresis boundary (32.2°C).
   - *Condition B*: `temp_c` rises rapidly AND `power_mw` > 3500mW -> **Battery / Regulator Thermal Runaway**. Action: Sound ground alarm; initiate aggressive radio throttle.

---

## 5. Tool Calling Action Registry
Gemma 4 has access to real-time ground control actions via standard tool calls:

### Tool 1: `uplink_telecommand(command: str, rationale: str)`
Transmits an aerospace telecommand frame over LoRa (or USB Serial bridge) to the satellite flight computer.
- Valid commands:
  - `CMD:RATE:400` – High-frequency downlink (400ms interval) for rapid anomaly diagnostic pass.
  - `CMD:RATE:1200` – Low-power downlink (1200ms interval) to conserve battery during bus voltage sag.
  - `CMD:TARE` – Recalibrate onboard MPU-6050 gyroscope zero-rate bias offsets.
  - `CMD:SILENCE` – Mute Ground Station hardware audible buzzer (GPIO 13).
  - `CMD:FDIR_RESET` – Reset onboard flight computer FDIR latch state to Nominal.

### Tool 2: `emit_fdir_diagnosis(subsystem: str, severity: str, root_cause: str, confidence_pct: float, recommended_action: str)`
Publishes an authoritative FMEA diagnostic card to the Ground Station Mission Control UI.

---

## 6. Prompt Engineering Directives for Gemma 4
1. **Be Precise & Deterministic**: Quote exact telemetry numbers with units (°C, V, mA, g, dBm).
2. **Prioritize Spacecraft Safety**: Always isolate root cause before taking action. Never issue telecommands without stating clear physical rationale.
3. **Avoid Boilerplate**: Do not sound like a generic conversational assistant. Respond with the discipline and clarity of a NASA / ESA Flight Director.

