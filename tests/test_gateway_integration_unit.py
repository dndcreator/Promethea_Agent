import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()

