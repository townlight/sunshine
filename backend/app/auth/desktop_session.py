"""Compatibility boundary for the desktop's existing native authenticated session."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import time


_ROLE_MODULES: dict[str, frozenset[str] | None] = {
    "local-admin": None,
    "city-staff": None,
    "clerk": frozenset({"civicclerk", "civicnotice", "civicaccess"}),
    "records-staff": frozenset({"civicrecords-ai"}),
    "code-staff": frozenset({"civiccode"}),
}


def validate_native_public_proof(proof: str | None, *, profile_root: Path) -> None:
    """Authenticate the local shell, not a resident identity or staff role."""
    try:
        admin = _json_file(profile_root / "config" / "first-admin.json")
        if not isinstance(admin, dict) or not admin.get("email"):
            raise ValueError("Setup incomplete")
        key = bytes.fromhex((profile_root / "session-mac-secret.key").read_text().strip())
        if len(key) != 32 or not isinstance(proof, str):
            raise ValueError("Invalid proof")
        expected = hmac.new(key, b"townlight-native-public-records-v1", hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, proof):
            raise ValueError("Invalid proof")
    except (OSError, ValueError, TypeError):
        raise PermissionError("Public Records requires the configured local application.") from None


@dataclass(frozen=True)
class NativeDesktopPrincipal:
    email: str
    display_name: str
    role: str
    expires_at_unix_seconds: int

    def allows_module(self, module_id: str) -> bool:
        if self.role not in _ROLE_MODULES:
            return False
        modules = _ROLE_MODULES[self.role]
        return modules is None or module_id in modules


def _json_file(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_native_session(
    proof: str | None,
    *,
    profile_root: Path,
    now_unix_seconds: int | None = None,
) -> NativeDesktopPrincipal:
    """Validate explicit proof against the current native session and account.

    This mirrors auth.rs's existing HMAC message, not a new login protocol.
    The service must not authenticate a caller merely because a desktop user
    is signed in: the caller must possess that session's proof. Checking the
    current files also preserves sign-out, expiry, disablement and credential
    or role-change invalidation. No secret or raw input appears in errors.
    """
    denied = "Sign in with an authorized Townlight desktop account."
    if not isinstance(proof, str) or len(proof) != 64:
        raise PermissionError(denied)
    try:
        supplied = bytes.fromhex(proof)
        config = profile_root / "config"
        session = _json_file(config / "local-session.json")
        admin = _json_file(config / "first-admin.json")
        if not isinstance(session, dict) or not isinstance(admin, dict):
            raise ValueError("Invalid native account state")
        email = session["email"]
        role = session["role"]
        expiry = session["expires_at_unix_seconds"]
        if (not isinstance(email, str) or not email.strip()
                or role not in _ROLE_MODULES or type(expiry) is not int
                or not 0 <= expiry <= (2**64 - 1)):
            raise ValueError("Invalid native session fields")
        now = int(time.time()) if now_unix_seconds is None else now_unix_seconds
        if expiry <= now:
            raise PermissionError(denied)

        normalized_email = email.strip().lower()
        if str(admin.get("email", "")).strip().lower() == normalized_email:
            account = admin
        else:
            users_path = config / "staff-users.json"
            users = _json_file(users_path) if users_path.is_file() else []
            if not isinstance(users, list) or any(not isinstance(u, dict) for u in users):
                raise ValueError("Invalid native user list")
            matches = [u for u in users
                       if str(u.get("email", "")).strip().lower() == normalized_email]
            if len(matches) != 1 or matches[0].get("active") is not True:
                raise PermissionError(denied)
            account = matches[0]
        verifier = account["passcode_hash"]
        account_email = account["email"]
        display_name = account["display_name"]
        if (account.get("role") != role or not isinstance(verifier, str) or not verifier
                or not isinstance(account_email, str) or not isinstance(display_name, str)):
            raise PermissionError(denied)
        key = bytes.fromhex((profile_root / "session-mac-secret.key").read_text().strip())
        if len(key) != 32 or len(supplied) != 32:
            raise PermissionError(denied)
        message = f"{account_email.lower()}\n{role}\n{expiry}\n{verifier}".encode("utf-8")
        expected = hmac.new(key, message, hashlib.sha256).digest()
        saved = bytes.fromhex(session["session_hash"])
        if not hmac.compare_digest(supplied, saved) or not hmac.compare_digest(saved, expected):
            raise PermissionError(denied)
        return NativeDesktopPrincipal(normalized_email, display_name, role, expiry)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        raise PermissionError(denied) from None
