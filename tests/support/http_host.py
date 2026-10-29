"""Disposable TCP host for system acceptance, never a production launcher."""
import argparse
import json
from pathlib import Path
import socket

import pytest
import uvicorn

from tests.support.http_runtime import app_at
from tests.support.runtime import ScriptedModel, finish_from_observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    snapshot = Path(__file__).resolve().parents[2]
    if root.parent != snapshot.parent or snapshot.name != "code":
        raise ValueError("This host only runs beside a disposable code snapshot")
    root.mkdir(parents=True, exist_ok=True)
    actions = json.loads((root / "model.json").read_text())
    model = ScriptedModel([finish_from_observation if action == "$observation" else action for action in actions])
    overrides = pytest.MonkeyPatch()
    app, _ = app_at(root, model, overrides)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    (root / "endpoint.json").write_text(json.dumps({"port": sock.getsockname()[1]}))
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
    finally:
        sock.close()
        overrides.undo()


if __name__ == "__main__":
    main()
