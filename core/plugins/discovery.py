import os
from typing import List

from .manifest import resolve_plugin_manifest_path
from .types import PluginCandidate


def discover_promethea_plugins(workspace_dir: str, extensions_dir: str = "extensions") -> List[PluginCandidate]:
    """
    Discover plugins under:
      <workspace_dir>/<extensions_dir>/*
    A plugin is a directory containing promethea.plugin.json
    """
    root = os.path.join(workspace_dir, extensions_dir)
    if not os.path.isdir(root):
        return []

    candidates: List[PluginCandidate] = []
    for name in os.listdir(root):
        plugin_root = os.path.join(root, name)
        if not os.path.isdir(plugin_root):
            continue

        manifest_path = resolve_plugin_manifest_path(plugin_root)
        if not os.path.exists(manifest_path):
            continue

        source = os.path.join(plugin_root, "plugin.py")
        if not os.path.exists(source):
            # still discoverable, but will fail load with clear error
            source = os.path.join(plugin_root, "__init__.py")

        candidates.append(
            PluginCandidate(
                root_dir=plugin_root,
                source=source,
                origin="local",
                workspace_dir=workspace_dir,
            )
        )
    return candidates

