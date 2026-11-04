"""Ticket #236: gaps found in the review of the removal feature.

Uses the same cast and fake database as tests/test_content_removal.py.
"""
from pathlib import Path
from unittest.mock import patch

from tests.test_content_removal import (  # noqa: F401  (db is a pytest fixture)
    ADMIN, ADMIN2, EVENT, HEADERS, ORG, OTHER_EVENT, P1, app, client, code, current, db, msg, notes,
    remove_event, remove_message,
)

MIGRATION = Path("supabase/migrations/20261026120000_removed_events_and_messages.sql")


def _event(db, event_id):
    return next(e for e in db.tables["events"] if e["id"] == event_id)


def _fail_update_when(db, table_name, predicate, error=None):
    """Make update() on one table raise (or, without error, run unchanged) when predicate(payload)."""
    real_table = db.table

    def table(name):
        query = real_table(name)
        if name == table_name:
            real_update = query.update

            def update(payload):
                if predicate(payload):
                    if error:
                        raise error
                return real_update(payload)

            query.update = update
        return query

    return patch.object(db, "table", table)


class TestAuditAndFanOut:
    def test_audit_is_written_even_when_notifying_participants_fails(self, db):
        with patch("app.services.notification_service.create_notification", side_effect=RuntimeError("slow db")):
            r = remove_event()
        assert r.status_code == 200
        assert db.tables["logs"][0]["type"] == "event_removed"
        assert notes(db, P1) == []  # participants were not reached, but the removal stands

    def test_participants_are_notified_after_the_audit_entry(self, db):
        from app.services import content_removal_service as service

        order = []
        real_audit = service.record_audit

        def audit(*args, **kwargs):
            order.append("audit")
            return real_audit(*args, **kwargs)

        def notify(event):
            order.append("participants")
            return 0

        with patch.object(service, "record_audit", audit), patch.object(service, "_notify_participants", notify):
            assert remove_event().status_code == 200
        assert order == ["audit", "participants"]


class TestWarningIsIdempotent:
    def test_same_content_is_not_warned_twice(self, db):
        from app.services.warning_service import give_removal_warning

        first = give_removal_warning(ORG, ADMIN, "reason", "event", EVENT)
        second = give_removal_warning(ORG, ADMIN2, "reason again", "event", EVENT)
        assert first["id"] == second["id"] and len(db.tables["warnings"]) == 1

    def test_retry_after_a_lost_warning_response_does_not_warn_twice(self, db):
        """The warning was stored but the call failed: the removal is undone, the retry reuses the warning."""
        from app.services import warning_service

        real = warning_service._insert_warning
        stored = []

        def insert_then_fail(*args, **kwargs):
            stored.append(real(*args, **kwargs))
            raise RuntimeError("connection reset")

        with patch.object(warning_service, "_insert_warning", insert_then_fail):
            assert remove_event().status_code == 500
        assert _event(db, EVENT)["removed_at"] is None
        assert remove_event().status_code == 200
        assert len(db.tables["warnings"]) == 1
        assert db.tables["notifications"][0]["warning_id"] == stored[0]["id"]


class TestUndo:
    def test_undo_only_touches_the_own_mark(self, db):
        """Another administrator's removal that got in between must not be undone."""
        def other_admin_got_there_first(payload):
            if payload.get("removed_at") is None:
                for e in db.tables["events"]:
                    e["removed_by"] = ADMIN2
            return False

        with patch("app.services.content_removal_service.give_removal_warning", side_effect=RuntimeError("db")), \
                _fail_update_when(db, "events", other_admin_got_there_first):
            r = remove_event()
        assert r.status_code == 500
        assert _event(db, EVENT)["removed_at"]  # still removed, by the other administrator

    def test_failed_undo_says_the_event_stays_removed(self, db):
        with patch("app.services.content_removal_service.give_removal_warning", side_effect=RuntimeError("db")), \
                _fail_update_when(db, "events", lambda p: p.get("removed_at") is None, RuntimeError("db down")):
            r = remove_event()
        assert r.status_code == 500 and code(r) == "removal_incomplete"
        assert "was removed" in r.json()["detail"]["message"]

    def test_failed_message_undo_is_reported_the_same_way(self, db):
        target = msg(db, "you are all")
        with patch("app.services.content_removal_service.give_removal_warning", side_effect=RuntimeError("db")), \
                _fail_update_when(db, "event_chats", lambda p: p.get("removed_at") is None, RuntimeError("db down")):
            r = remove_message(target["id"])
        assert r.status_code == 500 and code(r) == "removal_incomplete"


class TestOtherReaders:
    def test_participant_count_and_my_status_of_a_removed_event_are_410(self, db):
        remove_event()
        current["id"] = P1
        count = client.get(f"/api/participants/{EVENT}/participants/count", headers=HEADERS)
        assert count.status_code == 410 and code(count) == "event_removed"
        assert client.get(f"/api/participants/{EVENT}/my-status", headers=HEADERS).status_code == 410
        assert client.get(f"/api/participants/{OTHER_EVENT}/participants/count", headers=HEADERS).status_code == 200

    def test_max_price_ignores_removed_events(self, db):
        from app.services.event_service import get_max_event_price

        _event(db, EVENT)["cost"] = 500
        _event(db, OTHER_EVENT)["cost"] = 20
        assert get_max_event_price() == 500
        remove_event()
        assert get_max_event_price() == 20

    def test_invitations_to_a_removed_event_are_cleared_and_the_total_stays_right(self, db):
        from app.services.invitation_service import get_my_invitations

        remove_event()
        db.tables["event_invitations"] = [
            {"id": 1, "event_id": EVENT, "inviter_id": ORG, "invitee_id": P1, "created_at": "2026-01-01"},
            {"id": 2, "event_id": OTHER_EVENT, "inviter_id": ORG, "invitee_id": P1, "created_at": "2026-01-02"},
        ]
        result = get_my_invitations(P1)
        assert [i["event"]["id"] for i in result["data"]] == [OTHER_EVENT]
        assert result["total"] == 1 and result["has_more"] is False

    def test_event_lookup_is_chunked(self, db):
        from app.services import removed_content

        remove_event()
        sizes = []
        real_table = db.table

        def table(name):
            query = real_table(name)
            real_in = query.in_

            def in_(column, values):
                sizes.append(len(values))
                return real_in(column, values)

            query.in_ = in_
            return query

        ids = [f"00000000-0000-4000-8000-{i:012d}" for i in range(250)] + [EVENT]
        with patch.object(db, "table", table):
            assert removed_content.removed_event_ids(ids) == {EVENT}
        assert sizes == [100, 100, 51]

    def test_anonymous_semantic_search_over_fetches_for_removed_events(self, db):
        from app.services.event_service import list_events

        seen = {}
        db.rpc_results["search_events"] = lambda params: seen.update(params) or []
        with patch("app.services.event_service.generate_embedding", return_value=[0.1]):
            list_events(search="picnic", limit=10)
        assert seen["match_count"] == 30


class TestMigrationProtectsTheRemovalColumns:
    def test_trigger_is_declared_for_both_tables(self):
        """The trigger itself only runs in the database, so check the migration declares it."""
        sql = MIGRATION.read_text(encoding="utf-8")
        assert "create trigger events_protect_removal" in sql
        assert "create trigger event_chats_protect_removal" in sql
        assert "auth.role() in ('anon', 'authenticated')" in sql
        assert sql.count("before insert or update") == 2
