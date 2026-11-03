from townlight_records.models.audit import AuditLog
from townlight_records.models.document import DataSource, Document, DocumentChunk, IngestionStatus, SourceType
# Phase 2 Step 5c: ModelRegistry now lives in townlight_core.llm.registry.
# Re-export here so existing imports (`from townlight_records.models import ModelRegistry`)
# keep working.
from townlight_core.llm.registry import ModelRegistry
from townlight_records.models.exemption import DisclosureTemplate, ExemptionFlag, ExemptionRule, FlagStatus, RuleType
from townlight_records.models.request import DocumentCache, InclusionStatus, RecordsRequest, RequestDocument, RequestStatus
from townlight_records.models.search import SearchQuery, SearchResult, SearchSession
from townlight_records.models.service_account import ServiceAccount
from townlight_records.models.user import Base, User, UserRole

# Phase 2 models
from townlight_records.models.departments import Department
from townlight_records.models.fees import FeeSchedule, FeeLineItem, FeeWaiver
from townlight_records.models.request_workflow import RequestTimeline, RequestMessage, ResponseLetter, RequestPublicStatus
from townlight_records.models.records_evidence import RequestEvidenceNote, RequestExemptionDecision
from townlight_records.models.records_files import RequestFileEvidence, RequestReleaseCopy
from townlight_records.models.records_artifacts import RequestArtifact, RequestPublication
from townlight_records.models.notifications import NotificationTemplate, NotificationLog
# Phase 2 Step 5c: PromptTemplate now lives in townlight_core.llm.templates.
# Re-export here so existing imports (`from townlight_records.models import PromptTemplate`)
# keep working.
from townlight_core.llm.templates import PromptTemplate
from townlight_records.models.city_profile import CityProfile
from townlight_records.models.connectors import SystemCatalog, ConnectorTemplate

# P7 models
from townlight_records.models.sync_failure import SyncFailure, SyncRunLog

__all__ = [
    "Base", "User", "UserRole", "ServiceAccount", "AuditLog",
    "DataSource", "Document", "DocumentChunk", "IngestionStatus", "SourceType",
    "ModelRegistry",
    "SearchSession", "SearchQuery", "SearchResult",
    "RecordsRequest", "RequestDocument", "DocumentCache", "RequestStatus", "InclusionStatus",
    "ExemptionRule", "ExemptionFlag", "DisclosureTemplate", "RuleType", "FlagStatus",
    # Phase 2
    "Department", "FeeSchedule", "FeeLineItem", "FeeWaiver",
    "RequestTimeline", "RequestMessage", "ResponseLetter", "RequestPublicStatus",
    "RequestEvidenceNote", "RequestExemptionDecision",
    "RequestFileEvidence", "RequestReleaseCopy", "RequestArtifact", "RequestPublication",
    "NotificationTemplate", "NotificationLog",
    "PromptTemplate", "CityProfile",
    "SystemCatalog", "ConnectorTemplate",
    # P7
    "SyncFailure", "SyncRunLog",
]
