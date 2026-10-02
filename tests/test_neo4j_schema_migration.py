from memory.neo4j_connector import Neo4jConnector


class _Result:
    def __init__(self, record=None):
        self._record = record

    def single(self):
        return self._record

    def consume(self):
        return None


class _Session:
    def __init__(self, version):
        self.version = version
        self.queries = []

    def run(self, query):
        normalized = " ".join(str(query).split())
        self.queries.append(normalized)
        if "RETURN coalesce(s.version, 0) AS version" in normalized:
            return _Result({"version": self.version})
        return _Result()


def test_memory_schema_migration_backfills_legacy_message_fields_once():
    session = _Session(version=0)

    Neo4jConnector._migrate_schema(session)

    assert any("MATCH (m:Message)" in query for query in session.queries)
    assert any("SET s.version = 1" in query for query in session.queries)


def test_memory_schema_migration_skips_current_schema():
    session = _Session(version=1)

    Neo4jConnector._migrate_schema(session)

    assert not any("MATCH (m:Message)" in query for query in session.queries)
