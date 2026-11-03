"""P6a migration 014 tests — verify schema changes are correct.

These tests do NOT run the actual Alembic migration (that requires a fresh DB with all prior
migrations applied). Instead they verify the SQL shape the migration would produce by
inspecting the model and checking that the upgrade/downgrade functions contain the expected
operations. Run against the integration test DB after applying the migration.
"""


def test_migration_014_revision_metadata():
    """Migration has correct revision and down_revision IDs."""
    import importlib as ilib
    spec = ilib.util.spec_from_file_location(
        "migration_014",
        "alembic/versions/014_p6a_idempotency.py",
    )
    mod = ilib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "014_p6a_idempotency"
    assert mod.down_revision == "013_connector_types"


def test_connector_type_column_on_document_model():
    """Document ORM model has connector_type mapped column."""
    from townlight_records.models.document import Document
    from sqlalchemy import inspect
    mapper = inspect(Document)
    col_names = [c.key for c in mapper.mapper.column_attrs]
    assert "connector_type" in col_names, f"connector_type missing from Document model. Found: {col_names}"


def test_updated_at_column_on_document_model():
    """Document ORM model has updated_at mapped column."""
    from townlight_records.models.document import Document
    from sqlalchemy import inspect
    mapper = inspect(Document)
    col_names = [c.key for c in mapper.mapper.column_attrs]
    assert "updated_at" in col_names, f"updated_at missing from Document model. Found: {col_names}"


def test_migration_014_has_partial_index_for_structured():
    """Migration 014 upgrade() creates the structured partial UNIQUE index."""
    import pathlib
    src = pathlib.Path("alembic/versions/014_p6a_idempotency.py").read_text()
    assert "uq_documents_structured_path" in src
    assert "connector_type IN" in src


def test_migration_014_has_partial_index_for_binary():
    """Migration 014 upgrade() creates the binary partial UNIQUE index."""
    import pathlib
    src = pathlib.Path("alembic/versions/014_p6a_idempotency.py").read_text()
    assert "uq_documents_binary_hash" in src
    assert "connector_type NOT IN" in src


def test_migration_014_has_source_path_check_constraint():
    """Migration 014 upgrade() creates the source_path length check constraint."""
    import pathlib
    src = pathlib.Path("alembic/versions/014_p6a_idempotency.py").read_text()
    assert "chk_source_path_length" in src
    assert "2048" in src
