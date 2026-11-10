#!/usr/bin/env python3
"""
========================================================================================
STELLARSENSE E2E AUTOMATED TEST RUNNER & MOCK SERIAL TELEMETRY FEEDER
File: tests/e2e_test_runner.py

Features:
 - Automated discovery & execution of Tiers 1 to 4 test suites
 - Filtering by Tier (--tier 1..4) or Suite name (--suite <name>)
 - Rich ANSI terminal dashboard with test metrics & execution time
 - Integrated Mock Serial Telemetry Feeder for Ground Station / Web Serial testing
 - Deterministic process exit code (0 for PASS, 1 for FAIL)

Usage:
  python3 tests/e2e_test_runner.py
  python3 tests/e2e_test_runner.py --verbose
  python3 tests/e2e_test_runner.py --tier 2
  python3 tests/e2e_test_runner.py --suite fdir
  python3 tests/e2e_test_runner.py --mock-serial-feed 20 600
========================================================================================
"""

import sys
import os
import time
import argparse
import unittest
import json
import math

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ANSI Colors for Terminal Output
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_GREEN = "\033[32m"
CLR_RED = "\033[31m"
CLR_YELLOW = "\033[33m"
CLR_CYAN = "\033[36m"
CLR_BLUE = "\033[34m"
CLR_MAGENTA = "\033[35m"

SUITE_CATALOG = {
    "schema": {
        "tier": 1,
        "name": "Tier 1: Telemetry Schema & Contract Validation",
        "module": "tests.test_telemetry_schema",
        "file": "test_telemetry_schema.py"
    },
    "fdir": {
        "tier": 2,
        "name": "Tier 2: FDIR State Machine, Deadbands & Debounce",
        "module": "tests.test_fdir_state_machine",
        "file": "test_fdir_state_machine.py"
    },
    "dsp": {
        "tier": 2,
        "name": "Tier 2: DSP Algorithms & Attitude Fusion",
        "module": "tests.test_dsp_algorithms",
        "file": "test_dsp_algorithms.py"
    },
    "framing": {
        "tier": 3,
        "name": "Tier 3: Serial Framing & Protocol Robustness",
        "module": "tests.test_serial_framing",
        "file": "test_serial_framing.py"
    },
    "scenarios": {
        "tier": 4,
        "name": "Tier 4: Real-World Flight Mission Scenarios",
        "module": "tests.test_scenarios",
        "file": "test_scenarios.py"
    },
    "adversarial": {
        "tier": 5,
        "name": "Tier 5: Adversarial Stress & Coverage Hardening",
        "module": "tests.test_tier5_adversarial",
        "file": "test_tier5_adversarial.py"
    },
    "gemma": {
        "tier": 6,
        "name": "Tier 6: Gemma 4 Model Harness & Agent Skill Standard",
        "module": "tests.test_gemma_harness",
        "file": "test_gemma_harness.py"
    }
}


class StellarSenseTestResult(unittest.TestResult):
    """Custom TestResult collecting granular timing and pass/fail metrics."""

    def __init__(self, stream=None, descriptions=None, verbosity=1):
        super().__init__(stream, descriptions, verbosity)
        self.test_records = []
        self._current_test_start = 0.0

    def startTest(self, test):
        super().startTest(test)
        self._current_test_start = time.perf_counter()

    def addSuccess(self, test):
        super().addSuccess(test)
        elapsed = (time.perf_counter() - self._current_test_start) * 1000
        self.test_records.append({
            "test": str(test),
            "status": "PASS",
            "elapsed_ms": elapsed,
            "error": None
        })

    def addFailure(self, test, err):
        super().addFailure(test, err)
        elapsed = (time.perf_counter() - self._current_test_start) * 1000
        self.test_records.append({
            "test": str(test),
            "status": "FAIL",
            "elapsed_ms": elapsed,
            "error": self._exc_info_to_string(err, test)
        })

    def addError(self, test, err):
        super().addError(test, err)
        elapsed = (time.perf_counter() - self._current_test_start) * 1000
        self.test_records.append({
            "test": str(test),
            "status": "ERROR",
            "elapsed_ms": elapsed,
            "error": self._exc_info_to_string(err, test)
        })


def print_banner():
    banner = f"""{CLR_CYAN}{CLR_BOLD}
╔════════════════════════════════════════════════════════════════════════════╗
║    🛰️  STELLARSENSE MISSION ASSURANCE // E2E TEST RUNNER HARNESS        ║
║         Automated Verification of Satellite OBC & Ground Subsystems        ║
╚════════════════════════════════════════════════════════════════════════════╝{CLR_RESET}"""
    print(banner)


def run_suites(target_tier=None, target_suite=None, verbose=False):
    """Executes selected test suites and produces execution metrics."""
    print_banner()

    suites_to_run = {}
    for key, info in SUITE_CATALOG.items():
        if target_suite and target_suite.lower() not in key:
            continue
        if target_tier and info["tier"] != target_tier:
            continue
        suites_to_run[key] = info

    if not suites_to_run:
        print(f"{CLR_RED}No matching test suites found for tier={target_tier}, suite={target_suite}{CLR_RESET}")
        return 1

    print(f"{CLR_BOLD}Target Scope:{CLR_RESET} {len(suites_to_run)} test suites selected across Tiers 1-6.\n")

    loader = unittest.TestLoader()
    overall_start = time.perf_counter()
    suite_metrics = []
    all_passed = True
    total_tests = 0
    total_passed = 0
    total_failed = 0
    total_errors = 0

    for key, info in suites_to_run.items():
        print(f"─── {CLR_BOLD}[TIER {info['tier']}]{CLR_RESET} {CLR_CYAN}{info['name']}{CLR_RESET} ({info['file']})")
        suite = loader.loadTestsFromName(info["module"])
        result = StellarSenseTestResult(verbosity=2 if verbose else 1)

        suite_start = time.perf_counter()
        suite.run(result)
        suite_duration = (time.perf_counter() - suite_start) * 1000

        n_pass = len([r for r in result.test_records if r["status"] == "PASS"])
        n_fail = len(result.failures)
        n_err = len(result.errors)
        total_tests += result.testsRun
        total_passed += n_pass
        total_failed += n_fail
        total_errors += n_err

        status_str = f"{CLR_GREEN}PASSED{CLR_RESET}" if (n_fail == 0 and n_err == 0) else f"{CLR_RED}FAILED{CLR_RESET}"
        if n_fail > 0 or n_err > 0:
            all_passed = False

        print(f"    Results: {status_str} | Tests: {result.testsRun} | Passed: {n_pass} | Failed: {n_fail} | Errors: {n_err} | Duration: {suite_duration:.1f}ms")

        if verbose or n_fail > 0 or n_err > 0:
            for record in result.test_records:
                mark = f"{CLR_GREEN}✓{CLR_RESET}" if record["status"] == "PASS" else f"{CLR_RED}✗{CLR_RESET}"
                test_name = record["test"].split()[0]
                print(f"      {mark} {test_name} ({record['elapsed_ms']:.2f}ms)")
                if record["error"]:
                    print(f"\n{CLR_RED}--- Traceback: ---{CLR_RESET}\n{record['error']}")

        suite_metrics.append({
            "key": key,
            "tier": info["tier"],
            "name": info["name"],
            "tests": result.testsRun,
            "pass": n_pass,
            "fail": n_fail,
            "err": n_err,
            "time_ms": suite_duration
        })
        print()

    total_time_ms = (time.perf_counter() - overall_start) * 1000

    # Summary Dashboard
    print(f"{CLR_BOLD}════════════════════════════════════════════════════════════════════════════{CLR_RESET}")
    print(f"{CLR_BOLD}                           EXECUTION SUMMARY REPORT                        {CLR_RESET}")
    print(f"{CLR_BOLD}════════════════════════════════════════════════════════════════════════════{CLR_RESET}")
    print(f" Total Test Cases Run:   {CLR_BOLD}{total_tests}{CLR_RESET}")
    print(f" Passing Tests:          {CLR_GREEN}{CLR_BOLD}{total_passed}{CLR_RESET}")
    print(f" Failing Tests:          {CLR_RED}{CLR_BOLD}{total_failed}{CLR_RESET}")
    print(f" Errors:                 {CLR_RED}{CLR_BOLD}{total_errors}{CLR_RESET}")
    print(f" Total Execution Time:   {total_time_ms:.2f} ms")
    pass_pct = (total_passed / total_tests * 100) if total_tests > 0 else 0
    print(f" Overall Pass Rate:      {CLR_GREEN if pass_pct == 100 else CLR_RED}{pass_pct:.1f}%{CLR_RESET}")
    print(f"{CLR_BOLD}════════════════════════════════════════════════════════════════════════════{CLR_RESET}")

    tier_coverage = {}
    for sm in suite_metrics:
        tier_coverage[sm["tier"]] = tier_coverage.get(sm["tier"], 0) + sm["tests"]

    print(f"{CLR_BOLD}Tier Coverage Breakdown:{CLR_RESET}")
    for t in sorted(tier_coverage.keys()):
        print(f"  • Tier {t}: {tier_coverage[t]} test assertions verified")

    print()
    if all_passed:
        print(f"{CLR_GREEN}{CLR_BOLD}>>> ALL TEST SUITES PASSED — STELLARSENSE READY FOR FLIGHT / DEMO <<<{CLR_RESET}\n")
        return 0
    else:
        print(f"{CLR_RED}{CLR_BOLD}>>> FAILURES DETECTED IN TEST SUITES — PLEASE ESCALATE DEFECTS <<<{CLR_RESET}\n")
        return 1


def mock_serial_feed(count=20, interval_ms=600):
    """
    Simulates the ESP32 Ground Station sending real-time enriched JSON frames
    to stdout or a virtual serial port for live Web Serial API dashboard validation.
    """
    print(f"{CLR_YELLOW}=== STARTING MOCK SERIAL TELEMETRY STREAM ({count} frames @ {interval_ms}ms) ==={CLR_RESET}", file=sys.stderr)
    boot_frame = {"system": "GROUND_STATION", "status": "BOOT_OK", "freq_mhz": 433.0, "baud": 115200}
    print(json.dumps(boot_frame), flush=True)
    time.sleep(0.5)

    for pkt in range(1, count + 1):
        met = pkt
        # Generate realistic orbital sinusoidal harmonics
        temp = 27.2 + math.sin(met / 10.0) * 1.5
        volt = 5.02 + math.sin(met / 14.0) * 0.08
        curr = 310.0 + math.cos(met / 8.0) * 18.0
        pwr = volt * curr
        vib = 0.062 + abs(math.sin(met / 4.0)) * 0.035
        pitch = math.sin(met / 6.0) * 12.0
        roll = math.cos(met / 8.0) * 8.0

        fdir = "NOMINAL"
        if temp >= 38.0 or volt <= 4.20 or vib >= 0.70:
            fdir = "CRITICAL"
        elif temp >= 33.0 or volt <= 4.60 or vib >= 0.25:
            fdir = "CAUTION"

        frame = {
            "pkt": pkt,
            "met": met,
            "temp": round(temp, 2),
            "volt": round(volt, 2),
            "curr": round(curr, 1),
            "pwr": round(pwr, 1),
            "vib": round(vib, 3),
            "pitch": round(pitch, 1),
            "roll": round(roll, 1),
            "fdir": fdir,
            "rssi": -48,
            "snr": 9.5,
            "rx_count": pkt
        }
        print(json.dumps(frame), flush=True)
        time.sleep(interval_ms / 1000.0)

    print(f"{CLR_YELLOW}=== MOCK SERIAL TELEMETRY STREAM COMPLETED ==={CLR_RESET}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="StellarSense E2E Test Suite Runner")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3, 4, 5], help="Filter tests by Tier (1..5)")
    parser.add_argument("--suite", type=str, help="Run specific suite (schema, fdir, dsp, framing, scenarios, adversarial)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print verbose test execution traces")
    parser.add_argument("--mock-serial-feed", nargs="?", const="20", type=int, help="Run mock serial telemetry generator (count)")
    parser.add_argument("--interval", type=int, default=600, help="Interval in ms for mock serial feed (default: 600ms)")

    args = parser.parse_args()

    if args.mock_serial_feed is not None:
        mock_serial_feed(count=args.mock_serial_feed, interval_ms=args.interval)
        return 0

    exit_code = run_suites(target_tier=args.tier, target_suite=args.suite, verbose=args.verbose)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
