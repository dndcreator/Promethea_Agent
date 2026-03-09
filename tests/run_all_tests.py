"""Unified test runner for local development.

Examples:
  python tests/run_all_tests.py
  python tests/run_all_tests.py --live
  python tests/run_all_tests.py --file test_gateway_basic.py
  python tests/run_all_tests.py --pattern "test_memory_*.py"
  python tests/run_all_tests.py --coverage
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _build_pytest_args(args: argparse.Namespace, root: Path) -> list[str]:
    test_target: str
    if args.file:
        target = (root / "tests" / args.file).resolve()
        if not target.exists():
            raise FileNotFoundError(f"test file not found: {target}")
        test_target = str(target)
    else:
        test_target = str((root / "tests").resolve())

    cmd = [sys.executable, "-m", "pytest", test_target]

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
    print("command:", " ".join(cmd))

    result = subprocess.run(cmd, cwd=str(root), check=False)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
