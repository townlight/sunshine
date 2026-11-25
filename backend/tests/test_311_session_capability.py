"""Role capabilities for the Townlight 311 module in native desktop sessions."""

from __future__ import annotations

import pytest

from townlight_records.auth.desktop_session import NativeDesktopPrincipal


def _principal(role: str) -> NativeDesktopPrincipal:
    return NativeDesktopPrincipal(
        email=f"{role}@example.invalid",
        display_name=f"Synthetic {role}",
        role=role,
        expires_at_unix_seconds=2000,
    )


@pytest.mark.parametrize("module_id", ["townlight_311", "townlight_comms", "townlight_parks"])
@pytest.mark.parametrize(
    "role, has_access",
    [
        ("local-admin", True),
        ("city-staff", True),
        ("clerk", True),
        ("records-staff", False),
        ("code-staff", False),
    ],
)
def test_module_capability_for_each_existing_role(role: str, has_access: bool, module_id: str) -> None:
    """Existing roles keep the same access matrix for each added module."""
    assert _principal(role).allows_module(module_id) is has_access


@pytest.mark.parametrize(
    "module_id",
    [
        "townlight_meetings",
        "townlight_notice",
        "townlight_access",
        "townlight_311",
        "townlight_comms",
        "townlight_parks",
    ],
)
def test_clerk_keeps_existing_module_grants_and_gains_added_modules(module_id: str) -> None:
    """Clerk preserves existing grants and receives the added module grants."""
    assert _principal("clerk").allows_module(module_id)
