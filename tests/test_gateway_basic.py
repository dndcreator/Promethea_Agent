"""
网关基础功能测试
测试连接、健康检查、状态查询等基本功能
"""
import os
import asyncio
import websockets
import json
import uuid


class GatewayBasicTests:
    """网关基础测试"""
    
    def __init__(self, ws_url="ws://127.0.0.1:8000/gateway/ws"):
        self.ws_url = ws_url
        self.websocket = None
        self.device_id = str(uuid.uuid4())
        self.connection_id = None
        
    async def connect(self):
        """测试1: 连接和握手"""
        print("\n[测试1] 连接和握手")
        print(f"连接到: {self.ws_url}")
        
        try:
            self.websocket = await websockets.connect(self.ws_url)
            print("✓ WebSocket连接成功")
            
            # 发送connect请求
            connect_msg = {
                "type": "req",
                "id": str(uuid.uuid4()),
                "method": "connect",
                "params": {
                    "identity": {
                        "device_id": self.device_id,
                        "device_name": "测试客户端",
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
                print(f"✓ 连接握手成功")
                print(f"  连接ID: {self.connection_id}")
                return True
            else:
                print(f"✗ 连接握手失败: {resp_data.get('error')}")
                return False
                
        except Exception as e:
            print(f"✗ 连接失败: {e}")
            return False
    
    async def test_health(self):
        """测试2: 健康检查"""
        print("\n[测试2] 健康检查")
        
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
                print(f"✓ 健康检查通过")
                print(f"  状态: {payload.get('status')}")
                print(f"  运行时间: {payload.get('uptime', 0):.2f}秒")
                print(f"  活跃连接: {payload.get('active_connections')}")
                return True
            else:
                print(f"✗ 健康检查失败: {resp_data.get('error')}")
                return False
                
        except Exception as e:
            print(f"✗ 健康检查异常: {e}")
            return False
    
    async def test_status(self):
        """测试3: 状态查询"""
        print("\n[测试3] 状态查询")
        
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
                print(f"✓ 状态查询成功")
                print(f"  网关状态: {payload.get('gateway_status')}")
                print(f"  连接数: {payload.get('connections')}")
                
                channels = payload.get('channels', {})
                print(f"  通道数: {len(channels)}")
                for name, info in channels.items():
                    print(f"    - {name}: {info.get('status')}")
                return True
            else:
                print(f"✗ 状态查询失败: {resp_data.get('error')}")
                return False
                
        except Exception as e:
            print(f"✗ 状态查询异常: {e}")
            return False
    
    async def test_system_info(self):
        """测试4: 系统信息"""
        print("\n[测试4] 系统信息")
        
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
                print(f"✓ 系统信息查询成功")
                print(f"  版本: {payload.get('version')}")
                print(f"  运行时间: {payload.get('uptime', 0):.2f}秒")
                print(f"  通道: {', '.join(payload.get('channels', []))}")
                print(f"  功能: {', '.join(payload.get('features', []))}")
                return True
            else:
                print(f"✗ 系统信息查询失败: {resp_data.get('error')}")
                return False
                
        except Exception as e:
            print(f"✗ 系统信息查询异常: {e}")
            return False
    
    async def test_channels_status(self):
        """测试5: 通道状态"""
        print("\n[测试5] 通道状态")
        
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
                print(f"✓ 通道状态查询成功")
                for name, info in channels.items():
                    print(f"  - {name}: {info.get('status')} ({info.get('type')})")
                return True
            else:
                print(f"✗ 通道状态查询失败: {resp_data.get('error')}")
                return False
                
        except Exception as e:
            print(f"✗ 通道状态查询异常: {e}")
            return False
    
    async def close(self):
        """关闭连接"""
        if self.websocket:
            await self.websocket.close()
            print("\n✓ 连接已关闭")
    
    async def run_all(self):
        """运行所有测试"""
        print("=" * 60)
        print("网关基础功能测试")
        print("=" * 60)
        
        results = []
        
        # 测试1: 连接
        if await self.connect():
            results.append(("连接和握手", True))
            
            # 测试2-5: 其他功能
            results.append(("健康检查", await self.test_health()))
            results.append(("状态查询", await self.test_status()))
            results.append(("系统信息", await self.test_system_info()))
            results.append(("通道状态", await self.test_channels_status()))
        else:
            results.append(("连接和握手", False))
        
        await self.close()
        
        # 输出测试结果
        print("\n" + "=" * 60)
        print("测试结果汇总")
        print("=" * 60)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "✓ 通过" if result else "✗ 失败"
            print(f"{test_name}: {status}")
        
        print(f"\n总计: {passed}/{total} 通过 ({passed*100//total}%)")
        
        return passed == total


async def main():
    """主函数"""
    if os.getenv("PROMETHEA_LIVE_TEST") != "1":
        print("SKIP: set PROMETHEA_LIVE_TEST=1 to run live gateway tests")
        return 0
    tester = GatewayBasicTests()
    success = await tester.run_all()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
