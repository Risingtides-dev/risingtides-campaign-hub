"""Public health diagnostics redact credentials using the runtime URL grammar."""

import pytest
from flask import Flask

from campaign_manager.blueprints import health as health_module


@pytest.mark.parametrize(
    "database_url, expected",
    [
        ("", ""),
        ("postgresql://synthetic-user:synthetic-secret@db.example.test/hub", "postgresql://db.example.test"),
        ("postgresql://synthetic-user:synthetic-secret#tail@db.example.test/hub", "postgresql://db.example.test"),
        ("postgresql://synthetic-user:synthetic-secret?tail@db.example.test/hub", "postgresql://db.example.test"),
        ("postgresql://synthetic-user:synthetic-secret%40tail@db.example.test/hub", "postgresql://db.example.test"),
        ("postgresql://synthetic-user:synthetic-secret@tail@db.example.test/hub", "set"),
        ("postgresql://synthetic-user:synthetic-secret@tail?fragment@db.example.test/hub", "set"),
        ("postgresql+psycopg2://synthetic-user:synthetic-secret@db.example.test:5432/hub", "postgresql+psycopg2://db.example.test"),
        ("postgres://synthetic-user:synthetic-secret@[2001:db8::1]:5432/hub", "postgres://2001:db8::1"),
        ("postgresql://db.example.test/hub?password=synthetic-secret", "postgresql://db.example.test"),
        # Extra raw @ is ambiguous even in a query; omit this diagnostic.
        ("postgresql://synthetic-user:synthetic-secret@db.example.test/hub?contact=synthetic@example.test", "set"),
        ("postgresql://synthetic-user:synthetic-secret@db.example.test/hub?contact=synthetic%40example.test", "postgresql://db.example.test"),
        ("sqlite:////private/synthetic-secret.db", "sqlite"),
        ("not-a-database-url-synthetic-secret", "set"),
    ],
)
def test_db_target_redacts_credentials(database_url, expected):
    assert health_module._safe_db_target(database_url) == expected


@pytest.mark.parametrize(
    "password, expected_target",
    [
        ("synthetic-secret#tail", "postgresql://db.example.test"),
        ("synthetic-secret?tail", "postgresql://db.example.test"),
        ("synthetic-secret@tail", "set"),
    ],
)
def test_public_health_redacts_runtime_accepted_password(monkeypatch, password, expected_target):
    monkeypatch.setenv("DATABASE_URL", f"postgresql://synthetic-user:{password}@db.example.test/hub")
    monkeypatch.setattr(health_module._db, "is_active", lambda: True)
    monkeypatch.setattr(health_module._db, "completion_status_repair_ok", lambda: True)
    app = Flask(__name__)
    app.register_blueprint(health_module.health_bp)
    response = app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "db_active": True,
        "db_url_set": True,
        "db_target": expected_target,
        "schema_repair": "ok",
    }
