"""Computer controller and gateway integration tests."""

import os
import shutil
import unittest
from pathlib import Path

from computer import BrowserController, FileSystemController, ProcessController, ScreenController
from agentkit.security.sandbox import SandboxPolicy
from gateway_integration import GatewayIntegration


class TestComputerControllers(unittest.IsolatedAsyncioTestCase):
    async def test_controllers_construct(self):
        BrowserController()
        ScreenController()
        FileSystemController()
        ProcessController()

    async def test_filesystem_read_write_delete(self):
        fs = FileSystemController()
        await fs.initialize()

        local_tmp = Path(os.environ.get("PROMETHEA_TEST_TMP_ROOT", ".tmp/pytest-runtime")) / "tmp_fs_tests"
        local_tmp.mkdir(parents=True, exist_ok=True)
        case_dir = local_tmp / "case"
        case_dir.mkdir(parents=True, exist_ok=True)

        try:
            p = case_dir / "hello.txt"
            content = "hello"

            r1 = await fs.execute("write", {"path": str(p), "content": content})
            self.assertTrue(r1.success)

            r2 = await fs.execute("read", {"path": str(p)})
            self.assertTrue(r2.success)
            self.assertEqual(r2.result, content)

            r3 = await fs.execute("delete", {"path": str(p)})
            self.assertTrue(r3.success)
        finally:
            shutil.rmtree(case_dir, ignore_errors=True)

        await fs.cleanup()

    async def test_process_list_is_safe(self):
        pc = ProcessController()
        await pc.initialize()

        r = await pc.execute("list", {})
        self.assertTrue(r.success)
        self.assertIsInstance(r.result, list)

        await pc.cleanup()

    async def test_direct_process_execution_is_fail_closed(self):
        pc = ProcessController()
        pc.is_initialized = True
        pc.sandbox = SandboxPolicy(command_mode="deny")

        result = await pc.execute("run", {"command": "python -V"})

        self.assertFalse(result.success)
        self.assertIn("host process execution disabled", result.error)

    async def test_process_get_never_mutates_tracked_process(self):
        class _Tracked:
            def kill(self):
                raise AssertionError("get must not kill a process")

            def terminate(self):
                raise AssertionError("get must not terminate a process")

        pc = ProcessController()
        pc.is_initialized = True
        pc.sandbox = SandboxPolicy()
        pc.active_processes[12345] = _Tracked()

        await pc.execute("get", {"pid": 12345})

        self.assertIn(12345, pc.active_processes)

    async def test_direct_desktop_input_is_observation_only(self):
        sc = ScreenController()
        sc.is_initialized = True
        sc.sandbox = SandboxPolicy(desktop_mode="observe_only")

        result = await sc.execute("click", {"x": 1, "y": 1})

        self.assertFalse(result.success)
        self.assertIn("host desktop input is disabled", result.error)

    async def test_direct_browser_call_cannot_bypass_network_policy(self):
        bc = BrowserController()
        bc.is_initialized = True
        bc.sandbox = SandboxPolicy()

        result = await bc.execute("navigate", {"url": "http://127.0.0.1/private"})

        self.assertFalse(result.success)
        self.assertIn("private/loopback host blocked", result.error)

    async def test_browser_live_optional(self):
        if os.getenv("PROMETHEA_LIVE_TEST") != "1":
            self.skipTest("set PROMETHEA_LIVE_TEST=1 to run live browser tests")

        bc = BrowserController()
        ok = await bc.initialize()
        if not ok:
            self.skipTest("Browser not available")
        await bc.cleanup()

    async def test_screen_live_optional(self):
        if os.getenv("PROMETHEA_LIVE_TEST") != "1":
            self.skipTest("set PROMETHEA_LIVE_TEST=1 to run live screen tests")

        sc = ScreenController()
        ok = await sc.initialize()
        if not ok:
            self.skipTest("Screen controller not available")
        await sc.cleanup()


class TestComputerIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_controllers_exist(self):
        gi = GatewayIntegration("gateway_config.json")
        self.assertIn("browser", gi.computer_controllers)
        self.assertIn("screen", gi.computer_controllers)
        self.assertIn("filesystem", gi.computer_controllers)
        self.assertIn("process", gi.computer_controllers)

    async def test_unknown_capability(self):
        gi = GatewayIntegration("gateway_config.json")
        from computer.execution_context import bind_workspace
        from gateway.capability_service import CapabilityService
        from gateway.workspace_service import WorkspaceHandle

        service = CapabilityService(computer_runtime=gi.computer_runtime)
        handle = WorkspaceHandle(workspace_id="test", user_id="test", root_path=os.getcwd())
        with bind_workspace(handle):
            result = await service.execute_computer_action("unknown_capability", "some_action", {})
        self.assertFalse(result.success)
        self.assertIn("Unknown capability", result.error)
        await gi.computer_runtime.close()


if __name__ == "__main__":
    unittest.main()
