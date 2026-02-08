import json
import os
from typing import Tuple

from .types import PluginManifest


PROMETHEA_PLUGIN_MANIFEST_FILENAME = "promethea.plugin.json"


def resolve_plugin_manifest_path(root_dir: str) -> str:
    return os.path.join(root_dir, PROMETHEA_PLUGIN_MANIFEST_FILENAME)


def load_plugin_manifest(root_dir: str) -> Tuple[bool, str, PluginManifest | str]:
    """
    Returns:
      (ok, manifest_path, manifest_or_error)
    """
    manifest_path = resolve_plugin_manifest_path(root_dir)
    if not os.path.exists(manifest_path):
        return False, manifest_path, f"plugin manifest not found: {manifest_path}"
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        return False, manifest_path, f"failed to parse plugin manifest: {e}"

    try:
        manifest = PluginManifest.model_validate(raw)
    except Exception as e:
        return False, manifest_path, f"invalid plugin manifest: {e}"

    if not manifest.id:
        return False, manifest_path, "plugin manifest requires id"
    if manifest.config_schema is None:
        return False, manifest_path, "plugin manifest requires configSchema"

    return True, manifest_path, manifest

