"""
API兼容性测试
验证原有REST API端点仍然正常工作
"""
import os
try:
    import requests
except ModuleNotFoundError:  # live compatibility checks only
    requests = None
import json


class APICompatibilityTests:
    """API兼容性测试"""
    
    def __init__(self, base_url="http://127.0.0.1:8000"):
        self.base_url = base_url
        
    def test_root(self):
        """测试根端点"""
        print("\n[测试1] 根端点")
        
        try:
            response = requests.get(f"{self.base_url}/")
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 根端点正常")
                print(f"  消息: {data.get('message', 'N/A')}")
                print(f"  版本: {data.get('version', 'N/A')}")
                return True
            else:
                print(f"✗ 根端点失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 根端点异常: {e}")
            return False
    
    def test_health(self):
        """测试健康检查"""
        print("\n[测试2] 健康检查端点")
        
        try:
            response = requests.get(f"{self.base_url}/health")
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 健康检查正常")
                print(f"  状态: {data.get('status', 'N/A')}")
                print(f"  Agent就绪: {data.get('agent_ready', 'N/A')}")
                return True
            else:
                print(f"✗ 健康检查失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 健康检查异常: {e}")
            return False
    
    def test_system_info(self):
        """测试系统信息"""
        print("\n[测试3] 系统信息端点")
        
        try:
            response = requests.get(f"{self.base_url}/system/info")
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 系统信息正常")
                print(f"  版本: {data.get('version', 'N/A')}")
                print(f"  服务数: {len(data.get('available_services', []))}")
                return True
            else:
                print(f"✗ 系统信息失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 系统信息异常: {e}")
            return False
    
    def test_gateway_status(self):
        """测试网关状态端点"""
        print("\n[测试4] 网关状态端点")
        
        try:
            response = requests.get(f"{self.base_url}/gateway/status")
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 网关状态正常")
                print(f"  状态: {data.get('status', 'N/A')}")
                print(f"  运行时间: {data.get('uptime', 0):.2f}秒")
                print(f"  通道数: {len(data.get('channels', {}))}")
                return True
            else:
                print(f"✗ 网关状态失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 网关状态异常: {e}")
            return False
    
    def test_sessions_endpoint(self):
        """测试会话端点"""
        print("\n[测试5] 会话列表端点")
        
        try:
            response = requests.get(f"{self.base_url}/api/sessions")
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 会话列表正常")
                print(f"  总会话数: {data.get('total', 0)}")
                return True
            else:
                print(f"✗ 会话列表失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 会话列表异常: {e}")
            return False
    
    def test_docs_available(self):
        """测试API文档"""
        print("\n[测试6] API文档端点")
        
        try:
            response = requests.get(f"{self.base_url}/docs")
            if response.status_code == 200:
                print(f"✓ API文档可访问")
                return True
            else:
                print(f"✗ API文档失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ API文档异常: {e}")
            return False
    
    def run_all(self):
        """Run all live API compatibility tests."""
        print("=" * 60)
        print("API兼容性测试")
        print("=" * 60)
        print(f"基础URL: {self.base_url}")
        
        results = []
        results.append(("根端点", self.test_root()))
        results.append(("健康检查", self.test_health()))
        results.append(("系统信息", self.test_system_info()))
        results.append(("网关状态", self.test_gateway_status()))
        results.append(("会话列表", self.test_sessions_endpoint()))
        results.append(("API文档", self.test_docs_available()))
        
        # Print a summary of all test results
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


def main():
    """主函数"""
    if os.getenv("PROMETHEA_LIVE_TEST") != "1":
        print("SKIP: set PROMETHEA_LIVE_TEST=1 to run live API tests")
        return 0
    if requests is None:
        print("SKIP: install requests to run live API tests")
        return 0
    tester = APICompatibilityTests()
    success = tester.run_all()
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
