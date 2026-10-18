"""Read-only import validation. This is not a transactional/cutover proof."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

runtime_root = Path(__file__).resolve().parents[3] / "townlight/desktop/runtime/python-services"
if not runtime_root.is_dir():
    pytest.skip("Requires the paired Townlight runtime checkout", allow_module_level=True)
sys.path.insert(0, str(runtime_root))
from civicsuite_runtime.records_import import preflight


def source(root, data):
    path = root / "Data" / "workflows" / "city-work.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def sample():
    audit = dict(id="audit-1", module_id="civicrecords-ai", action="fixture", summary="Historical evidence",
                 created_at_unix_seconds=1000, previous_hash="GENESIS")
    audit["entry_hash"] = hashlib.sha256("\n".join(str(audit[k]) for k in (
        "previous_hash", "id", "module_id", "action", "summary", "created_at_unix_seconds")).encode()).hexdigest()
    return {"meetings": [], "code_sources": [], "code_handoffs": [], "audit_entries": [audit],
            "records_requests": [{"id":"historical-1", "requester":"Fixture resident", "summary":"Fixture work",
                "deadline":"Staff-reviewed label", "status":"approved", "response_draft":"Approved historical text",
                "approval_notes":["Historical reviewer note"], "approved_at_unix_seconds":1001,
                "created_at_unix_seconds":1000}]}


def test_preflight_preserves_source_defaults_ids_approval_and_hashes(tmp_path):
    data = sample()
    path = source(tmp_path, data)
    original_bytes = path.read_bytes()
    first = preflight(tmp_path)
    second = preflight(tmp_path)
    assert first.source_bytes == original_bytes == path.read_bytes()
    assert first.source_sha256 == hashlib.sha256(original_bytes).hexdigest()
    assert first.records[0].request_id == second.records[0].request_id
    assert first.records[0].id == "historical-1"
    assert first.records[0].approved_at_unix_seconds == 1001
    assert first.records[0].approval_notes == ["Historical reviewer note"]
    assert first.original == data
    assert first.legacy_audit_head == data["audit_entries"][-1]["entry_hash"]
    assert first.unhashed_audit_entries == 0
    assert first.verified_files == ()


@pytest.mark.parametrize("change", ["future-schema", "unknown-field", "bad-audit", "duplicate-id", "private-visibility"])
def test_preflight_refuses_lossy_or_corrupt_inputs_without_changes(tmp_path, change):
    data = sample()
    if change == "future-schema": data["schema_version"] = 2
    elif change == "unknown-field": data["records_requests"][0]["new_domain_field"] = "Do not drop me"
    elif change == "bad-audit": data["audit_entries"][0]["summary"] = "Altered evidence"
    elif change == "duplicate-id": data["records_requests"].append(copy.deepcopy(data["records_requests"][0]))
    else: data["records_requests"][0]["messages"] = [{"id":"msg-1", "author":"Fixture", "author_role":"staff",
            "body":"Private", "visibility":"unknown", "created_at_unix_seconds":1000}]
    path = source(tmp_path, data)
    before = path.read_bytes()
    with pytest.raises(ValueError): preflight(tmp_path)
    assert path.read_bytes() == before


def test_preflight_verifies_document_bytes_and_retains_them_on_failure(tmp_path):
    data = sample()
    file = tmp_path / "Data" / "files" / "records" / "original.txt"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"Original evidence")
    data["records_requests"][0]["documents"] = [{"id":"doc-1", "title":"Original", "original_path":"typed source",
        "stored_path":str(file), "citation":"Fixture", "sha256":hashlib.sha256(file.read_bytes()).hexdigest(),
        "size_bytes":file.stat().st_size, "status":"attached for response review", "added_by":"historical staff", "created_at_unix_seconds":1000}]
    path = source(tmp_path, data)
    result = preflight(tmp_path)
    assert len(result.verified_files) == 1
    assert result.records[0].documents[0].id == "doc-1"
    before = path.read_bytes()
    file.write_bytes(b"Changed evidence")
    with pytest.raises(ValueError): preflight(tmp_path)
    assert file.read_bytes() == b"Changed evidence"
    assert path.read_bytes() == before
