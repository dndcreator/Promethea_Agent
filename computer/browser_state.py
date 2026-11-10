"""Persist browser authentication only through the owner's protected storage."""
from hashlib import sha256

from agentkit.security.credential_store import ProtectedStore
from .execution_context import current_workspace


class BrowserProfile:
    def __init__(self, root):
        scope = current_workspace()
        self.store = None
        self.key = None
        self.root = root
        self.persistence = "ephemeral"
        if scope:
            if scope.root.resolve() != root.resolve():
                raise PermissionError("browser profile does not match its trusted workspace")
            self.store = ProtectedStore(scope.user_id)
            self.key = "browser_" + sha256(scope.workspace_id.encode()).hexdigest()

    def load(self):
        if self.store is None or not self.store.available():
            return None
        saved = self.store.read(self.key)
        legacy = self.root / "browser_state.json"
        if saved is None and legacy.exists():
            self.persistence = "legacy_plaintext_not_imported"
        else:
            self.persistence = "os_protected"
        return saved

    def save(self, state, *, protected):
        if self.store is not None and self.store.available():
            self.store.write(self.key, {"state": state, "protected": protected})
