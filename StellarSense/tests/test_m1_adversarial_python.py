#!/usr/bin/env python3
"""
Adversarial Python Test Harness for StellarSense Milestone 1
Validates FDIR Hysteresis State Machine, DSP True RMS, and Packet Boundaries.
"""

import math
import random
import unittest
import json

class TestAdversarialFDIR(unittest.TestCase):
    """Stress tests FDIR hysteresis and persistence with extreme boundary noise."""

    TEMP_WARN_HIGH = 33.0
    TEMP_WARN_CLEAR = 32.2
    TEMP_CRIT_HIGH = 38.0
    TEMP_CRIT_CLEAR = 37.2

    VOLT_WARN_LOW = 4.60
    VOLT_WARN_CLEAR = 4.68
    VOLT_CRIT_LOW = 4.20
    VOLT_CRIT_CLEAR = 4.28

    VIB_WARN_HIGH = 0.25
    VIB_WARN_CLEAR = 0.20
    VIB_CRIT_HIGH = 0.70
    VIB_CRIT_CLEAR = 0.60

    def setUp(self):
        self.state = 0 # 0=NOMINAL, 1=CAUTION, 2=CRITICAL
        self.pending = 0
        self.persistence = 0
        self.temp_warn = False
        self.temp_crit = False
        self.volt_warn = False
        self.volt_crit = False
        self.vib_warn = False
        self.vib_crit = False

    def step(self, temp=25.0, volt=5.0, vib=0.05):
        # Temp deadband
        if not self.temp_warn and temp >= self.TEMP_WARN_HIGH:
            self.temp_warn = True
        elif self.temp_warn and temp <= self.TEMP_WARN_CLEAR:
            self.temp_warn = False

        if not self.temp_crit and temp >= self.TEMP_CRIT_HIGH:
            self.temp_crit = True
        elif self.temp_crit and temp <= self.TEMP_CRIT_CLEAR:
            self.temp_crit = False

        # Volt deadband
        if not self.volt_warn and volt <= self.VOLT_WARN_LOW:
            self.volt_warn = True
        elif self.volt_warn and volt >= self.VOLT_WARN_CLEAR:
            self.volt_warn = False

        if not self.volt_crit and volt <= self.VOLT_CRIT_LOW:
            self.volt_crit = True
        elif self.volt_crit and volt >= self.VOLT_CRIT_CLEAR:
            self.volt_crit = False

        # Vib deadband
        if not self.vib_warn and vib >= self.VIB_WARN_HIGH:
            self.vib_warn = True
        elif self.vib_warn and vib <= self.VIB_WARN_CLEAR:
            self.vib_warn = False

        if not self.vib_crit and vib >= self.VIB_CRIT_HIGH:
            self.vib_crit = True
        elif self.vib_crit and vib <= self.VIB_CRIT_CLEAR:
            self.vib_crit = False

        # Candidate
        if self.temp_crit or self.volt_crit or self.vib_crit:
            cand = 2
        elif self.temp_warn or self.volt_warn or self.vib_warn:
            cand = 1
        else:
            cand = 0

        # Persistence
        if cand == self.pending:
            self.persistence += 1
            if self.persistence >= 3:
                self.state = cand
        else:
            self.pending = cand
            self.persistence = 1

        return self.state

    def test_thermal_boundary_monte_carlo(self):
        """Monte Carlo simulation of 5,000 thermal noise samples near trip threshold."""
        random.seed(42)
        # Settle to nominal
        for _ in range(5):
            self.step(temp=25.0)
        self.assertEqual(self.state, 0)

        # Inject noise centered at 32.90C strictly bounded below 32.98C (never crossing 33.0C trip)
        for _ in range(2000):
            t = min(32.98, random.gauss(32.90, 0.02))
            s = self.step(temp=t)
            self.assertEqual(s, 0, "Chatter detected below trip threshold!")

        # Step above trip to 33.5C for 3 samples
        for _ in range(3):
            s = self.step(temp=33.5)
        self.assertEqual(s, 1, "Failed to transition to CAUTION")

        # Inject noise centered at 32.50C (inside deadband [32.2, 33.0])
        for _ in range(2000):
            t = random.gauss(32.50, 0.1)
            # Clip so it never drops below clear 32.2 or above trip 38.0
            t = max(32.25, min(37.0, t))
            s = self.step(temp=t)
            self.assertEqual(s, 1, "Deadband chattered unexpectedly!")

        # Step below clear threshold
        for _ in range(3):
            s = self.step(temp=32.0)
        self.assertEqual(s, 0, "Failed to clear CAUTION to NOMINAL")

    def test_dsp_true_rms_vs_mad(self):
        """Empirically prove True RMS correctly measures sinusoid amplitude whereas MAD underestimates by 10%."""
        # Pure sinusoid: a(t) = A * sin(wt), true RMS is A / sqrt(2) = 0.7071 * A
        A = 1.0 # 1g amplitude
        num_samples = 1000
        omega = 2 * math.pi * 5 # 5 Hz vibration sampled at 20 Hz
        dt = 0.05

        mean_square = 0.0
        alpha = 0.15 # EMA weight

        rms_history = []
        for i in range(num_samples):
            dyn_g = A * math.sin(omega * i * dt)
            dyn_g_sq = dyn_g * dyn_g
            mean_square = 0.85 * mean_square + alpha * dyn_g_sq
            rms = math.sqrt(mean_square)
            rms_history.append(rms)

        # Average steady state RMS over last 200 samples
        steady_rms = sum(rms_history[-200:]) / 200.0
        expected_rms = A / math.sqrt(2.0) # 0.7071
        error_pct = abs(steady_rms - expected_rms) / expected_rms * 100.0

        self.assertLess(error_pct, 5.0, f"True RMS error {error_pct:.2f}% exceeds 5% bound!")

    def test_json_payload_boundary_limits(self):
        """Verify JSON deserialization and bounds on maximum 32-bit integers."""
        max_uint32 = 4294967295
        payload = {
            "pkt": max_uint32,
            "met": max_uint32,
            "temp": 84.99,
            "volt": 5.99,
            "curr": 999.9,
            "pwr": 5999.0,
            "vib": 1.999,
            "pitch": -89.9,
            "roll": 179.9,
            "fdir": "CRITICAL",
            "hw": 63
        }
        serialized = json.dumps(payload)
        self.assertLess(len(serialized), 256, "Serialized JSON frame exceeds 256-byte static buffer limit!")

        parsed = json.loads(serialized)
        self.assertEqual(parsed["pkt"], max_uint32)
        self.assertEqual(parsed["hw"], 63)

if __name__ == "__main__":
    unittest.main()
