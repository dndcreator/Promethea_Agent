"""
测试运行器 - 简洁易用

用法:
  python tests/run_all_tests.py              # 运行所有单元测试
  python tests/run_all_tests.py --live       # 运行集成测试（需要服务器）
  python tests/run_all_tests.py --file test_gateway_basic.py  # 运行特定文件
  python tests/run_all_tests.py --verbose     # 详细输出
"""

import os
import sys
import argparse
import unittest
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Promethea Agent 测试运行器")
    parser.add_argument("--live", action="store_true", help="运行集成测试（需要服务器和 Neo4j）")
    parser.add_argument("--file", type=str, help="运行特定测试文件")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--pattern", type=str, default="test_*.py", help="测试文件模式")
    
    args = parser.parse_args()
    
    root = Path(__file__).resolve().parent.parent
    tests_dir = root / "tests"
    
    print("=" * 80)
    print("Promethea Agent - Test Runner")
    print("=" * 80)
    
    # 设置环境变量
    if args.live:
        os.environ["PROMETHEA_LIVE_TEST"] = "1"
        print("Mode: LIVE (集成测试，需要运行服务器)")
    else:
        os.environ.pop("PROMETHEA_LIVE_TEST", None)
        print("Mode: UNIT (单元测试，默认)")
    
    # 运行测试
    if args.file:
        # 运行特定文件
        test_file = tests_dir / args.file
        if not test_file.exists():
            print(f"错误: 测试文件不存在: {test_file}")
            return 1
        suite = unittest.defaultTestLoader.loadTestsFromName(
            f"tests.{args.file.replace('.py', '').replace('/', '.')}"
        )
    else:
        # 发现所有测试
        suite = unittest.defaultTestLoader.discover(
            str(tests_dir),
            pattern=args.pattern
        )
    
    verbosity = 2 if args.verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    
    # 输出摘要
    print("\n" + "=" * 80)
    if result.wasSuccessful():
        print(f"✓ 所有测试通过 ({result.testsRun} 个测试)")
        return 0
    else:
        print(f"✗ 测试失败: {len(result.failures)} 个失败, {len(result.errors)} 个错误")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
