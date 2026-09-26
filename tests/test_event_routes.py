import logging
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_user


client = TestClient(app)


# ────────────────────────────────────────────────────────────────────────────
# GET /api/events/my-events
# ────────────────────────────────────────────────────────────────────────────

class TestMyEventsRoute:
    def test_returns_events_for_user(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        try:
            with patch(
                "app.api.v1.event_routes.get_all_events_by_user",
                return_value={"status": "success", "total_count": 0, "data": []},
            ):
                response = client.get(
                    "/api/events/my-events",
                    headers={"Authorization": "Bearer token"},
                )

            assert response.status_code == 200
            assert response.json() == {"status": "success", "total_count": 0, "data": []}
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_returns_500_and_logs_error_when_lookup_fails(self, caplog):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        try:
            with patch(
                "app.api.v1.event_routes.get_all_events_by_user",
                side_effect=Exception("boom"),
            ):
                with caplog.at_level(logging.ERROR, logger="app.api.v1.event_routes"):
                    response = client.get(
                        "/api/events/my-events",
                        headers={"Authorization": "Bearer token"},
                    )

            assert response.status_code == 500
            assert response.json()["detail"] == "Could not fetch events for user"
            error_records = [record for record in caplog.records if record.levelname == "ERROR"]
            assert len(error_records) >= 1
            assert error_records[0].exc_info is not None
        finally:
            app.dependency_overrides.pop(get_current_user, None)
