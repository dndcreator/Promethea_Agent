"""


"""
import os
import asyncio
import websockets
import json
import uuid


class GatewayBasicTests:
    """TODO: add docstring."""
    
    def __init__(self, ws_url="ws://127.0.0.1:8000/gateway/ws"):
        self.ws_url = ws_url
        self.websocket = None
        self.device_id = str(uuid.uuid4())
        self.connection_id = None
        
    async def connect(self):
        """TODO: add docstring."""
        print("\n[1] ?)
        print(f"? {self.ws_url}")
        
        try:
            self.websocket = await websockets.connect(self.ws_url)
            print("?WebSocket")
            
            # TODO: comment cleaned
            connect_msg = {
                "type": "req",
                "id": str(uuid.uuid4()),
                "method": "connect",
                "params": {
                    "identity": {
                        "device_id": self.device_id,
                        "device_name": "?,
                        "device_type": "desktop",
                        "role": "client"
                    },
                    "protocol_version": "1.0"
                }
            }
            
            await self.websocket.send(json.dumps(connect_msg, ensure_ascii=False))
            response = await self.websocket.recv()
            resp_data = json.loads(response)
            
            if resp_data.get("ok"):
                self.connection_id = resp_data.get("payload", {}).get("connection_id")
                print(f"?")
                print(f"  ID: {self.connection_id}")
                return True
            else:
                print(f"?: {resp_data.get('error')}")
                return False
                
        except Exception as e:
            print(f"?: {e}")
            return False
    
    async def test_health(self):
        """TODO: add docstring."""
        print("\n[2] ?)
        
        try:
            request = {
                "type": "req",
                "id": str(uuid.uuid4()),
                "method": "health",
                "params": {}
            }
            
            await self.websocket.send(json.dumps(request))
            response = await self.websocket.recv()
            resp_data = json.loads(response)
            
            if resp_data.get("ok"):
                payload = resp_data.get("payload", {})
                print(f"?")
                print(f"  ? {payload.get('status')}")
                print(f"  : {payload.get('uptime', 0):.2f}?)
                print(f"  : {payload.get('active_connections')}")
                return True
            else:
                print(f"?? {resp_data.get('error')}")
                return False
                
        except Exception as e:
            print(f"?? {e}")
            return False
    
    async def test_status(self):
        """TODO: add docstring."""
        print("\n[3] ?)
        
        try:
            request = {
                "type": "req",
                "id": str(uuid.uuid4()),
                "method": "status",
                "params": {}
            }
            
            await self.websocket.send(json.dumps(request))
            response = await self.websocket.recv()
            resp_data = json.loads(response)
            
            if resp_data.get("ok"):
                payload = resp_data.get("payload", {})
                print(f"??)
                print(f"  ? {payload.get('gateway_status')}")
                print(f"  ? {payload.get('connections')}")
                
                channels = payload.get('channels', {})
                print(f"  ? {len(channels)}")
                for name, info in channels.items():
                    print(f"    - {name}: {info.get('status')}")
                return True
            else:
                print(f"?? {resp_data.get('error')}")
                return False
                
        except Exception as e:
            print(f"?? {e}")
            return False
    
    async def test_system_info(self):
        """TODO: add docstring."""
        print("\n[4] ")
        
        try:
            request = {
                "type": "req",
                "id": str(uuid.uuid4()),
                "method": "system.info",
                "params": {}
            }
            
            await self.websocket.send(json.dumps(request))
            response = await self.websocket.recv()
            resp_data = json.loads(response)
            
            if resp_data.get("ok"):
                payload = resp_data.get("payload", {})
                print(f"?")
                print(f"  : {payload.get('version')}")
                print(f"  : {payload.get('uptime', 0):.2f}?)
                print(f"  : {', '.join(payload.get('channels', []))}")
                print(f"  : {', '.join(payload.get('features', []))}")
                return True
            else:
                print(f"?: {resp_data.get('error')}")
                return False
                
        except Exception as e:
            print(f"?: {e}")
            return False
    
    async def test_channels_status(self):
        """TODO: add docstring."""
        print("\n[5] ?)
        
        try:
            request = {
                "type": "req",
                "id": str(uuid.uuid4()),
                "method": "channels.status",
                "params": {}
            }
            
            await self.websocket.send(json.dumps(request))
            response = await self.websocket.recv()
            resp_data = json.loads(response)
            
            if resp_data.get("ok"):
                channels = resp_data.get("payload", {}).get("channels", {})
                print(f"??)
                for name, info in channels.items():
                    print(f"  - {name}: {info.get('status')} ({info.get('type')})")
                return True
            else:
                print(f"?? {resp_data.get('error')}")
                return False
                
        except Exception as e:
            print(f"?? {e}")
            return False
    
    async def close(self):
        """TODO: add docstring."""
        if self.websocket:
            await self.websocket.close()
            print("\n??)
    
    async def run_all(self):
        """TODO: add docstring."""
        print("=" * 60)
        print("")
        print("=" * 60)
        
        results = []
        
        # TODO: comment cleaned
        if await self.connect():
            results.append(("?, True))
            
            # TODO: comment cleaned
            results.append(("?, await self.test_health()))
            results.append(("?, await self.test_status()))
            results.append(("", await self.test_system_info()))
            results.append(("?, await self.test_channels_status()))
        else:
            results.append(("?, False))
        
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
        
        print(f"\n: {passed}/{total}  ({passed*100//total}%)")
        
        return passed == total


async def main():
    """TODO: add docstring."""
    if os.getenv("PROMETHEA_LIVE_TEST") != "1":
        print("SKIP: set PROMETHEA_LIVE_TEST=1 to run live gateway tests")
        return 0
    tester = GatewayBasicTests()
    success = await tester.run_all()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

