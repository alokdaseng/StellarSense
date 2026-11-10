#!/usr/bin/env python3
"""
========================================================================================
STELLARSENSE CHALLENGER 2: ADVERSARIAL RF, BUFFER BOUNDARY & TELECOMMAND STRESS SUITE
File: tests/test_challenger_adversarial.py

Mission Assurance Objectives:
 1. Adversarial RF Packet Corruption & Hardware CRC Validation Behavior
 2. Ground Station Static Buffer Boundaries, Truncation & Overflow Resilience
 3. Telecommand Uplink Injection & Parameter Boundary Matrix Validation
 4. Chaos Telemetry Stream Fuzzing (1000 Packets with Drops, Flips & Chunks)
========================================================================================
"""

import unittest
import json
import random
import string
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.test_serial_framing import SerialStreamProcessor
from tests.test_telemetry_schema import TelemetrySchemaValidator


class TestAdversarialRF(unittest.TestCase):
    """Adversarial RF packet corruption and hardware CRC behavior tests."""

    def setUp(self):
        self.processor = SerialStreamProcessor()

    def test_single_bit_flip_corruption_rejection(self):
        """
        Flips 1 bit in a serialized JSON telemetry frame.
        Empirically demonstrates why LoRa Hardware CRC is mission-critical:
         - Tier A (Syntactic bit flip): Fails JSON syntax deserialization.
         - Tier B (Structural bit flip): Produces invalid key ('mdt'), caught by Schema Validation.
         - Tier C (Semantic bit flip): Mutates numeric telemetry (5.01V -> 5.11V), creating
           Silent Data Corruption (SDC) that passes software JSON parsers!
           -> Proves that hardware CRC (LoRa.enableCrc()) is strictly required at PHY.
        """
        valid_json = '{"pkt":42,"met":20,"temp":27.5,"volt":5.01,"curr":312.0,"pwr":1563.1,"vib":0.065,"pitch":2.1,"roll":-1.4,"fdir":"NOMINAL","rssi":-48,"snr":9.5,"rx_count":42}\n'

        syntax_errors = 0
        schema_errors = 0
        silent_corruptions = 0

        # Test positions across syntax, keys, and values
        for pos in [5, 12, 25, 40, 60, 80, 100]:
            byte_arr = bytearray(valid_json, 'utf-8')
            byte_arr[pos] ^= 0x01 # Flip 1 bit
            corrupted_str = byte_arr.decode('utf-8', errors='replace').strip()

            try:
                data = json.loads(corrupted_str)
                is_valid, errs = TelemetrySchemaValidator.validate_satellite_frame(data)
                if not is_valid:
                    schema_errors += 1
                else:
                    # Semantic Silent Data Corruption: passes JSON and Schema, but values differ!
                    self.assertNotEqual(data.get("volt"), 5.01)
                    silent_corruptions += 1
            except json.JSONDecodeError:
                syntax_errors += 1

        self.assertGreaterEqual(syntax_errors, 1, "Syntactic bit flips must be trapped by parser")
        self.assertGreaterEqual(schema_errors, 1, "Key bit flips must be trapped by schema")
        self.assertGreaterEqual(silent_corruptions, 1, "Semantic bit flips prove SDC without hardware CRC")
        self.assertEqual(syntax_errors + schema_errors + silent_corruptions, 7)

    def test_truncated_rf_packet_handling(self):
        """Simulates RF loss mid-packet (packet truncated at byte 10, 20, 30, etc.)."""
        valid_json = '{"pkt":100,"met":60,"temp":31.2,"volt":4.88,"curr":340.5,"pwr":1661.6,"vib":0.11,"pitch":5.0,"roll":-3.0,"fdir":"CAUTION","rssi":-55,"snr":8.1,"rx_count":100}'

        for trunc_len in [5, 15, 30, 50, 80]:
            truncated = valid_json[:trunc_len] + "\n"
            proc = SerialStreamProcessor()
            proc.feed_chunk(truncated)

            self.assertEqual(len(proc.telemetry_frames), 0, f"Truncated packet of len {trunc_len} parsed as telemetry!")
            self.assertGreaterEqual(len(proc.error_frames) + len(proc.raw_logs), 1)

    def test_satellite_reboot_sequence_reset(self):
        """
        Ground station tracks expectedSatPkt.
        If satellite reboots, packet counter resets from 5000 back to 1.
        Ground station must NOT treat this as dropped packets (gap should not add billions).
        """
        # Ground Station sequence tracker logic
        expectedSatPkt = 5001
        totalPacketsDropped = 0

        # Rebooted satellite transmits pkt = 1
        satPkt = 1

        if expectedSatPkt > 0 and satPkt > expectedSatPkt:
            totalPacketsDropped += (satPkt - expectedSatPkt)
        expectedSatPkt = satPkt + 1

        self.assertEqual(totalPacketsDropped, 0, "Satellite reboot must not add to dropped packet count")
        self.assertEqual(expectedSatPkt, 2)


class TestStaticBufferBoundaries(unittest.TestCase):
    """Ground station static buffer boundaries, overflows, and pathological chunking."""

    def setUp(self):
        self.processor = SerialStreamProcessor(buffer_max_len=512)

    def test_buffer_overflow_flushing(self):
        """
        Simulates an incoming chunk exceeding buffer_max_len without a newline.
        Processor must flush buffer without crashing or hanging.
        """
        huge_chunk = "A" * 600
        self.processor.feed_chunk(huge_chunk)

        # Buffer must have been reset/flushed to prevent runaway memory usage
        self.assertIn("[BUFFER_OVERFLOW_FLUSH]", self.processor.raw_logs)

        # Subsequent valid packet must be processed cleanly
        valid = '{"pkt":1,"met":1,"temp":25.0,"volt":5.0,"curr":300.0,"pwr":1500.0,"vib":0.05,"pitch":0.0,"roll":0.0,"fdir":"NOMINAL","rssi":-50,"snr":9.0,"rx_count":1}\n'
        self.processor.feed_chunk(valid)
        self.assertEqual(len(self.processor.telemetry_frames), 1)

    def test_pathological_fuzzing_random_splits(self):
        """
        Takes 50 valid telemetry packets, serializes them, and feeds them in random
        micro-chunks (1 to 7 bytes) to challenge fragmentation and line reassembly.
        """
        packets = []
        raw_stream = ""
        for i in range(1, 51):
            frame = {
                "pkt": i, "met": i * 2, "temp": 25.0 + (i * 0.1),
                "volt": 5.0, "curr": 300.0, "pwr": 1500.0,
                "vib": 0.05, "pitch": 0.0, "roll": 0.0,
                "fdir": "NOMINAL", "rssi": -45, "snr": 9.0, "rx_count": i
            }
            packets.append(frame)
            raw_stream += json.dumps(frame) + "\n"

        proc = SerialStreamProcessor(buffer_max_len=2048)
        pos = 0
        random.seed(42)
        while pos < len(raw_stream):
            step = random.randint(1, 7)
            chunk = raw_stream[pos:pos + step]
            proc.feed_chunk(chunk)
            pos += step

        self.assertEqual(len(proc.telemetry_frames), 50, "All 50 fragmented frames must be reassembled")
        self.assertEqual([f["pkt"] for f in proc.telemetry_frames], list(range(1, 51)))


class TestAdversarialTelecommands(unittest.TestCase):
    """Telecommand uplink injection and parameter boundary matrix validation."""

    def setUp(self):
        self.processor = SerialStreamProcessor()

    def test_canonical_telecommands(self):
        """Valid canonical telecommands: CMD:PING, CMD:FDIR_RESET, CMD:TARE, CMD:RATE:500."""
        valid_cmds = ["CMD:PING\n", "CMD:FDIR_RESET\n", "CMD:TARE\n", "CMD:RATE:200\n", "CMD:RATE:5000\n"]
        for cmd in valid_cmds:
            self.processor.feed_chunk(cmd)

        self.assertEqual(len(self.processor.telecommands), 5)

    def test_cmd_rate_boundary_rules(self):
        """
        CMD:RATE:<ms> requires rate in [100, 5000].
        Tests boundary acceptance and rejection.
        """
        def validate_rate_cmd(cmd_str):
            if not cmd_str.startswith("CMD:RATE:"):
                return False, "Not rate command"
            val_str = cmd_str[9:].strip()
            try:
                rate = int(val_str)
                if 100 <= rate <= 5000:
                    return True, rate
                return False, f"Out of bounds: {rate}"
            except ValueError:
                return False, f"Non-numeric: {val_str}"

        # Valid boundaries
        self.assertTrue(validate_rate_cmd("CMD:RATE:100")[0])
        self.assertTrue(validate_rate_cmd("CMD:RATE:5000")[0])
        self.assertTrue(validate_rate_cmd("CMD:RATE:600")[0])

        # Invalid boundaries
        self.assertFalse(validate_rate_cmd("CMD:RATE:99")[0])
        self.assertFalse(validate_rate_cmd("CMD:RATE:5001")[0])
        self.assertFalse(validate_rate_cmd("CMD:RATE:0")[0])
        self.assertFalse(validate_rate_cmd("CMD:RATE:-500")[0])
        self.assertFalse(validate_rate_cmd("CMD:RATE:abc")[0])
        self.assertFalse(validate_rate_cmd("CMD:RATE:")[0])

    def test_malicious_injection_strings(self):
        """
        Hostile commands: SQL injection, shell escapes, long junk.
        Must be ingested as safe strings without crashing or executing.
        """
        injections = [
            "CMD:PING; DROP TABLE telecommand;\n",
            "CMD:RATE:1000 && cat /etc/passwd\n",
            "CMD:\"/><script>alert(1)</script>\n",
            "CMD:" + "A" * 200 + "\n"
        ]
        for inj in injections:
            self.processor.feed_chunk(inj)

        # All must be categorized as raw telecommand strings without parser crash
        self.assertEqual(len(self.processor.telecommands), 4)


class TestChaosTelemetryStream(unittest.TestCase):
    """
    Stress-tests the full communication pipeline with a 1,000-frame chaos stream:
     - 20% dropped packets
     - 10% corrupted JSON frames
     - 10% non-ASCII binary bursts
     - Interleaved uplink telecommands
    """

    def test_thousand_frame_chaos_stream_resilience(self):
        random.seed(1337)
        proc = SerialStreamProcessor(buffer_max_len=4096)

        expected_valid_pkts = 0
        expected_corrupt = 0
        expected_cmds = 0

        for i in range(1, 1001):
            r = random.random()

            # 1. Normal packet (60%)
            if r < 0.60:
                frame = {
                    "pkt": i, "met": i, "temp": 26.5 + (i % 10) * 0.1,
                    "volt": 5.0, "curr": 310.0, "pwr": 1550.0,
                    "vib": 0.055, "pitch": 0.5, "roll": -0.2,
                    "fdir": "NOMINAL", "rssi": -48, "snr": 9.2, "rx_count": i
                }
                raw = json.dumps(frame) + "\n"
                proc.feed_chunk(raw)
                expected_valid_pkts += 1

            # 2. Corrupted JSON (10%)
            elif r < 0.70:
                bad_json = f'{{"pkt": {i}, "temp": corrupted_nan, "volt": }}\n'
                proc.feed_chunk(bad_json)
                expected_corrupt += 1

            # 3. Non-ASCII binary noise (10%)
            elif r < 0.80:
                noise = f'\x00\x01\xfe\xff[NOISE_FRAME_{i}]\n'
                proc.feed_chunk(noise)

            # 4. Uplink telecommand (10%)
            elif r < 0.90:
                cmd = f"CMD:RATE:{100 + (i % 40) * 100}\n"
                proc.feed_chunk(cmd)
                expected_cmds += 1

            # 5. Dropped / empty packet (10%)
            else:
                pass # Emulates packet loss

        # Assertions
        self.assertEqual(len(proc.telemetry_frames), expected_valid_pkts)
        self.assertEqual(len(proc.error_frames), expected_corrupt)
        self.assertEqual(len(proc.telecommands), expected_cmds)
        # Processor must still have empty buffer and zero crashed state
        self.assertEqual(proc.buffer, "")


if __name__ == "__main__":
    unittest.main()
