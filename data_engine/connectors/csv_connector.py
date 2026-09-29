"""CSV connector over a local file.

A thin adapter: validation is a few cheap checks on the file, and
ingestion is delegated unchanged to the existing bounded-memory
``data_engine.ingestion.ingest_to_parquet`` - no CSV parsing or Parquet
writing happens here.
"""

from __future__ import annotations

import os
from pathlib import Path

from data_engine.connectors.base import ConnectorValidationError
from data_engine.ingestion import IngestionResult, ingest_to_parquet

# How much of the file's head is inspected for null bytes. Matches the
# upload route's copy chunk size, so validate() inspects the same window
# the route checks while streaming.
LEADING_BYTES = 1024 * 1024  # 1 MB


class CSVConnector:
    source_type = "csv"

    def __init__(self, path: str, filename: str):
        # `path` is where the CSV bytes live; `filename` is the
        # (already sanitized) display name used to judge the file type.
        self.path = path
        self.filename = filename

    @staticmethod
    def check_filename(filename: str) -> None:
        if Path(filename).suffix.lower() != ".csv":
            raise ConnectorValidationError(
                "Only CSV files are currently supported."
            )

    @staticmethod
    def check_leading_bytes(head: bytes) -> None:
        # A CSV is text. Null bytes are the cheapest signal that this is
        # a binary file wearing a ".csv" extension (the CSV parser would
        # otherwise fail deep inside its C implementation with a much
        # more confusing error).
        if b"\x00" in head:
            raise ConnectorValidationError(
                "The uploaded file does not look like a text CSV file."
            )

    def validate(self) -> None:
        self.check_filename(self.filename)

        if not os.path.isfile(self.path) or os.path.getsize(self.path) == 0:
            raise ConnectorValidationError("The uploaded CSV file is empty.")

        with open(self.path, "rb") as source:
            self.check_leading_bytes(source.read(LEADING_BYTES))

    def ingest(self, dataset_id: str, storage_root: str) -> IngestionResult:
        with open(self.path, "rb") as source_stream:
            return ingest_to_parquet(
                source_stream=source_stream,
                dataset_id=dataset_id,
                storage_root=storage_root,
            )
