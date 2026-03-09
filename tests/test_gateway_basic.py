"""Live websocket basic checks for gateway."""

import asyncio
import json
import os
import uuid

import websockets


class GatewayBasicTests:
    """Basic health/status checks on websocket gateway."""

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
                    "device_name": "Gateway Basic Tester",
                    "device_type": "desktop",
                    "role": "client",
                },
                "protocol_version": "1.0",
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

    async def test_health(self) -> bool:
        return await self._call_ok("health")

    async def test_status(self) -> bool:
        return await self._call_ok("status")

    async def test_system_info(self) -> bool:
        return await self._call_ok("system.info")

    async def test_channels_status(self) -> bool:
        return await self._call_ok("channels.status")

    async def close(self):
        if self.websocket:
            await self.websocket.close()

    async def run_all(self) -> bool:
        if not await self.connect():
            return False
        results = [
            await self.test_health(),
            await self.test_status(),
            await self.test_system_info(),
            await self.test_channels_status(),
        ]
        await self.close()
        return all(results)


async def main() -> int:
    if os.getenv("PROMETHEA_LIVE_TEST") != "1":
        print("SKIP: set PROMETHEA_LIVE_TEST=1 to run live gateway tests")
        return 0
    tester = GatewayBasicTests()
    success = await tester.run_all()
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
