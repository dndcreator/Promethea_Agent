"""
Agent集成测试
测试Agent调用、工具系统、会话管理等功能
"""
import os
import asyncio
import websockets
import json
import uuid


class AgentIntegrationTests:
    """Agent集成测试"""
    
    def __init__(self, ws_url="ws://127.0.0.1:8000/gateway/ws"):
        self.ws_url = ws_url
        self.websocket = None
        self.device_id = str(uuid.uuid4())
        
    async def connect(self):
        """连接到网关"""
        self.websocket = await websockets.connect(self.ws_url)
        
        connect_msg = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "identity": {
                    "device_id": self.device_id,
                    "device_name": "Agent测试客户端",
                    "role": "client"
                }
            }
        }
        
        await self.websocket.send(json.dumps(connect_msg))
        response = await self.websocket.recv()
        return json.loads(response).get("ok", False)
    
    async def test_tools_list(self):
        """测试工具列表"""
        print("\n[测试1] 获取工具列表")
        
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
            print(f"✓ 工具列表查询成功，共 {len(tools)} 个工具")
            for tool in tools:
                print(f"  - {tool.get('service')}: {tool.get('description', 'N/A')}")
            return True
        else:
            print(f"✗ 工具列表查询失败: {resp_data.get('error')}")
            return False
    
    async def test_sessions_list(self):
        """测试会话列表"""
        print("\n[测试2] 获取会话列表")
        
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
            print(f"✓ 会话列表查询成功，共 {len(sessions)} 个会话")
            for i, session in enumerate(sessions[:3], 1):
                print(f"  {i}. {session.get('session_id', 'N/A')} - {session.get('message_count', 0)} 条消息")
            return True
        else:
            print(f"✗ 会话列表查询失败: {resp_data.get('error')}")
            return False
    
    async def test_followup(self):
        """测试追问功能"""
        print("\n[测试3] 追问功能")
        
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "followup",
            "params": {
                "selected_text": "Python 是一门面向对象的编程语言",
                "query_type": "why",
                "session_id": "default"
            }
        }
        
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        resp_data = json.loads(response)
        
        if resp_data.get("ok"):
            payload = resp_data.get("payload", {})
            print(f"✓ 追问功能测试成功")
            print(f"  查询: {payload.get('query', '')[:60]}...")
            print(f"  响应: {payload.get('response', '')[:100]}...")
            return True
        else:
            print(f"✗ 追问功能测试失败: {resp_data.get('error')}")
            return False
    
    async def test_config_get(self):
        """测试配置获取"""
        print("\n[测试4] 获取配置")
        
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
            print(f"✓ 配置获取成功")
            print(f"  模型: {config.get('api', {}).get('model', 'N/A')}")
            print(f"  温度: {config.get('api', {}).get('temperature', 'N/A')}")
            print(f"  记忆系统: {'启用' if config.get('memory', {}).get('enabled') else '禁用'}")
            return True
        else:
            print(f"✗ 配置获取失败: {resp_data.get('error')}")
            return False
    
    async def test_config_reload(self):
        """测试配置重载"""
        print("\n[测试5] 配置热重载")
        
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
            print(f"✓ 配置重载成功")
            return True
        else:
            print(f"✗ 配置重载失败: {resp_data.get('error')}")
            return False
    
    async def close(self):
        """关闭连接"""
        if self.websocket:
            await self.websocket.close()
    
    async def run_all(self):
        """运行所有测试"""
        print("=" * 60)
        print("Agent集成功能测试")
        print("=" * 60)
        
        if not await self.connect():
            print("✗ 连接失败")
            return False
        
        print("✓ 连接成功")
        
        results = []
        results.append(("工具列表", await self.test_tools_list()))
        results.append(("会话列表", await self.test_sessions_list()))
        results.append(("追问功能", await self.test_followup()))
        results.append(("配置获取", await self.test_config_get()))
        results.append(("配置重载", await self.test_config_reload()))
        
        await self.close()
        
        # 输出结果
        print("\n" + "=" * 60)
        print("测试结果汇总")
        print("=" * 60)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "✓ 通过" if result else "✗ 失败"
            print(f"{test_name}: {status}")
        
        print(f"\n总计: {passed}/{total} 通过 ({passed*100//total if total > 0 else 0}%)")
        
        return passed == total


async def main():
    """主函数"""
    if os.getenv("PROMETHEA_LIVE_TEST") != "1":
        print("SKIP: set PROMETHEA_LIVE_TEST=1 to run live agent integration tests")
        return 0
    tester = AgentIntegrationTests()
    success = await tester.run_all()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
