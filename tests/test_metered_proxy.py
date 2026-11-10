"""Billing evidence must outlive disconnected product clients and failed requests."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading

import requests
import pytest

from tests.support.evaluation import Budget, BudgetExceeded
from tests.support.metered_proxy import MeteredProxy, image_reservation_limit


def test_official_flash_reserves_inline_images_without_discounting_text():
    image = "data:image/jpeg;base64," + "YWFh" * 5000
    payload = {"messages": [{"role": "user", "content": [
        {"type": "text", "text": image}, {"type": "image_url", "image_url": {"url": image}},
    ]}]}
    limit = image_reservation_limit("https://api.deepseek.com/v1", "deepseek-v4-flash")
    old = Budget.reservation(payload, 2048, (1, 1))
    new = Budget.reservation(payload, 2048, (1, 1), image_token_limit=limit)
    assert new["input_bytes"] == old["input_bytes"]
    assert new["reserved_tokens"] == old["reserved_tokens"] - 20000 + 1024
    guard = Budget(max_tokens=100000, max_cost_usd=new["reserved_cost_usd"] - .000001)
    with pytest.raises(BudgetExceeded, match="currency"):
        guard.admit(payload, 2048, (1, 1), image_token_limit=limit)
    assert guard.calls == 0
    assert image_reservation_limit("https://api.deepseek.com.example/v1", "deepseek-v4-flash") is None
    assert image_reservation_limit("https://api.deepseek.com/v1", "deepseek-v4-pro") is None


@contextmanager
def upstream(*, fail=False, started=None, release=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if started:
                started.set()
                assert release.wait(5)
            if fail:
                self.send_error(500)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def proxy_at(endpoint, tmp_path, **kwargs):
    return MeteredProxy({"PROMETHEA_EVAL_AGENT_BASE_URL": endpoint, "PROMETHEA_EVAL_AGENT_API_KEY": "fixture",
                        "PROMETHEA_EVAL_AGENT_MODEL": "fixture"}, (1, 1), tmp_path, ceiling=.10, **kwargs)


def test_unknown_usage_stops_all_further_provider_sends(tmp_path):
    with upstream(fail=True) as (endpoint, calls):
        proxy = proxy_at(endpoint, tmp_path)
        with proxy.serve() as base:
            first = requests.post(base + "/chat/completions", json={"messages": [], "max_tokens": 10}, timeout=5)
            assert first.status_code == 403
            assert first.json()["error"]["code"] == "EVALUATION_ADMISSION_CLOSED"
            assert requests.post(base + "/chat/completions", json={"messages": [], "max_tokens": 10}, timeout=5).status_code == 403
    assert len(calls) == 1 and not proxy.budget.usage_known
    assert proxy.receipts[0]["usage"] is None
    assert proxy.receipts[0]["provider_http_status"] == 500


def test_shutdown_drains_background_request_even_after_client_disconnect(tmp_path):
    started, release = threading.Event(), threading.Event()
    with upstream(started=started, release=release) as (endpoint, calls):
        proxy = proxy_at(endpoint, tmp_path)
        with proxy.serve() as base:
            from urllib.parse import urlparse
            address = urlparse(base)
            client = socket.create_connection((address.hostname, address.port))
            body = b'{"messages": [], "max_tokens": 10}'
            client.sendall(b"POST /v1/chat/completions HTTP/1.0\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            assert started.wait(5)
            client.close()
            threading.Timer(.05, release.set).start()
        assert len(calls) == len(proxy.receipts) == proxy.budget.calls == 1
        assert proxy.budget.usage_known and proxy.budget.cost_usd == .000015
        assert json.loads((tmp_path / "requests.jsonl").read_text().splitlines()[-1])["state"] == "settled"


def test_restart_carries_spending_instead_of_renewing_authorization(tmp_path):
    prior = {"usage_known": True, "rates": (1, 1), "calls": 1, "conservative_cost_usd": .099999,
             "receipts": [{"id": "prior", "usage": {"prompt_tokens": 99999, "completion_tokens": 0}}]}
    with upstream() as (endpoint, calls):
        proxy = proxy_at(endpoint, tmp_path, carry=prior)
        with proxy.serve() as base:
            response = requests.post(base + "/chat/completions", json={"messages": [], "max_tokens": 10}, timeout=5)
        assert response.status_code == 403 and not calls
        assert response.json()["error"]["code"] == "EVALUATION_ADMISSION_CLOSED"
        assert proxy.budget.calls == 1 and proxy.budget.cost_usd == .099999
        assert proxy.receipts == prior["receipts"]


def test_condition_labels_share_one_budget_and_never_reach_the_model(tmp_path):
    with upstream() as (endpoint, calls):
        proxy = proxy_at(endpoint, tmp_path)
        with proxy.serve() as base:
            for label in ("baseline", "candidate"):
                with proxy.lock:
                    proxy.request_labels["opaque-" + label] = label
                response = requests.post(base + "/chat/completions", json={"messages": [], "max_tokens": 10},
                    headers={"Authorization": "Bearer opaque-" + label}, timeout=5)
                assert response.status_code == 200
            proxy.budget.max_cost_usd = proxy.budget.cost_usd
            assert requests.post(base + "/chat/completions", json={"messages": [], "max_tokens": 10}, timeout=5).status_code == 403
    assert proxy.budget.calls == len(calls) == 2
    assert proxy.budget.cost_usd == pytest.approx(.000030)
    assert [receipt["label"] for receipt in proxy.receipts] == ["baseline", "candidate"]
    assert all("label" not in request and "baseline" not in str(request) and "candidate" not in str(request) for request in calls)


@pytest.mark.parametrize("known,rates", [(False, (1, 1)), (True, (2, 1))])
def test_restart_rejects_unknown_spending_or_changed_rates(tmp_path, known, rates):
    with pytest.raises(ValueError):
        proxy_at("http://127.0.0.1:9/v1", tmp_path, carry={"usage_known": known, "rates": rates})
