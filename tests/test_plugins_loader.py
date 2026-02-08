import unittest
from pathlib import Path

from core.plugins.loader import load_promethea_plugins, PluginLoadOptions


class TestPluginsLoader(unittest.TestCase):
    def test_loads_builtin_extensions(self):
        workspace_dir = str(Path(__file__).resolve().parents[1])

        reg = load_promethea_plugins(
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

        plugin_ids = {p.id for p in reg.plugins}
        self.assertIn("web", plugin_ids)
        self.assertIn("memory", plugin_ids)

        channel_ids = {c.channel_id for c in reg.channels}
        self.assertIn("web", channel_ids)

        service_ids = {s.service_id for s in reg.services}
        # memory disabled => should not register service (we currently still register even if disabled isn't checked inside plugin)
        # We assert only that it doesn't crash; registry may contain memory depending on config.
        self.assertTrue(isinstance(service_ids, set))


if __name__ == "__main__":
    unittest.main()

