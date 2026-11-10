"""
=====================================================================================
 STELLARSENSE / ORBITGUARD E2E TEST SUITE — TIER 6:
 GEMMA 4 MODEL HARNESS, AGENT SKILL & AUTONOMOUS FDIR VERIFICATION
=====================================================================================
"""

import os
import sys
import unittest
import json
import time

# Ensure parent directory is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ai_copilot.harness import GemmaFlightHarness
from ai_copilot.tools import TOOL_DEFINITIONS, VALID_COMMANDS, AerospaceToolExecutor


class TestGemmaAgentSkillStandard(unittest.TestCase):
    """Verifies compliance with the Agent Skill Open Standard v1.0."""

    def test_skill_file_exists(self):
        skill_path = os.path.join(BASE_DIR, "ai_copilot", "skills", "satellite-fdir", "SKILL.md")
        self.assertTrue(os.path.isfile(skill_path), f"SKILL.md must exist at {skill_path}")

    def test_skill_yaml_frontmatter(self):
        skill_path = os.path.join(BASE_DIR, "ai_copilot", "skills", "satellite-fdir", "SKILL.md")
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertTrue(content.startswith("---"), "SKILL.md must have YAML frontmatter starting with ---")
        parts = content.split("---")
        self.assertGreaterEqual(len(parts), 3, "Frontmatter must be enclosed by ---")

        frontmatter = parts[1]
        self.assertIn("name: satellite-fdir", frontmatter)
        self.assertIn("standard: Agent Skill Open Standard", frontmatter)
        self.assertIn("target_model: Gemma 4", frontmatter)
        self.assertIn("description:", frontmatter)


class TestGemmaToolSchemaAndExecution(unittest.TestCase):
    """Verifies tool definitions and deterministic execution safety."""

    def test_tool_definitions_schema(self):
        self.assertIsInstance(TOOL_DEFINITIONS, list)
        tool_names = [t["name"] for t in TOOL_DEFINITIONS]
        self.assertIn("uplink_telecommand", tool_names)
        self.assertIn("emit_fdir_diagnosis", tool_names)

        # Verify uplink_telecommand schema
        tele_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "uplink_telecommand")
        self.assertEqual(tele_tool["parameters"]["type"], "object")
        self.assertIn("command", tele_tool["parameters"]["properties"])
        self.assertIn("rationale", tele_tool["parameters"]["properties"])

    def test_tool_executor_valid_command(self):
        executor = AerospaceToolExecutor()
        res = executor.execute_tool("uplink_telecommand", {
            "command": "CMD:RATE:1200",
            "rationale": "Conserve bus power during solar eclipse."
        })
        self.assertEqual(res["status"], "EXECUTED")
        self.assertEqual(res["command"], "CMD:RATE:1200")
        self.assertIn("rationale", res)

    def test_tool_executor_invalid_command_rejected(self):
        executor = AerospaceToolExecutor()
        res = executor.execute_tool("uplink_telecommand", {
            "command": "CMD:UNAUTHORIZED_DESTRUCT",
            "rationale": "Malicious payload."
        })
        self.assertEqual(res["status"], "REJECTED")

    def test_fdir_diagnosis_tool(self):
        executor = AerospaceToolExecutor()
        diag = executor.execute_tool("emit_fdir_diagnosis", {
            "subsystem": "Thermal (DS18B20)",
            "severity": "CAUTION",
            "root_cause": "Internal temperature elevated due to solar radiation.",
            "confidence_pct": 94.5,
            "recommended_action": "Monitor sensor."
        })
        self.assertEqual(diag["status"], "PUBLISHED")
        self.assertEqual(diag["severity"], "CAUTION")
        self.assertEqual(diag["confidence_pct"], 94.5)


class TestGemmaFlightHarness(unittest.TestCase):
    """Verifies the Gemma 4 Model Harness context memory and reasoning."""

    def setUp(self):
        self.harness = GemmaFlightHarness(buffer_size=10)

    def test_sliding_window_buffer(self):
        for i in range(15):
            self.harness.ingest_telemetry({
                "pkt": i, "met_s": i, "temp_c": 25.0 + i * 0.1,
                "bus_v": 5.0, "current_ma": 300.0, "power_mw": 1500.0,
                "vib_rms_g": 0.05, "pitch_deg": 0.0, "roll_deg": 0.0,
                "fdir_state": 0, "hw_status": 31, "rssi_dbm": -80, "snr_db": 8.0
            })
        self.assertEqual(len(self.harness.telemetry_history), 10, "Buffer must respect maxlen=10")

    def test_nominal_telemetry_diagnosis(self):
        pkt = {
            "pkt": 1, "met_s": 10, "temp_c": 25.4,
            "bus_v": 5.02, "current_ma": 310.0, "power_mw": 1556.2,
            "vib_rms_g": 0.065, "pitch_deg": 1.2, "roll_deg": -0.8,
            "fdir_state": 0, "hw_status": 31, "rssi_dbm": -75, "snr_db": 9.5
        }
        res = self.harness.analyze_telemetry(pkt)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["diagnosis"]["severity"], "NOMINAL")
        self.assertGreaterEqual(res["diagnosis"]["confidence_pct"], 90.0)
        self.assertEqual(len(res["executed_actions"]), 0)

    def test_thermal_runaway_autonomous_mitigation(self):
        pkt = {
            "pkt": 2, "met_s": 12, "temp_c": 39.5,  # Above 38.0°C limit
            "bus_v": 5.01, "current_ma": 340.0, "power_mw": 1703.4,
            "vib_rms_g": 0.08, "pitch_deg": 0.0, "roll_deg": 0.0,
            "fdir_state": 2, "hw_status": 31, "rssi_dbm": -80, "snr_db": 8.0
        }
        res = self.harness.analyze_telemetry(pkt)
        self.assertEqual(res["diagnosis"]["severity"], "CRITICAL")
        self.assertEqual(res["diagnosis"]["subsystem"], "Thermal (DS18B20)")
        # Autonomous action must trigger CMD:RATE:1200
        executed_cmds = [act["command"] for act in res["executed_actions"]]
        self.assertIn("CMD:RATE:1200", executed_cmds)

    def test_eps_brownout_autonomous_mitigation(self):
        harness = GemmaFlightHarness()
        pkt = {
            "pkt": 3, "met_s": 15, "temp_c": 27.0,
            "bus_v": 4.10,  # Below 4.20V brownout threshold
            "current_ma": 650.0, "power_mw": 2665.0,
            "vib_rms_g": 0.05, "pitch_deg": 0.0, "roll_deg": 0.0,
            "fdir_state": 2, "hw_status": 31, "rssi_dbm": -80, "snr_db": 8.0
        }
        res = harness.analyze_telemetry(pkt)
        self.assertEqual(res["diagnosis"]["severity"], "CRITICAL")
        self.assertEqual(res["diagnosis"]["subsystem"], "Electrical Power (INA219)")
        executed_cmds = [act["command"] for act in res["executed_actions"]]
        self.assertIn("CMD:RATE:1200", executed_cmds)

    def test_attitude_despin_failure_mitigation(self):
        harness = GemmaFlightHarness()
        pkt = {
            "pkt": 4, "met_s": 20, "temp_c": 28.0,
            "bus_v": 5.00, "current_ma": 320.0, "power_mw": 1600.0,
            "vib_rms_g": 0.08, "pitch_deg": 82.5, "roll_deg": 12.0,  # >75.0°
            "fdir_state": 2, "hw_status": 31, "rssi_dbm": -80, "snr_db": 8.0
        }
        res = harness.analyze_telemetry(pkt)
        self.assertEqual(res["diagnosis"]["severity"], "CRITICAL")
        self.assertEqual(res["diagnosis"]["subsystem"], "ADCS Orientation (MPU2)")
        executed_cmds = [act["command"] for act in res["executed_actions"]]
        self.assertIn("CMD:TARE", executed_cmds)

    def test_cooldown_rate_limiter(self):
        harness = GemmaFlightHarness()
        pkt_hot = {
            "pkt": 5, "met_s": 25, "temp_c": 40.0,
            "bus_v": 5.0, "current_ma": 300.0, "power_mw": 1500.0,
            "vib_rms_g": 0.05, "pitch_deg": 0.0, "roll_deg": 0.0,
            "fdir_state": 2, "hw_status": 31, "rssi_dbm": -80, "snr_db": 8.0
        }
        # First call: triggers telecommand
        res1 = harness.analyze_telemetry(pkt_hot)
        self.assertGreaterEqual(len(res1["executed_actions"]), 1)

        # Second immediate call with same fault: cooldown blocks duplicate command
        res2 = harness.analyze_telemetry(pkt_hot)
        self.assertEqual(len(res2["executed_actions"]), 0, "Duplicate command must be throttled by cooldown")


if __name__ == "__main__":
    unittest.main()

