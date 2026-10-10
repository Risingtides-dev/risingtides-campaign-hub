"""The public diagnostic never launches scraper probes or reveals config."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.parametrize("query", ["", "?run=1", "?run=true", "?run=yes", "?run=0"])
def test_public_cron_diag_retired_without_side_effects(client, monkeypatch, query):
    monkeypatch.setenv("TIKTOK_PROXY", "https://secret:password@example.invalid")
    monkeypatch.setenv("TIKTOK_COOKIES_FILE", "/private/cookies.txt")
    with patch("subprocess.run") as run, \
            patch("requests.sessions.Session.request") as request:
        for _ in range(2):
            response = client.get(f"/api/cron/diag{query}")
            assert response.status_code == 410
            assert response.get_json() == {"error": "Public cron diagnostic retired"}
            assert "secret" not in response.get_data(as_text=True)
        run.assert_not_called()
        request.assert_not_called()
