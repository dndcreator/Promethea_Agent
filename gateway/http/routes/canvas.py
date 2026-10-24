from __future__ import annotations

import asyncio
import mimetypes
import hashlib
import shutil
from uuid import uuid4
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlencode, urlsplit

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from jose import JWTError

from computer.execution_context import ComputerWorkspace, bind_workspace
from computer.canvas_document import artifact_files, render_canvas_html, decode_canvas_library, canvas_csp, is_redirected_path
from gateway.public_contracts import CanvasEnvironmentList, CanvasState, CanvasStateWrite, CanvasEnvironment, CanvasInteraction, CanvasSemanticSnapshot
from pydantic import BaseModel, Field

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


def _preview_headers(*, process: bool = False) -> Dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": canvas_csp(process=process),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def _proxy_response_headers(headers: aiohttp.typedefs.LooseHeaders) -> Dict[str, str]:
    forwarded = {
        key: value for key, value in headers.items()
        if key.lower() in _FORWARDED_RESPONSE_HEADERS and key.lower() not in _HOP_BY_HOP_HEADERS
    }
    forwarded.update(_preview_headers(process=True))
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


def _public_environment(workspace_id: str, row: Dict[str, Any], root: Path | None = None) -> Dict[str, Any]:
    environment_id = str(row.get("environment_id") or "")
    revision = str(row.get("revision", 0))
    if root is not None and row.get("kind") == "static":
        app = (root / str(row.get("root") or ".")).resolve()
        app.relative_to(root.resolve())
        digest = hashlib.sha256()
        for path in artifact_files(app):
            relative = path.relative_to(app)
            if any(part.startswith(".") for part in relative.parts):
                continue
            digest.update(relative.as_posix().encode())
            digest.update(path.read_bytes())
        revision = digest.hexdigest()
    return {
        **row,
        "workspace_id": workspace_id,
        "preview_url": f"/api/canvas/{workspace_id}/{environment_id}/preview/",
        "content_revision": revision,
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
        "environments": [_public_environment(scope.workspace_id, row, scope.root) for row in (result.result or [])],
    }


async def _canvas_action(user_id: str, workspace_id: str, environment_id: str, action: str, params: dict | None = None):
    service, handle, _ = _runtime_and_scope(user_id, workspace_id)
    with bind_workspace(handle):
        result = await service.execute_computer_action("environment", action, {**(params or {}), "environment_id": environment_id})
    if not result.success:
        raise HTTPException(status_code=409, detail=result.error)
    return result.result


@router.get("/{workspace_id}/{environment_id}/state", response_model=CanvasState)
async def get_canvas_state(workspace_id: str, environment_id: str, user_id: str = Depends(get_current_user_id)):
    return await _canvas_action(user_id, workspace_id, environment_id, "state_get")


@router.put("/{workspace_id}/{environment_id}/state", response_model=CanvasState)
async def set_canvas_state(workspace_id: str, environment_id: str, body: CanvasStateWrite, user_id: str = Depends(get_current_user_id)):
    return await _canvas_action(user_id, workspace_id, environment_id, "state_set", body.model_dump())


class CanvasDiagnostic(BaseModel):
    message: str = Field(max_length=2000)


@router.get("/{workspace_id}/{environment_id}/semantics", response_model=CanvasSemanticSnapshot)
async def get_canvas_semantics(workspace_id: str, environment_id: str, user_id: str = Depends(get_current_user_id)):
    return await _canvas_action(user_id, workspace_id, environment_id, "semantics")


@router.post("/{workspace_id}/{environment_id}/interact", response_model=CanvasState)
async def interact_canvas(workspace_id: str, environment_id: str, body: CanvasInteraction, user_id: str = Depends(get_current_user_id)):
    return await _canvas_action(user_id, workspace_id, environment_id, "interact", body.model_dump())


@router.post("/{workspace_id}/{environment_id}/diagnostics")
async def report_canvas_error(workspace_id: str, environment_id: str, body: CanvasDiagnostic, user_id: str = Depends(get_current_user_id)):
    return await _canvas_action(user_id, workspace_id, environment_id, "report_error", body.model_dump())


@router.post("/{workspace_id}/{environment_id}/retain", response_model=CanvasEnvironment)
async def retain_canvas(workspace_id: str, environment_id: str, user_id: str = Depends(get_current_user_id)):
    scope, row = await _environment(user_id, workspace_id, environment_id)
    if row.get("kind") != "static":
        raise HTTPException(status_code=400, detail="only static canvas artifacts can be retained")
    service, _, _ = _runtime_and_scope(user_id, workspace_id)
    handle = service.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id="_canvas_library")
    source = (scope.root / row["root"]).resolve()
    source.relative_to(scope.root)
    new_id = f"env_{uuid4().hex}"
    relative = f".canvas_apps/{new_id}"
    destination = Path(handle.root_path) / relative
    destination.mkdir(parents=True, exist_ok=False)
    try:
        for path in artifact_files(source):
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        with bind_workspace(handle):
            registered = await service.execute_computer_action("environment", "register", {
                "environment_id": new_id, "name": row["name"], "root": relative,
                "entrypoint": row["entrypoint"], "lifetime": "reusable",
            })
        if not registered.success:
            raise HTTPException(status_code=409, detail=registered.error)
        state = await _canvas_action(user_id, workspace_id, environment_id, "state_get")
        await _canvas_action(user_id, handle.workspace_id, new_id, "state_set", {"expected_revision": 0, "value": state["value"]})
        return _public_environment(handle.workspace_id, registered.result, Path(handle.root_path))
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


@router.delete("/{workspace_id}/{environment_id}")
async def remove_canvas(workspace_id: str, environment_id: str, user_id: str = Depends(get_current_user_id)):
    scope, row = await _environment(user_id, workspace_id, environment_id)
    result = await _canvas_action(user_id, workspace_id, environment_id, "remove")
    relative = Path(row.get("root", "."))
    if relative.parts == (".canvas_apps", environment_id):
        target = scope.root / relative
        if is_redirected_path(target):
            raise HTTPException(status_code=409, detail="Canvas root must not redirect through a link")
        target = target.resolve()
        target.relative_to(scope.root)
        shutil.rmtree(target)
    return result


async def restore_canvas_library(user_id: str, payload: list[dict], *, merge: bool = True) -> int:
    apps = decode_canvas_library(payload)
    service, handle, scope = _runtime_and_scope(user_id, "_canvas_library")
    with bind_workspace(handle):
        current = await service.execute_computer_action("environment", "list", {})
    existing = {row["environment_id"]: row for row in current.result or []}
    pending = []
    for app in apps:
        environment_id = app["environment_id"]
        if merge and environment_id in existing:
            previous = existing[environment_id]
            old_root = (scope.root / previous["root"]).resolve()
            old_root.relative_to(scope.root)
            old_files = {p.relative_to(old_root).as_posix(): p.read_bytes() for p in artifact_files(old_root)}
            state = await _canvas_action(user_id, "_canvas_library", environment_id, "state_get")
            if old_files != app["files"] or state["value"] != app["value"] or previous["entrypoint"] != app["entrypoint"]:
                raise ValueError("canvas archive conflicts with an existing application; use replace mode")
            continue
        if (scope.root / ".canvas_apps" / environment_id).exists() and environment_id not in existing:
            raise ValueError("canvas archive destination already exists")
        pending.append(app)
    if not merge:
        for environment_id in existing:
            await remove_canvas("_canvas_library", environment_id, user_id)
        existing = {}
    for app in pending:
        environment_id = app["environment_id"]
        if environment_id in existing:
            raise ValueError("canvas archive conflicts with an existing application; use replace mode")
        relative = f".canvas_apps/{environment_id}"
        root = scope.root / relative
        if root.exists():
            raise ValueError("canvas archive destination already exists")
        root.mkdir(parents=True)
        for name, data in app["files"].items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        with bind_workspace(handle):
            result = await service.execute_computer_action("environment", "register", {"environment_id": environment_id,
                "name": app["name"], "root": relative, "entrypoint": app["entrypoint"], "lifetime": "reusable"})
        if not result.success:
            raise ValueError(result.error)
        await _canvas_action(user_id, "_canvas_library", environment_id, "state_set", {"expected_revision": 0, "value": app["value"]})
    return len(apps)


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
    if media_type == "text/html":
        return HTMLResponse(render_canvas_html(target.read_text(encoding="utf-8"), root=root, entrypoint=target), headers=headers)
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
