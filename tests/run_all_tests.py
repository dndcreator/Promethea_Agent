"""Unified test runner for local development and release audit.

Examples:
  python tests/run_all_tests.py
  python tests/run_all_tests.py --suite business
  python tests/run_all_tests.py --live --suite full
  python tests/run_all_tests.py --file test_gateway_basic.py
  python tests/run_all_tests.py --pattern "memory and not live"
  python tests/run_all_tests.py --coverage
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


SUITE_FILES: dict[str, list[str]] = {
    "smoke": [
        "tests/test_mvp_business_smoke.py",
        "tests/test_business_journeys.py",
    ],
    "core": [
        "tests/test_conversation_pipeline_staging.py",
        "tests/test_reasoning_service.py",
        "tests/test_tool_service.py",
        "tests/test_workflow_engine_mvp.py",
    ],
    "contracts": [
        "tests/test_protocol_surface_contracts.py",
        "tests/test_http_contract_registry.py",
        "tests/test_config_protocol.py",
        "tests/test_gateway_tools_list_contract.py",
        "tests/test_gateway_ws_error_model.py",
        "tests/test_http_dispatcher_error_model.py",
    ],
    "business": [
        "tests/test_business_journeys.py",
        "tests/test_mvp_business_smoke.py",
        "tests/test_official_tools.py",
        "tests/test_voice_routes.py",
        "tests/test_ops_readiness.py",
    ],
    "business_plus": [
        "tests/test_business_journeys.py",
        "tests/test_mvp_business_smoke.py",
        "tests/test_official_tools.py",
        "tests/test_voice_routes.py",
        "tests/test_ops_readiness.py",
        "tests/business_plus/test_business_plus_flows.py",
    ],
    "full": [
        "tests",
    ],
}


def _build_pytest_args(args: argparse.Namespace, root: Path) -> list[str]:
    if args.file:
        target = (root / "tests" / args.file).resolve()
        if not target.exists():
            raise FileNotFoundError(f"test file not found: {target}")
        targets = [str(target)]
    else:
        raw_targets = SUITE_FILES.get(args.suite, SUITE_FILES["full"])
        targets = [str((root / rel).resolve()) for rel in raw_targets]

    tmp_root = root / ".tmp" / "pytest-runtime" / "runner"
    tmp_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_tmp = tmp_root / f"run-{stamp}-{os.getpid()}"
    run_tmp.mkdir(parents=True, exist_ok=True)

    # Force pytest temp artifacts to stay inside repository workspace.
    os.environ["TEMP"] = str(run_tmp)
    os.environ["TMP"] = str(run_tmp)
    os.environ["TMPDIR"] = str(run_tmp)
    os.environ["PYTEST_DEBUG_TEMPROOT"] = str(run_tmp)
    os.environ["PROMETHEA_TEST_TMP_ROOT"] = str(root / ".tmp" / "pytest-runtime")

    cmd = [sys.executable, "-m", "pytest", "--basetemp", str(run_tmp / "base"), *targets]

    if args.pattern:
        cmd.extend(["-k", args.pattern])

    if args.coverage:
        cmd.extend(["--cov=.", "--cov-report=term-missing", "--cov-report=xml"])

    if args.verbose:
        cmd.append("-vv")
    else:
        cmd.append("-q")

    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="Promethea Agent test runner")
    parser.add_argument("--live", action="store_true", help="run live integration tests")
    parser.add_argument("--file", type=str, help="run a single test file under tests/")
    parser.add_argument(
        "--suite",
        type=str,
        choices=sorted(SUITE_FILES.keys()),
        default="full",
        help="predefined test suite profile",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="",
        help="pytest -k expression for selecting tests",
    )
    parser.add_argument("--coverage", action="store_true", help="enable coverage report")
    parser.add_argument("--verbose", "-v", action="store_true", help="verbose pytest output")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent

    if args.live:
        os.environ["PROMETHEA_LIVE_TEST"] = "1"
    else:
        os.environ.pop("PROMETHEA_LIVE_TEST", None)

    try:
        cmd = _build_pytest_args(args, root)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    print("=" * 80)
    print("Promethea Agent - Test Runner")
    print("=" * 80)
    print(f"mode: {'LIVE' if args.live else 'UNIT'}")
    print(f"suite: {args.suite}")
    print("command:", " ".join(cmd))

    result = subprocess.run(cmd, cwd=str(root), check=False)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
