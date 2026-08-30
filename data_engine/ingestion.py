"""Bounded-memory CSV -> Parquet ingestion.

Framework-independent (no FastAPI imports). Streams the source in
fixed-size chunks via pyarrow's incremental CSV reader and writes each
batch straight to a Parquet file through pyarrow.parquet.ParquetWriter,
so the full file/DataFrame is never materialized in memory at once.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import BinaryIO, Dict, List

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq

# Number of rows pyarrow buffers per incremental read_next_batch() call.
_BLOCK_SIZE_BYTES = 8 * 1024 * 1024


@dataclass
class IngestionResult:
    dataset_id: str
    parquet_path: str
    row_count: int
    column_names: List[str]
    schema_info: Dict[str, str] = field(default_factory=dict)


def ingest_to_parquet(
    source_stream: BinaryIO,
    dataset_id: str,
    storage_root: str,
) -> IngestionResult:
    """Stream ``source_stream`` (CSV bytes) into a Parquet file.

    Processes the input incrementally in bounded-size batches — never
    reads the whole file or a full DataFrame into memory. Row counts and
    schema are tracked as batches are written, not by re-reading the
    output afterward. On any failure the partially written Parquet file
    is removed and the exception is re-raised unchanged.
    """
    os.makedirs(storage_root, exist_ok=True)
    parquet_path = os.path.join(storage_root, f"{dataset_id}.parquet")

    row_count = 0
    column_names: List[str] = []
    schema_info: Dict[str, str] = {}
    writer: pq.ParquetWriter | None = None
    reader = None

    try:
        read_options = pa_csv.ReadOptions(block_size=_BLOCK_SIZE_BYTES)
        reader = pa_csv.open_csv(source_stream, read_options=read_options)

        while True:
            try:
                batch = reader.read_next_batch()
            except StopIteration:
                break

            if writer is None:
                schema = batch.schema
                column_names = list(schema.names)
                schema_info = {name: str(schema.field(name).type) for name in schema.names}
                writer = pq.ParquetWriter(parquet_path, schema)

            writer.write_batch(batch)
            row_count += batch.num_rows

        if writer is None:
            # Empty input: still produce a valid (header-less) parquet file
            # using whatever schema pyarrow inferred, if any.
            schema = reader.schema if reader is not None else pa.schema([])
            column_names = list(schema.names)
            schema_info = {name: str(schema.field(name).type) for name in schema.names}
            writer = pq.ParquetWriter(parquet_path, schema)

        return IngestionResult(
            dataset_id=dataset_id,
            parquet_path=parquet_path,
            row_count=row_count,
            column_names=column_names,
            schema_info=schema_info,
        )
    except Exception:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
            writer = None
        if os.path.exists(parquet_path):
            try:
                os.remove(parquet_path)
            except OSError:
                pass
        raise
    finally:
        if writer is not None:
            writer.close()
