from gateway.http.message_manager import MessageManager


class _NoopStore:
    def __init__(self):
        self.last = {}

    def load_all(self):
        return {}

    def save_all(self, sessions):
        self.last = sessions


def _build_manager() -> MessageManager:
    mgr = MessageManager()
    mgr.session_store = _NoopStore()
    mgr.session = {}
    mgr.memory_adapter = None
    return mgr


def test_turn_commit_is_atomic():
    mgr = _build_manager()
    sid = mgr.create_session("s1", user_id="u1")

    assert mgr.begin_turn(sid, "t1", "user", "hello", "u1")
    # TODO: comment cleaned

    assert mgr.commit_turn(sid, "t1", "world", user_id="u1")
    msgs = mgr.get_messages(sid, user_id="u1")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user" and msgs[0]["content"] == "hello"
    assert msgs[1]["role"] == "assistant" and msgs[1]["content"] == "world"


def test_turn_commit_idempotent_no_duplicate():
    mgr = _build_manager()
    sid = mgr.create_session("s1", user_id="u1")

    assert mgr.begin_turn(sid, "t1", "user", "hello", "u1")
    assert mgr.commit_turn(sid, "t1", "world", user_id="u1")
    # TODO: comment cleaned

    msgs = mgr.get_messages(sid, user_id="u1")
    assert len(msgs) == 2


def test_turn_abort_removes_pending():
    mgr = _build_manager()
    sid = mgr.create_session("s1", user_id="u1")

    assert mgr.begin_turn(sid, "t1", "user", "hello", "u1")
    assert mgr.abort_turn(sid, "t1", user_id="u1")
    # TODO: comment cleaned
    assert mgr.get_messages(sid, user_id="u1") == []
