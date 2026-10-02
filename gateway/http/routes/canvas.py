from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlencode, urlsplit

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from jose import JWTError

from computer.execution_context import ComputerWorkspace, bind_workspace
from gateway.public_contracts import CanvasEnvironmentList

from ..dispatcher import get_gateway_server
from .auth import AUTH_COOKIE_NAME, get_current_user_id, user_id_from_access_token


router = APIRouter(prefix="/canvas", tags=["canvas"])

_HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}
_FORWARDED_REQUEST_HEADERS = {
    "accept", "accept-encoding", "accept-language", "cache-control", "content-type",
    "if-match", "if-modified-since", "if-none-match", "if-range", "if-unmodified-since", "range",
}
_FORWARDED_RESPONSE_HEADERS = {
    "accept-ranges", "cache-control", "content-disposition", "content-encoding", "content-language",
    "content-length", "content-range", "content-type", "etag", "expires", "last-modified", "location",
}
_MAX_PROXY_BODY_BYTES = 16 * 1024 * 1024
_MAX_WEBSOCKET_MESSAGE_BYTES = 8 * 1024 * 1024


def _preview_headers() -> Dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "sandbox allow-scripts allow-forms allow-modals; "
            "default-src 'self' data: blob:; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "connect-src 'self' ws: wss:"
        ),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def _proxy_response_headers(headers: aiohttp.typedefs.LooseHeaders) -> Dict[str, str]:
    forwarded = {
        key: value for key, value in headers.items()
        if key.lower() in _FORWARDED_RESPONSE_HEADERS and key.lower() not in _HOP_BY_HOP_HEADERS
    }
    forwarded.update(_preview_headers())
    return forwarded


def _rewrite_location(location: str, *, port: int, workspace_id: str, environment_id: str) -> str:
    parsed = urlsplit(location)
    if parsed.netloc and parsed.netloc not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
        raise HTTPException(status_code=502, detail="Canvas process returned an external redirect")
    path = parsed.path.lstrip("/")
    rewritten = f"/api/canvas/{workspace_id}/{environment_id}/preview/{path}"
    return f"{rewritten}?{parsed.query}" if parsed.query else rewritten


async def _read_proxy_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_PROXY_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Canvas request body is too large")
    return bytes(body)


def _runtime_and_scope(user_id: str, workspace_id: str):
    server = get_gateway_server()
    workspace_service = getattr(server, "workspace_service", None)
    capability_service = getattr(server, "capability_service", None)
    runtime = getattr(capability_service, "computer_runtime", None)
    if workspace_service is None or runtime is None:
        raise HTTPException(status_code=503, detail="Capability runtime not initialized")
    handle = workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
    scope = ComputerWorkspace(handle.user_id, handle.workspace_id, Path(handle.root_path).resolve())
    return capability_service, handle, scope


async def _environment(user_id: str, workspace_id: str, environment_id: str) -> tuple[ComputerWorkspace, Dict[str, Any]]:
    capability_service, handle, scope = _runtime_and_scope(user_id, workspace_id)
    with bind_workspace(handle):
        result = await capability_service.execute_computer_action(
            "environment", "get", {"environment_id": environment_id},
        )
    if not result.success or not isinstance(result.result, dict):
        raise HTTPException(status_code=404, detail=result.error or "Canvas environment not found")
    return scope, dict(result.result)


def _public_environment(workspace_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    environment_id = str(row.get("environment_id") or "")
    return {
        **row,
        "workspace_id": workspace_id,
        "preview_url": f"/api/canvas/{workspace_id}/{environment_id}/preview/",
    }


@router.get("/environments", response_model=CanvasEnvironmentList)
async def list_canvas_environments(
    workspace_id: str = "default",
    user_id: str = Depends(get_current_user_id),
):
    capability_service, handle, scope = _runtime_and_scope(user_id, workspace_id)
    with bind_workspace(handle):
        result = await capability_service.execute_computer_action("environment", "list", {})
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error or "Unable to list canvas environments")
    return {
        "workspace_id": scope.workspace_id,
        "environments": [_public_environment(scope.workspace_id, row) for row in (result.result or [])],
    }


@router.api_route(
    "/{workspace_id}/{environment_id}/preview/{asset_path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def preview_canvas_environment(
    request: Request,
    workspace_id: str,
    environment_id: str,
    asset_path: str = "",
    user_id: str = Depends(get_current_user_id),
):
    scope, row = await _environment(user_id, workspace_id, environment_id)
    requested = asset_path or str(row.get("entrypoint") or "index.html")
    headers = _preview_headers()
    if row.get("kind") == "process":
        port = int(row.get("port") or 0)
        if row.get("status") != "running" or not 1024 <= port <= 65535:
            raise HTTPException(status_code=409, detail="Canvas process is not running")
        query = urlencode(list(request.query_params.multi_items()))
        target = f"http://127.0.0.1:{port}/{requested.lstrip('/')}"
        if query:
            target = f"{target}?{query}"
        try:
            timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=60)
            session = aiohttp.ClientSession(timeout=timeout, auto_decompress=False)
            upstream = await session.request(
                request.method,
                target,
                headers={key: value for key, value in request.headers.items() if key.lower() in _FORWARDED_REQUEST_HEADERS},
                data=await _read_proxy_body(request),
                allow_redirects=False,
            )
            response_headers = _proxy_response_headers(upstream.headers)
            location = upstream.headers.get("Location")
            if location:
                response_headers["Location"] = _rewrite_location(
                    location,
                    port=port,
                    workspace_id=workspace_id,
                    environment_id=environment_id,
                )

            async def stream_body():
                try:
                    async for chunk in upstream.content.iter_chunked(64 * 1024):
                        yield chunk
                finally:
                    upstream.release()
                    await session.close()

            return StreamingResponse(stream_body(), status_code=upstream.status, headers=response_headers)
        except aiohttp.ClientError as exc:
            if "session" in locals():
                await session.close()
            raise HTTPException(status_code=502, detail="Canvas process is unavailable") from exc
        except Exception:
            if "upstream" in locals():
                upstream.release()
            if "session" in locals():
                await session.close()
            raise

    if request.method not in {"GET", "HEAD"}:
        raise HTTPException(status_code=405, detail="Static canvas environments are read-only")

    root = (scope.root / str(row.get("root") or ".")).resolve()
    target = (root / requested).resolve()
    try:
        target.relative_to(root)
        root.relative_to(scope.root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Canvas path escapes workspace") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Canvas asset not found")
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type, headers=headers)


@router.websocket("/{workspace_id}/{environment_id}/preview/{asset_path:path}")
async def proxy_canvas_websocket(
    websocket: WebSocket,
    workspace_id: str,
    environment_id: str,
    asset_path: str = "",
):
    token = websocket.cookies.get(AUTH_COOKIE_NAME)
    authorization = websocket.headers.get("authorization", "")
    if not token and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    try:
        user_id = user_id_from_access_token(token or "")
    except JWTError:
        await websocket.close(code=4401)
        return

    try:
        _, row = await _environment(user_id, workspace_id, environment_id)
    except HTTPException:
        await websocket.close(code=4404)
        return
    port = int(row.get("port") or 0)
    if row.get("kind") != "process" or row.get("status") != "running" or not 1024 <= port <= 65535:
        await websocket.close(code=4409)
        return
    query = urlencode(list(websocket.query_params.multi_items()))
    target = f"ws://127.0.0.1:{port}/{asset_path.lstrip('/')}"
    if query:
        target = f"{target}?{query}"

    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=10))
    try:
        async with session.ws_connect(target, max_msg_size=_MAX_WEBSOCKET_MESSAGE_BYTES) as upstream:
            await websocket.accept()

            async def client_to_upstream():
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    if message.get("text") is not None:
                        if len(message["text"].encode("utf-8")) > _MAX_WEBSOCKET_MESSAGE_BYTES:
                            await websocket.close(code=1009)
                            break
                        await upstream.send_str(message["text"])
                    elif message.get("bytes") is not None:
                        if len(message["bytes"]) > _MAX_WEBSOCKET_MESSAGE_BYTES:
                            await websocket.close(code=1009)
                            break
                        await upstream.send_bytes(message["bytes"])

            async def upstream_to_client():
                async for message in upstream:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        await websocket.send_text(message.data)
                    elif message.type == aiohttp.WSMsgType.BINARY:
                        await websocket.send_bytes(message.data)
                    elif message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                        break

            tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, *pending, return_exceptions=True)
    except (aiohttp.ClientError, WebSocketDisconnect):
        if websocket.client_state.name == "CONNECTED":
            await websocket.close(code=1011)
    finally:
        await session.close()
