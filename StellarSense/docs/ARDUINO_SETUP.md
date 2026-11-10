# 💻 StellarSense Firmware Build & Deployment Guide

**System:** StellarSense Miniature Satellite Health Monitor & Ground Station Telemetry System  
**Document Classification:** Software Engineering & Avionics Toolchain Specification  
**Target Environments:** Arduino IDE 2.x & PlatformIO (VS Code / CLI)  
**Target Architecture:** Dual ESP32-WROOM-32 (Xtensa Dual-Core 32-bit LX6 @ 240 MHz)  
**Revision:** 2.0.0-RELEASE  

---

## 1. Executive Toolchain Overview

The StellarSense flight software is designed for zero-friction compilation and deterministic deployment across two industry-standard development ecosystems:
- **Arduino IDE 2.x**: Graphical environment for rapid bench testing and interactive serial inspection.
- **PlatformIO**: Production-grade, deterministic CLI and IDE environment with pin-point library version locking and reproducible multi-target builds.

Both flight sketches (`satellite_sender.ino` and `ground_receiver.ino`) leverage **ESP-IDF FreeRTOS** multi-core primitives, hardware Task Watchdog Timers (`esp_task_wdt`), and static memory buffers to deliver rock-solid CubeSat-grade avionics performance.

---

## 2. Exact Library Dependency Matrix

To ensure absolute binary reproducibility and prevent API incompatibilities, install the exact verified library versions listed below:

| Library Name | Author | Minimum / Verified Version | PlatformIO Package ID | Functional Subsystem / Role in StellarSense |
|:---|:---|:---:|:---|:---|
| **`LoRa`** | Sandeep Mistry | **`0.8.0`** | `sandeepmistry/LoRa @ ^0.8.0` | Semtech SX1278 SPI driver; handles hardware CRC & RF packet streaming. |
| **`Adafruit INA219`** | Adafruit | **`1.2.3`** | `adafruit/Adafruit INA219 @ ^1.2.3` | Bus voltage, current shunt, and instantaneous power monitoring via $I^2C$. |
| **`Adafruit MPU6050`** | Adafruit | **`2.2.6`** | `adafruit/Adafruit MPU6050 @ ^2.2.6` | 6-DOF IMU driver for vibration DSP (`0x68`) and attitude ADCS (`0x69`). |
| **`Adafruit SSD1306`** | Adafruit | **`2.5.9`** | `adafruit/Adafruit SSD1306 @ ^2.5.9` | 0.96" monochrome 128x64 OLED display buffer and graphics rendering. |
| **`DallasTemperature`** | Miles Burton | **`3.9.0`** | `milesburton/DallasTemperature @ ^3.9.0` | Maxim DS18B20 digital thermal sensor driver (asynchronous 10-bit mode). |
| **`OneWire`** | Paul Stoffregen | **`2.3.8`** | `paulstoffregen/OneWire @ ^2.3.8` | Bit-banged 1-Wire communication protocol engine for DS18B20. |
| **`ArduinoJson`** | Benoit Blanchon | **`7.4.3`** | `bblanchon/ArduinoJson @ ^7.4.3` | High-efficiency zero-copy JSON telemetry serialization and deserialization. |
| **`Adafruit Unified Sensor`** | Adafruit | **`1.1.14`** | `adafruit/Adafruit Unified Sensor @ ^1.1.14` | Abstract sensor HAL dependency for Adafruit sensor drivers. |
| **`Adafruit BusIO`** | Adafruit | **`1.16.1`** | `adafruit/Adafruit BusIO @ ^1.16.1` | Underlying SPI and $I^2C$ register abstraction layer. |
| **`Adafruit GFX Library`** | Adafruit | **`1.11.9`** | `adafruit/Adafruit GFX Library @ ^1.11.9` | 2D graphics primitives core for OLED user interface. |

---

## 3. FreeRTOS Dual-Core Concurrency & Compiler Architecture

The ESP32 incorporates two physical 32-bit Xtensa LX6 CPU cores:
- **Core 0 (PRO_CPU)**: Protocol CPU
- **Core 1 (APP_CPU)**: Application CPU

### 3.1 Task Partitioning Architecture

In naive single-threaded Arduino firmware, transmitting a 135-byte LoRa packet at SF7/125kHz blocks CPU execution inside `LoRa.endPacket()` for **220 to 287 milliseconds**. During this freeze, sensor sampling stops, gyroscope rate integration starves, attitude drift accumulates, and audible alarms stutter.

StellarSense eliminates this blocking freeze through a deterministic dual-core FreeRTOS architecture:

```
┌────────────────────────────────────────────────────────────────────────┐
│                      ESP32 DUAL-CORE EXECUTION MODEL                   │
├────────────────────────────────────┬───────────────────────────────────┤
│          CORE 1 (APP_CPU)          │         CORE 0 (PRO_CPU)          │
│       High-Priority Real-Time      │      Background Telemetry IO      │
├────────────────────────────────────┼───────────────────────────────────┤
│                                    │                                   │
│  ┌──────────────────────────────┐  │  ┌─────────────────────────────┐  │
│  │ runSensorDSP() [20 Hz / 50ms]│  │  │ loraTask() [Priority 1]     │  │
│  │ - 1Hz Async DS18B20 Polling  │  │  │ - xQueueReceive(50ms wait)  │  │
│  │ - INA219 Voltage & Current   │  │  │ - LoRa.beginPacket()        │  │
│  │ - True RMS Vibration Filter  │  │  │ - LoRa.print(staticBuffer)  │  │
│  │ - Complementary Attitude     │  │  │ - LoRa.endPacket() [BLOCKS  │  │
│  └──────────────┬───────────────┘  │  │   FOR 250ms WITHOUT STALLING│  │
│                 │                  │  │   CORE 1 REAL-TIME TASKS!]  │  │
│                 ▼                  │  │ - LoRa.parsePacket() [Uplink│  │
│  ┌──────────────────────────────┐  │  │   Telecommand Ingestion]    │  │
│  │ evaluateFDIR() [20 Hz]       │  │  └──────────────▲──────────────┘  │
│  │ - Dual-Threshold Deadbands   │  │                 │                 │
│  │ - 3-Sample Persistence Filter│  │                 │                 │
│  └──────────────┬───────────────┘  │                 │                 │
│                 │                  │                 │                 │
│                 ▼                  │                 │                 │
│  ┌──────────────────────────────┐  │                 │                 │
│  │ pushTelemetry()              ├──┼── Non-Blocking ─┘                 │
│  │ - TelemetryPayload Struct    │  │   FreeRTOS Queue                  │
│  └──────────────────────────────┘  │   (xQueueSend(..., 0))            │
│                 │                  │                                   │
│                 ▼                  │                                   │
│  ┌──────────────────────────────┐  │                                   │
│  │ updateAlertHardware() [10 Hz]│  │                                   │
│  │ updateOLED() [5 Hz]          │  │                                   │
│  │ feedWatchdog()               │  │                                   │
│  └──────────────────────────────┘  │                                   │
│                                    │                                   │
└────────────────────────────────────┴───────────────────────────────────┘
```

### 3.2 Inter-Core Communication Contract

1. **Queue Isolation (`telemetryQueue`):**
   - Implemented via `QueueHandle_t telemetryQueue = xQueueCreate(4, sizeof(TelemetryPayload));`.
   - Core 1 pushes flight metrics via `xQueueSend(telemetryQueue, &payload, 0)`. The timeout is strictly `0`: if the queue is full, the frame drops silently rather than stalling the 50ms real-time control loop.
   - Core 0 pops items via `xQueueReceive(telemetryQueue, &payload, pdMS_TO_TICKS(50))`.

2. **Atomic Command Flags:**
   - Telecommands received on Core 0 (`CMD:TARE`, `CMD:FDIR_RESET`) set `volatile bool` flags (`cmdTareRequested`, `cmdFdirResetRequested`).
   - Core 1 inspects and clears these flags at the top of its deterministic executive loop, preventing race conditions without heavy mutex overhead.

3. **Compiler Optimization Flags:**
   - StellarSense sketches are compiled with `-O2` optimization to maximize floating-point math throughput during DSP filtering and matrix operations.

---

## 4. PlatformIO Configuration (`platformio.ini`)

For automated, headless, or terminal-based workflows, use the production `platformio.ini` configuration below. It defines isolated builds for the Satellite OBC and the Ground Station Receiver:

```ini
; =====================================================================================
; StellarSense - Spacecraft Avionics & Ground Station Multi-Target Environment
; =====================================================================================

[platformio]
default_envs = satellite
src_dir = firmware

[env]
platform = espressif32 @ 6.5.0
board = esp32dev
framework = arduino
monitor_speed = 115200
upload_speed = 921600
board_build.f_cpu = 240000000L
board_build.f_flash = 80000000L
board_build.flash_mode = qio
build_unflags = -Os
build_flags = 
    -O2
    -DCORE_DEBUG_LEVEL=1
    -DCONFIG_ARDUHAL_LOG_COLORS=1

; -------------------------------------------------------------------------------------
; Target 1: Satellite Flight Computer (OBC Transmitter)
; -------------------------------------------------------------------------------------
[env:satellite]
build_src_filter = +<satellite_sender/*>
lib_deps =
    sandeepmistry/LoRa @ 0.8.0
    adafruit/Adafruit INA219 @ 1.2.3
    adafruit/Adafruit MPU6050 @ 2.2.6
    adafruit/Adafruit SSD1306 @ 2.5.9
    milesburton/DallasTemperature @ 3.9.0
    paulstoffregen/OneWire @ 2.3.8
    bblanchon/ArduinoJson @ 7.4.3
    adafruit/Adafruit Unified Sensor @ 1.1.14
    adafruit/Adafruit BusIO @ 1.16.1
    adafruit/Adafruit GFX Library @ 1.11.9

; -------------------------------------------------------------------------------------
; Target 2: Ground Station Receiver (USB Telemetry Bridge)
; -------------------------------------------------------------------------------------
[env:ground_station]
build_src_filter = +<ground_receiver/*>
lib_deps =
    sandeepmistry/LoRa @ 0.8.0
    bblanchon/ArduinoJson @ 7.4.3
```

### CLI Build & Flashing Commands:

```bash
# Build Satellite Flight Computer firmware
pio run -e satellite

# Upload Satellite Firmware (specify port if multiple ESP32s connected)
pio run -e satellite -t upload --upload-port /dev/ttyUSB0

# Build & Upload Ground Station Receiver
pio run -e ground_station -t upload --upload-port /dev/ttyUSB1

# Open high-speed Ground Station Serial Monitor
pio device monitor -b 115200 --port /dev/ttyUSB1
```

---

## 5. Arduino IDE 2.x Step-by-Step Setup Guide

### 5.1 ESP32 Board Package Installation
1. Launch **Arduino IDE 2.x**.
2. Navigate to **File $\rightarrow$ Preferences** (or `Ctrl + ,` / `Cmd + ,`).
3. In the **Additional boards manager URLs** field, insert the official Espressif package URL:
   ```text
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
4. Click **OK**. Open the Boards Manager from the left icon bar (`Ctrl + Shift + B`), search for **`esp32`** by *Espressif Systems*, and click **Install** (version `2.0.14` or `3.0.x`).

### 5.2 Board Configuration Parameters
Under the **Tools** menu, configure the exact board options:
- **Board:** `ESP32 Arduino` $\rightarrow$ `ESP32 Dev Module`
- **CPU Frequency:** `240MHz (WiFi/BT)`
- **Flash Frequency:** `80MHz`
- **Flash Mode:** `QIO`
- **Flash Size:** `4MB (32Mb)`
- **Partition Scheme:** `Default 4MB with spiffs (1.2MB APP/1.5MB SPIFFS)`
- **Core Debug Level:** `None` (or `Info` during bench debugging)
- **Upload Speed:** `921600` (Fall back to `115200` if using cheap USB cables)
- **Port:** Select corresponding `/dev/ttyUSBx` (Linux) or `COMx` (Windows)

---

## 6. Flashing & Bench Verification Procedure

### 6.1 Unit 1: Ground Station Unit (Receiver)
1. Connect the **Ground Station ESP32** to the workstation via USB.
2. Open `/home/alokd/Documents/StellarSense/firmware/ground_receiver/ground_receiver.ino`.
3. Select the correct serial port under **Tools $\rightarrow$ Port**.
4. Click **Upload** (`Ctrl + U`).
5. After upload completes:
   - The **active buzzer on D13** emits a crisp 100ms power-on confirmation chirp.
   - Open the Serial Monitor @ **115200 baud**.
6. Verify the boot banner appears:
   ```json
   {"system":"GROUND_STATION","status":"READY","freq":433.0,"crc":true}
   ```
7. **CRITICAL STEP:** **Close the Arduino Serial Monitor window!**  
   The Chrome Web Serial API requires exclusive access to the USB serial port. Leaving the Arduino Serial Monitor open will lock the COM port and block Mission Control from connecting.

### 6.2 Unit 2: Satellite Flight Computer (Transmitter)
1. Connect the **Satellite ESP32** to a second USB port (or USB power brick).
2. Open `/home/alokd/Documents/StellarSense/firmware/satellite_sender/satellite_sender.ino`.
3. Select its port under **Tools $\rightarrow$ Port** and click **Upload**.
4. Observe the physical boot sequence:
   - Green, Yellow, and Red status LEDs flash in sequence during power-on self-test (POST).
   - 0.96" OLED screen initializes, displaying:
     ```text
     STELLARSENSE [NOMINAL]
     T: 24.5C  VIB: 0.04g
     V: 5.02V  I: 312mA
     P: 1566mW P/R: 0/0
     PKT: 1    RF: 433MHz
     ```
   - Onboard **Green LED** illuminates steady, confirming all subsystem health checks passed. (Audible alerts are sounded through the Ground Station buzzer on D13).

---

## 7. Aerospace Avionics Troubleshooting Guide

| Symptom / Error | Root Cause | Engineering Solution |
|:---|:---|:---|
| `A fatal error occurred: Failed to connect to ESP32: Timed out waiting for packet header` | ESP32 auto-program transistor timing circuit failed to pull GPIO 0 LOW. | Hold down the physical **BOOT** button on the ESP32 DevKit when the upload starts showing `Connecting........_____`, then release when writing begins. Alternatively, solder a $10\,\mu\text{F}$ electrolytic capacitor between `EN` and `GND`. |
| Linux permission denied: `/dev/ttyUSB0` | Current Linux user account lacks permission to access dialout serial devices. | Add user to dialout group: `sudo usermod -a -G dialout $USER`. Log out and log back in, or run `sudo chmod 666 /dev/ttyUSB0`. |
| `LoRa init failed!` on Serial Console | SPI bus wiring fault, loose NSS/RST jumpers, or Ra-02 module unpowered. | Check SPI pin continuity: SCK (18), MISO (19), MOSI (23), NSS (27), RST (14), DIO0 (26). Verify Ra-02 VCC is securely connected to `3V3`. |
| OLED screen remains dark / blank | $I^2C$ address mismatch or bus held LOW by hung slave. | Verify OLED is at `0x3C`. Ensure common ground is connected. Run the autonomous bus clearance routine. |
| Ground Station receives zero packets | Antenna missing, frequency mismatch, or Hardware CRC configuration mismatch. | Verify both units run with `LoRa.enableCrc()`. Ensure both are configured for `433E6` carrier frequency and sync word `0xF3`. Confirm antennas are firmly attached. |
| Dashboard says "Access to serial port denied" | Arduino IDE Serial Monitor or another terminal instance is holding the port. | Close all Arduino IDE Serial Monitors, Putty, or screen sessions before clicking **CONNECT GROUND STATION** in Google Chrome. |
