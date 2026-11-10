# 📡 StellarSense Command & Data Handling (C&DH) Telecommand Specification

**System:** StellarSense Miniature Satellite Health Monitor & Ground Station Telemetry System  
**Document Classification:** Spacecraft Command & Data Handling (C&DH) Subsystem Interface Control Document (ICD)  
**Standard Compliance:** CCSDS-Inspired Packet Telecommand & Telemetry Framing  
**Target Transceivers:** Semtech SX1278 (Ra-02 433 MHz LoRa) & USB-UART Web Serial Bridge  
**Revision:** 1.0.0-RELEASE  

---

## 1. Executive Telecommand Architecture

StellarSense implements a bidirectional, half-duplex Telemetry and Telecommand (TM/TC) link between the ground-based Mission Control workstation and the orbiting Satellite Flight Computer (On-Board Computer - OBC).

Telecommands originate at the Mission Control user interface (or automated ground scripts), traverse the W3C Web Serial API bridge to the Ground Station ESP32, and are uplinked over the 433 MHz LoRa radio link. The Satellite OBC captures uplinked command packets on Core 0 (`PRO_CPU`), decodes the command opcode and parameters, verifies safety bounds, and coordinates execution with Core 1 (`APP_CPU`) via atomic FreeRTOS primitives.

```
┌────────────────────────────────────────────────────────────────────────┐
│                      END-TO-END TELECOMMAND DATAFLOW                   │
└────────────────────────────────────────────────────────────────────────┘

 [ Mission Control Dashboard ]
        │  (User clicks TARE, FDIR RESET, or sends CLI command)
        ▼
   Web Serial API (115200 Baud, 8N1)
        │  Line-delimited ASCII string (e.g. "CMD:TARE\n")
        ▼
 [ Ground Station ESP32 ]
   ├── processSerialCommands() -> Ingests UART bytes into static buffer
   ├── Echoes Event: {"system":"GROUND_STATION","event":"CMD_UPLINK","cmd":"..."}
   ├── Flashes Blue RX/TX LED (40ms Pulse)
   └── LoRa.beginPacket() -> Uplinks RF frame over 433 MHz carrier
        │
        ▼ LoRa 433 MHz RF Uplink (SF7, BW 125kHz, CR 4/5, Sync 0xF3, CRC)
        │
 [ Satellite Flight Computer (ESP32) ]
   ├── Core 0 (PRO_CPU): LoRa.parsePacket() demodulates frame & checks CRC
   ├── handleTelecommand() -> Validates syntax & parameter bounds
   ├── Inter-Core Flag Dispatch:
   │     ├── CMD:PING        ──> Immediate LoRa PONG downlink ACK
   │     ├── CMD:FDIR_RESET  ──> cmdFdirResetRequested = true
   │     ├── CMD:TARE        ──> cmdTareRequested = true
   │     └── CMD:RATE:<ms>   ──> downlinkIntervalMs = <ms>
   │
   └── Core 1 (APP_CPU): loop() checks flags deterministically
         ├── Executes tareAttitude() or FDIR filter flush
         └── Next telemetry frame reflects updated state
```

---

## 2. Physical & Data Link Layer Framing

### 2.1 RF Uplink Modulation Parameters

| Modulation Parameter | Configuration | Engineering Rationale |
|:---|:---:|:---|
| **Carrier Frequency** | `433.0 MHz` (`433E6`) | Standard Sub-GHz ISM band; provides superior link margin through obstacles. |
| **Spreading Factor** | `SF7` (128 chips/symbol) | Delivers fast transmission airtime (~40ms for short command frames). |
| **Signal Bandwidth** | `125 kHz` (`125E3`) | Standard balance between receiver noise floor and data throughput. |
| **Coding Rate** | `4/5` (`setCodingRate4(5)`) | 20% Forward Error Correction (FEC) protecting command opcodes. |
| **Sync Word** | `0xF3` | Private network preamble isolation; discards third-party 433MHz packets. |
| **Preamble Length** | `8 symbols` | Rapid preamble detection and AGC lock. |
| **Hardware CRC** | **ENABLED** (`LoRa.enableCrc()`) | Corrupted command frames are dropped at the PHY modem before software execution. |
| **RF Transmit Power** | `+17 dBm` (50 mW) | High SNR uplink guaranteed across ground testing environments. |

### 2.2 Serial Ingestion Protocol (Host $\leftrightarrow$ Ground Station)
- **Physical Interface:** USB Virtual COM Port (CP2102 / CH340 / ESP32 USB-CDC).
- **UART Framing:** 115200 Baud, 8 Data Bits, No Parity, 1 Stop Bit (8N1).
- **Line Delimiters:** Standard carriage return and line feed (`\r\n` or `\n`).
- **Memory Safety:** Ingestion uses a fixed-size stack buffer `char cmdSerialBuffer[64]` with strict boundary clamping. Dynamic heap strings (`String`) are prohibited to eliminate heap fragmentation.

---

## 3. Formal Telecommand Dictionary

StellarSense defines four flight telecommands supporting spacecraft checkout, attitude zeroing, autonomous fault recovery, and variable downlink bandwidth management:

```
+──────────────────+──────────────────+───────────────────────────────────────────────+
| Telecommand      | Parameters       | Flight Subsystem Action                       |
+──────────────────+──────────────────+───────────────────────────────────────────────+
| CMD:PING         | None             | Transmits instantaneous RF PONG verification. |
| CMD:FDIR_RESET   | None             | Flushes FDIR persistence filter & resets state.|
| CMD:TARE         | None             | Calibrates ADCS attitude zero-reference angle.|
| CMD:RATE:<ms>    | <ms>: 100..5000  | Dynamically adjusts telemetry downlink rate.  |
+──────────────────+──────────────────+───────────────────────────────────────────────+
```

---

### 3.1 Telecommand 0x01: `CMD:PING`

- **Purpose:** Spacecraft link verification and RF round-trip latency measurement.
- **Syntax:** `CMD:PING`
- **Parameters:** None.
- **Execution Pipeline:**
  1. Ground Station uplinks `CMD:PING` over LoRa.
  2. Satellite Core 0 parses packet and executes immediate response branch:
     ```cpp
     LoRa.beginPacket();
     LoRa.print(F("{\"system\":\"SATELLITE\",\"ack\":\"PONG\"}"));
     LoRa.endPacket();
     ```
  3. Ground Station receives the response packet, injects RSSI and SNR, and outputs the acknowledgment to Mission Control.
- **Downlink Acknowledgment Payload:**
  ```json
  {"system":"SATELLITE","ack":"PONG","rssi":-46,"snr":9.2}
  ```
- **Round-Trip Latency:** Approximately $110\text{ ms} - 160\text{ ms}$ total link turnaround time.

---

### 3.2 Telecommand 0x02: `CMD:FDIR_RESET`

- **Purpose:** Manual fault latch override and FDIR persistence filter reset.
- **Syntax:** `CMD:FDIR_RESET`
- **Parameters:** None.
- **Execution Pipeline:**
  1. Satellite Core 0 receives `CMD:FDIR_RESET` and asserts atomic volatile flag:
     `cmdFdirResetRequested = true;`
  2. At the next 50ms cycle on Core 1, the executive loop acknowledges the request:
     ```cpp
     if (cmdFdirResetRequested) {
       cmdFdirResetRequested = false;
       fdirWarnPersistence = 0;
       fdirCritPersistence = 0;
       currentFDIR = STATE_NOMINAL;
     }
     ```
  3. The 3-sample persistence counter is flushed to zero.
  4. If physical sensor readings are currently below the caution hysteresis clear thresholds ($T < 32.2^\circ\text{C}$, $V > 4.70\text{V}$, $A_{\text{vib}} < 0.20\text{g}$), the spacecraft returns immediately to `STATE_NOMINAL`.
  5. Status LEDs revert to Green, buzzer silences, and the next telemetry frame broadcasts `"fdir":"NOMINAL"`.
- **Safety Precedence:** If physical sensor readings remain in true critical violation (e.g. $T > 38.0^\circ\text{C}$), the FDIR engine will re-escalate to `STATE_CRITICAL` after 3 consecutive frames (150ms), ensuring manual overrides cannot mask ongoing catastrophic thermal/electrical conditions.

---

### 3.3 Telecommand 0x03: `CMD:TARE`

- **Purpose:** Attitude Determination & Control Subsystem (ADCS) zero-point alignment.
- **Syntax:** `CMD:TARE`
- **Parameters:** None.
- **Execution Pipeline:**
  1. Satellite Core 0 receives `CMD:TARE` and sets `cmdTareRequested = true;`.
  2. Core 1 invokes `tareAttitude()`:
     ```cpp
     void tareAttitude() {
       pitchAngle = 0.0f;
       rollAngle  = 0.0f;
     }
     ```
  3. Current physical orientation is established as the local horizontal horizon reference frame ($0.0^\circ$ pitch, $0.0^\circ$ roll).
  4. 3D Digital Twin on Mission Control immediately aligns to level orbit.
- **Downlink Telemetry Reflection:** Next telemetry frame downlinks `"pitch":0.0,"roll":0.0`.

---

### 3.4 Telecommand 0x04: `CMD:RATE:<ms>`

- **Purpose:** Dynamic modulation of telemetry downlink transmission frequency.
- **Syntax:** `CMD:RATE:<ms>`
- **Parameter `<ms>`:** Unsigned integer representing the downlink period in milliseconds.
  - **Permissible Flight Envelope:** $100\text{ ms} \le \text{rate} \le 5000\text{ ms}$
  - **Default Orbit Cadence:** $600\text{ ms}$ (~1.66 Hz)
  - **High-Rate Pass Mode:** $200\text{ ms}$ (5.0 Hz during ground station contact pass)
  - **Low-Power Deep Orbit Mode:** $2000\text{ ms}$ (0.5 Hz during battery recharge eclipse)
- **Validation & Clamping Logic:**
  ```cpp
  int rate = atoi(cmd + 9);
  if (rate >= 100 && rate <= 5000) {
    downlinkIntervalMs = (uint32_t)rate;
    Serial.print(F("[C&DH] Telemetry downlink rate adjusted to: "));
    Serial.print(downlinkIntervalMs);
    Serial.println(F(" ms."));
  } else {
    Serial.println(F("[C&DH] NACK: Rate out of permissible envelope (100-5000ms)."));
  }
  ```
- **Safety Interlock:** Telemetry rates below 100ms are strictly rejected to prevent RF transmitter duty-cycle violations and LDO thermal over-stress.

---

## 4. Ground Station Telemetry Event Framing

When telecommands are transmitted or link events occur, the Ground Station formats and streams JSON event frames to the host workstation over USB Serial:

### 4.1 Command Uplink Echo Frame
Broadcast immediately upon ingesting a command from the serial port:
```json
{
  "system": "GROUND_STATION",
  "event": "CMD_UPLINK",
  "cmd": "CMD:TARE"
}
```

### 4.2 System Boot Announcement Frame
Broadcast once upon Ground Station MCU boot:
```json
{
  "system": "GROUND_STATION",
  "status": "READY",
  "freq_mhz": 433.0,
  "baud": 115200,
  "crc": "ENABLED"
}
```

### 4.3 Corrupted Packet / Parse Failure Frame
Broadcast when a received LoRa packet fails CRC or contains corrupted JSON syntax:
```json
{
  "error": "PARSE_FAIL",
  "raw": "{\"pkt\":14,#corrupted...}",
  "rssi": -98,
  "snr": -4.5
}
```

---

## 5. Timing, Rate Limiting & Safety Timeouts

### 5.1 Uplink Rate Limiting
- To prevent LoRa channel contention and transmitter amplifier saturation, Mission Control enforces a **maximum telecommand rate of 2 commands per second** (minimum 500ms separation between successive uplink packets).
- Rapid user button clicking is debounced in the web frontend.

### 5.2 RF Turnaround & Airtime Analysis
- A 15-byte telecommand (`CMD:FDIR_RESET\r\n`) transmitted at SF7 / BW 125 kHz / CR 4/5 requires:
  $$T_{\text{preamble}} = (8 + 4.25) \times 1.024\text{ ms} = 12.54\text{ ms}$$
  $$n_{\text{payload}} = 8 + \max\left(\left\lceil \frac{8 \times 15 - 4 \times 7 + 28}{28} \right\rceil \times 5, 0\right) = 8 + 25 = 33\text{ symbols}$$
  $$T_{\text{payload}} = 33 \times 1.024\text{ ms} \approx 33.79\text{ ms}$$
  $$T_{\text{airtime}} = 12.54\text{ ms} + 33.79\text{ ms} \approx 46.33\text{ ms}$$
- The short uplink burst occupies less than **50ms of RF channel airtime**, enabling rapid interleaved uplink commands between regular 600ms telemetry downlinks.

### 5.3 Command Execution Watchdog & Timeout
- If a command acknowledgment or telemetry state change is not received within **3000 milliseconds**, Mission Control flags a `COMMAND_TIMEOUT` warning on the console HUD, prompting the operator to re-verify RF link RSSI/SNR metrics.

---

## 6. Verification & Test Procedures

The telecommand subsystem is verified via automated test suites in `/home/alokd/Documents/StellarSense/tests/`:

1. **Syntax Validation Test (`test_serial_framing.py`):**
   - Injects canonical commands, unknown opcodes (`CMD:UNKNOWN`), and malformed strings.
   - Verifies parser accepts valid syntax and safely ignores trailing whitespaces.

2. **Downlink Rate Boundaries (`test_telemetry_schema.py`):**
   - Verifies boundary conditions: `CMD:RATE:99` (Rejected), `CMD:RATE:100` (Accepted), `CMD:RATE:5000` (Accepted), `CMD:RATE:5001` (Rejected).

3. **Inter-Core State Dispatch Verification (`test_fdir_state_machine.py`):**
   - Validates that `CMD:FDIR_RESET` clears persistence filters and transitions state deterministically.
