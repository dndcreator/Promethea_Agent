"""Browser-only preview of workspace artifacts without host URLs or credentials."""
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .browser_observation import snapshot
from .canvas_document import is_redirected_path


ORIGIN = "https://workspace-preview.invalid"
ASSETS = {
    ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}
HTML = {".html", ".htm"}
CSP = (
    "sandbox allow-scripts allow-same-origin allow-forms; default-src 'none'; "
    "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self'; form-action 'none'; base-uri 'none'"
)


class WorkspaceBrowserPreview:
    def __init__(self, browser, workspace: Path, sandbox):
        self.browser = browser
        self.workspace = workspace
        self.sandbox = sandbox
        self.context = self.page = self.entry = None

    def _file(self, root: Path, relative: str) -> Path:
        parts = relative.split("/")
        if any(not part or part.startswith(".") or part.endswith((".", " "))
               or any(ch in part for ch in '\\:\x00') for part in parts):
            raise ValueError("Preview requires a visible workspace-relative path using '/'.")
        path = root
        for part in parts:
            path = path / part
            if is_redirected_path(path):
                raise ValueError("Preview cannot follow redirected paths.")
        if not path.is_relative_to(self.workspace) or not self.sandbox.check_path(
            str(path), intent="read", workspace_root=self.workspace,
        ).allowed:
            raise ValueError("Preview cannot read outside the allowed workspace.")
        if not path.is_file():
            raise ValueError("Preview file does not exist.")
        return path

    async def _serve(self, route):
        url = urlsplit(route.request.url)
        if f"{url.scheme}://{url.netloc}" != ORIGIN or route.request.method != "GET":
            await route.abort()
            return
        try:
            path = self._file(self.entry.parent, unquote(url.path[1:]))
            content_type = "text/html" if path == self.entry else ASSETS.get(path.suffix.lower())
            if not content_type:
                raise ValueError("Unsupported preview resource.")
            with path.open("rb") as source:
                body = source.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise ValueError("Preview resource is too large.")
        except (OSError, ValueError):
            await route.abort()
            return
        await route.fulfill(body=body, content_type=content_type, headers={
            "Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store", "X-DNS-Prefetch-Control": "off",
        })

    async def close(self):
        if self.context is not None:
            await self.context.close()
        self.context = self.page = self.entry = None

    async def execute(self, params: dict) -> dict:
        operation = params.get("operation", "open")
        timeout = min(60000, max(1, int(params.get("timeout", 10000))))
        if operation == "close":
            await self.close()
            return {"closed": True}
        if operation == "open":
            entry = self._file(self.workspace, str(params.get("path") or ""))
            if entry.suffix.lower() not in HTML:
                raise ValueError("Preview entry must be an HTML file.")
            if entry != self.entry or self.page is None or self.page.is_closed():
                await self.close()
                self.entry = entry
                self.context = await self.browser.new_context(
                    offline=True, service_workers="block", accept_downloads=False,
                )
                await self.context.route("**/*", self._serve)
                if hasattr(self.context, "route_web_socket"):
                    await self.context.route_web_socket("**/*", lambda socket: socket.close())
                self.page = await self.context.new_page()
            await self.page.goto(f"{ORIGIN}/{quote(entry.name)}", timeout=timeout, wait_until="load")
        elif self.page is None or self.page.is_closed():
            raise ValueError("Open a workspace HTML preview first.")
        elif operation == "reload":
            await self.page.reload(timeout=timeout, wait_until="load")
        elif operation in {"click", "fill", "press"}:
            target = self.page.locator(params["selector"])
            if operation == "click":
                await target.click(timeout=timeout)
            elif operation == "fill":
                await target.fill(str(params.get("text", "")), timeout=timeout)
            else:
                await target.press(params["key"], timeout=timeout)
        elif operation != "snapshot":
            raise ValueError("Unsupported workspace preview operation.")
        result = await snapshot(self.page, query=str(params.get("query", "")),
                                max_nodes=params.get("max_nodes", 120), include_state=True)
        return {**result, "path": self.entry.relative_to(self.workspace).as_posix()}
