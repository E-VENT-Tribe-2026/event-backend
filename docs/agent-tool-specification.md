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
- **FR-SEARCH-002:** Support the product's current discovery filters: category, upcoming status, date, and city.
- **FR-SEARCH-003:** Support pagination with a positive page number and bounded page size.
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
          "city": { "type": ["string", "null"] },
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
- **FR-DRAFT-007:** Require explicit user confirmation before any future publish/create action is attempted.
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
  "required": ["request_id", "success", "draft", "validation_issues", "requires_confirmation", "error"],
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
    "requires_confirmation": { "type": "boolean", "const": true },
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

## 6. Cross-tool Error Contract

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

## 7. Acceptance Criteria Traceability

| Acceptance criterion | Evidence in this specification |
|---|---|
| Functional requirements for all three tools are written down | Sections 3.1, 4.1, and 5.1 |
| Every tool call has an input and output schema | Sections 3.2-3.3, 4.2-4.3, and 5.2-5.3 |
| Specification and schemas are stored in the repository | This file: `docs/agent-tool-specification.md` |
| Specification is signed off | Section 8 must be completed before implementation begins |

## 8. Sign-off

The specification is not approved until each required approver records a decision. Approval means the approver accepts the functional requirements, schemas, privacy boundary, and draft confirmation behavior in this document.

| Role | Name | Decision | Date | Notes |
|---|---|---|---|---|
| Product owner | Pending | Pending | Pending | Pending |
| Engineering owner | Pending | Pending | Pending | Pending |
| Design/conversation owner | Pending | Pending | Pending | Pending |
| Security/privacy reviewer | Pending | Pending | Pending | Pending |

**Approval rule:** All required roles must record `Approved`. Any `Changes requested` decision returns the document to `DRAFT` and requires a new version after revision.

## 9. Open Decisions Before Sign-off

1. Should the draft tool remain preview-only, or should a separate confirmed create/publish tool be added later?
2. Which event fields are mandatory in the user experience beyond the API minimum: category, location, cost, and capacity?
3. What visibility rules apply to event search and details: public events only, authenticated users, private/invited events, or another policy?
4. Should search support a date range and radius/geolocation filters in the first release?
5. What user identity and permission context will the assistant receive for tool calls?
6. What are the required names of the product, product owner, engineering owner, conversation owner, and security/privacy approver?
