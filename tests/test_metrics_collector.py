from gateway.http.metrics import MetricsCollector


def test_metrics_collector_exposes_llm_token_fields_and_ui_aliases():
    collector = MetricsCollector()
    collector.record_llm_call(duration=0.25, prompt_tokens=120, completion_tokens=30)

    stats = collector.get_stats()

    assert stats["llm"]["calls"] == 1
    assert stats["llm"]["total_calls"] == 1
    assert stats["llm"]["prompt_tokens"] == 120
    assert stats["llm"]["completion_tokens"] == 30
    assert stats["llm"]["total_tokens"] == 150
    assert stats["llm"]["avg_time_ms"] == 250
    assert stats["llm"]["average_latency_ms"] == 250
    assert stats["llm"]["estimated_cost"] > 0
    assert stats["cost"]["estimated_usd"] == stats["llm"]["estimated_cost"]
