"""Records export decisions and durable finalization; native code writes bytes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from sqlalchemy import select

from app.desktop_bridge.projection import request_view
from app.desktop_bridge.schemas import ArtifactPlan
from app.models.records_artifacts import RequestArtifact, RequestPublication
from app.models.request import RequestStatus
from app.requests import workflow
from app.requests.files import managed_records_root


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_current_approval(req):
    if not (req.response_draft or "").strip():
        raise ValueError("Draft a records response before exporting.")
    if req.approved_at is None or req.approved_response_sha256 != text_hash(req.response_draft):
        raise ValueError("Approve the current records response before export or fulfillment.")


def rows_text(rows):
    if not rows:
        return "None recorded."
    lines = []
    for row in rows:
        if isinstance(row, str):
            lines.append(f"- {row}")
        else:
            fields = row.model_dump() if hasattr(row, "model_dump") else row
            lines.append("\n".join(f"  {key.replace('_', ' ').title()}: {value}" for key, value in fields.items()))
    return "\n".join(lines)


def render(view, kind):
    title = "Records Response" if kind == "response" else "Records Release Package Manifest"
    header = (f"# {title}\n\nTracking number: {view.public_tracking_number or 'Not assigned'}\n"
              f"Requester: {view.requester}\nContact: {view.requester_contact or 'No contact recorded.'}\n"
              f"Submitted via: {view.submitted_via}\nDeadline: {view.deadline}\nDeadline basis: {view.deadline_basis}\n"
              f"Assigned to: {view.assigned_to or 'Unassigned'}\nStatus: {view.status}\nFee estimate: {view.fee_estimate}\n"
              f"\n## Request\n{view.summary}\n")
    sections = [("Request Timeline", view.timeline), ("Request Messages", view.messages),
                ("Request Documents", view.documents), ("Release Packages", view.release_packages),
                ("Fee Review", view.fee_line_items), ("Clarification Notes", view.clarification_notes),
                ("Search Notes", view.search_notes), ("Search Sessions", view.search_sessions),
                ("Exemption Review Notes", view.exemption_reviews), ("Exemption Decisions", view.exemption_decisions),
                ("Citations", view.citations), ("Approval Notes", view.approval_notes)]
    body = "".join(f"\n## {name}\n{rows_text(rows)}\n" for name, rows in sections)
    body += f"\nFee waiver: {view.fee_waiver_reason or 'None recorded.'}\n"
    body += f"\n## {'Approved Response' if kind == 'response' else 'Response Draft Snapshot'}\n{view.response_draft}\n"
    return header + body


async def prepare_artifact(session, req, actor, kind, *, demo_fixture=None):
    workflow.ensure_active(req)
    view = await request_view(session, req)
    counts = dict(document_count=len(view.documents), release_artifact_count=sum(bool(doc.release_sha256) for doc in view.documents),
                  search_session_count=len(view.search_sessions),
                  release_count=sum(dec.decision == "release" for dec in view.exemption_decisions),
                  redacted_count=sum(dec.decision == "redact" for dec in view.exemption_decisions),
                  exempt_count=sum(dec.decision == "exempt" for dec in view.exemption_decisions))
    if kind == "response":
        require_current_approval(req)
    else:
        if not view.documents and not view.search_sessions:
            raise ValueError("Attach request documents or save a structured search session before building a release package.")
        if not view.exemption_decisions:
            raise ValueError("Save release, redact, or exempt decisions before building a release package.")
        if view.documents:
            for key, required in (("release_count", "release-ready copy"), ("redacted_count", "redacted copy")):
                if counts[key] and not any(doc.release_status == required and doc.release_sha256 for doc in view.documents):
                    raise ValueError(f"Attach a {required} before packaging these decisions.")
    content = render(view, kind)
    if demo_fixture is not None:
        content = ("## Demo Fixture Identity\n"
            f"Municipality: {demo_fixture['municipality_name']}\n"
            f"Fixture: {demo_fixture['fixture_id']} v{demo_fixture['fixture_version']}\n"
            f"Fixture SHA-256: {demo_fixture['fixture_sha256']}\n"
            f"Watermark: {demo_fixture['watermark']}\n\n" + content)
    if kind == "release-package":
        content += "\n## Package Counts\n" + "\n".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in counts.items()) + "\n"
    artifact = RequestArtifact(id=uuid.uuid4(), request_id=req.id, kind=kind, content=content,
                               sha256=text_hash(content), response_sha256=text_hash(req.response_draft or ""),
                               actor_id=actor.user.id, **counts)
    session.add(artifact)
    await session.flush()
    # An intent is not an exported file, a successful package or a public event.
    return ArtifactPlan(artifact_id=str(artifact.id), file_name=f"records-{kind}-{artifact.id}.md",
                        content=content, sha256=artifact.sha256,
                        created_at_unix_seconds=int(artifact.created_at.timestamp()))


def verify_export(profile_root, artifact, path_text):
    try:
        path = Path(path_text).resolve(strict=True)
        export_root = managed_records_root(profile_root).parent.parent / "exports" / "records"
        if not path.is_relative_to(export_root.resolve()) or not path.is_file():
            raise ValueError("Outside export directory")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest = json.loads(path.with_name(path.name + ".manifest.json").read_text(encoding="utf-8"))
        if (digest != artifact.sha256 or manifest.get("sha256") != digest
                or manifest.get("size_bytes") != path.stat().st_size or manifest.get("export_file") != path.name):
            raise ValueError("Export verification failed")
    except (OSError, ValueError, TypeError, AttributeError):
        raise ValueError("The Records export or integrity manifest does not match the prepared bytes.") from None
    return str(path)


async def complete_artifact(session, req, actor, artifact_id, path_text, profile_root):
    artifact = await session.get(RequestArtifact, artifact_id, with_for_update=True)
    if artifact is None or artifact.request_id != req.id or artifact.actor_id != actor.user.id:
        raise ValueError("This prepared Records artifact does not belong to this request and actor.")
    path = verify_export(profile_root, artifact, path_text)
    if artifact.completed_at is not None:
        if artifact.export_path != path:
            raise ValueError("This artifact was already completed at another path.")
        return "Records artifact already verified; no duplicate completion was recorded."
    workflow.ensure_active(req)
    if artifact.kind == "response":
        require_current_approval(req)
        if text_hash(req.response_draft) != artifact.response_sha256:
            raise ValueError("The response changed after export preparation. Prepare the approved current response again.")
    artifact.export_path = path
    artifact.completed_at = datetime.now(timezone.utc)
    response = artifact.kind == "response"
    status = "response package exported" if response else "release package built"
    await workflow.record_progress(
        session, req, actor, action="export-records-response" if response else "build-records-release-package",
        status=status, canonical_status=req.status, timeline_action=status,
        timeline_note=f"{'Approved response' if response else 'Release package manifest'} written to {path}; sha256 {artifact.sha256}.",
        public_label="Response package exported" if response else "Release package prepared",
        public_summary="The approved response package was exported for release." if response else "Staff prepared the release package for fulfillment.",
        audit_note=f"Verified {artifact.kind} at {path}; sha256 {artifact.sha256}.",
    )
    return f"Records {artifact.kind} written and verified at {path}."


async def fulfill(session, req, actor):
    workflow.ensure_active(req)
    require_current_approval(req)
    completed = (await session.execute(select(RequestArtifact).where(
        RequestArtifact.request_id == req.id, RequestArtifact.completed_at.is_not(None)
    ))).scalars().all()
    if not any(row.kind == "response" for row in completed):
        raise ValueError("Export the approved records response package before fulfillment.")
    if not any(row.kind == "release-package" for row in completed):
        raise ValueError("Build the records release package before fulfillment.")
    exports = "; ".join(row.export_path for row in completed if row.kind == "response")
    tracking = req.public_tracking_number or "without tracking number"
    payload = f"Records request {tracking} fulfilled for {req.requester_name}. Deadline: {req.deadline_label}. Exports: {exports}."
    req.fulfilled_at = datetime.now(timezone.utc)
    session.add(RequestPublication(request_id=req.id, payload=payload, payload_hash=text_hash(payload), actor_id=actor.user.id))
    await workflow.record_progress(
        session, req, actor, action="fulfill-records-request", status="fulfilled", canonical_status=RequestStatus.FULFILLED,
        timeline_action="fulfilled", timeline_note="Approved response package marked fulfilled.", public_label="Response ready",
        public_summary="The approved records response has been marked fulfilled.",
        audit_note="Marked records request fulfilled after human approval and export.",
        notification=("requester", f"Records request {tracking} response ready",
                      f"The approved response for {req.requester_name} has been marked fulfilled. Deadline: {req.deadline_label}. Export package: {exports}."),
    )
    return "Records request fulfilled and eligible for public status display."


async def close(session, req, actor):
    if req.closed_at is not None or req.status == RequestStatus.CLOSED:
        raise ValueError("This records request is already closed.")
    if req.fulfilled_at is None:
        raise ValueError("Fulfill the records request before closing it.")
    req.closed_at = datetime.now(timezone.utc)
    await workflow.record_progress(
        session, req, actor, action="close-records-request", status="closed", canonical_status=RequestStatus.CLOSED,
        timeline_action="closed", timeline_note="Fulfilled request closed with audit, export, and notification evidence preserved.",
        public_label="Request closed", public_summary="The fulfilled records request was closed locally.",
        audit_note="Closed fulfilled records request.",
        notification=("records staff", f"Records request {req.public_tracking_number} closed",
                      "The fulfilled records request is closed. Audit, export, publication, and notification evidence remain in the local profile."),
    )
    return "Records request closed with evidence preserved."
