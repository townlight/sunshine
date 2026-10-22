"""P4 continuation of the real Code/Zoning/Meetings PostgreSQL acceptance fixture.

Called by test_desktop_zoning after its existing source/citation checks. No model,
installer activation or external publication occurs. All municipal data is fictional.
"""
import base64
from datetime import date
import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.test_desktop_records_artifacts import prepare, complete, write_test_export
from tests.test_desktop_records_files import staged_file
from tests.test_desktop_records_lifecycle import operation


async def check_planning(api, headers, actor_id, records_app, url, zoning, archive_id):
    from civicplan.main import app as planning_app
    from civicplan.migrations import source_engine, upgrade
    from civicplan.source_store import PlanSourceRepository
    from civicplan.source_bundle import PlanBundle
    from civicplan.workflow_store import WorkflowRepository
    from civicsuite_runtime.planning_connections import configure

    records_app.state.desktop_enabled_modules = frozenset({
        *records_app.state.desktop_enabled_modules, "civicplan", "civicaccess"})
    configure(records_app, planning_app, url)
    engine = source_engine(url)
    upgrade(engine)
    sources = PlanSourceRepository(engine)
    raw = b"Fictional adopted policy. Support housing near civic services."
    payload = {
        "plan_id": "fictional-p4", "title": "Fictional Planning P4",
        "jurisdiction": "Fictional Redstone", "plan_type": "comprehensive",
        "status": "adopted", "visibility": "public", "source_date": "2026-01-01",
        "adopted_on": "2026-02-01", "effective_on": "2026-03-01",
        "change_note": "Explicit fictional adoption", "reviewer_label": "Fictional Planner",
        "documents": [{"document_id": "policy", "filename": "fictional.txt", "media_type": "text/plain",
                       "sha256": hashlib.sha256(raw).hexdigest(), "content_base64": base64.b64encode(raw).decode()}],
        "policies": [{"policy_id": "P4-1", "document_id": "policy", "goal": "Housing choice",
                      "objective": "Access", "topic_key": "housing", "title": "Housing policy",
                      "citation": "Fictional P4 Plan, policy 1", "anchor": "paragraph 1",
                      "excerpt": "Support housing near civic services.", "relevance": "Staff review applicability.",
                      "staff_verified": True}],
        "adoption_evidence": [{"kind": "manual-record", "reference": "Fictional staff adoption record",
                               "document_id": "policy", "note": "Not a live adoption determination."}],
    }
    revision = sources.import_bundle(PlanBundle.model_validate(payload), actor_id=str(actor_id))
    workflow = WorkflowRepository(sources, planning_app.state.planning_providers,
                                  planning_app.state.planning_access_rewrite)
    # A direct dependency override supplies the same persisted repository to the
    # trusted service API without changing process-wide database/key configuration.
    from civicplan.source_api import repository, staff
    planning_app.dependency_overrides[repository] = lambda: sources
    planning_app.dependency_overrides[staff] = lambda: "fixture-trusted-service"
    client = TestClient(planning_app)
    try:
        meeting = next(d for d in records_app.state.desktop_meetings_sources()
                       if d["archive_id"] == archive_id and d["kind"] == "minutes")
        ref = {"plan_id": payload["plan_id"], "revision_id": revision["revision_id"], "policy_id": "P4-1"}
        draft = {"project_name": "Fictional connected Planning review", "proposal": "PRIVATE proposed project",
                 "selected_policies": [ref], "staff_notes": "PRIVATE staff note", "linked_sources": [
                     {"provider": provider, "source_id": source["source_id"], "expected_sha256": source["sha256"],
                      "relation": "hearing"} for provider, source in (("meetings", meeting), ("zoning", zoning))]}
        saved = client.post("/api/v1/civicplan/analyses", json=draft)
        assert saved.status_code == 200, saved.text
        first = saved.json()
        draft.update(expected_previous_revision=first["revision_id"], audience="public", review_state="reviewed",
                     reviewer_label="Recorded fictional planner", reviewed_on=date.today().isoformat(),
                     review_notes="Staff checked selected sources.", analysis_text="Staff edited conditional analysis.",
                     public_summary="Public explanation under cited planning policy; no determination.",
                     considerations=[{"policy": ref, "stance": "uncertain", "note": "Staff reconcile applicability."}])
        path = "/api/v1/civicplan/analyses/" + first["analysis_id"]
        edited = client.post(path + "/revisions", json=draft)
        assert edited.status_code == 200, edited.text
        current = edited.json()
        result = client.post(path + "/snapshots", json={"expected_revision": current["revision_id"], "visibility": "public"})
        assert result.status_code == 200, result.text
        snapshot = result.json()
        assert "PRIVATE" not in snapshot["text"]
        assert meeting["text"] in snapshot["text"] and zoning["source_id"] in snapshot["text"]
        assert "land-use determinations" in snapshot["text"]
        exported = client.get("/api/v1/civicplan/snapshots/" + snapshot["version"] + "/export")
        assert exported.content == snapshot["text"].encode()
        advice = client.post("/api/v1/civicplan/snapshots/" + snapshot["version"] + "/access-advice")
        assert advice.status_code == 200 and advice.json()["original"] == snapshot["text"]
        assert advice.json()["advice"]["review_required"] is True

        intake = await api.post("/desktop/v1/requests", headers=headers, json={
            "requester": "Fictional P4 resident", "summary": "Planning review records",
            "deadline": "2026-11-01", "deadlineBasis": "Fictional staff basis"})
        assert intake.status_code == 201, intake.text
        request_id = intake.json()["id"]
        endpoint = "/desktop/v1/requests/" + request_id
        search = "/desktop/v1/planning-sources/search"
        assert (await api.post(search, json={"query": "Planning"})).status_code == 401
        found = await api.post(search, json={"query": "Planning"}, headers=headers)
        assert found.status_code == 200 and snapshot["source_id"] in found.text
        selection = {"source_id": snapshot["source_id"], "expected_sha256": snapshot["sha256"]}
        assert (await api.post(endpoint + "/planning-sources", headers=headers,
                               json={**selection, "expected_sha256": "0" * 64})).status_code == 409
        attached = await api.post(endpoint + "/planning-sources", headers=headers, json=selection)
        assert attached.status_code == 200, attached.text
        document = attached.json()["request"]["documents"][0]
        assert Path(document["stored_path"]).read_bytes() == exported.content
        assert document["sha256"] == snapshot["sha256"]
        # Human review still controls release-copy, decision, response and approval.
        await prepare(api, headers["X-Townlight-Session"], request_id, "response", 400)
        receipt = staged_file(records_app, "planning-public-copy.json", exported.content)
        release = await api.post(endpoint + "/documents/" + document["attachment_id"] + "/release-copy",
                                 headers=headers, json={"status": "release-ready copy", "note": "Fictional human review", "file": receipt})
        assert release.status_code == 200, release.text
        proof = headers["X-Townlight-Session"]
        await operation(api, proof, request_id, "add-records-exemption-decision", {
            "exemptionSource": snapshot["citation"], "exemptionKind": "Human review", "exemptionFinding": "Public source",
            "exemptionDecision": "release", "exemptionBasis": "Explicit fictional staff selection"})
        await operation(api, proof, request_id, "draft-records-response", {"responseDraft": "Reviewed public Planning snapshot supplied."})
        await operation(api, proof, request_id, "approve-records-response", {"approvalNote": "Fictional human approved"})
        response = await prepare(api, proof, request_id, "response")
        output = write_test_export(records_app, response)

        def visibility(value):
            with engine.begin() as connection:
                connection.execute(text("UPDATE civicclerk.public_meeting_records SET visibility=:value WHERE id=:id"),
                                   {"value": value, "id": archive_id})
        visibility("closed_session")
        assert workflow.public_documents(source_id=snapshot["source_id"]) == []
        assert (await api.post(search, json={"query": "Planning"}, headers=headers)).json()["results"] == []
        assert (await api.post(endpoint + "/planning-sources", headers=headers, json=selection)).status_code == 404
        assert (await api.get(endpoint + "/view", headers=headers)).status_code == 503
        assert (await api.get(endpoint, headers=headers)).status_code == 503
        await prepare(api, proof, request_id, "response", 503)
        await complete(api, proof, request_id, response, output, 503)
        assert output.read_bytes() == response["content"].encode()
        visibility("public")
        await complete(api, proof, request_id, response, output)
        package = await prepare(api, proof, request_id, "release-package")
        package_path = write_test_export(records_app, package)
        assert snapshot["sha256"] in package["content"]
        await complete(api, proof, request_id, package, package_path)
        visibility("closed_session")
        await operation(api, proof, request_id, "fulfill-records-request", expected_status=503)
        visibility("public")
        # Later staff edits and adopted amendments preserve the earlier selected bytes.
        draft.update(expected_previous_revision=current["revision_id"], analysis_text="Later staff revision.")
        assert client.post(path + "/revisions", json=draft).status_code == 200
        payload["change_note"] = "Later fictional amendment"
        sources.import_bundle(PlanBundle.model_validate(payload), actor_id=str(actor_id),
                              expected_previous_revision=revision["revision_id"])
        assert workflow.document(snapshot["version"])["text"] == snapshot["text"]
        assert workflow.audit(first["analysis_id"])["ok"]
        fulfilled = await operation(api, proof, request_id, "fulfill-records-request")
        assert fulfilled["request"]["fulfilled_at_unix_seconds"] is not None
        assert output.read_bytes() == response["content"].encode()
        assert hashlib.sha256(Path(document["stored_path"]).read_bytes()).hexdigest() == snapshot["sha256"]
        # Authenticated staff-only Planning snapshots are never public Records sources.
        private = client.post(path + "/snapshots", json={"expected_revision": client.get(path).json()["revision_id"],
                                                         "visibility": "staff_only"})
        assert private.status_code == 200
        assert workflow.public_documents(source_id=private.json()["source_id"]) == []
        evidence_dir = os.environ.get("TOWNLIGHT_PLANNING_EVIDENCE_DIR")
        if evidence_dir:
            # Preserve actual fixture files before the temporary native profile
            # is removed. Database readback retains its original paths; this map
            # identifies the archived bytes rather than pretending it is installed.
            evidence_root = Path(evidence_dir)
            evidence_root.mkdir(parents=True, exist_ok=True)
            files = []
            for index, source_path in enumerate((Path(document["stored_path"]), Path(receipt["stored_path"]), output, package_path)):
                content = source_path.read_bytes()
                target = evidence_root / f"connected-file-{index}{source_path.suffix}"
                target.write_bytes(content)
                files.append({"original_path": str(source_path), "archived_path": str(target),
                              "sha256": hashlib.sha256(content).hexdigest()})
            (evidence_root / "connected-files.json").write_text(json.dumps(files, indent=2), encoding="utf-8")
    finally:
        with engine.begin() as connection:
            connection.execute(text("UPDATE civicclerk.public_meeting_records SET visibility='public' WHERE id=:id"), {"id": archive_id})
        planning_app.dependency_overrides.clear()
        engine.dispose()
