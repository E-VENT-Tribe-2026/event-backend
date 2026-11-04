---
status: accepted
date: 2026-11-03
decision-makers: kaleb
---

# Caller Identity Forwarding, Blocking Visibility, and Assistant Personalization

**ID**: `cpt-eventbackend-adr-caller-identity-blocking`

## Table of Contents

- [Context and Problem Statement](#context-and-problem-statement)
- [Decision Drivers](#decision-drivers)
- [Considered Options](#considered-options)
- [Decision Outcome](#decision-outcome)
  - [Consequences](#consequences)
  - [Confirmation](#confirmation)
- [Pros and Cons of the Options](#pros-and-cons-of-the-options)
- [Traceability](#traceability)

## Context and Problem Statement

`POST /api/assistant/tools/search-events` and `POST /api/assistant/chat` authenticated incoming requests via JWT dependencies (`get_current_user`), but did not forward the caller's identity (`user.id` or user metadata) to the underlying services. As reported in Issue #225, this allowed events organized by users who blocked the caller (or whom the caller blocked) to remain visible through assistant search. Additionally, conversational responses lacked caller personalization.

How should assistant endpoints propagate caller context to enforce blocking rules and provide personalized responses without violating data access boundaries?

## Decision Drivers

* **Privacy & Safety**: Event visibility must strictly enforce bidirectional user blocking rules (#184, #225).
* **Architecture Compliance**: Assistant chat must not query Supabase tables directly (`test_assistant_chat_does_not_query_supabase_tables`).
* **Personalization**: LLM responses should tailor suggestions to the authenticated user's name and interests.
* **Compatibility**: Maintain strict adherence to `docs/agent-tool-specification.md`.

## Considered Options

* **Option 1: Rely on route-level authentication without service propagation** (Existing behavior — rejected due to Issue #225 leak).
* **Option 2: Query database profiles during chat** (Rejected — violates requirement that chat does not query database tables).
* **Option 3: Forward caller ID to search service and inject minimal user metadata from verified JWT into assistant prompt** (Chosen).

## Decision Outcome

Chosen option: **Option 3**, because:
1. `search_events(payload, viewer_id)` already implemented `hidden_events_filter(viewer_id)` based on Issue #184 blocking rules; passing `getattr(user, "id", None)` immediately enforces the policy.
2. Extracting minimal, non-sensitive identity metadata (`id`, `name`, `username`, `interests`) from the verified `user` object provides LLM personalization without any database table queries.

### Consequences

* **Good**: Blocked organizers' events are properly omitted from Assistant search results, while existing-participation exceptions are honored.
* **Good**: The assistant greets users by name and tailors responses according to their metadata without additional network latency or database load.
* **Good**: All automated tests pass without regressions.

### Confirmation

* Verified via unit and integration tests:
  - `tests/test_event_search.py::test_search_forwards_authenticated_user_id`
  - `tests/test_blocking.py::test_assistant_search_events_endpoint_respects_blocking`
  - `tests/test_assistant_routes.py::test_assistant_chat_includes_minimal_user_context_in_prompt`
* Verified via live API testing with authenticated account `kalebteshale72@gmail.com`.

## Pros and Cons of the Options

### Option 3 (Chosen: Forward caller ID and minimal JWT user context)

* Good, because closes the security leak in #225.
* Good, because respects the design rule against querying database tables during chat.
* Neutral, because prompt size increases slightly to include minimal user context.

## Traceability

- **Specification**: [agent-tool-specification.md](../../docs/agent-tool-specification.md)
- **Issues Addressed**:
  * [#225](https://github.com/E-VENT-Tribe-2026/event-backend/issues/225) — Blocked organizers' events remain visible through Assistant search
  * User context personalization for assistant chat

