"""Live REST API compatibility checks."""

import os

try:
    import requests
except ModuleNotFoundError:  # live compatibility checks only
    requests = None


class APICompatibilityTests:
    """Smoke tests for core REST endpoints."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url

    def _get_ok(self, path: str) -> bool:
        response = requests.get(f"{self.base_url}{path}", timeout=10)
        return response.status_code == 200

    def test_root(self) -> bool:
        return self._get_ok("/")

    def test_health(self) -> bool:
        return self._get_ok("/health")

    def test_system_info(self) -> bool:
        return self._get_ok("/system/info")

    def test_gateway_status(self) -> bool:
        return self._get_ok("/gateway/status")

    def test_sessions_endpoint(self) -> bool:
        return self._get_ok("/api/sessions")

    def test_docs_available(self) -> bool:
        return self._get_ok("/docs")

    def run_all(self) -> bool:
        results = [
            self.test_root(),
            self.test_health(),
            self.test_system_info(),
            self.test_gateway_status(),
            self.test_sessions_endpoint(),
            self.test_docs_available(),
        ]
        return all(results)


def main() -> int:
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
    raise SystemExit(main())
