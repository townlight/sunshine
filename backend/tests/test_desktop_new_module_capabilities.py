import pytest

from townlight_records.auth.desktop_session import NativeDesktopPrincipal


@pytest.mark.parametrize(
    ("role", "module_id", "expected"),
    [
        ("clerk", "townlight_utilities", True),
        ("clerk", "townlight_library", True),
        ("clerk", "townlight_elections", True),
        ("records-staff", "townlight_utilities", False),
        ("records-staff", "townlight_library", False),
        ("records-staff", "townlight_elections", False),
        ("code-staff", "townlight_utilities", False),
        ("code-staff", "townlight_library", False),
        ("code-staff", "townlight_elections", False),
        ("unknown-role", "townlight_utilities", False),
        ("unknown-role", "townlight_library", False),
        ("unknown-role", "townlight_elections", False),
        ("records-staff", "townlight_records", True),
    ],
)
def test_desktop_module_capabilities(role: str, module_id: str, expected: bool) -> None:
    principal = NativeDesktopPrincipal(
        email="staff@example.test",
        display_name="Staff Member",
        role=role,
        expires_at_unix_seconds=2**32,
    )

    assert principal.allows_module(module_id) is expected
