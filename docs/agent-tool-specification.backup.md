# Product Orientation Assistant Tool Specification

- **Status:** DRAFT - revised, ready for sign-off review
- **Version:** 0.2
- **Scope:** The three tools available to the product-orientation chat assistant
- **Owner:** Product team
- **Last updated:** 2026-10-12

### Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-09-14 | First draft. |
| 0.2 | 2026-10-12 | Fixed the publish endpoint to `POST /api/events/`. Search input now requires at least one search criterion and only accepts real calendar dates. All output schemas now use `if`/`then`/`else` so success and failure cannot be mixed. Added the caller identity and access policy (Section 2.2 to 2.5). Error codes are now a closed list. Added known implementation gaps (Section 13). |

## 1. Purpose

The assistant helps users understand and use the events product through chat. It may call three tools:

1. Search for events.
2. Retrieve the details of one event.
3. Draft a new event.

The assistant must use tools for authoritative event data. It must not claim that an event exists, has been changed, or has been published unless the corresponding tool response confirms it.

## 2. Common Tool Contract

### 2.1 Input and output rules

Every tool call has:

- A JSON input object that validates against the tool's input schema.
- A JSON output object that validates against the tool's output schema.
- A stable `request_id` for tracing the call.
- A `success` boolean.
- An `error` field that is `null` when `success` is `true`, and an `Error` object when `success` is `false`. The schemas enforce this with `if`/`then`/`else`; a response that breaks this rule is invalid.

Dates and times use ISO 8601 strings with an explicit timezone offset or `Z`. Event identifiers are UUID strings.

Tool calls must not expose service-role credentials, internal database errors, or unrestricted personal data.

**Schema validation rule.** In JSON Schema draft 2020-12, the `format` keyword is only a note by default and is not checked. Every validator used for these schemas (tests, the agent runtime, CI) must turn on format checking (for example `format_checker=Draft202012Validator.FORMAT_CHECKER` in the Python `jsonschema` package). The services must also run their own checks (Pydantic models), because a regular expression alone cannot reject dates such as `2026-02-30`.

### 2.2 Caller identity context

Every tool call runs on behalf of exactly one signed-in user. The backend builds a `ToolCallContext` for each call. This context is **not** part of the tool input, and the language model can never create, see, or change it.

| Field | Type | Source | Rules |
|---|---|---|---|
| `user_id` | UUID string | The `sub` claim of the Supabase JWT that was verified on the `/api/assistant/*` request (`get_current_user`). | Required for every tool. Never taken from model output or chat text. |
| `access_token` | string | The same bearer token from the request. | Used only to create a per-request Supabase client with the anon key, so database row-level security (RLS) applies as that user. Never logged, never written to `ai_agent_audit_logs`, never put in model context. |
| `is_onboarded` | boolean | The same check used by `get_current_onboarded_user`. | Used by the Draft tool only. |
| `request_id` | string | Created by the backend per tool call. | Returned in the tool output. |

Rules:

1. If `ToolCallContext` is missing, or `user_id` is empty, the tool returns `UNAUTHORIZED` and reads no data.
2. Tool input schemas use `"additionalProperties": false`, so the model cannot pass `user_id`, `created_by`, `status`, or any other identity or permission field.
3. The user's role (including `administrator`) gives no extra access through the assistant. Admin work happens only in the admin panel.
4. Tool services never use `SUPABASE_SERVICE_KEY`.

### 2.3 Event visibility policy

The data model today has no private, invite-only, or friends-only events: the `events` table has no visibility column, and its RLS read policy allows everyone (`USING (true)`). Event `status` is either `active` or `cancelled`.

An event is **visible to the assistant** only when both are true:

- `status = 'active'`, and
- `end_datetime` is now or in the future.

| Visibility level | Exists today? | Assistant access |
|---|---|---|
| Active and not yet ended | Yes | Search and Get Event Details |
| Active but already ended | Yes | Not visible. Details returns `NOT_FOUND`. |
| Cancelled | Yes | Not visible. Details returns `NOT_FOUND`. |
| Private, invite-only, friends-only | No | Not visible. If such levels are added later, the tools must hide them by default (fail closed) until this specification is revised and signed off again. |
| Draft previews | Not stored | Returned only to the user who asked for them, in the same conversation. |

### 2.4 Per-tool authorization

| Tool | Signed in | Onboarded | What it can read | Failure codes it may return |
|---|---|---|---|---|
| Search Events | Required | Not required | Visible events only (Section 2.3) | `UNAUTHORIZED`, `INVALID_INPUT`, `SERVICE_UNAVAILABLE`, `INTERNAL_ERROR` |
| Get Event Details | Required | Not required | One visible event | `UNAUTHORIZED`, `INVALID_INPUT`, `NOT_FOUND`, `SERVICE_UNAVAILABLE`, `INTERNAL_ERROR` |
| Draft New Event | Required | Required (same rule as `POST /api/events/`, because a user who cannot publish should not get a draft they cannot use) | Nothing from the database | `UNAUTHORIZED`, `FORBIDDEN`, `INVALID_INPUT`, `INTERNAL_ERROR` |

### 2.5 Access error behavior

- **Not signed in, or token invalid or expired:** `UNAUTHORIZED`. The assistant tells the user to sign in again. It does not retry with other credentials.
- **Signed in but not onboarded (Draft only):** `FORBIDDEN`. The assistant tells the user to finish their profile first.
- **Event does not exist, or exists but is not visible:** `NOT_FOUND` with the same message (`"Event not found."`) in both cases, so the response does not confirm that a hidden event exists. `FORBIDDEN` is never used for event visibility.
- Error messages never include stack traces, SQL, table names, tokens, or other users' data.

## 3. Tool: Search Events

### 3.1 Functional requirements

- **FR-SEARCH-001:** Accept a free-text search query and optional event filters.
- **FR-SEARCH-002:** Support the product's current discovery filters: category, upcoming status, date, and city (matched against `location_name`).
- **FR-SEARCH-003:** Support pagination with a positive page number, bounded page size, total record count, and `has_next` calculation.
- **FR-SEARCH-004:** Return only events visible under Section 2.3, for a signed-in caller (Section 2.4).
- **FR-SEARCH-005:** Return enough summary data for the assistant to explain and compare results without requiring a detail call for every result.
- **FR-SEARCH-006:** Return an empty result set with `success: true` when no events match; this is not an error.
- **FR-SEARCH-007:** Apply deterministic ordering. The initial default is upcoming events ordered by start time ascending, followed by a stable identifier as a tie-breaker.
- **FR-SEARCH-008:** Reject invalid pagination or filter values with a structured validation error. A `date` must be a real calendar date (for example, `2026-02-30` and `2026-99-99` are rejected).
- **FR-SEARCH-009:** The assistant should ask a clarifying question when the user's request is too ambiguous to form a useful search, rather than issuing an unconstrained search.
- **FR-SEARCH-010:** The tool must reject a search without at least one meaningful criterion: a non-empty, non-whitespace value for `query`, `category`, `date`, or `city`. `upcoming`, `page`, and `limit` alone do not count. Inputs such as `{}`, `{"query": null}`, and `{"query": "   "}` return `INVALID_INPUT`. This enforces FR-SEARCH-009 at the tool level, so a model that skips the clarifying question still cannot run an unconstrained search.

### 3.2 Input schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SearchEventsInput",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "query": {
      "type": ["string", "null"],
      "description": "Free-text terms matched against event title and description.",
      "minLength": 1,
      "maxLength": 200
    },
    "category": {
      "type": ["string", "null"],
      "minLength": 1,
      "maxLength": 100
    },
    "upcoming": {
      "type": "boolean",
      "default": true
    },
    "date": {
      "type": ["string", "null"],
      "description": "Calendar date in YYYY-MM-DD format. Must be a real date.",
      "format": "date",
      "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$"
    },
    "city": {
      "type": ["string", "null"],
      "description": "City or locality name matched against event location_name.",
      "minLength": 1,
      "maxLength": 120
    },
    "page": {
      "type": "integer",
      "minimum": 1,
      "default": 1
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 50,
      "default": 10
    }
  },
  "anyOf": [
    { "required": ["query"], "properties": { "query": { "type": "string", "pattern": "\\S" } } },
    { "required": ["category"], "properties": { "category": { "type": "string", "pattern": "\\S" } } },
    { "required": ["date"], "properties": { "date": { "type": "string" } } },
    { "required": ["city"], "properties": { "city": { "type": "string", "pattern": "\\S" } } }
  ]
}
```

The `anyOf` block is what rejects empty and unconstrained searches: at least one of `query`, `category`, `date`, or `city` must be present as a string with at least one non-space character. A `null` value does not count.

### 3.3 Output schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SearchEventsOutput",
  "type": "object",
  "additionalProperties": false,
  "required": ["request_id", "success", "events", "pagination", "error"],
  "properties": {
    "request_id": { "type": "string", "minLength": 1 },
    "success": { "type": "boolean" },
    "events": {
      "type": "array",
      "items": { "$ref": "#/$defs/EventSummary" }
    },
    "pagination": {
      "type": "object",
      "additionalProperties": false,
      "required": ["page", "limit", "total", "has_next"],
      "properties": {
        "page": { "type": "integer", "minimum": 1 },
        "limit": { "type": "integer", "minimum": 1, "maximum": 50 },
        "total": { "type": "integer", "minimum": 0 },
        "has_next": { "type": "boolean" }
      }
    },
    "error": {
      "oneOf": [{ "type": "null" }, { "$ref": "#/$defs/Error" }]
    }
  },
  "if": {
    "required": ["success"],
    "properties": { "success": { "const": true } }
  },
  "then": {
    "properties": { "error": { "type": "null" } }
  },
  "else": {
    "properties": {
      "error": { "$ref": "#/$defs/Error" },
      "events": { "maxItems": 0 },
      "pagination": {
        "properties": {
          "total": { "const": 0 },
          "has_next": { "const": false }
        }
      }
    }
  },
  "$defs": {
    "EventSummary": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "title", "start_datetime", "status"],
      "properties": {
        "id": { "type": "string", "format": "uuid" },
        "title": { "type": "string", "minLength": 1 },
        "description": { "type": ["string", "null"] },
        "category": { "type": ["string", "null"] },
        "start_datetime": { "type": "string", "format": "date-time" },
        "end_datetime": { "type": ["string", "null"], "format": "date-time" },
        "location_name": { "type": ["string", "null"] },
        "cost": { "type": ["number", "null"], "minimum": 0 },
        "max_capacity": { "type": ["integer", "null"], "minimum": 1 },
        "status": { "const": "active" }
      }
    },
    "Error": {
      "type": "object",
      "additionalProperties": false,
      "required": ["code", "message", "field"],
      "properties": {
        "code": {
          "enum": ["INVALID_INPUT", "NOT_FOUND", "UNAUTHORIZED", "FORBIDDEN", "SERVICE_UNAVAILABLE", "INTERNAL_ERROR"]
        },
        "message": { "type": "string", "minLength": 1 },
        "field": { "type": ["string", "null"] }
      }
    }
  }
}
```

On failure, `events` must be empty and `pagination` must report `total: 0` and `has_next: false`. `status` is fixed to `active` because only visible events may be returned (Section 2.3).

## 4. Tool: Get Event Details

### 4.1 Functional requirements

- **FR-DETAIL-001:** Accept exactly one event identifier, which must be a UUID.
- **FR-DETAIL-002:** Return the current authoritative event record when the event exists and is visible under Section 2.3.
- **FR-DETAIL-003:** Return the event's identity, description, category, timing, location, cost, capacity, status, and creator reference when available.
- **FR-DETAIL-004:** Return `NOT_FOUND` when the identifier does not refer to a visible event. Missing events and hidden events (cancelled, ended, or any future restricted level) get the same code and message (Section 2.5).
- **FR-DETAIL-005:** Never invent missing event fields. Optional or unavailable values must be returned as `null`.
- **FR-DETAIL-006:** The assistant should use this tool before answering detailed questions about one event when the search result does not contain enough information.
- **FR-DETAIL-007:** Require a signed-in caller (Section 2.4). Without one, return `UNAUTHORIZED` before reading any data.

### 4.2 Input schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "GetEventDetailsInput",
  "type": "object",
  "additionalProperties": false,
  "required": ["event_id"],
  "properties": {
    "event_id": {
      "type": "string",
      "description": "The event identifier returned by Search Events.",
      "format": "uuid",
      "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    }
  }
}
```

### 4.3 Output schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "GetEventDetailsOutput",
  "type": "object",
  "additionalProperties": false,
  "required": ["request_id", "success", "event", "error"],
  "properties": {
    "request_id": { "type": "string", "minLength": 1 },
    "success": { "type": "boolean" },
    "event": {
      "oneOf": [{ "type": "null" }, { "$ref": "#/$defs/EventDetails" }]
    },
    "error": {
      "oneOf": [{ "type": "null" }, { "$ref": "#/$defs/Error" }]
    }
  },
  "if": {
    "required": ["success"],
    "properties": { "success": { "const": true } }
  },
  "then": {
    "properties": {
      "event": { "$ref": "#/$defs/EventDetails" },
      "error": { "type": "null" }
    }
  },
  "else": {
    "properties": {
      "event": { "type": "null" },
      "error": { "$ref": "#/$defs/Error" }
    }
  },
  "$defs": {
    "EventDetails": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "id", "title", "description", "category", "cost", "max_capacity",
        "start_datetime", "end_datetime", "location_name", "latitude",
        "longitude", "created_by", "status"
      ],
      "properties": {
        "id": { "type": "string", "format": "uuid" },
        "title": { "type": "string", "minLength": 1 },
        "description": { "type": ["string", "null"] },
        "category": { "type": ["string", "null"] },
        "cost": { "type": ["number", "null"], "minimum": 0 },
        "max_capacity": { "type": ["integer", "null"], "minimum": 1 },
        "start_datetime": { "type": "string", "format": "date-time" },
        "end_datetime": { "type": "string", "format": "date-time" },
        "location_name": { "type": ["string", "null"] },
        "latitude": { "type": ["number", "null"], "minimum": -90, "maximum": 90 },
        "longitude": { "type": ["number", "null"], "minimum": -180, "maximum": 180 },
        "created_by": { "type": ["string", "null"] },
        "status": { "const": "active" }
      }
    },
    "Error": {
      "type": "object",
      "additionalProperties": false,
      "required": ["code", "message", "field"],
      "properties": {
        "code": {
          "enum": ["INVALID_INPUT", "NOT_FOUND", "UNAUTHORIZED", "FORBIDDEN", "SERVICE_UNAVAILABLE", "INTERNAL_ERROR"]
        },
        "message": { "type": "string", "minLength": 1 },
        "field": { "type": ["string", "null"] }
      }
    }
  }
}
```

All event keys are always present; unknown values are `null` (FR-DETAIL-005).

## 5. Tool: Draft New Event

### 5.1 Functional requirements

- **FR-DRAFT-001:** Accept the fields required to describe a new event and optional fields supported by the product.
- **FR-DRAFT-002:** Require `title`, `start_datetime`, and `end_datetime`.
- **FR-DRAFT-003:** Validate that the end is later than the start, cost is non-negative, capacity is positive when supplied, and coordinates are within valid geographic bounds.
- **FR-DRAFT-004:** Normalize dates to ISO 8601 and preserve the supplied timezone information. A date-time without a timezone offset or `Z` is rejected.
- **FR-DRAFT-005:** Return a draft preview and a list of validation issues, if any.
- **FR-DRAFT-006:** Do not persist, publish, notify participants, or add the creator as a participant during drafting.
- **FR-DRAFT-007:** The agent never directly creates, persists, or publishes an event. Drafted events are returned to the user, and event creation occurs exclusively through the user's explicit publish action in the application interface (human-in-the-loop).
- **FR-DRAFT-008:** Never silently replace invalid or missing user-provided values with defaults. Return a validation issue that the assistant can explain. A value the user did not give stays `null` in the preview.
- **FR-DRAFT-009:** Require a signed-in and onboarded caller (Section 2.4). Return `UNAUTHORIZED` without a signed-in user and `FORBIDDEN` for a user who has not finished onboarding.
- **FR-DRAFT-010:** `success` is `true` only when there are no validation issues with `severity: "error"`. Warnings may be returned with a successful draft.

### 5.2 Input schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "DraftNewEventInput",
  "type": "object",
  "additionalProperties": false,
  "required": ["title", "start_datetime", "end_datetime"],
  "properties": {
    "title": { "type": "string", "minLength": 1, "maxLength": 200, "pattern": "\\S" },
    "description": { "type": ["string", "null"], "maxLength": 5000 },
    "category": { "type": ["string", "null"], "maxLength": 100 },
    "cost": { "type": ["number", "null"], "minimum": 0 },
    "max_capacity": { "type": ["integer", "null"], "minimum": 1 },
    "start_datetime": { "$ref": "#/$defs/ZonedDateTime" },
    "end_datetime": { "$ref": "#/$defs/ZonedDateTime" },
    "location_name": { "type": ["string", "null"], "maxLength": 300 },
    "latitude": { "type": ["number", "null"], "minimum": -90, "maximum": 90 },
    "longitude": { "type": ["number", "null"], "minimum": -180, "maximum": 180 }
  },
  "$defs": {
    "ZonedDateTime": {
      "type": "string",
      "format": "date-time",
      "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9](\\.[0-9]+)?)?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$"
    }
  }
}
```

The rule "end is later than start" (FR-DRAFT-003) cannot be written in JSON Schema. The service checks it and returns a validation issue with code `INVALID_DATE_ORDER`.

### 5.3 Output schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "DraftNewEventOutput",
  "type": "object",
  "additionalProperties": false,
  "required": ["request_id", "success", "draft", "validation_issues", "error"],
  "properties": {
    "request_id": { "type": "string", "minLength": 1 },
    "success": { "type": "boolean" },
    "draft": {
      "oneOf": [{ "type": "null" }, { "$ref": "#/$defs/DraftPreview" }]
    },
    "validation_issues": {
      "type": "array",
      "items": { "$ref": "#/$defs/ValidationIssue" }
    },
    "error": {
      "oneOf": [{ "type": "null" }, { "$ref": "#/$defs/Error" }]
    }
  },
  "if": {
    "required": ["success"],
    "properties": { "success": { "const": true } }
  },
  "then": {
    "properties": {
      "draft": { "$ref": "#/$defs/DraftPreview" },
      "error": { "type": "null" },
      "validation_issues": {
        "items": { "properties": { "severity": { "const": "warning" } } }
      }
    }
  },
  "else": {
    "properties": {
      "draft": { "type": "null" },
      "error": { "$ref": "#/$defs/Error" }
    }
  },
  "$defs": {
    "DraftPreview": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "title", "description", "category", "cost", "max_capacity",
        "start_datetime", "end_datetime", "location_name", "latitude", "longitude"
      ],
      "properties": {
        "title": { "type": "string", "minLength": 1 },
        "description": { "type": ["string", "null"] },
        "category": { "type": ["string", "null"] },
        "cost": { "type": ["number", "null"], "minimum": 0 },
        "max_capacity": { "type": ["integer", "null"], "minimum": 1 },
        "start_datetime": { "type": "string", "format": "date-time" },
        "end_datetime": { "type": "string", "format": "date-time" },
        "location_name": { "type": ["string", "null"] },
        "latitude": { "type": ["number", "null"], "minimum": -90, "maximum": 90 },
        "longitude": { "type": ["number", "null"], "minimum": -180, "maximum": 180 }
      }
    },
    "ValidationIssue": {
      "type": "object",
      "additionalProperties": false,
      "required": ["code", "field", "message", "severity"],
      "properties": {
        "code": { "type": "string", "minLength": 1 },
        "field": { "type": ["string", "null"] },
        "message": { "type": "string", "minLength": 1 },
        "severity": { "enum": ["error", "warning"] }
      }
    },
    "Error": {
      "type": "object",
      "additionalProperties": false,
      "required": ["code", "message", "field"],
      "properties": {
        "code": {
          "enum": ["INVALID_INPUT", "NOT_FOUND", "UNAUTHORIZED", "FORBIDDEN", "SERVICE_UNAVAILABLE", "INTERNAL_ERROR"]
        },
        "message": { "type": "string", "minLength": 1 },
        "field": { "type": ["string", "null"] }
      }
    }
  }
}
```

A successful draft has a preview, no error, and only `warning` issues. A failed draft has no preview and an error; it may also list the `error` issues that caused the failure, so the assistant can explain each one.

## 6. Agent Architecture and Conversational Workflow

### 6.1 Core Agents and Shared Session State

The assistant architecture couples **4 specialized agents** with a centralized **Session State Store (Context Cache)** so that all conversational turns, extracted entity slots, and tool outputs remain synchronized in a single object across the entire chat lifecycle:

1. **`GuardianAgent`:**
   - **Input Gate:** Screens user prompts to intercept malicious instructions, prompt injection attacks, and irrelevant/off-topic questions before downstream processing.
   - **Output Gate:** Verifies the final response to ensure no internal errors, secrets, or sensitive system details are leaked.
2. **`IntentIdentifier`:**
   - Analyzes the sanitized user prompt and session state to determine the user's intent:
     - **Tool Calling:** The request requires live event data or drafting (`Search Events`, `Get Event Details`, `Draft New Event`).
     - **Normal LLM Response:** The request is a general question, product FAQ, or navigation guidance.
     - **More Information Asking:** The request is ambiguous or incomplete, requiring clarifying follow-up questions.
3. **`ToolCaller`:**
   - Dispatches and executes the necessary tool call against backend service functions (`Search Events`, `Get Event Details`, or `Draft New Event`).
4. **`ResponseCollector`:**
   - Gathers output from the **`ToolCaller`** (or direct responses from the **`IntentIdentifier`** for FAQs/clarifications), synthesizes the data into a helpful conversational response, and presents draft cards to the user for human-in-the-loop publishing.
5. **`ConversationStateStore` (Supabase Session Store & Context Scratchpad):**
   - Pure Supabase-backed persistence (no Redis) managing conversation lifecycle and agent scratchpads.
   - For every conversational turn, the session record, active slot cache (`context_state`), and recent dialogue are loaded from Supabase into a structured Pydantic state object (`agent_context_json`).
   - Every agent in the orchestration receives the shared context JSON and multi-turn message history.
   - Every discrete agent action, tool invocation, and guardrail check is recorded directly to Supabase tables.

### 6.2 Architecture Diagram

Can be refered at agent_archtecture.png

## 7. Data Persistence & Session Storage (Supabase)

All AI assistant dialogues, orchestration states, and agent telemetry are persisted directly in PostgreSQL via Supabase without external cache layers (no Redis).

During orchestration, each agent possesses a `context_data` array attribute containing all previous text messages in the conversation (e.g., `[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]`), providing each agent with the complete conversational history to perform its evaluation, intent identification, tool calling, or response synthesis. Every action taken by each agent is recorded directly into `ai_agent_audit_logs`.

For the frontend, chat sessions and message histories are retrieved directly from these tables to display active and past conversations, including draft preview cards and event search results stored in message metadata.

### 7.1 Database Schema (3 Dedicated Tables)

#### 1. `ai_conversations` (Chat Sessions)
Represents an ongoing or past chat session between a user and the AI orientation assistant.

| Column | Type | Constraints / Defaults | Description |
|---|---|---|---|
| `id` | `UUID` | `PRIMARY KEY DEFAULT gen_random_uuid()` | Unique session identifier |
| `user_id` | `UUID` | `NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE` | Owner of the chat session |
| `title` | `TEXT` | `DEFAULT 'New Conversation'` | Human-readable title (auto-generated from first prompt or user-edited) |
| `context_state` | `JSONB` | `DEFAULT '{}'::jsonb` | Active entity slot cache (e.g., extracted draft fields, timezone, active filters) |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT NOW()` | Session creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT NOW()` | Timestamp of last message or state update |

#### 2. `ai_messages` (User-Facing Chat History)
Stores user queries and assistant responses that are retrieved and presented in the frontend chat interface.

| Column | Type | Constraints / Defaults | Description |
|---|---|---|---|
| `id` | `UUID` | `PRIMARY KEY DEFAULT gen_random_uuid()` | Unique message identifier |
| `conversation_id` | `UUID` | `NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE` | Linked session |
| `role` | `TEXT` | `NOT NULL CHECK (role IN ('user', 'assistant', 'system'))` | Sender role |
| `content` | `TEXT` | `NOT NULL` | Markdown-rendered textual dialogue content |
| `metadata` | `JSONB` | `DEFAULT '{}'::jsonb` | Rich UI card payloads: draft event previews, search result lists, validation issues, tool references |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT NOW()` | Message timestamp |

#### 3. `ai_agent_audit_logs` (Orchestration & Action Telemetry)
Records every granular step, decision, and tool invocation made by each agent in the orchestration pipeline for transparency, debugging, and guardrail monitoring.

| Column | Type | Constraints / Defaults | Description |
|---|---|---|---|
| `id` | `UUID` | `PRIMARY KEY DEFAULT gen_random_uuid()` | Unique log entry identifier |
| `conversation_id` | `UUID` | `NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE` | Linked session |
| `message_id` | `UUID` | `REFERENCES ai_messages(id) ON DELETE SET NULL` | Linked message if applicable |
| `user_id` | `UUID` | `REFERENCES auth.users(id) ON DELETE SET NULL` | Authenticated user making the request |
| `agent_name` | `TEXT` | `NOT NULL` | Name of executing agent (`GuardianAgent`, `IntentIdentifier`, `ToolCaller`, `ResponseCollector`) |
| `action_taken` | `TEXT` | `NOT NULL` | Action code (e.g., `INPUT_GUARD_PASSED`, `INPUT_GUARD_BLOCKED`, `INTENT_CLASSIFIED`, `TOOL_CALLED`, `TOOL_COMPLETED`, `OUTPUT_GUARD_PASSED`, `DRAFT_GENERATED`) |
| `execution_payload` | `JSONB` | `DEFAULT '{}'::jsonb` | Input arguments, tool response payload, decision rationales, error traces, and execution duration (ms) |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT NOW()` | Action execution timestamp |

---

## 8. Security and Guardrails

To protect user data, prevent service abuse, and ensure safe agent behavior, the integration enforces the following security boundaries:

1. **Human-in-the-Loop Event Creation:**
   The agent has read and draft preview capabilities only. It cannot autonomously persist, publish, or modify events in the database. All event creation occurs only when the human user reviews the draft card in the UI and explicitly triggers the application's publish method (`POST /api/events/`), which requires a signed-in, onboarded user (`get_current_onboarded_user`).
2. **Authenticated User Session Tokens:**
   All tool operations run on behalf of the signed-in user using the `ToolCallContext` in Section 2.2. Database reads use a per-request Supabase client built from the anon key and the user's own JWT, so RLS applies. The agent is never granted elevated system privileges or access to the Supabase service-role key (`SUPABASE_SERVICE_KEY`). See Section 13, gap 1: the current code does not meet this rule yet.
3. **Zero Direct Database Access:**
   The agent has no direct connection string, network route, or permission to execute raw database queries against PostgreSQL / Supabase.
4. **Backend Function Reuse:**
   Tool implementations do not reimplement business logic; they strictly wrap existing, audited FastAPI endpoints and backend service functions (`app/services/event_search_service.py`, `app/services/event_details_service.py`, `app/services/event_draft_service.py`). This keeps row-level security (RLS), field validations, coordinate checks, and rate limits the same as the rest of the API.
5. **Guardian / Guardrail Agent & Audit Logging:**
   A dedicated Guardian Agent acts as an input/output firewall, and all security decisions are permanently recorded in `ai_agent_audit_logs`:
   - **Input Filtering:** Intercepts prompt injection attacks, jailbreaks, system instruction exfiltration attempts, and off-topic requests before they reach the reasoning model.
   - **Output Filtering:** Verifies that agent replies do not leak internal database errors, access tokens, PII, or prompt templates.
   - **Audit payload rule:** `execution_payload` may store `user_id` and tool inputs and outputs, but never `access_token` or any other credential.

---

## 9. Cross-tool Error Contract

The following error codes are the complete list for this version. The output schemas reject any other code.

| Code | Meaning | Typical HTTP cause |
|---|---|---|
| `INVALID_INPUT` | The input does not satisfy the schema or a business rule. | 400, 422 |
| `NOT_FOUND` | The requested event does not exist or is not visible to the caller (Section 2.5). | 404 |
| `UNAUTHORIZED` | No signed-in user, or the token is invalid or expired. | 401 |
| `FORBIDDEN` | The user is signed in but may not use this tool (Draft: not onboarded). Never used for event visibility. | 403 |
| `SERVICE_UNAVAILABLE` | The event service or database is temporarily unavailable. | 502, 503, 504, timeouts |
| `INTERNAL_ERROR` | An unexpected server-side failure occurred. | 500 |

When `success` is `false`, the output must contain `error.code`, `error.message`, and `error.field` (which may be `null`). The message must be safe to show to the assistant and user. When `success` is `true`, `error` must be `null`.

---

## 10. Acceptance Criteria Traceability

| Acceptance criterion | Evidence in this specification |
|---|---|
| Functional requirements for all three tools are written down | Sections 3.1, 4.1, and 5.1 |
| Every tool call has an input and output schema | Sections 3.2-3.3, 4.2-4.3, and 5.2-5.3 |
| Documented API endpoints match the backend | Section 8.1 (`POST /api/events/`, defined in `app/api/v1/event_routes.py` under the `/api` and `/events` prefixes) |
| Schemas reject invalid, empty, and unconstrained input | Sections 2.1, 3.2 (`anyOf`, real-date check), 4.2, 5.2; FR-SEARCH-008 and FR-SEARCH-010 |
| Output schemas enforce consistent success and error states | Sections 3.3, 4.3, 5.3 (`if`/`then`/`else`); Section 9 |
| Caller identity, visibility, and authorization defined for every tool | Sections 2.2 to 2.5 |
| Agent architecture, intent routing, and conversation framework defined | Section 6 |
| Data persistence, 3 Supabase tables, and frontend chat retrieval specified | Section 7 |
| Security boundaries, human-in-the-loop, and guardrail rules specified | Section 8 |
| Specification and schemas are stored in the repository | This file: `docs/agent-tool-specification.md`; schemas are checked by `tests/test_agent_tool_spec_schemas.py` |
| Specification is signed off | Section 11 must be completed before implementation begins |

---

## 11. Sign-off

The specification is not approved until each required approver records a decision. Approval means the approver accepts the functional requirements, schemas, access policy, privacy boundary, and draft confirmation behavior in this document.

| Role | Name | Decision | Date | Notes |
|---|---|---|---|---|
| Product owner | Pending | Pending | Pending | Pending |
| Engineering owner | Pending | Pending | Pending | Pending |
| Design/conversation owner | Pending | Pending | Pending | Pending |
| Security/privacy reviewer | Pending | Pending | Pending | Pending |

**Approval rule:** All required roles must record `Approved`. Any `Changes requested` decision returns the document to `DRAFT` and requires a new version after revision.

---

## 12. Open Decisions Before Sign-off

1. **Publish Workflow (Resolved):** The draft tool remains preview-only. Event creation is executed by the user via the frontend publish method `POST /api/events/` (human-in-the-loop).
2. **Session Persistence (Resolved):** Full Supabase persistence using 3 tables (`ai_conversations`, `ai_messages`, `ai_agent_audit_logs`) without Redis.
3. Which event fields are mandatory in the user experience beyond the API minimum: category, location, cost, and capacity?
4. **Visibility rules (Resolved in v0.2):** Only active, not-yet-ended events are visible to the assistant. See Section 2.3.
5. Should search support a date range and radius/geolocation filters in the first release?
6. **Caller identity and permission context (Resolved in v0.2):** See Sections 2.2 and 2.4.
7. What are the required names of the product, product owner, engineering owner, conversation owner, and security/privacy approver?
8. Should Get Event Details return cancelled events (marked as cancelled) so the assistant can tell a user that an event they asked about was cancelled? Version 0.2 says no and returns `NOT_FOUND`. Changing this needs a spec revision because it changes Section 2.3 and the `status` field in the output schemas.

---

## 13. Known Implementation Gaps

These are differences between this specification and the code on `dev` on 2026-10-12. They do not block sign-off of the document, but the tools must not be marked done until each one is fixed or the specification is changed and signed off again.

| # | Gap | Location | Rule broken |
|---|---|---|---|
| 1 | Tool services read events with the shared client created from `SUPABASE_SERVICE_KEY`, not a per-user client. | `app/db/supabase_client.py`, used by the search and details services | Section 2.2 rule 4, Section 8.2 |
| 2 | Search accepts `{}`, `{"query": null}`, and whitespace-only values, and then returns all upcoming events. | `app/schemas/event_search_schema.py`, `app/services/event_search_service.py` | FR-SEARCH-010 |
| 3 | Search service takes no caller context; it relies only on the route's `get_current_user` check. | `app/services/event_search_service.py`, `app/api/v1/assistant_routes.py` | Section 2.2 |
| 4 | Details returns `FORBIDDEN` ("You cannot view this event.") for cancelled or ended events, which confirms the event exists. | `app/services/event_details_service.py` (`_is_visible` branch) | FR-DETAIL-004, Section 2.5 |
| 5 | Draft accepts `user_id=None` and has no onboarding check. | `app/services/event_draft_service.py` | FR-DRAFT-009, Section 2.4 |
| 6 | Draft replaces a missing `cost` with `0.0` in the preview. | `app/services/event_draft_service.py` | FR-DRAFT-008 |
| 7 | Draft accepts date-times without a timezone offset, such as `2026-10-12T10:00`, because `datetime.fromisoformat` allows them. | `app/schemas/event_draft_schema.py` | FR-DRAFT-004 |
| 8 | Agent tool functions are placeholders that always return `success: true` with empty data; the draft placeholder returns `"draft": {}`, which fails the output schema. | `app/agents/tools.py` | Sections 3.3, 4.3, 5.3 |

Related note outside the tools: `GET /api/events/{event_id}` is public and returns cancelled events. So `NOT_FOUND` from the assistant hides nothing secret today; the rule exists so the assistant stays safe if restricted events are added later.