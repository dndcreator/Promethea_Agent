from datetime import datetime

from memory.forgetting import ForgettingManager


class _FakeConnector:
    def __init__(self):
        self.calls = []

    def query(self, cypher, params=None):
        self.calls.append((cypher, params or {}))
        if "RETURN n.id as id, n.created_at as created_at" in cypher:
            return [
                {
                    "id": "entity_1",
                    "created_at": "2026-01-01T00:00:00",
                    "importance": 0.5,
                    "access_count": 0,
                }
            ]
        return []


def test_forgetting_session_query_includes_message_path():
    connector = _FakeConnector()
    mgr = ForgettingManager(connector)

    mgr.apply_time_decay(session_id="s1")

    query_text = connector.calls[0][0]
    assert "FROM_MESSAGE" in query_text
    assert "PART_OF_SESSION" in query_text


def test_forgetting_time_conversion_string_and_datetime():
    mgr = ForgettingManager(_FakeConnector())
    now = datetime.now()
    assert mgr._to_python_datetime(now) == now
    assert mgr._to_python_datetime("2026-01-01T00:00:00") == datetime(2026, 1, 1, 0, 0, 0)
