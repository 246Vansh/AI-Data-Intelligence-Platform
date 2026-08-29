from __future__ import annotations

import io
from pathlib import Path
from threading import Lock

import pandas as pd

from data_engine.dataset import Dataset
from data_engine.dataset_registry import (
    DatasetNotFoundError,
    DatasetRegistry,
    dataset_registry,
)
from data_engine.storage import PandasStorage


def _parse_csv_bytes(contents: bytes) -> pd.DataFrame:
    """
    Parse CSV bytes into a DataFrame.

    Tries the pyarrow engine first. If parsing fails, falls back to
    pandas' default CSV engine.
    """

    try:
        return pd.read_csv(
            io.BytesIO(contents),
            engine="pyarrow",
        )

    except Exception:
        return pd.read_csv(io.BytesIO(contents))


class DatasetManager:
    """
    Backward-compatible single-active-dataset view over DatasetRegistry.

    Dataset identity and lifecycle are owned by DatasetRegistry.

    DatasetManager only tracks which dataset is currently active and
    resolves that dataset through the registry.

    Physical dataset storage is hidden behind DatasetStorage.
    The initial implementation uses PandasStorage.
    """

    def __init__(
        self,
        registry: DatasetRegistry | None = None,
    ):
        self._registry = registry if registry is not None else dataset_registry

        self._active_id: str | None = None
        self._lock = Lock()

    def _get_active_dataset(self) -> Dataset:
        """
        Resolve the currently active dataset through the registry.
        """

        with self._lock:
            active_id = self._active_id

        if active_id is None:
            raise RuntimeError("No dataset has been loaded.")

        try:
            return self._registry.get(active_id)

        except DatasetNotFoundError as exc:
            raise RuntimeError("No dataset has been loaded.") from exc

    def register_csv_bytes(
        self,
        contents: bytes,
        filename: str | None = None,
    ) -> Dataset:
        """
        Parse CSV bytes, create a Dataset backed by PandasStorage,
        register it, and make it the active dataset.

        Returns the complete Dataset so callers can access its
        dataset_id and storage abstraction.
        """

        df = _parse_csv_bytes(contents)

        if df.empty:
            raise ValueError("The uploaded CSV dataset is empty.")

        dataset = Dataset(
            storage=PandasStorage(df),
            name=filename,
        )

        self._registry.register(dataset)

        with self._lock:
            self._active_id = dataset.dataset_id

        return dataset

    def load_csv_bytes(
        self,
        contents: bytes,
        filename: str | None = None,
    ) -> pd.DataFrame:
        """
        Parse CSV bytes, register the dataset, make it active,
        and return its DataFrame.

        This method remains for backward compatibility with existing
        DataFrame-based callers.
        """

        dataset = self.register_csv_bytes(
            contents,
            filename=filename,
        )

        return dataset.storage.to_dataframe()

    def load_csv(
        self,
        file_path: str | Path,
        filename: str | None = None,
    ) -> pd.DataFrame:
        """
        Load a CSV file from disk into the active dataset.
        """

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Dataset file does not exist: {path}")

        if path.suffix.lower() != ".csv":
            raise ValueError("Only CSV datasets are currently supported.")

        return self.load_csv_bytes(
            path.read_bytes(),
            filename=filename or path.name,
        )

    def set_dataframe(
        self,
        df: pd.DataFrame,
        filename: str | None = None,
    ) -> pd.DataFrame:
        """
        Set an already-loaded DataFrame as the active dataset.

        The DataFrame is wrapped in PandasStorage before being placed
        inside the Dataset domain object.
        """

        if not isinstance(df, pd.DataFrame):
            raise TypeError("Dataset must be a pandas DataFrame.")

        if df.empty:
            raise ValueError("The dataset is empty.")

        dataset = Dataset(
            storage=PandasStorage(df.copy()),
            name=filename,
        )

        self._registry.register(dataset)

        with self._lock:
            self._active_id = dataset.dataset_id

        return dataset.storage.to_dataframe()

    def get_dataframe(self) -> pd.DataFrame:
        """
        Return the currently loaded dataset as a DataFrame.

        This is the compatibility boundary for existing DataFrame-based
        application components.
        """

        return self._get_active_dataset().storage.to_dataframe()

    def get_filename(self) -> str | None:
        """
        Return the name of the currently loaded dataset.
        """

        with self._lock:
            active_id = self._active_id

        if active_id is None:
            return None

        try:
            return self._registry.get(active_id).name

        except DatasetNotFoundError:
            return None

    def is_loaded(self) -> bool:
        """
        Check whether a dataset is currently available.
        """

        with self._lock:
            active_id = self._active_id

        return active_id is not None and self._registry.exists(active_id)

    def clear(self) -> None:
        """
        Remove the currently active dataset.

        The dataset is removed from the registry as well.
        """

        with self._lock:
            active_id = self._active_id
            self._active_id = None

        if active_id is not None and self._registry.exists(active_id):
            self._registry.delete(active_id)

    def clear_dataset(self, dataset_id: str) -> None:
        """
        Clear the active-dataset pointer if it currently points at
        dataset_id; otherwise do nothing.

        Unlike clear(), this never touches the registry itself - it
        only exists to keep DatasetManager from pointing at a dataset
        that a caller (e.g. the delete endpoint) is removing from the
        registry through some other path.
        """

        with self._lock:
            if self._active_id == dataset_id:
                self._active_id = None

    def get_cached(
        self,
        key: str,
        builder,
    ):
        """
        Return a cached computation for the active dataset.
        """

        return get_cached_on(
            self._get_active_dataset(),
            key,
            builder,
        )


def get_cached_on(
    dataset: Dataset,
    key: str,
    builder,
):
    """
    Return a cached computation for a specific Dataset.

    The builder receives the DataFrame materialized through the
    DatasetStorage abstraction.
    """

    if key in dataset.cache:
        return dataset.cache[key]

    value = builder(dataset.storage.to_dataframe())

    dataset.cache[key] = value

    return value


dataset_manager = DatasetManager()
