"""Minimal connector protocols.

Framework-independent (no FastAPI imports). ``Connector`` is the only
thing every source must provide: a type tag and a ``validate()`` check.
How a source's data is then made available is a separate, opt-in
capability - ``MaterializingConnector`` covers sources that are copied
into a local Parquet file via the existing ingestion boundary
(``data_engine.ingestion.ingest_to_parquet``). A future source that is
queried in place rather than materialized locally implements
``Connector`` without ``MaterializingConnector``, so nothing here forces
every source through a local Parquet path.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from data_engine.ingestion import IngestionResult


class ConnectorValidationError(ValueError):
    """The source was rejected by ``Connector.validate()``.

    The message is safe to show to an end user - it describes what is
    wrong with the source, never internal state.
    """


@runtime_checkable
class Connector(Protocol):
    source_type: str

    def validate(self) -> None:
        """Raise ``ConnectorValidationError`` if the source is unusable."""
        ...


@runtime_checkable
class MaterializingConnector(Connector, Protocol):
    def ingest(self, dataset_id: str, storage_root: str) -> IngestionResult:
        """Materialize the source as ``{storage_root}/{dataset_id}.parquet``."""
        ...
