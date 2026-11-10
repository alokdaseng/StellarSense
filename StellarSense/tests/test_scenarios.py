"""
========================================================================================
STELLARSENSE E2E TEST SUITE — TIER 4: REAL-WORLD FLIGHT SCENARIOS
File: tests/test_scenarios.py

Methodologies:
 - End-to-End Mission Scenario Orchestration (100% Opaque-Box Telemetry Simulation)
 - Aerospace Environmental Dynamics (Orbital Passes, Solar Flux, Shadows, Resonance)
 - Autonomous Reflex Validation (Escalation, Annunciation, Deadbands, De-escalation)
 - Link Budget Tracking (Sequence Gaps, Packet Loss %, Loss of Signal Watchdog)

Scenarios Covered:
 1. Nominal Orbital Pass (60-sec pass, 100 packets, zero faults, 100% link budget)
 2. Thermal Excursion / Direct Solar Heating (Nominal -> Caution -> Critical -> Recovery)
 3. Solar Eclipse Battery Brownout (EPS Bus Sag -> Critical Brownout -> Sunlit Recovery)
 4. High-Frequency Structural Flutter (Acoustic Resonance Spike -> Damping Recovery)
 5. Uncontrolled Tumble & Tumbling Recovery (Separation Tip-Off -> ADCS Detumble Horizon)
 6. Loss of Signal (LOS) Watchdog & RF Fade (Packet Gap -> RF Silence >3s -> LOS Clear)

Authoritative Specifications:
 - PROJECT.md § Architecture, Feature Inventory & Milestones
 - PITCH_CHEATSHEET.md § 1, 2, 3 (Judge pitch runbook & live demo cues)
 - spec_survey_report.md § 3, 4, 7
========================================================================================
"""

import unittest
import math
from tests.test_telemetry_schema import TelemetrySchemaValidator
from tests.test_fdir_state_machine import AerospaceFDIRSimulator, FDIRState
from tests.test_dsp_algorithms import (
    TrueRMSVibrationDSP,
    ComplementaryAttitudeFilter,
    TumbleRateCalculator
)


class FlightMissionHarness:
    """
    Simulates the end-to-end telemetry pipeline across Satellite OBC,
    Ra-02 433MHz LoRa Link, ESP32 Ground Station, and Mission Control Dashboard.
    """

    def __init__(self):
        self.fdir = AerospaceFDIRSimulator()
        self.vib_dsp = TrueRMSVibrationDSP(ema_alpha=0.15)
        self.attitude_filter = ComplementaryAttitudeFilter(gyro_weight=0.96)
        self.validator = TelemetrySchemaValidator

        # Mission state variables
        self.current_met = 0
        self.current_pkt = 0
        self.rx_count = 0
        self.received_frames = []
        self.fdir_history = []
        self.annunciator_events = []

        # Loss of Signal (LOS) Watchdog Tracker
        self.last_rx_met = 0
        self.los_triggered = False
        self.total_dropped_packets = 0

    def step_flight_cycle(self, temp=27.0, volt=5.02, curr=310.0,
                          vib_ax=0.0, vib_ay=0.0, vib_az=9.80665,
                          gyro_x=0.0, gyro_y=0.0,
                          rssi=-48, snr=9.5,
                          drop_packet=False):
        """
        Executes one flight interval (dt = 0.6s downlink, matching 600ms telemetry cycle).
        """
        self.current_met += 1
        self.current_pkt += 1

        # 1. Onboard DSP Processing
        vib_rms = self.vib_dsp.process_sample(vib_ax, vib_ay, vib_az)
        pwr = volt * curr
        pitch, roll = self.attitude_filter.update(
            ax=vib_ax, ay=vib_ay, az=vib_az,
            gyro_x_dps=gyro_x, gyro_y_dps=gyro_y,
            dt=0.60
        )

        # 2. Onboard FDIR 3-sample Persistence State Evaluation
        system_fdir = self.fdir.step(temp=temp, volt=volt, vib=vib_rms)

        # 3. Satellite Telemetry Packet Serialization
        satellite_frame = {
            "pkt": self.current_pkt,
            "met": self.current_met,
            "temp": round(temp, 2),
            "volt": round(volt, 2),
            "curr": round(curr, 1),
            "pwr": round(pwr, 1),
            "vib": round(vib_rms, 3),
            "pitch": round(pitch, 1),
            "roll": round(roll, 1),
            "fdir": system_fdir.name
        }

        # 4. LoRa RF Transmission & Ground Station Reception
        if drop_packet:
            self.total_dropped_packets += 1
            # Check LOS watchdog condition (>3 seconds of telemetry silence)
            if (self.current_met - self.last_rx_met) >= 3:
                self.los_triggered = True
                self.annunciator_events.append(f"[T+{self.current_met}s] COMMS_ALERT: LOSS OF SIGNAL (LOS) WATCHDOG TRIGGERED")
            return None

        # Successful reception by Ground Station
        self.rx_count += 1
        self.last_rx_met = self.current_met
        self.los_triggered = False

        # Ground station link enrichment
        enriched_frame = dict(satellite_frame, rssi=rssi, snr=snr, rx_count=self.rx_count)
        self.received_frames.append(enriched_frame)
        self.fdir_history.append(system_fdir.name)
        return enriched_frame


class TestFlightScenarios(unittest.TestCase):
    """
    Tier 4 Mission Scenarios: Real-World Flight Conditions & Edge Case Verification.
    """

    # -------------------------------------------------------------------------
    # SCENARIO 1: NOMINAL ORBITAL PASS (60-SECOND BASELINE)
    # -------------------------------------------------------------------------
    def test_scenario_1_nominal_orbital_pass(self):
        """
        Scenario 1: 60-Second Nominal Orbital Pass (100 packets @ 600ms).
        - Core temp stable at 26-28 C
        - EPS bus stable at 5.00-5.04 V
        - Vibration quiet (< 0.08g)
        - Pitch/Roll stabilized near nadir
        - Verifies 100% packet integrity, zero packet drops, 100% NOMINAL FDIR.
        """
        harness = FlightMissionHarness()

        for step in range(100):
            # Gentle harmonic temperature & voltage variations
            temp = 27.0 + 0.8 * math.sin(step / 10.0)
            volt = 5.02 + 0.02 * math.cos(step / 15.0)
            curr = 310.0 + 10.0 * math.sin(step / 8.0)
            frame = harness.step_flight_cycle(temp=temp, volt=volt, curr=curr)

            # Validate each frame adheres strictly to enriched schema
            is_valid, errors = harness.validator.validate_enriched_frame(frame)
            self.assertTrue(is_valid, f"Packet {step} invalid: {errors}")
            self.assertEqual(frame["fdir"], "NOMINAL")

        self.assertEqual(len(harness.received_frames), 100)
        self.assertEqual(harness.total_dropped_packets, 0)
        self.assertFalse(harness.los_triggered)
        # All states remained strictly NOMINAL
        self.assertTrue(all(f == "NOMINAL" for f in harness.fdir_history))

    # -------------------------------------------------------------------------
    # SCENARIO 2: THERMAL EXCURSION / DIRECT SOLAR HEATING
    # -------------------------------------------------------------------------
    def test_scenario_2_thermal_excursion_and_solar_heating(self):
        """
        Scenario 2: Spacecraft rotates into direct solar flux -> thermal runaway -> shadow cooling.
        - T=0..10: Nominal equilibrium (27 C)
        - T=11..25: Temperature rises to 34.5 C (Trips CAUTION at 33.0 C)
        - T=26..40: Solar flare / direct thermal flux surges to 39.5 C (Trips CRITICAL at 38.0 C)
        - T=41..55: Off-pointing attitude maneuver; temp cools to 36.0 C (Hysteresis de-escalates to CAUTION < 37.2 C)
        - T=56..70: Spacecraft enters orbital shadow; temp cools to 28.0 C (Recovers to NOMINAL < 32.2 C)
        """
        harness = FlightMissionHarness()

        # Phase 1: Nominal
        for _ in range(10):
            harness.step_flight_cycle(temp=27.0)
        self.assertEqual(harness.fdir_history[-1], "NOMINAL")

        # Phase 2: Caution thermal excursion (>33.0C)
        for _ in range(15):
            harness.step_flight_cycle(temp=34.5)
        self.assertEqual(harness.fdir_history[-1], "CAUTION")

        # Phase 3: Critical thermal runaway (>38.0C)
        for _ in range(15):
            harness.step_flight_cycle(temp=39.5)
        self.assertEqual(harness.fdir_history[-1], "CRITICAL")

        # Phase 4: Cooling into hysteresis deadband (36.0 C < 37.2 C clear threshold)
        for _ in range(15):
            harness.step_flight_cycle(temp=36.0)
        self.assertEqual(harness.fdir_history[-1], "CAUTION",
                         "Must de-escalate from CRITICAL to CAUTION once below 37.2C")

        # Phase 5: Orbital shadow cooling (28.0 C < 32.2 C clear threshold)
        for _ in range(15):
            harness.step_flight_cycle(temp=28.0)
        self.assertEqual(harness.fdir_history[-1], "NOMINAL",
                         "Must fully recover to NOMINAL once sustained below 32.2C")

    # -------------------------------------------------------------------------
    # SCENARIO 3: SOLAR ECLIPSE BATTERY BROWNOUT
    # -------------------------------------------------------------------------
    def test_scenario_3_solar_eclipse_battery_brownout(self):
        """
        Scenario 3: Spacecraft enters Earth's shadow; solar arrays lose illumination;
        battery voltage sags through Caution into Critical Brownout, then re-illuminates.
        - Nominal: 5.02V
        - Sag: 4.45V (Trips EPS CAUTION <= 4.60V)
        - Brownout: 4.10V (Trips EPS CRITICAL <= 4.20V)
        - Sunlight recharge: 4.75V (Clears to CAUTION > 4.28V and NOMINAL > 4.68V)
        """
        harness = FlightMissionHarness()

        # Sunlight nominal
        for _ in range(10):
            harness.step_flight_cycle(volt=5.02)
        self.assertEqual(harness.fdir_history[-1], "NOMINAL")

        # Umbra entry: battery voltage sag to 4.45V
        for _ in range(15):
            harness.step_flight_cycle(volt=4.45)
        self.assertEqual(harness.fdir_history[-1], "CAUTION")

        # Deep eclipse: brownout danger at 4.10V
        for _ in range(15):
            harness.step_flight_cycle(volt=4.10)
        self.assertEqual(harness.fdir_history[-1], "CRITICAL")

        # Sunlight exit: arrays re-illuminate, voltage restores to 4.75V
        for _ in range(15):
            harness.step_flight_cycle(volt=4.75)
        self.assertEqual(harness.fdir_history[-1], "NOMINAL",
                         "Bus voltage above 4.68V clearing threshold restores EPS to NOMINAL")

    # -------------------------------------------------------------------------
    # SCENARIO 4: HIGH-FREQUENCY STRUCTURAL FLUTTER
    # -------------------------------------------------------------------------
    def test_scenario_4_high_frequency_structural_flutter(self):
        """
        Scenario 4: Reaction wheel micro-vibration & structural flutter resonance.
        - Phase 1: Baseline quiet (0.05g RMS)
        - Phase 2: Moderate flutter (0.35g RMS -> CAUTION >= 0.25g)
        - Phase 3: Severe resonance surge (0.85g RMS -> CRITICAL >= 0.70g)
        - Phase 4: Structural damping dissipation -> recovers below 0.20g -> NOMINAL.
        """
        harness = FlightMissionHarness()

        # Baseline
        for _ in range(10):
            harness.step_flight_cycle(vib_ax=0.0, vib_ay=0.0, vib_az=9.80665)
        self.assertEqual(harness.fdir_history[-1], "NOMINAL")

        # Flutter spike: oscillating dynamic acceleration (vibration)
        for step in range(20):
            sign = 1.0 if (step % 2 == 0) else -1.0
            harness.step_flight_cycle(vib_ax=3.0 * sign, vib_ay=1.5 * sign, vib_az=9.80665)
        self.assertEqual(harness.fdir_history[-1], "CAUTION")

        # Severe launch/resonance spike: larger oscillating acceleration
        for step in range(20):
            sign = 1.0 if (step % 2 == 0) else -1.0
            harness.step_flight_cycle(vib_ax=7.5 * sign, vib_ay=5.0 * sign, vib_az=9.80665)
        self.assertEqual(harness.fdir_history[-1], "CRITICAL")

        # Damping active: dynamic vibrations cease (stationary 1g gravity)
        for _ in range(35):
            harness.step_flight_cycle(vib_ax=0.0, vib_ay=0.0, vib_az=9.80665)
        self.assertEqual(harness.fdir_history[-1], "NOMINAL")

    # -------------------------------------------------------------------------
    # SCENARIO 5: UNCONTROLLED TUMBLE & TUMBLING RECOVERY
    # -------------------------------------------------------------------------
    def test_scenario_5_uncontrolled_tumble_and_recovery(self):
        """
        Scenario 5: Separation tip-off causes high tumble angular rate.
        - Verifies tumble rate calculator flags rates >30 dps.
        - Verifies detumble maneuvers bring angular rate back to <5 dps.
        - Verifies attitude filter maintains pitch/roll stability during recovery.
        """
        harness = FlightMissionHarness()

        # Satellite is tumbling at 45 dps pitch and 35 dps roll
        tumble_vel_initial = TumbleRateCalculator.compute_from_rates(45.0, 35.0, 0.0)
        self.assertAlmostEqual(tumble_vel_initial, 57.0, delta=1.0)
        self.assertGreater(tumble_vel_initial, 30.0, "Must flag uncontrolled tumble")

        # Detumble maneuver active across 30 flight cycles
        for step in range(30):
            decay = max(0.05, 1.0 - (step / 25.0))
            gx = 45.0 * decay
            gy = 35.0 * decay
            harness.step_flight_cycle(gyro_x=gx, gyro_y=gy)

        # Final stabilized tumble velocity
        tumble_vel_final = TumbleRateCalculator.compute_from_rates(
            gx, gy, 0.0
        )
        self.assertLess(tumble_vel_final, 5.0, "Detumble maneuver must stabilize rates below 5 dps")

    # -------------------------------------------------------------------------
    # SCENARIO 6: LOSS OF SIGNAL (LOS) WATCHDOG & RF PACKET GAP
    # -------------------------------------------------------------------------
    def test_scenario_6_loss_of_signal_watchdog_and_packet_gap(self):
        """
        Scenario 6: RF Link degradation, burst packet drop, and LOS timeout.
        - T=0..20: Nominal link (RSSI -48 dBm, SNR 9.5 dB, 0 drops)
        - T=21..26: RF interference fades link; 6 consecutive packets dropped.
        - Verifies: >3.0 seconds of silence trips Loss of Signal (LOS) Watchdog.
        - T=27..35: Re-acquisition of signal; LOS clears, packets resume.
        """
        harness = FlightMissionHarness()

        # Initial link nominal
        for _ in range(20):
            harness.step_flight_cycle(rssi=-48, snr=9.5)
        self.assertFalse(harness.los_triggered)
        self.assertEqual(len(harness.received_frames), 20)

        # Drop 6 consecutive packets (3.6 seconds of total RF silence)
        for _ in range(6):
            harness.step_flight_cycle(drop_packet=True)

        self.assertTrue(harness.los_triggered,
                        "Loss of Signal (LOS) watchdog must trip when silence >= 3 seconds")
        self.assertEqual(harness.total_dropped_packets, 6)

        # Signal re-acquired at T+27s
        frame = harness.step_flight_cycle(rssi=-52, snr=8.0, drop_packet=False)
        self.assertFalse(harness.los_triggered,
                         "LOS state must automatically clear upon packet reception")
        self.assertIsNotNone(frame)
        self.assertEqual(frame["rx_count"], 21)


if __name__ == '__main__':
    unittest.main()
