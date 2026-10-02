"""Extensible semantic locations for host filesystem tools."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional


LocationProvider = Callable[[], Optional[Path]]


class SystemLocationRegistry:
    def __init__(self, *, workspace_root: Optional[Path] = None) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).expanduser()
        self._providers: Dict[str, LocationProvider] = {}
        self._host_readable: set[str] = set()

    def register(self, name: str, provider: LocationProvider, *, host_readable: bool = False) -> None:
        key = str(name or "").strip().lower()
        if not key:
            raise ValueError("location name is required")
        self._providers[key] = provider
        if host_readable:
            self._host_readable.add(key)
        else:
            self._host_readable.discard(key)

    def resolve(self, name: str) -> Path:
        key = str(name or "").strip().lower()
        provider = self._providers.get(key)
        if provider is None:
            raise ValueError(f"Unknown system location: {name}")
        value = provider()
        if value is None:
            raise FileNotFoundError(f"System location is unavailable: {name}")
        return Path(value).expanduser()

    def available_names(self) -> list[str]:
        available = []
        for name, provider in self._providers.items():
            try:
                if provider() is not None:
                    available.append(name)
            except Exception:
                continue
        return sorted(available)

    def host_readable_roots(self) -> list[Path]:
        roots = []
        for name in sorted(self._host_readable):
            try:
                path = self.resolve(name).resolve(strict=True)
                if path.is_dir():
                    roots.append(path)
            except (OSError, ValueError):
                continue
        return roots


def build_default_location_registry(*, workspace_root: Optional[Path] = None) -> SystemLocationRegistry:
    registry = SystemLocationRegistry(workspace_root=workspace_root)
    registry.register("workspace", lambda: registry.workspace_root)
    registry.register("home", Path.home)
    registry.register("temp", lambda: Path(tempfile.gettempdir()))

    for name in ("desktop", "documents", "downloads"):
        registry.register(name, lambda name=name: _discover_user_folder(name), host_readable=True)

    return registry


def _discover_user_folder(name: str) -> Optional[Path]:
    registry_names = {
        "desktop": "Desktop",
        "documents": "Personal",
        "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    }
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as handle:
                raw, _ = winreg.QueryValueEx(handle, registry_names[name])
            value = Path(os.path.expandvars(str(raw))).expanduser()
            if value.exists():
                return value
        except (KeyError, OSError, ImportError):
            pass

    conventional = {"desktop": "Desktop", "documents": "Documents", "downloads": "Downloads"}[name]
    candidates: Iterable[Path] = (
        *((Path(root) / conventional) for root in (os.getenv("OneDrive"), os.getenv("OneDriveConsumer")) if root),
        Path.home() / conventional,
    )
    return next((candidate for candidate in candidates if candidate.exists()), None)
