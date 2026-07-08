import importlib
import os


def test_database_client_uses_database_url_when_host_missing(monkeypatch):
    monkeypatch.delenv("COCKROACH_HOST", raising=False)
    monkeypatch.delenv("COCKROACH_USER", raising=False)
    monkeypatch.setenv("COCKROACH_PASSWORD", "")
    monkeypatch.delenv("COCKROACH_PORT", raising=False)
    monkeypatch.delenv("COCKROACH_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://nzmarie:secret@example.cluster.cockroachlabs.cloud:26257/defaultdb?sslmode=verify-full")

    import utils.database as database_module
    database_module = importlib.reload(database_module)

    client = database_module.DatabaseClient()

    assert client.host == "example.cluster.cockroachlabs.cloud"
    assert client.port == "26257"
    assert client.dbname == "defaultdb"
    assert client.password == "secret"
    assert client.user == "nzmarie"
