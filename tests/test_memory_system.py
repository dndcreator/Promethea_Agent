"""
记忆系统测试
测试三层记忆架构功能
"""
import os
import asyncio
import websockets
import json
import uuid


class MemorySystemTests:
    """记忆系统测试"""
    
    def __init__(self, ws_url="ws://127.0.0.1:8000/gateway/ws"):
        self.ws_url = ws_url
        self.websocket = None
        self.test_session_id = "test_session_001"
        
    async def connect(self):
        """连接到网关"""
        self.websocket = await websockets.connect(self.ws_url)
        
        connect_msg = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "identity": {
                    "device_id": str(uuid.uuid4()),
                    "device_name": "记忆测试客户端",
                    "role": "client"
                }
            }
        }
        
        await self.websocket.send(json.dumps(connect_msg))
        response = await self.websocket.recv()
        return json.loads(response).get("ok", False)
    
    async def test_memory_graph(self):
        """测试记忆图查询"""
        print("\n[测试1] 记忆图查询")
        
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "memory.graph",
            "params": {"session_id": self.test_session_id}
        }
        
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        resp_data = json.loads(response)
        
        if resp_data.get("ok"):
            payload = resp_data.get("payload", {})
            stats = payload.get("stats", {})
            print(f"✓ 记忆图查询成功")
            print(f"  节点数: {stats.get('total_nodes', 0)}")
            print(f"  边数: {stats.get('total_edges', 0)}")
            return True
        else:
            print(f"✗ 记忆图查询失败: {resp_data.get('error')}")
            return False
    
    async def test_memory_cluster(self):
        """测试记忆聚类（温层）"""
        print("\n[测试2] 记忆聚类")
        
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "memory.cluster",
            "params": {"session_id": self.test_session_id}
        }
        
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        resp_data = json.loads(response)
        
        if resp_data.get("ok"):
            payload = resp_data.get("payload", {})
            print(f"✓ 记忆聚类成功")
            print(f"  新建概念: {payload.get('concepts_created', 0)}")
            print(f"  总概念数: {payload.get('total_concepts', 0)}")
            return True
        else:
            print(f"✗ 记忆聚类失败: {resp_data.get('error')}")
            return False
    
    async def test_memory_summarize(self):
        """测试记忆摘要（冷层）"""
        print("\n[测试3] 记忆摘要")
        
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "memory.summarize",
            "params": {
                "session_id": self.test_session_id,
                "incremental": False
            }
        }
        
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        resp_data = json.loads(response)
        
        if resp_data.get("ok"):
            payload = resp_data.get("payload", {})
            status = payload.get("status", "unknown")
            print(f"✓ 记忆摘要请求成功")
            print(f"  状态: {status}")
            if status != "skipped":
                print(f"  摘要ID: {payload.get('summary_id', 'N/A')}")
            return True
        else:
            print(f"✗ 记忆摘要失败: {resp_data.get('error')}")
            return False
    
    async def test_memory_decay(self):
        """测试记忆衰减（遗忘）"""
        print("\n[测试4] 记忆衰减")
        
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "memory.decay",
            "params": {"session_id": self.test_session_id}
        }
        
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        resp_data = json.loads(response)
        
        if resp_data.get("ok"):
            payload = resp_data.get("payload", {})
            print(f"✓ 记忆衰减成功")
            print(f"  已衰减节点: {payload.get('decayed_nodes', 0)}")
            return True
        else:
            print(f"✗ 记忆衰减失败: {resp_data.get('error')}")
            return False
    
    async def test_memory_cleanup(self):
        """测试记忆清理"""
        print("\n[测试5] 记忆清理")
        
        request = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "memory.cleanup",
            "params": {"session_id": self.test_session_id}
        }
        
        await self.websocket.send(json.dumps(request))
        response = await self.websocket.recv()
        resp_data = json.loads(response)
        
        if resp_data.get("ok"):
            payload = resp_data.get("payload", {})
            print(f"✓ 记忆清理成功")
            print(f"  已清理节点: {payload.get('cleaned_nodes', 0)}")
            return True
        else:
            print(f"✗ 记忆清理失败: {resp_data.get('error')}")
            return False
    
    async def close(self):
        """关闭连接"""
        if self.websocket:
            await self.websocket.close()
    
    async def run_all(self):
        """运行所有测试"""
        print("=" * 60)
        print("记忆系统功能测试")
        print("=" * 60)
        print(f"测试会话: {self.test_session_id}")
        
        if not await self.connect():
            print("✗ 连接失败")
            return False
        
        print("✓ 连接成功")
        
        results = []
        results.append(("记忆图查询", await self.test_memory_graph()))
        results.append(("记忆聚类", await self.test_memory_cluster()))
        results.append(("记忆摘要", await self.test_memory_summarize()))
        results.append(("记忆衰减", await self.test_memory_decay()))
        results.append(("记忆清理", await self.test_memory_cleanup()))
        
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
        print("\n注意: 如果记忆系统未启用，某些测试会失败")
        
        return passed == total


async def main():
    """主函数"""
    if os.getenv("PROMETHEA_LIVE_TEST") != "1":
        print("SKIP: set PROMETHEA_LIVE_TEST=1 to run live memory tests (requires Neo4j + running server)")
        return 0
    tester = MemorySystemTests()
    success = await tester.run_all()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
