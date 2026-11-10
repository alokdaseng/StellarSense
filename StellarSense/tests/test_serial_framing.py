"""
========================================================================================
STELLARSENSE E2E TEST SUITE — TIER 3: SERIAL STREAM FRAMING & PROTOCOL ROBUSTNESS
File: tests/test_serial_framing.py

Methodologies:
 - Byte-Chunk Fragmentation Simulation (1-byte, arbitrary n-byte splits)
 - Incomplete Line Retention & Reassembly
 - Multi-Frame Bursts within a Single Chunk
 - Corrupted / Truncated JSON & Non-ASCII Binary Noise Rejection
 - Discriminator Isolation of Ground Station Boot / Error Frames
 - Uplink Telecommand Parsing & Validation

Authoritative Specifications:
 - PROJECT.md § Interface Contracts (Ground Station ↔ Mission Control Serial Contract)
 - explorer_dashboard_survey/handoff.md § 1.1, 1.2, 2.1, 2.2
 - spec_survey_report.md § 7 (Edge Cases 1 & 2)
========================================================================================
"""

import unittest
import json
import random


class SerialStreamProcessor:
    """
    Simulation of the Web Serial streaming buffer reader in `dashboard/app.js`
    and static buffer parser in `firmware/ground_receiver/ground_receiver.ino`.
    """

    def __init__(self, buffer_max_len=1024):
        self.buffer = ""
        self.buffer_max_len = buffer_max_len
        self.telemetry_frames = []
        self.system_events = []
        self.error_frames = []
        self.telecommands = []
        self.raw_logs = []

    def feed_chunk(self, chunk: str):
        """
        Simulates receiving a chunk from Web Serial `readable.getReader().read()`.
        Implements line-delimited splitting: lines = buffer.split('\\n'); buffer = lines.pop().
        """
        if len(self.buffer) + len(chunk) > self.buffer_max_len:
            # Defensive buffer overflow protection: flush corrupted head
            self.buffer = ""
            self.raw_logs.append("[BUFFER_OVERFLOW_FLUSH]")

        self.buffer += chunk
        lines = self.buffer.split("\n")
        self.buffer = lines.pop() # Incomplete tail stays in buffer

        for line in lines:
            clean = line.strip()
            if not clean:
                continue

            # Telecommand pattern
            if clean.startswith("CMD:"):
                self.telecommands.append(clean)
                continue

            # JSON Frame detection
            if clean.startswith("{") and clean.endswith("}"):
                try:
                    data = json.loads(clean)
                    self._dispatch_json_frame(data, clean)
                except json.JSONDecodeError:
                    self.error_frames.append({"type": "MALFORMED_JSON", "raw": clean})
            else:
                self.raw_logs.append(clean)

    def _dispatch_json_frame(self, data: dict, raw_line: str):
        """Dispatches JSON objects into telemetry vs system vs error frames."""
        if "system" in data and data.get("system") == "GROUND_STATION":
            self.system_events.append(data)
        elif "error" in data or "err" in data:
            self.error_frames.append(data)
        elif "pkt" in data and ("temp" in data or "volt" in data):
            self.telemetry_frames.append(data)
        else:
            self.raw_logs.append(f"[UNRECOGNIZED_JSON] {raw_line}")

    def reset(self):
        """Simulates disconnect/reconnect buffer reset."""
        self.buffer = ""
        self.telemetry_frames.clear()
        self.system_events.clear()
        self.error_frames.clear()
        self.telecommands.clear()
        self.raw_logs.clear()


class TestSerialFraming(unittest.TestCase):
    """
    Tier 3 Integration & Protocol Framing Tests.
    """

    def setUp(self):
        self.processor = SerialStreamProcessor()

    # -------------------------------------------------------------------------
    # 1. STREAM FRAGMENTATION & CHUNKING
    # -------------------------------------------------------------------------
    def test_single_byte_by_byte_stream_reassembly(self):
        """
        Feeds a valid JSON line 1 byte at a time.
        Verifies that buffer holds partial fragments and fires exactly upon '\\n'.
        """
        payload = '{"pkt":42,"met":25,"temp":26.5,"volt":5.02,"curr":305.1,"pwr":1531.6,"vib":0.052,"pitch":1.2,"roll":-0.8,"fdir":"NOMINAL","rssi":-46,"snr":9.2,"rx_count":42}\n'

        for i, byte_char in enumerate(payload):
            self.processor.feed_chunk(byte_char)
            if i < len(payload) - 1:
                # Before final newline, no frame should have been emitted
                self.assertEqual(len(self.processor.telemetry_frames), 0)

        # After final newline, exactly 1 frame is emitted
        self.assertEqual(len(self.processor.telemetry_frames), 1)
        self.assertEqual(self.processor.telemetry_frames[0]["pkt"], 42)
        self.assertEqual(self.processor.buffer, "")

    def test_split_across_json_key_boundaries(self):
        """
        Splits a single frame across arbitrary chunk boundaries right in the middle of keys/numbers.
        """
        chunks = [
            '{"pkt": 101, "met": ',
            '60, "temp": 29.',
            '4, "volt": 4.9',
            '5, "curr": 310.0, "pwr": 1534.5, "vib": 0.08, "pitch": 0.0, "roll": 0.0, ',
            '"fdir": "NOMINAL", "rssi": -52, "snr": 8.5, "rx_count": 101}\n'
        ]

        for chunk in chunks:
            self.processor.feed_chunk(chunk)

        self.assertEqual(len(self.processor.telemetry_frames), 1)
        frame = self.processor.telemetry_frames[0]
        self.assertEqual(frame["pkt"], 101)
        self.assertEqual(frame["temp"], 29.4)
        self.assertEqual(frame["volt"], 4.95)

    def test_multi_frame_burst_in_single_chunk(self):
        """
        Simulates 3 back-to-back packets arriving within a single large serial chunk.
        """
        p1 = '{"pkt":1,"met":1,"temp":25.0,"volt":5.0,"curr":300.0,"pwr":1500.0,"vib":0.05,"pitch":0.0,"roll":0.0,"fdir":"NOMINAL","rssi":-50,"snr":9.0,"rx_count":1}'
        p2 = '{"pkt":2,"met":2,"temp":25.1,"volt":5.0,"curr":301.0,"pwr":1505.0,"vib":0.06,"pitch":0.1,"roll":0.0,"fdir":"NOMINAL","rssi":-49,"snr":9.1,"rx_count":2}'
        p3 = '{"pkt":3,"met":3,"temp":25.2,"volt":5.0,"curr":302.0,"pwr":1510.0,"vib":0.05,"pitch":0.0,"roll":0.1,"fdir":"NOMINAL","rssi":-51,"snr":8.9,"rx_count":3}'

        big_chunk = f"{p1}\n{p2}\n{p3}\n"
        self.processor.feed_chunk(big_chunk)

        self.assertEqual(len(self.processor.telemetry_frames), 3)
        self.assertEqual([f["pkt"] for f in self.processor.telemetry_frames], [1, 2, 3])
        self.assertEqual(self.processor.buffer, "")

    def test_multi_frame_with_incomplete_tail(self):
        """
        A chunk with 1 complete packet followed by half of a second packet.
        """
        p1 = '{"pkt":10,"met":6,"temp":25.0,"volt":5.0,"curr":300.0,"pwr":1500.0,"vib":0.05,"pitch":0.0,"roll":0.0,"fdir":"NOMINAL","rssi":-50,"snr":9.0,"rx_count":10}\n'
        half_p2 = '{"pkt":11,"met":7,"temp":26.0,'

        self.processor.feed_chunk(p1 + half_p2)

        self.assertEqual(len(self.processor.telemetry_frames), 1)
        self.assertEqual(self.processor.telemetry_frames[0]["pkt"], 10)
        self.assertEqual(self.processor.buffer, half_p2)

        # Now feed remainder of p2
        tail_p2 = '"volt":5.0,"curr":300.0,"pwr":1500.0,"vib":0.05,"pitch":0.0,"roll":0.0,"fdir":"NOMINAL","rssi":-50,"snr":9.0,"rx_count":11}\n'
        self.processor.feed_chunk(tail_p2)

        self.assertEqual(len(self.processor.telemetry_frames), 2)
        self.assertEqual(self.processor.telemetry_frames[1]["pkt"], 11)
        self.assertEqual(self.processor.buffer, "")

    # -------------------------------------------------------------------------
    # 2. MALFORMED FRAMES & CORRUPTION RECOVERY
    # -------------------------------------------------------------------------
    def test_corrupted_json_syntax_handling(self):
        """
        Corrupted JSON (missing values, unquoted keys, trailing commas)
        must be trapped into error log without crashing processor.
        """
        bad_frames = [
            '{"pkt": 5, "temp": 28.5, "volt": }\n',
            '{pkt: 6, "temp": 28.5}\n',
            '{"pkt": 7, "temp": 28.5, "extra_comma": 1,}\n',
        ]

        for bad in bad_frames:
            self.processor.feed_chunk(bad)

        self.assertEqual(len(self.processor.telemetry_frames), 0)
        self.assertEqual(len(self.processor.error_frames), len(bad_frames))

        # A non-brace truncated line should be captured in raw_logs
        unclosed = '{"pkt": 8, "unclosed": "missing_brace\n'
        self.processor.feed_chunk(unclosed)
        self.assertIn('{"pkt": 8, "unclosed": "missing_brace', self.processor.raw_logs)

        # Subsequent valid packet must process cleanly
        valid = '{"pkt":9,"met":5,"temp":25.0,"volt":5.0,"curr":300.0,"pwr":1500.0,"vib":0.05,"pitch":0.0,"roll":0.0,"fdir":"NOMINAL","rssi":-50,"snr":9.0,"rx_count":9}\n'
        self.processor.feed_chunk(valid)
        self.assertEqual(len(self.processor.telemetry_frames), 1)
        self.assertEqual(self.processor.telemetry_frames[0]["pkt"], 9)

    def test_binary_garbage_and_ascii_control_characters(self):
        """
        Adversarial: Stream contains null bytes, escape characters, or binary noise.
        """
        garbage = '\x00\x01\x1b[31m[RAW_NOISE]\x00\xff\n'
        self.processor.feed_chunk(garbage)
        self.assertEqual(len(self.processor.telemetry_frames), 0)
        self.assertGreaterEqual(len(self.processor.raw_logs), 1)

    # -------------------------------------------------------------------------
    # 3. DISCRIMINATOR: SYSTEM EVENT & ERROR FRAMES
    # -------------------------------------------------------------------------
    def test_ground_station_boot_event_isolation(self):
        """
        Ground station boot event:
        {"system":"GROUND_STATION","status":"READY","freq":433.0}
        Must be routed to system_events, NOT telemetry_frames.
        """
        boot_msg = '{"system":"GROUND_STATION","status":"READY","freq":433.0}\n'
        self.processor.feed_chunk(boot_msg)

        self.assertEqual(len(self.processor.telemetry_frames), 0)
        self.assertEqual(len(self.processor.system_events), 1)
        self.assertEqual(self.processor.system_events[0]["status"], "READY")

    def test_ground_station_parse_fail_event_isolation(self):
        """
        Ground station error event on corrupted RF packet:
        {"raw":"bad_rf_bits","rssi":-98,"snr":-6.2,"err":"PARSE_FAIL"}
        Must be routed to error_frames, NOT telemetry_frames.
        """
        rf_err = '{"raw":"bad_rf_bits","rssi":-98,"snr":-6.2,"err":"PARSE_FAIL"}\n'
        self.processor.feed_chunk(rf_err)

        self.assertEqual(len(self.processor.telemetry_frames), 0)
        self.assertEqual(len(self.processor.error_frames), 1)
        self.assertEqual(self.processor.error_frames[0]["err"], "PARSE_FAIL")

    # -------------------------------------------------------------------------
    # 4. TELECOMMAND FRAMING
    # -------------------------------------------------------------------------
    def test_uplink_telecommand_framing(self):
        """
        Validates uplink telecommands: CMD:PING, CMD:FDIR_RESET, CMD:TARE, CMD:RATE:500.
        """
        commands = [
            "CMD:PING\n",
            "CMD:FDIR_RESET\n",
            "CMD:TARE\n",
            "CMD:RATE:500\n"
        ]
        for cmd in commands:
            self.processor.feed_chunk(cmd)

        self.assertEqual(len(self.processor.telecommands), 4)
        self.assertIn("CMD:PING", self.processor.telecommands)
        self.assertIn("CMD:RATE:500", self.processor.telecommands)

    # -------------------------------------------------------------------------
    # 5. RECONNECTION & BUFFER FLUSH
    # -------------------------------------------------------------------------
    def test_reconnection_buffer_flush(self):
        """
        Verifies that resetting or reconnecting cleans out incomplete fragments.
        """
        self.processor.feed_chunk('{"pkt": 99, "partial": true')
        self.assertNotEqual(self.processor.buffer, "")

        self.processor.reset()
        self.assertEqual(self.processor.buffer, "")
        self.assertEqual(len(self.processor.telemetry_frames), 0)


if __name__ == '__main__':
    unittest.main()
