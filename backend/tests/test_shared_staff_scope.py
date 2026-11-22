"""Unbound or cross-profile shared staff proofs cannot grant native access."""

import pytest

from townlight_records.auth.desktop_session import (
    NativeDesktopPrincipal,
    shared_staff_scope,
    validate_native_session,
)


def test_shared_principal_stays_inside_host_request_scope(tmp_path):
    proof = "e" * 64
    principal = NativeDesktopPrincipal("clerk@city.example", "City Clerk", "clerk", 20)
    with shared_staff_scope(tmp_path, proof, principal):
        actor = validate_native_session(proof, profile_root=tmp_path, now_unix_seconds=10)
        assert actor.allows_module("townlight_meetings")
        assert not actor.allows_module("townlight_records")
        with pytest.raises(PermissionError):
            validate_native_session(proof, profile_root=tmp_path / "different-profile", now_unix_seconds=10)
        with pytest.raises(PermissionError):
            validate_native_session("a" * 64, profile_root=tmp_path, now_unix_seconds=10)
        with pytest.raises(PermissionError):
            validate_native_session(proof, profile_root=tmp_path, now_unix_seconds=20)
    with pytest.raises(PermissionError):
        validate_native_session(proof, profile_root=tmp_path, now_unix_seconds=10)
