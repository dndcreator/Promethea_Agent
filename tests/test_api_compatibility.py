"""
API?
REST API
"""
import os
try:
    import requests
except ModuleNotFoundError:  # live compatibility checks only
    requests = None
import json


class APICompatibilityTests:
    """TODO: add docstring."""
    
    def __init__(self, base_url="http://127.0.0.1:8000"):
        self.base_url = base_url
        
    def test_root(self):
        """TODO: add docstring."""
        print("\n[1] ?)
        
        try:
            response = requests.get(f"{self.base_url}/")
            if response.status_code == 200:
                data = response.json()
                print(f"??)
                print(f"  : {data.get('message', 'N/A')}")
                print(f"  : {data.get('version', 'N/A')}")
                return True
            else:
                print(f"?? {response.status_code}")
                return False
        except Exception as e:
            print(f"?? {e}")
            return False
    
    def test_health(self):
        """TODO: add docstring."""
        print("\n[2] ?)
        
        try:
            response = requests.get(f"{self.base_url}/health")
            if response.status_code == 200:
                data = response.json()
                print(f"??)
                print(f"  ? {data.get('status', 'N/A')}")
                print(f"  Agent: {data.get('agent_ready', 'N/A')}")
                return True
            else:
                print(f"?? {response.status_code}")
                return False
        except Exception as e:
            print(f"?? {e}")
            return False
    
    def test_system_info(self):
        """TODO: add docstring."""
        print("\n[3] ")
        
        try:
            response = requests.get(f"{self.base_url}/system/info")
            if response.status_code == 200:
                data = response.json()
                print(f"?")
                print(f"  : {data.get('version', 'N/A')}")
                print(f"  ? {len(data.get('available_services', []))}")
                return True
            else:
                print(f"?: {response.status_code}")
                return False
        except Exception as e:
            print(f"?: {e}")
            return False
    
    def test_gateway_status(self):
        """TODO: add docstring."""
        print("\n[4] ?)
        
        try:
            response = requests.get(f"{self.base_url}/gateway/status")
            if response.status_code == 200:
                data = response.json()
                print(f"??)
                print(f"  ? {data.get('status', 'N/A')}")
                print(f"  : {data.get('uptime', 0):.2f}?)
                print(f"  ? {len(data.get('channels', {}))}")
                return True
            else:
                print(f"?? {response.status_code}")
                return False
        except Exception as e:
            print(f"?? {e}")
            return False
    
    def test_sessions_endpoint(self):
        """TODO: add docstring."""
        print("\n[5] ")
        
        try:
            response = requests.get(f"{self.base_url}/api/sessions")
            if response.status_code == 200:
                data = response.json()
                print(f"?")
                print(f"  : {data.get('total', 0)}")
                return True
            else:
                print(f"?: {response.status_code}")
                return False
        except Exception as e:
            print(f"?: {e}")
            return False
    
    def test_docs_available(self):
        """TODO: add docstring."""
        print("\n[6] API")
        
        try:
            response = requests.get(f"{self.base_url}/docs")
            if response.status_code == 200:
                print(f"?API?)
                return True
            else:
                print(f"?API: {response.status_code}")
                return False
        except Exception as e:
            print(f"?API: {e}")
            return False
    
    def run_all(self):
        """Run all live API compatibility tests."""
        print("=" * 60)
        print("API?)
        print("=" * 60)
        print(f"URL: {self.base_url}")
        
        results = []
        results.append(("?, self.test_root()))
        results.append(("?, self.test_health()))
        results.append(("", self.test_system_info()))
        results.append(("?, self.test_gateway_status()))
        results.append(("", self.test_sessions_endpoint()))
        results.append(("API", self.test_docs_available()))
        
        # Print a summary of all test results
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


def main():
    """TODO: add docstring."""
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

