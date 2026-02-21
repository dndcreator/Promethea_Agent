"""
?- ?

:
  python tests/run_all_tests.py              # TODO: comment cleaned
  python tests/run_all_tests.py --live       # TODO: comment cleaned
  python tests/run_all_tests.py --file test_gateway_basic.py  # TODO: comment cleaned
  python tests/run_all_tests.py --verbose     # TODO: comment cleaned
"""

import os
import sys
import argparse
import unittest
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Promethea Agent ?)
    parser.add_argument("--live", action="store_true", help="?Neo4j?)
    parser.add_argument("--file", type=str, help="")
    parser.add_argument("--verbose", "-v", action="store_true", help="")
    parser.add_argument("--pattern", type=str, default="test_*.py", help="")
    
    args = parser.parse_args()
    
    root = Path(__file__).resolve().parent.parent
    tests_dir = root / "tests"
    
    print("=" * 80)
    print("Promethea Agent - Test Runner")
    print("=" * 80)
    
    # TODO: comment cleaned
    if args.live:
        os.environ["PROMETHEA_LIVE_TEST"] = "1"
        print("Mode: LIVE ()")
    else:
        os.environ.pop("PROMETHEA_LIVE_TEST", None)
        print("Mode: UNIT (?")
    
    # TODO: comment cleaned
    if args.file:
        # TODO: comment cleaned
        test_file = tests_dir / args.file
        if not test_file.exists():
            print(f": ? {test_file}")
            return 1
        suite = unittest.defaultTestLoader.loadTestsFromName(
            f"tests.{args.file.replace('.py', '').replace('/', '.')}"
        )
    else:
        # TODO: comment cleaned
        suite = unittest.defaultTestLoader.discover(
            str(tests_dir),
            pattern=args.pattern
        )
    
    verbosity = 2 if args.verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    
    # TODO: comment cleaned
    print("\n" + "=" * 80)
    if result.wasSuccessful():
        print(f"? ({result.testsRun} ?")
        return 0
    else:
        print(f"?: {len(result.failures)} ? {len(result.errors)} ?)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

