# Product Orientation Assistant Tool Specification

- **Status:** DRAFT - pending product and engineering sign-off
- **Version:** 0.1
- **Scope:** The three tools available to the product-orientation chat assistant
- **Owner:** Product team
- **Last updated:** 2026-09-14

## 1. Purpose

The assistant helps users understand and use the events product through chat. It may call three tools:

1. Search for events.
2. Retrieve the details of one event.
3. Draft a new event.

The assistant must use tools for authoritative event data. It must not claim that an event exists, has been changed, or has been published unless the corresponding tool response confirms it.

## 2. Common Tool Contract

Every tool call has:

- A JSON input object that validates against the tool's input schema.
- A JSON output object that validates against the tool's output schema.
- A stable `request_id` for tracing the call.
- A `success` boolean.
- A structured `error` object when `success` is `false`.

Dates and times use ISO 8601 strings with an explicit timezone offset or `Z`. Identifiers are UUID strings unless the implementation specifies another identifier format.

Tool calls must not expose service-role credentials, internal database errors, or unrestricted personal data.

## 3. Tool: Search Events

### 3.1 Functional requirements

- **FR-SEARCH-001:** Accept a free-text search query and optional event filters.
- **FR-SEARCH-002:** Support the product's current discovery filters: category, upcoming status, date, and city (matched against `location_name`).
- **FR-SEARCH-003:** Support pagination with a positive page number, bounded page size, total record count, and `has_next` calculation.
- **FR-SEARCH-004:** Return only events visible to the requesting user according to the product's access rules.
- **FR-SEARCH-005:** Return enough summary data for the assistant to explain and compare results without requiring a detail call for every result.
- **FR-SEARCH-006:** Return an empty result set with `success: true` when no events match; this is not an error.
- **FR-SEARCH-007:** Apply deterministic ordering. The initial default is upcoming events ordered by start time ascending, followed by a stable identifier as a tie-breaker.
- **FR-SEARCH-008:** Reject invalid pagination or filter values with a structured validation error.
- **FR-SEARCH-009:** The assistant should ask a clarifying question when the user's request is too ambiguous to form a useful search, rather than issuing an unconstrained search.

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
      "description": "Free-text terms matched against event content.",
      "maxLength": 200
    },
    "category": {
      "type": ["string", "null"],
      "maxLength": 100
    },
    "upcoming": {
      "type": "boolean",
      "default": true
    },
    "date": {
      "type": ["string", "null"],
      "description": "Date filter in YYYY-MM-DD format.",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
    },
    "city": {
      "type": ["string", "null"],
      "description": "City or locality name matched against event location_name.",
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
  }
}
```

### 3.3 Output schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SearchEventsOutput",
  "type": "object",
  "required": ["request_id", "success", "events", "pagination", "error"],
  "properties": {
    "request_id": { "type": "string", "minLength": 1 },
    "success": { "type": "boolean" },
    "events": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "title", "start_datetime", "status"],
        "properties": {
          "id": { "type": "string" },
          "title": { "type": "string" },
          "description": { "type": ["string", "null"] },
          "category": { "type": ["string", "null"] },
          "start_datetime": { "type": "string", "format": "date-time" },
          "end_datetime": { "type": ["string", "null"], "format": "date-time" },
          "location_name": { "type": ["string", "null"] },
          "cost": { "type": ["number", "null"], "minimum": 0 },
          "max_capacity": { "type": ["integer", "null"], "minimum": 1 },
          "status": { "type": "string" }
        }
      }
    },
    "pagination": {
      "type": "object",
      "required": ["page", "limit", "total", "has_next"],
      "properties": {
        "page": { "type": "integer", "minimum": 1 },
        "limit": { "type": "integer", "minimum": 1 },
        "total": { "type": "integer", "minimum": 0 },
        "has_next": { "type": "boolean" }
      }
    },
    "error": { "$ref": "#/$defs/Error" }
  },
  "$defs": {
    "Error": {
      "type": ["object", "null"],
      "required": ["code", "message"],
      "properties": {
        "code": { "type": "string" },
        "message": { "type": "string" },
        "field": { "type": ["string", "null"] }
      }
    }
  }
}
```

## 4. Tool: Get Event Details

### 4.1 Functional requirements

- **FR-DETAIL-001:** Accept exactly one event identifier.
- **FR-DETAIL-002:** Return the current authoritative event record when the event exists and is visible to the requesting user.
- **FR-DETAIL-003:** Return the event's identity, description, category, timing, location, cost, capacity, status, and creator reference when available.
- **FR-DETAIL-004:** Return a not-found error when the identifier does not refer to an accessible event.
- **FR-DETAIL-005:** Never invent missing event fields. Optional or unavailable values must be returned as `null` or omitted according to the schema.
- **FR-DETAIL-006:** The assistant should use this tool before answering detailed questions about one event when the search result does not contain enough information.

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
      "minLength": 1
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
  "required": ["request_id", "success", "event", "error"],
  "properties": {
    "request_id": { "type": "string", "minLength": 1 },
    "success": { "type": "boolean" },
    "event": {
      "type": ["object", "null"],
      "required": ["id", "title", "start_datetime", "end_datetime", "status"],
      "properties": {
        "id": { "type": "string" },
        "title": { "type": "string" },
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
        "status": { "type": "string" }
      }
    },
    "error": { "$ref": "#/$defs/Error" }
  },
  "$defs": {
    "Error": {
      "type": ["object", "null"],
      "required": ["code", "message"],
      "properties": {
        "code": { "type": "string" },
        "message": { "type": "string" },
        "field": { "type": ["string", "null"] }
      }
    }
  }
}
```

## 5. Tool: Draft New Event

### 5.1 Functional requirements

- **FR-DRAFT-001:** Accept the fields required to describe a new event and optional fields supported by the product.
- **FR-DRAFT-002:** Require `title`, `start_datetime`, and `end_datetime`.
- **FR-DRAFT-003:** Validate that the end is later than the start, cost is non-negative, capacity is positive when supplied, and coordinates are within valid geographic bounds.
- **FR-DRAFT-004:** Normalize dates to ISO 8601 and preserve the supplied timezone information.
- **FR-DRAFT-005:** Return a draft preview and a list of validation issues, if any.
- **FR-DRAFT-006:** Do not persist, publish, notify participants, or add the creator as a participant during drafting.
- **FR-DRAFT-007:** The agent never directly creates, persists, or publishes an event. Drafted events are returned to the user, and event creation occurs exclusively through the user's explicit publish action in the application interface (human-in-the-loop).
- **FR-DRAFT-008:** Never silently replace invalid or missing user-provided values with defaults. Return a validation issue that the assistant can explain.
- **FR-DRAFT-009:** Require authentication or an equivalent permission check before allowing a draft to proceed, subject to the final product access policy.

### 5.2 Input schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "DraftNewEventInput",
  "type": "object",
  "additionalProperties": false,
  "required": ["title", "start_datetime", "end_datetime"],
  "properties": {
    "title": { "type": "string", "minLength": 1, "maxLength": 200 },
    "description": { "type": ["string", "null"], "maxLength": 5000 },
    "category": { "type": ["string", "null"], "maxLength": 100 },
    "cost": { "type": ["number", "null"], "minimum": 0 },
    "max_capacity": { "type": ["integer", "null"], "minimum": 1 },
    "start_datetime": { "type": "string", "format": "date-time" },
    "end_datetime": { "type": "string", "format": "date-time" },
    "location_name": { "type": ["string", "null"], "maxLength": 300 },
    "latitude": { "type": ["number", "null"], "minimum": -90, "maximum": 90 },
    "longitude": { "type": ["number", "null"], "minimum": -180, "maximum": 180 }
  }
}
```

### 5.3 Output schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "DraftNewEventOutput",
  "type": "object",
  "required": ["request_id", "success", "draft", "validation_issues", "error"],
  "properties": {
    "request_id": { "type": "string", "minLength": 1 },
    "success": { "type": "boolean" },
    "draft": {
      "type": ["object", "null"],
      "properties": {
        "title": { "type": "string" },
        "description": { "type": ["string", "null"] },
        "category": { "type": ["string", "null"] },
        "cost": { "type": ["number", "null"] },
        "max_capacity": { "type": ["integer", "null"] },
        "start_datetime": { "type": "string", "format": "date-time" },
        "end_datetime": { "type": "string", "format": "date-time" },
        "location_name": { "type": ["string", "null"] },
        "latitude": { "type": ["number", "null"] },
        "longitude": { "type": ["number", "null"] }
      }
    },
    "validation_issues": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["code", "message", "severity"],
        "properties": {
          "code": { "type": "string" },
          "field": { "type": ["string", "null"] },
          "message": { "type": "string" },
          "severity": { "type": "string", "enum": ["error", "warning"] }
        }
      }
    },
    "error": { "$ref": "#/$defs/Error" }
  },
  "$defs": {
    "Error": {
      "type": ["object", "null"],
      "required": ["code", "message"],
      "properties": {
        "code": { "type": "string" },
        "message": { "type": "string" },
        "field": { "type": ["string", "null"] }
      }
    }
  }
}
```

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
   The agent has read and draft preview capabilities only. It cannot autonomously persist, publish, or modify events in the database. All event creation occurs only when the human user reviews the draft card in the UI and explicitly triggers the application's publish method (`POST /api/v1/events/`).
2. **Authenticated User Session Tokens:**
   All tool operations invoked on behalf of a user strictly pass and execute under that user's authenticated session credentials (JWT / Bearer token). The agent is never granted elevated system privileges or access to the Supabase service-role key (`SUPABASE_SERVICE_KEY`).
3. **Zero Direct Database Access:**
   The agent has no direct connection string, network route, or permission to execute raw database queries against PostgreSQL / Supabase.
4. **Backend Function Reuse:**
   Tool implementations do not reimplement business logic; they strictly wrap existing, audited FastAPI endpoints and backend service functions (e.g., `app/services/event_service.py`). This guarantees that row-level security (RLS), field validations, coordinate checks, and rate limits are uniformly applied.
5. **Guardian / Guardrail Agent & Audit Logging:**
   A dedicated Guardian Agent acts as an input/output firewall, and all security decisions are permanently recorded in `ai_agent_audit_logs`:
   - **Input Filtering:** Intercepts prompt injection attacks, jailbreaks, system instruction exfiltration attempts, and off-topic requests before they reach the reasoning model.
   - **Output Filtering:** Verifies that agent replies do not leak internal database errors, access tokens, PII, or prompt templates.

---

## 9. Cross-tool Error Contract

The following error codes are reserved for the initial version:

| Code | Meaning |
|---|---|
| `INVALID_INPUT` | The input does not satisfy the schema. |
| `NOT_FOUND` | The requested event does not exist or is not accessible. |
| `UNAUTHORIZED` | Authentication or permission is required. |
| `FORBIDDEN` | The user is authenticated but cannot perform the operation. |
| `SERVICE_UNAVAILABLE` | The event service is temporarily unavailable. |
| `INTERNAL_ERROR` | An unexpected server-side failure occurred. |

When `success` is `false`, the output must contain `error.code` and `error.message`. The message must be safe to show to the assistant and user.

---

## 10. Acceptance Criteria Traceability

| Acceptance criterion | Evidence in this specification |
|---|---|
| Functional requirements for all three tools are written down | Sections 3.1, 4.1, and 5.1 |
| Every tool call has an input and output schema | Sections 3.2-3.3, 4.2-4.3, and 5.2-5.3 |
| Agent architecture, intent routing, and conversation framework defined | Section 6 |
| Data persistence, 3 Supabase tables, and frontend chat retrieval specified | Section 7 |
| Security boundaries, human-in-the-loop, and guardrail rules specified | Section 8 |
| Specification and schemas are stored in the repository | This file: `docs/agent-tool-specification.md` |
| Specification is signed off | Section 11 must be completed before implementation begins |

---

## 11. Sign-off

The specification is not approved until each required approver records a decision. Approval means the approver accepts the functional requirements, schemas, privacy boundary, and draft confirmation behavior in this document.

| Role | Name | Decision | Date | Notes |
|---|---|---|---|---|
| Product owner | Pending | Pending | Pending | Pending |
| Engineering owner | Pending | Pending | Pending | Pending |
| Design/conversation owner | Pending | Pending | Pending | Pending |
| Security/privacy reviewer | Pending | Pending | Pending | Pending |

**Approval rule:** All required roles must record `Approved`. Any `Changes requested` decision returns the document to `DRAFT` and requires a new version after revision.

---

## 12. Open Decisions Before Sign-off

1. **Publish Workflow (Resolved):** The draft tool remains preview-only. Event creation is executed by the user via the frontend publish method (human-in-the-loop).
2. **Session Persistence (Resolved):** Full Supabase persistence using 3 tables (`ai_conversations`, `ai_messages`, `ai_agent_audit_logs`) without Redis.
3. Which event fields are mandatory in the user experience beyond the API minimum: category, location, cost, and capacity?
4. What visibility rules apply to event search and details: public events only, authenticated users, private/invited events, or another policy?
5. Should search support a date range and radius/geolocation filters in the first release?
6. What user identity and permission context will the assistant receive for tool calls?
7. What are the required names of the product, product owner, engineering owner, conversation owner, and security/privacy approver?


