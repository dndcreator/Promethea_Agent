"""Explicitly opt-in, read-only deployment checks; never mutate personal memory."""
import os

import pytest
import requests


pytestmark = [pytest.mark.live, pytest.mark.skipif(os.environ.get("PROMETHEA_LIVE_TEST") != "1", reason="deployment checks require explicit --live")]


@pytest.mark.parametrize("path", ["/health", "/api/ops/readiness"])
def test_readiness(path):
    base = os.environ.get("PROMETHEA_TEST_BASE_URL")
    if not base:
        pytest.fail("Set PROMETHEA_TEST_BASE_URL explicitly; no implicit personal deployment")
    response = requests.get(base.rstrip("/") + path, timeout=10)
    assert response.status_code == 200, response.text[:300]
    assert isinstance(response.json(), dict)


def test_authenticated_profile_and_session_listing():
    base = os.environ.get("PROMETHEA_TEST_BASE_URL")
    token = os.environ.get("PROMETHEA_TEST_TOKEN")
    if not base or not token:
        pytest.fail("Set PROMETHEA_TEST_BASE_URL and PROMETHEA_TEST_TOKEN for a dedicated test account")
    with requests.Session() as client:
        client.headers["Authorization"] = f"Bearer {token}"
        profile = client.get(base.rstrip("/") + "/api/user/profile", timeout=10)
        assert profile.status_code == 200
        assert profile.json().get("user_id")
        sessions = client.get(base.rstrip("/") + "/api/sessions", timeout=10)
        assert sessions.status_code == 200
        assert isinstance(sessions.json().get("sessions"), (list, dict))
