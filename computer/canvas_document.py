"""Rendering helpers shared by the canvas shell and artifact verification."""
from pathlib import Path
import os
import base64
import hashlib
import json
import re
from html.parser import HTMLParser
from html import escape
from urllib.parse import unquote, urlsplit
import mimetypes


def is_redirected_path(path: Path) -> bool:
    return path.is_symlink() or path.resolve() != path.absolute()


def canvas_csp(*, process: bool = False) -> str:
    return ("sandbox allow-scripts allow-forms allow-modals; "
            "default-src 'self' data: blob:; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            + ("connect-src 'self' ws: wss:; " if process else "connect-src 'none'; ")
            + "form-action 'none'; base-uri 'none'")


def export_canvas_library(root: Path) -> list[dict]:
    state = root / ".promethea" / "environments.json"
    if not state.exists():
        return []
    rows = json.loads(state.read_text(encoding="utf-8")).get("environments", {})
    result = []
    for row in rows.values():
        if row.get("kind") != "static" or row.get("lifetime") != "reusable":
            continue
        app = (root / row["root"]).resolve()
        app.relative_to(root.resolve())
        files = {}
        for path in artifact_files(app):
            data = path.read_bytes()
            files[path.relative_to(app).as_posix()] = {"data": base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest()}
        result.append({"environment_id": row["environment_id"], "name": row["name"], "entrypoint": row["entrypoint"],
                       "state": row.get("app_state", {"revision": 0, "value": {}}), "files": files})
    return result


def decode_canvas_library(payload: list[dict]) -> list[dict]:
    if not isinstance(payload, list) or len(payload) > 20:
        raise ValueError("canvas archive must contain at most 20 applications")
    result = []
    ids = set()
    for item in payload:
        environment_id = str(item["environment_id"])
        if not re.fullmatch(r"env_[0-9a-f]{32}", environment_id) or environment_id in ids:
            raise ValueError("invalid or duplicate canvas archive identity")
        ids.add(environment_id)
        files = {}
        if not isinstance(item["files"], dict) or len(item["files"]) > 32:
            raise ValueError("canvas archive exceeds file limits")
        for name, blob in item["files"].items():
            path = Path(name)
            if not name or "\\" in name or path.is_absolute() or ".." in path.parts or ":" in name or any(part.startswith(".") for part in path.parts):
                raise ValueError("invalid canvas archive path")
            if not isinstance(blob["data"], str) or len(blob["data"]) > 1_400_000:
                raise ValueError("canvas archive file exceeds size limits")
            data = base64.b64decode(blob["data"], validate=True)
            if hashlib.sha256(data).hexdigest() != blob["sha256"]:
                raise ValueError("canvas artifact checksum mismatch")
            files[name] = data
        if sum(map(len, files.values())) > 1_000_000 or item["entrypoint"] not in files:
            raise ValueError("invalid canvas archive entrypoint or size")
        value = item.get("state", {}).get("value", {})
        if not isinstance(value, dict) or len(json.dumps(value, allow_nan=False).encode()) > 256000:
            raise ValueError("invalid canvas archive state")
        result.append({"environment_id": environment_id, "name": str(item["name"])[:200], "entrypoint": item["entrypoint"], "value": value, "files": files})
    return result


def render_canvas_html(source: str, *, root: Path | None = None, entrypoint: Path | None = None) -> str:
    if root is not None and entrypoint is not None:
        # Local assets are inlined so opaque frames never need the host's cookies.
        class Assets(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=False)
                self.parts = []
                self.embedded_script = False

            def local(self, value):
                parsed = urlsplit(value or "")
                if not value or parsed.scheme or parsed.netloc:
                    return None
                target = ((root if parsed.path.startswith("/") else entrypoint.parent) / unquote(parsed.path).lstrip("/")).resolve()
                target.relative_to(root.resolve())
                if target.is_symlink() or not target.is_file() or target.stat().st_size > 1_000_000:
                    raise ValueError("invalid local canvas asset")
                return target

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                target = self.local(attributes.get("src")) if tag in {"script", "img"} else self.local(attributes.get("href")) if tag == "link" and attributes.get("rel") == "stylesheet" else None
                if target is not None and tag == "script":
                    retained = " ".join(f'{key}="{escape(value or "", quote=True)}"' for key, value in attrs if key != "src")
                    code = target.read_text(encoding="utf-8").replace("</script", "<\\/script")
                    self.parts.append(f"<script {retained}>{code}")
                    self.embedded_script = True
                elif target is not None and tag == "link":
                    css = target.read_text(encoding="utf-8").replace("</style", "<\\/style")
                    self.parts.append(f'<style>{css}</style>')
                elif target is not None and tag == "img":
                    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                    attributes["src"] = f"data:{mime};base64,{base64.b64encode(target.read_bytes()).decode()}"
                    self.parts.append("<img " + " ".join(f'{key}="{escape(value or "", quote=True)}"' for key, value in attributes.items()) + ">")
                else:
                    self.parts.append(self.get_starttag_text())

            def handle_startendtag(self, tag, attrs):
                self.handle_starttag(tag, attrs)

            def handle_endtag(self, tag):
                if tag == "script":
                    self.embedded_script = False
                self.parts.append(f"</{tag}>")

            def handle_data(self, data):
                if not self.embedded_script:
                    self.parts.append(data)

            def handle_decl(self, decl):
                self.parts.append(f"<!{decl}>")

            def handle_comment(self, data):
                self.parts.append(f"<!--{data}-->")

            def handle_entityref(self, name):
                self.parts.append(f"&{name};")

            def handle_charref(self, name):
                self.parts.append(f"&#{name};")

        assets = Assets()
        assets.feed(source)
        source = "".join(assets.parts)
    script = Path(__file__).with_name("canvas_bridge.js").read_text(encoding="utf-8")
    expressions = Path(__file__).with_name("canvas_expressions.js").read_text(encoding="utf-8")
    bootstrap = f"<script>{expressions}\n{script}</script>"
    # Place the bridge before application scripts without altering application code.
    class Position(HTMLParser):
        insertion = 0
        def handle_decl(self, decl):
            if not self.insertion and decl.lower().startswith("doctype"):
                self.insertion = len(f"<!{decl}>")

        def handle_starttag(self, tag, attrs):
            if tag == "head":
                line, column = self.getpos()
                self.insertion = sum(map(len, source.splitlines(keepends=True)[:line - 1])) + column + len(self.get_starttag_text())

    position = Position()
    position.feed(source)
    return source[:position.insertion] + bootstrap + source[position.insertion:]


def artifact_files(root: Path) -> list[Path]:
    paths = []
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = [name for name in names if name not in {"node_modules", ".git", ".venv", "__pycache__", ".cache", ".promethea"}]
        for name in names + files:
            path = Path(directory) / name
            if is_redirected_path(path):
                raise PermissionError("canvas artifacts cannot contain links")
            if name in files and name not in {"agent-manifest.json", ".published.json"}:
                path.resolve().relative_to(root.resolve())
                paths.append(path)
    if len(paths) > 32 or sum(p.stat().st_size for p in paths) > 1_000_000:
        raise ValueError("canvas artifact exceeds 32 files or 1 MB")
    return sorted(paths)
