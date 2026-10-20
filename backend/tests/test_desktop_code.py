"""Code integration using the existing native identity and PostgreSQL fixtures."""

import pytest

from tests.test_desktop_records import native_api, native_profile  # noqa: F401


async def check_code_source_boundary(runtime, headers, endpoint, source):
    import sqlalchemy as sa
    from tests.conftest import TEST_DATABASE_URL
    from civiccode.source_registry import source_registry_records as table

    engine = sa.create_engine(TEST_DATABASE_URL.replace('+asyncpg', '+psycopg2'))
    try:
        with engine.connect() as conn:
            original = conn.execute(sa.select(table).where(table.c.source_id == 'csv_active')).mappings().one()
        for values in ({'source_category': 'internal_staff_notes'}, {'is_official': False}, {'status': 'stale'}):
            with engine.begin() as conn:
                conn.execute(table.update().where(table.c.source_id == 'csv_active').values(**values))
            try:
                r = await runtime.post('/desktop/v1/code-sources/search', headers=headers, json={'query': '6.12.040'})
                assert r.status_code == 200, r.text
                assert r.json()['results'] == []
                r = await runtime.post(endpoint + '/code-sources', headers=headers, json={
                    'source_id': source['source_id'], 'expected_sha256': source['sha256'], 'as_of': source['as_of'],
                })
                assert r.status_code == 404, r.text
            finally:
                with engine.begin() as conn:
                    conn.execute(table.update().where(table.c.source_id == 'csv_active').values(**{k: original[k] for k in values}))
        with engine.begin() as conn:
            conn.execute(table.update().where(table.c.source_id == 'csv_active').values(name='Changed synthetic provenance'))
        try:
            r = await runtime.post(endpoint + '/code-sources', headers=headers, json={
                'source_id': source['source_id'], 'expected_sha256': source['sha256'], 'as_of': source['as_of'],
            })
            assert r.status_code == 409, r.text
        finally:
            with engine.begin() as conn:
                conn.execute(table.update().where(table.c.source_id == 'csv_active').values(name=original['name']))
    finally:
        engine.dispose()


async def code_records_journey(runtime, headers, profile_root):
    import hashlib, json
    from pathlib import Path

    search = '/desktop/v1/code-sources/search'
    r = await runtime.post(search, json={'query': '6.12.040'})
    assert r.status_code == 401, r.text
    items = []
    for asof in (None, '2025-06-01'):
        r = await runtime.post(search, headers=headers, json={'query': '6.12.040', 'as_of': asof})
        assert r.status_code == 200, r.text
        s = r.json()['results'][0]
        assert s['as_of'] == asof
        assert s['version'] == ('version_6_12_040_historic' if asof else 'version_6_12_040_current')
        assert 'PRIVATE INTERPRETATION C1' not in r.text
        items.append(s)
    r = await runtime.post('/desktop/v1/requests', headers=headers, json={
        'requester': 'SyntheticC3', 'summary': 'Council and code',
        'deadline': '2026-11-01', 'deadlineBasis': 'Synthetic',
    })
    assert r.status_code == 201, r.text
    endpoint = '/desktop/v1/requests/' + r.json()['id']
    for s in items:
        selection = {'source_id': s['source_id'], 'expected_sha256': s['sha256'], 'as_of': s['as_of']}
        attach = endpoint + '/code-sources'
        r = await runtime.post(attach, headers=headers, json=dict(selection, expected_sha256='0' * 64))
        assert r.status_code == 409, r.text
        r = await runtime.post(attach, headers=headers, json=selection)
        assert r.status_code == 200, r.text
        assert r.json()['request']['approved_at_unix_seconds'] is None
        duplicate = await runtime.post(attach, headers=headers, json=selection)
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()['request'] == r.json()['request']
        document = next(d for d in r.json()['request']['documents'] if d['sha256'] == s['sha256'])
        data = Path(document['stored_path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == s['sha256']
        export = json.loads(data)
        assert export['version']['version_id'] == s['version']
        assert export['citation']['as_of'] == s['as_of']
    await check_code_source_boundary(runtime, headers, endpoint, items[0])
    meeting = await runtime.post("/desktop/v1/meetings/meetings", json={
        "title":"C3 Council", "scheduled_start":"2026-10-20T18:00:00-06:00", "location":"Synthetic",
    }, headers=headers)
    assert meeting.status_code == 201, meeting.text
    mid = meeting.json()["id"]
    uncited = await runtime.post(f"/desktop/v1/meetings/meetings/{mid}/minutes/drafts",
        json={"sentences":[{"text":"Synthetic C3 ordinance discussion."}]}, headers=headers)
    assert uncited.status_code == 201, uncited.text
    archive_data = {"minutes_id":uncited.json()["id"], "plain_language_summary":"Synthetic <script>danger</script> archive."}
    archive = await runtime.post(f"/desktop/v1/meetings/meetings/{mid}/archive",
        json={**archive_data,"visibility":"public"}, headers=headers)
    assert archive.status_code == 201, archive.text
    public_url = "/public/meetings/" + archive.json()["id"]
    public = await runtime.get(public_url)
    assert public.status_code == 200 and "<script>danger</script>" not in public.text and "Draft minutes" in public.text
    download = await runtime.get(public_url + "/minutes.txt")
    assert download.status_code == 200 and download.text.startswith("Draft minutes")
    restricted = await runtime.post(f"/desktop/v1/meetings/meetings/{mid}/archive",
        json={**archive_data,"visibility":"closed_session"}, headers=headers)
    assert restricted.status_code == 201, restricted.text
    assert (await runtime.get("/public/meetings/" + restricted.json()["id"])).status_code == 404
    assert (await runtime.get("/public/meetings/" + restricted.json()["id"] + "/minutes.txt")).status_code == 404
    search_path = "/desktop/v1/meetings-sources/search"
    assert (await runtime.post(search_path, json={"query":"Synthetic C3 ordinance"})).status_code == 401
    found = await runtime.post(search_path, json={"query":"Synthetic C3 ordinance"}, headers=headers)
    assert found.status_code == 200, found.text
    source = next(s for s in found.json()["results"] if s["archive_id"] == archive.json()["id"])
    assert all(s["archive_id"] != restricted.json()["id"] for s in found.json()["results"])
    selection = {"source_id":source["source_id"],"expected_sha256":source["sha256"]}
    attach_path = endpoint + "/meetings-sources"
    assert (await runtime.post(attach_path, json={**selection,"expected_sha256":"0"*64}, headers=headers)).status_code == 409
    linked = await runtime.post(attach_path, json=selection, headers=headers)
    assert linked.status_code == 200, linked.text
    items.append(source)
    r = await runtime.post(endpoint + '/actions', headers=headers, json={'action': 'draft-records-response', 'payload': {
        'responseDraft': 'Meeting and historic/current code evidence supplied for review.',
        'citation': ' | '.join(s['citation'] for s in items)}})
    assert r.status_code == 200, r.text
    assert r.json()['request']['approved_at_unix_seconds'] is None
    r = await runtime.post(endpoint + '/artifacts', headers=headers, json={'kind': 'response'})
    assert r.status_code == 400, r.text
    r = await runtime.post(endpoint + '/actions', headers=headers, json={'action': 'approve-records-response', 'payload': {'approvalNote': 'Explicit human C3 approval'}})
    assert r.status_code == 200, r.text
    approval = r.json()['request']['approved_at_unix_seconds']
    r = await runtime.post(endpoint + '/code-sources', headers=headers, json={
        'source_id': items[0]['source_id'], 'expected_sha256': items[0]['sha256'], 'as_of': items[0]['as_of']})
    assert r.status_code == 200, r.text
    assert r.json()['request']['approved_at_unix_seconds'] == approval
    r = await runtime.post(endpoint + '/artifacts', headers=headers, json={'kind': 'response'})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert all(s['citation'] in plan['content'] for s in items)
    assert hashlib.sha256(plan['content'].encode()).hexdigest() == plan['sha256']
    from tests.test_desktop_records_artifacts import write_test_export
    from types import SimpleNamespace
    path = write_test_export(SimpleNamespace(state=SimpleNamespace(desktop_profile_root=profile_root)), plan)
    r = await runtime.post(endpoint + '/artifacts/' + plan['artifact_id'] + '/complete',
        headers=headers, json={'export_path': str(path)})
    assert r.status_code == 200, r.text
    assert len(r.json()['request']['documents']) == 3
    assert hashlib.sha256(path.read_bytes()).hexdigest() == plan['sha256']
    return endpoint, items


@pytest.mark.asyncio
async def test_code_native_postgres_import(native_api, monkeypatch, tmp_path):
    api, proof, actor_id, app = native_api

    from civicsuite_runtime.code_bridge import router

    app.include_router(router)
    app.state.desktop_enabled_modules = frozenset({"civicrecords-ai", "civiccode"})

    response = await api.get(
        "/desktop/v1/code/workspace", headers={"X-Townlight-Session": proof},
    )
    assert response.status_code == 403

    from pathlib import Path
    import civiccode.main as code
    from tests.conftest import TEST_DATABASE_URL
    from civicsuite_runtime.migrate import _run_alembic

    root = Path(code.__file__).parent
    url = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("CIVICCODE_SOURCE_REGISTRY_DB_URL", url)
    _run_alembic("Code", root / "migrations/alembic.ini", root / "migrations", url)
    from civicsuite_runtime.code_meetings import ensure_schema
    import sqlalchemy as sa
    schema_engine = sa.create_engine(url)
    try:
        ensure_schema(schema_engine)
    finally:
        schema_engine.dispose()

    import json
    import hmac
    import hashlib

    profile_root = app.state.desktop_profile_root
    config_dir = profile_root / "config"
    staff_path = config_dir / "staff-users.json"
    session_path = config_dir / "local-session.json"
    with staff_path.open("r", encoding="utf-8") as f:
        staff = json.load(f)
    staff[0]["role"] = "code-staff"
    with staff_path.open("w", encoding="utf-8") as f:
        json.dump(staff, f)
    expiry = 4102444800
    message = f"{staff[0]['email']}\ncode-staff\n{expiry}\n{staff[0]['passcode_hash']}"
    token = hmac.new(bytes(range(32)), message.encode("utf-8"), hashlib.sha256).hexdigest()
    session = dict(staff[0])
    session["expires_at_unix_seconds"] = expiry
    session["session_hash"] = token
    with session_path.open("w", encoding="utf-8") as f:
        json.dump(session, f)
    headers = {"X-Townlight-Session": token}

    payload = json.loads((root.parent / "tests/fixtures/milestone_12/csv_bundle.json").read_text())
    old = {
        **payload["versions"][0],
        "version_id": "version_6_12_040_historic",
        "version_label": "Synthetic 2025",
        "body": "Synthetic historical limit: four backyard chickens.",
        "effective_start": "2025-01-01",
        "effective_end": "2025-12-31",
        "is_current": False,
    }
    payload["versions"].append(old)
    resp = await api.post("/desktop/v1/code/imports", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["actor"] == str(actor_id)

    resp = await api.get("/desktop/v1/code/lookup", params={"section_number": "6.12.040"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert "six backyard chickens" in resp.text

    lookup_resp = await api.get(
        "/desktop/v1/code/lookup",
        params={"section_number": "6.12.040", "as_of": "2025-06-01"}, headers=headers,
    )
    assert lookup_resp.status_code == 200
    data = lookup_resp.json()
    assert data["version"]["version_id"] == old["version_id"]
    assert "four" in data["version"]["body"].lower()

    resp = await api.get("/desktop/v1/code/citation", params={"section_number": "6.12.040"}, headers=headers)
    assert resp.status_code == 200, resp.text
    citation = resp.json()
    assert citation["status"] == "ok"
    assert citation["citation"]["source_id"] == "csv_active"
    assert "6.12.040" in citation["citation"]["citation_text"]

    resp = await api.get("/desktop/v1/code/sections/sec_6_12_040/history", headers=headers)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["versions"]) == 2

    resp = await api.get("/desktop/v1/code/imports/import_csv_animals/tree", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["titles"][0]["title_name"] == "Animals"

    from civicsuite_runtime.code_public import router as public_router
    app.include_router(public_router)
    private_note = "PRIVATE INTERPRETATION C1"
    resp = await api.post(
        "/desktop/v1/code/sections/sec_6_12_040/notes",
        json={"note_text": private_note}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    for path in ("/civiccode/sections/6.12.040", "/civiccode/sections/6.12.040/export"):
        resp = await api.get(path)
        assert resp.status_code == 200, resp.text
        assert "six backyard chickens" in resp.text
        assert private_note not in resp.text
    resp = await api.get("/civiccode/search", params={"q": private_note})
    assert resp.status_code == 200
    assert "No matching code sections yet." in resp.text
    resp = await api.get(
        "/desktop/v1/code/citation", params={"section_number": "99.99"}, headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "refused"

    import os, socket, subprocess, sys, asyncio, httpx, time

    _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bind_port = 15480 if os.environ.get("TOWNLIGHT_TEST_NATIVE_CODE_TRANSPORT") == "1" else 0
    _s.bind(("127.0.0.1", bind_port))
    port = _s.getsockname()[1]
    _s.close()
    environment = {
        **os.environ,
        "DATABASE_URL": TEST_DATABASE_URL,
        "TOWNLIGHT_PRODUCT_PROFILE": "city-core",
        "TOWNLIGHT_PROFILE_ROOT": str(profile_root),
        "TESTING": "1",
        "JWT_SECRET": "a" * 64,
    }
    command = [
        sys.executable, "-m", "uvicorn", "tests.test_desktop_records:isolated_runtime_app",
        "--factory", "--host", "127.0.0.1", "--port", str(port),
        "--no-access-log", "--log-level", "warning",
    ]
    import civicclerk
    _run_alembic("Meetings", Path(civicclerk.__file__).parent / "migrations/alembic.ini",
                 Path(civicclerk.__file__).parent / "migrations", url)
    staff[0]["role"] = "city-staff"
    staff_path.write_text(json.dumps(staff))
    message = f"{staff[0]['email']}\ncity-staff\n{expiry}\n{staff[0]['passcode_hash']}"
    token = hmac.new(bytes(range(32)), message.encode(), hashlib.sha256).hexdigest()
    session_path.write_text(json.dumps({**staff[0], "expires_at_unix_seconds": expiry, "session_hash": token}))
    headers = {"X-Townlight-Session": token}
    from civicsuite_runtime.records_import_store import metadata as import_metadata
    fixture_engine = sa.create_engine(url)
    try:
        import_metadata.create_all(fixture_engine)
    finally:
        fixture_engine.dispose()
    for iteration in range(2):
        with open(tmp_path / f"code-runtime-{iteration}.log", "w") as log:
            process = subprocess.Popen(
                command, env=environment, stdout=log, stderr=log,
                cwd=Path(__file__).resolve().parents[1],
            )
            try:
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=5) as runtime:
                    deadline = time.monotonic() + 20
                    while True:
                        assert process.poll() is None, "inspect code-runtime log"
                        try:
                            response = await runtime.get('/desktop/v1/code/workspace', timeout=1)
                            if response.status_code == 401:
                                break
                        except (httpx.ConnectError, httpx.TimeoutException):
                            pass
                        assert time.monotonic() < deadline
                        await asyncio.sleep(0.25)
                    history = await runtime.get(
                        "/desktop/v1/code/sections/sec_6_12_040/history", headers=headers,
                    )
                    assert history.status_code == 200, history.text
                    assert len(history.json()["versions"]) == 2
                    citation = await runtime.get(
                        "/desktop/v1/code/citation", params={"section_number": "6.12.040"}, headers=headers,
                    )
                    assert citation.status_code == 200
                    current = (history.json(), citation.json())
                    if iteration == 0:
                        saved = current
                        c3_endpoint, c3_sources = await code_records_journey(runtime, headers, profile_root)
                        c3_view = (await runtime.get(c3_endpoint + "/view", headers=headers)).json()
                    else:
                        assert current == saved
                        c3_readback = await runtime.get(c3_endpoint + "/view", headers=headers)
                        assert c3_readback.status_code == 200, c3_readback.text
                        assert c3_readback.json() == c3_view
                    if iteration == 0 and os.environ.get("TOWNLIGHT_TEST_NATIVE_CODE_TRANSPORT") == "1":
                        import civicsuite_runtime.services as _civicsuite_services
                        nativebundle = dict(payload, job_id="import_native_code_c1")
                        bundlepath = tmp_path / "native-code.json"
                        bundlepath.write_text(json.dumps(nativebundle), encoding="utf-8")
                        nativeenv = {
                            **environment, "TOWNLIGHT_TEST_SESSION_PROOF": token,
                            "TOWNLIGHT_TEST_CODE_BUNDLE": str(bundlepath),
                        }
                        desktoppath = Path(_civicsuite_services.__file__).resolve().parents[3]
                        result = subprocess.run(
                            ["cargo", "test", "--offline", "--manifest-path", "src-tauri/Cargo.toml",
                             "-j", "1", "native_code_roundtrip_with_real_runtime", "--", "--ignored", "--nocapture"],
                            cwd=str(desktoppath), env=nativeenv, capture_output=True, text=True, timeout=180,
                        )
                        assert result.returncode == 0, result.stdout + result.stderr
            finally:
                process.terminate()
                process.wait(timeout=10)

    monkeypatch.delenv("CIVICCODE_AI_MODE", raising=False)
    monkeypatch.delenv("CIVICCODE_OLLAMA_URL", raising=False)
    question = "What does section 6.12.040 say?"
    section_number = "6.12.040"
    response = await api.post(
        "/desktop/v1/code/questions",
        json={"question": question, "section_number": section_number},
        headers=headers,
    )
    assert response.status_code == 200
    answer_payload = response.json()
    assert answer_payload["status"] == "ok"
    assert answer_payload["classification"] == "information_not_determination"
    assert "not a legal determination" in answer_payload["answer"]

    export_response = await api.get(
        "/desktop/v1/code/export",
        params={"section_ref": section_number},
        headers=headers,
    )
    assert export_response.status_code == 200
    assert "PRIVATE INTERPRETATION C1" not in export_response.text

    code.SECTION_STORE.create_version(code.SectionVersionCreate.model_validate({
        **old, "version_id": "overlap_c1", "body": "Conflicting synthetic text."
    }).model_dump())
    from civicsuite_runtime.code_records import public_documents
    assert public_documents(url, query='6.12.040', as_of='2025-06-01') == []
    refused_response = await api.post(
        "/desktop/v1/code/questions",
        json={"question": question, "section_number": section_number, "as_of": "2025-06-01"},
        headers=headers,
    )
    assert refused_response.status_code == 200
    assert refused_response.json()["status"] == "refused"

    answer_response = await api.get(
        "/civiccode/answer",
        params={"q": question, "section_number": section_number, "as_of": "2025-06-01"},
    )
    assert answer_response.status_code == 200
    assert "four backyard chickens" not in answer_response.text
    assert "Conflicting synthetic text." not in answer_response.text

    # C2 uses the same real database/native actor, not an in-memory sender.
    import civicclerk
    from civicsuite_runtime.code_meetings_bridge import code_router, meetings_router
    from civicsuite_runtime.meetings_bridge import router as clerk_router
    _run_alembic("Meetings", Path(civicclerk.__file__).parent / "migrations/alembic.ini",
                 Path(civicclerk.__file__).parent / "migrations", url)
    for paired_router in (code_router, meetings_router, clerk_router):
        app.include_router(paired_router)
    app.state.desktop_enabled_modules = frozenset({"civicrecords-ai", "civiccode", "civicclerk"})
    staff[0]["role"] = "city-staff"
    staff_path.write_text(json.dumps(staff))
    message = f"{staff[0]['email']}\n{staff[0]['role']}\n{expiry}\n{staff[0]['passcode_hash']}"
    token = hmac.new(bytes(range(32)), message.encode(), hashlib.sha256).hexdigest()
    session_path.write_text(json.dumps({**staff[0], "expires_at_unix_seconds": expiry, "session_hash": token}))
    headers = {"X-Townlight-Session": token}
    r = await api.post("/desktop/v1/meetings/meetings", headers=headers, json={
        "title": "Synthetic C2 Council", "scheduled_start": "2026-10-20T18:00:00-06:00", "location": "Synthetic",
    })
    assert r.status_code == 201, r.text
    proposal = {"id": "c2-test", "version_id": "version_6_12_040_current", "meeting_id": r.json()["id"],
                "title": "Synthetic amendment", "ordinance_number": "SYN-C2", "proposed_text": "Synthetic eight chickens."}
    r = await api.post("/desktop/v1/code/connections", headers=headers, json=proposal)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["proposal"]["actor"] == str(actor_id)
    replay = await api.post("/desktop/v1/code/connections", headers=headers, json=proposal)
    assert replay.status_code == 200 and replay.json() == body
    changed = await api.post("/desktop/v1/code/connections", headers=headers, json={**proposal, "proposed_text": "Changed"})
    assert changed.status_code == 409, changed.text
    agenda = await api.get(f"/desktop/v1/meetings/agenda-items/{body['proposal']['agenda_item_id']}", headers=headers)
    assert agenda.status_code == 200, agenda.text
    decision = {"id": "d1", "outcome": "adopted", "decision_text": "Explicit synthetic human decision", "supporting_references": []}
    path = "/desktop/v1/meetings/code-connections/c2-test/decisions"
    r = await api.post(path, headers=headers, json=decision)
    assert r.status_code == 200, r.text
    decision_body = r.json()
    assert decision_body["decisions"][0]["supporting_evidence_status"] == "not_provided"
    replay = await api.post(path, headers=headers, json=decision)
    assert replay.status_code == 200 and replay.json() == decision_body
    closeout = {"decision_id": "d1", "version_id": "c2_test_final", "source_id": "csv_active",
                "version_label": "C2 synthetic", "body": proposal["proposed_text"],
                "effective_start": "2026-11-01", "is_current": False}
    path = "/desktop/v1/code/connections/c2-test/closeout"
    r = await api.post(path, headers=headers, json=closeout)
    assert r.status_code == 200, r.text
    replay = await api.post(path, headers=headers, json=closeout)
    assert replay.status_code == 200 and replay.json() == r.json()
    history = await api.get("/desktop/v1/code/sections/sec_6_12_040/history", headers=headers)
    assert history.status_code == 200
    version_ids = {v["version_id"] for v in history.json()["versions"]}
    assert {"c2_test_final", "version_6_12_040_current"} <= version_ids
