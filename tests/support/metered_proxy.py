"""Test-only transparent Chat Completions proxy with a shared fail-closed ledger."""
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from tests.support.evaluation import Budget, digest


def image_reservation_limit(endpoint, model):
    # https://api-docs.deepseek.com/guides/vision/#token-usage
    url = urlsplit(endpoint)
    if (url.scheme == "https" and url.netloc == "api.deepseek.com" and url.path in {"", "/v1"}
            and not url.query and not url.fragment and model in {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}):
        return 1024
    return None


class MeteredProxy:
    def __init__(self, values, rates, output, *, ceiling, carry=None):
        self.endpoint = values["PROMETHEA_EVAL_AGENT_BASE_URL"].rstrip("/")
        self.key = values["PROMETHEA_EVAL_AGENT_API_KEY"]
        self.model = values["PROMETHEA_EVAL_AGENT_MODEL"]
        self.image_token_limit = image_reservation_limit(self.endpoint, self.model)
        self.rates, self.output = rates, output
        self.budget = Budget(max_calls=12, max_tokens=500000, seconds=900, max_cost_usd=ceiling)
        self.lock = threading.Lock()
        self.receipts = []
        self.stop_reason = None
        self.request_labels = {}
        if carry:
            if not carry["usage_known"] or tuple(carry["rates"]) != tuple(rates):
                raise ValueError("cannot resume unknown billing or changed price ceilings")
            self.receipts = list(carry["receipts"])
            self.budget.calls = carry["calls"]
            self.budget.cost_usd = carry["conservative_cost_usd"]
            self.budget.tokens = sum(row["usage"]["prompt_tokens"] + row["usage"]["completion_tokens"] for row in self.receipts)

    def journal(self, value):
        self.output.mkdir(parents=True, exist_ok=True)
        with (self.output / "requests.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def reject(handler):
        body = json.dumps({"error": {"message": "Evaluation admission closed", "type": "evaluation_limit",
                                      "code": "EVALUATION_ADMISSION_CLOSED"}}).encode()
        handler.send_response(403)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def forward(self, handler, parameters):
        # Serialize admission through settlement, including calls from background services.
        with self.lock:
            token = handler.headers.get("Authorization", "").removeprefix("Bearer ")
            label = self.request_labels.get(token)
            tags = {"label": label} if label is not None else {}
            maximum = int(parameters.get("max_tokens") or parameters.get("max_completion_tokens") or 8192)
            parameters["model"] = self.model
            reserve = {}
            try:
                reserve = self.budget.reservation(parameters, maximum, self.rates, image_token_limit=self.image_token_limit)
                self.budget.admit(parameters, maximum, self.rates, image_token_limit=self.image_token_limit)
                identifier = uuid4().hex
                self.journal({"state": "pending", "id": identifier, "at": datetime.now(timezone.utc).isoformat(),
                              **tags, "request_hash": digest(parameters), "stream": bool(parameters.get("stream")),
                              "native": bool(parameters.get("tools")), **reserve})
            except Exception as exc:
                self.stop_reason = type(exc).__name__ + ": " + str(exc)
                self.journal({"state": "not_sent", "reason": self.stop_reason, **tags, **reserve})
                self.reject(handler)
                return
            usage, chunks, disconnected = None, 0, False
            headers_sent = False
            record = {"id": identifier, "stream": bool(parameters.get("stream")), "native": bool(parameters.get("tools")), **tags, **reserve}
            try:
                with requests.post(self.endpoint + "/chat/completions", json=parameters,
                                   headers={"Authorization": "Bearer " + self.key}, timeout=(10, 120), stream=True) as response:
                    record["provider_http_status"] = response.status_code
                    response.raise_for_status()
                    handler.send_response(response.status_code)
                    handler.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                    handler.send_header("Connection", "close")
                    headers_sent = True
                    handler.end_headers()
                    if parameters.get("stream"):
                        for line in response.iter_lines(chunk_size=1):
                            if line.startswith(b"data: ") and line != b"data: [DONE]":
                                packet = json.loads(line[6:])
                                usage = packet.get("usage") or usage
                                chunks += 1
                            if not disconnected:
                                try:
                                    handler.wfile.write(line + b"\n")
                                    handler.wfile.flush()
                                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                                    disconnected = True  # Drain upstream to resolve usage, never resend.
                    else:
                        body = response.content
                        usage = response.json().get("usage")
                        handler.wfile.write(body)
            except Exception as exc:
                record["error_type"] = type(exc).__name__
            self.budget.settle(usage, self.rates)
            record.update(usage=usage, chunks=chunks, client_disconnected=disconnected)
            self.receipts.append(record)
            self.journal({"state": "settled" if self.budget.usage_known else "unresolved", **record})
            if not self.budget.usage_known:
                self.stop_reason = "unknown provider usage; all further admissions closed"
                if not headers_sent:
                    self.reject(handler)

    @contextmanager
    def serve(self):
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return
                parameters = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                proxy.forward(self, parameters)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # A client/backend may exit before an auxiliary response. Drain the provider
        # and fsync its usage receipt before reporting or ending the test process.
        server.daemon_threads = False
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)
