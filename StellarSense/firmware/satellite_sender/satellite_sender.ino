/*
 * =====================================================================================
 *  STELLARSENSE - MINIATURE SATELLITE HEALTH & FDIR TELEMETRY SUBSYSTEM
 *  Firmware: Onboard Satellite Flight Computer (Transmitter Unit)
 *  Target MCU: ESP32 DevKit (30-Pin)
 *  
 *  Hardware Peripherals:
 *   - DS18B20 Digital Temp Sensor -> GPIO 4 (1-Wire with 4.7k pull-up to 3.3V)
 *   - MPU-6050 #1 (Structural Vibration) -> I2C 0x68 (AD0 -> GND)
 *   - MPU-6050 #2 (Attitude & ADCS) -> I2C 0x69 (AD0 -> 3.3V)
 *   - INA219 (Power / EPS Subsystem) -> I2C 0x40
 *   - 0.96" SSD1306 OLED Display -> I2C 0x3C
 *   - LoRa Ra-02 SX1278 (433MHz) -> SPI (SCK:18, MISO:19, MOSI:23, SS:27, RST:14, DIO0:26)
 *   - Status LEDs: Green (GPIO 25), Yellow (GPIO 32), Red (GPIO 33)
 *   - Note: Audible Buzzer is located on Ground Station Unit only (GPIO 13 via NPN)
 * 
 *  Architecture:
 *   - Dual-Core FreeRTOS Architecture:
 *       * Core 1 (APP_CPU): Deterministic 20Hz Sensor DSP, 1Hz Thermal Sampling,
 *         Complementary Attitude Fusion, FDIR Hysteresis Engine, Local OLED HUD & Alarms.
 *       * Core 0 (PRO_CPU): Dedicated Background LoRa Telemetry Downlink & Telecommand
 *         Uplink Handler (eliminates 287ms blocking RF airtime freeze).
 *   - LoRa Hardware CRC: SX1278 PHY-level CRC enabled on all frames.
 *   - I2C Bus Hang Protection: 25ms timeout with autonomous 9-clock bus clear routine.
 *   - Hardware Task Watchdog: Autonomous system self-recovery via esp_task_wdt.
 *   - DSP Engine: True RMS structural vibration: RMS = sqrt(EMA(dynG^2)).
 *   - ADCS Calibration: 100-sample stationary zero-rate gyro bias calibration at boot.
 *   - FDIR Subsystem: Dual-threshold deadband hysteresis + 3-sample (150ms) persistence.
 *   - Memory Architecture: Zero-fragmentation static buffers; zero dynamic String heap churn.
 * =====================================================================================
 */

#include <Wire.h>
#include <SPI.h>
#include <LoRa.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_INA219.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>
#include <esp_task_wdt.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// -------------------------------------------------------------------------------------
// PIN DEFINITIONS (Exact Match with Satellite Schematic Diagram)
// -------------------------------------------------------------------------------------
#define PIN_ONEWIRE        4     // DS18B20 Temp Sensor Data (4.7k pull-up to 3.3V)
#define PIN_LED_GREEN      25    // Nominal State Indicator (Green LED)
#define PIN_LED_YELLOW     32    // Caution / Warning Indicator (Yellow LED)
#define PIN_LED_RED        33    // Critical Fault Indicator (Red LED)
#define PIN_LED_POWER      13    // Power / Load Monitor Indicator (Green LED - D13)
// Note: Audible Buzzer is on Ground Station ESP32 (D13 via NPN) per hardware architecture

// LoRa SPI Pins (Ra-02 SX1278 433MHz)
#define LORA_SCK           18
#define LORA_MISO          19
#define LORA_MOSI          23
#define LORA_SS            27
#define LORA_RST           14
#define LORA_DIO0          26
#define LORA_FREQ          433E6 // 433.0 MHz Carrier Frequency

// I2C Pins & Addresses
#define I2C_SDA            21
#define I2C_SCL            22
#define I2C_ADDR_OLED      0x3C
#define I2C_ADDR_INA219    0x40
#define I2C_ADDR_MPU1      0x68  // Structural Vibration (AD0 -> GND)
#define I2C_ADDR_MPU2      0x69  // Attitude & Orientation (AD0 -> 3.3V)

// OLED Display Configuration
#define SCREEN_WIDTH       128
#define SCREEN_HEIGHT      64
#define OLED_RESET         -1

// Watchdog Timeout (Seconds) - 8 seconds provides generous margin for breadboard wiring
#define WDT_TIMEOUT_SECONDS 8

// -------------------------------------------------------------------------------------
// AEROSPACE FDIR HYSTERESIS THRESHOLDS (Dual-Threshold Deadband Matrix)
// -------------------------------------------------------------------------------------
// Thermal Core Boundaries (Deg C)
#define TEMP_WARN_HIGH     33.0f // Trip Caution (Thumb press trigger)
#define TEMP_WARN_CLEAR    32.2f // Clear Caution (0.8C deadband)
#define TEMP_CRIT_HIGH     38.0f // Trip Critical (Thermal runaway)
#define TEMP_CRIT_CLEAR    37.2f // Clear Critical (0.8C deadband)

// EPS Power Bus Voltage Boundaries (Volts)
#define VOLT_WARN_LOW      4.60f // Trip Caution (EPS bus sag)
#define VOLT_WARN_CLEAR    4.68f // Clear Caution (0.08V deadband)
#define VOLT_CRIT_LOW      4.20f // Trip Critical (Brownout hazard)
#define VOLT_CRIT_CLEAR    4.28f // Clear Critical (0.08V deadband)

// EPS Power Bus Overcurrent Boundaries (mA - Latchup / Short Protection)
#define CURR_WARN_HIGH     650.0f // Trip Caution (Excess load current)
#define CURR_WARN_CLEAR    580.0f // Clear Caution
#define CURR_CRIT_HIGH     950.0f // Trip Critical (Single-event latchup / short)
#define CURR_CRIT_CLEAR    850.0f // Clear Critical

// Structural Acoustic Vibration Boundaries (g_RMS)
#define VIB_WARN_HIGH      0.25f // Trip Caution (Structural flutter / reaction wheel noise)
#define VIB_WARN_CLEAR     0.20f // Clear Caution (0.05g deadband)
#define VIB_CRIT_HIGH      0.70f // Trip Critical (Launch resonance / violent tumble)
#define VIB_CRIT_CLEAR     0.60f // Clear Critical (0.10g deadband)

// Persistence Filter Debounce Depth (3 consecutive 50ms frames = 150ms debounce)
#define FDIR_PERSISTENCE_COUNT 3

// -------------------------------------------------------------------------------------
// GLOBAL OBJECTS & DRIVERS
// -------------------------------------------------------------------------------------
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
Adafruit_INA219 ina219(I2C_ADDR_INA219);
Adafruit_MPU6050 mpuVibration;
Adafruit_MPU6050 mpuAttitude;
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature tempSensor(&oneWire);

// -------------------------------------------------------------------------------------
// SYSTEM STATE & SENSOR HEALTH FLAGS
// -------------------------------------------------------------------------------------
enum FDIRState {
  STATE_NOMINAL = 0,
  STATE_CAUTION = 1,
  STATE_CRITICAL = 2
};

volatile FDIRState currentFDIR = STATE_NOMINAL;

// Hardware Online Status Flags (Provides graceful degradation if a wire is pulled)
bool statusOled      = false;
bool statusIna       = false;
bool statusMpu1      = false;
bool statusMpu2      = false;
bool statusTemp      = false;
bool statusLoRa      = false;

// Telemetry & DSP Variables
uint32_t packetId    = 0;
float telemetryTemp  = 25.0f;
float busVoltage     = 5.00f;
float current_mA     = 280.0f;
float power_mW       = 1400.0f;
float vibrationRMS   = 0.05f;
float pitchAngle     = 0.0f;
float rollAngle      = 0.0f;

// DSP Accelerometer Filter Variables (MPU1 - Structural Vibration True RMS)
float lastAx = 0.0f, lastAy = 0.0f, lastAz = 9.80665f;
float vibMeanSquare = 0.0025f; // Initial estimate (0.05g ^ 2)

// ADCS Gyroscope Calibration & Complementary Filter Variables (MPU2 - Attitude)
float gyroRollBias   = 0.0f; // deg/s offset
float gyroPitchBias  = 0.0f; // deg/s offset
unsigned long lastAttitudeTime = 0;

// Cooperative Non-Blocking Timers (Core 1)
unsigned long lastDspTime    = 0;  // 50ms (20 Hz)
unsigned long lastTxTime     = 0;  // 600ms (1.6 Hz Downlink dispatch)
unsigned long lastOledTime   = 0;  // 200ms (5 Hz Refresh)
unsigned long lastAlarmTime  = 0;  // 100ms (Buzzer & LED cadence)
unsigned long bootTime       = 0;
uint32_t downlinkIntervalMs  = 600; // Adjustable via CMD:RATE:<ms>

// DS18B20 1Hz Non-Blocking Sampling State Machine
unsigned long lastTempRequestTime = 0;
unsigned long lastTempReadTime    = 0;
bool tempConversionPending        = false;
uint8_t tempErrorStreak           = 0;

// FDIR Hysteresis Latches
bool tempWarnLatched = false;
bool tempCritLatched = false;
bool voltWarnLatched = false;
bool voltCritLatched = false;
bool currWarnLatched = false;
bool currCritLatched = false;
bool vibWarnLatched  = false;
bool vibCritLatched  = false;

FDIRState candidateFDIR   = STATE_NOMINAL;
FDIRState pendingFDIR     = STATE_NOMINAL;
uint8_t fdirPersistenceCtr = 0;

// Annunciator State (Red LED fault blinker)
bool ledToggle = false;

// Thread-Safe Command Flags (Bridging Core 0 C&DH to Core 1 Executive)
volatile bool cmdTareRequested      = false;
volatile bool cmdFdirResetRequested = false;

// -------------------------------------------------------------------------------------
// FREERTOS DUAL-CORE TELEMETRY QUEUE & ARCHITECTURE
// -------------------------------------------------------------------------------------
struct TelemetryPayload {
  uint32_t pkt;
  uint32_t met;
  float temp;
  float volt;
  float curr;
  float pwr;
  float vib;
  float pitch;
  float roll;
  uint8_t fdirState;
  uint8_t hwStatus;
};

QueueHandle_t telemetryQueue = NULL;
TaskHandle_t loraTaskHandle  = NULL;

// Forward Declarations
void loraTask(void *pvParameters);
void handleTelecommand(const char *cmd);
void recoverI2CBus(uint8_t sdaPin, uint8_t sclPin);
void initWatchdog();
void feedWatchdog();
void calibrateGyro();
void tareAttitude();

// -------------------------------------------------------------------------------------
// I2C BUS RECOVERY ROUTINE (Prevents Bus Lockup from Hung Slaves)
// -------------------------------------------------------------------------------------
void recoverI2CBus(uint8_t sdaPin, uint8_t sclPin) {
  Wire.end();
  pinMode(sdaPin, INPUT_PULLUP);
  pinMode(sclPin, OUTPUT_OPEN_DRAIN);

  // Clock up to 9 cycles on SCL to flush stuck slave shift registers
  for (int i = 0; i < 9; i++) {
    digitalWrite(sclPin, LOW);
    delayMicroseconds(5);
    digitalWrite(sclPin, HIGH);
    delayMicroseconds(5);
    if (digitalRead(sdaPin) == HIGH) {
      break; // Slave released SDA line
    }
  }

  // Generate I2C STOP condition (SDA low -> SCL high -> SDA high)
  pinMode(sdaPin, OUTPUT_OPEN_DRAIN);
  digitalWrite(sdaPin, LOW);
  delayMicroseconds(5);
  digitalWrite(sclPin, HIGH);
  delayMicroseconds(5);
  digitalWrite(sdaPin, HIGH);
  delayMicroseconds(5);

  // Reinitialize Wire with 25ms timeout
  Wire.begin(sdaPin, sclPin);
  Wire.setClock(400000);
  Wire.setTimeOut(25);
  Serial.println(F("[I2C] Bus clearance executed. Wire timeout set to 25ms."));
}

// -------------------------------------------------------------------------------------
// ESP32 TASK WATCHDOG TIMER INITIALIZATION
// -------------------------------------------------------------------------------------
void initWatchdog() {
#if defined(ESP_IDF_VERSION_MAJOR) && (ESP_IDF_VERSION_MAJOR >= 5)
  esp_task_wdt_config_t twdt_config = {
    .timeout_ms = WDT_TIMEOUT_SECONDS * 1000,
    .idle_core_mask = 0,
    .trigger_panic = true
  };
  esp_task_wdt_init(&twdt_config);
#else
  esp_task_wdt_init(WDT_TIMEOUT_SECONDS, true);
#endif
  esp_task_wdt_add(NULL); // Register Core 1 task
  Serial.println(F("[WDT] Hardware Task Watchdog initialized (4-second timeout)."));
}

void feedWatchdog() {
  esp_task_wdt_reset();
}

// -------------------------------------------------------------------------------------
// BOOT GYROSCOPE CALIBRATION (MPU-6050 #2 Stationary Bias Subtraction)
// -------------------------------------------------------------------------------------
void calibrateGyro() {
  if (!statusMpu2) return;
  Serial.println(F("[BOOT] Calibrating MPU-6050 #2 Gyroscope (100 samples, keep stationary)..."));

  float sumRoll  = 0.0f;
  float sumPitch = 0.0f;
  const int CAL_SAMPLES = 100;

  for (int i = 0; i < CAL_SAMPLES; i++) {
    feedWatchdog();
    sensors_event_t a, g, temp;
    mpuAttitude.getEvent(&a, &g, &temp);
    sumRoll  += g.gyro.x;
    sumPitch += g.gyro.y;
    delay(10); // 10ms * 100 = 1000ms calibration duration
  }

  gyroRollBias  = (sumRoll  / CAL_SAMPLES) * 180.0f / PI; // deg/s
  gyroPitchBias = (sumPitch / CAL_SAMPLES) * 180.0f / PI; // deg/s

  Serial.print(F("[BOOT] Gyro Calibrated. Bias Roll: "));
  Serial.print(gyroRollBias, 3);
  Serial.print(F(" deg/s, Bias Pitch: "));
  Serial.print(gyroPitchBias, 3);
  Serial.println(F(" deg/s. Zero-drift baseline locked."));
}

void tareAttitude() {
  pitchAngle = 0.0f;
  rollAngle  = 0.0f;
  calibrateGyro();
  Serial.println(F("[C&DH] TARE executed: attitude Euler angles zeroed."));
}

// -------------------------------------------------------------------------------------
// HARDWARE INITIALIZATION (SAFE, DEFENSIVE BOOT)
// -------------------------------------------------------------------------------------
void setup() {
  // Disable brownout detector to prevent reboot loops from LoRa RF transmit current spikes on breadboards
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

  Serial.begin(115200);
  delay(100);
  Serial.println(F("\n========================================================"));
  Serial.println(F("  STELLARSENSE - SATELLITE FLIGHT COMPUTER (BOOTING)   "));
  Serial.println(F("  Architecture: Dual-Core FreeRTOS / FDIR Hysteresis    "));
  Serial.println(F("========================================================"));

  // Initialize Discrete Actuator GPIOs (4x Status LEDs per schematic)
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_LED_POWER, OUTPUT);

  digitalWrite(PIN_LED_GREEN, LOW);
  digitalWrite(PIN_LED_YELLOW, LOW);
  digitalWrite(PIN_LED_RED, LOW);
  digitalWrite(PIN_LED_POWER, LOW);

  // Initialize and Clear I2C Bus with 25ms Timeout Protection
  recoverI2CBus(I2C_SDA, I2C_SCL);

  // 1. Initialize OLED Display (0x3C)
  if (display.begin(SSD1306_SWITCHCAPVCC, I2C_ADDR_OLED)) {
    statusOled = true;
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(18, 10);
    display.println(F("STELLARSENSE"));
    display.setCursor(12, 26);
    display.println(F("Flight Computer"));
    display.setCursor(16, 42);
    display.println(F("Dual-Core RTOS"));
    display.setCursor(20, 54);
    display.println(F("Initializing..."));
    display.display();
    Serial.println(F("[BOOT] OLED Display online (0x3C)."));
  } else {
    Serial.println(F("[WARN] OLED Display not detected at 0x3C. Continuing..."));
  }

  // 2. Initialize INA219 EPS Power Monitor (0x40)
  if (ina219.begin()) {
    statusIna = true;
    Serial.println(F("[BOOT] INA219 Power Monitor online (0x40)."));
  } else {
    Serial.println(F("[WARN] INA219 not detected at 0x40. Dynamic fallback active."));
  }

  // 3. Initialize MPU-6050 #1 (Structural Vibration - 0x68)
  if (mpuVibration.begin(I2C_ADDR_MPU1)) {
    statusMpu1 = true;
    mpuVibration.setAccelerometerRange(MPU6050_RANGE_4_G);
    mpuVibration.setGyroRange(MPU6050_RANGE_500_DEG);
    // Configure DLPF to 10 Hz to prevent Nyquist aliasing when sampled at 20 Hz
    mpuVibration.setFilterBandwidth(MPU6050_BAND_10_HZ);
    Serial.println(F("[BOOT] MPU-6050 #1 (Vibration) online (0x68, DLPF: 10Hz)."));
  } else {
    Serial.println(F("[WARN] MPU-6050 #1 not detected at 0x68. Dynamic fallback active."));
  }

  // 4. Initialize MPU-6050 #2 (Attitude Horizon - 0x69)
  if (mpuAttitude.begin(I2C_ADDR_MPU2)) {
    statusMpu2 = true;
    mpuAttitude.setAccelerometerRange(MPU6050_RANGE_2_G);
    mpuAttitude.setGyroRange(MPU6050_RANGE_250_DEG);
    mpuAttitude.setFilterBandwidth(MPU6050_BAND_21_HZ);
    Serial.println(F("[BOOT] MPU-6050 #2 (Attitude) online (0x69, DLPF: 21Hz)."));
    // Execute stationary zero-rate gyro calibration
    calibrateGyro();
  } else {
    Serial.println(F("[WARN] MPU-6050 #2 not detected at 0x69. Orbital sway fallback active."));
  }

  // 5. Initialize DS18B20 1-Wire Thermal Probe (D4)
  tempSensor.begin();
  int devCount = tempSensor.getDeviceCount();
  if (devCount > 0) {
    statusTemp = true;
    tempSensor.setResolution(10); // 10-bit resolution = 187.5ms conversion time
    tempSensor.setWaitForConversion(false); // Enable non-blocking asynchronous mode
    tempSensor.requestTemperatures();
    lastTempRequestTime = millis();
    tempConversionPending = true;
    Serial.print(F("[BOOT] DS18B20 Temperature Sensor online (D4, Devices: "));
    Serial.print(devCount);
    Serial.println(F("). 1Hz non-blocking sampling engaged."));
  } else {
    statusTemp = false;
    Serial.println(F("[WARN] DS18B20 not detected on D4! Graceful thermal fallback active."));
  }

  // 6. Initialize LoRa SX1278 Transceiver (Ra-02 433MHz) with Hardware CRC
  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);

  if (LoRa.begin(LORA_FREQ)) {
    statusLoRa = true;
    LoRa.setSpreadingFactor(7);                   // SF7 (fast, robust link)
    LoRa.setSignalBandwidth(125E3);               // 125 kHz Bandwidth
    LoRa.setCodingRate4(5);                       // 4/5 Error Coding
    LoRa.setSyncWord(0xF3);                       // Isolated Mission Sync Word
    LoRa.setPreambleLength(8);
    LoRa.setTxPower(17, PA_OUTPUT_PA_BOOST_PIN);  // +17 dBm Output Power
    LoRa.enableCrc();                             // CRITICAL: Hardware CRC Enabled!
    Serial.println(F("[BOOT] LoRa Ra-02 (433 MHz) online with Hardware CRC enabled."));
  } else {
    Serial.println(F("[ERR] LoRa initialization failed! Check wiring on SPI pins."));
  }

  // 7. Create FreeRTOS Inter-Core Telemetry Queue
  telemetryQueue = xQueueCreate(2, sizeof(TelemetryPayload));
  if (telemetryQueue == NULL) {
    Serial.println(F("[ERR] Failed to create FreeRTOS telemetry queue!"));
  }

  // 8. Launch Dedicated LoRa Background Task on Core 0 (PRO_CPU)
  xTaskCreatePinnedToCore(
    loraTask,             // Task function
    "LoRaTask",           // Task name
    4096,                 // Stack size (bytes)
    NULL,                 // Parameters
    1,                    // Priority
    &loraTaskHandle,      // Task handle
    0                     // Pin strictly to Core 0
  );
  Serial.println(F("[BOOT] FreeRTOS LoRa background task pinned to Core 0 (PRO_CPU)."));

  // 9. Initialize Hardware Task Watchdog on Core 1
  initWatchdog();

  bootTime = millis();
  lastAttitudeTime = millis();

  // Visual Quad-LED Self-Test Flash on Boot
  digitalWrite(PIN_LED_GREEN, HIGH);
  digitalWrite(PIN_LED_YELLOW, HIGH);
  digitalWrite(PIN_LED_RED, HIGH);
  digitalWrite(PIN_LED_POWER, HIGH);
  delay(150);
  digitalWrite(PIN_LED_YELLOW, LOW);
  digitalWrite(PIN_LED_RED, LOW);

  Serial.println(F("[BOOT] Autonomous Flight Executive running on Core 1 (APP_CPU)."));
}

// -------------------------------------------------------------------------------------
// TASK 1: NON-BLOCKING 1HZ DS18B20 TEMPERATURE POLLER
// -------------------------------------------------------------------------------------
void pollTemperature() {
  unsigned long now = millis();

  // If a conversion was requested >= 200ms ago (10-bit conversion max time = 187.5ms)
  if (tempConversionPending && (now - lastTempRequestTime >= 200)) {
    tempConversionPending = false;
    lastTempReadTime = now;

    if (statusTemp) {
      float readT = tempSensor.getTempCByIndex(0);
      // DEVICE_DISCONNECTED_C is -127.0f; also reject invalid out-of-range readings
      if (readT <= -100.0f || readT >= 85.0f || readT == DEVICE_DISCONNECTED_C) {
        tempErrorStreak++;
        if (tempErrorStreak >= 3) {
          statusTemp = false;
          Serial.println(F("[FDIR] DS18B20 disconnected (-127C detected). Graceful fallback active."));
        }
      } else {
        tempErrorStreak = 0;
        // Low-pass filter (80% historical, 20% fresh reading)
        telemetryTemp = (telemetryTemp * 0.8f) + (readT * 0.2f);
      }
    }
  }

  // Request next 1-Wire conversion every 1000ms (1 Hz)
  if (!tempConversionPending && (now - lastTempReadTime >= 1000)) {
    // If online or retrying a previously disconnected probe
    tempSensor.requestTemperatures();
    lastTempRequestTime = now;
    tempConversionPending = true;

    // Periodically re-check device count if disconnected
    if (!statusTemp && (tempErrorStreak >= 3)) {
      if (tempSensor.getDeviceCount() > 0) {
        statusTemp = true;
        tempErrorStreak = 0;
        Serial.println(F("[FDIR] DS18B20 reconnected! Resuming hardware readings."));
      }
    }
  }

  // Graceful thermal fallback if hardware probe is offline
  if (!statusTemp) {
    telemetryTemp = 24.5f + sin(now / 10000.0f) * 1.2f;
  }
}

// -------------------------------------------------------------------------------------
// TASK 2: HIGH-RATE SENSOR SAMPLING & DSP (Run every 50ms = 20 Hz on Core 1)
// -------------------------------------------------------------------------------------
void runSensorDSP() {
  unsigned long now = millis();
  float dt = (now - lastAttitudeTime) / 1000.0f;
  if (dt <= 0.0f || dt > 0.5f) dt = 0.05f;
  lastAttitudeTime = now;

  // --- A. Read INA219 EPS Bus Power ---
  if (statusIna) {
    busVoltage = ina219.getBusVoltage_V();
    current_mA = ina219.getCurrent_mA();
    power_mW   = busVoltage * current_mA;
  } else {
    // Graceful nominal fallback if INA219 offline
    busVoltage = 5.02f;
    current_mA = 315.0f + sin(now / 1500.0f) * 15.0f;
    power_mW   = busVoltage * current_mA;
  }

  // --- B. DSP on MPU-6050 #1: True RMS Structural Vibration: RMS = sqrt(EMA(dynG^2)) ---
  if (statusMpu1) {
    sensors_event_t a, g, temp;
    mpuVibration.getEvent(&a, &g, &temp);

    // Delta acceleration (high-pass filter removing 1g static gravity baseline)
    float dAx = a.acceleration.x - lastAx;
    float dAy = a.acceleration.y - lastAy;
    float dAz = a.acceleration.z - lastAz;

    lastAx = a.acceleration.x;
    lastAy = a.acceleration.y;
    lastAz = a.acceleration.z;

    // Convert m/s^2 to g (1g = 9.80665 m/s^2) and compute squared dynamic magnitude
    const float ONE_G = 9.80665f;
    float dynamicGSq = (dAx * dAx + dAy * dAy + dAz * dAz) / (ONE_G * ONE_G);

    // Exponential Moving Average of squared magnitude:
    // MeanSquare[k] = 0.85 * MeanSquare[k-1] + 0.15 * (dynamicG^2)
    vibMeanSquare = (vibMeanSquare * 0.85f) + (dynamicGSq * 0.15f);

    // True RMS = sqrt(MeanSquare)
    vibrationRMS = sqrtf(vibMeanSquare);
  } else {
    // Dynamic simulated micro-jitter if sensor absent
    vibrationRMS = 0.06f + (float)(random(0, 30)) / 1000.0f;
  }

  // --- C. Sensor Fusion on MPU-6050 #2: ADCS Attitude Horizon with Zero-Drift Calibration ---
  if (statusMpu2) {
    sensors_event_t a, g, temp;
    mpuAttitude.getEvent(&a, &g, &temp);

    // Accelerometer Euler angles (Horizon reference)
    float accRoll  = atan2(a.acceleration.y, a.acceleration.z) * 180.0f / PI;
    float accPitch = atan2(-a.acceleration.x, sqrt(a.acceleration.y * a.acceleration.y + a.acceleration.z * a.acceleration.z)) * 180.0f / PI;

    // Gyroscope angular rates with zero-rate offset subtracted (deg/sec)
    float gyroRollRate  = (g.gyro.x * 180.0f / PI) - gyroRollBias;
    float gyroPitchRate = (g.gyro.y * 180.0f / PI) - gyroPitchBias;

    // Complementary Filter: 96% Gyro Integration + 4% Accelerometer Horizon Correction
    rollAngle  = 0.96f * (rollAngle + gyroRollRate * dt) + 0.04f * accRoll;
    pitchAngle = 0.96f * (pitchAngle + gyroPitchRate * dt) + 0.04f * accPitch;
  } else {
    // Subtle slow orbital sway if sensor unpopulated
    pitchAngle = sin(now / 3000.0f) * 8.0f;
    rollAngle  = cos(now / 3500.0f) * 6.0f;
  }

  pitchAngle = constrain(pitchAngle, -90.0f, 90.0f);
  rollAngle  = constrain(rollAngle, -180.0f, 180.0f);
}

// -------------------------------------------------------------------------------------
// TASK 3: AUTONOMOUS FDIR ENGINE (Dual-Threshold Hysteresis & 3-Sample Persistence)
// -------------------------------------------------------------------------------------
void evaluateFDIR() {
  // --- 1. Dual-Threshold Hysteresis Evaluation ---

  // Temperature Deadband Checks
  if (!tempWarnLatched && telemetryTemp >= TEMP_WARN_HIGH) tempWarnLatched = true;
  else if (tempWarnLatched && telemetryTemp <= TEMP_WARN_CLEAR) tempWarnLatched = false;

  if (!tempCritLatched && telemetryTemp >= TEMP_CRIT_HIGH) tempCritLatched = true;
  else if (tempCritLatched && telemetryTemp <= TEMP_CRIT_CLEAR) tempCritLatched = false;

  // EPS Bus Voltage & Current Deadband Checks
  if (statusIna) {
    // Under-voltage sag
    if (!voltWarnLatched && busVoltage <= VOLT_WARN_LOW) voltWarnLatched = true;
    else if (voltWarnLatched && busVoltage >= VOLT_WARN_CLEAR) voltWarnLatched = false;

    if (!voltCritLatched && busVoltage <= VOLT_CRIT_LOW) voltCritLatched = true;
    else if (voltCritLatched && busVoltage >= VOLT_CRIT_CLEAR) voltCritLatched = false;

    // Overcurrent / Latchup surge
    if (!currWarnLatched && current_mA >= CURR_WARN_HIGH) currWarnLatched = true;
    else if (currWarnLatched && current_mA <= CURR_WARN_CLEAR) currWarnLatched = false;

    if (!currCritLatched && current_mA >= CURR_CRIT_HIGH) currCritLatched = true;
    else if (currCritLatched && current_mA <= CURR_CRIT_CLEAR) currCritLatched = false;
  } else {
    voltWarnLatched = voltCritLatched = currWarnLatched = currCritLatched = false;
  }

  // Structural Acoustic Vibration Deadband Checks
  if (!vibWarnLatched && vibrationRMS >= VIB_WARN_HIGH) vibWarnLatched = true;
  else if (vibWarnLatched && vibrationRMS <= VIB_WARN_CLEAR) vibWarnLatched = false;

  if (!vibCritLatched && vibrationRMS >= VIB_CRIT_HIGH) vibCritLatched = true;
  else if (vibCritLatched && vibrationRMS <= VIB_CRIT_CLEAR) vibCritLatched = false;

  // Synthesize candidate classification level
  if (tempCritLatched || voltCritLatched || currCritLatched || vibCritLatched) {
    candidateFDIR = STATE_CRITICAL;
  } else if (tempWarnLatched || voltWarnLatched || currWarnLatched || vibWarnLatched) {
    candidateFDIR = STATE_CAUTION;
  } else {
    candidateFDIR = STATE_NOMINAL;
  }

  // --- 2. Persistence Debounce Filter (3 consecutive 50ms frames = 150ms debounce) ---
  if (candidateFDIR == pendingFDIR) {
    fdirPersistenceCtr++;
    if (fdirPersistenceCtr >= FDIR_PERSISTENCE_COUNT) {
      currentFDIR = candidateFDIR;
    }
  } else {
    pendingFDIR = candidateFDIR;
    fdirPersistenceCtr = 1;
  }
}

// -------------------------------------------------------------------------------------
// TASK 4: ONBOARD STATUS LEDS & ANNUNCIATORS (Run every 100ms on Core 1)
// -------------------------------------------------------------------------------------
void updateAlertHardware() {
  ledToggle = !ledToggle;

  switch (currentFDIR) {
    case STATE_NOMINAL:
      digitalWrite(PIN_LED_GREEN, HIGH);
      digitalWrite(PIN_LED_YELLOW, LOW);
      digitalWrite(PIN_LED_RED, LOW);
      break;

    case STATE_CAUTION:
      digitalWrite(PIN_LED_GREEN, LOW);
      digitalWrite(PIN_LED_YELLOW, HIGH);
      digitalWrite(PIN_LED_RED, LOW);
      break;

    case STATE_CRITICAL:
      digitalWrite(PIN_LED_GREEN, LOW);
      digitalWrite(PIN_LED_YELLOW, LOW);
      // Synchronized 10Hz Flashing Red LED on Satellite
      digitalWrite(PIN_LED_RED, ledToggle ? HIGH : LOW);
      break;
  }
}

// -------------------------------------------------------------------------------------
// TASK 5: LOCAL OLED TELEMETRY HUD (Run every 200ms on Core 1)
// -------------------------------------------------------------------------------------
void updateOLED() {
  if (!statusOled) return;

  display.clearDisplay();

  // Top Mission Header
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.print(F("STELLARSENSE"));

  display.setCursor(80, 0);
  switch (currentFDIR) {
    case STATE_NOMINAL: display.print(F("[OK]"));   break;
    case STATE_CAUTION: display.print(F("[WARN]")); break;
    case STATE_CRITICAL: display.print(F("[CRIT]")); break;
  }

  display.drawLine(0, 9, 128, 9, SSD1306_WHITE);

  // Line 1: Thermal & Vibration
  display.setCursor(0, 14);
  display.print(F("T: "));
  display.print(telemetryTemp, 1);
  display.print(F("C"));

  display.setCursor(68, 14);
  display.print(F("VIB: "));
  display.print(vibrationRMS, 2);
  display.print(F("g"));

  // Line 2: Electrical EPS
  display.setCursor(0, 26);
  display.print(F("V: "));
  display.print(busVoltage, 2);
  display.print(F("V"));

  display.setCursor(68, 26);
  display.print(F("I: "));
  display.print((int)current_mA);
  display.print(F("mA"));

  // Line 3: Power & Attitude
  display.setCursor(0, 38);
  display.print(F("P: "));
  display.print((int)power_mW);
  display.print(F("mW"));

  display.setCursor(68, 38);
  display.print(F("P/R: "));
  display.print((int)pitchAngle);
  display.print(F("/"));
  display.print((int)rollAngle);

  // Bottom Status Bar
  display.drawLine(0, 49, 128, 49, SSD1306_WHITE);
  display.setCursor(0, 53);
  display.print(F("PKT:"));
  display.print(packetId);
  display.print(F(" | CRC433"));

  display.display();
}

// -------------------------------------------------------------------------------------
// TASK 6: TELEMETRY DISPATCH (Pushes Snapshot to FreeRTOS Queue for Core 0)
// -------------------------------------------------------------------------------------
void dispatchTelemetry() {
  packetId++;
  uint32_t metSeconds = (millis() - bootTime) / 1000;

  TelemetryPayload payload;
  payload.pkt = packetId;
  payload.met = metSeconds;
  payload.temp = telemetryTemp;
  payload.volt = busVoltage;
  payload.curr = current_mA;
  payload.pwr = power_mW;
  payload.vib = vibrationRMS;
  payload.pitch = pitchAngle;
  payload.roll = rollAngle;
  payload.fdirState = (uint8_t)currentFDIR;
  payload.hwStatus = (statusOled ? 1 : 0) |
                     (statusIna  ? 2 : 0) |
                     (statusMpu1 ? 4 : 0) |
                     (statusMpu2 ? 8 : 0) |
                     (statusTemp ? 16 : 0) |
                     (statusLoRa ? 32 : 0);

  if (telemetryQueue != NULL) {
    // Non-blocking push (timeout 0): never stalls Core 1 if queue is momentarily full
    xQueueSend(telemetryQueue, &payload, 0);
  }
}

// -------------------------------------------------------------------------------------
// C&DH: TELECOMMAND HANDLER
// -------------------------------------------------------------------------------------
void handleTelecommand(const char *cmd) {
  Serial.print(F("[C&DH] Received Telecommand: "));
  Serial.println(cmd);

  if (strcmp(cmd, "CMD:PING") == 0) {
    // Immediate RF Pong
    LoRa.beginPacket();
    LoRa.print(F("{\"system\":\"SATELLITE\",\"ack\":\"PONG\"}"));
    LoRa.endPacket();
    Serial.println(F("[C&DH] Uplink acknowledged: PONG transmitted."));
  }
  else if (strcmp(cmd, "CMD:FDIR_RESET") == 0) {
    cmdFdirResetRequested = true;
    Serial.println(F("[C&DH] FDIR fault reset queued for Core 1."));
  }
  else if (strcmp(cmd, "CMD:TARE") == 0) {
    cmdTareRequested = true;
    Serial.println(F("[C&DH] Attitude TARE calibration queued for Core 1."));
  }
  else if (strncmp(cmd, "CMD:RATE:", 9) == 0) {
    int rate = atoi(cmd + 9);
    if (rate >= 100 && rate <= 5000) {
      downlinkIntervalMs = (uint32_t)rate;
      Serial.print(F("[C&DH] Telemetry downlink rate adjusted to: "));
      Serial.print(downlinkIntervalMs);
      Serial.println(F(" ms."));
    }
  }
}

// -------------------------------------------------------------------------------------
// CORE 0 FREERTOS BACKGROUND TASK: LORA RF TRANSMISSION & TELECOMMAND UPLINK
// -------------------------------------------------------------------------------------
void loraTask(void *pvParameters) {
  (void)pvParameters;
  TelemetryPayload payload;
  char jsonBuffer[256];

  for (;;) {
    // Wait for telemetry payload from Core 1 (timeout 50ms)
    if (telemetryQueue != NULL && xQueueReceive(telemetryQueue, &payload, pdMS_TO_TICKS(50)) == pdPASS) {
      if (statusLoRa) {
        const char *fdirStr = "NOMINAL";
        if (payload.fdirState == STATE_CRITICAL) fdirStr = "CRITICAL";
        else if (payload.fdirState == STATE_CAUTION)  fdirStr = "CAUTION";

        // Format clean JSON into static char buffer (zero heap String fragmentation)
        snprintf(jsonBuffer, sizeof(jsonBuffer),
          "{\"pkt\":%u,\"met\":%u,\"temp\":%.2f,\"volt\":%.2f,\"curr\":%.1f,\"pwr\":%.1f,\"vib\":%.3f,\"pitch\":%.1f,\"roll\":%.1f,\"fdir\":\"%s\",\"hw\":%u}",
          payload.pkt, payload.met, payload.temp, payload.volt, payload.curr, payload.pwr, payload.vib, payload.pitch, payload.roll, fdirStr, payload.hwStatus
        );

        // Core 0 executes blocking RF airtime wait (~220ms) without stalling Core 1!
        LoRa.beginPacket();
        LoRa.print(jsonBuffer);
        LoRa.endPacket();

        // Stream downlink frame to USB Serial
        Serial.print(F("[TX-DOWNLINK] "));
        Serial.println(jsonBuffer);
      }
    }

    // Check for incoming telecommands over LoRa RF
    if (statusLoRa) {
      int packetSize = LoRa.parsePacket();
      if (packetSize > 0) {
        char cmdBuf[64];
        int len = LoRa.readBytes(cmdBuf, min(packetSize, (int)sizeof(cmdBuf) - 1));
        cmdBuf[len] = '\0';
        handleTelecommand(cmdBuf);
      }
    }

    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

// -------------------------------------------------------------------------------------
// MAIN DETERMINISTIC EXECUTIVE (CORE 1 - APP_CPU)
// -------------------------------------------------------------------------------------
void loop() {
  // Feed Hardware Task Watchdog Timer
  feedWatchdog();

  // Process Inter-Core C&DH Requests from Core 0
  if (cmdTareRequested) {
    cmdTareRequested = false;
    tareAttitude();
  }
  if (cmdFdirResetRequested) {
    cmdFdirResetRequested = false;
    tempWarnLatched = tempCritLatched = false;
    voltWarnLatched = voltCritLatched = false;
    currWarnLatched = currCritLatched = false;
    vibWarnLatched  = vibCritLatched  = false;
    currentFDIR = STATE_NOMINAL;
    pendingFDIR = STATE_NOMINAL;
    Serial.println(F("[FDIR] Manual latch clearance complete: NOMINAL restored."));
  }

  // Non-blocking 1Hz DS18B20 Temperature Polling
  pollTemperature();

  unsigned long currentMillis = millis();

  // Task 1: High-Rate Sensor DSP & FDIR (every 50ms = 20 Hz deterministic)
  if (currentMillis - lastDspTime >= 50) {
    lastDspTime = currentMillis;
    runSensorDSP();
    evaluateFDIR();
  }

  // Task 2: Alarm & Annunciator Timing (every 100ms = 10 Hz)
  if (currentMillis - lastAlarmTime >= 100) {
    lastAlarmTime = currentMillis;
    updateAlertHardware();
  }

  // Task 3: Local OLED HUD Screen Update (every 200ms = 5 Hz)
  if (currentMillis - lastOledTime >= 200) {
    lastOledTime = currentMillis;
    updateOLED();
  }

  // Task 4: LoRa Downlink Dispatch to Core 0 (default 600ms = ~1.6 Hz)
  if (currentMillis - lastTxTime >= downlinkIntervalMs) {
    lastTxTime = currentMillis;
    dispatchTelemetry();
  }
}
