"""Live memory pipeline checks over websocket API."""

import asyncio
import json
import os
import uuid

import websockets


class MemorySystemTests:
    """Live checks for memory endpoints (requires running services)."""

    def __init__(self, ws_url: str = "ws://127.0.0.1:8000/gateway/ws"):
        self.ws_url = ws_url
        self.websocket = None
        self.test_session_id = "test_session_001"

    async def connect(self) -> bool:
        self.websocket = await websockets.connect(self.ws_url)
        connect_msg = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "identity": {
                    "device_id": str(uuid.uuid4()),
                    "device_name": "Memory Tester",
                    "role": "client",
                }
            },
        }
        await self.websocket.send(json.dumps(connect_msg))
        response = await self.websocket.recv()
        return bool(json.loads(response).get("ok"))

    async def _call_ok(self, method: str, params: dict | None = None) -> bool:
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params or {},
        }
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        return bool(json.loads(response).get("ok"))

    async def test_memory_graph(self) -> bool:
        return await self._call_ok("memory.graph", {"session_id": self.test_session_id})

    async def test_memory_cluster(self) -> bool:
        return await self._call_ok("memory.cluster", {"session_id": self.test_session_id})

    async def test_memory_summarize(self) -> bool:
        return await self._call_ok(
            "memory.summarize",
            {"session_id": self.test_session_id, "incremental": False},
        )

    async def test_memory_decay(self) -> bool:
        return await self._call_ok("memory.decay", {"session_id": self.test_session_id})

    async def test_memory_cleanup(self) -> bool:
        return await self._call_ok("memory.cleanup", {"session_id": self.test_session_id})

    async def close(self):
        if self.websocket:
            await self.websocket.close()

    async def run_all(self) -> bool:
        if not await self.connect():
            return False
        results = [
            await self.test_memory_graph(),
            await self.test_memory_cluster(),
            await self.test_memory_summarize(),
            await self.test_memory_decay(),
            await self.test_memory_cleanup(),
        ]
        await self.close()
        return all(results)


async def main() -> int:
    if os.getenv("PROMETHEA_LIVE_TEST") != "1":
        print("SKIP: set PROMETHEA_LIVE_TEST=1 to run live memory tests")
        return 0
    tester = MemorySystemTests()
    success = await tester.run_all()
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
