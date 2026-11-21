"""Large recorder receipts and explicit first-run pairing, without allocating GiB fixtures."""
import json
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from townlight_records.desktop_bridge.schemas import ManagedFileReceipt
from townlight_records.desktop_bridge.station import station_url


def test_large_managed_receipt_preserves_size_without_32_bit_truncation():
    value = dict(original_path='station://fixture', stored_path='recording.ts', file_name='recording.ts', sha256='a'*64, size_bytes=3*1024**3)
    assert ManagedFileReceipt(**value).size_bytes == 3*1024**3
    for size in (64*1024**3+1, -1, True, '3000000000'):
        with pytest.raises(ValidationError):
            ManagedFileReceipt(**{**value, 'size_bytes': size})


def test_setup_pairing_is_required_and_malformed_pairing_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv('TOWNLIGHT_STATION_URL', raising=False)
    monkeypatch.setenv('TOWNLIGHT_PROFILE_ROOT', str(tmp_path))
    pairing = tmp_path/'config/station.json'
    pairing.parent.mkdir()
    with pytest.raises(HTTPException) as error:
        station_url()
    assert error.value.status_code == 503
    pairing.write_text(json.dumps({'configured': True}))
    assert station_url() == 'http://127.0.0.1:8756'
    pairing.write_text('corrupt')
    with pytest.raises(HTTPException) as error:
        station_url()
    assert error.value.status_code == 503
    monkeypatch.setenv('TOWNLIGHT_STATION_URL', 'http://127.0.0.1:18756')
    assert station_url() == 'http://127.0.0.1:18756'
