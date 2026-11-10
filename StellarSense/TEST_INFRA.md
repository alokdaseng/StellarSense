# 🛰️ StellarSense End-to-End Testing Infrastructure Specification

**System**: StellarSense — Miniature Satellite Health Monitor & Ground Station Telemetry System  
**Track**: E2E Testing Track (M5)  
**Author**: Test Writer Subagent (`test_writer_e2e`)  
**Status**: APPROVED & OPERATIONAL  
**Test Harness Version**: 1.0.0  
**Target Environment**: Linux / Python 3.10+ (Standard Library, Zero-Install Dependency Architecture)  

---

## 1. Executive Architecture Overview

The StellarSense End-to-End (E2E) testing track implements an industry-grade, opaque-box, requirement-driven verification harness modeled after ESA ECSS-E-ST-70-41C (Telemetry and Telecommand Packet Utilization) and NASA-HDBK-7004. 

The test infrastructure validates all data links, processing loops, and fault response mechanisms across the entire aerospace telemetry lifecycle:
```
+-------------------------------------------------------------+
|              SATELLITE ON-BOARD COMPUTER (OBC)              |
|  - FreeRTOS Deterministic 20Hz Sampling & 1Hz Thermal Loop   |
|  - DSP Engine (True RMS Flutter, Stationary Gyro Bias)       |
|  - Dual-Tier FDIR (Multi-Threshold, Hysteresis, 3-Debounce) |
+------------------------------+------------------------------+
                               | 433 MHz LoRa RF Link (SF7, CR 4/5)
                               v
+-------------------------------------------------------------+
|                 GROUND STATION RECEIVER                      |
|  - SX1278 PHY Demodulation + Hardware CRC Check             |
|  - Static RX Buffer (256-byte Heap-Safe Reassembly)         |
|  - RF Link Budget Metric Injection (RSSI, SNR, rx_count)    |
|  - 40ms Pulse-Stretched Activity LED Heartbeat               |
+------------------------------+------------------------------+
                               | USB UART Web Serial (115200 Baud)
                               v
+-------------------------------------------------------------+
|                 MISSION CONTROL DASHBOARD                   |
|  - Line-Delimited Stream Reader with Chunk Fragmentation    |
|  - Telemetry vs System Event vs Error Discriminator         |
|  - Rolling 60s Strip Charts + Master Annunciator Panel      |
|  - Loss of Signal (LOS) Watchdog (>3.0s Packet Timeout)     |
+-------------------------------------------------------------+
```

---

## 2. 4-Tier Test Architecture Pyramid

The test infrastructure is structured into four progressive testing tiers:

```
               /=======================\
              /         TIER 4          \
             /   Flight Mission Scenarios\
            /-----------------------------\
           /            TIER 3             \
          /   Serial Framing & Robustness   \
         /-----------------------------------\
        /               TIER 2                \
       /    DSP Algorithms & FDIR State Machine\
      /-----------------------------------------\
     /                   TIER 1                  \
    /     Telemetry Schema & Contract Validation  \
   /===============================================\
```

### Tier 1: Telemetry Schema & Contract Validation (`test_telemetry_schema.py`)
- **Focus**: Syntactic, semantic, and boundary-value verification of satellite downlink packets and ground station serial frames.
- **Methodologies**:
  - *Category-Partition Testing*: Distinguishes standard satellite telemetry, RF-enriched telemetry, ground station system boot events, and error frames.
  - *Boundary Value Analysis (BVA)*: Rigorous evaluation of minimum, maximum, and illegal out-of-bounds values across all 13 telemetry metrics (`pkt`, `met`, `temp`, `volt`, `curr`, `pwr`, `vib`, `pitch`, `roll`, `fdir`, `rssi`, `snr`, `rx_count`).
  - *Adversarial Mutation*: Missing required keys, unknown keys, invalid enum strings, and corrupted data types (strings, lists, None, dictionaries).
  - *Physical Consistency*: Cross-checks instantaneous electrical power $P = V \times I$ within sensor calibration tolerances.

### Tier 2: Algorithmic DSP & FDIR State Machine (`test_dsp_algorithms.py`, `test_fdir_state_machine.py`)
- **Focus**: High-fidelity discrete mathematical modeling of onboard digital signal processing and autonomous fault handling.
- **DSP Algorithms**:
  - *True RMS Vibration DSP*: Formulated as $RMS = \sqrt{\text{EMA}(dynG^2)}$ via dynamic acceleration differential filtering ($d\vec{a} = \vec{a}_k - \vec{a}_{k-1}$). Validates 100% DC gravity offset rejection ($1g \implies 0g_{\text{RMS}}$), sinusoidal frequency response, and impulse shock dissipation.
  - *Thermal Low-Pass Filtering*: Exponential moving average ($T_k = 0.8 T_{k-1} + 0.2 T_{\text{meas}}$) step response, settling time constant ($\tau$), and high-frequency noise suppression.
  - *Stationary Gyroscope Bias Calibration*: 100-sample boot calibration eliminating hardware DC zero-rate drift, preventing attitude divergence over long orbital passes.
  - *Attitude Sensor Fusion*: Complementary horizon filter ($0.96 \times \text{Gyro} + 0.04 \times \text{Horizon}$) and active tumble angular velocity magnitude ($\omega_{\text{tumble}} = \sqrt{\omega_x^2 + \omega_y^2 + \omega_z^2}$).
- **FDIR State Machine**:
  - *Multi-Tier Escalation*: Nominal $\rightarrow$ Caution $\rightarrow$ Critical.
  - *Dual-Threshold Hysteresis Deadbands*: Temperature (trip $\ge 33.0^\circ\text{C}$, clear $< 32.2^\circ\text{C}$), Voltage (trip $\le 4.60\text{V}$, clear $> 4.68\text{V}$), Vibration (trip $\ge 0.250\text{g}$, clear $< 0.200\text{g}$) to eliminate 20Hz boundary chattering.
  - *Persistence Debounce Filter*: Requires 3 consecutive samples (150ms at 20Hz) to confirm state escalation or recovery. Single-sample and 2-sample noise glitches are suppressed.
  - *Defensive Sensor Isolation*: Detects DS18B20 disconnects ($-127.0^\circ\text{C}$) and INA219 bus disconnects ($0.0\text{V}$) to isolate faulted nodes without triggering false vehicle aborts.

### Tier 3: Serial Framing & Protocol Robustness (`test_serial_framing.py`)
- **Focus**: Real-world serial UART stream dynamics, byte fragmentation, corrupted frames, and ground station discriminator logic.
- **Methodologies**:
  - *Byte-by-Byte Chunking*: Emulates slow UART transfers and arbitrary byte chunk arrivals (e.g. 1-byte reads) to verify buffer retention (`lines.pop()`) and newline-delimited framing.
  - *Burst Framing*: Multiple consecutive complete JSON packets within a single read chunk.
  - *Noise & Control Character Immunity*: Stream-level rejection of null bytes, ANSI control codes, and malformed JSON syntax without throwing unhandled exceptions.
  - *Ground Station Event Isolation*: Discriminator ensures ground station system frames (`{"system":"GROUND_STATION",...}`) and error reports (`{"err":"PARSE_FAIL",...}`) are routed to system logs and never pollute rolling flight charts.
  - *Telecommand Framing*: Bidirectional uplink telecommand validation (`CMD:PING`, `CMD:FDIR_RESET`, `CMD:TARE`, `CMD:RATE:<ms>`).

### Tier 4: Real-World Orbital Flight Scenarios (`test_scenarios.py`)
- **Focus**: Multi-minute mission flight profile simulations validating end-to-end autonomous reflexes under aerospace anomalies.
- **Scenario Catalog**:
  1. *Nominal Orbital Pass*: 60-second pass, 100 packets, zero drops, 100% NOMINAL FDIR.
  2. *Thermal Excursion & Direct Solar Heating*: Solar flux thermal runaway up to $39.5^\circ\text{C}$ triggering Master Caution and Master Warning sirens, followed by off-pointing cooling and hysteresis recovery.
  3. *Solar Eclipse Battery Brownout*: Orbital umbra entry causing bus voltage sag to $4.10\text{V}$, triggering EPS brownout alerts, followed by post-eclipse photovoltaic recharge and recovery.
  4. *High-Frequency Structural Flutter*: Reaction wheel acoustic resonance exceeding $0.80\text{g}_{\text{RMS}}$, triggering structural flutter alerts, followed by active damping dissipation.
  5. *Uncontrolled Tumble & ADCS Recovery*: Separation tip-off angular rates exceeding $50^\circ/\text{s}$, triggering tumble rate warnings, followed by detumble maneuvers restoring nadir stability ($< 5^\circ/\text{s}$).
  6. *Loss of Signal (LOS) Watchdog & RF Link Fade*: RF attenuation and 6-packet burst fade ($> 3.0\text{s}$ silence), triggering ground station COMMS LOS alarms, followed by signal re-acquisition and link recovery.

---

## 3. Test Suite Catalog & Test Matrix

| # | Test Module | Test Method | Tier | Description |
|---|---|---|---|---|
| 1 | `test_telemetry_schema.py` | `test_canonical_satellite_frame_validation` | 1 | Validates standard satellite packet against canonical contract |
| 2 | `test_telemetry_schema.py` | `test_canonical_enriched_frame_validation` | 1 | Validates enriched ground station packet including RF metrics |
| 3 | `test_telemetry_schema.py` | `test_json_serialization_roundtrip` | 1 | Confirms JSON serialize/deserialize numerical precision |
| 4 | `test_telemetry_schema.py` | `test_classify_ground_station_boot_frame` | 1 | Identifies ground station boot banners and isolates from telemetry |
| 5 | `test_telemetry_schema.py` | `test_classify_ground_station_error_frame` | 1 | Identifies RF parse failures (`PARSE_FAIL`) |
| 6 | `test_telemetry_schema.py` | `test_classify_telecommand_frame` | 1 | Identifies uplink command frames (`CMD:*`) |
| 7 | `test_telemetry_schema.py` | `test_classify_enriched_vs_satellite_frame`| 1 | Distinguishes raw LoRa packets from serial-enriched frames |
| 8 | `test_telemetry_schema.py` | `test_bva_packet_counter_boundaries` | 1 | BVA on `pkt`: 1, uint32_max, 0 (invalid), -1 (invalid) |
| 9 | `test_telemetry_schema.py` | `test_bva_mission_elapsed_time_boundaries` | 1 | BVA on `met`: 0s, 1 year, negative values |
| 10 | `test_telemetry_schema.py` | `test_bva_temperature_boundaries` | 1 | BVA on `temp`: -50°C, +85°C, -127°C (disconnect), +120°C |
| 11 | `test_telemetry_schema.py` | `test_bva_bus_voltage_boundaries` | 1 | BVA on `volt`: 0.0V, 6.0V, -0.5V (invalid), 7.5V (invalid) |
| 12 | `test_telemetry_schema.py` | `test_bva_vibration_rms_boundaries` | 1 | BVA on `vib`: 0.000g, 0.250g, 0.700g, negative, >10g |
| 13 | `test_telemetry_schema.py` | `test_bva_attitude_angles_boundaries` | 1 | BVA on Pitch [-90°, +90°] and Roll [-180°, +180°] |
| 14 | `test_telemetry_schema.py` | `test_bva_rf_metrics_boundaries` | 1 | BVA on RSSI [-140, 0 dBm] and SNR [-30, +30 dB] |
| 15 | `test_telemetry_schema.py` | `test_missing_required_keys` | 1 | Adversarial: Drops each mandatory key individually |
| 16 | `test_telemetry_schema.py` | `test_invalid_fdir_enum_values` | 1 | Rejects illegal FDIR status strings |
| 17 | `test_telemetry_schema.py` | `test_corrupted_type_safety` | 1 | Injects invalid types (strings, lists, dicts, None) into numbers |
| 18 | `test_telemetry_schema.py` | `test_stringified_float_graceful_handling` | 1 | Parses ArduinoJson stringified floats (`"28.40"`) safely |
| 19 | `test_fdir_state_machine.py` | `test_single_sample_noise_glitch_rejection` | 2 | Rejects single-cycle threshold breach (debounce filter) |
| 20 | `test_fdir_state_machine.py` | `test_two_sample_noise_glitch_rejection` | 2 | Rejects two-cycle threshold glitch |
| 21 | `test_fdir_state_machine.py` | `test_sustained_three_samples_triggers_state_escalation` | 2 | Confirms state change upon 3 consecutive samples (150ms) |
| 22 | `test_fdir_state_machine.py` | `test_thermal_hysteresis_deadband` | 2 | Verifies 33.0°C trip and 32.2°C clear deadband |
| 23 | `test_fdir_state_machine.py` | `test_voltage_hysteresis_deadband` | 2 | Verifies 4.60V trip and 4.68V clear deadband |
| 24 | `test_fdir_state_machine.py` | `test_vibration_hysteresis_deadband` | 2 | Verifies 0.250g trip and 0.200g clear deadband |
| 25 | `test_fdir_state_machine.py` | `test_critical_precedence_over_caution` | 2 | Multi-subsystem priority: CRITICAL overrides CAUTION |
| 26 | `test_fdir_state_machine.py` | `test_ds18b20_sensor_disconnect_isolation` | 2 | Isolates -127°C disconnect without false vehicle abort |
| 27 | `test_fdir_state_machine.py` | `test_ina219_sensor_disconnect_isolation` | 2 | Isolates 0.0V sensor failure without false brownout trip |
| 28 | `test_dsp_algorithms.py` | `test_static_gravity_rejection` | 2 | Static 1g Earth gravity vector yields 0.0g dynamic RMS |
| 29 | `test_dsp_algorithms.py` | `test_pure_sinusoidal_vibration_rms` | 2 | Sine wave excitation converges to theoretical RMS power |
| 30 | `test_dsp_algorithms.py` | `test_shock_impulse_and_exponential_decay` | 2 | High-g shock pulse spikes RMS followed by exponential decay |
| 31 | `test_dsp_algorithms.py` | `test_ema_step_response_and_time_constant` | 2 | Thermal EMA step response asymptotic convergence |
| 32 | `test_dsp_algorithms.py` | `test_ema_white_noise_filtering` | 2 | High-frequency noise variance attenuation (>50%) |
| 33 | `test_dsp_algorithms.py` | `test_gyro_stationary_offset_calibration` | 2 | 100-sample calibration eliminates hardware DC bias |
| 34 | `test_dsp_algorithms.py` | `test_uncalibrated_vs_calibrated_integration_drift` | 2 | Calibrated gyro suppresses 30° divergence over 10s |
| 35 | `test_dsp_algorithms.py` | `test_attitude_filter_static_horizontal_equilibrium` | 2 | Nadir attitude hold converges to 0.0° pitch and 0.0° roll |
| 36 | `test_dsp_algorithms.py` | `test_attitude_filter_pitch_tilt` | 2 | 30° physical tilt converges accurately in complementary filter |
| 37 | `test_dsp_algorithms.py` | `test_attitude_boundary_clamping` | 2 | Enforces safe angular constraints [-90°, 90°], [-180°, 180°] |
| 38 | `test_dsp_algorithms.py` | `test_tumble_rate_stationary_vs_active` | 2 | Calculates 3D angular rate magnitude from gyro rates |
| 39 | `test_serial_framing.py` | `test_single_byte_by_byte_stream_reassembly` | 3 | Reassembles JSON line fed 1 single byte per read |
| 40 | `test_serial_framing.py` | `test_split_across_json_key_boundaries` | 3 | Reassembles packet split across middle of keys and numbers |
| 41 | `test_serial_framing.py` | `test_multi_frame_burst_in_single_chunk` | 3 | Dispatches 3 back-to-back packets in a single buffer read |
| 42 | `test_serial_framing.py` | `test_multi_frame_with_incomplete_tail` | 3 | Retains trailing incomplete fragment across chunk reads |
| 43 | `test_serial_framing.py` | `test_corrupted_json_syntax_handling` | 3 | Traps syntax errors into error log without crashing |
| 44 | `test_serial_framing.py` | `test_binary_garbage_and_ascii_control_characters` | 3 | Stream-level noise immunity against non-ASCII bytes |
| 45 | `test_serial_framing.py` | `test_ground_station_boot_event_isolation` | 3 | Filters `{"system":"GROUND_STATION",...}` from charts |
| 46 | `test_serial_framing.py` | `test_ground_station_parse_fail_event_isolation` | 3 | Filters `{"err":"PARSE_FAIL",...}` from charts |
| 47 | `test_serial_framing.py` | `test_uplink_telecommand_framing` | 3 | Dispatches uplink telecommands (`CMD:PING`, etc.) |
| 48 | `test_serial_framing.py` | `test_reconnection_buffer_flush` | 3 | Flushes buffer cleanly upon serial disconnect/reconnect |
| 49 | `test_scenarios.py` | `test_scenario_1_nominal_orbital_pass` | 4 | 60-second nominal pass (100 packets, zero faults) |
| 50 | `test_scenarios.py` | `test_scenario_2_thermal_excursion_and_solar_heating` | 4 | Direct solar flux excursion and shadow recovery |
| 51 | `test_scenarios.py` | `test_scenario_3_solar_eclipse_battery_brownout` | 4 | Eclipse battery bus sag, critical brownout, and solar recharge |
| 52 | `test_scenarios.py` | `test_scenario_4_high_frequency_structural_flutter` | 4 | Reaction wheel resonance surge and damping dissipation |
| 53 | `test_scenarios.py` | `test_scenario_5_uncontrolled_tumble_and_recovery` | 4 | Separation tip-off tumble and ADCS stabilization |
| 54 | `test_scenarios.py` | `test_scenario_6_loss_of_signal_watchdog_and_packet_gap` | 4 | RF fade packet loss and 3.0s LOS watchdog alert/recovery |

---

## 4. Test Harness Execution Guide

The test harness is implemented in `tests/e2e_test_runner.py` and requires **zero external third-party dependencies** (runs natively on Python 3.10+ standard library).

### Basic Command:
```bash
python3 tests/e2e_test_runner.py
```

### Command-Line Options:
| Flag | Description | Example |
|---|---|---|
| `--verbose`, `-v` | Prints detailed individual test names, execution timings, and tracebacks | `python3 tests/e2e_test_runner.py -v` |
| `--tier <1..4>` | Filters execution by specific architectural tier | `python3 tests/e2e_test_runner.py --tier 2` |
| `--suite <name>` | Runs a specific test suite (`schema`, `fdir`, `dsp`, `framing`, `scenarios`) | `python3 tests/e2e_test_runner.py --suite fdir` |
| `--mock-serial-feed [N]`| Generates synthetic real-time serial telemetry stream ($N$ packets) | `python3 tests/e2e_test_runner.py --mock-serial-feed 50` |
| `--interval <ms>` | Packet interval for mock serial feed (default: 600ms) | `python3 tests/e2e_test_runner.py --mock-serial-feed 20 --interval 200` |

### Deterministic Exit Codes:
- `0`: All executed test assertions passed with 100% success.
- `1`: One or more test assertions failed or encountered an error.

---

## 5. Mock Serial Telemetry Feeder for Mission Control Validation

To validate the browser-based Mission Control Dashboard (`dashboard/index.html` + `dashboard/app.js`) without physical ESP32 hardware connected, the test harness provides a built-in mock telemetry feeder.

### Feeder Output Format:
```json
{"system": "GROUND_STATION", "status": "BOOT_OK", "freq_mhz": 433.0, "baud": 115200}
{"pkt": 1, "met": 1, "temp": 27.35, "volt": 5.03, "curr": 327.9, "pwr": 1647.7, "vib": 0.071, "pitch": 2.0, "roll": 7.9, "fdir": "NOMINAL", "rssi": -48, "snr": 9.5, "rx_count": 1}
{"pkt": 2, "met": 2, "temp": 27.50, "volt": 5.03, "curr": 327.4, "pwr": 1647.5, "vib": 0.079, "pitch": 3.9, "roll": 7.8, "fdir": "NOMINAL", "rssi": -48, "snr": 9.5, "rx_count": 2}
```

### Feeding into Virtual Serial Ports (`socat`):
```bash
# Terminal 1: Create a virtual pseudo-terminal pair
socat -d -d pty,raw,echo=0 pty,raw,echo=0
# Note the ports generated, e.g. /dev/pts/2 and /dev/pts/3

# Terminal 2: Stream simulated telemetry to /dev/pts/2
python3 tests/e2e_test_runner.py --mock-serial-feed 500 --interval 600 > /dev/pts/2

# In Chrome: Connect Web Serial API to /dev/pts/3 to view live mission telemetry!
```

---
*Infrastructure Specification Certified by Test Writer.*
