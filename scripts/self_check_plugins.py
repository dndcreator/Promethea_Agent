"""
Windows-friendly self check: plugin discovery + load + registry summary.
"""
from __future__ import annotations

from pathlib import Path

from core.plugins.loader import load_promethea_plugins, PluginLoadOptions


def main() -> None:
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

    print("== Promethea Plugin Self Check ==")
    print("plugins:", [f"{p.id}:{p.status}" for p in reg.plugins])
    print("channels:", [c.channel_id for c in reg.channels])
    print("services:", [s.service_id for s in reg.services])
    if reg.diagnostics:
        print("diagnostics:")
        for d in reg.diagnostics:
            print(f"- {d.level} {d.plugin_id or ''} {d.source or ''} {d.message}")


if __name__ == "__main__":
    main()

