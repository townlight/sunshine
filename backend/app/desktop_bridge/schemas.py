from datetime import date, datetime
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.request import RequestRead


class StaffRecordsIntake(BaseModel):
    """Existing native create-records-request input; no caller-supplied actor."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    requester: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    deadline: str
    deadlineBasis: str = ""

    @field_validator("deadline")
    @classmethod
    def valid_deadline(cls, value: str) -> str:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("Enter the records response deadline as YYYY-MM-DD.")
        return value


class NativeRequestRead(RequestRead):
    desktop_id: str | None
    public_tracking_number: str | None
    submitted_via: str
    deadline_label: str
    deadline_basis: str
    deadline_reviewed_at: datetime | None


class NativePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssignmentPayload(NativePayload):
    assignedTo: str = Field(min_length=1)


class DeadlinePayload(NativePayload):
    deadline: str
    deadlineBasis: str = Field(min_length=1)

    _deadline = field_validator("deadline")(StaffRecordsIntake.valid_deadline.__func__)


class CalculateDeadlinePayload(NativePayload):
    deadlineReceivedDate: str
    deadlineRuleName: str = Field(min_length=1)
    deadlineDayCount: str
    deadlineDayType: str
    deadlineBasis: str = Field(min_length=1)

    _date = field_validator("deadlineReceivedDate")(StaffRecordsIntake.valid_deadline.__func__)

    @field_validator("deadlineDayCount")
    @classmethod
    def bounded_days(cls, value):
        if not re.fullmatch(r"[0-9]+", value) or not 1 <= int(value) <= 365:
            raise ValueError("Deadline day count must be between 1 and 365.")
        return value

    @field_validator("deadlineDayType")
    @classmethod
    def day_type(cls, value):
        if value.lower() not in {"business", "business day", "business days", "working", "working days",
                                 "calendar", "calendar day", "calendar days"}:
            raise ValueError("Deadline day type must be business days or calendar days.")
        return value


class ClarificationPayload(NativePayload):
    clarificationNote: str = Field(min_length=1)


class MessagePayload(NativePayload):
    requestMessageBody: str = Field(min_length=1)


class SearchNotePayload(NativePayload):
    sourceNote: str = Field(min_length=1)
    citation: str = ""


class SearchReceiptPayload(NativePayload):
    searchQuery: str = Field(min_length=1)
    searchLocations: str = Field(min_length=1)
    searchResultTitle: str = Field(min_length=1)
    searchResultCitation: str = Field(min_length=1)
    searchResultSummary: str = Field(min_length=1)
    searchResultStatus: str = ""
    searchReviewer: str = ""


class ExemptionNotePayload(NativePayload):
    exemptionNote: str = Field(min_length=1)


class ExemptionDecisionPayload(NativePayload):
    exemptionSource: str = Field(min_length=1)
    exemptionKind: str = Field(min_length=1)
    exemptionFinding: str = Field(min_length=1)
    exemptionDecision: Literal["release", "redact", "exempt"]
    exemptionBasis: str = Field(min_length=1)
    exemptionReviewer: str = ""

    @field_validator("exemptionDecision", mode="before")
    @classmethod
    def lower_decision(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class FeeEstimatePayload(NativePayload):
    feeEstimate: str = Field(min_length=1)


class FeeLinePayload(NativePayload):
    feeLineDescription: str = Field(min_length=1)
    feeScheduleBasis: str = Field(min_length=1)
    feeLineAmount: str

    @field_validator("feeLineAmount")
    @classmethod
    def exact_cents(cls, value):
        normalized = value.lstrip("$").replace(",", "")
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", normalized):
            raise ValueError("Enter the fee amount as dollars and cents, such as 12.50.")
        dollars, _, cents = normalized.partition(".")
        amount = int(dollars) * 100 + int(cents.ljust(2, "0") or "0")
        if not 0 < amount <= 2**63 - 1:
            raise ValueError("Fee line amount must be greater than zero and fit exact stored cents.")
        return normalized


class FeeWaiverPayload(NativePayload):
    feeWaiverReason: str = Field(min_length=1)


class DraftPayload(NativePayload):
    responseDraft: str = Field(min_length=1)
    citation: str = ""


class ApprovalPayload(NativePayload):
    approvalNote: str = ""


class AssignCommand(NativePayload):
    action: Literal["assign-records-request"]
    payload: AssignmentPayload


class DeadlineCommand(NativePayload):
    action: Literal["set-records-deadline"]
    payload: DeadlinePayload


class CalculateDeadlineCommand(NativePayload):
    action: Literal["calculate-records-deadline"]
    payload: CalculateDeadlinePayload


class ClarificationCommand(NativePayload):
    action: Literal["request-records-clarification"]
    payload: ClarificationPayload


class MessageCommand(NativePayload):
    action: Literal["add-records-message"]
    payload: MessagePayload


class SearchNoteCommand(NativePayload):
    action: Literal["record-records-search"]
    payload: SearchNotePayload


class SearchReceiptCommand(NativePayload):
    action: Literal["record-records-search-session"]
    payload: SearchReceiptPayload


class ExemptionNoteCommand(NativePayload):
    action: Literal["add-records-exemption-review"]
    payload: ExemptionNotePayload


class ExemptionDecisionCommand(NativePayload):
    action: Literal["add-records-exemption-decision"]
    payload: ExemptionDecisionPayload


class FeeEstimateCommand(NativePayload):
    action: Literal["estimate-records-fee"]
    payload: FeeEstimatePayload


class FeeLineCommand(NativePayload):
    action: Literal["add-records-fee-line"]
    payload: FeeLinePayload


class FeeWaiverCommand(NativePayload):
    action: Literal["waive-records-fee"]
    payload: FeeWaiverPayload


class DraftCommand(NativePayload):
    action: Literal["draft-records-response"]
    payload: DraftPayload


class ApprovalCommand(NativePayload):
    action: Literal["approve-records-response"]
    payload: ApprovalPayload = Field(default_factory=ApprovalPayload)


class FinishCommand(NativePayload):
    action: Literal["fulfill-records-request", "close-records-request"]
    payload: NativePayload = Field(default_factory=NativePayload)


RecordsCommand = Annotated[
    AssignCommand | DeadlineCommand | CalculateDeadlineCommand | ClarificationCommand | MessageCommand
    | SearchNoteCommand | SearchReceiptCommand | ExemptionNoteCommand | ExemptionDecisionCommand
    | FeeEstimateCommand | FeeLineCommand | FeeWaiverCommand | DraftCommand | ApprovalCommand | FinishCommand,
    Field(discriminator="action"),
]


class NativeView(BaseModel):
    # Never normalize stored/imported evidence while projecting it.
    model_config = ConfigDict(extra="forbid")


class TimelineView(NativeView):
    id: str
    action: str
    actor: str
    note: str
    created_at_unix_seconds: int


class PublicStatusView(NativeView):
    id: str
    label: str
    summary: str
    status: str
    created_at_unix_seconds: int


class MessageView(NativeView):
    id: str
    author: str
    author_role: str
    body: str
    visibility: str
    created_at_unix_seconds: int


class FeeLineView(NativeView):
    id: str
    description: str
    schedule_basis: str
    amount_cents: int
    created_at_unix_seconds: int


class ExemptionDecisionView(NativeView):
    id: str
    source: str
    kind: str
    finding: str
    decision: Literal["release", "redact", "exempt"]
    basis: str
    reviewer: str
    created_at_unix_seconds: int


class SearchResultView(NativeView):
    id: str
    title: str
    citation: str
    summary: str
    status: str


class SearchReceiptView(NativeView):
    id: str
    query: str
    locations: str
    reviewer: str
    results: list[SearchResultView]
    created_at_unix_seconds: int


class RecordsView(NativeView):
    # Presentation boundary, not a second persisted representation.
    request_id: str
    id: str
    public_tracking_number: str
    requester: str
    requester_contact: str
    submitted_via: str
    summary: str
    deadline: str
    deadline_basis: str
    status: str
    assigned_to: str
    clarification_notes: list[str]
    search_notes: list[str]
    search_sessions: list[SearchReceiptView]
    exemption_reviews: list[str]
    exemption_decisions: list[ExemptionDecisionView]
    fee_estimate: str
    fee_line_items: list[FeeLineView]
    fee_waiver_reason: str
    citations: list[str]
    response_draft: str
    approval_notes: list[str]
    exports: list[str]
    documents: list["RecordsDocumentView"] = Field(default_factory=list)
    release_packages: list["ReleasePackageView"] = Field(default_factory=list)
    timeline: list[TimelineView]
    public_status_events: list[PublicStatusView]
    messages: list[MessageView]
    deadline_reviewed_at_unix_seconds: int | None
    approved_at_unix_seconds: int | None
    fulfilled_at_unix_seconds: int | None
    closed_at_unix_seconds: int | None
    created_at_unix_seconds: int


class RecordsOperationRead(NativeView):
    action: str
    message: str
    request: RecordsView


class RecordsStateRead(NativeView):
    records_requests: list[RecordsView]
    notification_events: list["NotificationView"] = Field(default_factory=list)
    publication_events: list["PublicationView"] = Field(default_factory=list)
    audit_entries: list["AuditView"] = Field(default_factory=list)


class ManagedFileReceipt(NativePayload):
    original_path: str = Field(min_length=1)
    stored_path: str = Field(min_length=1)
    file_name: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0, le=2147483647, strict=True)


class AttachDocument(NativePayload):
    title: str = Field(min_length=1)
    citation: str = ""
    file: ManagedFileReceipt


class AttachReleaseCopy(NativePayload):
    status: Literal["release-ready copy", "redacted copy"]
    note: str = ""
    added_by: str = ""
    file: ManagedFileReceipt


class RecordsDocumentView(NativeView):
    id: str
    attachment_id: str
    title: str
    original_path: str
    stored_path: str
    citation: str
    sha256: str
    size_bytes: int
    status: str
    added_by: str
    created_at_unix_seconds: int
    release_original_path: str = ""
    release_stored_path: str = ""
    release_file_name: str = ""
    release_sha256: str = ""
    release_size_bytes: int = 0
    release_status: str = ""
    release_note: str = ""
    release_added_by: str = ""
    release_added_at_unix_seconds: int | None = None


class ReleasePackageView(NativeView):
    id: str
    export_path: str
    package_hash: str
    document_count: int
    release_artifact_count: int
    search_session_count: int
    release_count: int
    redacted_count: int
    exempt_count: int
    created_at_unix_seconds: int


class PrepareArtifact(NativePayload):
    kind: Literal["response", "release-package"]


class ArtifactPlan(NativeView):
    artifact_id: str
    file_name: str
    content: str
    sha256: str
    created_at_unix_seconds: int


class CompleteArtifact(NativePayload):
    export_path: str = Field(min_length=1)


class PublicIntake(NativePayload):
    requester: str = Field(min_length=1)
    requesterContact: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    deadline: str = ""


class PublicLookup(NativePayload):
    trackingNumber: str = Field(min_length=1)
    requesterContact: str = Field(min_length=1)


class PublicMessage(PublicLookup):
    publicRequestMessage: str = Field(min_length=1)


class GeneratedDraft(NativePayload):
    text: str = Field(min_length=1)
    model: str = Field(min_length=1)
    previous_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class NotificationView(NativeView):
    id: str
    notification_id: str
    module_id: str
    record_id: str
    audience: str
    channel: str
    subject: str
    body: str
    status: str
    created_at_unix_seconds: int
    sent_at_unix_seconds: int | None


class PublicationView(NativeView):
    id: str
    source_module: str
    source_record_id: str
    record_type: str
    public_payload: str
    payload_hash: str
    published_at_unix_seconds: int
    retracted_at_unix_seconds: int | None = None
    retracted_by: str = ""


class AuditView(NativeView):
    id: str
    module_id: str
    action: str
    summary: str
    created_at_unix_seconds: int
    previous_hash: str
    entry_hash: str


RecordsView.model_rebuild()
RecordsOperationRead.model_rebuild()
RecordsStateRead.model_rebuild()
