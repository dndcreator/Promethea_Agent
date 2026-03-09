"""Live websocket integration checks for the agent gateway."""

import asyncio
import json
import os
import uuid

import websockets


class AgentIntegrationTests:
    """Basic live integration checks over gateway websocket API."""

    def __init__(self, ws_url: str = "ws://127.0.0.1:8000/gateway/ws"):
        self.ws_url = ws_url
        self.websocket = None
        self.device_id = str(uuid.uuid4())

    async def connect(self) -> bool:
        self.websocket = await websockets.connect(self.ws_url)
        connect_msg = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "identity": {
                    "device_id": self.device_id,
                    "device_name": "Agent Client",
                    "role": "client",
                }
            },
        }
        await self.websocket.send(json.dumps(connect_msg))
        response = await self.websocket.recv()
        return bool(json.loads(response).get("ok", False))

    async def test_tools_list(self) -> bool:
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "tools.list",
            "params": {},
        }
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        return bool(json.loads(response).get("ok"))

    async def test_sessions_list(self) -> bool:
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "sessions.list",
            "params": {},
        }
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        return bool(json.loads(response).get("ok"))

    async def test_followup(self) -> bool:
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "followup",
            "params": {
                "selected_text": "Python async programming",
                "query_type": "why",
                "session_id": "default",
            },
        }
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        return bool(json.loads(response).get("ok"))

    async def test_config_get(self) -> bool:
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "config.get",
            "params": {},
        }
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        return bool(json.loads(response).get("ok"))

    async def test_config_reload(self) -> bool:
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "config.reload",
            "params": {},
        }
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        return bool(json.loads(response).get("ok"))

    async def close(self):
        if self.websocket:
            await self.websocket.close()

    async def run_all(self) -> bool:
        if not await self.connect():
            return False
        results = [
            await self.test_tools_list(),
            await self.test_sessions_list(),
            await self.test_followup(),
            await self.test_config_get(),
            await self.test_config_reload(),
        ]
        await self.close()
        return all(results)


async def main() -> int:
    if os.getenv("PROMETHEA_LIVE_TEST") != "1":
        print("SKIP: set PROMETHEA_LIVE_TEST=1 to run live agent integration tests")
        return 0
    tester = AgentIntegrationTests()
    success = await tester.run_all()
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
