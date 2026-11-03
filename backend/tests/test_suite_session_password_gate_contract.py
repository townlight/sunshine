"""Contract tests for Records AI suite sessions preserving password-rotation gates."""

from __future__ import annotations

import pytest


def test_suite_session_adapter_exposes_password_rotation_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOWNLIGHT_CORE_SUITE_SESSION_SECRET", "records-suite-session-secret")
    from townlight_records.auth.suite_session import (
        SuiteSessionUser,
        issue_suite_session_for_test,
        validate_suite_session_for_user,
    )

    user = SuiteSessionUser(
        email="rotate-suite@example.gov",
        roles=frozenset({"records_admin", "clerk_admin", "code_admin"}),
        must_change_password=True,
    )
    token = issue_suite_session_for_test(
        subject=user.email,
        roles=user.roles,
        session_id="records-password-rotation-required",
    )

    with pytest.raises(PermissionError, match="Password rotation required"):
        validate_suite_session_for_user(token, user=user, required_roles={"records_admin"})
