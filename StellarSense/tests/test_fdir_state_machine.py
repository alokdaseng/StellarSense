"""
========================================================================================
STELLARSENSE E2E TEST SUITE — TIER 2: FDIR STATE MACHINE & PERSISTENCE DEBOUNCE
File: tests/test_fdir_state_machine.py

Methodologies:
 - Mathematical Simulation of Dual-Threshold Hysteresis Deadbands
 - 3-Sample (150ms @ 20Hz) Persistence Debounce Verification
 - State Transition Completeness (Nominal, Caution, Critical)
 - Multi-Subsystem Anomaly Priority Arbitration & Fault Isolation

Authoritative Specifications:
 - PROJECT.md § Architecture & Feature Inventory (Feature 7)
 - explorer_firmware_survey/handoff.md § 1.6 & 2.6
 - spec_survey_report.md § 3 (Autonomous FDIR Matrix & Recovery Rules)
========================================================================================
"""

import unittest
from enum import Enum


class FDIRState(Enum):
    NOMINAL = 0
    CAUTION = 1
    CRITICAL = 2


class FDIRSubsystem(Enum):
    THERMAL = "TCS"
    ELECTRICAL = "EPS"
    STRUCTURE = "STR"
    ATTITUDE = "ADCS"
    COMMS = "COMMS"


class AerospaceFDIRSimulator:
    """
    Mathematical reference model of the dual-tier FDIR state machine
    with hysteresis deadbands and 3-sample persistence debounce filtering.
    """

    # Trip Thresholds (Escalation)
    TEMP_WARN_TRIP = 33.0     # deg C
    TEMP_CRIT_TRIP = 38.0     # deg C
    VOLT_WARN_TRIP = 4.60     # Volts
    VOLT_CRIT_TRIP = 4.20     # Volts
    VIB_WARN_TRIP = 0.250     # g RMS
    VIB_CRIT_TRIP = 0.700     # g RMS

    # Clear Thresholds (Hysteresis Recovery)
    TEMP_WARN_CLEAR = 32.2    # deg C (0.8C deadband)
    TEMP_CRIT_CLEAR = 37.2    # deg C (0.8C deadband)
    VOLT_WARN_CLEAR = 4.68    # Volts (0.08V deadband)
    VOLT_CRIT_CLEAR = 4.28    # Volts (0.08V deadband)
    VIB_WARN_CLEAR = 0.200    # g RMS (0.05g deadband)
    VIB_CRIT_CLEAR = 0.600    # g RMS (0.10g deadband)

    PERSISTENCE_LIMIT = 3     # 3 consecutive samples required for transition

    def __init__(self):
        self.system_state = FDIRState.NOMINAL
        self.subsystem_states = {
            FDIRSubsystem.THERMAL: FDIRState.NOMINAL,
            FDIRSubsystem.ELECTRICAL: FDIRState.NOMINAL,
            FDIRSubsystem.STRUCTURE: FDIRState.NOMINAL,
            FDIRSubsystem.ATTITUDE: FDIRState.NOMINAL,
            FDIRSubsystem.COMMS: FDIRState.NOMINAL,
        }

        # Candidate target states and persistence counters per subsystem
        self.subsystem_candidates = {s: FDIRState.NOMINAL for s in FDIRSubsystem}
        self.persistence_counters = {s: 0 for s in FDIRSubsystem}

        # Sensor health flags (defensive isolation)
        self.temp_sensor_online = True
        self.ina219_online = True
        self.mpu_vibration_online = True

        # Transition history log
        self.transition_log = []

    def _evaluate_instantaneous_subsystem(self, subsystem, temp, volt, vib):
        """Calculates instantaneous target state based on hysteresis thresholds."""
        curr = self.subsystem_states[subsystem]

        if subsystem == FDIRSubsystem.THERMAL:
            if not self.temp_sensor_online or temp <= -50.0 or temp >= 85.0:
                # Disconnected / invalid sensor -> isolate without false trip
                return FDIRState.NOMINAL
            if curr == FDIRState.NOMINAL:
                if temp >= self.TEMP_CRIT_TRIP:
                    return FDIRState.CRITICAL
                if temp >= self.TEMP_WARN_TRIP:
                    return FDIRState.CAUTION
                return FDIRState.NOMINAL
            elif curr == FDIRState.CAUTION:
                if temp >= self.TEMP_CRIT_TRIP:
                    return FDIRState.CRITICAL
                if temp < self.TEMP_WARN_CLEAR:
                    return FDIRState.NOMINAL
                return FDIRState.CAUTION
            elif curr == FDIRState.CRITICAL:
                if temp < self.TEMP_CRIT_CLEAR:
                    # De-escalates to caution if above caution clear
                    return FDIRState.CAUTION if temp >= self.TEMP_WARN_CLEAR else FDIRState.NOMINAL
                return FDIRState.CRITICAL

        elif subsystem == FDIRSubsystem.ELECTRICAL:
            if not self.ina219_online:
                return FDIRState.NOMINAL
            if curr == FDIRState.NOMINAL:
                if volt <= self.VOLT_CRIT_TRIP:
                    return FDIRState.CRITICAL
                if volt <= self.VOLT_WARN_TRIP:
                    return FDIRState.CAUTION
                return FDIRState.NOMINAL
            elif curr == FDIRState.CAUTION:
                if volt <= self.VOLT_CRIT_TRIP:
                    return FDIRState.CRITICAL
                if volt > self.VOLT_WARN_CLEAR:
                    return FDIRState.NOMINAL
                return FDIRState.CAUTION
            elif curr == FDIRState.CRITICAL:
                if volt > self.VOLT_CRIT_CLEAR:
                    return FDIRState.CAUTION if volt <= self.VOLT_WARN_CLEAR else FDIRState.NOMINAL
                return FDIRState.CRITICAL

        elif subsystem == FDIRSubsystem.STRUCTURE:
            if not self.mpu_vibration_online:
                return FDIRState.NOMINAL
            if curr == FDIRState.NOMINAL:
                if vib >= self.VIB_CRIT_TRIP:
                    return FDIRState.CRITICAL
                if vib >= self.VIB_WARN_TRIP:
                    return FDIRState.CAUTION
                return FDIRState.NOMINAL
            elif curr == FDIRState.CAUTION:
                if vib >= self.VIB_CRIT_TRIP:
                    return FDIRState.CRITICAL
                if vib < self.VIB_WARN_CLEAR:
                    return FDIRState.NOMINAL
                return FDIRState.CAUTION
            elif curr == FDIRState.CRITICAL:
                if vib < self.VIB_CRIT_CLEAR:
                    return FDIRState.CAUTION if vib >= self.VIB_WARN_CLEAR else FDIRState.NOMINAL
                return FDIRState.CRITICAL

        return FDIRState.NOMINAL

    def step(self, temp=25.0, volt=5.00, vib=0.06):
        """
        Executes one 50ms discrete sampling step across all subsystems.
        Applies 3-sample persistence debounce before confirming state change.
        """
        for sub in [FDIRSubsystem.THERMAL, FDIRSubsystem.ELECTRICAL, FDIRSubsystem.STRUCTURE]:
            target = self._evaluate_instantaneous_subsystem(sub, temp, volt, vib)
            current = self.subsystem_states[sub]

            if target != current:
                # Potential state change candidate
                if target == self.subsystem_candidates[sub]:
                    self.persistence_counters[sub] += 1
                else:
                    self.subsystem_candidates[sub] = target
                    self.persistence_counters[sub] = 1

                # Confirm transition once candidate persists for PERSISTENCE_LIMIT samples
                if self.persistence_counters[sub] >= self.PERSISTENCE_LIMIT:
                    old_state = self.subsystem_states[sub]
                    self.subsystem_states[sub] = target
                    self.persistence_counters[sub] = 0
                    self.transition_log.append({
                        "subsystem": sub.value,
                        "from": old_state.name,
                        "to": target.name,
                        "reason": f"Sustained for {self.PERSISTENCE_LIMIT} samples"
                    })
            else:
                # Signal aligned with current confirmed state; reset candidate debounce
                self.subsystem_candidates[sub] = current
                self.persistence_counters[sub] = 0

        # Overall system state is the highest severity across all subsystems
        max_severity = max(s.value for s in self.subsystem_states.values())
        self.system_state = FDIRState(max_severity)
        return self.system_state


class TestFDIRStateMachine(unittest.TestCase):
    """
    Tier 2 Integration Tests: FDIR Multi-Tier Thresholds, Hysteresis, and Debounce.
    """

    def setUp(self):
        self.fdir = AerospaceFDIRSimulator()

    # -------------------------------------------------------------------------
    # 1. PERSISTENCE FILTER & DEBOUNCE REJECTION
    # -------------------------------------------------------------------------
    def test_single_sample_noise_glitch_rejection(self):
        """Verify a single-cycle noise spike above threshold does NOT trip state transition."""
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)

        # 1 cycle spike at 35.0 C (above Caution 33.0 C)
        self.fdir.step(temp=35.0, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL,
                         "Single sample spike must be filtered by persistence debounce")

        # Returns to nominal next cycle
        self.fdir.step(temp=25.0, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)

    def test_two_sample_noise_glitch_rejection(self):
        """Verify 2-sample transient spike is filtered and does not trip caution."""
        self.fdir.step(temp=34.0, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)
        self.fdir.step(temp=34.5, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)

        # Glitch clears on 3rd sample
        self.fdir.step(temp=28.0, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)

    def test_sustained_three_samples_triggers_state_escalation(self):
        """Verify 3 consecutive cycles above threshold successfully triggers state change."""
        self.fdir.step(temp=33.5, volt=5.00, vib=0.06) # Sample 1
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)
        self.fdir.step(temp=33.6, volt=5.00, vib=0.06) # Sample 2
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)
        self.fdir.step(temp=33.4, volt=5.00, vib=0.06) # Sample 3 -> Tripped!
        self.assertEqual(self.fdir.system_state, FDIRState.CAUTION)

    # -------------------------------------------------------------------------
    # 2. HYSTERESIS DEADBAND VALIDATION (ANTI-CHATTER)
    # -------------------------------------------------------------------------
    def test_thermal_hysteresis_deadband(self):
        """
        Verify temperature trip at 33.0C and clear only below 32.2C.
        Values between 32.3C and 32.9C must maintain CAUTION to prevent boundary chatter.
        """
        # Trip to Caution (3 sustained samples @ 33.2C)
        for _ in range(3):
            self.fdir.step(temp=33.2, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.CAUTION)

        # Temperature drops slightly to 32.8 C (below trip 33.0C but above clear 32.2C)
        for _ in range(5):
            self.fdir.step(temp=32.8, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.CAUTION,
                         "Hysteresis deadband: state must remain CAUTION while above 32.2C")

        # Temperature drops below clear threshold to 32.0 C for 3 samples
        for _ in range(3):
            self.fdir.step(temp=32.0, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL,
                         "State must recover to NOMINAL once sustained below 32.2C")

    def test_voltage_hysteresis_deadband(self):
        """
        Verify bus voltage trip at <= 4.60V and clear only above 4.68V.
        """
        # Trip to Caution (3 samples @ 4.55V)
        for _ in range(3):
            self.fdir.step(temp=25.0, volt=4.55, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.CAUTION)

        # Voltage rises to 4.65V (above 4.60V trip, but below 4.68V clear)
        for _ in range(5):
            self.fdir.step(temp=25.0, volt=4.65, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.CAUTION)

        # Voltage recovers to 4.80V for 3 samples
        for _ in range(3):
            self.fdir.step(temp=25.0, volt=4.80, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)

    def test_vibration_hysteresis_deadband(self):
        """
        Verify vibration RMS trip at >= 0.250g and clear only below 0.200g.
        """
        # Trip to Caution
        for _ in range(3):
            self.fdir.step(temp=25.0, volt=5.00, vib=0.280)
        self.assertEqual(self.fdir.system_state, FDIRState.CAUTION)

        # Flutter drops to 0.220g (inside hysteresis deadband [0.200g, 0.250g])
        for _ in range(5):
            self.fdir.step(temp=25.0, volt=5.00, vib=0.220)
        self.assertEqual(self.fdir.system_state, FDIRState.CAUTION)

        # Drops below 0.200g
        for _ in range(3):
            self.fdir.step(temp=25.0, volt=5.00, vib=0.150)
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)

    # -------------------------------------------------------------------------
    # 3. MULTI-SUBSYSTEM PRIORITY ARBITRATION
    # -------------------------------------------------------------------------
    def test_critical_precedence_over_caution(self):
        """Verify CRITICAL fault on any subsystem overrides CAUTION on another."""
        # Thermal is in CAUTION (35.0 C)
        for _ in range(3):
            self.fdir.step(temp=35.0, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.CAUTION)

        # EPS develops CRITICAL brownout (4.10 V)
        for _ in range(3):
            self.fdir.step(temp=35.0, volt=4.10, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.CRITICAL)

        # EPS recovers to nominal (5.00 V), but thermal remains in CAUTION (35.0 C)
        for _ in range(3):
            self.fdir.step(temp=35.0, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.CAUTION,
                         "System state must gracefully de-escalate to CAUTION when CRITICAL clears")

        # Thermal recovers to nominal (25.0 C)
        for _ in range(3):
            self.fdir.step(temp=25.0, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)

    # -------------------------------------------------------------------------
    # 4. DEFENSIVE SENSOR ISOLATION (ZERO-HANG GUARANTEE)
    # -------------------------------------------------------------------------
    def test_ds18b20_sensor_disconnect_isolation(self):
        """
        Verify that DS18B20 disconnect (-127.0 C) does NOT trigger false emergency,
        but safely isolates the thermal subsystem.
        """
        # Initial nominal operation
        for _ in range(3):
            self.fdir.step(temp=25.0, volt=5.00, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)

        # Wire disconnects -> DallasTemperature library returns -127.0 C
        for _ in range(10):
            self.fdir.step(temp=-127.0, volt=5.00, vib=0.06)

        # Must NOT trip CRITICAL or CAUTION
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)
        self.assertEqual(self.fdir.subsystem_states[FDIRSubsystem.THERMAL], FDIRState.NOMINAL)

    def test_ina219_sensor_disconnect_isolation(self):
        """
        Verify that INA219 offline flag disables electrical trips to prevent false brownout alarms.
        """
        self.fdir.ina219_online = False
        for _ in range(5):
            self.fdir.step(temp=25.0, volt=0.0, vib=0.06)
        self.assertEqual(self.fdir.system_state, FDIRState.NOMINAL)


if __name__ == '__main__':
    unittest.main()
