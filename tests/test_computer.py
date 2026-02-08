"""
电脑控制测试（合并版）
测试电脑控制器的基本功能和 GatewayIntegration 集成
"""
import os
import tempfile
import unittest
from pathlib import Path

from computer import BrowserController, ScreenController, FileSystemController, ProcessController
from gateway_integration import GatewayIntegration


class TestComputerControllers(unittest.IsolatedAsyncioTestCase):
    """电脑控制器单元测试"""
    
    async def test_controllers_construct(self):
        """测试控制器可以正常构造"""
        BrowserController()
        ScreenController()
        FileSystemController()
        ProcessController()

    async def test_filesystem_read_write_delete(self):
        """测试文件系统读写删除"""
        fs = FileSystemController()
        await fs.initialize()

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "hello.txt"
            content = "hello"

            r1 = await fs.execute("write", {"path": str(p), "content": content})
            self.assertTrue(r1.success)

            r2 = await fs.execute("read", {"path": str(p)})
            self.assertTrue(r2.success)
            self.assertEqual(r2.result, content)

            r3 = await fs.execute("delete", {"path": str(p)})
            self.assertTrue(r3.success)

        await fs.cleanup()

    async def test_process_list_is_safe(self):
        """测试进程列表查询（安全操作）"""
        pc = ProcessController()
        await pc.initialize()

        r = await pc.execute("list", {})
        self.assertTrue(r.success)
        self.assertIsInstance(r.result, list)

        await pc.cleanup()

    async def test_browser_live_optional(self):
        """测试浏览器控制器（需要 LIVE 模式）"""
        if os.getenv("PROMETHEA_LIVE_TEST") != "1":
            self.skipTest("set PROMETHEA_LIVE_TEST=1 to run live browser tests")

        bc = BrowserController()
        ok = await bc.initialize()
        if not ok:
            self.skipTest("Browser not available")
        await bc.cleanup()

    async def test_screen_live_optional(self):
        """测试屏幕控制器（需要 LIVE 模式）"""
        if os.getenv("PROMETHEA_LIVE_TEST") != "1":
            self.skipTest("set PROMETHEA_LIVE_TEST=1 to run live screen tests")

        sc = ScreenController()
        ok = await sc.initialize()
        if not ok:
            self.skipTest("Screen controller not available")
        await sc.cleanup()


class TestComputerIntegration(unittest.IsolatedAsyncioTestCase):
    """电脑控制集成测试（GatewayIntegration）"""
    
    async def test_controllers_exist(self):
        """测试 GatewayIntegration 中的控制器存在"""
        gi = GatewayIntegration("gateway_config.json")
        self.assertIn("browser", gi.computer_controllers)
        self.assertIn("screen", gi.computer_controllers)
        self.assertIn("filesystem", gi.computer_controllers)
        self.assertIn("process", gi.computer_controllers)

    async def test_unknown_capability(self):
        """测试未知能力返回错误"""
        gi = GatewayIntegration("gateway_config.json")
        result = await gi.execute_computer_action("unknown_capability", "some_action", {})
        self.assertFalse(result.success)
        self.assertIn("Unknown capability", result.error)

    async def test_uninitialized_controller(self):
        """测试未初始化的控制器返回错误"""
        gi = GatewayIntegration("gateway_config.json")
        result = await gi.execute_computer_action("browser", "navigate", {"url": "https://example.com"})
        self.assertFalse(result.success)
        self.assertIn("not initialized", result.error)


if __name__ == "__main__":
    unittest.main()
