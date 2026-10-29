from typing import Any, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from app.schemas.suspension_schema import SUSPENSION_REASON_MAX_LENGTH
from app.schemas.warning_schema import PersonSummary, WARNING_REASON_MAX_LENGTH


ReportStatus = Literal["open", "dismissed", "action_taken"]
ReportOutcome = Literal["dismissed", "warned", "content_removed", "suspended"]
ReportReason = Literal["spam", "inappropriate_content", "harassment_or_hate", "scam_or_fraud",
                       "misleading_event", "other"]
ReportOrigin = Literal["event_details", "profile", "event_chat"]
ReportTargetType = Literal["event", "user", "message"]


class ReportedEvent(BaseModel):
    id: str
    title: Optional[str] = None
    banner: Optional[str] = None
    banner_url: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class ReportedMessage(BaseModel):
    id: int
    event_id: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class ReportedContent(BaseModel):
    """What the report is about; only the part that fits its type is set."""
    type: ReportTargetType
    event: Optional[ReportedEvent] = None
    user: Optional[PersonSummary] = None
    message: Optional[ReportedMessage] = None

    model_config = ConfigDict(extra="ignore")


class AdminReportItem(BaseModel):
    id: int
    status: ReportStatus
    reason: ReportReason
    created_at: str
    target_type: ReportTargetType
    origin: ReportOrigin
    reporter: Optional[PersonSummary] = None
    reported: ReportedContent

    model_config = ConfigDict(extra="ignore")


class AdminReportOpenListResponse(BaseModel):
    total: int
    items: List[AdminReportItem]


class AdminReportListResponse(BaseModel):
    items: List[AdminReportItem]
    total: int
    page: int
    limit: int
    total_pages: int


class AdminReportDetailResponse(AdminReportItem):
    description: Optional[str] = None
    event: Optional[ReportedEvent] = None
    chat_context: Optional[Any] = None
    outcome: Optional[ReportOutcome] = None
    closed_by: Optional[PersonSummary] = None
    closed_at: Optional[str] = None
    content_removed: bool = False
    reported_user_is_administrator: bool = False


class ReportHistoryEntry(BaseModel):
    id: int
    status: ReportStatus
    created_at: str
    target_type: ReportTargetType
    reason: ReportReason

    model_config = ConfigDict(extra="ignore")


class ReportHistoryEvent(BaseModel):
    id: str
    title: str


class ReportAboutEntry(ReportHistoryEntry):
    """A report about the user; `event` is set only for a report about an event they organize."""
    event: Optional[ReportHistoryEvent] = None


class ReportHistory(BaseModel):
    about: List[ReportAboutEntry]
    made: List[ReportHistoryEntry]


class ReportActionRequest(BaseModel):
    """Act on a report. A warning and a suspension need a written reason; removing content does not."""
    action: Literal["warn", "suspend", "remove_content"]
    # validate_default: a missing reason must still reach the validator below (error location body.reason).
    reason: Optional[str] = Field(
        None, validate_default=True,
        description="Why. Required for warn and suspend (1 to 1000 characters), ignored for remove_content.")

    @field_validator("reason")
    @classmethod
    def reason_for_warn_and_suspend(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        action = info.data.get("action")        # declared above, so already validated; absent when invalid
        if action not in ("warn", "suspend"):
            return value
        limit = WARNING_REASON_MAX_LENGTH if action == "warn" else SUSPENSION_REASON_MAX_LENGTH
        value = (value or "").strip()
        if not value:
            raise ValueError("A reason is required.")
        if len(value) > limit:
            raise ValueError(f"The reason can have at most {limit} characters.")
        return value
