from townlight_records.connectors.base import BaseConnector
from townlight_records.connectors.file_system import FileSystemConnector
from townlight_records.connectors.manual_drop import ManualDropConnector
from townlight_records.connectors.rest_api import RestApiConnector
from townlight_records.connectors.odbc import OdbcConnector

_REGISTRY: dict[str, type[BaseConnector]] = {
    "file_system": FileSystemConnector,
    "manual_drop": ManualDropConnector,
    "rest_api": RestApiConnector,
    "odbc": OdbcConnector,
}


def get_connector(connector_type: str, config: dict) -> BaseConnector:
    """Instantiate a connector by type string.

    Raises ValueError for unknown connector types.
    """
    cls = _REGISTRY.get(connector_type)
    if cls is None:
        raise ValueError(
            f"Unknown connector type: {connector_type!r}. "
            f"Available: {sorted(_REGISTRY.keys())}"
        )
    return cls(config)


__all__ = ["get_connector", "_REGISTRY"]
