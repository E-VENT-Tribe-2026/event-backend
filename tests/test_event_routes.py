import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_user, get_current_onboarded_user


client = TestClient(app)


# ────────────────────────────────────────────────────────────────────────────
# GET /api/events/my-events
# ────────────────────────────────────────────────────────────────────────────

class TestMyEventsRoute:
    def test_returns_events_for_user(self):
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="u1")
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
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    def test_returns_500_and_logs_error_when_lookup_fails(self, caplog):
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="u1")
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
            app.dependency_overrides.pop(get_current_onboarded_user, None)


class TestEventListLive:
    def test_list_is_not_http_cached(self):
        with patch(
            "app.api.v1.event_routes.list_events",
            return_value={"page": 1, "limit": 10, "data": []},
        ), patch("app.api.v1.event_routes.attach_organizers"):
            slashed = client.get("/api/events/")
            bare = client.get("/api/events")
        assert slashed.status_code == 200
        assert bare.status_code == 200
        assert slashed.headers.get("Cache-Control") == "no-store"

    def test_event_date_query_is_passed_as_date(self):
        with patch(
            "app.api.v1.event_routes.list_events",
            return_value={"page": 1, "limit": 10, "data": []},
        ) as mock_list, patch("app.api.v1.event_routes.attach_organizers"):
            response = client.get("/api/events/?event_date=2026-10-20")
        assert response.status_code == 200
        assert mock_list.call_args.args[5] == "2026-10-20"


class TestEventBannerRoutes:
    BANNER = "https://cdn.example.com/storage/v1/object/public/avatars/u1/event-banner.png"

    def test_create_accepts_banner_url(self):
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="u1")
        try:
            with patch(
                "app.api.v1.event_routes.create_event",
                return_value={
                    "id": "e1",
                    "title": "Festival",
                    "banner": self.BANNER,
                    "banner_url": self.BANNER,
                },
            ) as mock_create:
                response = client.post(
                    "/api/events/",
                    json={
                        "title": "Festival",
                        "start_datetime": "2026-11-01T18:00:00Z",
                        "end_datetime": "2026-11-01T21:00:00Z",
                        "banner": self.BANNER,
                    },
                    headers={"Authorization": "Bearer token"},
                )
            assert response.status_code == 200
            body = response.json()
            assert body["banner"] == self.BANNER
            assert body["banner_url"] == self.BANNER
            assert mock_create.call_args.args[1]["banner"] == self.BANNER
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    def test_get_returns_banner(self):
        with patch(
            "app.api.v1.event_routes.get_event",
            return_value={
                "id": "e1",
                "title": "Festival",
                "banner": self.BANNER,
                "banner_url": self.BANNER,
            },
        ), patch("app.api.v1.event_routes.attach_organizers"):
            response = client.get("/api/events/e1")
        assert response.status_code == 200
        assert response.json()["banner"] == self.BANNER
        assert response.json()["banner_url"] == self.BANNER

    def test_list_returns_banner(self):
        with patch(
            "app.api.v1.event_routes.list_events",
            return_value={
                "page": 1,
                "limit": 10,
                "data": [{"id": "e1", "title": "Festival", "banner": self.BANNER, "banner_url": self.BANNER}],
            },
        ), patch("app.api.v1.event_routes.attach_organizers"):
            response = client.get("/api/events/")
        assert response.status_code == 200
        item = response.json()["data"][0]
        assert item["banner"] == self.BANNER
        assert item["banner_url"] == self.BANNER

    def test_upload_banner_stores_in_avatars_bucket(self):
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="u1")
        storage = MagicMock()
        storage.from_.return_value.upload.return_value = None
        storage.from_.return_value.get_public_url.return_value = self.BANNER
        try:
            with patch("app.api.v1.event_routes.supabase") as mock_sb:
                mock_sb.storage = storage
                response = client.post(
                    "/api/events/upload-banner",
                    files={"file": ("night.png", b"fake-image", "image/png")},
                    headers={"Authorization": "Bearer token"},
                )
            assert response.status_code == 200
            assert response.json() == {"banner": self.BANNER, "banner_url": self.BANNER}
            storage.from_.assert_called_with("avatars")
            uploaded = storage.from_.return_value.upload.call_args.kwargs
            assert uploaded["file_options"]["content-type"] == "image/png"
            assert uploaded["path"].startswith("u1/event-banner-")
            assert uploaded["path"].endswith(".png")
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    def test_upload_banner_rejects_unsupported_type(self):
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="u1")
        try:
            response = client.post(
                "/api/events/upload-banner",
                files={"file": ("notes.pdf", b"%PDF", "application/pdf")},
                headers={"Authorization": "Bearer token"},
            )
            assert response.status_code == 400
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)
