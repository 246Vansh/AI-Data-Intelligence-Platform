"""Step 10: storage-tier selection for ingestion output.

``select_storage_for_ingestion`` is the single place that maps an
IngestionResult (a Parquet path + schema descriptor) onto a concrete
DatasetStorage backend. This mirrors
``data_engine.execution.selector.select_engine_for`` on purpose - it
keeps storage-backend dispatch confined to the storage package instead
of leaking engine-specific type checks into DatasetManager or, worse,
FastAPI route code.
"""

import io

from data_engine.ingestion import ingest_to_parquet
from data_engine.storage import DatasetStorage, DuckDBStorage
from data_engine.storage.selector import select_storage_for_ingestion


def _csv_stream(text: str) -> io.BytesIO:
    return io.BytesIO(text.encode("utf-8"))


def test_select_storage_for_ingestion_returns_duckdb_storage(tmp_path):
    result = ingest_to_parquet(
        source_stream=_csv_stream("id,name\n1,alice\n2,bob\n"),
        dataset_id="sel_ds",
        storage_root=str(tmp_path),
    )

    storage = select_storage_for_ingestion(result)

    assert isinstance(storage, DatasetStorage)
    assert isinstance(storage, DuckDBStorage)
    assert storage.row_count() == 2
    assert storage.column_names() == ["id", "name"]


def test_select_storage_for_ingestion_reads_from_the_parquet_file_itself(tmp_path):
    # Prove the storage is backed by the persistent Parquet reference,
    # not by anything held over from ingestion in Python memory: build
    # it straight from the IngestionResult's path, independent of the
    # ingest_to_parquet call that produced it.
    result = ingest_to_parquet(
        source_stream=_csv_stream("amount\n10\n20\n30\n"),
        dataset_id="sel_ds_2",
        storage_root=str(tmp_path),
    )

    storage = select_storage_for_ingestion(result)

    assert storage.row_count() == 3
    assert storage.to_dataframe()["amount"].sum() == 60
