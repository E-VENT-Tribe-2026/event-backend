"""Ticket #255: removing content must not reuse an unrelated earlier warning about the same content.

Each removal gets its own warning, marked with removal_key ('event:<id>' / 'chat_message:<id>').
Only a warning with the same (user_id, removal_key) is reused (a retry of that same removal).
Uses the cast and the in-memory fake database of tests/test_content_removal.py.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.dependencies import require_regular_user
from tests.test_content_removal import (  # noqa: F401  (db is a pytest fixture)
    ADMIN, ADMIN2, EVENT, HEADERS, ORG, P2, app, client, code, current, db, msg, notes,
    remove_event, remove_message,
)

NOW = "2026-10-01T00:00:00+00:00"


def _manual_warning(db, user_id, about_type, about_id, state):
    """A warning given by hand (removal_key null) in the state 'active', 'acknowledged' or 'withdrawn'."""
    return db.add("warnings", {
        "user_id": user_id, "admin_id": ADMIN2, "reason": "manual reason", "about_type": about_type,
        "about_id": about_id, "removal_key": None,
        "acknowledged_at": NOW if state == "acknowledged" else None,
        "withdrawn_at": NOW if state == "withdrawn" else None,
        "withdrawn_by": ADMIN2 if state == "withdrawn" else None,
    })


def _counted(owner):
    from app.services.warning_service import counted_warning_counts
    return counted_warning_counts([owner])[owner]


def _pending_ids(owner):
    from app.services.warning_service import get_pending_warnings
    return [i["id"] for i in get_pending_warnings(owner)["items"]]


def _scenario(db, kind):
    """(owner, about_type, about_id, remove callable, check of the removal's own reason)."""
    if kind == "event":
        return ORG, "event", EVENT, remove_event, lambda r: r == 'Your event "Sunset Picnic" was removed by an administrator.'
    target = msg(db, "you are all")
    mid = str(target["id"])
    return (P2, "chat_message", mid, lambda: remove_message(target["id"]),
            lambda r: r.startswith('Your message in "Sunset Picnic" was removed by an administrator: "')
            and "you are all idiots" in r)


@pytest.mark.parametrize("state", ["active", "acknowledged", "withdrawn"])
@pytest.mark.parametrize("kind", ["event", "message"])
class TestRemovalGetsItsOwnWarning:
    def test_a_prior_manual_warning_is_not_reused(self, db, kind, state):
        owner, about_type, about_id, remove, reason_ok = _scenario(db, kind)
        old = _manual_warning(db, owner, about_type, about_id, state)
        old_before = dict(old)
        counted_before = _counted(owner)

        response = remove()
        assert response.status_code == 200
        warning_id = response.json()["warning_id"]

        new = [w for w in db.tables["warnings"] if w["id"] == warning_id]
        assert len(new) == 1 and warning_id != old["id"] and len(db.tables["warnings"]) == 2
        new = new[0]
        assert new["user_id"] == owner and new["admin_id"] == ADMIN
        assert reason_ok(new["reason"]), new["reason"]
        assert (new["about_type"], new["about_id"]) == (about_type, about_id)
        assert new["removal_key"] == f"{about_type}:{about_id}"
        assert new.get("acknowledged_at") is None and new.get("withdrawn_at") is None

        # the old warning row is untouched
        assert old == old_before
        assert (old["reason"], old["acknowledged_at"], old["withdrawn_at"]) == (
            old_before["reason"], old_before["acknowledged_at"], old_before["withdrawn_at"])

        # exactly one more warning counts, and the new one is pending
        assert _counted(owner) == counted_before + 1
        assert warning_id in _pending_ids(owner)

        [note] = notes(db, owner, "content_removed")
        assert note["warning_id"] == warning_id and "counts as a warning" in note["message"]
        assert notes(db, owner, "warning") == []


class TestRemovalEdgeCases:
    def test_event_without_an_owner_gets_no_warning(self, db):
        next(e for e in db.tables["events"] if e["id"] == EVENT)["created_by"] = None
        r = remove_event()
        assert r.status_code == 200 and r.json()["warning_id"] is None
        assert db.tables["warnings"] == [] and notes(db, ORG, "content_removed") == []

    def test_administrator_owner_gets_no_warning_even_with_a_keyed_warning_around(self, db):
        """The administrator check comes first: nothing is reused or created for an administrator."""
        next(p for p in db.tables["profiles"] if p["id"] == ORG)["role"] = "administrator"
        keyed = db.add("warnings", {"user_id": ORG, "admin_id": ADMIN2, "reason": "old removal",
                                    "about_type": "event", "about_id": EVENT,
                                    "removal_key": f"event:{EVENT}"})
        r = remove_event()
        assert r.status_code == 200 and r.json()["warning_id"] is None
        assert db.tables["warnings"] == [keyed]
        [note] = notes(db, ORG)
        assert note["warning_id"] is None and "counts as a warning" not in note["message"]

    def test_manual_warnings_for_the_same_content_still_coexist(self, db):
        from app.services.warning_service import give_warning

        first = give_warning(ORG, ADMIN, "first", "event", EVENT)
        second = give_warning(ORG, ADMIN2, "second", "event", EVENT)
        assert first["id"] != second["id"] and len(db.tables["warnings"]) == 2
        assert all(w.get("removal_key") is None for w in db.tables["warnings"])

    def test_removing_twice_is_409_with_one_warning(self, db):
        assert remove_event().status_code == 200
        r = remove_event()
        assert r.status_code == 409 and code(r) == "already_removed"
        assert len(db.tables["warnings"]) == 1

    def test_history_and_pending_payloads_do_not_expose_removal_key(self, db):
        removal = remove_event()
        assert removal.status_code == 200 and "removal_key" not in removal.json()
        [warning] = db.tables["warnings"]
        warning["removal_key"] = f"event:{EVENT}"  # make sure the column is present on the row
        history = client.get(f"/api/admin/users/{ORG}/warnings", headers=HEADERS).json()
        assert len(history["items"]) == 1 and "removal_key" not in history["items"][0]
        app.dependency_overrides[require_regular_user] = lambda: SimpleNamespace(id=ORG, email="x@y.z")
        try:
            pending = client.get("/api/warnings/pending", headers=HEADERS).json()
        finally:
            app.dependency_overrides.pop(require_regular_user, None)
        assert len(pending["items"]) == 1 and "removal_key" not in pending["items"][0]


class TestInsertConflict:
    """A unique violation on (user_id, removal_key) means the same removal already stored its warning.

    The code is expected to treat an exception as a unique violation when its text contains '23505' or
    'duplicate key' (e.g. 'duplicate key value violates unique constraint "warnings_user_removal_key_uidx"'
    or a PostgREST error with code 23505), then re-read by (user_id, removal_key) and reuse that row.
    """

    @pytest.mark.parametrize("text", [
        'duplicate key value violates unique constraint "warnings_user_removal_key_uidx"',
        "{'code': '23505', 'message': 'conflict on warnings_user_removal_key_uidx'}",
    ])
    def test_conflict_rereads_and_reuses_the_existing_keyed_warning(self, db, text):
        from app.services import warning_service

        real = warning_service._insert_warning
        calls = []

        def insert_then_conflict(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:  # a concurrent request stored the keyed row first
                real(*args, **kwargs)
                raise Exception(text)
            return real(*args, **kwargs)

        with patch.object(warning_service, "_insert_warning", insert_then_conflict):
            result = warning_service.give_removal_warning(ORG, ADMIN, "reason", "event", EVENT)

        key = f"event:{EVENT}"
        keyed = [w for w in db.tables["warnings"] if w.get("removal_key") == key]
        assert len(keyed) == 1 and len(db.tables["warnings"]) == 1
        assert result["id"] == keyed[0]["id"] and result["removal_key"] == key
        assert len(calls) == 1  # re-read, no second insert

    def test_other_errors_are_not_swallowed(self, db):
        from app.services import warning_service

        with patch.object(warning_service, "_insert_warning", side_effect=RuntimeError("connection reset")):
            with pytest.raises(RuntimeError):
                warning_service.give_removal_warning(ORG, ADMIN, "reason", "event", EVENT)
        assert db.tables["warnings"] == []


class _CodedError(Exception):
    """An error that carries only a structured SQLSTATE code (no 'duplicate key' text)."""

    def __init__(self, code, message="insert failed"):
        super().__init__(message)
        self.code = code


class TestUniqueViolationDetection:
    def test_structured_code_23505_without_text_is_a_unique_violation_and_reuses_the_row(self, db):
        from app.services import warning_service

        real = warning_service._insert_warning
        calls = []

        def insert_then_conflict(*args, **kwargs):
            calls.append(1)
            real(*args, **kwargs)
            raise _CodedError("23505", "insert failed")

        with patch.object(warning_service, "_insert_warning", insert_then_conflict):
            result = warning_service.give_removal_warning(ORG, ADMIN, "reason", "event", EVENT)
        [keyed] = db.tables["warnings"]
        assert result["id"] == keyed["id"] and keyed["removal_key"] == f"event:{EVENT}" and len(calls) == 1

    def test_other_structured_code_without_duplicate_text_is_reraised(self, db):
        from app.services import warning_service

        with patch.object(warning_service, "_insert_warning", side_effect=_CodedError("23503", "fk failed")):
            with pytest.raises(_CodedError):
                warning_service.give_removal_warning(ORG, ADMIN, "reason", "event", EVENT)
        assert db.tables["warnings"] == []

    @pytest.mark.parametrize("exc,expected", [
        (_CodedError("23505"), True),
        (_CodedError("23503"), False),
        (Exception({"code": "23505", "message": "x"}), True),
        (Exception({"code": "23503", "message": "x"}), False),
        (Exception('duplicate key value violates unique constraint "x"'), True),
        (RuntimeError("connection reset"), False),
    ])
    def test_helper(self, exc, expected):
        from app.services.warning_service import _is_unique_violation

        assert _is_unique_violation(exc) is expected


class TestConflictWithoutAKeyedRow:
    def test_unique_violation_without_a_keyed_row_reraises_and_fails_the_removal(self, db):
        from app.services import warning_service

        error = Exception('duplicate key value violates unique constraint "warnings_user_removal_key_uidx" (23505)')
        with patch.object(warning_service, "_insert_warning", side_effect=error):
            with pytest.raises(Exception) as raised:
                warning_service.give_removal_warning(ORG, ADMIN, "reason", "event", EVENT)
            assert raised.value is error
            assert db.tables["warnings"] == []
            r = remove_event()
        assert r.status_code == 500 and code(r) == "removal_failed"
        assert next(e for e in db.tables["events"] if e["id"] == EVENT)["removed_at"] is None
        assert db.tables["warnings"] == [] and db.tables["notifications"] == []


class TestKeyedWarningInAnyStateIsReused:
    @pytest.mark.parametrize("state", ["acknowledged", "withdrawn"])
    def test_keyed_warning_is_returned_unchanged_without_an_insert(self, db, state):
        from app.services import warning_service

        key = f"event:{EVENT}"
        keyed = db.add("warnings", {
            "user_id": ORG, "admin_id": ADMIN2, "reason": "earlier removal", "about_type": "event",
            "about_id": EVENT, "removal_key": key,
            "acknowledged_at": NOW if state == "acknowledged" else None,
            "withdrawn_at": NOW if state == "withdrawn" else None,
            "withdrawn_by": ADMIN2 if state == "withdrawn" else None,
        })
        before = dict(keyed)

        def must_not_insert(*args, **kwargs):
            raise AssertionError("no insert expected")

        with patch.object(warning_service, "_insert_warning", must_not_insert):
            result = warning_service.give_removal_warning(ORG, ADMIN, "reason", "event", EVENT)
        assert result["id"] == keyed["id"]
        assert db.tables["warnings"] == [keyed] and keyed == before
        assert keyed["acknowledged_at"] == before["acknowledged_at"]
        assert keyed["withdrawn_at"] == before["withdrawn_at"]


class TestMissingColumn:
    def test_lookup_failing_because_the_column_is_missing_fails_and_undoes_the_removal(self, db):
        from app.services import warning_service

        error = Exception("{'code': '42703', 'message': 'column warnings.removal_key does not exist'}")
        with patch.object(warning_service, "_find_removal_warning", side_effect=error):
            r = remove_event()
        assert r.status_code == 500 and code(r) == "removal_failed"
        assert next(e for e in db.tables["events"] if e["id"] == EVENT)["removed_at"] is None
        assert db.tables["warnings"] == [] and db.tables["notifications"] == [] and db.tables["logs"] == []
