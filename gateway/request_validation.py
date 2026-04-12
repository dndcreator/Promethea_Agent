from __future__ import annotations

from typing import Any, Dict

from .protocol import (
    AgentCallParams,
    ChatConfirmParams,
    ChatParams,
    FollowupParams,
    MemoryClusterParams,
    MemoryQueryParams,
    MemorySummarizeParams,
    RequestType,
    SendMessageParams,
    SessionParams,
)


_VALIDATOR_BY_METHOD = {
    RequestType.SEND: SendMessageParams,
    RequestType.AGENT: AgentCallParams,
    RequestType.MEMORY_QUERY: MemoryQueryParams,
    RequestType.FOLLOWUP: FollowupParams,
    RequestType.CHAT: ChatParams,
    RequestType.CHAT_CONFIRM: ChatConfirmParams,
    RequestType.MEMORY_CLUSTER: MemoryClusterParams,
    RequestType.MEMORY_SUMMARIZE: MemorySummarizeParams,
    RequestType.SESSION_DETAIL: SessionParams,
    RequestType.SESSION_DELETE: SessionParams,
    RequestType.MEMORY_GRAPH: SessionParams,
    RequestType.MEMORY_DECAY: SessionParams,
    RequestType.MEMORY_CLEANUP: SessionParams,
}


def validate_gateway_request_params(
    method: RequestType,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate params using protocol schemas when available."""
    model = _VALIDATOR_BY_METHOD.get(method)
    if not model:
        return params
    obj = model(**params)
    return obj.model_dump() if hasattr(obj, "model_dump") else obj.dict()
