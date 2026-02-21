"""
Agent
Agent
"""
import os
import asyncio
import websockets
import json
import uuid


class AgentIntegrationTests:
    """TODO: add docstring."""
    
    def __init__(self, ws_url="ws://127.0.0.1:8000/gateway/ws"):
        self.ws_url = ws_url
        self.websocket = None
        self.device_id = str(uuid.uuid4())
        
    async def connect(self):
        """TODO: add docstring."""
        self.websocket = await websockets.connect(self.ws_url)
        
        connect_msg = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "identity": {
                    "device_id": self.device_id,
                    "device_name": "Agent?,
                    "role": "client"
                }
            }
        }
        
        await self.websocket.send(json.dumps(connect_msg))
        response = await self.websocket.recv()
        return json.loads(response).get("ok", False)
    
    async def test_tools_list(self):
        """TODO: add docstring."""
        print("\n[1] ")
        
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "tools.list",
            "params": {}
        }
        
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        resp_data = json.loads(response)
        
        if resp_data.get("ok"):
            tools = resp_data.get("payload", {}).get("tools", [])
            print(f"? {len(tools)} ?)
            for tool in tools:
                print(f"  - {tool.get('service')}: {tool.get('description', 'N/A')}")
            return True
        else:
            print(f"?: {resp_data.get('error')}")
            return False
    
    async def test_sessions_list(self):
        """TODO: add docstring."""
        print("\n[2] ")
        
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "sessions.list",
            "params": {}
        }
        
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        resp_data = json.loads(response)
        
        if resp_data.get("ok"):
            sessions = resp_data.get("payload", {}).get("sessions", [])
            print(f"? {len(sessions)} ?)
            for i, session in enumerate(sessions[:3], 1):
                print(f"  {i}. {session.get('session_id', 'N/A')} - {session.get('message_count', 0)} ?)
            return True
        else:
            print(f"?: {resp_data.get('error')}")
            return False
    
    async def test_followup(self):
        """TODO: add docstring."""
        print("\n[3] ")
        
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "followup",
            "params": {
                "selected_text": "Python ",
                "query_type": "why",
                "session_id": "default"
            }
        }
        
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        resp_data = json.loads(response)
        
        if resp_data.get("ok"):
            payload = resp_data.get("payload", {})
            print(f"?")
            print(f"  : {payload.get('query', '')[:60]}...")
            print(f"  : {payload.get('response', '')[:100]}...")
            return True
        else:
            print(f"?: {resp_data.get('error')}")
            return False
    
    async def test_config_get(self):
        """TODO: add docstring."""
        print("\n[4] ")
        
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "config.get",
            "params": {}
        }
        
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        resp_data = json.loads(response)
        
        if resp_data.get("ok"):
            config = resp_data.get("payload", {})
            print(f"?")
            print(f"  : {config.get('api', {}).get('model', 'N/A')}")
            print(f"  : {config.get('api', {}).get('temperature', 'N/A')}")
            print(f"  : {'' if config.get('memory', {}).get('enabled') else ''}")
            return True
        else:
            print(f"?: {resp_data.get('error')}")
            return False
    
    async def test_config_reload(self):
        """TODO: add docstring."""
        print("\n[5] ?)
        
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "config.reload",
            "params": {}
        }
        
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        resp_data = json.loads(response)
        
        if resp_data.get("ok"):
            print(f"?")
            return True
        else:
            print(f"?: {resp_data.get('error')}")
            return False
    
    async def close(self):
        """TODO: add docstring."""
        if self.websocket:
            await self.websocket.close()
    
    async def run_all(self):
        """TODO: add docstring."""
        print("=" * 60)
        print("Agent")
        print("=" * 60)
        
        if not await self.connect():
            print("?")
            return False
        
        print("?")
        
        results = []
        results.append(("", await self.test_tools_list()))
        results.append(("", await self.test_sessions_list()))
        results.append(("", await self.test_followup()))
        results.append(("", await self.test_config_get()))
        results.append(("", await self.test_config_reload()))
        
        await self.close()
        
        # TODO: comment cleaned
        print("\n" + "=" * 60)
        print("?)
        print("=" * 60)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "?" if result else "?"
            print(f"{test_name}: {status}")
        
        print(f"\n: {passed}/{total}  ({passed*100//total if total > 0 else 0}%)")
        
        return passed == total


async def main():
    """TODO: add docstring."""
    if os.getenv("PROMETHEA_LIVE_TEST") != "1":
        print("SKIP: set PROMETHEA_LIVE_TEST=1 to run live agent integration tests")
        return 0
    tester = AgentIntegrationTests()
    success = await tester.run_all()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

