import io
import os
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from data_engine.ingestion import IngestionResult, ingest_to_parquet


def _csv_stream(text: str) -> io.BytesIO:
    return io.BytesIO(text.encode("utf-8"))


def test_ingest_csv_to_parquet_success(tmp_path):
    csv_text = "id,name,amount\n1,alice,10.5\n2,bob,20.0\n3,carol,30.25\n"
    stream = _csv_stream(csv_text)

    result = ingest_to_parquet(
        source_stream=stream,
        dataset_id="dataset_ok",
        storage_root=str(tmp_path),
    )

    expected_path = os.path.join(str(tmp_path), "dataset_ok.parquet")
    assert isinstance(result, IngestionResult)
    assert result.dataset_id == "dataset_ok"
    assert result.parquet_path == expected_path
    assert result.row_count == 3
    assert result.column_names == ["id", "name", "amount"]
    assert os.path.exists(expected_path)

    table = pq.read_table(expected_path)
    assert table.num_rows == 3
    assert table.column_names == ["id", "name", "amount"]


def test_ingest_reports_matching_schema_info(tmp_path):
    csv_text = "id,score\n1,1.5\n2,2.5\n"
    stream = _csv_stream(csv_text)

    result = ingest_to_parquet(
        source_stream=stream,
        dataset_id="dataset_schema",
        storage_root=str(tmp_path),
    )

    assert set(result.schema_info.keys()) == {"id", "score"}
    table = pq.read_table(result.parquet_path)
    for name in table.column_names:
        assert result.schema_info[name] == str(table.schema.field(name).type)


def test_ingest_creates_nested_storage_root(tmp_path):
    nested_root = tmp_path / "nested" / "storage"
    stream = _csv_stream("a,b\n1,2\n")

    result = ingest_to_parquet(
        source_stream=stream,
        dataset_id="dataset_nested",
        storage_root=str(nested_root),
    )

    assert os.path.isdir(str(nested_root))
    assert os.path.exists(result.parquet_path)


def test_ingest_cleans_up_partial_file_on_parser_failure(tmp_path):
    stream = _csv_stream("id,name\n1,alice\n2,bob\n")
    dataset_id = "dataset_failure"
    expected_path = os.path.join(str(tmp_path), f"{dataset_id}.parquet")

    schema = pa.schema([("id", pa.int64()), ("name", pa.string())])
    good_batch = pa.RecordBatch.from_arrays(
        [pa.array([1], type=pa.int64()), pa.array(["alice"], type=pa.string())],
        schema=schema,
    )

    class FakeReader:
        def __init__(self):
            self.schema = schema
            self._batches = iter([good_batch])

        def read_next_batch(self):
            try:
                return next(self._batches)
            except StopIteration:
                raise RuntimeError("simulated parser failure")

    with patch("data_engine.ingestion.pa_csv.open_csv", return_value=FakeReader()):
        with pytest.raises(RuntimeError, match="simulated parser failure"):
            ingest_to_parquet(
                source_stream=stream,
                dataset_id=dataset_id,
                storage_root=str(tmp_path),
            )

    assert not os.path.exists(expected_path)


def test_ingest_cleans_up_on_failure_before_any_batch_written(tmp_path):
    stream = _csv_stream("id,name\n1,alice\n")
    dataset_id = "dataset_failure_early"
    expected_path = os.path.join(str(tmp_path), f"{dataset_id}.parquet")

    class FakeReader:
        def __init__(self):
            self.schema = pa.schema([("id", pa.int64()), ("name", pa.string())])

        def read_next_batch(self):
            raise RuntimeError("simulated early failure")

    with patch("data_engine.ingestion.pa_csv.open_csv", return_value=FakeReader()):
        with pytest.raises(RuntimeError, match="simulated early failure"):
            ingest_to_parquet(
                source_stream=stream,
                dataset_id=dataset_id,
                storage_root=str(tmp_path),
            )

    assert not os.path.exists(expected_path)
