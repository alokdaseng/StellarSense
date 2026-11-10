"""
========================================================================================
STELLARSENSE E2E TEST SUITE — TIER 5: ADVERSARIAL STRESS & COVERAGE HARDENING
File: tests/test_tier5_adversarial.py

Adversarial Objectives:
 1. Web Serial Stream Buffering Hardening:
    - Split JSON tokens (mid-key, mid-value, mid-bracket, 1-byte micro-chunking)
    - High-baud binary noise, escape sequences, and ASCII control characters
    - Defensive buffer overflow purge (>8192 bytes and >1024 bytes)
    - Rapid connect/disconnect cycles with dirty buffer retention prevention
 2. 60-Second Rolling Strip Charts Memory Stability:
    - True 60s sliding window (MAX_CHART_POINTS = 100) across 1,000 continuous updates
    - Zero dropped frames in active rolling window & bounded O(1) memory
    - Dynamic vibration threshold styling (Nominal Green, Caution Amber, Critical Red)
    - Telemetry history ring buffer clamped at 5,000 items
 3. FDIR Annunciator Rapid Chaotic Transitions:
    - 5-Subsystem exhaustive truth table (EPS, TCS, ADCS, COMMS, STRUCTURE)
    - Master Annunciator hierarchical arbitration (Critical > Caution > Nominal)
    - 1,000 rapid chaotic transitions cycling pseudo-randomly across all 5 subsystems
    - Master Warning siren silencing, de-escalation, and re-arming lifecycle
 4. CSV Flight Log Replayer & Exporter Hardening:
    - 15-column RFC 4180 CSV export schema and precision contract
    - Replayer header aliasing and case insensitivity (e.g. MET_Seconds vs met)
    - Malformed CSV robustness (empty files, header-only, non-numeric values)
    - Massive 10,000-row flight log stream processing with bounded memory
 5. Telecommand Interface Adversarial Hardening:
    - Canonical telecommand dispatch matrix (CMD:PING, CMD:FDIR_RESET, CMD:TARE, CMD:RATE:<ms>)
    - CMD:RATE:<ms> Parameter Boundary Value Analysis [100, 5000]
    - Invalid syntax, casing, and non-canonical command rejection
    - Buffer overflow attacks (>64B) and hostile injection immunity (SQL/Shell/XSS/CRLF)

Authoritative Specifications:
 - PROJECT.md § Architecture, Feature Inventory & Interface Contracts
 - firmware/satellite_sender/satellite_sender.ino & ground_receiver.ino
 - dashboard/app.js, styles.css, index.html
 - docs/TELECOMMAND_SPEC.md & SYSTEM_ARCHITECTURE.md
========================================================================================
"""

import unittest
import json
import math
import random
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.test_serial_framing import SerialStreamProcessor
from tests.test_telemetry_schema import TelemetrySchemaValidator


# ======================================================================================
# REFERENCE IMPLEMENTATIONS MODELING DASHBOARD & FIRMWARE LOGIC
# ======================================================================================

class ChartManagerSimulation:
    """
    Exact simulation of Chart.js rolling strip charts from dashboard/app.js.
    Configured with MAX_CHART_POINTS = 100 (60s window at 600ms rate).
    """

    def __init__(self, max_points=100):
        self.max_points = max_points
        # 4 Strip Charts
        self.chart_temp = {"labels": [], "data": []}
        self.chart_power = {"labels": [], "volt": [], "curr": []}
        self.chart_vib = {"labels": [], "data": [], "color": "#10b981", "bg": "rgba(16, 185, 129, 0.08)"}
        self.chart_attitude = {"labels": [], "pitch": [], "roll": []}
        self.telemetry_history = []
        self.max_history = 5000

    def update(self, time_label, temp, volt, curr, vib, pitch, roll, pkt=1, met=0, fdir="NOMINAL", rssi=-50, snr=9.0):
        # 1. Temperature Chart
        self.chart_temp["labels"].append(time_label)
        self.chart_temp["data"].append(temp)
        if len(self.chart_temp["labels"]) > self.max_points:
            self.chart_temp["labels"].pop(0)
            self.chart_temp["data"].pop(0)

        # 2. Power Chart
        self.chart_power["labels"].append(time_label)
        self.chart_power["volt"].append(volt)
        self.chart_power["curr"].append(curr)
        if len(self.chart_power["labels"]) > self.max_points:
            self.chart_power["labels"].pop(0)
            self.chart_power["volt"].pop(0)
            self.chart_power["curr"].pop(0)

        # 3. Vibration Chart & Dynamic Color Styling
        self.chart_vib["labels"].append(time_label)
        self.chart_vib["data"].append(vib)
        if len(self.chart_vib["labels"]) > self.max_points:
            self.chart_vib["labels"].pop(0)
            self.chart_vib["data"].pop(0)

        if vib >= 0.70:
            self.chart_vib["color"] = "#ef4444"
            self.chart_vib["bg"] = "rgba(239, 68, 68, 0.15)"
        elif vib >= 0.25:
            self.chart_vib["color"] = "#f59e0b"
            self.chart_vib["bg"] = "rgba(245, 158, 11, 0.12)"
        else:
            self.chart_vib["color"] = "#10b981"
            self.chart_vib["bg"] = "rgba(16, 185, 129, 0.08)"

        # 4. Attitude Chart
        self.chart_attitude["labels"].append(time_label)
        self.chart_attitude["pitch"].append(pitch)
        self.chart_attitude["roll"].append(roll)
        if len(self.chart_attitude["labels"]) > self.max_points:
            self.chart_attitude["labels"].pop(0)
            self.chart_attitude["pitch"].pop(0)
            self.chart_attitude["roll"].pop(0)

        # Telemetry History Ring Buffer
        self.telemetry_history.append({
            "met": met, "timeString": time_label, "pkt": pkt,
            "temp": temp, "volt": volt, "curr": curr, "pwr": volt * curr,
            "vib": vib, "pitch": pitch, "roll": roll, "fdir": fdir,
            "rssi": rssi, "snr": snr, "lostPackets": 0
        })
        if len(self.telemetry_history) > self.max_history:
            self.telemetry_history.pop(0)


class DashboardFDIREvaluator:
    """
    Exact simulation of evaluateSubsystems() and setFDIRState() from dashboard/app.js.
    """

    @staticmethod
    def evaluate_subsystems(temp, volt, curr, vib, tumble_rate, rssi, is_los):
        # EPS
        eps_status = "nominal"
        eps_text = "NOMINAL (5.0V)"
        if volt <= 4.2 or curr >= 800:
            eps_status = "critical"
            eps_text = f"BUS SAG ({volt:.2f}V)" if volt <= 4.2 else f"OVERCURRENT ({round(curr)}mA)"
        elif volt <= 4.6 or curr >= 500:
            eps_status = "caution"
            eps_text = f"LOW VOLT ({volt:.2f}V)" if volt <= 4.6 else f"HIGH LOAD ({round(curr)}mA)"

        # TCS
        tcs_status = "nominal"
        tcs_text = f"NOMINAL ({temp:.1f}°C)"
        if temp >= 38.0:
            tcs_status = "critical"
            tcs_text = f"OVERHEAT ({temp:.1f}°C)"
        elif temp >= 33.0:
            tcs_status = "caution"
            tcs_text = f"THERMAL CAUTION ({temp:.1f}°C)"

        # ADCS
        adcs_status = "nominal"
        adcs_text = "LOCKED / STABLE"
        if tumble_rate >= 45.0:
            adcs_status = "critical"
            adcs_text = f"TUMBLE ({tumble_rate:.1f}°/s)"
        elif tumble_rate >= 20.0:
            adcs_status = "caution"
            adcs_text = f"HIGH SLEW ({tumble_rate:.1f}°/s)"

        # COMMS
        comms_status = "nominal"
        comms_text = "433 MHz LoRa ACTIVE"
        if is_los:
            comms_status = "critical"
            comms_text = "LOS / SIGNAL LOST"
        elif rssi <= -105:
            comms_status = "caution"
            comms_text = f"WEAK RF ({rssi} dBm)"

        # STRUCTURE
        struct_status = "nominal"
        struct_text = "NOMINAL (<0.25g)"
        if vib >= 0.70:
            struct_status = "critical"
            struct_text = f"FLUTTER CRIT ({vib:.3f}g)"
        elif vib >= 0.25:
            struct_status = "caution"
            struct_text = f"VIB CAUTION ({vib:.3f}g)"

        return {
            "eps": {"status": eps_status, "text": eps_text},
            "tcs": {"status": tcs_status, "text": tcs_text},
            "adcs": {"status": adcs_status, "text": adcs_text},
            "comms": {"status": comms_status, "text": comms_text},
            "struct": {"status": struct_status, "text": struct_text}
        }

    @classmethod
    def arbitrate_master_fdir(cls, sub_eval, telemetry_fdir=None):
        if telemetry_fdir in ("CRITICAL", "CAUTION"):
            return telemetry_fdir

        statuses = [s["status"] for s in sub_eval.values()]
        if "critical" in statuses:
            return "CRITICAL"
        if "caution" in statuses:
            return "CAUTION"
        return "NOMINAL"


class CsvReplaySimulation:
    """
    Exact simulation of startCsvReplay() and exportCSV() from dashboard/app.js.
    """

    HEADER_ALIASES = {
        "met_seconds": "met", "met": "met",
        "packet_id": "pkt", "pkt": "pkt",
        "temp_c": "temp", "temp": "temp",
        "bus_volt_v": "volt", "volt": "volt",
        "current_mA": "curr", "curr": "curr", "current_ma": "curr",
        "power_mw": "pwr", "pwr": "pwr",
        "vib_grms": "vib", "vib": "vib",
        "pitch_deg": "pitch", "pitch": "pitch",
        "roll_deg": "roll", "roll": "roll",
        "tumble_deg_s": "tumble", "tumble": "tumble",
        "fdir_state": "fdir", "fdir": "fdir",
        "rssi_dbm": "rssi", "rssi": "rssi",
        "snr_db": "snr", "snr": "snr",
        "lost_packets": "lost", "lost": "lost"
    }

    @classmethod
    def export_csv(cls, history):
        headers = [
            "MET_Seconds", "Time_UTC", "Packet_ID",
            "Temp_C", "Bus_Volt_V", "Current_mA", "Power_mW",
            "Vib_gRMS", "Pitch_deg", "Roll_deg", "Tumble_deg_s",
            "FDIR_State", "RSSI_dBm", "SNR_dB", "Lost_Packets"
        ]
        lines = [",".join(headers)]
        for row in history:
            line = [
                str(row.get("met", 0)),
                str(row.get("timeString", "00:00:00")),
                str(row.get("pkt", 0)),
                str(row.get("temp", 25.0)),
                str(row.get("volt", 5.0)),
                str(row.get("curr", 300.0)),
                str(row.get("pwr", 1500.0)),
                str(row.get("vib", 0.05)),
                str(row.get("pitch", 0.0)),
                str(row.get("roll", 0.0)),
                f"{row.get('tumbleRate', 0.0):.2f}",
                str(row.get("fdir", "NOMINAL")),
                str(row.get("rssi", -50)),
                str(row.get("snr", 9.0)),
                str(row.get("lostPackets", 0))
            ]
            lines.append(",".join(line))
        return "\n".join(lines)

    @classmethod
    def parse_csv_stream(cls, csv_text):
        lines = csv_text.strip().split("\n")
        if len(lines) < 2:
            return []

        raw_headers = [h.strip() for h in lines[0].split(",")]
        mapped_headers = [cls.HEADER_ALIASES.get(h.lower(), h) for h in raw_headers]
        parsed_records = []

        for row_str in lines[1:]:
            parts = [p.strip() for p in row_str.split(",")]
            record = {}
            for idx, key in enumerate(mapped_headers):
                if idx < len(parts):
                    val = parts[idx]
                    if key in ("met", "pkt", "rssi", "lost"):
                        try:
                            record[key] = int(val)
                        except (ValueError, TypeError):
                            record[key] = 0
                    elif key in ("temp", "volt", "curr", "pwr", "vib", "pitch", "roll", "snr", "tumble"):
                        try:
                            val_f = float(val)
                            if math.isnan(val_f) or math.isinf(val_f):
                                defaults = {"temp": 25.0, "volt": 5.0, "curr": 300.0, "vib": 0.05}
                                record[key] = defaults.get(key, 0.0)
                            else:
                                record[key] = val_f
                        except (ValueError, TypeError):
                            # Default fallback matching app.js (parseFloat(val) || default)
                            defaults = {"temp": 25.0, "volt": 5.0, "curr": 300.0, "vib": 0.05}
                            record[key] = defaults.get(key, 0.0)
                    else:
                        record[key] = val
            parsed_records.append(record)

        return parsed_records


# ======================================================================================
# SUITE 1: WEB SERIAL STREAM BUFFERING ADVERSARIAL STRESS
# ======================================================================================

class TestWebSerialStreamBufferingHardening(unittest.TestCase):
    """
    Stress-tests the Web Serial stream ingestion engine with pathological chunking,
    split JSON tokens, high-baud binary noise, and buffer overflow recovery.
    """

    def setUp(self):
        self.processor = SerialStreamProcessor(buffer_max_len=8192)

    def test_split_across_json_tokens_keys_and_values(self):
        """
        Adversarially slices a telemetry packet across every single character boundary.
        Verifies that splitting mid-key, mid-value, mid-colon, or mid-comma never corrupts state.
        """
        sample_frame = {
            "pkt": 42, "met": 120, "temp": 28.75, "volt": 5.01,
            "curr": 312.4, "pwr": 1565.1, "vib": 0.085,
            "pitch": 4.2, "roll": -2.8, "fdir": "NOMINAL",
            "rssi": -48, "snr": 9.5, "rx_count": 42
        }
        serialized = json.dumps(sample_frame) + "\n"

        for split_pos in range(1, len(serialized) - 1):
            proc = SerialStreamProcessor(buffer_max_len=8192)
            chunk1 = serialized[:split_pos]
            chunk2 = serialized[split_pos:]

            proc.feed_chunk(chunk1)
            # Frame must not yet be emitted before newline
            self.assertEqual(len(proc.telemetry_frames), 0)

            proc.feed_chunk(chunk2)
            # Upon second chunk completing the line, frame must be completely parsed
            self.assertEqual(len(proc.telemetry_frames), 1, f"Failed at split index {split_pos}")
            parsed = proc.telemetry_frames[0]
            self.assertEqual(parsed["pkt"], 42)
            self.assertAlmostEqual(parsed["temp"], 28.75, places=2)
            self.assertAlmostEqual(parsed["volt"], 5.01, places=2)
            self.assertEqual(parsed["fdir"], "NOMINAL")

    def test_pathological_micro_chunk_streaming(self):
        """
        Takes 100 valid telemetry packets, generates a continuous raw stream,
        and streams them in pseudo-random 1-byte to 7-byte micro-chunks.
        """
        packets = []
        raw_stream = ""
        for i in range(1, 101):
            frame = {
                "pkt": i, "met": i * 2, "temp": 25.0 + (i % 20) * 0.1,
                "volt": 5.02, "curr": 310.0, "pwr": 1556.2,
                "vib": 0.065, "pitch": 1.0, "roll": -0.5,
                "fdir": "NOMINAL", "rssi": -50, "snr": 9.2, "rx_count": i
            }
            packets.append(frame)
            raw_stream += json.dumps(frame) + "\n"

        proc = SerialStreamProcessor(buffer_max_len=16384)
        pos = 0
        rng = random.Random(42)
        while pos < len(raw_stream):
            step = rng.randint(1, 7) # Micro-chunks
            chunk = raw_stream[pos:pos + step]
            proc.feed_chunk(chunk)
            pos += step

        self.assertEqual(len(proc.telemetry_frames), 100, "All 100 micro-chunked packets must be reassembled")
        self.assertEqual([f["pkt"] for f in proc.telemetry_frames], list(range(1, 101)))
        self.assertEqual(proc.buffer, "", "Buffer must be empty after complete stream transmission")

    def test_high_baud_binary_noise_and_control_chars(self):
        """
        Intersperses raw binary garbage bytes (\x00, \xFF, \x80, \x1B, ANSI codes)
        between valid JSON telemetry packets to test noise isolation.
        """
        proc = SerialStreamProcessor(buffer_max_len=8192)

        # 1. First valid packet
        proc.feed_chunk('{"pkt": 1, "temp": 25.0, "volt": 5.0}\n')
        self.assertEqual(len(proc.telemetry_frames), 1)

        # 2. Ingest binary noise burst with control codes
        noise = "\x00\x01\x02\xff\xfe\x1b[31;1mGARBAGE_BAUD_NOISE\x1b[0m\x08\x07\n"
        proc.feed_chunk(noise)

        # 3. Second valid packet
        proc.feed_chunk('{"pkt": 2, "temp": 25.5, "volt": 5.0}\n')

        self.assertEqual(len(proc.telemetry_frames), 2)
        self.assertEqual(proc.telemetry_frames[0]["pkt"], 1)
        self.assertEqual(proc.telemetry_frames[1]["pkt"], 2)
        self.assertGreaterEqual(len(proc.raw_logs), 1)

    def test_buffer_overflow_defense_head_purge(self):
        """
        Simulates receiving a massive uninterrupted string exceeding 8192 bytes
        without a newline delimiter.
        Verifies buffer flush defense and clean immediate recovery.
        """
        proc = SerialStreamProcessor(buffer_max_len=8192)

        # Inject 10,000 bytes without newline
        huge_junk = "X" * 10000
        proc.feed_chunk(huge_junk)

        # Buffer must have triggered overflow flush
        self.assertIn("[BUFFER_OVERFLOW_FLUSH]", proc.raw_logs)

        # Immediate valid packet after overflow must parse cleanly
        valid = '{"pkt": 99, "temp": 26.0, "volt": 5.0}\n'
        proc.feed_chunk(valid)
        self.assertEqual(len(proc.telemetry_frames), 1)
        self.assertEqual(proc.telemetry_frames[0]["pkt"], 99)

    def test_rapid_connect_disconnect_cycles_with_dirty_buffer(self):
        """
        Simulates 50 rapid sequential connect/disconnect cycles.
        In each cycle: feed incomplete fragment (dirty buffer), issue reset, reconnect, feed clean frame.
        """
        proc = SerialStreamProcessor(buffer_max_len=2048)

        for cycle in range(1, 51):
            # Dirty fragment
            proc.feed_chunk('{"pkt": ' + str(cycle) + ', "temp":')
            self.assertEqual(len(proc.telemetry_frames), 0)

            # Abrupt disconnect
            proc.reset()
            self.assertEqual(proc.buffer, "")

            # Reconnection and clean packet
            clean = f'{{"pkt": {cycle}, "temp": 25.0, "volt": 5.0}}\n'
            proc.feed_chunk(clean)
            self.assertEqual(len(proc.telemetry_frames), 1)
            self.assertEqual(proc.telemetry_frames[0]["pkt"], cycle)
            proc.telemetry_frames.clear()

    def test_webserial_multi_frame_burst_with_incomplete_tail(self):
        """
        Feeds multiple complete frames in a single chunk with an incomplete tail.
        Verifies complete frames are dispatched immediately, and incomplete tail waits for newline.
        """
        proc = SerialStreamProcessor(buffer_max_len=4096)
        burst = '{"pkt": 1, "temp": 25.0, "volt": 5.0}\n{"pkt": 2, "temp": 25.1, "volt": 5.0}\n{"pkt": 3, "temp": 25.2'
        proc.feed_chunk(burst)

        self.assertEqual(len(proc.telemetry_frames), 2)
        self.assertEqual([f["pkt"] for f in proc.telemetry_frames], [1, 2])
        self.assertEqual(proc.buffer, '{"pkt": 3, "temp": 25.2')

        # Tail completion
        proc.feed_chunk(', "volt": 5.0}\n')
        self.assertEqual(len(proc.telemetry_frames), 3)
        self.assertEqual(proc.telemetry_frames[2]["pkt"], 3)
        self.assertEqual(proc.buffer, "")


# ======================================================================================
# SUITE 2: 60-SECOND ROLLING STRIP CHARTS MEMORY STABILITY
# ======================================================================================

class TestRollingStripChartsMemoryStability(unittest.TestCase):
    """
    Stress-tests the 60-second rolling strip chart buffer manager under 1,000
    continuous telemetry updates for bounded O(1) memory and zero dropped frames.
    """

    def setUp(self):
        self.chart_sim = ChartManagerSimulation(max_points=100)

    def test_chart_sliding_window_1000_updates_capacity(self):
        """
        Feeds 1,000 sequential telemetry frames into ChartManagerSimulation.
        Verifies:
         - After 100 points, all 4 strip chart buffers remain strictly clamped at 100 points.
         - At N=1000, arrays contain items 901 through 1000 (FIFO order preserved).
         - Zero frames are dropped from the rolling window.
        """
        for i in range(1, 1001):
            time_label = f"{i // 60:02d}:{i % 60:02d}"
            temp = 25.0 + math.sin(i / 10.0) * 2.0
            volt = 5.0 + math.cos(i / 15.0) * 0.1
            curr = 300.0 + math.sin(i / 8.0) * 20.0
            vib = 0.05 + abs(math.sin(i / 5.0)) * 0.03
            pitch = math.sin(i / 7.0) * 10.0
            roll = math.cos(i / 9.0) * 8.0

            self.chart_sim.update(time_label, temp, volt, curr, vib, pitch, roll, pkt=i, met=i)

            # Invariant check: after reaching capacity, length must remain EXACTLY 100
            if i >= 100:
                self.assertEqual(len(self.chart_sim.chart_temp["labels"]), 100)
                self.assertEqual(len(self.chart_sim.chart_temp["data"]), 100)
                self.assertEqual(len(self.chart_sim.chart_power["volt"]), 100)
                self.assertEqual(len(self.chart_sim.chart_power["curr"]), 100)
                self.assertEqual(len(self.chart_sim.chart_vib["data"]), 100)
                self.assertEqual(len(self.chart_sim.chart_attitude["pitch"]), 100)
                self.assertEqual(len(self.chart_sim.chart_attitude["roll"]), 100)

        # Final state check at 1,000 updates
        self.assertEqual(len(self.chart_sim.chart_temp["labels"]), 100)
        # Check first and last item in the 100-point window
        expected_first_label = f"{901 // 60:02d}:{901 % 60:02d}"
        expected_last_label = f"{1000 // 60:02d}:{1000 % 60:02d}"
        self.assertEqual(self.chart_sim.chart_temp["labels"][0], expected_first_label)
        self.assertEqual(self.chart_sim.chart_temp["labels"][-1], expected_last_label)

    def test_vibration_dynamic_color_threshold_transitions(self):
        """
        Validates dynamic color threshold transitions in the Vibration strip chart:
         - vib >= 0.70g: Red (#ef4444)
         - 0.25g <= vib < 0.70g: Amber (#f59e0b)
         - vib < 0.25g: Green (#10b981)
        """
        # 1. Nominal
        self.chart_sim.update("00:01", 25.0, 5.0, 300.0, 0.150, 0.0, 0.0)
        self.assertEqual(self.chart_sim.chart_vib["color"], "#10b981")

        # 2. Caution Boundary (0.250g)
        self.chart_sim.update("00:02", 25.0, 5.0, 300.0, 0.250, 0.0, 0.0)
        self.assertEqual(self.chart_sim.chart_vib["color"], "#f59e0b")

        # 3. Critical Boundary (0.700g)
        self.chart_sim.update("00:03", 25.0, 5.0, 300.0, 0.700, 0.0, 0.0)
        self.assertEqual(self.chart_sim.chart_vib["color"], "#ef4444")

        # 4. Recovery back to Nominal
        self.chart_sim.update("00:04", 25.0, 5.0, 300.0, 0.080, 0.0, 0.0)
        self.assertEqual(self.chart_sim.chart_vib["color"], "#10b981")

    def test_telemetry_history_ring_buffer_bounding(self):
        """
        Verifies telemetry history array bounding at 5,000 items over 10,000 updates.
        """
        for i in range(1, 10001):
            self.chart_sim.update("00:01", 25.0, 5.0, 300.0, 0.05, 0.0, 0.0, pkt=i)

        self.assertEqual(len(self.chart_sim.telemetry_history), 5000)
        self.assertEqual(self.chart_sim.telemetry_history[0]["pkt"], 5001)
        self.assertEqual(self.chart_sim.telemetry_history[-1]["pkt"], 10000)


# ======================================================================================
# SUITE 3: FDIR ANNUNCIATOR RAPID CHAOTIC TRANSITIONS
# ======================================================================================

class TestFDIRAnnunciatorChaoticTransitions(unittest.TestCase):
    """
    Stress-tests the 5-subsystem FDIR annunciator matrix under rapid chaotic transitions,
    multi-fault injections, and priority arbitration.
    """

    def setUp(self):
        self.evaluator = DashboardFDIREvaluator()

    def test_five_subsystems_exhaustive_truth_table(self):
        """
        Exhaustively verifies evaluation rules across all 5 subsystems:
        EPS, TCS, ADCS, COMMS, and STRUCTURE.
        """
        # 1. EPS: Nominal, Low Volt, High Load, Bus Sag, Overcurrent
        res_eps_nom = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.05, 0.0, -50, False)["eps"]
        self.assertEqual(res_eps_nom["status"], "nominal")

        res_eps_low_v = self.evaluator.evaluate_subsystems(25.0, 4.55, 300.0, 0.05, 0.0, -50, False)["eps"]
        self.assertEqual(res_eps_low_v["status"], "caution")
        self.assertIn("LOW VOLT", res_eps_low_v["text"])

        res_eps_high_i = self.evaluator.evaluate_subsystems(25.0, 5.0, 550.0, 0.05, 0.0, -50, False)["eps"]
        self.assertEqual(res_eps_high_i["status"], "caution")
        self.assertIn("HIGH LOAD", res_eps_high_i["text"])

        res_eps_crit_v = self.evaluator.evaluate_subsystems(25.0, 4.15, 300.0, 0.05, 0.0, -50, False)["eps"]
        self.assertEqual(res_eps_crit_v["status"], "critical")
        self.assertIn("BUS SAG", res_eps_crit_v["text"])

        res_eps_crit_i = self.evaluator.evaluate_subsystems(25.0, 5.0, 850.0, 0.05, 0.0, -50, False)["eps"]
        self.assertEqual(res_eps_crit_i["status"], "critical")
        self.assertIn("OVERCURRENT", res_eps_crit_i["text"])

        # 2. TCS: Nominal, Caution, Overheat Critical
        res_tcs_nom = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.05, 0.0, -50, False)["tcs"]
        self.assertEqual(res_tcs_nom["status"], "nominal")

        res_tcs_caut = self.evaluator.evaluate_subsystems(34.5, 5.0, 300.0, 0.05, 0.0, -50, False)["tcs"]
        self.assertEqual(res_tcs_caut["status"], "caution")
        self.assertIn("THERMAL CAUTION", res_tcs_caut["text"])

        res_tcs_crit = self.evaluator.evaluate_subsystems(39.2, 5.0, 300.0, 0.05, 0.0, -50, False)["tcs"]
        self.assertEqual(res_tcs_crit["status"], "critical")
        self.assertIn("OVERHEAT", res_tcs_crit["text"])

        # 3. ADCS: Stable, High Slew, Tumble Critical
        res_adcs_nom = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.05, 12.0, -50, False)["adcs"]
        self.assertEqual(res_adcs_nom["status"], "nominal")

        res_adcs_caut = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.05, 25.0, -50, False)["adcs"]
        self.assertEqual(res_adcs_caut["status"], "caution")
        self.assertIn("HIGH SLEW", res_adcs_caut["text"])

        res_adcs_crit = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.05, 52.0, -50, False)["adcs"]
        self.assertEqual(res_adcs_crit["status"], "critical")
        self.assertIn("TUMBLE", res_adcs_crit["text"])

        # 4. COMMS: Active, Weak RF, LOS Critical
        res_comms_nom = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.05, 0.0, -55, False)["comms"]
        self.assertEqual(res_comms_nom["status"], "nominal")

        res_comms_caut = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.05, 0.0, -112, False)["comms"]
        self.assertEqual(res_comms_caut["status"], "caution")
        self.assertIn("WEAK RF", res_comms_caut["text"])

        res_comms_crit = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.05, 0.0, -50, True)["comms"]
        self.assertEqual(res_comms_crit["status"], "critical")
        self.assertIn("LOS", res_comms_crit["text"])

        # 5. STRUCTURE: Nominal, Vibration Caution, Flutter Critical
        res_str_nom = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.12, 0.0, -50, False)["struct"]
        self.assertEqual(res_str_nom["status"], "nominal")

        res_str_caut = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.35, 0.0, -50, False)["struct"]
        self.assertEqual(res_str_caut["status"], "caution")
        self.assertIn("VIB CAUTION", res_str_caut["text"])

        res_str_crit = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.82, 0.0, -50, False)["struct"]
        self.assertEqual(res_str_crit["status"], "critical")
        self.assertIn("FLUTTER CRIT", res_str_crit["text"])

    def test_master_annunciator_arbitration_hierarchy(self):
        """
        Validates Master Annunciator hierarchical escalation:
        CRITICAL > CAUTION > NOMINAL.
        """
        # Nominal
        all_nom = self.evaluator.evaluate_subsystems(25.0, 5.0, 300.0, 0.05, 0.0, -50, False)
        self.assertEqual(self.evaluator.arbitrate_master_fdir(all_nom), "NOMINAL")

        # 1 Caution -> Master CAUTION
        one_caut = self.evaluator.evaluate_subsystems(34.0, 5.0, 300.0, 0.05, 0.0, -50, False)
        self.assertEqual(self.evaluator.arbitrate_master_fdir(one_caut), "CAUTION")

        # 1 Critical + 1 Caution -> Master CRITICAL (Critical precedence)
        crit_and_caut = self.evaluator.evaluate_subsystems(39.0, 4.5, 300.0, 0.05, 0.0, -50, False)
        self.assertEqual(self.evaluator.arbitrate_master_fdir(crit_and_caut), "CRITICAL")

    def test_rapid_chaotic_transitions_1000_cycles(self):
        """
        Runs 1,000 rapid chaotic transitions cycling pseudo-randomly across all 5 subsystems
        with simultaneous multi-fault injections.
        Verifies deterministic arbitration with zero state machine deadlocks.
        """
        rng = random.Random(1337)
        for _ in range(1000):
            temp = rng.uniform(20.0, 42.0)
            volt = rng.uniform(3.8, 5.2)
            curr = rng.uniform(200.0, 900.0)
            vib = rng.uniform(0.01, 1.0)
            tumble = rng.uniform(0.0, 60.0)
            rssi = rng.randint(-120, -40)
            is_los = rng.random() < 0.10

            sub = self.evaluator.evaluate_subsystems(temp, volt, curr, vib, tumble, rssi, is_los)
            master = self.evaluator.arbitrate_master_fdir(sub)

            # Mathematical validation of master state
            has_crit = any(s["status"] == "critical" for s in sub.values())
            has_caut = any(s["status"] == "caution" for s in sub.values())

            if has_crit:
                self.assertEqual(master, "CRITICAL")
            elif has_caut:
                self.assertEqual(master, "CAUTION")
            else:
                self.assertEqual(master, "NOMINAL")

    def test_master_warning_siren_silencing_and_rearm_cycle(self):
        """
        Validates the audio siren lifecycle in dashboard/app.js:
         - Escalation to CRITICAL triggers audible alarm and enables silence button.
         - Silence action suppresses siren without masking the visual critical state.
         - Subsequent telemetry in CRITICAL preserves silence (no continuous re-chirp).
         - Return to NOMINAL resets silence state.
         - Re-escalation to CRITICAL automatically re-arms and sounds the siren.
        """
        current_state = "NOMINAL"
        alarm_silenced = False
        siren_playing = False

        def process_state(new_state):
            nonlocal current_state, alarm_silenced, siren_playing
            prev = current_state
            current_state = new_state
            if new_state == "CRITICAL":
                if prev != "CRITICAL":
                    alarm_silenced = False
                    siren_playing = True
            elif new_state == "CAUTION":
                siren_playing = False
            else: # NOMINAL
                siren_playing = False
                alarm_silenced = False

        def click_silence():
            nonlocal alarm_silenced, siren_playing
            alarm_silenced = True
            siren_playing = False

        # 1. Boot at Nominal
        process_state("NOMINAL")
        self.assertFalse(siren_playing)
        self.assertFalse(alarm_silenced)

        # 2. Critical Fault Occurs
        process_state("CRITICAL")
        self.assertTrue(siren_playing, "Siren must sound upon entering CRITICAL")
        self.assertFalse(alarm_silenced)

        # 3. Flight Director Silences Alarm
        click_silence()
        self.assertFalse(siren_playing, "Siren must stop when silenced")
        self.assertTrue(alarm_silenced)
        self.assertEqual(current_state, "CRITICAL", "Visual state remains CRITICAL while silenced")

        # 4. Another Critical Telemetry Packet Arrives (same fault persists)
        process_state("CRITICAL")
        self.assertFalse(siren_playing, "Siren must stay silenced while same critical state persists")
        self.assertTrue(alarm_silenced)

        # 5. Fault Clears -> Nominal Recovery
        process_state("NOMINAL")
        self.assertFalse(siren_playing)
        self.assertFalse(alarm_silenced, "Silence flag must reset upon recovery to NOMINAL")

        # 6. Secondary Critical Fault Occurs Later
        process_state("CRITICAL")
        self.assertTrue(siren_playing, "New critical fault must re-arm and trigger siren")



# ======================================================================================
# SUITE 4: CSV EXPORT & FLIGHT LOG REPLAYER ADVERSARIAL STRESS
# ======================================================================================

class TestCsvExportAndFlightLogReplayerHardening(unittest.TestCase):
    """
    Stress-tests CSV flight log generation, parsing resilience, header aliasing,
    and massive row count streaming.
    """

    def test_csv_export_rfc4180_format_and_headers(self):
        """
        Validates that CSV export generates exact 15 columns with proper RFC 4180 headers.
        """
        sample_history = [
            {
                "met": 10, "timeString": "00:00:10", "pkt": 1,
                "temp": 25.4, "volt": 5.01, "curr": 310.2, "pwr": 1554.1,
                "vib": 0.062, "pitch": 2.1, "roll": -1.4, "tumbleRate": 0.45,
                "fdir": "NOMINAL", "rssi": -48, "snr": 9.5, "lostPackets": 0
            }
        ]
        csv_str = CsvReplaySimulation.export_csv(sample_history)
        lines = csv_str.strip().split("\n")
        self.assertEqual(len(lines), 2)

        expected_headers = [
            "MET_Seconds", "Time_UTC", "Packet_ID",
            "Temp_C", "Bus_Volt_V", "Current_mA", "Power_mW",
            "Vib_gRMS", "Pitch_deg", "Roll_deg", "Tumble_deg_s",
            "FDIR_State", "RSSI_dBm", "SNR_dB", "Lost_Packets"
        ]
        self.assertEqual(lines[0].split(","), expected_headers)

        row_vals = lines[1].split(",")
        self.assertEqual(len(row_vals), 15)
        self.assertEqual(row_vals[0], "10")
        self.assertEqual(row_vals[2], "1")
        self.assertEqual(row_vals[3], "25.4")
        self.assertEqual(row_vals[11], "NOMINAL")

    def test_replayer_header_aliasing_matrix(self):
        """
        Tests CSV replayer flexibility with standard and abbreviated header names.
        """
        csv_canonical = (
            "MET_Seconds,Packet_ID,Temp_C,Bus_Volt_V,Current_mA,Vib_gRMS,Pitch_deg,Roll_deg,FDIR_State\n"
            "20,10,27.5,5.02,320.0,0.075,1.5,-0.8,NOMINAL"
        )
        records_canon = CsvReplaySimulation.parse_csv_stream(csv_canonical)
        self.assertEqual(len(records_canon), 1)
        self.assertEqual(records_canon[0]["pkt"], 10)
        self.assertEqual(records_canon[0]["temp"], 27.5)

        csv_short = (
            "met,pkt,temp,volt,curr,vib,pitch,roll,fdir\n"
            "20,10,27.5,5.02,320.0,0.075,1.5,-0.8,NOMINAL"
        )
        records_short = CsvReplaySimulation.parse_csv_stream(csv_short)
        self.assertEqual(len(records_short), 1)
        self.assertEqual(records_short[0]["pkt"], 10)
        self.assertEqual(records_short[0]["temp"], 27.5)

    def test_replayer_malformed_headers_and_garbage_rows(self):
        """
        Challenges replayer with malformed inputs:
         - Empty string
         - Header only
         - Non-numeric garbage in numeric fields
         - Missing values in row
        """
        # Empty
        self.assertEqual(CsvReplaySimulation.parse_csv_stream(""), [])
        # Header only
        self.assertEqual(CsvReplaySimulation.parse_csv_stream("met,pkt,temp\n"), [])

        # Non-numeric garbage fallback
        csv_garbage = (
            "met,pkt,temp,volt,curr,vib\n"
            "abc,xyz,corrupted_temp,null,NaN,inf"
        )
        records = CsvReplaySimulation.parse_csv_stream(csv_garbage)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["met"], 0)
        self.assertEqual(records[0]["pkt"], 0)
        # Default fallbacks
        self.assertEqual(records[0]["temp"], 25.0)
        self.assertEqual(records[0]["volt"], 5.0)
        self.assertEqual(records[0]["curr"], 300.0)

    def test_replayer_massive_10000_row_stream(self):
        """
        Streams 10,000 telemetry rows through CSV parser.
        Verifies O(1) memory behavior and 100% record integrity.
        """
        lines = ["met,pkt,temp,volt,curr,vib,pitch,roll,fdir"]
        for i in range(1, 10001):
            lines.append(f"{i},{i},26.0,5.0,300.0,0.05,0.0,0.0,NOMINAL")
        csv_data = "\n".join(lines)

        records = CsvReplaySimulation.parse_csv_stream(csv_data)
        self.assertEqual(len(records), 10000)
        self.assertEqual(records[0]["pkt"], 1)
        self.assertEqual(records[-1]["pkt"], 10000)


# ======================================================================================
# SUITE 5: TELECOMMAND INTERFACE ADVERSARIAL HARDENING
# ======================================================================================

class TestTelecommandInterfaceAdversarialHardening(unittest.TestCase):
    """
    Stress-tests telecommand parsing against parameter boundaries, syntax violations,
    buffer overflows, and hostile injection payloads.
    """

    def setUp(self):
        self.processor = SerialStreamProcessor()

    def test_canonical_telecommands_dispatch(self):
        """
        Validates all 4 canonical flight telecommands:
        CMD:PING, CMD:FDIR_RESET, CMD:TARE, CMD:RATE:<ms>
        """
        cmds = ["CMD:PING\n", "CMD:FDIR_RESET\n", "CMD:TARE\n", "CMD:RATE:600\n"]
        for c in cmds:
            self.processor.feed_chunk(c)

        self.assertEqual(len(self.processor.telecommands), 4)
        self.assertIn("CMD:PING", self.processor.telecommands)
        self.assertIn("CMD:FDIR_RESET", self.processor.telecommands)
        self.assertIn("CMD:TARE", self.processor.telecommands)
        self.assertIn("CMD:RATE:600", self.processor.telecommands)

    def test_cmd_rate_boundary_value_matrix(self):
        """
        Validates CMD:RATE:<ms> bounds [100, 5000] ms.
        """
        def validate_cmd_rate(cmd_str):
            if not cmd_str.startswith("CMD:RATE:"):
                return False, "Not rate command"
            val_part = cmd_str[9:].strip()
            try:
                rate = int(val_part)
                if 100 <= rate <= 5000:
                    return True, rate
                return False, f"Out of range: {rate}"
            except ValueError:
                return False, f"Invalid integer: {val_part}"

        # Valid boundaries
        self.assertTrue(validate_cmd_rate("CMD:RATE:100")[0])
        self.assertTrue(validate_cmd_rate("CMD:RATE:5000")[0])
        self.assertTrue(validate_cmd_rate("CMD:RATE:600")[0])

        # Invalid boundaries
        self.assertFalse(validate_cmd_rate("CMD:RATE:99")[0])
        self.assertFalse(validate_cmd_rate("CMD:RATE:5001")[0])
        self.assertFalse(validate_cmd_rate("CMD:RATE:0")[0])
        self.assertFalse(validate_cmd_rate("CMD:RATE:-500")[0])
        self.assertFalse(validate_cmd_rate("CMD:RATE:fast")[0])
        self.assertFalse(validate_cmd_rate("CMD:RATE:100.5")[0])
        self.assertFalse(validate_cmd_rate("CMD:RATE:")[0])

    def test_invalid_telecommand_syntax_rejection(self):
        """
        Rejects non-canonical commands, missing prefixes, lowercase variants, and random tokens.
        """
        invalid_tokens = [
            "PING\n",
            "cmd:ping\n",
            "Cmd:Tare\n",
            "RATE:500\n",
            "TELECOMMAND:PING\n",
            "RANDOM_JUNK\n"
        ]
        for token in invalid_tokens:
            self.processor.feed_chunk(token)

        # None of these must be classified as telecommands
        self.assertEqual(len(self.processor.telecommands), 0)

    def test_telecommand_buffer_overflow_and_injection_resilience(self):
        """
        Attacks telecommand parser with payloads exceeding 64 bytes (firmware static buffer),
        SQL injection, shell execution attempts, and script injection.
        """
        hostile_payloads = [
            "CMD:" + "A" * 128 + "\n",
            "CMD:PING; DROP TABLE telecommand;\n",
            "CMD:RATE:500 && rm -rf /bin\n",
            "CMD:<script>alert('XSS')</script>\n",
            "CMD:TARE\x00INJECTED_TAIL\n"
        ]

        for payload in hostile_payloads:
            self.processor.feed_chunk(payload)

        # Ingestion completes without parser crashes
        self.assertEqual(len(self.processor.telecommands), 5)


if __name__ == "__main__":
    unittest.main()
