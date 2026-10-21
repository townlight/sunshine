"""P2: native CivicZone import/lookup against real PostGIS and Code citations."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import TEST_DATABASE_URL

pytest.importorskip("civiczone")

from tests.test_desktop_records import native_api, native_profile  # noqa: F401


def _sibling(name: str) -> Path:
    root = os.environ.get("CIVICRECORDS_REPO_ROOT")
    if root:
        return Path(root) / ".ci-siblings" / name
    return next(
        parent / name for parent in Path(__file__).resolve().parents if (parent / name).is_dir()
    )


@pytest.mark.asyncio
async def test_zoning_native_postgres_import(native_api, monkeypatch):  # noqa: F811
    import logging
    for logger in list(logging.Logger.manager.loggerDict.values()):
        if isinstance(logger, logging.Logger):
            monkeypatch.setattr(logger, "disabled", logger.disabled)
    api, original_proof, actor_id, app = native_api

    from civicsuite_runtime.code_bridge import router as code_router
    from civicsuite_runtime.zoning_bridge import router as zoning_router
    from civicsuite_runtime.migrate import _run_alembic
    import civiccode.main as code
    import civiczone

    for cache_name in (
        "_source_registry_repository",
        "_section_lifecycle_repository",
        "_staff_workbench_repository",
        "_plain_language_repository",
        "_ordinance_handoff_repository",
        "_popular_question_repository",
        "_import_store",
        "_codifier_sync_store",
    ):
        cache = getattr(code, cache_name)
        if cache is not None:
            engine = getattr(cache, "engine", None)
            if engine is not None:
                engine.dispose()
        monkeypatch.setattr(code, cache_name, None)

    app.include_router(code_router)
    app.include_router(zoning_router)
    app.state.desktop_enabled_modules = frozenset({"civicrecords-ai", "civiccode", "civiczone"})

    syncurl = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("CIVICCODE_SOURCE_REGISTRY_DB_URL", syncurl)

    code_root = Path(code.__file__).parent
    _run_alembic(
        "Code",
        code_root / "migrations/alembic.ini",
        code_root / "migrations",
        syncurl,
    )
    zone_root = Path(civiczone.__file__).parent
    _run_alembic(
        "Zoning",
        zone_root / "migrations/alembic.ini",
        zone_root / "migrations",
        syncurl,
    )

    from civicsuite_runtime.code_meetings import ensure_schema

    schema_engine = create_engine(syncurl)
    try:
        ensure_schema(schema_engine)
    finally:
        schema_engine.dispose()

    code_payload = json.loads(
        (_sibling("ordinances") / "tests/fixtures/milestone_12/csv_bundle.json").read_text()
    )
    code_payload["titles"][0]["title_name"] = "Fictional Zoning"
    code_payload["chapters"][0]["chapter_name"] = "R2 district"
    code_payload["sections"][0]["section_heading"] = "Uses and dimensions"
    code_payload["versions"][0]["body"] = (
        "In fictional R2 and HIST, ADUs are allowed. The front setback is 20 feet. Other uses require planner review."
    )
    code_payload["versions"][0]["effective_end"] = "2026-12-31"
    future = dict(code_payload["versions"][0])
    future.update(
        version_id="z2-future",
        version_label="Future Zoning",
        effective_start="2027-01-01",
        effective_end=None,
        is_current=False,
        body="ADUs are conditional beginning 2027.",
    )
    code_payload["versions"].append(future)
    zoning_payload = json.loads((_sibling("zone") / "tests/fixtures/z1-town.json").read_text())
    zoning_payload["jurisdiction"] = "Z1-Connected-Acceptance"
    zoning_payload["actor_id"] = "forged-body-actor"

    missing = await api.post("/desktop/v1/zoning/imports", json=zoning_payload)
    assert missing.status_code == 401

    records_staff = await api.post(
        "/desktop/v1/zoning/imports",
        json=zoning_payload,
        headers={"X-Townlight-Session": original_proof},
    )
    assert records_staff.status_code == 403

    profile_root = app.state.desktop_profile_root
    config_dir = profile_root / "config"
    staff_path = config_dir / "staff-users.json"
    session_path = config_dir / "local-session.json"

    staff = json.loads(staff_path.read_text())
    staff[0]["role"] = "city-staff"
    staff_path.write_text(json.dumps(staff))

    expiry = 4102444800
    message = f"{staff[0]['email']}\ncity-staff\n{expiry}\n{staff[0]['passcode_hash']}"
    proof = hmac.new(bytes(range(32)), message.encode("utf-8"), hashlib.sha256).hexdigest()
    session = dict(staff[0])
    session["expires_at_unix_seconds"] = expiry
    session["session_hash"] = proof
    session_path.write_text(json.dumps(session))
    headers = {"X-Townlight-Session": proof}
    monkeypatch.setattr("app.auth.desktop_session.time.time", lambda: datetime.now().timestamp())

    code_resp = await api.post("/desktop/v1/code/imports", json=code_payload, headers=headers)
    assert code_resp.status_code == 200, code_resp.text
    code_receipt = code_resp.json()
    assert code_receipt["status"] == "completed"
    assert code_receipt["actor"] == str(actor_id)

    zone_resp = await api.post("/desktop/v1/zoning/imports", json=zoning_payload, headers=headers)
    assert zone_resp.status_code == 200, zone_resp.text

    db_engine = create_engine(syncurl)
    try:
        with db_engine.connect() as conn:
            actor_row = conn.execute(
                text(
                    "SELECT actor_id FROM civiczone.geo_imports WHERE jurisdiction = :jurisdiction"
                ),
                {"jurisdiction": "Z1-Connected-Acceptance"},
            ).scalar_one()
    finally:
        db_engine.dispose()
    assert str(actor_row) == str(actor_id)

    lookup = await api.post(
        "/desktop/v1/zoning/parcels/lookup",
        json={"jurisdiction": "Z1-Connected-Acceptance", "query": "P1"},
        headers=headers,
    )
    assert lookup.status_code == 200, lookup.text
    result = lookup.json()
    assert result["status"] == "ok"
    assert result["code_citation"]["status"] == "ok"
    assert result["code_citation"]["citation"]["source_id"] == "csv_active"
    assert result["source"]["content_sha256"] == zone_resp.json()["content_sha256"]
    for overlay in result.get("overlays", []):
        assert overlay["code_citation"]["status"] == "ok"
        assert overlay["code_citation"]["citation"]["source_id"] == "csv_active"

    qid = await _check_z2(api, headers, actor_id, app, syncurl, monkeypatch)
    await _check_z3(api, headers, actor_id, app, syncurl, qid)

    unknown = await api.post(
        "/desktop/v1/zoning/parcels/lookup",
        json={"jurisdiction": "Z1-Connected-Acceptance", "query": "100-200-300"},
        headers=headers,
    )
    assert unknown.status_code == 200
    assert unknown.json()["status"] == "not_found"

    extra = await api.post(
        "/desktop/v1/zoning/parcels/lookup",
        json={
            "jurisdiction": "Z1-Connected-Acceptance",
            "query": "P1",
            "actor": "forged-body-actor",
        },
        headers=headers,
    )
    assert extra.status_code == 422

    forged = await api.post(
        "/desktop/v1/zoning/parcels/lookup",
        json={"jurisdiction": "Z1-Connected-Acceptance", "query": "P1"},
        headers={"X-Townlight-Session": "forged"},
    )
    assert forged.status_code == 401

    app.state.desktop_enabled_modules = frozenset({"civicrecords-ai", "civiccode"})
    disabled = await api.post(
        "/desktop/v1/zoning/parcels/lookup",
        json={"jurisdiction": "Z1-Connected-Acceptance", "query": "P1"},
        headers=headers,
    )
    assert disabled.status_code == 403

    app.state.desktop_enabled_modules = frozenset({"civicrecords-ai", "civiccode", "civiczone"})
    app.state.desktop_domain_enabled = False
    inactive = await api.post(
        "/desktop/v1/zoning/parcels/lookup",
        json={"jurisdiction": "Z1-Connected-Acceptance", "query": "P1"},
        headers=headers,
    )
    assert inactive.status_code == 503


async def _check_z2(api, headers, actor_id, app, syncurl, monkeypatch):
    from civicsuite_runtime.zoning_bridge import public_router

    app.include_router(public_router)
    u = lambda p: p  # noqa: E731
    base = {
        "jurisdiction": "Z1-Connected-Acceptance",
        "zone_code": "R2",
        "kind": "use",
        "key": "ADU",
        "value": "allowed",
        "section_number": "6.12.040",
        "overlay_code": None,
    }
    r = await api.post(u("/desktop/v1/zoning/rules"), json=base)
    assert r.status_code == 401, r.text
    r = await api.post(u("/desktop/v1/zoning/rules"), json=base, headers=headers)
    assert r.status_code == 200, r.text
    q = {
        "jurisdiction": "Z1-Connected-Acceptance",
        "query": "P1",
        "question": "ADU informational lookup",
        "kind": "use",
        "key": "ADU",
    }
    r = await api.post(u("/desktop/v1/zoning/questions"), json=q, headers=headers)
    assert (
        r.status_code == 200 and "needs_planner" in r.text and "overlay_rule_unavailable" in r.text
    ), r.text
    overlay = dict(base, overlay_code="HIST")
    r = await api.post(u("/desktop/v1/zoning/rules"), json=overlay, headers=headers)
    assert r.status_code == 200, r.text
    r = await api.post(u("/desktop/v1/zoning/questions"), json=q, headers=headers)
    assert r.status_code == 200 and "answered" in r.text and "csv_active" in r.text, r.text
    qid = r.json()["id"]
    await _z2_rule_cases(api, headers, base, q)
    review = {"answer": "Human correction", "notes": "PRIVATE NOTE", "queue_status": "open"}
    r = await api.post(
        u(f"/desktop/v1/zoning/questions/{qid}/reviews"), json=review, headers=headers
    )
    assert r.status_code == 200, r.text
    ws = await api.get("/desktop/v1/zoning/workspace", headers=headers)
    assert ws.status_code == 200
    assert any(
        q.get("source_question_id") == qid and q.get("status") == "open" for q in ws.json()["queue"]
    )
    review2 = {
        "answer": "Second human correction",
        "notes": "PRIVATE NOTE 2",
        "queue_status": "closed",
    }
    r = await api.post(
        u(f"/desktop/v1/zoning/questions/{qid}/reviews"), json=review2, headers=headers
    )
    assert r.status_code == 200, r.text
    r = await api.get(u("/desktop/v1/zoning/workspace"))
    assert r.status_code == 401, r.text
    r = await api.get(u("/desktop/v1/zoning/workspace"), headers=headers)
    assert r.status_code == 200 and len(r.json().get("reviews", [])) >= 2, r.text
    r = await api.post(u("/civiczone/questions"), json=q)
    assert r.status_code == 200 and "PRIVATE NOTE" not in r.text, r.text
    r = await api.get(u("/civiczone/workspace"))
    assert r.status_code == 404, r.text
    r = await api.post(
        u("/desktop/v1/zoning/outlines"),
        json={"title": "Draft", "question_ids": [qid]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    snapshot = _z2_original(syncurl, qid, actor_id)
    monkeypatch.setattr("civicsuite_runtime.zoning_bridge.date", FutureDate)
    r = await api.post("/desktop/v1/zoning/questions", json=q, headers=headers)
    assert (
        r.status_code == 200
        and r.json()["status"] == "needs_planner"
        and r.json()["reason"] == "stale_code"
    )
    new_id = r.json()["id"]
    r2 = await api.post(
        f"/desktop/v1/zoning/questions/{new_id}/reviews",
        json={"answer": "", "notes": "", "queue_status": "closed"},
        headers=headers,
    )
    assert r2.status_code == 200
    engine = create_engine(syncurl)
    with engine.connect() as conn:
        orig = conn.execute(
            text("SELECT context FROM civiczone.zone_question_ledger_records WHERE id=:id"),
            {"id": qid},
        ).scalar()
        assert orig == snapshot
    engine.dispose()
    return qid


def _z2_original(syncurl, qid, actor_id):
    engine = create_engine(syncurl)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT context, actor_id FROM civiczone.zone_question_ledger_records WHERE id=:id"
                ),
                {"id": qid},
            ).one()
            original_context, stored_actor = row
            assert stored_actor == str(actor_id)
            assert original_context["answer"] == "allowed"
            cnt = conn.execute(
                text(
                    "SELECT COUNT(*) FROM civiczone.question_events WHERE question_id=:id AND event_type='human_correction'"
                ),
                {"id": qid},
            ).scalar()
            assert cnt == 2
        return original_context
    finally:
        engine.dispose()


class FutureDate(date):
    @classmethod
    def today(cls):
        return date(2027, 1, 1)


async def _check_z3(api, headers, actor_id, app, syncurl, qid):
    import json
    from civicclerk.meeting_lifecycle import MeetingStore
    from civicclerk.public_archive import PublicArchiveRepository
    from civicclerk.records_sources import public_documents as meeting_docs
    from civicsuite_runtime.zoning_records import public_documents as zoning_docs

    store = MeetingStore(db_url=syncurl)
    try:
        m = store.create(title="Fictional Z3 hearing", meeting_type="regular", actor=str(actor_id))
    finally:
        store.engine.dispose()
    repo = PublicArchiveRepository(db_url=syncurl)
    try:
        archive = repo.publish(
            meeting_id=m.id,
            title=m.title,
            visibility="public",
            posted_agenda="Fictional hearing",
            posted_packet="",
            approved_minutes="Fictional minutes, not an amendment",
            actor=str(actor_id),
        )
    finally:
        repo.engine.dispose()
    archive_id = archive.id
    modules = list(getattr(app.state, "desktop_enabled_modules", None) or [])
    if "civicclerk" not in modules:
        modules.append("civicclerk")
    app.state.desktop_enabled_modules = modules

    def provider(query="", source_id=None):
        return meeting_docs(syncurl, query=query, source_id=source_id)

    app.state.desktop_meetings_sources = provider
    app.state.desktop_zoning_sources = lambda query="", source_id=None: zoning_docs(
        syncurl, provider, query=query, source_id=source_id
    )
    r = await api.post(
        "/desktop/v1/zoning/meetings/search", json={"query": "Fictional"}, headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    items = body.get("results") or body.get("items") or body
    mi = next(i for i in items if "Fictional minutes" in json.dumps(i))
    source_id = mi["source_id"]
    expected_sha256 = mi.get("sha256") or mi.get("expected_sha256")
    r = await api.post(
        f"/desktop/v1/zoning/questions/{qid}/meetings",
        json={"source_id": source_id, "expected_sha256": expected_sha256, "relation": "precedent"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    event_id = r.json()["event_id"]
    r = await api.post(
        f"/desktop/v1/zoning/questions/{qid}/snapshots",
        json={"visibility": "public", "meeting_event_ids": [event_id]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    snapshot = r.json()
    text = snapshot["text"]
    assert archive_id in text
    assert "PRIVATE NOTE" not in text
    assert "informational" in json.dumps(snapshot).lower()
    r = await api.get(f"/desktop/v1/zoning/questions/{qid}/history", headers=headers)
    assert r.status_code == 200, r.text
    hist_items = r.json()["events"]
    assert any((archive_id in json.dumps(h)) or (event_id in json.dumps(h)) for h in hist_items)
    r = await api.post("/desktop/v1/zoning-sources/search", json={"query": qid}, headers=headers)
    assert r.status_code == 200, r.text
    sb = r.json()
    src_results = sb.get("results") or sb.get("items") or sb
    assert any(snapshot.get("source_id") == it.get("source_id") for it in src_results)
    await _z3_visibility(api, headers, app, syncurl, qid, snapshot)
    endpoint = await _z3_records(api, headers, app, qid, snapshot)
    await _z3_permissions(api, headers, app, syncurl, qid, snapshot, archive_id, endpoint)
    return snapshot, archive_id


async def _z2_rule_cases(api, headers, base, q):
    async def post(path, body):
        r = await api.post(path, headers=headers, json=body)
        assert r.status_code == 200, r.text
        return r.json()

    R = "/desktop/v1/zoning/rules"
    Q = "/desktop/v1/zoning/questions"
    hist = {**base, "overlay_code": "HIST"}
    for v in ("conditional", "prohibited"):
        await post(R, {**base, "value": v})
        await post(R, {**hist, "value": v})
        j = await post(Q, q)
        assert j["status"] == "answered", j
        assert j["answer"] == v, j
    await post(R, {**base, "value": "allowed"})
    await post(R, {**hist, "value": "prohibited"})
    j = await post(Q, q)
    assert j["status"] == "needs_planner", j
    assert j["reason"] == "conflicting_rules", j
    await post(R, {**base, "value": "allowed"})
    await post(R, {**hist, "value": "allowed"})
    b2 = {**base, "kind": "dimension", "key": "front_setback", "value": "20 feet"}
    await post(R, b2)
    await post(R, {**b2, "overlay_code": "HIST"})
    j = await post(Q, {**q, "kind": "dimension", "key": "front_setback"})
    assert j["status"] == "answered", j
    assert j["answer"] == "20 feet", j
    j = await post(
        "/desktop/v1/zoning/code-context", {"section_number": "6.12.040", "as_of": "2027-01-01"}
    )
    assert j["temporal_context"] == "future", j
    assert j["citation"]["citation"]["version_id"] == "z2-future", j


async def _z3_records(api, headers, app, qid, snapshot):
    r = await api.post(
        "/desktop/v1/requests",
        headers=headers,
        json={
            "requester": "SyntheticZ3",
            "summary": "Fictional zoning records",
            "deadline": "2026-11-01",
            "deadlineBasis": "Synthetic",
        },
    )
    assert r.status_code == 201, r.text
    endpoint = "/desktop/v1/requests/" + r.json()["id"]
    attach = endpoint + "/zoning-sources"
    selection = {"source_id": snapshot["source_id"], "expected_sha256": snapshot["sha256"]}
    r = await api.post(attach, headers=headers, json={**selection, "expected_sha256": "0" * 64})
    assert r.status_code == 409, r.text
    r = await api.post(attach, headers=headers, json=selection)
    assert r.status_code == 200, r.text
    request = r.json()["request"]
    assert request["approved_at_unix_seconds"] is None
    duplicate = await api.post(attach, headers=headers, json=selection)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["request"] == request
    documents = duplicate.json()["request"]["documents"]
    assert len(documents) == 1
    document = documents[0]
    assert document["sha256"] == snapshot["sha256"]
    data = Path(document["stored_path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == snapshot["sha256"]
    r = await api.post(
        endpoint + "/actions",
        headers=headers,
        json={
            "action": "draft-records-response",
            "payload": {
                "responseDraft": "Zoning source evidence supplied for review.",
                "citation": snapshot["citation"],
            },
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["request"]["approved_at_unix_seconds"] is None
    r = await api.post(endpoint + "/artifacts", headers=headers, json={"kind": "response"})
    assert r.status_code == 400, r.text
    r = await api.post(
        endpoint + "/actions",
        headers=headers,
        json={
            "action": "approve-records-response",
            "payload": {"approvalNote": "Explicit human C3 approval"},
        },
    )
    assert r.status_code == 200, r.text
    approval = r.json()["request"]["approved_at_unix_seconds"]
    r = await api.post(attach, headers=headers, json=selection)
    assert r.status_code == 200, r.text
    assert r.json()["request"]["approved_at_unix_seconds"] == approval
    r = await api.post(endpoint + "/artifacts", headers=headers, json={"kind": "response"})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert snapshot["citation"] in plan["content"]
    assert hashlib.sha256(plan["content"].encode()).hexdigest() == plan["sha256"]
    return endpoint


async def _z3_visibility(api, headers, app, syncurl, qid, snapshot):
    import json
    from sqlalchemy import create_engine
    from civiccode.source_registry import source_registry_records as sourcetable

    original_text = snapshot.get("text")
    original_hash = snapshot.get("sha256") or snapshot.get("expected_sha256")
    r = await api.post(
        "/desktop/v1/zoning/meetings/search", json={"query": "Fictional"}, headers={}
    )
    assert r.status_code == 401, r.text
    r = await api.get(f"/civiczone/questions/{qid}/history", headers={})
    assert r.status_code == 404, r.text
    r = await api.post(
        f"/desktop/v1/zoning/questions/{qid}/snapshots",
        json={"visibility": "staff_only", "meeting_event_ids": []},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    staff_source_id = r.json()["source_id"]
    r = await api.post("/desktop/v1/zoning-sources/search", json={"query": qid}, headers=headers)
    assert r.status_code == 200, r.text
    sb = r.json()
    src_results = sb.get("results") or sb.get("items") or (sb if isinstance(sb, list) else [])
    assert all(it.get("source_id") != staff_source_id for it in src_results)
    r = await api.post(
        f"/desktop/v1/zoning/questions/{qid}/reviews",
        json={
            "answer": "Human revised interpretation",
            "notes": "PRIVATE Z3 NOTE",
            "queue_status": "closed",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    r = await api.post(
        f"/desktop/v1/zoning/questions/{qid}/snapshots",
        json={"visibility": "public", "meeting_event_ids": []},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    new_snapshot = r.json()
    dumped = json.dumps(new_snapshot)
    assert "Human revised interpretation" in dumped and "PRIVATE Z3 NOTE" not in dumped
    assert snapshot.get("text") == original_text
    assert (snapshot.get("sha256") or snapshot.get("expected_sha256")) == original_hash
    engine = create_engine(syncurl)
    try:
        with engine.begin() as conn:
            conn.execute(
                sourcetable.update()
                .where(sourcetable.c.source_id == "csv_active")
                .values(is_official=False)
            )
        r = await api.post(
            "/desktop/v1/zoning-sources/search", json={"query": qid}, headers=headers
        )
        assert r.status_code == 200, r.text
        sb = r.json()
        sr = sb.get("results") or sb.get("items") or (sb if isinstance(sb, list) else [])
        assert sr == []
    finally:
        with engine.begin() as conn:
            conn.execute(
                sourcetable.update()
                .where(sourcetable.c.source_id == "csv_active")
                .values(is_official=True)
            )
        engine.dispose()


async def _z3_permissions(api, headers, app, syncurl, qid, snapshot, archive_id, endpoint):
    engine = create_engine(syncurl)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE civicclerk.public_meeting_records SET visibility='closed_session' WHERE id=:id"
                ),
                {"id": archive_id},
            )
        r = await api.post(
            "/desktop/v1/zoning-sources/search", json={"query": qid}, headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        results = body["results"]
        assert snapshot["source_id"] not in {it.get("source_id") for it in results}
        r = await api.post(
            endpoint + "/zoning-sources",
            headers=headers,
            json={"source_id": snapshot["source_id"], "expected_sha256": snapshot["sha256"]},
        )
        assert r.status_code == 404, r.text
        r = await api.get("/desktop/v1/zoning/questions/" + qid + "/history", headers=headers)
        assert r.status_code == 200, r.text
        assert "Fictional minutes, not an amendment" not in r.text
        with engine.connect() as conn:
            payload = conn.execute(
                text("SELECT payload FROM civiczone.question_events WHERE id=:id"),
                {"id": snapshot["version"]},
            ).scalar_one()
        assert payload["text"] == snapshot["text"]
        assert payload["sha256"] == snapshot["sha256"]
    finally:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE civicclerk.public_meeting_records SET visibility='public' WHERE id=:id"
                    ),
                    {"id": archive_id},
                )
        finally:
            engine.dispose()
