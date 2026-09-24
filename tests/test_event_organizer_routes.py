from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_user
from tests._supabase_mock import make_table_router


client = TestClient(app)


ORGANIZER_SUMMARY = {
    "id": "u1",
    "username": "jill5",
    "full_name": "Jill Five",
    "display_name": "jill5",
    "avatar_kind": "icon",
    "icon_id": "icon_fox",
    "avatar_url": None,
}

OTHER_ORGANIZER_SUMMARY = {
    "id": "u2",
    "username": "tom9",
    "full_name": "Tom Nine",
    "display_name": "tom9",
    "avatar_kind": "icon",
    "icon_id": "icon_owl",
    "avatar_url": None,
}


# ────────────────────────────────────────────────────────────────────────────
# GET /api/events/{event_id}
# ────────────────────────────────────────────────────────────────────────────

class TestGetEventRouteOrganizer:
    def test_public_event_exposes_organizer_no_participant_data(self):
        event = {"id": "e1", "title": "Party", "created_by": "u1"}
        with patch(
            "app.api.v1.event_routes.get_event",
            return_value=event,
        ), patch(
            "app.services.event_service.get_user_summaries",
            create=True,
            return_value={"u1": ORGANIZER_SUMMARY},
        ) as mock_get_summaries:
            response = client.get("/api/events/e1")

        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"id", "title", "created_by", "organizer"}
        assert body["organizer"] == ORGANIZER_SUMMARY
        assert body["id"] == "e1"
        assert body["title"] == "Party"
        assert body["created_by"] == "u1"
        mock_get_summaries.assert_called_once()


# ────────────────────────────────────────────────────────────────────────────
# GET /api/events/
# ────────────────────────────────────────────────────────────────────────────

class TestListEventsRouteOrganizer:
    def test_filter_call_exposes_organizer_on_each_item(self):
        rows = [
            {"id": "e1", "title": "Party", "created_by": "u1"},
            {"id": "e2", "title": "Concert", "created_by": "u2"},
        ]
        response_body = {"page": 1, "limit": 10, "data": rows}
        with patch(
            "app.api.v1.event_routes.list_events",
            return_value=response_body,
        ), patch(
            "app.services.event_service.get_user_summaries",
            create=True,
            return_value={"u1": ORGANIZER_SUMMARY, "u2": OTHER_ORGANIZER_SUMMARY},
        ) as mock_get_summaries:
            response = client.get("/api/events/")

        assert response.status_code == 200
        body = response.json()
        assert body["page"] == 1
        assert body["limit"] == 10
        assert body["data"][0]["organizer"] == ORGANIZER_SUMMARY
        assert body["data"][1]["organizer"] == OTHER_ORGANIZER_SUMMARY
        for original, item in zip(rows, body["data"]):
            for key, value in original.items():
                assert item[key] == value
        mock_get_summaries.assert_called_once()

    def test_search_call_with_missing_created_by_triggers_backfill(self):
        rows = [{"id": "e1", "title": "Outdoor Fest", "status": "active"}]
        response_body = {"page": 1, "limit": 10, "data": rows}

        mock_sb, chains = make_table_router()
        chains["events"].execute.return_value = MagicMock(
            data=[{"id": "e1", "created_by": "u1"}]
        )

        with patch(
            "app.api.v1.event_routes.list_events",
            return_value=response_body,
        ), patch(
            "app.services.event_service.supabase", mock_sb
        ), patch(
            "app.services.event_service.get_user_summaries",
            create=True,
            return_value={"u1": ORGANIZER_SUMMARY},
        ) as mock_get_summaries:
            response = client.get("/api/events/", params={"search": "outdoor festival"})

        assert response.status_code == 200
        body = response.json()
        assert body["data"][0]["organizer"] == ORGANIZER_SUMMARY
        assert body["data"][0]["id"] == "e1"
        assert body["data"][0]["title"] == "Outdoor Fest"
        assert "created_by" not in body["data"][0]
        mock_get_summaries.assert_called_once()

        event_query_count = [c.args[0] for c in mock_sb.table.call_args_list].count("events")
        assert event_query_count == 1


# ────────────────────────────────────────────────────────────────────────────
# GET /api/events/my-events
# ────────────────────────────────────────────────────────────────────────────

class TestMyEventsRouteOrganizer:
    def test_my_events_exposes_organizer_on_each_item(self):
        rows = [{"id": "e1", "title": "Party", "created_by": "u1"}]
        response_body = {"status": "success", "total_count": 1, "data": rows}

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        try:
            with patch(
                "app.api.v1.event_routes.get_all_events_by_user",
                return_value=response_body,
            ), patch(
                "app.services.event_service.get_user_summaries",
                create=True,
                return_value={"u1": ORGANIZER_SUMMARY},
            ) as mock_get_summaries:
                response = client.get(
                    "/api/events/my-events",
                    headers={"Authorization": "Bearer token"},
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["total_count"] == 1
        assert body["data"][0]["organizer"] == ORGANIZER_SUMMARY
        assert body["data"][0]["id"] == "e1"
        assert body["data"][0]["title"] == "Party"
        mock_get_summaries.assert_called_once()


# ────────────────────────────────────────────────────────────────────────────
# GET /api/favorites/all
# ────────────────────────────────────────────────────────────────────────────

class TestSavedEventsRouteOrganizer:
    def test_saved_events_exposes_organizer_on_each_item(self):
        rows = [{"id": "e1", "title": "Party", "created_by": "u1"}]

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        try:
            with patch(
                "app.api.v1.saved_event_routes.get_saved_events",
                return_value=rows,
            ), patch(
                "app.services.event_service.get_user_summaries",
                create=True,
                return_value={"u1": ORGANIZER_SUMMARY},
            ) as mock_get_summaries:
                response = client.get(
                    "/api/favorites/all",
                    headers={"Authorization": "Bearer token"},
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200
        body = response.json()
        assert body[0]["organizer"] == ORGANIZER_SUMMARY
        assert body[0]["id"] == "e1"
        assert body[0]["title"] == "Party"
        mock_get_summaries.assert_called_once()


# ────────────────────────────────────────────────────────────────────────────
# GET /api/recommendations
# ────────────────────────────────────────────────────────────────────────────

class TestRecommendationsRouteOrganizer:
    def test_recommendations_missing_created_by_triggers_backfill(self):
        rows = [{"id": "e1", "title": "Outdoor Fest", "status": "active"}]
        response_body = {"user_id": "u1", "total": 1, "data": rows}

        mock_sb, chains = make_table_router()
        chains["events"].execute.return_value = MagicMock(
            data=[{"id": "e1", "created_by": "u1"}]
        )

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        try:
            with patch(
                "app.api.v1.recommendation_routes.get_recommendations",
                return_value=response_body,
            ), patch(
                "app.services.event_service.supabase", mock_sb
            ), patch(
                "app.services.event_service.get_user_summaries",
                create=True,
                return_value={"u1": ORGANIZER_SUMMARY},
            ) as mock_get_summaries:
                response = client.get(
                    "/api/recommendations",
                    headers={"Authorization": "Bearer token"},
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == "u1"
        assert body["total"] == 1
        assert body["data"][0]["organizer"] == ORGANIZER_SUMMARY
        assert body["data"][0]["id"] == "e1"
        assert body["data"][0]["title"] == "Outdoor Fest"
        assert "created_by" not in body["data"][0]
        mock_get_summaries.assert_called_once()

        event_query_count = [c.args[0] for c in mock_sb.table.call_args_list].count("events")
        assert event_query_count == 1


# ────────────────────────────────────────────────────────────────────────────
# GET /api/participants/my/events
# ────────────────────────────────────────────────────────────────────────────

class TestMyParticipantEventsRouteOrganizer:
    def test_events_get_organizer_and_none_row_unchanged(self):
        rows = [
            {"event_id": "e1", "events": {"id": "e1", "title": "Party", "created_by": "u1"}},
            {"event_id": "e2", "events": None},
        ]

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        try:
            with patch(
                "app.api.v1.participant_routes.get_my_events",
                return_value=rows,
            ), patch(
                "app.services.event_service.get_user_summaries",
                create=True,
                return_value={"u1": ORGANIZER_SUMMARY},
            ) as mock_get_summaries:
                response = client.get(
                    "/api/participants/my/events",
                    headers={"Authorization": "Bearer token"},
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200
        body = response.json()
        assert body[0]["event_id"] == "e1"
        assert body[0]["events"]["organizer"] == ORGANIZER_SUMMARY
        assert body[0]["events"]["id"] == "e1"
        assert body[0]["events"]["title"] == "Party"
        assert body[1]["event_id"] == "e2"
        assert body[1]["events"] is None
        mock_get_summaries.assert_called_once()

    def test_events_embed_as_single_item_list_still_gets_organizer(self):
        rows = [
            {"event_id": "e3", "events": [{"id": "e3", "title": "Gig", "created_by": "u1"}]},
        ]

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        try:
            with patch(
                "app.api.v1.participant_routes.get_my_events",
                return_value=rows,
            ), patch(
                "app.services.event_service.get_user_summaries",
                create=True,
                return_value={"u1": ORGANIZER_SUMMARY},
            ) as mock_get_summaries:
                response = client.get(
                    "/api/participants/my/events",
                    headers={"Authorization": "Bearer token"},
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body[0]["events"], list)
        assert len(body[0]["events"]) == 1
        assert body[0]["events"][0]["organizer"] == ORGANIZER_SUMMARY
        mock_get_summaries.assert_called_once()
