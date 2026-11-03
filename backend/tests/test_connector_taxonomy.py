"""T3B/T3C: Connector taxonomy unification tests.

Verifies that:
- SourceType enum uses only the 4 canonical values
- imap_email is not reachable from the shipping registry
- Registry contains exactly the 4 implemented connector types
- dispatch returns an explicit error for unknown source types
- test-connection returns actionable errors for file_system and manual_drop
"""
import pytest
from townlight_records.models.document import SourceType
from townlight_records.connectors import _REGISTRY


# ── Enum / Registry ─────────────────────────────────────────────────────────

class TestCanonicalVocabulary:
    def test_source_type_canonical_values(self):
        values = {m.value for m in SourceType}
        assert values == {"file_system", "manual_drop", "rest_api", "odbc"}

    def test_source_type_no_legacy_values(self):
        values = {m.value for m in SourceType}
        assert "upload" not in values, "legacy 'upload' value must not exist in SourceType"
        assert "directory" not in values, "legacy 'directory' value must not exist in SourceType"
        assert "imap_email" not in values
        assert "email" not in values
        assert "imap" not in values

    def test_registry_has_exactly_canonical_types(self):
        assert set(_REGISTRY.keys()) == {"file_system", "manual_drop", "rest_api", "odbc"}

    def test_imap_email_not_in_registry(self):
        assert "imap_email" not in _REGISTRY, "imap_email must not be a shipping registry entry"

    def test_registry_connectors_are_importable(self):
        """Each registered connector class must be importable and instantiable."""
        from townlight_records.connectors.file_system import FileSystemConnector
        from townlight_records.connectors.manual_drop import ManualDropConnector
        from townlight_records.connectors.rest_api import RestApiConnector
        from townlight_records.connectors.odbc import OdbcConnector

        assert _REGISTRY["file_system"] is FileSystemConnector
        assert _REGISTRY["manual_drop"] is ManualDropConnector
        assert _REGISTRY["rest_api"] is RestApiConnector
        assert _REGISTRY["odbc"] is OdbcConnector

    def test_imap_class_exists_on_disk_but_not_in_registry(self):
        """ImapEmailConnector may remain as roadmap groundwork but must not ship."""
        from townlight_records.connectors.imap_email import ImapEmailConnector
        assert ImapEmailConnector is not None
        assert "imap_email" not in _REGISTRY


# ── test-connection actionable messages ──────────────────────────────────────

class TestConnectionActionableErrors:
    """Test-connection responses must be human-actionable, not vague."""

    def _make_request(self, **kwargs):
        from townlight_records.datasources.router import TestConnectionRequest
        return TestConnectionRequest(**kwargs)

    @pytest.mark.asyncio
    async def test_file_system_missing_path_returns_clear_error(self):
        from townlight_records.datasources.router import test_connection
        req = self._make_request(source_type="file_system", path=None)
        resp = await test_connection(req, user=None)
        assert resp.success is False
        assert "path" in resp.message.lower()

    @pytest.mark.asyncio
    async def test_file_system_nonexistent_path_names_path_in_error(self, tmp_path):
        from townlight_records.datasources.router import test_connection
        bad = str(tmp_path / "does_not_exist")
        req = self._make_request(source_type="file_system", path=bad)
        resp = await test_connection(req, user=None)
        assert resp.success is False
        assert bad in resp.message, "Error message must name the bad path"

    @pytest.mark.asyncio
    async def test_file_system_valid_path_returns_success(self, tmp_path):
        from townlight_records.datasources.router import test_connection
        req = self._make_request(source_type="file_system", path=str(tmp_path))
        resp = await test_connection(req, user=None)
        assert resp.success is True
        assert "accessible" in resp.message.lower()

    @pytest.mark.asyncio
    async def test_manual_drop_missing_path_returns_clear_error(self):
        from townlight_records.datasources.router import test_connection
        req = self._make_request(source_type="manual_drop", path=None)
        resp = await test_connection(req, user=None)
        assert resp.success is False
        assert "path" in resp.message.lower() or "drop_path" in resp.message.lower()

    @pytest.mark.asyncio
    async def test_manual_drop_nonexistent_path_names_path(self, tmp_path):
        from townlight_records.datasources.router import test_connection
        bad = str(tmp_path / "missing_drop")
        req = self._make_request(source_type="manual_drop", path=bad)
        resp = await test_connection(req, user=None)
        assert resp.success is False
        assert bad in resp.message

    @pytest.mark.asyncio
    async def test_manual_drop_valid_path_returns_success(self, tmp_path):
        from townlight_records.datasources.router import test_connection
        req = self._make_request(source_type="manual_drop", path=str(tmp_path))
        resp = await test_connection(req, user=None)
        assert resp.success is True

    @pytest.mark.asyncio
    async def test_unknown_source_type_returns_failure(self):
        from townlight_records.datasources.router import test_connection
        req = self._make_request(source_type="imap")
        resp = await test_connection(req, user=None)
        assert resp.success is False
        assert "unknown" in resp.message.lower() or "imap" in resp.message.lower()

    @pytest.mark.asyncio
    async def test_rest_api_without_config_returns_clear_error(self):
        from townlight_records.datasources.router import test_connection
        req = self._make_request(source_type="rest_api", rest_api_config=None)
        resp = await test_connection(req, user=None)
        assert resp.success is False
        assert "rest_api_config" in resp.message

    @pytest.mark.asyncio
    async def test_odbc_without_config_returns_clear_error(self):
        from townlight_records.datasources.router import test_connection
        req = self._make_request(source_type="odbc", odbc_config=None)
        resp = await test_connection(req, user=None)
        assert resp.success is False
        assert "odbc_config" in resp.message
