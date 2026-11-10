r"""
========================================================================================
STELLARSENSE E2E TEST SUITE — TIER 2: DIGITAL SIGNAL PROCESSING (DSP) & SENSOR FUSION
File: tests/test_dsp_algorithms.py

Methodologies:
 - Mathematical Simulation of True RMS Vibration ($g_RMS = \sqrt{EMA(dynG^2)}$)
 - Dynamic High-Pass Filter DC Gravity Offset Rejection
 - Thermal Exponential Moving Average (EMA) Step Response & Attenuation
 - 100-Sample Boot Gyroscope Drift Calibration
 - Complementary Attitude Filter (96% Gyro + 4% Horizon)
 - Active Tumble Angular Velocity Vector Magnitude

Authoritative Specifications:
 - PROJECT.md § Feature Inventory (Features 8, 9, 14)
 - explorer_firmware_survey/handoff.md § 1.2, 1.8, 1.9
 - spec_survey_report.md § 6 (Features 4 & 5)
========================================================================================
"""

import unittest
import math
import random


class TrueRMSVibrationDSP:
    """
    Mathematical reference DSP model for MPU-6050 #1 structural flutter vibration.
    Extracts dynamic acceleration via 1st-order high-pass difference and
    computes true RMS: RMS = sqrt(EMA(dynG^2)).
    """
    GRAVITY = 9.80665

    def __init__(self, ema_alpha=0.15):
        self.alpha = ema_alpha
        self.last_ax = 0.0
        self.last_ay = 0.0
        self.last_az = self.GRAVITY
        self.ema_dyng2 = 0.0025 # initial baseline (0.05g RMS)

    def process_sample(self, ax, ay, az):
        # 1. Dynamic differential high-pass filter
        dax = ax - self.last_ax
        day = ay - self.last_ay
        daz = az - self.last_az

        self.last_ax = ax
        self.last_ay = ay
        self.last_az = az

        # 2. Dynamic G magnitude
        dynamic_g = math.sqrt(dax*dax + day*day + daz*daz) / self.GRAVITY

        # 3. True RMS via power EMA
        dyng2 = dynamic_g * dynamic_g
        self.ema_dyng2 = (self.ema_dyng2 * (1.0 - self.alpha)) + (dyng2 * self.alpha)
        return math.sqrt(self.ema_dyng2)


class ExponentialMovingAverageFilter:
    """EMA Low-pass filter for noisy analog/digital sensors."""
    def __init__(self, alpha=0.20, initial_value=25.0):
        self.alpha = alpha
        self.state = initial_value

    def filter(self, raw_value):
        self.state = (self.state * (1.0 - self.alpha)) + (raw_value * self.alpha)
        return self.state


class GyroscopeCalibrator:
    """
    100-sample stationary offset calibration for MPU-6050 #2 gyroscope.
    Computes baseline bias and applies zero-drift corrections.
    """
    CALIBRATION_SAMPLES = 100

    def __init__(self):
        self.offset_gx = 0.0
        self.offset_gy = 0.0
        self.offset_gz = 0.0
        self.calibrated = False

    def calibrate(self, sample_stream):
        """Processes 100 stationary samples and stores mean offsets."""
        sum_x = 0.0
        sum_y = 0.0
        sum_z = 0.0
        samples = list(sample_stream)[:self.CALIBRATION_SAMPLES]
        if len(samples) < self.CALIBRATION_SAMPLES:
            raise ValueError(f"Insufficient calibration samples: {len(samples)} < {self.CALIBRATION_SAMPLES}")

        for gx, gy, gz in samples:
            sum_x += gx
            sum_y += gy
            sum_z += gz

        self.offset_gx = sum_x / self.CALIBRATION_SAMPLES
        self.offset_gy = sum_y / self.CALIBRATION_SAMPLES
        self.offset_gz = sum_z / self.CALIBRATION_SAMPLES
        self.calibrated = True
        return self.offset_gx, self.offset_gy, self.offset_gz

    def correct(self, gx, gy, gz):
        if not self.calibrated:
            return gx, gy, gz
        return (gx - self.offset_gx, gy - self.offset_gy, gz - self.offset_gz)


class ComplementaryAttitudeFilter:
    """
    Sensor fusion for attitude determination:
    Combines 96% high-rate gyro integration with 4% accelerometer gravity horizon.
    """
    def __init__(self, gyro_weight=0.96):
        self.gyro_weight = gyro_weight
        self.acc_weight = 1.0 - gyro_weight
        self.pitch = 0.0 # deg
        self.roll = 0.0  # deg

    def update(self, ax, ay, az, gyro_x_dps, gyro_y_dps, dt=0.05):
        # 1. Accelerometer absolute horizon reference
        acc_roll = math.atan2(ay, az) * 180.0 / math.pi
        acc_pitch = math.atan2(-ax, math.sqrt(ay*ay + az*az)) * 180.0 / math.pi

        # 2. Complementary fusion
        self.roll = self.gyro_weight * (self.roll + gyro_x_dps * dt) + self.acc_weight * acc_roll
        self.pitch = self.gyro_weight * (self.pitch + gyro_y_dps * dt) + self.acc_weight * acc_pitch

        # 3. Constrain within physical bounds
        self.pitch = max(-90.0, min(90.0, self.pitch))
        self.roll = max(-180.0, min(180.0, self.roll))
        return self.pitch, self.roll


class TumbleRateCalculator:
    """Calculates active spacecraft tumble angular velocity."""
    @staticmethod
    def compute_from_rates(gyro_x_dps, gyro_y_dps, gyro_z_dps=0.0):
        return math.sqrt(gyro_x_dps*gyro_x_dps + gyro_y_dps*gyro_y_dps + gyro_z_dps*gyro_z_dps)

    @staticmethod
    def compute_from_euler_derivatives(d_pitch, d_roll, dt):
        if dt <= 0.0:
            return 0.0
        pitch_rate = d_pitch / dt
        roll_rate = d_roll / dt
        return math.sqrt(pitch_rate*pitch_rate + roll_rate*roll_rate)


class TestDSPAlgorithms(unittest.TestCase):
    """
    Tier 2 Unit & Algorithm Tests for DSP and Attitude Sensor Fusion.
    """

    # -------------------------------------------------------------------------
    # 1. TRUE RMS VIBRATION DSP
    # -------------------------------------------------------------------------
    def test_static_gravity_rejection(self):
        """
        DC Offset Rejection:
        A stationary satellite experiences 1g gravity (az = 9.80665 m/s^2).
        Because dAx = dAy = dAz = 0, dynamic acceleration is 0, and RMS must decay to 0.
        """
        dsp = TrueRMSVibrationDSP(ema_alpha=0.15)
        # Feed 100 stationary 1g samples
        rms_final = 0.0
        for _ in range(100):
            rms_final = dsp.process_sample(0.0, 0.0, 9.80665)

        self.assertLess(rms_final, 0.001,
                        f"Expected static 1g DC offset to produce near-zero dynamic RMS, got {rms_final}g")

    def test_pure_sinusoidal_vibration_rms(self):
        r"""
        Sinusoidal Vibration:
        $a(t) = A \sin(2\pi f t)$.
        Verify that dynamic vibration produces positive RMS proportional to amplitude.
        """
        dsp = TrueRMSVibrationDSP(ema_alpha=0.15)
        dt = 0.05 # 20 Hz sampling
        freq = 2.0 # 2 Hz oscillation
        amplitude = 2.0 # m/s^2

        rms_readings = []
        for i in range(150):
            t = i * dt
            ax = amplitude * math.sin(2 * math.pi * freq * t)
            rms = dsp.process_sample(ax, 0.0, 9.80665)
            if i > 80: # allow EMA to settle
                rms_readings.append(rms)

        avg_rms = sum(rms_readings) / len(rms_readings)
        # Dynamic acceleration of sine wave has expected RMS
        self.assertGreater(avg_rms, 0.05)
        self.assertLess(avg_rms, 0.35)

    def test_shock_impulse_and_exponential_decay(self):
        """Mechanical shock pulse causes immediate RMS spike followed by smooth exponential decay."""
        dsp = TrueRMSVibrationDSP(ema_alpha=0.15)
        # Initialize stationary
        for _ in range(30):
            dsp.process_sample(0.0, 0.0, 9.80665)

        # Single 8g shock impulse
        spike_rms = dsp.process_sample(78.4, 0.0, 9.80665)
        self.assertGreater(spike_rms, 0.50, f"Shock must produce significant RMS spike, got {spike_rms}")

        # Return to stationary: first sample settling high-pass diff, then subsequent samples decay
        dsp.process_sample(0.0, 0.0, 9.80665)
        decay_samples = [dsp.process_sample(0.0, 0.0, 9.80665) for _ in range(70)]

        # Verify strictly decreasing decay once diff clears
        for k in range(len(decay_samples) - 1):
            self.assertLessEqual(decay_samples[k+1], decay_samples[k])
        self.assertLess(decay_samples[-1], 0.05)

    # -------------------------------------------------------------------------
    # 2. THERMAL EXPONENTIAL MOVING AVERAGE (EMA)
    # -------------------------------------------------------------------------
    def test_ema_step_response_and_time_constant(self):
        """Verify EMA step response converges smoothly to step target."""
        ema = ExponentialMovingAverageFilter(alpha=0.20, initial_value=25.0)

        # Step input: 35.0 C for 30 cycles
        values = [ema.filter(35.0) for _ in range(30)]

        # Sample 1: 25*0.8 + 35*0.2 = 27.0
        self.assertAlmostEqual(values[0], 27.0, places=4)
        # Monotonically increasing
        for k in range(len(values) - 1):
            self.assertGreater(values[k+1], values[k])
        # Asymptotically converges to 35.0 C
        self.assertAlmostEqual(values[-1], 35.0, delta=0.05)

    def test_ema_white_noise_filtering(self):
        """Verify EMA reduces standard deviation of zero-mean high-frequency noise."""
        random.seed(42)
        raw_noise = [25.0 + random.uniform(-2.0, 2.0) for _ in range(500)]
        ema = ExponentialMovingAverageFilter(alpha=0.10, initial_value=25.0)
        filtered = [ema.filter(x) for x in raw_noise]

        raw_std = math.sqrt(sum((x - 25.0)**2 for x in raw_noise) / len(raw_noise))
        filtered_std = math.sqrt(sum((x - 25.0)**2 for x in filtered[50:]) / len(filtered[50:]))

        self.assertLess(filtered_std, raw_std * 0.5,
                        "EMA filter must reduce noise variance by over 50%")

    # -------------------------------------------------------------------------
    # 3. 100-SAMPLE BOOT GYRO CALIBRATION
    # -------------------------------------------------------------------------
    def test_gyro_stationary_offset_calibration(self):
        """
        Verify that 100-sample calibration eliminates hardware DC bias.
        """
        calibrator = GyroscopeCalibrator()
        random.seed(123)

        # Synthesize 100 stationary samples with real-world sensor bias (2.5 dps X, -1.8 dps Y, 0.9 dps Z)
        bias_x, bias_y, bias_z = 2.50, -1.80, 0.90
        stationary_stream = [
            (bias_x + random.gauss(0, 0.05),
             bias_y + random.gauss(0, 0.05),
             bias_z + random.gauss(0, 0.05))
            for _ in range(100)
        ]

        off_x, off_y, off_z = calibrator.calibrate(stationary_stream)

        self.assertAlmostEqual(off_x, bias_x, delta=0.03)
        self.assertAlmostEqual(off_y, bias_y, delta=0.03)
        self.assertAlmostEqual(off_z, bias_z, delta=0.03)

        # Apply calibration to new reading
        raw_sample = (bias_x + 0.01, bias_y - 0.02, bias_z + 0.01)
        corr_x, corr_y, corr_z = calibrator.correct(*raw_sample)

        self.assertAlmostEqual(corr_x, 0.0, delta=0.05)
        self.assertAlmostEqual(corr_y, 0.0, delta=0.05)
        self.assertAlmostEqual(corr_z, 0.0, delta=0.05)

    def test_uncalibrated_vs_calibrated_integration_drift(self):
        """
        Demonstrate that uncalibrated gyro causes linear divergence over 100 seconds,
        while calibrated gyro maintains zero drift.
        """
        calibrator = GyroscopeCalibrator()
        bias_x = 3.0 # 3 deg/sec offset
        stream = [(bias_x, 0.0, 0.0) for _ in range(100)]
        calibrator.calibrate(stream)

        dt = 0.05
        uncalibrated_angle = 0.0
        calibrated_angle = 0.0

        for _ in range(200): # 10 seconds (200 * 50ms)
            # uncalibrated integration
            uncalibrated_angle += bias_x * dt
            # calibrated integration
            cx, _, _ = calibrator.correct(bias_x, 0.0, 0.0)
            calibrated_angle += cx * dt

        self.assertAlmostEqual(uncalibrated_angle, 30.0, delta=0.1) # Drifted by 30 degrees!
        self.assertAlmostEqual(calibrated_angle, 0.0, delta=0.0001)  # Stays at 0.0 degrees!

    # -------------------------------------------------------------------------
    # 4. COMPLEMENTARY ATTITUDE FILTER
    # -------------------------------------------------------------------------
    def test_attitude_filter_static_horizontal_equilibrium(self):
        """Horizontal satellite (ax=0, ay=0, az=9.81, zero gyro rate) yields 0 pitch and 0 roll."""
        filter_att = ComplementaryAttitudeFilter(gyro_weight=0.96)
        for _ in range(50):
            pitch, roll = filter_att.update(0.0, 0.0, 9.80665, 0.0, 0.0, dt=0.05)

        self.assertAlmostEqual(pitch, 0.0, delta=0.1)
        self.assertAlmostEqual(roll, 0.0, delta=0.1)

    def test_attitude_filter_pitch_tilt(self):
        """Tilted 30 degrees pitch yields convergent 30 degree pitch output."""
        filter_att = ComplementaryAttitudeFilter(gyro_weight=0.96)
        # 30 deg pitch: ax = -9.81 * sin(30) = -4.903, az = 9.81 * cos(30) = 8.492
        ax = -9.80665 * math.sin(math.radians(30))
        az = 9.80665 * math.cos(math.radians(30))

        final_pitch = 0.0
        for _ in range(150):
            final_pitch, _ = filter_att.update(ax, 0.0, az, 0.0, 0.0, dt=0.05)

        self.assertAlmostEqual(final_pitch, 30.0, delta=0.5)

    def test_attitude_boundary_clamping(self):
        """Attitude filter enforces safety limits: Pitch in [-90, 90], Roll in [-180, 180]."""
        filter_att = ComplementaryAttitudeFilter(gyro_weight=0.96)
        filter_att.pitch = 89.0
        # Continuous high pitch rate
        for _ in range(50):
            pitch, roll = filter_att.update(0.0, 0.0, 9.81, 0.0, 100.0, dt=0.05)

        self.assertLessEqual(pitch, 90.0)
        self.assertGreaterEqual(pitch, -90.0)

    # -------------------------------------------------------------------------
    # 5. TUMBLE RATE CALCULATION
    # -------------------------------------------------------------------------
    def test_tumble_rate_stationary_vs_active(self):
        """Verify tumble rate is ~0 dps when stationary and matches 3D angular rate when tumbling."""
        calc = TumbleRateCalculator

        rate_stationary = calc.compute_from_rates(0.0, 0.0, 0.0)
        self.assertEqual(rate_stationary, 0.0)

        # 3-axis rotation (30 dps X, 40 dps Y, 0 dps Z -> 50 dps magnitude)
        rate_tumble = calc.compute_from_rates(30.0, 40.0, 0.0)
        self.assertAlmostEqual(rate_tumble, 50.0, places=4)

        # Euler derivative method: 2 degrees over 50ms = 40 dps
        rate_euler = calc.compute_from_euler_derivatives(d_pitch=2.0, d_roll=0.0, dt=0.05)
        self.assertAlmostEqual(rate_euler, 40.0, places=4)


if __name__ == '__main__':
    unittest.main()
