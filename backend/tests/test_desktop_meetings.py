"""Meetings integration through the existing native identity and actual PostgreSQL.

Reuses the Records fixture database; never points at an owner profile. The
subprocess portion proves API restart, not an installed/WebView journey.
"""
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys

import httpx
import pytest
import sqlalchemy as sa

from tests.conftest import TEST_DATABASE_URL
from tests.test_desktop_records import native_api as native_api, native_profile as native_profile  # noqa: F401


@pytest.mark.parametrize("product_profile", ["meetings-beta", "city-core"])
@pytest.mark.asyncio
async def test_meetings_native_postgres_actor_permissions_and_process_restart(native_api, monkeypatch, tmp_path, product_profile):
    from civicclerk.meeting_lifecycle import MeetingStore
    from civicclerk.agenda_lifecycle import AgendaItemRepository
    from civicclerk.minutes import MinutesDraftRepository
    from civicclerk.packet_assembly import PacketAssemblyRepository
    from civicclerk.notice_checklist import NoticeChecklistRepository
    from civicclerk.transcripts import TranscriptRepository
    from civicclerk.public_archive import PublicArchiveRepository
    from civicclerk.motion_vote import MotionVoteRepository
    from civicclerk.packet_notice import PacketStore
    from civicsuite_runtime.meetings_bridge import router
    api, proof, actor_id, app = native_api
    url = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")
    for repository in (MeetingStore(db_url=url), AgendaItemRepository(db_url=url),
            MinutesDraftRepository(db_url=url), PacketAssemblyRepository(db_url=url),
            NoticeChecklistRepository(db_url=url),TranscriptRepository(db_url=url),PublicArchiveRepository(db_url=url),
            MotionVoteRepository(db_url=url),PacketStore(db_url=url)):
        repository.engine.dispose()
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    app.include_router(router)
    app.state.desktop_enabled_modules = frozenset({"civicrecords-ai", "civicclerk"})
    meeting_path = "/desktop/v1/meetings/meetings"
    agenda_path = "/desktop/v1/meetings/agenda-items"
    meeting = {"title": "Redstone Council", "scheduled_start": "2026-10-20T18:00:00-06:00", "location": "Synthetic town hall"}
    agenda = {"title": "Trail report", "department_name": "Public Works"}
    assert (await api.post(meeting_path, json=meeting)).status_code == 401
    assert (await api.post(meeting_path, json=meeting, headers={"X-Townlight-Session": proof})).status_code == 403
    root = app.state.desktop_profile_root
    staff_path = root / "config/staff-users.json"
    staff = json.loads(staff_path.read_text())
    staff[0]["role"] = "clerk"
    staff_path.write_text(json.dumps(staff))
    expiry = 4102444800  # synthetic fixture, valid in subprocess without time patch
    message = f"{staff[0]['email']}\nclerk\n{expiry}\n{staff[0]['passcode_hash']}"
    proof = hmac.new(bytes(range(32)), message.encode(), hashlib.sha256).hexdigest()
    (root / "config/local-session.json").write_text(json.dumps({
        **staff[0], "expires_at_unix_seconds": expiry, "session_hash": proof,
    }))
    headers = {"X-Townlight-Session": proof}
    def use_role(role):
        staff[0]["role"]=role
        staff_path.write_text(json.dumps(staff))
        message=f"{staff[0]['email']}\n{role}\n{expiry}\n{staff[0]['passcode_hash']}"
        token=hmac.new(bytes(range(32)),message.encode(),hashlib.sha256).hexdigest()
        (root/"config/local-session.json").write_text(json.dumps({**staff[0],
            "expires_at_unix_seconds":expiry,"session_hash":token}))
        return {"X-Townlight-Session":token}
    assert (await api.post(meeting_path, json={**meeting, "actor": "forged"}, headers=headers)).status_code == 422

    # Actual runtime host, explicit synthetic activation, two distinct processes.
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    paths = [entry for entry in sys.path if entry]
    script = (
        f"import sys; sys.path[:0]={paths!r}; "
        "from civicsuite_runtime.services import create_runtime_app; import uvicorn; "
        f"uvicorn.run(create_runtime_app(domain_enabled=True),host='127.0.0.1',port={port},access_log=False,log_level='warning')"
    )
    environment = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL,
                   "TOWNLIGHT_PRODUCT_PROFILE": product_profile, "TOWNLIGHT_PROFILE_ROOT": str(root),
                   "TESTING": "1", "JWT_SECRET": "a" * 64}
    saved = []
    with (tmp_path / "meetings-runtime.log").open("w") as log:
        for iteration in range(2):
            process = subprocess.Popen([sys.executable, "-c", script], env=environment, stdout=log, stderr=log)
            try:
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10) as runtime:
                    import asyncio
                    for _ in range(80):
                        assert process.poll() is None, "Runtime exited; inspect meetings-runtime.log"
                        try:
                            response = await runtime.get(meeting_path + "/00000000-0000-0000-0000-000000000000")
                            if response.status_code == 401:
                                break
                        except httpx.ConnectError:
                            pass
                        await asyncio.sleep(.25)
                    else:
                        pytest.fail("Runtime did not become reachable")
                    if iteration == 0:
                        for endpoint, data in ((meeting_path, meeting), (agenda_path, agenda)):
                            response = await runtime.post(endpoint, json=data, headers=headers)
                            assert response.status_code == 201, response.text
                            body = response.json()
                            assert body["audit_entries"][0]["actor"] == str(actor_id)
                            saved.append((endpoint + "/" + body["id"], body))
                        endpoint = saved[0][0]
                        initial_history = saved[0][1]["audit_entries"]
                        for stage in ("IN_PROGRESS","RECESSED","IN_PROGRESS","CANCELLED"):
                            stage_result = await runtime.post(endpoint + "/stages",json={"to_status":stage},headers=headers)
                            assert stage_result.status_code == 200, stage_result.text
                            assert stage_result.json()["status"] == stage
                            assert stage_result.json()["audit_entries"][:len(initial_history)] == initial_history
                        assert stage_result.json()["audit_entries"][-1]["workflow_warning"]
                        saved[0] = (endpoint,stage_result.json())
                        agenda_endpoint = saved[1][0]
                        assignment = {"meeting_id": saved[0][1]["id"]}
                        placement = await runtime.post(agenda_endpoint + "/meeting", json=assignment, headers=headers)
                        assert placement.status_code == 200, placement.text
                        assert placement.json()["audit_entries"][-1]["workflow_warning"]
                        for status in ("SUBMITTED", "DEPT_APPROVED", "LEGAL_REVIEWED", "CLERK_ACCEPTED"):
                            response = await runtime.post(agenda_endpoint + "/reviews", json={"to_status":status}, headers=headers)
                            assert response.status_code == 200, response.text
                        response = await runtime.post(agenda_endpoint + "/meeting", json=assignment, headers=headers)
                        assert response.status_code == 200, response.text
                        assert response.json()["meeting_id"] == assignment["meeting_id"]
                        saved[1] = (agenda_endpoint, response.json())
                        managed = root / "Data/files/meetings/staged/source.txt"
                        managed.parent.mkdir(parents=True,exist_ok=True)
                        managed.write_bytes(b"Synthetic packet source document.")
                        source_receipt = {"original_path":"synthetic.txt","stored_path":str(managed),
                            "file_name":"source.txt","sha256":hashlib.sha256(managed.read_bytes()).hexdigest(),
                            "size_bytes":managed.stat().st_size}
                        for ids in ([saved[1][1]["id"]], []):
                            packet = await runtime.post(endpoint + "/packet-snapshots", json={"agenda_item_ids": ids,"source_files":[source_receipt]}, headers=headers)
                            assert packet.status_code == 201, packet.text
                            assert packet.json()["agenda_item_ids"] == ids
                            assert packet.json()["actor"] == str(actor_id)
                        delivery_path = "/desktop/v1/meetings/packets/" + packet.json()["packet_id"] + "/deliver"
                        delivered = await runtime.post(delivery_path,headers=headers)
                        assert delivered.status_code == 200, delivered.text
                        from pathlib import Path
                        bundle = Path(delivered.json()["delivery_history"][0]["bundle_path"])
                        from civiccore.exports import validate_bundle
                        validate_bundle(bundle)
                        assert (bundle/"sources/001-source.txt").read_bytes() == managed.read_bytes()
                        managed.write_bytes(b"Unexpected changed bytes")
                        assert (await runtime.post(delivery_path,headers=headers)).status_code == 422
                        assert (bundle/"sources/001-source.txt").read_bytes() == b"Synthetic packet source document."
                        managed.write_bytes(b"Synthetic packet source document.")
                        notice = await runtime.post(endpoint+"/notice-checks",json={
                            "notice_type":"regular","posted_at":"2026-10-20T17:59:00-06:00",
                            "minimum_notice_hours":24},headers=headers)
                        assert notice.status_code == 201, notice.text
                        assert not notice.json()["compliant"]
                        assert notice.json()["approved_by"] is None
                        document_path="/desktop/v1/meetings/notices/"+notice.json()["id"]+"/document"
                        template=await runtime.get("/desktop/v1/meetings/notices/"+notice.json()["id"]+"/template",headers=headers)
                        assert template.status_code==200,template.text
                        assert "NOTICE:" in template.json()["text"]
                        document=await runtime.post(document_path,json={"text":"Synthetic final notice."},headers=headers)
                        assert document.status_code==200,document.text
                        assert document.json()["status"]=="CHECKED"
                        first_document=document.json()["current_document"]
                        assert Path(first_document["bundle_path"],"notice.txt").read_text()=="Synthetic final notice."
                        validate_bundle(first_document["bundle_path"])
                        proof_path="/desktop/v1/meetings/notices/"+notice.json()["id"]+"/proof"
                        first_proof=await runtime.post(proof_path,json={"location":"Synthetic bulletin board","note":"First proof","document_delivery_id":first_document["delivery_id"]},headers=headers)
                        assert first_proof.status_code==200,first_proof.text
                        assert first_proof.json()["current_document_has_linked_proof"]
                        revised=await runtime.post(document_path,json={"text":"Synthetic revised notice."},headers=headers)
                        assert revised.status_code==200,revised.text
                        assert not revised.json()["current_document_has_linked_proof"]
                        assert revised.json()["posting_proof"]==first_proof.json()["posting_proof"]
                        assert Path(first_document["bundle_path"],"notice.txt").read_text()=="Synthetic final notice."
                        second_proof=await runtime.post(proof_path,json={"location":"Synthetic web notice","note":"Additional proof"},headers=headers)
                        assert second_proof.status_code==200,second_proof.text
                        assert second_proof.json()["audit_entries"][:-1]==revised.json()["audit_entries"]
                        assert second_proof.json()["audit_entries"][-1]["previous_posting_proof"]==first_proof.json()["posting_proof"]
                        transcript=await runtime.post(endpoint+"/transcripts",json={"source_label":"Synthetic clerk notes","transcript_text":"Council discussed trail maintenance."},headers=headers)
                        assert transcript.status_code==201,transcript.text
                        correction=await runtime.post(endpoint+"/transcripts",json={"source_label":"Corrected clerk notes","transcript_text":"Council discussed trail maintenance and access.","correction_of_id":transcript.json()["id"]},headers=headers)
                        assert correction.status_code==201,correction.text
                        motion = await runtime.post(endpoint + "/motions", json={"text": "Approve trail report", "actor": "forged"}, headers=headers)
                        assert motion.status_code == 422
                        motion = await runtime.post(endpoint + "/motions", json={"text": "Approve trail report"}, headers=headers)
                        assert motion.status_code == 201, motion.text
                        motion = motion.json()
                        assert motion["actor"] == str(actor_id)
                        action=await runtime.post(endpoint+"/action-items",json={"description":"Report trail repair costs","assigned_to":"Public Works","source_motion_id":motion["id"]},headers=headers)
                        assert action.status_code==201,action.text
                        vote_path = "/desktop/v1/meetings/motions/" + motion["id"] + "/votes"
                        vote = await runtime.post(vote_path, json={"voter_name": "Synthetic member", "vote": "aye"}, headers=headers)
                        assert vote.status_code == 201, vote.text
                        vote = vote.json()
                        corrected = await runtime.post("/desktop/v1/meetings/votes/" + vote["id"] + "/corrections", json={"vote": "nay", "reason": "Clerk capture correction"}, headers=headers)
                        assert corrected.status_code == 201, corrected.text
                        assert corrected.json()["correction_of_id"] == vote["id"]
                        draft = {"source_materials": [{"source_id": motion["id"], "label": "Motion", "text": motion["text"]}], "sentences": [{"text": motion["text"], "citations": [motion["id"]]}]}
                        minutes = await runtime.post(endpoint + "/minutes/drafts", json=draft, headers=headers)
                        assert minutes.status_code == 201, minutes.text
                        assert not minutes.json()["adopted"] and not minutes.json()["posted"]
                        decision_path = "/desktop/v1/meetings/minutes/" + minutes.json()["id"] + "/decisions"
                        posted = await runtime.post(decision_path,json={"action":"post"},headers=headers)
                        assert posted.status_code == 200, posted.text
                        assert posted.json()["posted"] and not posted.json()["adopted"]
                        assert posted.json()["publication_label"] == "Draft minutes — not adopted"
                        signed = await runtime.post(decision_path,json={"action":"sign","note":"Synthetic authorized signature"},headers=headers)
                        assert signed.status_code == 200, signed.text
                        assert signed.json()["signed_by"] == str(actor_id)
                        assert not signed.json()["adopted"]
                        assert signed.json()["decision_history"][-1]["warnings"]
                        adopted = await runtime.post(decision_path,json={"action":"adopt"},headers=headers)
                        assert adopted.status_code == 200, adopted.text
                        assert adopted.json()["adopted"]
                        assert adopted.json()["decision_history"][:len(signed.json()["decision_history"])] == signed.json()["decision_history"]
                        assert adopted.json()["decision_history"][:len(posted.json()["decision_history"])] == posted.json()["decision_history"]
                        assert (await runtime.post(decision_path,json={"action":"sign","actor":"forged"},headers=headers)).status_code == 422
                        draft["sentences"][0]["citations"] = ["unknown-source"]
                        uncited = await runtime.post(endpoint + "/minutes/drafts", json={"sentences":[{"text":"Staff-authored account without a citation."}]}, headers=headers)
                        assert uncited.status_code == 201, uncited.text
                        assert uncited.json()["decision_history"][0]["warnings"]
                        assert not uncited.json()["adopted"] and not uncited.json()["posted"]
                        archive_data={"visibility":"public","packet_id":packet.json()["packet_id"],"minutes_id":uncited.json()["id"],"plain_language_summary":"Synthetic <script>danger</script> archive."}
                        archive=await runtime.post(endpoint+"/archive",json=archive_data,headers=headers)
                        assert archive.status_code==201,archive.text
                        assert archive.json()["audit_entries"][0]["actor"]==str(actor_id)
                        assert archive.json()["audit_entries"][0]["source_references"]["minutes_id"]==uncited.json()["id"]
                        public_url="/public/meetings/"+archive.json()["id"]
                        public=await runtime.get(public_url)
                        assert public.status_code==200,public.text
                        assert "<script>danger</script>" not in public.text
                        assert "Draft minutes" in public.text
                        download=await runtime.get(public_url+"/minutes.txt")
                        assert download.status_code==200 and download.text.startswith("Draft minutes")
                        restricted=await runtime.post(endpoint+"/archive",json={**archive_data,"visibility":"closed_session"},headers=headers)
                        assert restricted.status_code==201,restricted.text
                        assert (await runtime.get("/public/meetings/"+restricted.json()["id"])).status_code==404
                        assert (await runtime.get("/public/meetings/"+restricted.json()["id"]+"/minutes.txt")).status_code==404
                        saved_public=(public_url,public.text)
                        # M3: real source lookup -> canonical Records attachment,
                        # never mocked search or caller-supplied source contents.
                        search_path="/desktop/v1/meetings-sources/search"
                        assert (await runtime.post(search_path,json={"query":"Staff-authored"})).status_code==401
                        assert (await runtime.post(search_path,json={"query":"Staff-authored"},headers=headers)).status_code==403
                        headers=use_role("records-staff")
                        found=await runtime.post(search_path,json={"query":"Staff-authored"},headers=headers)
                        assert found.status_code==200,found.text
                        source=next(s for s in found.json()["results"] if s["archive_id"]==archive.json()["id"])
                        assert all(s["archive_id"]!=restricted.json()["id"] for s in found.json()["results"])
                        intake=await runtime.post("/desktop/v1/requests",json={"requester":"Synthetic M3 resident",
                            "summary":"Meeting minutes","deadline":"2026-11-01","deadlineBasis":"Synthetic"},headers=headers)
                        assert intake.status_code==201,intake.text
                        records_endpoint="/desktop/v1/requests/"+intake.json()["id"]
                        selection={"source_id":source["source_id"],"expected_sha256":source["sha256"]}
                        attach_path=records_endpoint+"/meetings-sources"
                        assert (await runtime.post(attach_path,json={**selection,"expected_sha256":"0"*64},headers=headers)).status_code==409
                        forbidden_id=source["source_id"].replace(archive.json()["id"],restricted.json()["id"])
                        assert (await runtime.post(attach_path,json={**selection,"source_id":forbidden_id},headers=headers)).status_code==404
                        assert (await runtime.post(attach_path,json={**selection,"actor":"forged"},headers=headers)).status_code==422
                        linked=await runtime.post(attach_path,json=selection,headers=headers)
                        assert linked.status_code==200,linked.text
                        attached=linked.json()["request"]["documents"][0]
                        assert attached["sha256"]==source["sha256"]
                        assert attached["citation"]==source["citation"]
                        copied=Path(attached["stored_path"]).read_bytes()
                        assert hashlib.sha256(copied).hexdigest()==source["sha256"]
                        assert copied.decode()==download.text
                        replay=await runtime.post(attach_path,json=selection,headers=headers)
                        assert replay.status_code==200,replay.text
                        assert len(replay.json()["request"]["documents"])==1
                        assert replay.json()["request"]["timeline"]==linked.json()["request"]["timeline"]
                        response=await runtime.post(records_endpoint+"/actions",json={"action":"draft-records-response",
                            "payload":{"responseDraft":"Responsive meeting minutes attached for review.","citation":source["citation"]}},headers=headers)
                        assert response.status_code==200,response.text
                        assert response.json()["request"]["approved_at_unix_seconds"] is None
                        saved.append((records_endpoint+"/view",response.json()["request"]))
                        headers=use_role("clerk")
                        record = await runtime.get(endpoint + "/proceedings", headers=headers)
                        assert record.status_code == 200, record.text
                        assert [v["vote"] for v in record.json()["votes"]] == ["aye", "nay"]
                        assert len(record.json()["minutes"]) == 2
                        assert [p["version"] for p in record.json()["packet_snapshots"]] == [1, 2]
                        assert record.json()["packet_snapshots"][0]["agenda_item_ids"] == [saved[1][1]["id"]]
                        assert len(record.json()["transcripts"])==2
                        assert record.json()["transcripts"][0]["transcript_text"]=="Council discussed trail maintenance."
                        assert len(record.json()["action_items"])==1
                        saved.append((endpoint + "/proceedings", record.json()))
                        for meeting_type in ("special","emergency","closed_session"):
                            exceptional=await runtime.post(meeting_path,json={**meeting,"meeting_type":meeting_type},headers=headers)
                            assert exceptional.status_code==201,exceptional.text
                            exceptional_endpoint=meeting_path+"/"+exceptional.json()["id"]
                            assert exceptional.json()["meeting_type"]==meeting_type
                            saved.append((exceptional_endpoint,exceptional.json()))
                            if meeting_type=="closed_session":
                                closed=await runtime.post(exceptional_endpoint+"/transcripts",json={
                                    "source_label":"Restricted synthetic source","transcript_text":"Closed discussion not for public archive."},headers=headers)
                                assert closed.status_code==201,closed.text
                                assert closed.json()["sensitivity_label"]=="closed_session"
                                assert "Closed discussion" not in (await runtime.get("/public/meetings")).text
                    else:
                        assert (await runtime.get(saved_public[0])).text==saved_public[1]
                        for endpoint, expected in saved:
                            headers=use_role("records-staff" if endpoint.startswith("/desktop/v1/requests/") else "clerk")
                            response = await runtime.get(endpoint, headers=headers)
                            assert response.status_code == 200, response.text
                            assert response.json() == expected
                        # Missing schema must reject a write, not recreate/fallback.
                        headers=use_role("clerk")
                        engine = sa.create_engine(url)
                        with engine.begin() as connection:
                            connection.execute(sa.text("ALTER TABLE civicclerk.meetings RENAME TO m1_unready_records"))
                        try:
                            response = await runtime.post(meeting_path, json=meeting, headers=headers)
                            assert response.status_code == 503, response.text
                        finally:
                            with engine.begin() as connection:
                                connection.execute(sa.text("ALTER TABLE civicclerk.m1_unready_records RENAME TO meetings"))
                            engine.dispose()
            finally:
                process.terminate()
                process.wait(timeout=15)
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT count(*) FROM civicclerk.meetings")) == 4
            assert connection.scalar(sa.text("SELECT count(*) FROM civicclerk.agenda_items")) == 1
    finally:
        engine.dispose()
