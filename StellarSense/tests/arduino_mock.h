#ifndef ARDUINO_MOCK_H
#define ARDUINO_MOCK_H

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <string>
#include <vector>
#include <queue>
#include <deque>
#include <map>
#include <type_traits>

#define HIGH 0x1
#define LOW  0x0
#define INPUT 0x0
#define OUTPUT 0x1
#define INPUT_PULLUP 0x2
#define OUTPUT_OPEN_DRAIN 0x3
#define PI 3.14159265358979323846

#define F(x) x
#define SSD1306_SWITCHCAPVCC 0x2
#define SSD1306_WHITE 1
#define MPU6050_RANGE_4_G 1
#define MPU6050_RANGE_2_G 0
#define MPU6050_RANGE_500_DEG 1
#define MPU6050_RANGE_250_DEG 0
#define MPU6050_BAND_44_HZ 3
#define MPU6050_BAND_21_HZ 4
#define MPU6050_BAND_10_HZ 5
#define PA_OUTPUT_PA_BOOST_PIN 1
#define DEVICE_DISCONNECTED_C -127.0f

inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, uint8_t) {}
inline int digitalRead(uint8_t) { return HIGH; }
inline void delay(unsigned long) {}
inline void delayMicroseconds(unsigned int) {}
static unsigned long _mock_millis = 1000;
inline unsigned long millis() { return _mock_millis; }
template<typename T> inline T constrain(T x, T a, T b) { return (x < a) ? a : ((x > b) ? b : x); }
template<typename T> inline T min(T a, T b) { return (a < b) ? a : b; }
template<typename T> inline T max(T a, T b) { return (a > b) ? a : b; }
inline long random(long min_v, long max_v) { return min_v + (std::rand() % (max_v - min_v + 1)); }

// Controllable sensor mock states
static float _mock_temp_reading = 25.4f;
static int _mock_temp_device_count = 1;
static bool _mock_temp_requested = false;

static float _mock_ina_voltage = 5.01f;
static float _mock_ina_current = 312.4f;

static bool _mock_mpu1_override = false;
static float _mock_mpu1_ax = 0.0f;
static float _mock_mpu1_ay = 0.0f;
static float _mock_mpu1_az = 9.80665f;

static bool _mock_mpu2_override = false;
static float _mock_mpu2_gx = 0.0f;
static float _mock_mpu2_gy = 0.0f;
static float _mock_mpu2_gz = 0.0f;
static float _mock_mpu2_ax = 0.0f;
static float _mock_mpu2_ay = 0.0f;
static float _mock_mpu2_az = 9.80665f;

struct MockSerial {
  std::queue<char> rx_queue;
  std::string tx_history;

  void begin(unsigned long) {}
  void print(const char* s) { if (s) tx_history += s; }
  void print(int v) { tx_history += std::to_string(v); }
  void print(unsigned int v) { tx_history += std::to_string(v); }
  void print(float v, int = 2) { tx_history += std::to_string(v); }
  void println(const char* s = "") { if (s) tx_history += s; tx_history += "\n"; }
  void println(int v) { tx_history += std::to_string(v) + "\n"; }
  void println(unsigned int v) { tx_history += std::to_string(v) + "\n"; }
  void println(float v, int = 2) { tx_history += std::to_string(v) + "\n"; }
  int available() { return (int)rx_queue.size(); }
  int read() {
    if (rx_queue.empty()) return -1;
    char c = rx_queue.front();
    rx_queue.pop();
    return (unsigned char)c;
  }
  void feed(const std::string& str) {
    for (char c : str) rx_queue.push(c);
  }
  void clear() {
    while (!rx_queue.empty()) rx_queue.pop();
    tx_history.clear();
  }
};
static MockSerial Serial;

struct TwoWire {
  void begin(int, int) {}
  void setClock(uint32_t) {}
  void setTimeOut(uint32_t) {}
  void end() {}
};
static TwoWire Wire;

struct SPIClass {
  void begin(int, int, int, int) {}
};
static SPIClass SPI;

struct MockLoRa {
  bool crc_enabled = false;
  std::vector<uint8_t> rx_packet;
  size_t rx_read_pos = 0;
  std::string tx_history;
  std::string last_tx_packet;
  bool in_packet = false;

  void setPins(int, int, int) {}
  bool begin(long) { return true; }
  void setSpreadingFactor(int) {}
  void setSignalBandwidth(long) {}
  void setCodingRate4(int) {}
  void setSyncWord(int) {}
  void setPreambleLength(int) {}
  void setTxPower(int, int = 0) {}
  void enableCrc() { crc_enabled = true; }
  void beginPacket() { in_packet = true; last_tx_packet.clear(); }
  void print(const char* s) { if (s) { last_tx_packet += s; tx_history += s; } }
  void endPacket() { in_packet = false; }

  void injectPacket(const std::string& data) {
    rx_packet.assign(data.begin(), data.end());
    rx_read_pos = 0;
  }
  void clearPacket() { rx_packet.clear(); rx_read_pos = 0; }
  int parsePacket() {
    return (rx_read_pos < rx_packet.size()) ? (int)(rx_packet.size() - rx_read_pos) : 0;
  }
  int available() {
    return (rx_read_pos < rx_packet.size()) ? (int)(rx_packet.size() - rx_read_pos) : 0;
  }
  int read() {
    if (rx_read_pos < rx_packet.size()) return rx_packet[rx_read_pos++];
    return -1;
  }
  int readBytes(char* buf, int len) {
    int count = 0;
    while (count < len && rx_read_pos < rx_packet.size()) {
      buf[count++] = (char)rx_packet[rx_read_pos++];
    }
    return count;
  }
  int packetRssi() { return -65; }
  float packetSnr() { return 9.5f; }
};
static MockLoRa LoRa;

struct Adafruit_SSD1306 {
  Adafruit_SSD1306(int, int, TwoWire*, int) {}
  bool begin(int, int) { return true; }
  void clearDisplay() {}
  void setTextColor(int) {}
  void setTextSize(int) {}
  void setCursor(int, int) {}
  void print(const char*) {}
  void print(float, int = 2) {}
  void print(int) {}
  void print(uint32_t) {}
  void println(const char* = "") {}
  void drawLine(int, int, int, int, int) {}
  void display() {}
};

struct Adafruit_INA219 {
  Adafruit_INA219(int) {}
  bool begin() { return true; }
  float getBusVoltage_V() { return _mock_ina_voltage; }
  float getCurrent_mA() { return _mock_ina_current; }
};

struct sensors_vec_t { float x, y, z; };
struct sensors_event_t {
  sensors_vec_t acceleration;
  sensors_vec_t gyro;
};

struct Adafruit_MPU6050 {
  int _addr = 0x68;
  Adafruit_MPU6050() {}
  bool begin(int addr = 0x68) { _addr = addr; return true; }
  void setAccelerometerRange(int) {}
  void setGyroRange(int) {}
  void setFilterBandwidth(int) {}
  bool getEvent(sensors_event_t* a, sensors_event_t* g, sensors_event_t*) {
    if (a) {
      if (_addr == 0x68 && _mock_mpu1_override) {
        a->acceleration.x = _mock_mpu1_ax;
        a->acceleration.y = _mock_mpu1_ay;
        a->acceleration.z = _mock_mpu1_az;
      } else if (_addr == 0x69 && _mock_mpu2_override) {
        a->acceleration.x = _mock_mpu2_ax;
        a->acceleration.y = _mock_mpu2_ay;
        a->acceleration.z = _mock_mpu2_az;
      } else {
        // Dynamic vibration simulation with 0.15g RMS amplitude
        float t = _mock_millis * 0.02f;
        a->acceleration.x = sin(t) * 0.8f;
        a->acceleration.y = cos(t) * 0.8f;
        a->acceleration.z = 9.80665f + sin(t * 1.5f) * 0.5f;
      }
    }
    if (g) {
      if (_addr == 0x69 && _mock_mpu2_override) {
        g->gyro.x = _mock_mpu2_gx;
        g->gyro.y = _mock_mpu2_gy;
        g->gyro.z = _mock_mpu2_gz;
      } else {
        g->gyro.x = 0.0f; g->gyro.y = 0.0f; g->gyro.z = 0.0f;
      }
    }
    return true;
  }
};

struct OneWire {
  OneWire(int) {}
};

struct DallasTemperature {
  DallasTemperature(OneWire*) {}
  void begin() {}
  int getDeviceCount() { return _mock_temp_device_count; }
  void setResolution(int) {}
  void setWaitForConversion(bool) {}
  void requestTemperatures() { _mock_temp_requested = true; }
  float getTempCByIndex(int) { return _mock_temp_reading; }
};

// Mock JsonDocument with field access and error simulation
struct JsonVariant {
  std::string s;
  double d = 0;
  bool is_str = false;
  bool valid = false;

  JsonVariant() : valid(false) {}
  JsonVariant(double v) : d(v), valid(true) {}
  JsonVariant(const std::string& v) : s(v), is_str(true), valid(true) {}

  template<typename T> bool is() const { return valid; }

  template<typename T>
  JsonVariant& operator=(const T& val) {
    if constexpr (std::is_constructible_v<std::string, T>) {
      s = val;
      is_str = true;
    } else {
      d = (double)val;
      is_str = false;
    }
    valid = true;
    return *this;
  }
  operator uint32_t() const { return (uint32_t)d; }
  operator int() const { return (int)d; }
  operator float() const { return (float)d; }
  operator double() const { return d; }
  operator const char*() const { return s.c_str(); }
};

struct JsonDocument {
  std::map<std::string, JsonVariant> fields;

  JsonVariant operator[](const char* key) const {
    auto it = fields.find(key);
    if (it != fields.end()) return it->second;
    return JsonVariant();
  }
  JsonVariant& operator[](const char* key) {
    return fields[key];
  }
  void clear() { fields.clear(); }
};

struct DeserializationError {
  bool is_err = false;
  DeserializationError(bool err = false) : is_err(err) {}
  operator bool() const { return is_err; }
};

inline DeserializationError deserializeJson(JsonDocument& doc, const char* json_str) {
  doc.clear();
  if (!json_str) return DeserializationError(true);
  std::string s(json_str);
  size_t start = s.find_first_not_of(" \t\r\n");
  size_t end = s.find_last_not_of(" \t\r\n");
  if (start == std::string::npos || end == std::string::npos || s[start] != '{' || s[end] != '}') {
    return DeserializationError(true);
  }
  // Corrupted syntax indicators
  if (s.find(": }") != std::string::npos || s.find(":,") != std::string::npos || s.find(":\n") != std::string::npos) {
    return DeserializationError(true);
  }

  // Parse "pkt": <int>
  size_t pkt_pos = s.find("\"pkt\"");
  if (pkt_pos != std::string::npos) {
    size_t colon = s.find(":", pkt_pos);
    if (colon != std::string::npos) {
      char* endptr = nullptr;
      long val = std::strtol(s.c_str() + colon + 1, &endptr, 10);
      doc["pkt"] = (uint32_t)val;
    }
  }

  // Parse "system": "<str>"
  size_t sys_pos = s.find("\"system\"");
  if (sys_pos != std::string::npos) {
    size_t q1 = s.find("\"", sys_pos + 8);
    if (q1 != std::string::npos) {
      size_t q2 = s.find("\"", q1 + 1);
      if (q2 != std::string::npos) {
        doc["system"] = s.substr(q1 + 1, q2 - q1 - 1);
      }
    }
  }

  return DeserializationError(false);
}

inline void serializeJson(const JsonDocument& doc, MockSerial& serial) {
  std::string out = "{";
  bool first = true;
  for (const auto& kv : doc.fields) {
    if (!first) out += ",";
    first = false;
    out += "\"" + kv.first + "\":";
    if (kv.second.is_str) {
      out += "\"" + kv.second.s + "\"";
    } else {
      out += std::to_string(kv.second.d);
    }
  }
  out += "}";
  serial.print(out.c_str());
}

// FreeRTOS Realistic Queue Mocks
typedef void* QueueHandle_t;
typedef void* TaskHandle_t;
typedef void (*TaskFunction_t)(void*);
#define pdMS_TO_TICKS(ms) (ms)
#define pdPASS 1

struct MockFreeRTOSQueue {
  int capacity = 2;
  size_t item_size = 0;
  std::deque<std::vector<uint8_t>> items;
  uint32_t total_sends = 0;
  uint32_t dropped_sends = 0;
  uint32_t total_receives = 0;
};

inline QueueHandle_t xQueueCreate(int capacity, size_t item_size) {
  MockFreeRTOSQueue* q = new MockFreeRTOSQueue();
  q->capacity = capacity;
  q->item_size = item_size;
  return (QueueHandle_t)q;
}

inline int xQueueSend(QueueHandle_t handle, const void* item, int) {
  if (!handle) return 0;
  MockFreeRTOSQueue* q = (MockFreeRTOSQueue*)handle;
  if ((int)q->items.size() >= q->capacity) {
    q->dropped_sends++;
    return 0; // Queue full
  }
  std::vector<uint8_t> buf(q->item_size);
  std::memcpy(buf.data(), item, q->item_size);
  q->items.push_back(buf);
  q->total_sends++;
  return pdPASS;
}

inline int xQueueReceive(QueueHandle_t handle, void* item, int) {
  if (!handle) return 0;
  MockFreeRTOSQueue* q = (MockFreeRTOSQueue*)handle;
  if (q->items.empty()) return 0;
  std::vector<uint8_t> buf = q->items.front();
  q->items.pop_front();
  std::memcpy(item, buf.data(), q->item_size);
  q->total_receives++;
  return pdPASS;
}

inline int xTaskCreatePinnedToCore(TaskFunction_t, const char*, uint32_t, void*, int, TaskHandle_t*, int) { return 1; }
inline void vTaskDelay(int) {}

// ESP Task Watchdog Mocks
struct esp_task_wdt_config_t {
  uint32_t timeout_ms;
  uint32_t idle_core_mask;
  bool trigger_panic;
};
inline void esp_task_wdt_init(const esp_task_wdt_config_t*) {}
inline void esp_task_wdt_init(uint32_t, bool) {}
inline void esp_task_wdt_add(void*) {}
inline void esp_task_wdt_reset() {}

#endif // ARDUINO_MOCK_H
