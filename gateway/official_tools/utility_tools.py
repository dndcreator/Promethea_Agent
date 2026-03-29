from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from gateway.tool_service import ToolInvocationContext


class UtilsNowTool:
    tool_id = "utils.now"
    name = "utils.now"
    description = "Return current UTC/local timestamps."
    official = True
    official_domain = "utils"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = args, ctx
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now().astimezone()
        return {
            "utc_iso": now_utc.isoformat(),
            "local_iso": now_local.isoformat(),
            "epoch_ms": int(now_utc.timestamp() * 1000),
        }


class UtilsUuidTool:
    tool_id = "utils.uuid"
    name = "utils.uuid"
    description = "Generate one or more UUID4 strings."
    official = True
    official_domain = "utils"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        count = int((args or {}).get("count") or 1)
        count = max(1, min(count, 100))
        values = [str(uuid.uuid4()) for _ in range(count)]
        return {"count": count, "uuids": values}


class UtilsHashTextTool:
    tool_id = "utils.hash_text"
    name = "utils.hash_text"
    description = "Compute text hash (sha256/md5)."
    official = True
    official_domain = "utils"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        text = str((args or {}).get("text") or "")
        algo = str((args or {}).get("algo") or "sha256").strip().lower()
        if algo not in {"sha256", "md5"}:
            raise ValueError("algo must be one of: sha256, md5")
        payload = text.encode("utf-8")
        if algo == "md5":
            digest = hashlib.md5(payload).hexdigest()  # noqa: S324
        else:
            digest = hashlib.sha256(payload).hexdigest()
        return {"algo": algo, "digest": digest, "bytes": len(payload)}

