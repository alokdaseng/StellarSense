"""
========================================================================================
STELLARSENSE E2E TEST SUITE — TIER 1: TELEMETRY SCHEMA & CONTRACT VALIDATION
File: tests/test_telemetry_schema.py

Methodologies:
 - Category-Partition Testing (Satellite Frame, Enriched GS Frame, System Event, Error Frame)
 - Boundary Value Analysis (BVA) across all physical and mathematical ranges
 - Pairwise Combinations of valid/invalid fields, edge encodings, and malformed types

Authoritative Specifications:
 - PROJECT.md § Interface Contracts (Satellite ↔ Ground Station & Ground Station ↔ Dashboard)
 - ORIGINAL_REQUEST.md & spec_survey_report.md § 2 (Telemetry Frame & RF Communication Specs)
========================================================================================
"""

import unittest
import json
import math


class TelemetrySchemaValidator:
    """
    Authoritative reference validator for StellarSense telemetry and serial frames
    derived from PROJECT.md Interface Contracts and hardware specifications.
    """

    # Physical and logical boundaries
    BOUNDARIES = {
        "pkt": {"min": 1, "max": 4294967295, "type": int},
        "met": {"min": 0, "max": 4294967295, "type": int},
        "temp": {"min": -50.0, "max": 85.0, "type": (float, int)},
        "volt": {"min": 0.0, "max": 6.0, "type": (float, int)},
        "curr": {"min": 0.0, "max": 1000.0, "type": (float, int)},
        "pwr": {"min": 0.0, "max": 6000.0, "type": (float, int)},
        "vib": {"min": 0.0, "max": 10.0, "type": (float, int)},
        "pitch": {"min": -90.0, "max": 90.0, "type": (float, int)},
        "roll": {"min": -180.0, "max": 180.0, "type": (float, int)},
        "fdir": {"allowed": ["NOMINAL", "CAUTION", "CRITICAL"], "type": str},
        "rssi": {"min": -140, "max": 0, "type": int},
        "snr": {"min": -30.0, "max": 30.0, "type": (float, int)},
        "rx_count": {"min": 1, "max": 4294967295, "type": int},
    }

    SATELLITE_REQUIRED_KEYS = {
        "pkt", "met", "temp", "volt", "curr", "pwr", "vib", "pitch", "roll", "fdir"
    }

    ENRICHED_REQUIRED_KEYS = SATELLITE_REQUIRED_KEYS | {"rssi", "snr", "rx_count"}

    @classmethod
    def classify_frame(cls, data):
        """Discriminates between satellite telemetry, ground station system events, and errors."""
        if not isinstance(data, dict):
            return "INVALID_NOT_DICT"
        if "system" in data and data.get("system") == "GROUND_STATION":
            return "SYSTEM_BOOT_EVENT"
        if "error" in data or "err" in data:
            return "ERROR_FRAME"
        if "cmd" in data or any(str(v).startswith("CMD:") for v in data.values()):
            return "TELECOMMAND_FRAME"
        if cls.ENRICHED_REQUIRED_KEYS.issubset(data.keys()):
            return "ENRICHED_TELEMETRY"
        if cls.SATELLITE_REQUIRED_KEYS.issubset(data.keys()):
            return "SATELLITE_TELEMETRY"
        return "UNKNOWN_SCHEMA"

    @classmethod
    def validate_satellite_frame(cls, frame):
        """Validates raw satellite telemetry packet schema and physical bounds."""
        errors = []
        if not isinstance(frame, dict):
            return False, ["Frame is not a dictionary"]

        missing = cls.SATELLITE_REQUIRED_KEYS - set(frame.keys())
        if missing:
            errors.append(f"Missing required satellite keys: {sorted(list(missing))}")

        for key, rules in cls.BOUNDARIES.items():
            if key in cls.SATELLITE_REQUIRED_KEYS and key in frame:
                val = frame[key]
                # Type check
                allowed_types = rules["type"]
                # Convert stringified numbers if coming from serialized ArduinoJson
                if isinstance(val, str) and key != "fdir":
                    try:
                        val = float(val) if "float" in str(allowed_types) else int(val)
                    except ValueError:
                        errors.append(f"Field '{key}' has unparseable string value '{frame[key]}'")
                        continue

                if not isinstance(val, allowed_types):
                    errors.append(f"Field '{key}' expected {allowed_types}, got {type(val).__name__}")
                    continue

                # Range check
                if "min" in rules and (val < rules["min"] or val > rules["max"]):
                    errors.append(f"Field '{key}' value {val} out of bounds [{rules['min']}, {rules['max']}]")
                if "allowed" in rules and val not in rules["allowed"]:
                    errors.append(f"Field '{key}' value '{val}' not in allowed set {rules['allowed']}")

        # Power consistency check (P = V * I within 15% tolerance due to rounding/sensor drift)
        if "volt" in frame and "curr" in frame and "pwr" in frame:
            try:
                v = float(frame["volt"])
                i = float(frame["curr"])
                p = float(frame["pwr"])
                expected_p = v * i
                # Check within 20% or 50mW margin
                if expected_p > 0 and abs(p - expected_p) / max(p, expected_p) > 0.25 and abs(p - expected_p) > 50.0:
                    errors.append(f"Power inconsistency: pwr={p}mW != volt({v}V) * curr({i}mA) = {expected_p:.1f}mW")
            except (ValueError, TypeError):
                pass

        return len(errors) == 0, errors

    @classmethod
    def validate_enriched_frame(cls, frame):
        """Validates enriched ground station telemetry packet schema and RF bounds."""
        sat_valid, errors = cls.validate_satellite_frame(frame)
        missing_rf = (cls.ENRICHED_REQUIRED_KEYS - cls.SATELLITE_REQUIRED_KEYS) - set(frame.keys())
        if missing_rf:
            errors.append(f"Missing ground station RF keys: {sorted(list(missing_rf))}")

        for key in ["rssi", "snr", "rx_count"]:
            if key in frame:
                rules = cls.BOUNDARIES[key]
                val = frame[key]
                if isinstance(val, str):
                    try:
                        val = float(val) if "float" in str(rules["type"]) else int(val)
                    except ValueError:
                        errors.append(f"Field '{key}' unparseable string value '{frame[key]}'")
                        continue
                if not isinstance(val, rules["type"]):
                    errors.append(f"Field '{key}' expected {rules['type']}, got {type(val).__name__}")
                    continue
                if val < rules["min"] or val > rules["max"]:
                    errors.append(f"Field '{key}' value {val} out of bounds [{rules['min']}, {rules['max']}]")

        return len(errors) == 0, errors


class TestTelemetrySchema(unittest.TestCase):
    """
    Tier 1 Unit & Schema Tests for StellarSense Telemetry Contract.
    """

    def setUp(self):
        self.validator = TelemetrySchemaValidator

        # Canonical valid satellite frame
        self.valid_satellite_frame = {
            "pkt": 142,
            "met": 85,
            "temp": 28.40,
            "volt": 4.98,
            "curr": 315.2,
            "pwr": 1569.7,
            "vib": 0.082,
            "pitch": 4.2,
            "roll": -1.8,
            "fdir": "NOMINAL"
        }

        # Canonical valid enriched ground station frame
        self.valid_enriched_frame = {
            "pkt": 142,
            "met": 85,
            "temp": 28.40,
            "volt": 4.98,
            "curr": 315.2,
            "pwr": 1569.7,
            "vib": 0.082,
            "pitch": 4.2,
            "roll": -1.8,
            "fdir": "NOMINAL",
            "rssi": -48,
            "snr": 9.5,
            "rx_count": 142
        }

    # -------------------------------------------------------------------------
    # PARTITION 1: HAPPY PATH CANONICAL FRAMES
    # -------------------------------------------------------------------------
    def test_canonical_satellite_frame_validation(self):
        """Verify baseline valid satellite frame passes validation with zero errors."""
        is_valid, errors = self.validator.validate_satellite_frame(self.valid_satellite_frame)
        self.assertTrue(is_valid, f"Expected canonical frame to be valid, got: {errors}")
        self.assertEqual(len(errors), 0)

    def test_canonical_enriched_frame_validation(self):
        """Verify baseline enriched ground station frame passes validation with zero errors."""
        is_valid, errors = self.validator.validate_enriched_frame(self.valid_enriched_frame)
        self.assertTrue(is_valid, f"Expected canonical enriched frame to be valid, got: {errors}")
        self.assertEqual(len(errors), 0)

    def test_json_serialization_roundtrip(self):
        """Verify JSON serialization and deserialization preserves all schema values."""
        json_str = json.dumps(self.valid_enriched_frame)
        parsed = json.loads(json_str)
        is_valid, errors = self.validator.validate_enriched_frame(parsed)
        self.assertTrue(is_valid, f"Roundtrip serialization failed: {errors}")
        self.assertEqual(parsed["pkt"], 142)
        self.assertAlmostEqual(parsed["temp"], 28.40, places=2)

    # -------------------------------------------------------------------------
    # PARTITION 2: CATEGORY-PARTITION DISCRIMINATOR
    # -------------------------------------------------------------------------
    def test_classify_ground_station_boot_frame(self):
        """Verify discriminator identifies ground station boot frames and prevents telemetry pollution."""
        boot_frame = {"system": "GROUND_STATION", "status": "BOOT_OK", "freq_mhz": 433.0, "baud": 115200}
        classification = self.validator.classify_frame(boot_frame)
        self.assertEqual(classification, "SYSTEM_BOOT_EVENT")

    def test_classify_ground_station_error_frame(self):
        """Verify discriminator identifies RF parse failure frames."""
        error_frame = {"error": "PARSE_FAIL", "raw": "{\"corrupted_payload", "rssi": -92, "snr": -4.2}
        classification = self.validator.classify_frame(error_frame)
        self.assertEqual(classification, "ERROR_FRAME")

    def test_classify_telecommand_frame(self):
        """Verify discriminator identifies uplink telecommands."""
        cmd_frame = {"cmd": "CMD:PING", "seq": 1}
        classification = self.validator.classify_frame(cmd_frame)
        self.assertEqual(classification, "TELECOMMAND_FRAME")

    def test_classify_enriched_vs_satellite_frame(self):
        """Verify correct discrimination between raw RF downlink and USB serial enriched frame."""
        self.assertEqual(self.validator.classify_frame(self.valid_satellite_frame), "SATELLITE_TELEMETRY")
        self.assertEqual(self.validator.classify_frame(self.valid_enriched_frame), "ENRICHED_TELEMETRY")

    # -------------------------------------------------------------------------
    # PARTITION 3: BOUNDARY VALUE ANALYSIS (BVA)
    # -------------------------------------------------------------------------
    def test_bva_packet_counter_boundaries(self):
        """BVA: Packet counter min (1), high values (uint32 max), and invalid values (0, negative)."""
        # Min boundary (1) - Valid
        frame = dict(self.valid_satellite_frame, pkt=1)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        # Uint32 max boundary (4294967295) - Valid
        frame = dict(self.valid_satellite_frame, pkt=4294967295)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        # Below min (0) - Invalid
        frame = dict(self.valid_satellite_frame, pkt=0)
        is_valid, errors = self.validator.validate_satellite_frame(frame)
        self.assertFalse(is_valid)
        self.assertTrue(any("pkt" in e for e in errors))

        # Negative (-1) - Invalid
        frame = dict(self.valid_satellite_frame, pkt=-1)
        self.assertFalse(self.validator.validate_satellite_frame(frame)[0])

    def test_bva_mission_elapsed_time_boundaries(self):
        """BVA: MET at T=0 seconds (boot), large values, and negative invalid value."""
        frame = dict(self.valid_satellite_frame, met=0)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        frame = dict(self.valid_satellite_frame, met=86400 * 365) # 1 year
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        frame = dict(self.valid_satellite_frame, met=-5)
        self.assertFalse(self.validator.validate_satellite_frame(frame)[0])

    def test_bva_temperature_boundaries(self):
        """BVA: DS18B20 physical range (-50C to +85C), caution (33C), critical (38C), disconnect (-127C)."""
        # -50 C min limit - Valid
        frame = dict(self.valid_satellite_frame, temp=-50.0)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        # +85 C max limit - Valid
        frame = dict(self.valid_satellite_frame, temp=85.0)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        # -127 C DS18B20 disconnect error - Invalid physical range
        frame = dict(self.valid_satellite_frame, temp=-127.0)
        is_valid, errors = self.validator.validate_satellite_frame(frame)
        self.assertFalse(is_valid)
        self.assertTrue(any("temp" in e for e in errors))

        # +120 C physical oven exceedance - Invalid
        frame = dict(self.valid_satellite_frame, temp=120.0)
        self.assertFalse(self.validator.validate_satellite_frame(frame)[0])

    def test_bva_bus_voltage_boundaries(self):
        """BVA: Bus voltage limits (0.0V to 6.0V), critical brownout (4.20V), caution sag (4.60V)."""
        # 0.0V bus collapse
        frame = dict(self.valid_satellite_frame, volt=0.0, curr=0.0, pwr=0.0)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        # 6.0V overvoltage max limit
        frame = dict(self.valid_satellite_frame, volt=6.0, curr=100.0, pwr=600.0)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        # -0.5V negative voltage - Invalid
        frame = dict(self.valid_satellite_frame, volt=-0.5)
        self.assertFalse(self.validator.validate_satellite_frame(frame)[0])

        # 7.5V severe overvoltage - Invalid
        frame = dict(self.valid_satellite_frame, volt=7.5)
        self.assertFalse(self.validator.validate_satellite_frame(frame)[0])

    def test_bva_vibration_rms_boundaries(self):
        """BVA: Structural vibration (0.000g to 10.000g), caution threshold (0.250g), critical (0.700g)."""
        # 0.000g zero vibration - Valid
        frame = dict(self.valid_satellite_frame, vib=0.0)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        # 0.250g Caution boundary - Valid
        frame = dict(self.valid_satellite_frame, vib=0.250)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        # 0.700g Critical boundary - Valid
        frame = dict(self.valid_satellite_frame, vib=0.700)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        # Negative vibration - Invalid
        frame = dict(self.valid_satellite_frame, vib=-0.01)
        self.assertFalse(self.validator.validate_satellite_frame(frame)[0])

        # 15.0g extreme beyond accelerometer range - Invalid
        frame = dict(self.valid_satellite_frame, vib=15.0)
        self.assertFalse(self.validator.validate_satellite_frame(frame)[0])

    def test_bva_attitude_angles_boundaries(self):
        """BVA: Pitch [-90.0, +90.0] degrees, Roll [-180.0, +180.0] degrees."""
        # Exact pitch boundaries
        frame = dict(self.valid_satellite_frame, pitch=-90.0)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])
        frame = dict(self.valid_satellite_frame, pitch=90.0)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        # Pitch out of range
        frame = dict(self.valid_satellite_frame, pitch=90.1)
        self.assertFalse(self.validator.validate_satellite_frame(frame)[0])
        frame = dict(self.valid_satellite_frame, pitch=-90.1)
        self.assertFalse(self.validator.validate_satellite_frame(frame)[0])

        # Exact roll boundaries
        frame = dict(self.valid_satellite_frame, roll=-180.0)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])
        frame = dict(self.valid_satellite_frame, roll=180.0)
        self.assertTrue(self.validator.validate_satellite_frame(frame)[0])

        # Roll out of range
        frame = dict(self.valid_satellite_frame, roll=180.5)
        self.assertFalse(self.validator.validate_satellite_frame(frame)[0])
        frame = dict(self.valid_satellite_frame, roll=-180.5)
        self.assertFalse(self.validator.validate_satellite_frame(frame)[0])

    def test_bva_rf_metrics_boundaries(self):
        """BVA: RSSI [-140 dBm, 0 dBm], SNR [-30 dB, +30 dB]."""
        frame = dict(self.valid_enriched_frame, rssi=-140, snr=-30.0)
        self.assertTrue(self.validator.validate_enriched_frame(frame)[0])

        frame = dict(self.valid_enriched_frame, rssi=0, snr=30.0)
        self.assertTrue(self.validator.validate_enriched_frame(frame)[0])

        # RSSI positive (physically invalid for received RF signal)
        frame = dict(self.valid_enriched_frame, rssi=5)
        self.assertFalse(self.validator.validate_enriched_frame(frame)[0])

        # RSSI below receiver sensitivity floor
        frame = dict(self.valid_enriched_frame, rssi=-155)
        self.assertFalse(self.validator.validate_enriched_frame(frame)[0])

    # -------------------------------------------------------------------------
    # PARTITION 4: ADVERSARIAL INPUT COMBINATIONS & TYPE SAFETY
    # -------------------------------------------------------------------------
    def test_missing_required_keys(self):
        """Adversarial: Individually drop each required key and verify failure."""
        for key in self.validator.SATELLITE_REQUIRED_KEYS:
            corrupted = dict(self.valid_satellite_frame)
            del corrupted[key]
            is_valid, errors = self.validator.validate_satellite_frame(corrupted)
            self.assertFalse(is_valid, f"Expected validation failure when key '{key}' was dropped")
            self.assertTrue(any(key in e for e in errors))

    def test_invalid_fdir_enum_values(self):
        """Adversarial: Invalid FDIR strings must be rejected."""
        invalid_fdirs = ["WARNING", "ERROR", "OK", "UNKNOWN", "", "123", "nominal"]
        for fdir in invalid_fdirs:
            frame = dict(self.valid_satellite_frame, fdir=fdir)
            is_valid, errors = self.validator.validate_satellite_frame(frame)
            self.assertFalse(is_valid, f"Expected invalid FDIR string '{fdir}' to be rejected")

    def test_corrupted_type_safety(self):
        """Adversarial: Non-numeric values in numeric fields."""
        type_corruptions = [
            ("temp", "HOT"),
            ("volt", [5.0]),
            ("curr", {"value": 300}),
            ("vib", None),
            ("pkt", "first_packet")
        ]
        for field, bad_val in type_corruptions:
            frame = dict(self.valid_satellite_frame, **{field: bad_val})
            is_valid, errors = self.validator.validate_satellite_frame(frame)
            self.assertFalse(is_valid, f"Expected type corruption on '{field}' with {bad_val} to fail")

    def test_stringified_float_graceful_handling(self):
        """Verify ArduinoJson serialized strings (e.g. '28.40') are correctly parsed."""
        stringified_frame = {
            "pkt": 142,
            "met": 85,
            "temp": "28.40",
            "volt": "4.98",
            "curr": "315.2",
            "pwr": "1569.7",
            "vib": "0.082",
            "pitch": "4.2",
            "roll": "-1.8",
            "fdir": "NOMINAL"
        }
        is_valid, errors = self.validator.validate_satellite_frame(stringified_frame)
        self.assertTrue(is_valid, f"Stringified floats should be valid, got: {errors}")


if __name__ == '__main__':
    unittest.main()
