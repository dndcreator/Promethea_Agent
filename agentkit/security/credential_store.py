"""Owner-scoped OS-protected records. Never expose secret values as tool results."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import string
import sys
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4
from utils.persistence import rename_with_retry


class ProtectedStorageUnavailable(RuntimeError):
    pass


def web_origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("protected credentials require an HTTPS origin without URL credentials")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    host = f"[{host}]" if ":" in host else host
    return f"https://{host}" + (f":{parsed.port}" if parsed.port and parsed.port != 443 else "")


class ProtectedStore:
    def __init__(self, user_id: str, root: Path | None = None):
        if not user_id or not str(user_id).strip():
            raise PermissionError("protected storage requires a trusted owner")
        if root is None:
            from config import PROJECT_ROOT
            root = PROJECT_ROOT / "config" / "users"
        self.owner = str(user_id)
        self.root = Path(root) / sha256(self.owner.encode()).hexdigest() / "protected"

    @staticmethod
    def available() -> bool:
        if sys.platform != "win32":
            return False
        try:
            import win32crypt
            return callable(win32crypt.CryptProtectData)
        except ImportError:
            return False

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"[a-z]+_[a-f0-9]{32,64}", key):
            raise ValueError("invalid protected record reference")
        return self.root / (key + ".sealed")

    def _entropy(self, key: str) -> bytes:
        return sha256(("promethea.protected.v1\0" + self.owner + "\0" + key).encode()).digest()

    def write(self, key: str, value: dict) -> None:
        if not self.available():
            raise ProtectedStorageUnavailable("OS-protected storage is unavailable; no plaintext fallback is permitted")
        import win32crypt
        path = self._path(key)
        data = json.dumps({"version": 1, "owner": self.owner, "value": value}, ensure_ascii=False).encode()
        sealed = win32crypt.CryptProtectData(data, "Promethea", self._entropy(key), None, None, 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".protected-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(sealed)
                stream.flush()
                os.fsync(stream.fileno())
            rename_with_retry(name, path, replace=True)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def read(self, key: str) -> dict | None:
        path = self._path(key)
        if not path.exists():
            return None
        if not self.available():
            raise ProtectedStorageUnavailable("OS-protected storage is unavailable")
        import win32crypt
        try:
            _, data = win32crypt.CryptUnprotectData(path.read_bytes(), self._entropy(key), None, None, 1)
            record = json.loads(data)
            if record["version"] != 1 or record["owner"] != self.owner or not isinstance(record["value"], dict):
                raise ValueError("invalid protected record")
            return record["value"]
        except Exception:
            raise PermissionError("protected record cannot be opened in this owner/OS context") from None

    def create_credential(self, *, url: str, username: str = "", length: int = 32) -> dict:
        origin = web_origin(url)
        if not 16 <= length <= 128 or len(username) > 320:
            raise ValueError("credential length must be 16..128; username must be bounded")
        alphabet = string.ascii_letters + string.digits + "-_!@#"
        password = "".join(secrets.choice(group) for group in (string.ascii_lowercase, string.ascii_uppercase, string.digits, "-_!@#"))
        password += "".join(secrets.choice(alphabet) for _ in range(length - 4))
        password = "".join(secrets.SystemRandom().sample(password, len(password)))
        reference = "cred_" + uuid4().hex
        self.write(reference, {"origin": origin, "username": username, "password": password})
        return {"credential_ref": reference, "origin": origin, "username": username, "storage": "os_protected"}

    def password_for_origin(self, reference: str, url: str) -> str:
        record = self.read(reference)
        if not record or not reference.startswith("cred_") or record.get("origin") != web_origin(url):
            raise PermissionError("credential does not belong to the current HTTPS origin")
        return record["password"]

    def list_credentials(self) -> list[dict]:
        result = []
        for path in sorted(self.root.glob("cred_*.sealed"))[:200]:
            value = self.read(path.stem)
            result.append({"credential_ref": path.stem, "origin": value["origin"], "username": value["username"], "storage": "os_protected"})
        return result
