"""Source connectors: the boundary between an external data source and
the existing ingestion -> DatasetManager registration pipeline."""

from data_engine.connectors.base import (
    Connector,
    ConnectorValidationError,
    MaterializingConnector,
)
from data_engine.connectors.csv_connector import CSVConnector

__all__ = [
    "Connector",
    "ConnectorValidationError",
    "MaterializingConnector",
    "CSVConnector",
]
