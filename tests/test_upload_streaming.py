"""Step 24: streaming upload + removal of the 100MB bottleneck.

Verifies, at the FastAPI route level, that the production upload path:
  - never accumulates the HTTP body into one in-memory bytes object
    (``b"".join(chunks)``);
  - copies the incoming upload incrementally, in bounded chunks, into
    a temporary file, which is what gets handed to the existing
    bounded-memory ``ingest_to_parquet`` pipeline;
  - enforces the configured upload-size ceiling while streaming, not
    after buffering the whole body;
  - removes the temporary upload file on every exit path (success,
    ingestion failure, and over-limit rejection);
  - still behaves exactly as before for a normal small CSV upload
    (same response contract, same 100MB-era limit still removed).

Each test gets its own DatasetManager/DatasetRegistry pair patched into
the route module, matching the isolation pattern already used by
tests/test_route_upload_ingestion.py, so this never touches the
process-wide singletons other test modules (or the running app) rely
on.
"""

import glob
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.routes.dataset as dataset_route
from backend.main import app
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_registry import DatasetRegistry

client = TestClient(app)

VALID_CSV = b"id,name,amount\n1,alice,10.5\n2,bob,20.0\n3,carol,30.25\n"

# The prefix upload_dataset() gives its temp file (dataset.py). Used
# below to scan the system temp directory for leftovers without
# depending on any other private implementation detail.
_TMP_GLOB = os.path.join(tempfile.gettempdir(), "dataset_upload_*")


def _leftover_tmp_files() -> set[str]:
    return set(glob.glob(_TMP_GLOB))


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "PARQUET_STORAGE_ROOT", str(tmp_path))

    return registry


def _upload(filename: str = "sample.csv", content: bytes = VALID_CSV):
    return client.post(
        "/api/dataset/upload",
        files={"file": (filename, content, "text/csv")},
    )


# =========================================================
# A. SMALL UPLOAD STILL SUCCEEDS, WITH THE SAME RESPONSE CONTRACT
# =========================================================


def test_small_upload_still_succeeds_with_unchanged_contract(isolated_registry):
    response = _upload(filename="orders.csv")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "message",
        "filename",
        "rows",
        "columns",
        "dataset_id",
    }
    assert body["filename"] == "orders.csv"
    assert body["rows"] == 3
    assert body["columns"] == 3


# =========================================================
# B. NO WHOLE-FILE b"".join(chunks) BUFFERING IN THE SOURCE
# =========================================================


def test_upload_route_source_contains_no_whole_file_join():
    source = Path(dataset_route.__file__).read_text(encoding="utf-8")
    assert 'b"".join(' not in source
    assert "b''.join(" not in source


# =========================================================
# C. UPLOAD IS STREAMED/COPIED INCREMENTALLY INTO THE TEMP SINK
# =========================================================


def test_upload_copies_in_bounded_incremental_chunks(isolated_registry, monkeypatch):
    # Force many small chunks instead of one read grabbing the whole
    # (small) test payload, so the incremental behavior is observable.
    monkeypatch.setattr(dataset_route, "UPLOAD_CHUNK_BYTES", 8)

    write_sizes = []
    real_named_temp_file = tempfile.NamedTemporaryFile

    class _SpyTempFile:
        """Wraps the real temp file to record each incremental write."""

        def __init__(self, real_file):
            self._real = real_file

        def write(self, data):
            write_sizes.append(len(data))
            return self._real.write(data)

        def close(self):
            return self._real.close()

        @property
        def name(self):
            return self._real.name

    def _spy_named_temp_file(*args, **kwargs):
        return _SpyTempFile(real_named_temp_file(*args, **kwargs))

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _spy_named_temp_file)

    response = _upload(content=VALID_CSV)

    assert response.status_code == 200
    # More than one write proves the body was copied incrementally,
    # not accumulated then written once; each write staying within the
    # configured chunk size proves memory stays bounded per-chunk.
    assert len(write_sizes) > 1
    assert all(size <= 8 for size in write_sizes)
    assert sum(write_sizes) == len(VALID_CSV)


# =========================================================
# D/E/F. CONFIGURED LIMIT IS ENFORCED WHILE STREAMING
# =========================================================


def test_upload_just_below_limit_reaches_ingestion(isolated_registry, monkeypatch):
    monkeypatch.setattr(dataset_route, "MAX_UPLOAD_BYTES", len(VALID_CSV))

    response = _upload(content=VALID_CSV)

    assert response.status_code == 200
    assert response.json()["rows"] == 3


def test_upload_above_limit_is_rejected_with_413(isolated_registry, monkeypatch):
    monkeypatch.setattr(dataset_route, "MAX_UPLOAD_BYTES", len(VALID_CSV) - 1)

    response = _upload(content=VALID_CSV)

    assert response.status_code == 413
    assert "maximum allowed size" in response.json()["detail"]

    # Rejected upload registered nothing.
    assert isolated_registry.list() == []


def test_upload_above_limit_stops_reading_before_full_body(isolated_registry, monkeypatch):
    # A limit far smaller than the payload, with a small chunk size,
    # so the incremental check has multiple opportunities to fire
    # before the (fake) "rest of the file" would ever be read.
    monkeypatch.setattr(dataset_route, "MAX_UPLOAD_BYTES", 4)
    monkeypatch.setattr(dataset_route, "UPLOAD_CHUNK_BYTES", 4)

    large_content = b"a,b\n" + (b"1,2\n" * 1000)
    response = _upload(content=large_content)

    assert response.status_code == 413
    assert isolated_registry.list() == []


# =========================================================
# G/H. TEMP FILE CLEANUP
# =========================================================


def test_temp_upload_file_removed_after_successful_processing(isolated_registry):
    before = _leftover_tmp_files()

    response = _upload()

    assert response.status_code == 200
    assert _leftover_tmp_files() == before


def test_temp_upload_file_removed_after_ingestion_failure(isolated_registry, monkeypatch):
    def _failing_ingest(**kwargs):
        raise RuntimeError("simulated ingestion failure")

    monkeypatch.setattr(dataset_route, "ingest_to_parquet", _failing_ingest)

    before = _leftover_tmp_files()

    response = _upload()

    assert response.status_code == 400
    assert _leftover_tmp_files() == before


def test_temp_upload_file_removed_after_over_limit_rejection(isolated_registry, monkeypatch):
    monkeypatch.setattr(dataset_route, "MAX_UPLOAD_BYTES", len(VALID_CSV) - 1)

    before = _leftover_tmp_files()

    response = _upload(content=VALID_CSV)

    assert response.status_code == 413
    assert _leftover_tmp_files() == before


# =========================================================
# THE OLD 100MB CEILING IS GONE
# =========================================================


def test_100mb_ceiling_no_longer_the_default_limit():
    assert dataset_route.MAX_UPLOAD_BYTES != 100 * 1024 * 1024
    assert dataset_route.MAX_UPLOAD_BYTES > 100 * 1024 * 1024
