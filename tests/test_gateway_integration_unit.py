import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from channels.registry import ChannelRegistry
from core.plugins.loader import load_promethea_plugins, PluginLoadOptions
from gateway_integration import GatewayIntegration


class DummyGatewayServer:
    def __init__(self):
        self.channels = {}


class TestGatewayIntegrationUnit(unittest.IsolatedAsyncioTestCase):
    async def test_init_channels_registers_from_plugin_registry(self):
        workspace_dir = str(Path(__file__).resolve().parents[1])

        # Load only web channel plugin
        load_promethea_plugins(
            PluginLoadOptions(
                workspace_dir=workspace_dir,
                extensions_dir="extensions",
                config={
                    "plugins": {
                        "web": {"enabled": True, "config": {"channel_config": {"enabled": True, "type": "web"}}},
                        "memory": {"enabled": False, "config": {}},
                    }
                },
                cache=False,
                mode="full",
                allow=None,
            )
        )

        gi = GatewayIntegration("gateway_config.json")
        gi.gateway_server = DummyGatewayServer()
        gi.channel_registry = ChannelRegistry()

        await gi._init_channels()

        self.assertIsNotNone(gi.channel_registry.get("web"))
        self.assertIn("web", gi.gateway_server.channels)

    async def test_plugin_refresh_updates_extensions_only_when_registry_changes(self):
        workspace_dir = str(Path(__file__).resolve().parents[1])
        registry = load_promethea_plugins(
            PluginLoadOptions(
                workspace_dir=workspace_dir,
                extensions_dir="extensions",
                config={"plugins": {}},
                cache=True,
                mode="full",
                allow=None,
            )
        )
        gi = GatewayIntegration("gateway_config.json")
        gi.gateway_server = DummyGatewayServer()
        gi.channel_registry = ChannelRegistry()
        gi._plugin_refresh_interval_seconds = 0
        gi._load_plugin_registry = lambda: registry

        reload_mock = AsyncMock(return_value={"registered": []})
        with patch("gateway.extension_catalog.reload_extensions", reload_mock):
            await gi.maybe_refresh_plugins(force=True)
            await gi.maybe_refresh_plugins(force=False)

        reload_mock.assert_awaited_once_with(gi.gateway_server)


if __name__ == "__main__":
    unittest.main()

