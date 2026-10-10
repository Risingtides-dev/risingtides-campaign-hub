"""The retired public toggle must never mutate a scheduler worker."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.parametrize("body", [
    None,
    {},
    {"enabled": True},
    {"enabled": False},
    {"enabled": "false"},
])
def test_toggle_retired_without_scheduler_mutation(client, body):
    with patch("campaign_manager.services.scheduler.toggle_scheduler") as toggle, \
            patch("campaign_manager.services.scheduler._scheduler") as scheduler:
        for _ in range(2):
            response = client.post("/api/cron/toggle", json=body)
            assert response.status_code == 410
            assert response.get_json() == {
                "error": "Scheduler toggle retired; configure SCHEDULER_ENABLED and restart the service",
            }
        toggle.assert_not_called()
        scheduler.pause.assert_not_called()
        scheduler.resume.assert_not_called()
