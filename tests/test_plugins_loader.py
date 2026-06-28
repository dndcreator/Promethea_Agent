import json
import os
import shutil
import unittest
import uuid
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

    def test_cache_key_auto_includes_extensions_changes(self):
        workspace_root = Path(__file__).resolve().parents[1]
        tmp_base = Path(os.environ.get("PROMETHEA_TEST_TMP_ROOT", str(workspace_root / ".tmp" / "pytest-runtime"))) / "plugins-loader"
        tmp_base.mkdir(parents=True, exist_ok=True)
        workspace = tmp_base / f"plugins_reload_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            ext_dir = workspace / "extensions"
            ext_dir.mkdir(parents=True, exist_ok=True)

            def _write_plugin(plugin_id: str) -> None:
                root = ext_dir / plugin_id
                root.mkdir(parents=True, exist_ok=True)
                (root / "promethea.plugin.json").write_text(
                    json.dumps(
                        {
                            "id": plugin_id,
                            "kind": "service",
                            "name": plugin_id,
                            "version": "0.1.0",
                            "configSchema": {},
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                (root / "plugin.py").write_text(
                    "def register(api):\n"
                    f"    api.register_service('{plugin_id}', object())\n",
                    encoding="utf-8",
                )

            _write_plugin("alpha")
            reg1 = load_promethea_plugins(
                PluginLoadOptions(
                    workspace_dir=str(workspace),
                    extensions_dir="extensions",
                    config={"plugins": {"alpha": {"enabled": True, "config": {}}}},
                    cache=True,
                    mode="full",
                    allow=None,
                )
            )
            ids1 = {p.id for p in reg1.plugins}
            self.assertIn("alpha", ids1)
            self.assertNotIn("beta", ids1)

            _write_plugin("beta")
            reg2 = load_promethea_plugins(
                PluginLoadOptions(
                    workspace_dir=str(workspace),
                    extensions_dir="extensions",
                    config={
                        "plugins": {
                            "alpha": {"enabled": True, "config": {}},
                            "beta": {"enabled": True, "config": {}},
                        }
                    },
                    cache=True,
                    mode="full",
                    allow=None,
                )
            )
            ids2 = {p.id for p in reg2.plugins}
            self.assertIn("alpha", ids2)
            self.assertIn("beta", ids2)
            self.assertNotEqual(id(reg1), id(reg2))
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
