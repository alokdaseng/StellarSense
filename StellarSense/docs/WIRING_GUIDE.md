# 🛰️ StellarSense Hardware Wiring, Pinout & Electrical Architecture Guide

**System:** StellarSense Miniature Satellite Health Monitor & Ground Station Telemetry System  
**Document Classification:** Spacecraft Avionics & Electrical Ground Support Equipment (EGSE) Specification  
**Target Hardware:** Dual ESP32-WROOM-32 DevKit (30-Pin), Ra-02 SX1278 (433 MHz LoRa), INA219, Dual MPU-6050, DS18B20, SSD1306 OLED, 5V Active Buzzer  
**Revision:** 2.0.0-RELEASE  

---

## 1. Executive Electrical Overview

StellarSense implements a dual-unit aerospace telemetry architecture:
1. **Satellite Flight Computer (On-Board Computer - OBC)**: An ESP32 DevKit running dual-core FreeRTOS firmware, multiplexing five heterogeneous physical sensing nodes across $I^2C$, 1-Wire, and SPI buses, with hardware Fault Detection, Isolation, and Recovery (FDIR) annunciators.
2. **Ground Station Receiver**: An ESP32 DevKit operating an SX1278 transceiver in continuous low-noise reception mode, feeding link-budget-enriched telemetry directly to the Mission Control workstation over USB-UART.

This guide provides an authoritative electrical pinout, strapping pin safety analysis, schematic wiring diagrams, power budget calculations, and bus engineering justifications.

---

## 2. Authoritative 30-Pin ESP32 DevKit Pinout Table

The table below details all 30 pins of the standard ESP32 DevKit V1 (30-pin layout), mapping their electrical characteristics, boot strapping behaviors, and assigned flight roles in the StellarSense OBC.

| Physical Pin # | Pin Label | ESP32 GPIO | Primary Flight Subsystem | Bus / Signal Function | Direction / Mode | Operating Voltage | Boot Strapping & Safety Notes |
|:---:|:---|:---|:---|:---|:---:|:---:|:---|
| **1** | `3V3` | Power | Regulated 3.3V Rail | Power Supply Output | Output | +3.3V DC | Sourced from onboard AMS1117 / ME6211 LDO regulator (max 800mA). |
| **2** | `GND` | Power | Ground Reference | Common System Ground | Reference | 0.0V | Star-ground tie point for all digital logic and RF decoupling. |
| **3** | `D15` | GPIO 15 | Unconnected (Expansion) | MTDO / Touch 3 / HSPI SS | Input/Output | +3.3V | **Strapping Pin**: Internal weak pull-up. Controls ROM boot message output. |
| **4** | `D2` | GPIO 2 | Unused on Satellite (RX LED on GS) | Onboard Blue LED / HSPI WP | Output | +3.3V | **Strapping Pin**: Must be LOW/floating during flash download. Safe post-boot. |
| **5** | `D4` | GPIO 4 | DS18B20 Temperature Probe | 1-Wire Bidirectional Data | Open-Drain | +3.3V | Requires external $4.7\text{ k}\Omega$ pull-up to 3.3V. Safe strapping behavior. |
| **6** | `RX2` | GPIO 16 | Unconnected (Expansion) | UART2 RX / HSPI CS | Input | +3.3V | General purpose input/output; available for serial payload expansion. |
| **7** | `TX2` | GPIO 17 | Unconnected (Expansion) | UART2 TX / HSPI CLK | Output | +3.3V | General purpose input/output; available for serial payload expansion. |
| **8** | `D5` | GPIO 5 | Unconnected (Expansion) | VSPI CS / Touch 6 | Input/Output | +3.3V | **Strapping Pin**: Internal weak pull-up. Controls SDIO timing during reset. |
| **9** | `D18` | GPIO 18 | Ra-02 SX1278 LoRa | VSPI SCK (Serial Clock) | Output | +3.3V | Hardware SPI Clock line (up to 10 MHz SPI clock supported by SX1278). |
| **10** | `D19` | GPIO 19 | Ra-02 SX1278 LoRa | VSPI MISO (Master In) | Input | +3.3V | Hardware SPI Master-In Slave-Out from SX1278 receiver register. |
| **11** | `D21` | GPIO 21 | Shared $I^2C$ Bus | $I^2C$ SDA (Serial Data) | Open-Drain | +3.3V | Shared across INA219, MPU-6050 #1, MPU-6050 #2, and SSD1306 OLED. |
| **12** | `RX0` | GPIO 3 | USB-UART Console Interface | UART0 RX (Serial RX) | Input | +3.3V | Connected to onboard CP2102/CH340 USB-to-UART bridge. |
| **13** | `TX0` | GPIO 1 | USB-UART Console Interface | UART0 TX (Serial TX) | Output | +3.3V | Telemetry downlink stream to local host @ 115200 baud. |
| **14** | `D22` | GPIO 22 | Shared $I^2C$ Bus | $I^2C$ SCL (Serial Clock) | Open-Drain | +3.3V | 400 kHz Fast Mode clock with autonomous 9-pulse bus clearance. |
| **15** | `D23` | GPIO 23 | Ra-02 SX1278 LoRa | VSPI MOSI (Master Out) | Output | +3.3V | Hardware SPI Master-Out Slave-In to SX1278 configuration registers. |
| **16** | `EN` | Reset | Hardware Reset Button | Chip Enable / Reboot | Input | +3.3V | Active HIGH; pulled to GND via reset button to reboot flight computer. |
| **17** | `VP` | GPIO 36 | Unconnected | ADC1_CH0 / SENSOR_VP | Input Only | Max 3.3V | Pure input pin (no internal pull-up/pull-down resistors). |
| **18** | `VN` | GPIO 39 | Unconnected | ADC1_CH3 / SENSOR_VN | Input Only | Max 3.3V | Pure input pin (no internal pull-up/pull-down resistors). |
| **19** | `D34` | GPIO 34 | Unconnected | ADC1_CH6 / VDET_1 | Input Only | Max 3.3V | Pure input pin (no internal pull-up/pull-down resistors). |
| **20** | `D35` | GPIO 35 | Unconnected | ADC1_CH7 / VDET_2 | Input Only | Max 3.3V | Pure input pin (no internal pull-up/pull-down resistors). |
| **21** | `D32` | GPIO 32 | Yellow LED (Caution) | Discrete FDIR Annunciator | Output | +3.3V | Sinks/sources logic level via $220\,\Omega$ series current-limiting resistor. |
| **22** | `D33` | GPIO 33 | Red LED (Critical Fault) | Discrete FDIR Annunciator | Output | +3.3V | Sinks/sources logic level via $220\,\Omega$ series current-limiting resistor. |
| **23** | `D25` | GPIO 25 | Green LED (Nominal) | Discrete FDIR Annunciator | Output | +3.3V | Sinks/sources logic level via $220\,\Omega$ series current-limiting resistor. |
| **24** | `D26` | GPIO 26 | Ra-02 SX1278 LoRa | DIO0 (RxDone/TxDone IRQ) | Input | +3.3V | Hardware edge interrupt flagging packet transmission/reception complete. |
| **25** | `D27` | GPIO 27 | Ra-02 SX1278 LoRa | NSS / CS (Chip Select) | Output | +3.3V | Active LOW SPI slave select for SX1278 bus transactions. |
| **26** | `D14` | GPIO 14 | Ra-02 SX1278 LoRa | RST (Hardware Reset) | Output | +3.3V | Active LOW radio reset line asserted during transceiver initialization. |
| **27** | `D12` | GPIO 12 | **CRITICAL: LEAVE UNCONNECTED** | MTDI / Strapping Pin | Unconnected | N/A | **MANDATORY SAFETY CONSTRAINT**: See Section 3 below. |
| **28** | `D13` | GPIO 13 | Unconnected on Satellite (Buzzer on GS) | GPIO 13 / Touch 4 | Input/Output | +3.3V | **Final Layout Update:** Buzzer relocated exclusively to Ground Station Unit. |
| **29** | `GND` | Power | Ground Reference | Common System Ground | Reference | 0.0V | Star-ground tie point for sensors and RF return. |
| **30** | `VIN` | Power | Raw 5V DC Bus Input | USB Bus Power (+5V) | Power Input | +5.0V DC | Sourced directly from USB host port (+5.0V ± 5%). |

---

## 3. Strapping Pin Safety & GPIO 12 (MTDI) Deep Dive

The ESP32 microcontroller samples six physical pins at reset to configure internal flash voltage, boot source, and timing. Improper connections to these strapping pins will trap the chip in an unrecoverable bootloop or flash brownout.

```
       ESP32 RESET STATE SAMPLING
                   │
    ┌──────────────┴──────────────┐
    ▼                             ▼
GPIO 0 = HIGH                 GPIO 12 (MTDI) = LOW (Default)
Boot from SPI Flash           VDD_SDIO = 3.3V (Normal Flash Operation)
    │                             │
    │ If GPIO 0 = LOW:            │ If GPIO 12 = HIGH:
    ▼                             ▼
Enters UART Bootloader        VDD_SDIO forced to 1.8V
(Requires serial flashing)     SPI Flash Under-Volt Brownout!
                              Flash Read CRC Failure -> Infinite Bootloop
```

### Critical Safety Rules:

1. **GPIO 12 (MTDI) — Mandatory Open Circuit**:
   - **Internal Function:** During power-on reset (POR), GPIO 12 dictates the output voltage of the ESP32 internal LDO regulator that powers the external SPI flash memory (`VDD_SDIO`).
   - **Logic State 0 (LOW):** `VDD_SDIO` outputs **3.3V** (Standard for 3.3V SPI Flash chips on ESP-WROOM-32 modules).
   - **Logic State 1 (HIGH):** `VDD_SDIO` outputs **1.8V** (Intended for low-voltage 1.8V flash memory variants).
   - **Hazard Analysis:** If GPIO 12 is pulled HIGH or connected to an external sensor with an active pull-up during boot, the internal LDO drops flash voltage from 3.3V to 1.8V. The SPI flash experiences an immediate brownout, fails to return valid instruction opcodes, and causes the ROM bootloader to trigger `flash read err, 1000` in an **infinite reboot loop**.
   - **StellarSense Mandate:** **Pin 27 (`GPIO 12`) must remain strictly unconnected at all times.**

2. **GPIO 0 & GPIO 2**:
   - `GPIO 0` possesses an internal weak pull-up resistor holding it HIGH for standard SPI flash execution. The onboard "BOOT" tactile button pulls it to ground only during manual firmware upload.
   - `GPIO 2` is tied to the onboard blue LED on the DevKit. It must not be pulled HIGH during bootloader entry. In StellarSense, it is utilized exclusively on the Ground Station unit as an output indicator after boot has completed.

3. **GPIO 15 (MTDO)**:
   - Configured with an internal pull-up to enable normal UART0 boot logging. Leaving it unconnected ensures clean boot messages at 115200 baud.

---

## 4. Complete System ASCII Wiring Diagrams

### 4.1 Satellite Flight Computer Interconnect Schematic

```
                                  +-----------------------------------------+
                                  |         ESP32 DEVKIT V1 (30-PIN)        |
                                  |         SATELLITE FLIGHT COMPUTER       |
                                  +-----------------------------------------+
                                  |                                         |
     [+3.3V RAIL] <---------------+ [ 1] 3V3                       VIN [30] +<-------------- [+5V USB POWER]
     [GND RAIL]   <---------------+ [ 2] GND                       GND [29] +<-------------- [GND RETURN]
                                  | [ 3] D15                       D13 [28] | [NC: Buzzer on Ground Station]
                                  | [ 4] D2                        D12 [27] +--- [NC: DO NOT CONNECT!]
[DS18B20 1-WIRE] <================+ [ 5] D4                        D14 [26] +--------------> LoRa [RST]
                                  | [ 6] RX2                       D27 [25] +--------------> LoRa [NSS]
                                  | [ 7] TX2                       D26 [24] +<-------------- LoRa [DIO0]
                                  | [ 8] D5                        D25 [23] +-----[ 220 ]--> [GREEN LED]
LoRa [SCK]       <----------------+ [ 9] D18                       D33 [22] +-----[ 220 ]--> [RED LED]
LoRa [MISO]      <----------------+ [10] D19                       D32 [21] +-----[ 220 ]--> [YELLOW LED]
I2C [SDA]        <===============>+ [11] D21                       D35 [20] |
[USB SERIAL RX]  <----------------+ [12] RX0                       D34 [19] |
[USB SERIAL TX]  ---------------->+ [13] TX0                        VN [18] |
I2C [SCL]        ---------------->+ [14] D22                        VP [17] |
LoRa [MOSI]      ---------------->+ [15] D23                        EN [16] |
                                  +-----------------------------------------+

========================================================================================================
                                   I2C MULTI-DROP SENSOR BUS (GPIO 21 / 22)
========================================================================================================

          GPIO 21 (SDA) ──┬────────────────┬────────────────┬────────────────┐
          GPIO 22 (SCL) ──┼───┐            ├───┐            ├───┐            ├───┐
          +3.3V Rail    ──┼───┼───┐        ├───┼───┐        ├───┼───┐        ├───┼───┐
          GND Rail      ──┼───┼───┼───┐    ├───┼───┼───┐    ├───┼───┼───┐    ├───┼───┼───┐
                          │   │   │   │    │   │   │   │    │   │   │   │    │   │   │   │
                        ┌─┴───┴───┴───┴┐ ┌─┴───┴───┴───┴┐ ┌─┴───┴───┴───┴┐ ┌─┴───┴───┴───┴┐
                        │   INA219     │ │  MPU-6050 #1 │ │  MPU-6050 #2 │ │  SSD1306 OLED │
                        │ EPS Monitor  │ │  Vibration   │ │ Attitude ADCS│ │  0.96" 128x64 │
                        │  Addr: 0x40  │ │  Addr: 0x68  │ │  Addr: 0x69  │ │  Addr: 0x3C   │
                        └──────────────┘ └──────┬───────┘ └──────┬───────┘ └───────────────┘
                                                │                │
                                            [AD0->GND]       [AD0->3.3V]
```

### 4.2 Ground Station Receiver Interconnect Schematic

```
                                  +-----------------------------------------+
                                  |         ESP32 DEVKIT V1 (30-PIN)        |
                                  |           GROUND STATION UNIT           |
                                  +-----------------------------------------+
                                  |                                         |
     [+3.3V TO Ra-02] <-----------+ [ 1] 3V3                       VIN [30] +<-------------- [+5V USB TO BUZZER]
     [GND TO Ra-02]   <-----------+ [ 2] GND                       GND [29] +<-------------- [GND TO HOST & NPN]
                                  | [ 3] D15                       D13 [28] +-----[ 1k ]---> [BUZZER NPN BASE]
[ONBOARD BLUE LED]<---------------+ [ 4] D2 (RX Pulse 40ms)        D12 [27] +--- [NC: DO NOT CONNECT!]
                                  | [ 5] D4                        D14 [26] +--------------> LoRa [RST]
                                  | [ 6] RX2                       D27 [25] +--------------> LoRa [NSS]
                                  | [ 7] TX2                       D26 [24] +<-------------- LoRa [DIO0]
                                  | [ 8] D5                        D25 [23] |
LoRa [SCK]        <---------------+ [ 9] D18                       D33 [22] |
LoRa [MISO]       <---------------+ [10] D19                       D32 [21] |
                                  | [11] D21                       D35 [20] |
[CP2102 USB UART] <===============+ [12] RX0 / [13] TX0            D34 [19] |
                                  | [14] D22                        VN [18] |
LoRa [MOSI]       ----------------+ [15] D23                        VP [17] |
                                  +-----------------------------------------+
                                                │
                                    [USB-C / Micro-USB Cable]
                                                │
                                                ▼
                                  +-----------------------------------------+
                                  |        MISSION CONTROL DASHBOARD        |
                                  |     Google Chrome Web Serial 115200     |
                                  +-----------------------------------------+
```

---

## 5. Subsystem Electrical Circuits & Calculations

### 5.1 5V Active Piezo Buzzer NPN Driver Circuit (Ground Station Unit - ESP32 #2 Only)

> [!NOTE]
> **Final Hardware Update:** As per the updated hardware architecture (Image 3), only **one buzzer** is used in the entire system, located exclusively on the **Ground Station Unit** to alert the mission control operator. The Satellite Unit utilizes its 3 onboard status LEDs (Green, Yellow, Red) and OLED display for local indication.

Driving an electromagnetic or active piezo buzzer directly from a microcontroller GPIO is prohibited in aerospace avionics for three engineering reasons:
1. **Current Starvation:** An active 5V buzzer demands $30\text{ mA}$ of current. The ESP32 recommended output sink/source current per pin is $12\text{ mA}$ ($40\text{ mA}$ absolute maximum rating). Sustained $30\text{ mA}$ draw degrades the internal output stage FET.
2. **Inductive Flyback Kickback:** Piezo and magnetic diaphragms generate negative inductive back-EMF voltage spikes exceeding $-15\text{V}$ upon turn-off, which will blow the ESD clamping diodes on the MCU silicon.
3. **Acoustic Pressure (SPL):** Powered from 3.3V, a 5V buzzer operates below its resonance threshold, yielding a quiet, muffled alarm. Sourcing from the raw 5V VIN rail delivers full $85\text{ dBA}$ sound pressure level.

#### Schematic:

```
              +5V (VIN Rail)
                   │
                   ├──[ + ] ACTIVE PIEZO BUZZER
                   │        (30mA Nominal Load)
                   │  [ - ]
                   ├───┬────────────────┐
                   │   │                │
                   │   ▼ 1N4148 / 1N4007│ (Flyback Clamping Diode:
                   │   ─ (Cathode to 5V)│  Protects NPN from Inductive
                   │   │                │  Turn-Off Transients)
                   │   └────────────────┘
                   │
                   ▼ Collector (C)
                 ┌───┐
GPIO 13 ──[1kΩ]──┤ B │  2N2222 / BC547 NPN Transistor
                 └───┘
                   │ Emitter (E)
                   ▼
                  GND
```

#### Transistor Bias Calculation:

The 2N2222 NPN transistor acts as a saturated low-side switch.

1. **Base Voltage & Current:**
   $$\text{ESP32 Logic HIGH Output } V_{OH} = 3.3\text{ V}$$
   $$\text{Base-Emitter Forward Diode Drop } V_{BE(sat)} \approx 0.70\text{ V}$$
   $$\text{Voltage Drop across Base Resistor } V_{R_B} = V_{OH} - V_{BE(sat)} = 3.3\text{ V} - 0.70\text{ V} = 2.60\text{ V}$$
   $$I_B = \frac{V_{R_B}}{R_B} = \frac{2.60\text{ V}}{1000\,\Omega} = 2.60\text{ mA}$$

2. **Collector Saturation & Overdrive Ratio:**
   $$\text{Collector Load Current } I_C \approx 30.0\text{ mA}$$
   $$\text{Forced Beta / Saturation Overdrive } \beta_{\text{forced}} = \frac{I_C}{I_B} = \frac{30.0\text{ mA}}{2.60\text{ mA}} \approx 11.54$$

   Because the standard small-signal current gain $h_{FE}$ of a 2N2222 is between $75$ and $300$, a forced beta of $\approx 11.5$ guarantees **deep saturation**.
   $$\text{Collector-to-Emitter Saturation Voltage } V_{CE(sat)} \le 0.15\text{ V}$$
   $$\text{Buzzer Operating Voltage } V_{\text{buzzer}} = 5.0\text{ V} - V_{CE(sat)} \approx 4.85\text{ V}$$
   The buzzer receives $97\%$ of the full $5\text{V}$ rail voltage, maximizing alarm volume while loading GPIO 13 with only an ultra-safe $2.6\text{ mA}$.

---

### 5.2 3.3V Power Rail Budget & LDO Thermal Analysis

The ESP32 DevKit incorporates an onboard linear low-dropout regulator (LDO) — typically an **AMS1117-3.3** (SOT-223 package, rated for $800\text{ mA}$) or a **ME6211** (SOT-23-5 package, rated for $500\text{ mA}$).

All 3.3V digital logic and the RF transceiver draw power from this single regulator. The table below details the steady-state nominal and peak current consumption across all flight subsystems:

| Subsystem Component | Operating Voltage | Steady-State Current ($I_{\text{nom}}$) | Peak Dynamic Current ($I_{\text{peak}}$) | Power Rail Source | Electrical Constraint / Condition |
|:---|:---:|:---:|:---:|:---:|:---|
| **ESP32 MCU Core** | 3.3V | 50.0 mA | 80.0 mA | 3.3V LDO Rail | Dual-core active @ 240 MHz (Wi-Fi/BT modems powered down). |
| **Ra-02 SX1278 (LoRa)** | **3.3V STRICT** | 12.0 mA | 120.0 mA | 3.3V LDO Rail | Peak during $+17\text{ dBm}$ PA_BOOST RF packet downlink transmission. |
| **MPU-6050 #1 (Vib DSP)** | 3.3V | 3.8 mA | 4.0 mA | 3.3V LDO Rail | Continuous internal accelerometer ADC sampling @ 20 Hz. |
| **MPU-6050 #2 (ADCS)** | 3.3V | 3.8 mA | 4.0 mA | 3.3V LDO Rail | Continuous internal gyro + accel sampling with DMP active. |
| **INA219 Power Monitor** | 3.3V | 1.0 mA | 1.0 mA | 3.3V LDO Rail | Continuous ADC voltage & shunt current sensing. |
| **DS18B20 Temp Probe** | 3.3V | 1.0 mA | 1.5 mA | 3.3V LDO Rail | Active 10-bit thermal conversion cycle ($187.5\text{ ms}$). |
| **DS18B20 Pull-Up** | 3.3V | 0.0 mA | 0.7 mA | 3.3V LDO Rail | Current through $4.7\text{ k}\Omega$ resistor when 1-Wire pin pulled LOW. |
| **SSD1306 0.96" OLED** | 3.3V | 15.0 mA | 25.0 mA | 3.3V LDO Rail | Dependent on lit pixel count (white OLED array display). |
| **Status LEDs (x3 max)** | 3.3V | 5.9 mA | 17.7 mA | 3.3V LDO Rail | $I_{\text{LED}} = \frac{3.3\text{V} - 2.0\text{V}}{220\,\Omega} \approx 5.9\text{ mA}$ each. Worst-case all 3 lit at boot. |
| **Active 5V Buzzer** | **5.0V VIN** | **0.0 mA** | **0.0 mA** | **5V VIN Rail** | **ISOLATED FROM 3.3V RAIL** via 2N2222 NPN switch. |
| **TOTAL 3.3V RAIL LOAD** | **3.3V** | **92.5 mA** | **253.9 mA** | **LDO Output** | **Peak load is 31.7% of 800mA AMS1117 rating (68.3% Margin)** |

#### Thermal Headroom Calculation:

$$V_{\text{in}} = 5.0\text{ V}, \quad V_{\text{out}} = 3.3\text{ V}, \quad \Delta V = 1.7\text{ V}$$
$$P_{\text{diss(peak)}} = \Delta V \times I_{\text{peak}} = 1.7\text{ V} \times 0.2539\text{ A} \approx 0.432\text{ W}$$

For an AMS1117 SOT-223 package with junction-to-ambient thermal resistance $\theta_{JA} \approx 90^\circ\text{C/W}$:
$$\Delta T = P_{\text{diss}} \times \theta_{JA} = 0.432\text{ W} \times 90^\circ\text{C/W} \approx 38.8^\circ\text{C}$$
$$\text{Junction Temperature } T_J = 25^\circ\text{C} + 38.8^\circ\text{C} = 63.8^\circ\text{C} \ll 125^\circ\text{C (Maximum Rating)}$$

The voltage regulator operates well within safe thermal dissipation limits with zero risk of thermal throttling or shutdown.

> [!CAUTION]
> **SX1278 Over-Voltage Destruction Warning:**  
> The Semtech SX1278 datasheet specifies an **Absolute Maximum Supply Voltage of 3.9V**. Connecting the Ra-02 VCC line to the 5V rail will result in instantaneous dielectric breakdown of the RF CMOS front-end. The Ra-02 must strictly connect to the regulated **`3V3`** pin.

---

### 5.3 Shared $I^2C$ Bus Fast Mode Electrical Validation

StellarSense multiplexes four slave devices onto a single physical two-wire interface on `GPIO 21` (SDA) and `GPIO 22` (SCL) operating at **400 kHz Fast Mode** (`Wire.setClock(400000)`).

```
              +3.3V Rail
                  │
                  ├──[ R_pullup_eq ≈ 2.5kΩ ]── GPIO 21 (SDA)
                  │
                  ├──[ R_pullup_eq ≈ 2.5kΩ ]── GPIO 22 (SCL)
                  │
         ┌────────┴────────┬────────────────┬────────────────┐
         ▼                 ▼                ▼                ▼
   INA219 (0x40)     MPU-6050 #1      MPU-6050 #2      SSD1306 (0x3C)
   EPS Monitor       Vibration (0x68) Attitude (0x69)  OLED Display
                     [AD0 to GND]     [AD0 to 3.3V]
```

#### Address Disambiguation:
- **INA219 Power Monitor:** Address `0x40` (A0 and A1 solder jumpers open).
- **MPU-6050 #1 (Vibration DSP):** Pin `AD0` wired to `GND` selects primary address `0x68`.
- **MPU-6050 #2 (ADCS Attitude):** Pin `AD0` wired to `3V3` pulls the internal address bit HIGH, selecting secondary address `0x69`.
- **SSD1306 OLED:** Address `0x3C` (Factory hardwired).
- **Contention Proof:** Addresses `0x3C`, `0x40`, `0x68`, and `0x69` are completely distinct. Zero collision risk exists.

#### Parallel Pull-Up Resistance Calculation:
Breakout boards for GY-521 (MPU-6050), INA219, and SSD1306 each incorporate onboard pull-up resistors connected to 3.3V:
- MPU-6050 #1 GY-521 board: $10\text{ k}\Omega$ on SDA & SCL
- MPU-6050 #2 GY-521 board: $10\text{ k}\Omega$ on SDA & SCL
- INA219 breakout board: $10\text{ k}\Omega$ on SDA & SCL
- SSD1306 OLED breakout: $10\text{ k}\Omega$ on SDA & SCL

Equivalent parallel resistance on each line:
$$\frac{1}{R_{\text{eq}}} = \frac{1}{10\text{ k}\Omega} + \frac{1}{10\text{ k}\Omega} + \frac{1}{10\text{ k}\Omega} + \frac{1}{10\text{ k}\Omega} = \frac{4}{10\text{ k}\Omega} \implies R_{\text{eq}} = 2.50\text{ k}\Omega$$

#### $I^2C$ Standard Compliance:
1. **Low-Level Output Sink Current ($I_{OL}$):**
   $$I_{OL} = \frac{V_{DD} - V_{OL}}{R_{\text{eq}}} = \frac{3.3\text{ V} - 0.4\text{ V}}{2500\,\Omega} = 1.16\text{ mA}$$
   The NXP $I^2C$ specification establishes a maximum allowable sink current of $3.0\text{ mA}$ for Fast Mode devices. A sink current of $1.16\text{ mA}$ is well within the driver capabilities of all four ICs, preventing bus voltage rise during ACK pulses.

2. **Bus Rise Time ($t_r$):**
   Breadboard parasitic capacitance across 4 sensor jumper wire pairs is measured at approximately $C_b \approx 45\text{ pF}$.
   $$t_r = 0.8473 \times R_{\text{eq}} \times C_b = 0.8473 \times 2500\,\Omega \times 45 \times 10^{-12}\text{ F} \approx 95.3\text{ ns}$$
   The NXP Fast Mode specification dictates $t_r \le 300\text{ ns}$. An edge rise time of $\approx 95\text{ ns}$ ensures sharp, monotonic square waves without ringing or false double-clocking.
   **Conclusion:** **No additional external pull-up resistors are required or permitted on the $I^2C$ lines.**

---

### 5.4 1-Wire Thermal Sensor Interface (DS18B20)

The Maxim DS18B20 digital thermometer operates over a single-wire digital communications bus (`GPIO 4`).

```
                    +3.3V Rail
                        │
                        └──[ 4.7kΩ Pull-Up ]──┐
                                              │
ESP32 GPIO 4 ─────────────────────────────────┼── DS18B20 Yellow/White (DATA)
ESP32 GND    ─────────────────────────────────┴── DS18B20 Black/Blue   (GND)
ESP32 3V3    ──────────────────────────────────── DS18B20 Red          (VDD)
```

- **Resistor Specification:** A dedicated $4.7\text{ k}\Omega \pm 5\%$ metal-film pull-up resistor is installed between `GPIO 4` and `3.3V`.
- **Mode of Operation:** The 1-Wire protocol relies on an open-drain bus architecture where the bus master and slave only pull the line LOW. The $4.7\text{ k}\Omega$ pull-up pulls the line HIGH with a rise time $\tau \approx 4.7\text{ k}\Omega \times 30\text{ pF} \approx 141\text{ ns}$, satisfying Dallas 1-Wire timing tolerances.

---

### 5.5 Ra-02 SX1278 SPI Bus Connections

The Semtech SX1278 RF transceiver communicates with the ESP32 via the hardware VSPI controller:

| Ra-02 Pin | ESP32 GPIO | VSPI Function | Signal Direction | Design Consideration |
|:---|:---|:---|:---:|:---|
| **VCC** | `3V3` | Power Supply | Input | Must connect to 3.3V rail. Peak TX current = 120mA. |
| **GND** | `GND` | Ground Reference | Reference | Tie directly to ESP32 ground pin. |
| **SCK** | `GPIO 18` | Serial Clock | Input (from ESP32) | Hardware SPI clock; lines kept under 15cm on breadboard. |
| **MISO** | `GPIO 19` | Master In / Slave Out | Output (to ESP32) | High-impedance tri-state line when NSS is HIGH. |
| **MOSI** | `GPIO 23` | Master Out / Slave In | Input (from ESP32) | Hardware SPI data out. |
| **NSS** | `GPIO 27` | Slave Select | Input (from ESP32) | Active LOW; controlled automatically by LoRa driver. |
| **RST** | `GPIO 14` | Hardware Reset | Input (from ESP32) | Active LOW; pulsed during initialization sequence. |
| **DIO0** | `GPIO 26` | Digital I/O 0 (IRQ) | Output (to ESP32) | Configured in SX1278 for `RxDone` and `TxDone` interrupts. |

> [!NOTE]
> **Antenna Requirement:** Never power or transmit on the Ra-02 module without an attached 433 MHz helical spring or SMA whip antenna. Operating the transmitter at $+17\text{ dBm}$ without an antenna produces an impedance mismatch with a Voltage Standing Wave Ratio (VSWR) $> 10:1$, which reflects RF power back into the final amplifier stage and can permanently destroy the power amplifier.

---

## 6. Pre-Power-On Hardware Verification Checklist

Before inserting USB cables or applying power, execute this 6-point electrical sanity inspection using a digital multimeter:

- [ ] **1. Continuity & Ground Loop Check:** Measure continuity ($0.0\,\Omega$) between all sensor GND pins, DevKit GND pins, and the 2N2222 emitter.
- [ ] **2. 3.3V Rail Isolation:** Measure resistance between `3V3` and `GND`. It must measure $> 1.0\text{ k}\Omega$. A reading $< 10\,\Omega$ indicates a dead short; DO NOT POWER ON.
- [ ] **3. GPIO 12 Open Circuit Verification:** Visually and electrically verify that Pin 27 (`GPIO 12`) has **no wire connected**.
- [ ] **4. Dual MPU-6050 AD0 Polarity:**
  - On MPU-6050 #1 (Vibration): Verify `AD0` is wired to `GND` ($0\,\Omega$).
  - On MPU-6050 #2 (Attitude): Verify `AD0` is wired to `3V3` ($0\,\Omega$).
- [ ] **5. NPN Transistor Pinout:** Confirm 2N2222 pin orientation (Flat face forward, pins pointing down: Left = Emitter, Center = Base, Right = Collector). Confirm flyback diode cathode (striped end) connects to $+5\text{V}$.
- [ ] **6. LoRa VCC Verification:** Trace the red wire from the Ra-02 module to the ESP32. Confirm it terminates on **`3V3` (Pin 1)** and NOT on `VIN` (Pin 30).
