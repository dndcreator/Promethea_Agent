"""
?
?GatewayIntegration 
"""
import os
import tempfile
import unittest
from pathlib import Path

from computer import BrowserController, ScreenController, FileSystemController, ProcessController
from gateway_integration import GatewayIntegration


class TestComputerControllers(unittest.IsolatedAsyncioTestCase):
    """TODO: add docstring."""
    
    async def test_controllers_construct(self):
        """TODO: add docstring."""
        BrowserController()
        ScreenController()
        FileSystemController()
        ProcessController()

    async def test_filesystem_read_write_delete(self):
        """TODO: add docstring."""
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
        """TODO: add docstring."""
        pc = ProcessController()
        await pc.initialize()

        r = await pc.execute("list", {})
        self.assertTrue(r.success)
        self.assertIsInstance(r.result, list)

        await pc.cleanup()

    async def test_browser_live_optional(self):
        """TODO: add docstring."""
        if os.getenv("PROMETHEA_LIVE_TEST") != "1":
            self.skipTest("set PROMETHEA_LIVE_TEST=1 to run live browser tests")

        bc = BrowserController()
        ok = await bc.initialize()
        if not ok:
            self.skipTest("Browser not available")
        await bc.cleanup()

    async def test_screen_live_optional(self):
        """TODO: add docstring."""
        if os.getenv("PROMETHEA_LIVE_TEST") != "1":
            self.skipTest("set PROMETHEA_LIVE_TEST=1 to run live screen tests")

        sc = ScreenController()
        ok = await sc.initialize()
        if not ok:
            self.skipTest("Screen controller not available")
        await sc.cleanup()


class TestComputerIntegration(unittest.IsolatedAsyncioTestCase):
    """TODO: add docstring."""
    
    async def test_controllers_exist(self):
        """TODO: add docstring."""
        gi = GatewayIntegration("gateway_config.json")
        self.assertIn("browser", gi.computer_controllers)
        self.assertIn("screen", gi.computer_controllers)
        self.assertIn("filesystem", gi.computer_controllers)
        self.assertIn("process", gi.computer_controllers)

    async def test_unknown_capability(self):
        """TODO: add docstring."""
        gi = GatewayIntegration("gateway_config.json")
        result = await gi.execute_computer_action("unknown_capability", "some_action", {})
        self.assertFalse(result.success)
        self.assertIn("Unknown capability", result.error)

    async def test_uninitialized_controller(self):
        """TODO: add docstring."""
        gi = GatewayIntegration("gateway_config.json")
        result = await gi.execute_computer_action("browser", "navigate", {"url": "https://example.com"})
        self.assertFalse(result.success)
        self.assertIn("not initialized", result.error)


if __name__ == "__main__":
    unittest.main()

