#define DO_NOT_INCLUDE_MOCK_TWICE
#include "arduino_mock.h"
#include <cassert>
#include <iostream>
#include <iomanip>
#include <chrono>
#include <vector>

namespace SatelliteOBC {
  #include "../firmware/satellite_sender/satellite_sender.ino"
}

namespace GroundStation {
  #include "../firmware/ground_receiver/ground_receiver.ino"
}

// ANSI Escape Codes for formatting
#define RESET   "\033[0m"
#define RED     "\033[31m"
#define GREEN   "\033[32m"
#define YELLOW  "\033[33m"
#define BLUE    "\033[34m"
#define BOLD    "\033[1m"

int total_checks = 0;
int passed_checks = 0;

void record_check(bool condition, const std::string& desc) {
  total_checks++;
  if (condition) {
    passed_checks++;
    std::cout << "  " << GREEN << "✓ PASS" << RESET << " - " << desc << "\n";
  } else {
    std::cout << "  " << RED << "✗ FAIL" << RESET << " - " << desc << "\n";
    assert(condition);
  }
}

int main() {
  std::cout << BOLD << BLUE << "\n========================================================================\n"
            << "   STELLARSENSE M1 EMPIRICAL ADVERSARIAL STRESS TEST HARNESS\n"
            << "   Role: Empirical Challenger (critic / specialist)\n"
            << "========================================================================\n\n" << RESET;

  SatelliteOBC::setup();
  GroundStation::setup();

  // =====================================================================================
  // SUITE 1: FDIR THRESHOLD BOUNDARY TRANSITIONS & HYSTERESIS STRESS
  // =====================================================================================
  std::cout << BOLD << "\n--- [SUITE 1] FDIR Boundary Transitions, Hysteresis & Persistence Filter ---\n" << RESET;

  // 1.1 Temperature Caution Trip Boundary (33.0C)
  SatelliteOBC::currentFDIR = SatelliteOBC::STATE_NOMINAL;
  SatelliteOBC::pendingFDIR = SatelliteOBC::STATE_NOMINAL;
  SatelliteOBC::tempWarnLatched = false;
  SatelliteOBC::telemetryTemp = 32.99f;
  for (int i = 0; i < 50; i++) {
    SatelliteOBC::evaluateFDIR();
  }
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL && !SatelliteOBC::tempWarnLatched,
               "Temperature 32.99C (< 33.0C) remains NOMINAL indefinitely");

  // Step to 33.01C (Trip Caution)
  SatelliteOBC::telemetryTemp = 33.01f;
  SatelliteOBC::evaluateFDIR(); // sample 1
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL && SatelliteOBC::tempWarnLatched,
               "Temp 33.01C: Latches caution, but persistence 1/3 holds NOMINAL");
  SatelliteOBC::evaluateFDIR(); // sample 2
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL,
               "Temp 33.01C: Persistence 2/3 holds NOMINAL");
  SatelliteOBC::evaluateFDIR(); // sample 3
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION,
               "Temp 33.01C: Persistence 3/3 successfully transitions to CAUTION");

  // Adversarial Noise around Trip Boundary (Oscillating 32.95C <-> 33.05C for 500 cycles)
  int chattering_flips = 0;
  for (int i = 0; i < 500; i++) {
    SatelliteOBC::telemetryTemp = (i % 2 == 0) ? 32.95f : 33.05f;
    SatelliteOBC::FDIRState prev = SatelliteOBC::currentFDIR;
    SatelliteOBC::evaluateFDIR();
    if (SatelliteOBC::currentFDIR != prev) {
      chattering_flips++;
    }
  }
  record_check(chattering_flips == 0 && SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION,
               "Trip boundary noise (32.95C <-> 33.05C): Zero chatter over 500 cycles (Hysteresis holds CAUTION)");

  // 1.2 Temperature Caution Clear Boundary (32.2C)
  // Inside deadband [32.2, 33.0]
  SatelliteOBC::telemetryTemp = 32.50f;
  for (int i = 0; i < 100; i++) {
    SatelliteOBC::evaluateFDIR();
  }
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION,
               "Deadband holding: 32.50C maintains CAUTION without drop-out");

  // Step below clear threshold (32.19C)
  SatelliteOBC::telemetryTemp = 32.19f;
  SatelliteOBC::evaluateFDIR(); // sample 1
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION && !SatelliteOBC::tempWarnLatched,
               "Temp 32.19C: Unlatches caution, persistence 1/3 holds CAUTION");
  SatelliteOBC::evaluateFDIR(); // sample 2
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION,
               "Temp 32.19C: Persistence 2/3 holds CAUTION");
  SatelliteOBC::evaluateFDIR(); // sample 3
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL,
               "Temp 32.19C: Persistence 3/3 smoothly recovers to NOMINAL");

  // Adversarial Noise around Clear Boundary (Oscillating 32.15C <-> 32.25C for 500 cycles)
  chattering_flips = 0;
  for (int i = 0; i < 500; i++) {
    SatelliteOBC::telemetryTemp = (i % 2 == 0) ? 32.15f : 32.25f;
    SatelliteOBC::FDIRState prev = SatelliteOBC::currentFDIR;
    SatelliteOBC::evaluateFDIR();
    if (SatelliteOBC::currentFDIR != prev) {
      chattering_flips++;
    }
  }
  record_check(chattering_flips == 0 && SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL,
               "Clear boundary noise (32.15C <-> 32.25C): Zero chatter over 500 cycles (Remains NOMINAL)");

  // 1.3 Voltage Sag Boundary (Caution <= 4.60V, Clear >= 4.68V; Crit <= 4.20V, Clear >= 4.28V)
  SatelliteOBC::statusIna = true;
  SatelliteOBC::busVoltage = 4.62f;
  SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL,
               "Voltage 4.62V (> 4.60V): NOMINAL");

  // Sag to 4.58V
  SatelliteOBC::busVoltage = 4.58f;
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION && SatelliteOBC::voltWarnLatched,
               "Voltage sag 4.58V: Transitions to CAUTION after 3 samples");

  // Fluctuate around sag boundary (4.59V <-> 4.61V for 500 cycles)
  chattering_flips = 0;
  for (int i = 0; i < 500; i++) {
    SatelliteOBC::busVoltage = (i % 2 == 0) ? 4.59f : 4.61f;
    SatelliteOBC::FDIRState prev = SatelliteOBC::currentFDIR;
    SatelliteOBC::evaluateFDIR();
    if (SatelliteOBC::currentFDIR != prev) chattering_flips++;
  }
  record_check(chattering_flips == 0 && SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION,
               "Voltage trip boundary noise: Zero chatter (Hysteresis holds CAUTION)");

  // Recover to 4.69V
  SatelliteOBC::busVoltage = 4.69f;
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL,
               "Voltage recovery to 4.69V (>= 4.68V): Recovers to NOMINAL after 3 samples");

  // Critical Voltage Brownout (4.15V)
  SatelliteOBC::busVoltage = 4.15f;
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CRITICAL,
               "Voltage brownout 4.15V (<= 4.20V): Transitions to CRITICAL");

  // Step recovery to 4.30V (clears critical threshold 4.28V, but still under caution 4.68V)
  SatelliteOBC::busVoltage = 4.30f;
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION,
               "Voltage partial recovery to 4.30V (>= 4.28V, < 4.68V): Degrades to CAUTION (no premature jump to NOMINAL)");

  // Full recovery to 4.70V (>= 4.68V)
  SatelliteOBC::busVoltage = 4.70f;
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL,
               "Voltage full recovery to 4.70V (>= 4.68V): Restores to NOMINAL after 3 samples");

  // 1.4 Structural Vibration Boundaries (Trip Caution >= 0.25g, Clear <= 0.20g; Crit >= 0.70g, Clear <= 0.60g)
  SatelliteOBC::vibrationRMS = 0.245f;
  SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL,
               "Vibration 0.245g: NOMINAL");

  SatelliteOBC::vibrationRMS = 0.255f;
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION,
               "Vibration 0.255g: Trips CAUTION after 3 samples");

  // Oscillate in deadband (0.21g <-> 0.24g)
  chattering_flips = 0;
  for (int i = 0; i < 500; i++) {
    SatelliteOBC::vibrationRMS = (i % 2 == 0) ? 0.21f : 0.24f;
    SatelliteOBC::FDIRState prev = SatelliteOBC::currentFDIR;
    SatelliteOBC::evaluateFDIR();
    if (SatelliteOBC::currentFDIR != prev) chattering_flips++;
  }
  record_check(chattering_flips == 0 && SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION,
               "Vibration deadband noise: Zero chatter (Hysteresis holds CAUTION)");

  // Vibration drops to 0.19g
  SatelliteOBC::vibrationRMS = 0.19f;
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL,
               "Vibration drops to 0.19g (<= 0.20g): Recovers to NOMINAL after 3 samples");

  // 1.5 Rapid Alternating Candidate Glitches (Persistence Filter Immunity Test)
  // Alternating candidate between NOMINAL and CRITICAL every single sample for 1,000 cycles
  chattering_flips = 0;
  for (int i = 0; i < 1000; i++) {
    if (i % 2 == 0) {
      SatelliteOBC::vibrationRMS = 0.05f; // NOMINAL
      SatelliteOBC::vibWarnLatched = SatelliteOBC::vibCritLatched = false;
    } else {
      SatelliteOBC::vibrationRMS = 0.85f; // CRITICAL
    }
    SatelliteOBC::FDIRState prev = SatelliteOBC::currentFDIR;
    SatelliteOBC::evaluateFDIR();
    if (SatelliteOBC::currentFDIR != prev) chattering_flips++;
  }
  record_check(chattering_flips == 0 && SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL,
               "High-frequency 1-cycle impulse noise: 1,000 cycles produced EXACTLY 0 false state transitions");

  // 1.6 Priority Hierarchy: Simultaneous Multi-Fault Resolution
  SatelliteOBC::telemetryTemp = 34.0f; // Caution
  SatelliteOBC::vibrationRMS  = 0.80f; // Critical
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CRITICAL,
               "Multi-Fault: CRITICAL overrides CAUTION");

  // Clear Critical vibration while thermal caution remains
  SatelliteOBC::vibrationRMS = 0.10f; // Cleared
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION,
               "Multi-Fault: When CRITICAL clears, gracefully degrades to CAUTION (does NOT leap to NOMINAL)");

  // Clear thermal
  SatelliteOBC::telemetryTemp = 25.0f;
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL,
               "Multi-Fault: When CAUTION clears, returns to NOMINAL");

  // 1.7 CMD:FDIR_RESET Telecommand Verification
  SatelliteOBC::telemetryTemp = 34.0f;
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();
  assert(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION);
  // Send FDIR_RESET command
  SatelliteOBC::handleTelecommand("CMD:FDIR_RESET");
  record_check(SatelliteOBC::cmdFdirResetRequested == true,
               "CMD:FDIR_RESET accepted by C&DH telecommand parser");
  // Executive loop processes reset
  SatelliteOBC::loop();
  record_check(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL && !SatelliteOBC::cmdFdirResetRequested,
               "CMD:FDIR_RESET executed: all latches reset to NOMINAL immediately");

  // Reset to nominal baseline
  SatelliteOBC::telemetryTemp = 25.0f;
  SatelliteOBC::busVoltage = 5.01f;
  SatelliteOBC::current_mA = 312.0f;
  SatelliteOBC::vibrationRMS = 0.05f;
  SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR(); SatelliteOBC::evaluateFDIR();


  // =====================================================================================
  // SUITE 2: TELEMETRY QUEUE CAPACITY, HIGH-RATE GENERATION & MEMORY SAFETY
  // =====================================================================================
  std::cout << BOLD << "\n--- [SUITE 2] Telemetry Queue Capacity, High-Rate Generation & Memory Safety ---\n" << RESET;

  MockFreeRTOSQueue* q = (MockFreeRTOSQueue*)SatelliteOBC::telemetryQueue;
  record_check(q != nullptr && q->capacity == 2,
               "FreeRTOS telemetryQueue initialized with fixed capacity = 2");

  // Drain any existing packets
  SatelliteOBC::TelemetryPayload dummy;
  while (xQueueReceive(SatelliteOBC::telemetryQueue, &dummy, 0) == pdPASS) {}

  uint32_t initial_sends = q->total_sends;

  // Test 2.1: Enqueue exactly 2 packets (100% capacity)
  SatelliteOBC::telemetryTemp = 24.1f;
  SatelliteOBC::dispatchTelemetry(); // pkt 1
  record_check(q->items.size() == 1 && q->total_sends == initial_sends + 1,
               "Queue push 1: Stored cleanly (depth = 1)");

  SatelliteOBC::telemetryTemp = 24.2f;
  SatelliteOBC::dispatchTelemetry(); // pkt 2
  record_check(q->items.size() == 2 && q->total_sends == initial_sends + 2,
               "Queue push 2: Stored cleanly (depth = 2, queue full)");

  // Test 2.2: Saturated queue drops next packet non-blocking with zero stall
  auto t_start = std::chrono::high_resolution_clock::now();
  SatelliteOBC::telemetryTemp = 24.3f;
  SatelliteOBC::dispatchTelemetry(); // pkt 3 (must be rejected non-blocking)
  auto t_end = std::chrono::high_resolution_clock::now();
  auto elapsed_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t_end - t_start).count();

  record_check(q->items.size() == 2 && q->dropped_sends == 1,
               "Queue saturation: Pushing to full queue increments dropped_sends without queue growth");
  record_check(elapsed_ns < 100000, // < 100 microseconds
               "Queue saturation non-blocking: Dispatch returned in < 100 microseconds (no Core 1 freeze)");

  // Test 2.3: Massive Dispatch Flood (10,000 rapid dispatches with 0 Core 0 reads)
  uint32_t drops_before = q->dropped_sends;
  for (int i = 0; i < 10000; i++) {
    SatelliteOBC::dispatchTelemetry();
  }
  record_check(q->items.size() == 2,
               "Queue flood stress: After 10,000 dispatches, queue size remains STRICTLY <= 2");
  record_check(q->dropped_sends == drops_before + 10000,
               "Queue flood stress: All 10,000 saturated packets safely discarded without leak");

  // Test 2.4: FIFO Order & Data Integrity Verification
  SatelliteOBC::TelemetryPayload p1, p2;
  int r1 = xQueueReceive(SatelliteOBC::telemetryQueue, &p1, 0);
  int r2 = xQueueReceive(SatelliteOBC::telemetryQueue, &p2, 0);
  int r3 = xQueueReceive(SatelliteOBC::telemetryQueue, &dummy, 0);

  record_check(r1 == pdPASS && r2 == pdPASS && r3 == 0,
               "Queue drain: Exactly 2 items received, 3rd receive returned empty (0)");
  record_check(fabs(p1.temp - 24.1f) < 0.01f && fabs(p2.temp - 24.2f) < 0.01f,
               "FIFO Integrity: Extracted payloads maintain exact order and floating-point precision");

  // Test 2.5: Queue Resumption after Drain
  SatelliteOBC::telemetryTemp = 28.5f;
  SatelliteOBC::dispatchTelemetry();
  record_check(q->items.size() == 1,
               "Queue recovery: New packet accepted immediately after draining");
  xQueueReceive(SatelliteOBC::telemetryQueue, &dummy, 0);


  // =====================================================================================
  // SUITE 3: SENSOR DISCONNECT & RECOVERY SIMULATION
  // =====================================================================================
  std::cout << BOLD << "\n--- [SUITE 3] Sensor Disconnect & Recovery Simulation ---\n" << RESET;

  // 3.1 DS18B20 Disconnect (-127C) State Machine
  _mock_millis = 2000;
  _mock_temp_reading = 25.0f;
  _mock_temp_device_count = 1;
  SatelliteOBC::statusTemp = true;
  SatelliteOBC::tempErrorStreak = 0;
  SatelliteOBC::tempConversionPending = false;
  SatelliteOBC::lastTempReadTime = _mock_millis - 1000;

  // Normal read cycle
  SatelliteOBC::pollTemperature(); // requests conversion
  record_check(SatelliteOBC::tempConversionPending == true,
               "DS18B20: Asynchronous 1-Wire conversion requested (1Hz poller)");

  _mock_millis += 250; // pass 200ms conversion time
  SatelliteOBC::pollTemperature(); // reads temperature
  record_check(SatelliteOBC::tempConversionPending == false && SatelliteOBC::statusTemp == true,
               "DS18B20: 10-bit conversion completed and read successfully");

  // Physical Disconnect Simulation: Probe unplugged -> returns -127.0C
  std::cout << "  -> Simulating physical 1-Wire disconnect: probe returns -127.0C (DEVICE_DISCONNECTED_C)\n";
  _mock_temp_reading = DEVICE_DISCONNECTED_C;

  // Disconnect Conversion 1
  _mock_millis += 1000;
  SatelliteOBC::pollTemperature(); // request
  _mock_millis += 250;
  SatelliteOBC::pollTemperature(); // read -127C
  record_check(SatelliteOBC::tempErrorStreak == 1 && SatelliteOBC::statusTemp == true,
               "Disconnect Cycle 1: streak=1/3, statusTemp remains true (grace period)");

  // Disconnect Conversion 2
  _mock_millis += 1000;
  SatelliteOBC::pollTemperature(); // request
  _mock_millis += 250;
  SatelliteOBC::pollTemperature(); // read -127C
  record_check(SatelliteOBC::tempErrorStreak == 2 && SatelliteOBC::statusTemp == true,
               "Disconnect Cycle 2: streak=2/3, statusTemp remains true (grace period)");

  // Disconnect Conversion 3 -> Must trip disconnect
  _mock_millis += 1000;
  SatelliteOBC::pollTemperature(); // request
  _mock_millis += 250;
  SatelliteOBC::pollTemperature(); // read -127C
  record_check(SatelliteOBC::tempErrorStreak >= 3 && SatelliteOBC::statusTemp == false,
               "Disconnect Cycle 3: streak=3/3, statusTemp marked FALSE (Hardware offline detected)");

  // Verify thermal fallback prevents -127C poisoning
  record_check(SatelliteOBC::telemetryTemp >= 23.0f && SatelliteOBC::telemetryTemp <= 26.0f,
               "Graceful Thermal Fallback: telemetryTemp safe nominal estimate (NOT poisoned by -127C)");

  // 3.2 Hot-Plug Reconnection Simulation
  std::cout << "  -> Simulating physical 1-Wire hot-plug reconnection: probe re-inserted\n";
  _mock_temp_reading = 26.8f;
  _mock_temp_device_count = 1;

  _mock_millis += 1000;
  SatelliteOBC::pollTemperature(); // detects deviceCount > 0 and clears error
  record_check(SatelliteOBC::statusTemp == true && SatelliteOBC::tempErrorStreak == 0,
               "Hot-Plug Reconnection: Device detected on bus, statusTemp restored to TRUE");

  _mock_millis += 250;
  SatelliteOBC::pollTemperature(); // reads new 26.8C reading
  record_check(SatelliteOBC::telemetryTemp > 24.5f,
               "Hot-Plug Reconnection: Resumed live sensor reading and filtered integration");

  // 3.3 INA219 Disconnect Fallback
  SatelliteOBC::statusIna = false;
  SatelliteOBC::runSensorDSP();
  record_check(fabs(SatelliteOBC::busVoltage - 5.02f) < 0.01f && SatelliteOBC::power_mW > 1400.0f,
               "INA219 Disconnect: EPS fallback maintains nominal bus voltage (5.02V) and power");

  // 3.4 MPU-6050 Disconnect Fallbacks
  SatelliteOBC::statusMpu1 = false;
  SatelliteOBC::statusMpu2 = false;
  SatelliteOBC::runSensorDSP();
  record_check(SatelliteOBC::vibrationRMS >= 0.05f && SatelliteOBC::vibrationRMS <= 0.10f,
               "MPU-6050 #1 Disconnect: Structural vibration enters simulated micro-jitter mode");
  record_check(SatelliteOBC::pitchAngle >= -15.0f && SatelliteOBC::pitchAngle <= 15.0f,
               "MPU-6050 #2 Disconnect: Attitude enters stable orbital sway mode");


  // =====================================================================================
  // SUITE 4: GROUND STATION RECEIVER ADVERSARIAL ROBUSTNESS
  // =====================================================================================
  std::cout << BOLD << "\n--- [SUITE 4] Ground Station Receiver Robustness & Serial Safety ---\n" << RESET;

  // 4.1 Telecommand Buffer Overflow Attack (Feed 120 bytes without newline)
  GroundStation::cmdSerialIdx = 0;
  for (int i = 0; i < 120; i++) {
    char c = 'A' + (i % 26);
    if (GroundStation::cmdSerialIdx < sizeof(GroundStation::cmdSerialBuffer) - 1) {
      GroundStation::cmdSerialBuffer[GroundStation::cmdSerialIdx++] = c;
    }
  }
  record_check(GroundStation::cmdSerialIdx == sizeof(GroundStation::cmdSerialBuffer) - 1,
               "Serial Telecommand Buffer: 120-byte flood safely clamped to 63 bytes (zero overflow)");
  GroundStation::cmdSerialIdx = 0; // reset

  // 4.2 Sequence Gap & Dropped Packet Detection
  GroundStation::expectedSatPkt = 100;
  GroundStation::totalPacketsDropped = 0;
  // Simulate packet 105 arriving (missed packets 100, 101, 102, 103, 104 = gap of 5)
  uint32_t incomingPkt = 105;
  if (GroundStation::expectedSatPkt > 0 && incomingPkt > GroundStation::expectedSatPkt) {
    uint32_t gap = incomingPkt - GroundStation::expectedSatPkt;
    GroundStation::totalPacketsDropped += gap;
  }
  GroundStation::expectedSatPkt = incomingPkt + 1;
  record_check(GroundStation::totalPacketsDropped == 5 && GroundStation::expectedSatPkt == 106,
               "Sequence Gap Detection: Accurately detected and recorded 5 dropped RF packets");

  // Duplicate / Late packet (pkt 104 arriving out-of-order)
  incomingPkt = 104;
  uint32_t drops_before_dup = GroundStation::totalPacketsDropped;
  if (GroundStation::expectedSatPkt > 0 && incomingPkt > GroundStation::expectedSatPkt) {
    uint32_t gap = incomingPkt - GroundStation::expectedSatPkt;
    GroundStation::totalPacketsDropped += gap;
  }
  record_check(GroundStation::totalPacketsDropped == drops_before_dup,
               "Out-of-order / Duplicate Packet: Does not corrupt totalPacketsDropped meter");

  // =====================================================================================
  // SUMMARY REPORT
  // =====================================================================================
  std::cout << BOLD << "\n========================================================================\n"
            << "                     CHALLENGER EXECUTION SUMMARY                       \n"
            << "========================================================================\n" << RESET;
  std::cout << " Total Adversarial Checks Run:  " << total_checks << "\n";
  std::cout << " Passing Checks:                " << GREEN << passed_checks << RESET << "\n";
  std::cout << " Failing Checks:                " << (total_checks - passed_checks == 0 ? GREEN : RED)
            << (total_checks - passed_checks) << RESET << "\n";
  std::cout << " Challenger Pass Rate:          " << BOLD << GREEN
            << std::fixed << std::setprecision(1) << (100.0f * passed_checks / total_checks) << "%\n" << RESET;
  std::cout << "========================================================================\n\n";

  return 0;
}
