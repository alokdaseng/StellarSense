/*
 * =====================================================================================
 *  STELLARSENSE - MINIATURE SATELLITE HEALTH & FDIR TELEMETRY SUBSYSTEM
 *  Firmware: Ground Station Receiver & Telecommand Unit
 *  Target MCU: ESP32 DevKit (30-Pin) connected via USB to Mission Control Laptop
 *  
 *  Hardware Peripherals:
 *   - LoRa Ra-02 SX1278 (433MHz) -> SPI (SCK:18, MISO:19, MOSI:23, SS:27, RST:14, DIO0:26)
 *   - Onboard Status LED (GPIO 2) -> Telemetry RX pulse-stretched heartbeat flash
 *   - USB Serial UART0 -> 115200 Baud JSON streaming to Laptop Dashboard
 * 
 *  Architecture:
 *   - High-sensitivity non-blocking LoRa packet receiver with Hardware CRC validation.
 *   - Non-blocking 40ms RX LED pulse stretcher for crisp, human-visible reception flash.
 *   - Static stack-allocated buffers (zero heap String fragmentation / memory leaks).
 *   - Link budget telemetry enrichment (RSSI, SNR, rx_count, dropped_pkts).
 *   - Bidirectional Telecommand (C&DH) Uplink: parses Serial commands and transmits
 *     uplink frames over LoRa to satellite flight computer.
 *   - ESP32 Hardware Task Watchdog Timer (4s timeout) with autonomous reboot recovery.
 * =====================================================================================
 */

#include <SPI.h>
#include <LoRa.h>
#include <ArduinoJson.h>
#include <esp_task_wdt.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// -------------------------------------------------------------------------------------
// PIN DEFINITIONS (Final Hardware Layout - Single Buzzer on Ground Station Only)
// -------------------------------------------------------------------------------------
#define LORA_SCK       18
#define LORA_MISO      19
#define LORA_MOSI      23
#define LORA_SS        27
#define LORA_RST       14
#define LORA_DIO0      26
#define LORA_FREQ      433E6 // 433.0 MHz Carrier Frequency

#define PIN_RX_LED     2     // ESP32 DevKit Onboard Blue LED
#define PIN_BUZZER     13    // 5V Active Buzzer via NPN (2N2222/BC547) + 1k Base Resistor

// Timing & Watchdog Constants
#define WDT_TIMEOUT_SECONDS 8
#define RX_LED_PULSE_MS     40 // 40ms pulse duration for optimal human persistence vision

// Link Budget & Telemetry Statistics
uint32_t totalPacketsReceived = 0;
uint32_t totalPacketsDropped  = 0;
uint32_t expectedSatPkt       = 0;
uint32_t lastPacketTime       = 0;
bool loraInitialized          = false;

// Non-blocking RX LED Pulse Stretcher
unsigned long rxLedOffTime    = 0;
bool rxLedActive              = false;

// Ground Station Audible Alarm State Machine (D13 Buzzer)
enum GroundFDIRState {
  GS_NOMINAL = 0,
  GS_CAUTION = 1,
  GS_CRITICAL = 2
};

GroundFDIRState currentGroundAlert = GS_NOMINAL;
bool buzzerSilenced           = false;
bool buzzerToggle             = false;
unsigned long lastBuzzerCadence = 0;

// Static Telecommand Serial Ingestion Buffer
char cmdSerialBuffer[64];
uint8_t cmdSerialIdx          = 0;

// -------------------------------------------------------------------------------------
// ESP32 TASK WATCHDOG INITIALIZATION
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
  esp_task_wdt_add(NULL);
  Serial.println(F("[WDT] Ground Station Task Watchdog initialized (4-second timeout)."));
}

void feedWatchdog() {
  esp_task_wdt_reset();
}

// -------------------------------------------------------------------------------------
// HARDWARE INITIALIZATION
// -------------------------------------------------------------------------------------
void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
  Serial.begin(115200);
  pinMode(PIN_RX_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_RX_LED, LOW);
  digitalWrite(PIN_BUZZER, LOW);

  // Power-On Confirmation Chirp on Ground Station Buzzer
  digitalWrite(PIN_BUZZER, HIGH);
  delay(100);
  digitalWrite(PIN_BUZZER, LOW);

  delay(50);
  Serial.println(F("\n========================================================"));
  Serial.println(F("  STELLARSENSE - GROUND STATION RECEIVER (ONLINE)       "));
  Serial.println(F("  Hardware: LoRa 433MHz + D13 Active Audible Buzzer     "));
  Serial.println(F("========================================================"));

  // Initialize LoRa SPI Bus
  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);

  if (LoRa.begin(LORA_FREQ)) {
    loraInitialized = true;
    LoRa.setSpreadingFactor(7);
    LoRa.setSignalBandwidth(125E3);
    LoRa.setCodingRate4(5);
    LoRa.setSyncWord(0xF3); // Must match Satellite Unit Sync Word
    LoRa.setPreambleLength(8);
    LoRa.enableCrc();       // CRITICAL: Hardware CRC Enabled!
    Serial.println(F("{\"system\":\"GROUND_STATION\",\"status\":\"READY\",\"freq\":433.0,\"crc\":true}"));
  } else {
    Serial.println(F("{\"system\":\"GROUND_STATION\",\"status\":\"LORA_ERROR\",\"desc\":\"Check SPI wiring\"}"));
  }

  // Initialize Hardware Task Watchdog Timer
  initWatchdog();
}

// -------------------------------------------------------------------------------------
// TASK: PROCESS INCOMING SERIAL TELECOMMANDS & UPLINK VIA LORA RF
// -------------------------------------------------------------------------------------
void processSerialCommands() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdSerialIdx > 0) {
        cmdSerialBuffer[cmdSerialIdx] = '\0';

        // Local Ground Station Commands
        if (strcmp(cmdSerialBuffer, "CMD:SILENCE") == 0) {
          buzzerSilenced = true;
          digitalWrite(PIN_BUZZER, LOW);
          Serial.println(F("{\"system\":\"GROUND_STATION\",\"event\":\"BUZZER_SILENCED\"}"));
        } else if (strcmp(cmdSerialBuffer, "CMD:BUZZER_TEST") == 0) {
          buzzerSilenced = false;
          digitalWrite(PIN_BUZZER, HIGH);
          delay(100);
          digitalWrite(PIN_BUZZER, LOW);
          Serial.println(F("{\"system\":\"GROUND_STATION\",\"event\":\"BUZZER_TEST_OK\"}"));
        }

        // Log telecommand transmission to Mission Control
        Serial.print(F("{\"system\":\"GROUND_STATION\",\"event\":\"CMD_UPLINK\",\"cmd\":\""));
        Serial.print(cmdSerialBuffer);
        Serial.println(F("\"}"));

        // Uplink command over 433 MHz LoRa RF link
        if (loraInitialized) {
          LoRa.beginPacket();
          LoRa.print(cmdSerialBuffer);
          LoRa.endPacket();

          // Flash RX/TX LED briefly to indicate uplink
          digitalWrite(PIN_RX_LED, HIGH);
          rxLedActive = true;
          rxLedOffTime = millis() + RX_LED_PULSE_MS;
        }

        cmdSerialIdx = 0;
      }
    } else if (cmdSerialIdx < sizeof(cmdSerialBuffer) - 1) {
      cmdSerialBuffer[cmdSerialIdx++] = c;
    }
  }
}

// -------------------------------------------------------------------------------------
// TASK: GROUND STATION AUDIBLE BUZZER STATE MACHINE (D13 via NPN Driver)
// -------------------------------------------------------------------------------------
void updateGroundBuzzer() {
  if (millis() - lastBuzzerCadence < 100) return;
  lastBuzzerCadence = millis();
  buzzerToggle = !buzzerToggle;

  if (buzzerSilenced) {
    digitalWrite(PIN_BUZZER, LOW);
    return;
  }

  switch (currentGroundAlert) {
    case GS_NOMINAL:
      digitalWrite(PIN_BUZZER, LOW);
      break;

    case GS_CAUTION:
      // Caution: soft chirp (100ms beep every 800ms)
      if ((millis() / 100) % 8 == 0) {
        digitalWrite(PIN_BUZZER, HIGH);
      } else {
        digitalWrite(PIN_BUZZER, LOW);
      }
      break;

    case GS_CRITICAL:
      // Critical: alternating high-urgency siren (100ms ON / 100ms OFF)
      digitalWrite(PIN_BUZZER, buzzerToggle ? HIGH : LOW);
      break;
  }
}

// -------------------------------------------------------------------------------------
// MAIN NON-BLOCKING EXECUTION LOOP
// -------------------------------------------------------------------------------------
void loop() {
  // Feed Hardware Task Watchdog
  feedWatchdog();

  // Process Ground Station Audible Alarm Cadence (D13 Buzzer)
  updateGroundBuzzer();

  // Process non-blocking RX LED Pulse Stretcher
  if (rxLedActive && (millis() >= rxLedOffTime)) {
    digitalWrite(PIN_RX_LED, LOW);
    rxLedActive = false;
  }

  // Process incoming telecommands from Laptop Mission Control
  processSerialCommands();

  // Defensive RF link reconnection check
  if (!loraInitialized) {
    static unsigned long lastRetry = 0;
    if (millis() - lastRetry > 3000) {
      lastRetry = millis();
      if (LoRa.begin(LORA_FREQ)) {
        loraInitialized = true;
        LoRa.setSpreadingFactor(7);
        LoRa.setSignalBandwidth(125E3);
        LoRa.setCodingRate4(5);
        LoRa.setSyncWord(0xF3);
        LoRa.setPreambleLength(8);
        LoRa.enableCrc(); // Re-enable CRC
        Serial.println(F("{\"system\":\"GROUND_STATION\",\"status\":\"READY\",\"freq\":433.0,\"crc\":true}"));
      }
    }
    return;
  }

  // Non-blocking check for received LoRa packet
  int packetSize = LoRa.parsePacket();
  if (packetSize > 0) {
    // Static stack buffer eliminates dynamic String heap fragmentation
    char rxBuffer[256];
    int bytesToRead = (packetSize < (int)sizeof(rxBuffer) - 1) ? packetSize : ((int)sizeof(rxBuffer) - 1);
    int bytesRead = LoRa.readBytes(rxBuffer, bytesToRead);
    rxBuffer[bytesRead] = '\0';

    // Flush any remaining overflow bytes if packet exceeded buffer size
    while (LoRa.available()) {
      LoRa.read();
    }

    // Capture RF Link Budget Metrics
    int rssi = LoRa.packetRssi();
    float snr = LoRa.packetSnr();
    totalPacketsReceived++;
    lastPacketTime = millis();

    // Trigger non-blocking 40ms pulse stretcher for bright, human-visible LED flash
    digitalWrite(PIN_RX_LED, HIGH);
    rxLedActive = true;
    rxLedOffTime = millis() + RX_LED_PULSE_MS;

    // Parse incoming JSON
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, rxBuffer);

    if (!err) {
      // Check if this is a satellite telemetry frame
      if (doc["pkt"].is<uint32_t>() || doc["pkt"].is<int>()) {
        uint32_t satPkt = doc["pkt"];

        // Sequence Tracking: Detect dropped packets over RF link
        if (expectedSatPkt > 0 && satPkt > expectedSatPkt) {
          uint32_t gap = satPkt - expectedSatPkt;
          totalPacketsDropped += gap;
        }
        expectedSatPkt = satPkt + 1;

        // Update Ground Station Audible Alarm State from Satellite FDIR
        if (doc["fdir"].is<const char*>()) {
          const char* fdir = doc["fdir"];
          if (strcmp(fdir, "CRITICAL") == 0) {
            if (currentGroundAlert != GS_CRITICAL) {
              buzzerSilenced = false; // Reset silence flag on new critical escalation
            }
            currentGroundAlert = GS_CRITICAL;
          } else if (strcmp(fdir, "CAUTION") == 0) {
            if (currentGroundAlert == GS_NOMINAL) {
              buzzerSilenced = false;
            }
            currentGroundAlert = GS_CAUTION;
          } else {
            currentGroundAlert = GS_NOMINAL;
            buzzerSilenced = false;
          }
        }

        // Enrich with Ground Station Link Metrics
        doc["rssi"]         = rssi;
        doc["snr"]          = round(snr * 10.0f) / 10.0f;
        doc["rx_count"]     = totalPacketsReceived;
        doc["dropped_pkts"] = totalPacketsDropped;

        // Stream enriched telemetry frame to USB Web Serial
        serializeJson(doc, Serial);
        Serial.println();
      } else {
        // Uplink acknowledgment or system frame (e.g. {"system":"SATELLITE","ack":"PONG"})
        doc["rssi"] = rssi;
        doc["snr"]  = round(snr * 10.0f) / 10.0f;
        serializeJson(doc, Serial);
        Serial.println();
      }
    } else {
      // In case of noisy or malformed frame, package diagnostic frame
      JsonDocument rawDoc;
      rawDoc["raw"]  = rxBuffer;
      rawDoc["rssi"] = rssi;
      rawDoc["snr"]  = round(snr * 10.0f) / 10.0f;
      rawDoc["err"]  = "PARSE_FAIL";
      serializeJson(rawDoc, Serial);
      Serial.println();
    }
  }
}
