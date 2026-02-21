"""In-process metrics collector for HTTP and gateway stats."""

import time
from typing import Dict, Any
from datetime import datetime


class MetricsCollector:
    """Collect runtime counters and basic latency statistics."""
    
    def __init__(self):
        self.stats = {
            'llm_calls': 0,
            'llm_total_time': 0.0,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'memory_recalls': 0,
            'memory_total_time': 0.0,
            'memory_items_recalled': 0,
            'sessions_created': 0,
            'messages_total': 0,
            'http_requests_total': 0,
            'http_errors_total': 0,
            'http_latency_ms_total': 0.0,
            'http_latency_ms_count': 0,
            'start_time': datetime.now()
        }
        self.http_by_path: Dict[str, Dict[str, float]] = {}
    
    def record_llm_call(self, duration: float, prompt_tokens: int = 0, completion_tokens: int = 0):
        """Record one LLM call."""
        self.stats['llm_calls'] += 1
        self.stats['llm_total_time'] += duration
        self.stats['prompt_tokens'] += prompt_tokens
        self.stats['completion_tokens'] += completion_tokens
    
    def record_memory_recall(self, duration: float, items_count: int = 0):
        """Record one memory recall."""
        self.stats['memory_recalls'] += 1
        self.stats['memory_total_time'] += duration
        self.stats['memory_items_recalled'] += items_count
    
    def record_message(self):
        """Record one message event."""
        self.stats['messages_total'] += 1
    
    def record_session(self):
        """Record one created session."""
        self.stats['sessions_created'] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Return aggregated metrics snapshot."""
        total_tokens = self.stats['prompt_tokens'] + self.stats['completion_tokens']
        
        # Cost estimate uses placeholder pricing.
        estimated_cost = (
            self.stats['prompt_tokens'] / 1000 * 0.03 +
            self.stats['completion_tokens'] / 1000 * 0.06
        )
        
        uptime = (datetime.now() - self.stats['start_time']).total_seconds()
        
        return {
            'llm': {
                'calls': self.stats['llm_calls'],
                'avg_time_ms': round(self.stats['llm_total_time'] * 1000 / max(1, self.stats['llm_calls'])),
                'total_tokens': total_tokens,
                'prompt_tokens': self.stats['prompt_tokens'],
                'completion_tokens': self.stats['completion_tokens']
            },
            'memory': {
                'recalls': self.stats['memory_recalls'],
                'avg_time_ms': round(self.stats['memory_total_time'] * 1000 / max(1, self.stats['memory_recalls'])),
                'items_recalled': self.stats['memory_items_recalled']
            },
            'sessions': {
                'created': self.stats['sessions_created'],
                'messages': self.stats['messages_total']
            },
            'http': {
                'requests_total': self.stats['http_requests_total'],
                'errors_total': self.stats['http_errors_total'],
                'avg_time_ms': round(
                    self.stats['http_latency_ms_total']
                    / max(1, self.stats['http_latency_ms_count']),
                    2,
                ),
            },
            'cost': {
                'estimated_usd': round(estimated_cost, 4)
            },
            'uptime_seconds': round(uptime)
        }

    def record_http_request(self, method: str, path: str, status_code: int, duration_ms: float):
        self.stats['http_requests_total'] += 1
        self.stats['http_latency_ms_total'] += float(duration_ms)
        self.stats['http_latency_ms_count'] += 1
        if int(status_code) >= 400:
            self.stats['http_errors_total'] += 1

        key = f"{method} {path}"
        if key not in self.http_by_path:
            self.http_by_path[key] = {"count": 0, "latency_ms_total": 0.0, "errors": 0}
        self.http_by_path[key]["count"] += 1
        self.http_by_path[key]["latency_ms_total"] += float(duration_ms)
        if int(status_code) >= 400:
            self.http_by_path[key]["errors"] += 1

    def to_prometheus_text(self) -> str:
        lines = [
            "# HELP promethea_http_requests_total Total HTTP requests",
            "# TYPE promethea_http_requests_total counter",
            f"promethea_http_requests_total {self.stats['http_requests_total']}",
            "# HELP promethea_http_errors_total Total HTTP error responses",
            "# TYPE promethea_http_errors_total counter",
            f"promethea_http_errors_total {self.stats['http_errors_total']}",
            "# HELP promethea_http_request_duration_ms_total Total HTTP request latency in milliseconds",
            "# TYPE promethea_http_request_duration_ms_total counter",
            f"promethea_http_request_duration_ms_total {self.stats['http_latency_ms_total']}",
        ]
        for path, data in self.http_by_path.items():
            escaped = path.replace('"', '\\"')
            lines.append(
                f'promethea_http_requests_by_path_total{{path="{escaped}"}} {data["count"]}'
            )
            lines.append(
                f'promethea_http_errors_by_path_total{{path="{escaped}"}} {data["errors"]}'
            )
        return "\n".join(lines) + "\n"
    
    def reset(self):
        """Reset all counters."""
        self.__init__()


_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Return shared metrics collector singleton."""
    return _metrics_collector

