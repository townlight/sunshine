from typing import Annotated, Union
from pydantic import Field

from townlight_records.schemas.connectors.rest_api import RestApiConfig
from townlight_records.schemas.connectors.odbc import ODBCConfig

ConnectorConfig = Annotated[
    Union[RestApiConfig, ODBCConfig],
    Field(discriminator="connector_type"),
]

__all__ = ["ConnectorConfig", "RestApiConfig", "ODBCConfig"]
