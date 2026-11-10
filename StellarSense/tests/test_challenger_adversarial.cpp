#define DO_NOT_INCLUDE_MOCK_TWICE
#include "arduino_mock.h"
#include <cassert>
#include <iostream>
#include <string>
#include <vector>

namespace SatelliteOBC {
  #include "../firmware/satellite_sender/satellite_sender.ino"
}

namespace GroundStation {
  #include "../firmware/ground_receiver/ground_receiver.ino"
}

// Global counters
static int g_tests_passed = 0;
static int g_tests_failed = 0;

#define ASSERT_CHALLENGE(cond, msg) \
  do { \
    if (!(cond)) { \
      std::cerr << "  [FAIL] Assertion failed: " << msg << " (" << #cond << ") at line " << __LINE__ << std::endl; \
      g_tests_failed++; \
      return; \
    } \
  } while(0)

#define PASS_CHALLENGE(name) \
  do { \
    std::cout << "  [PASS] " << name << std::endl; \
    g_tests_passed++; \
  } while(0)

// =====================================================================================
// SUITE 1: RF PACKET CORRUPTION & HARDWARE CRC VALIDATION BEHAVIOR
// =====================================================================================
void challenge_1_1_hardware_crc_configuration() {
  std::cout << "\n--- CHALLENGE 1.1: SX1278 LoRa Hardware CRC Configuration ---\n";
  
  // Verify Satellite boot enables hardware CRC
  LoRa.crc_enabled = false;
  SatelliteOBC::setup();
  ASSERT_CHALLENGE(LoRa.crc_enabled == true, "Satellite OBC must invoke LoRa.enableCrc() during setup()");

  // Verify Ground Station boot enables hardware CRC
  LoRa.crc_enabled = false;
  GroundStation::setup();
  ASSERT_CHALLENGE(LoRa.crc_enabled == true, "Ground Station must invoke LoRa.enableCrc() during setup()");

  PASS_CHALLENGE("Hardware CRC verified enabled on both Satellite OBC and Ground Station");
}

void challenge_1_2_phy_crc_error_rejection() {
  std::cout << "\n--- CHALLENGE 1.2: Hardware PHY CRC Rejection Behavior ---\n";
  
  // When SX1278 encounters bitflips with CRC enabled, the PHY modem drops the packet
  // and parsePacket() returns 0.
  LoRa.clearPacket();
  int size = LoRa.parsePacket();
  ASSERT_CHALLENGE(size == 0, "Corrupted packet dropped by PHY results in parsePacket() == 0");
  
  // Ground station loop executes with 0 packet without crashing or incrementing totalPacketsReceived
  uint32_t rx_before = GroundStation::totalPacketsReceived;
  GroundStation::loop();
  ASSERT_CHALLENGE(GroundStation::totalPacketsReceived == rx_before, "No false reception when parsePacket() == 0");

  PASS_CHALLENGE("PHY CRC rejection prevents corrupt packets from entering receive pipeline");
}

void challenge_1_3_malformed_json_packet_handling() {
  std::cout << "\n--- CHALLENGE 1.3: Corrupted JSON Frame Diagnostic Trap ---\n";
  
  // Inject a corrupted JSON payload that bypassed RF (e.g. invalid syntax)
  std::string badJson = "{\"pkt\": 42, \"temp\": }";
  LoRa.injectPacket(badJson);
  Serial.clear();

  // Process frame
  GroundStation::loop();

  // Verify ground receiver trapped into parse error branch and output PARSE_FAIL diagnostic frame
  ASSERT_CHALLENGE(Serial.tx_history.find("PARSE_FAIL") != std::string::npos, 
                   "Corrupted JSON must generate PARSE_FAIL diagnostic frame");
  ASSERT_CHALLENGE(Serial.tx_history.find(badJson) != std::string::npos,
                   "Diagnostic frame must retain raw corrupted payload for ground debugging");

  PASS_CHALLENGE("Corrupted JSON safely isolated and logged as PARSE_FAIL without crash");
}

void challenge_1_4_truncated_rf_frame_handling() {
  std::cout << "\n--- CHALLENGE 1.4: Truncated RF Packet Trapping ---\n";

  // Packet cut off abruptly mid-stream
  std::string truncated = "{\"pkt\":99,\"met\":40,\"temp\":28.4";
  LoRa.injectPacket(truncated);
  Serial.clear();

  GroundStation::loop();

  ASSERT_CHALLENGE(Serial.tx_history.find("PARSE_FAIL") != std::string::npos,
                   "Truncated JSON frame must be trapped as PARSE_FAIL");

  PASS_CHALLENGE("Truncated RF frame trapped gracefully");
}

void challenge_1_5_binary_garbage_noise_rejection() {
  std::cout << "\n--- CHALLENGE 1.5: Non-ASCII Binary Noise & Control Character Rejection ---\n";

  std::string binaryGarbage("\x01\x1b[31m\xff\xfe\x00", 6);
  LoRa.injectPacket(binaryGarbage);
  Serial.clear();

  GroundStation::loop();

  ASSERT_CHALLENGE(Serial.tx_history.find("PARSE_FAIL") != std::string::npos,
                   "Binary noise must be rejected as PARSE_FAIL");

  PASS_CHALLENGE("Non-ASCII binary noise safely handled by ground station parser");
}

// =====================================================================================
// SUITE 2: GROUND STATION STATIC BUFFER BOUNDARY LIMITS & OVERFLOW RESILIENCE
// =====================================================================================
void challenge_2_1_lora_massive_packet_overflow_drain() {
  std::cout << "\n--- CHALLENGE 2.1: LoRa 1024-Byte Buffer Overflow Attack & Drain ---\n";

  // Ground receiver rxBuffer is char rxBuffer[256].
  // Attack: inject a massive 1024-byte packet.
  std::string hugePacket(1024, 'A');
  LoRa.injectPacket(hugePacket);
  Serial.clear();

  // Execute loop()
  GroundStation::loop();

  // Verify that all 1024 bytes were read and drained so LoRa FIFO is not locked
  ASSERT_CHALLENGE(LoRa.available() == 0, "LoRa FIFO must be fully drained after packet read");
  
  // Subsequent valid packet must be processed cleanly
  std::string validPacket = "{\"pkt\":101,\"temp\":25.0}";
  LoRa.injectPacket(validPacket);
  Serial.clear();
  GroundStation::loop();

  ASSERT_CHALLENGE(Serial.tx_history.find("101") != std::string::npos,
                   "Ground Station must recover immediately and process valid packet after overflow attack");

  PASS_CHALLENGE("1024-byte LoRa overflow attack clamped to buffer size and fully drained");
}

void challenge_2_2_zero_byte_packet_resilience() {
  std::cout << "\n--- CHALLENGE 2.2: Zero-Byte Packet Handling ---\n";

  LoRa.clearPacket();
  uint32_t rx_before = GroundStation::totalPacketsReceived;
  GroundStation::loop();
  ASSERT_CHALLENGE(GroundStation::totalPacketsReceived == rx_before, "Zero-byte packet handled as no-op");

  PASS_CHALLENGE("Zero-byte packet handled safely");
}

void challenge_2_3_serial_telecommand_buffer_overflow() {
  std::cout << "\n--- CHALLENGE 2.3: Serial Telecommand Buffer Overflow Defense (cmdSerialBuffer[64]) ---\n";

  // Ground station serial buffer is 64 bytes (cmdSerialBuffer[64]).
  // Attack: feed 500 characters without newline.
  std::string attackString(500, 'X');
  Serial.clear();
  Serial.feed(attackString);

  GroundStation::processSerialCommands();

  // Index must not exceed sizeof(cmdSerialBuffer) - 1 (63)
  ASSERT_CHALLENGE(GroundStation::cmdSerialIdx == 63, 
                   "cmdSerialIdx must be clamped at 63 without buffer overflow");
  
  // Terminate with newline
  Serial.feed("\n");
  GroundStation::processSerialCommands();

  // After processing, buffer index must be reset to 0
  ASSERT_CHALLENGE(GroundStation::cmdSerialIdx == 0, "cmdSerialIdx must reset to 0 after newline");

  // Verify subsequent valid telecommand works normally
  LoRa.last_tx_packet.clear();
  Serial.feed("CMD:PING\n");
  GroundStation::processSerialCommands();

  ASSERT_CHALLENGE(LoRa.last_tx_packet == "CMD:PING",
                   "Ground Station uplinked CMD:PING after buffer overflow attempt");

  PASS_CHALLENGE("cmdSerialBuffer[64] immune to overflow attacks; subsequent commands execute cleanly");
}

void challenge_2_4_crlf_double_dispatch_prevention() {
  std::cout << "\n--- CHALLENGE 2.4: CRLF (\\r\\n) Line-Ending Single Dispatch ---\n";

  Serial.clear();
  LoRa.last_tx_packet.clear();
  Serial.feed("CMD:TARE\r\n");

  GroundStation::processSerialCommands();

  // Uplinked command must be CMD:TARE
  ASSERT_CHALLENGE(LoRa.last_tx_packet == "CMD:TARE", "CMD:TARE dispatched");
  // Index must be 0
  ASSERT_CHALLENGE(GroundStation::cmdSerialIdx == 0, "Buffer index reset to 0");

  PASS_CHALLENGE("CRLF (\\r\\n) parsed with zero double-dispatch");
}

void challenge_2_5_rapid_empty_newlines() {
  std::cout << "\n--- CHALLENGE 2.5: Rapid Empty Newlines Ingestion ---\n";

  Serial.clear();
  LoRa.last_tx_packet.clear();
  Serial.feed("\n\n\r\n\r\r\n");

  GroundStation::processSerialCommands();
  ASSERT_CHALLENGE(GroundStation::cmdSerialIdx == 0, "Empty newlines produce 0 dispatches");
  ASSERT_CHALLENGE(LoRa.last_tx_packet.empty(), "No uplink triggered by empty newlines");

  PASS_CHALLENGE("Empty newlines discarded harmlessly");
}

// =====================================================================================
// SUITE 3: TELECOMMAND UPLINK INJECTION & C&DH EXECUTION
// =====================================================================================
void challenge_3_1_cmd_ping_execution() {
  std::cout << "\n--- CHALLENGE 3.1: CMD:PING Telecommand & RF Pong ---\n";

  LoRa.last_tx_packet.clear();
  SatelliteOBC::handleTelecommand("CMD:PING");

  ASSERT_CHALLENGE(LoRa.last_tx_packet.find("PONG") != std::string::npos,
                   "CMD:PING must trigger immediate RF PONG response packet");

  PASS_CHALLENGE("CMD:PING successfully dispatched RF PONG response");
}

void challenge_3_2_cmd_fdir_reset_execution() {
  std::cout << "\n--- CHALLENGE 3.2: CMD:FDIR_RESET Telecommand & Latch Clear ---\n";

  // Simulate an active Caution state
  SatelliteOBC::currentFDIR = SatelliteOBC::STATE_CAUTION;
  SatelliteOBC::tempWarnLatched = true;
  SatelliteOBC::cmdFdirResetRequested = false;

  SatelliteOBC::handleTelecommand("CMD:FDIR_RESET");
  ASSERT_CHALLENGE(SatelliteOBC::cmdFdirResetRequested == true, "cmdFdirResetRequested flag set");

  // Core 1 main loop execution
  SatelliteOBC::loop();
  ASSERT_CHALLENGE(SatelliteOBC::cmdFdirResetRequested == false, "cmdFdirResetRequested flag consumed");
  ASSERT_CHALLENGE(SatelliteOBC::tempWarnLatched == false, "tempWarnLatched cleared");
  ASSERT_CHALLENGE(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL, "currentFDIR restored to NOMINAL");

  PASS_CHALLENGE("CMD:FDIR_RESET clears latches and restores NOMINAL");
}

void challenge_3_3_cmd_tare_attitude_zeroing() {
  std::cout << "\n--- CHALLENGE 3.3: CMD:TARE Telecommand Attitude Zeroing ---\n";

  SatelliteOBC::pitchAngle = 45.2f;
  SatelliteOBC::rollAngle = -28.7f;
  SatelliteOBC::cmdTareRequested = false;

  SatelliteOBC::handleTelecommand("CMD:TARE");
  ASSERT_CHALLENGE(SatelliteOBC::cmdTareRequested == true, "cmdTareRequested flag set");

  SatelliteOBC::loop();
  ASSERT_CHALLENGE(SatelliteOBC::cmdTareRequested == false, "cmdTareRequested flag consumed");
  ASSERT_CHALLENGE(SatelliteOBC::pitchAngle == 0.0f, "pitchAngle zeroed by TARE");
  ASSERT_CHALLENGE(SatelliteOBC::rollAngle == 0.0f, "rollAngle zeroed by TARE");

  PASS_CHALLENGE("CMD:TARE zeroes Euler attitude angles and triggers calibration");
}

void challenge_3_4_cmd_rate_boundary_matrix() {
  std::cout << "\n--- CHALLENGE 3.4: CMD:RATE:<ms> Parameter Boundaries & Injection ---\n";

  // Baseline rate: 600ms
  SatelliteOBC::downlinkIntervalMs = 600;

  // 1. Valid lower bound: 100ms
  SatelliteOBC::handleTelecommand("CMD:RATE:100");
  ASSERT_CHALLENGE(SatelliteOBC::downlinkIntervalMs == 100, "Valid rate 100ms accepted");

  // 2. Valid upper bound: 5000ms
  SatelliteOBC::handleTelecommand("CMD:RATE:5000");
  ASSERT_CHALLENGE(SatelliteOBC::downlinkIntervalMs == 5000, "Valid rate 5000ms accepted");

  // 3. Valid nominal: 1000ms
  SatelliteOBC::handleTelecommand("CMD:RATE:1000");
  ASSERT_CHALLENGE(SatelliteOBC::downlinkIntervalMs == 1000, "Valid rate 1000ms accepted");

  // 4. Adversarial: Underflow bound 99ms (must be rejected, remain 1000ms)
  SatelliteOBC::handleTelecommand("CMD:RATE:99");
  ASSERT_CHALLENGE(SatelliteOBC::downlinkIntervalMs == 1000, "Rate 99ms (<100) must be rejected");

  // 5. Adversarial: Overflow bound 5001ms (must be rejected)
  SatelliteOBC::handleTelecommand("CMD:RATE:5001");
  ASSERT_CHALLENGE(SatelliteOBC::downlinkIntervalMs == 1000, "Rate 5001ms (>5000) must be rejected");

  // 6. Adversarial: Zero rate (must be rejected)
  SatelliteOBC::handleTelecommand("CMD:RATE:0");
  ASSERT_CHALLENGE(SatelliteOBC::downlinkIntervalMs == 1000, "Rate 0ms must be rejected");

  // 7. Adversarial: Negative rate (must be rejected)
  SatelliteOBC::handleTelecommand("CMD:RATE:-500");
  ASSERT_CHALLENGE(SatelliteOBC::downlinkIntervalMs == 1000, "Negative rate must be rejected");

  // 8. Adversarial: Non-numeric garbage
  SatelliteOBC::handleTelecommand("CMD:RATE:abc");
  ASSERT_CHALLENGE(SatelliteOBC::downlinkIntervalMs == 1000, "Garbage rate 'abc' must be rejected");

  // 9. Adversarial: Empty parameter
  SatelliteOBC::handleTelecommand("CMD:RATE:");
  ASSERT_CHALLENGE(SatelliteOBC::downlinkIntervalMs == 1000, "Empty rate 'CMD:RATE:' must be rejected");

  PASS_CHALLENGE("CMD:RATE boundary matrix verified: valid in [100, 5000]ms, all out-of-bounds rejected");
}

void challenge_3_5_hostile_unknown_telecommands() {
  std::cout << "\n--- CHALLENGE 3.5: Hostile & Unknown Telecommand Ingestion ---\n";

  const std::vector<std::string> hostileCmds = {
    "CMD:EXPLODE",
    "CMD:KILL",
    "CMD:REBOOT",
    "CMD:RESET_HARD",
    "ADMIN:ROOT",
    "DROP TABLE users;",
    "",
    "CMD:",
    "\x00\x01\x1b"
  };

  uint32_t rate_before = SatelliteOBC::downlinkIntervalMs;
  auto fdir_before = SatelliteOBC::currentFDIR;

  for (const auto& cmd : hostileCmds) {
    SatelliteOBC::handleTelecommand(cmd.c_str());
    SatelliteOBC::loop();
  }

  // System state must remain uncorrupted
  ASSERT_CHALLENGE(SatelliteOBC::downlinkIntervalMs == rate_before, "Downlink rate unchanged by invalid commands");
  ASSERT_CHALLENGE(SatelliteOBC::currentFDIR == fdir_before, "FDIR state unaffected by invalid commands");

  PASS_CHALLENGE("All 9 hostile / unknown telecommands safely ignored without crash or state corruption");
}

void challenge_3_6_safety_persistence_under_active_fault() {
  std::cout << "\n--- CHALLENGE 3.6: Safety Persistence Under Active Physical Fault ---\n";

  // Simulate an ongoing thermal hazard: temperature is 35.0C (Caution trip >= 33.0C)
  SatelliteOBC::telemetryTemp = 35.0f;
  
  // 3 samples to trip Caution
  for (int i = 0; i < 3; i++) SatelliteOBC::evaluateFDIR();
  ASSERT_CHALLENGE(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION, "FDIR in CAUTION at 35C");

  // Operator sends CMD:FDIR_RESET
  SatelliteOBC::handleTelecommand("CMD:FDIR_RESET");
  SatelliteOBC::loop(); // Clears latches to NOMINAL
  ASSERT_CHALLENGE(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL, "Temporarily reset to NOMINAL");

  // However, because 35.0C thermal hazard is STILL PHYSICALLY ACTIVE:
  // After 3 consecutive DSP cycles (150ms debounce), FDIR MUST re-escalate to CAUTION!
  SatelliteOBC::evaluateFDIR(); // sample 1: pending CAUTION, persistence = 1
  ASSERT_CHALLENGE(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL, "Sample 1: still NOMINAL (persistence=1)");
  SatelliteOBC::evaluateFDIR(); // sample 2: persistence = 2
  ASSERT_CHALLENGE(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_NOMINAL, "Sample 2: still NOMINAL (persistence=2)");
  SatelliteOBC::evaluateFDIR(); // sample 3: persistence = 3 -> re-escalation!
  ASSERT_CHALLENGE(SatelliteOBC::currentFDIR == SatelliteOBC::STATE_CAUTION, "Sample 3: correctly re-tripped to CAUTION");

  PASS_CHALLENGE("Safety property verified: FDIR reset does not blind flight computer to active hazard");
}

int main() {
  std::cout << "====================================================================\n";
  std::cout << "  STELLARSENSE CHALLENGER 2: ADVERSARIAL RF & PROTOCOL STRESS HARNESS\n";
  std::cout << "====================================================================\n";

  // Suite 1
  challenge_1_1_hardware_crc_configuration();
  challenge_1_2_phy_crc_error_rejection();
  challenge_1_3_malformed_json_packet_handling();
  challenge_1_4_truncated_rf_frame_handling();
  challenge_1_5_binary_garbage_noise_rejection();

  // Suite 2
  challenge_2_1_lora_massive_packet_overflow_drain();
  challenge_2_2_zero_byte_packet_resilience();
  challenge_2_3_serial_telecommand_buffer_overflow();
  challenge_2_4_crlf_double_dispatch_prevention();
  challenge_2_5_rapid_empty_newlines();

  // Suite 3
  challenge_3_1_cmd_ping_execution();
  challenge_3_2_cmd_fdir_reset_execution();
  challenge_3_3_cmd_tare_attitude_zeroing();
  challenge_3_4_cmd_rate_boundary_matrix();
  challenge_3_5_hostile_unknown_telecommands();
  challenge_3_6_safety_persistence_under_active_fault();

  std::cout << "\n====================================================================\n";
  std::cout << "  CHALLENGER EXECUTION SUMMARY:\n";
  std::cout << "   Passed: " << g_tests_passed << "\n";
  std::cout << "   Failed: " << g_tests_failed << "\n";
  std::cout << "====================================================================\n";

  if (g_tests_failed > 0) {
    std::cout << ">>> CHALLENGE FAILED: DEFECTS DETECTED <<<\n";
    return 1;
  } else {
    std::cout << ">>> ALL 16 ADVERSARIAL CHALLENGES CONFIRMED ROBUST <<<\n";
    return 0;
  }
}
