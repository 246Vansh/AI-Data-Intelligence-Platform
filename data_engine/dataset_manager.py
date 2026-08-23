from __future__ import annotations

from pathlib import Path
from threading import Lock

import pandas as pd


class DatasetManager:
    """
    Stores and provides access to the currently loaded dataset.

    The manager is dataset-agnostic. It does not know whether the
    dataset is retail, finance, healthcare, marketing, etc.
    """

    def __init__(self):
        self._dataframe: pd.DataFrame | None = None
        self._filename: str | None = None
        self._lock = Lock()

        # Per-dataset computation cache (metadata, profile,
        # quality, parsed time columns). Cleared whenever a
        # new dataset is loaded.
        self._cache: dict = {}

    def load_csv(
        self,
        file_path: str | Path,
        filename: str | None = None,
    ) -> pd.DataFrame:
        """
        Load a CSV file into the active dataset.
        """

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Dataset file does not exist: {path}")

        if path.suffix.lower() != ".csv":
            raise ValueError("Only CSV datasets are currently supported.")

        df = pd.read_csv(path)

        if df.empty:
            raise ValueError("The uploaded CSV dataset is empty.")

        with self._lock:
            self._dataframe = df
            self._filename = filename or path.name
            self._cache = {}

        return df

    def set_dataframe(
        self,
        df: pd.DataFrame,
        filename: str | None = None,
    ) -> pd.DataFrame:
        """
        Set an already-loaded DataFrame as the active dataset.
        """

        if not isinstance(df, pd.DataFrame):
            raise TypeError("Dataset must be a pandas DataFrame.")

        if df.empty:
            raise ValueError("The dataset is empty.")

        with self._lock:
            self._dataframe = df.copy()
            self._filename = filename
            self._cache = {}

        return self._dataframe

    def get_dataframe(self) -> pd.DataFrame:
        """
        Return the currently loaded dataset.
        """

        with self._lock:
            if self._dataframe is None:
                raise RuntimeError("No dataset has been loaded.")

            return self._dataframe

    def get_filename(self) -> str | None:
        """
        Return the name of the currently loaded dataset.
        """

        with self._lock:
            return self._filename

    def is_loaded(self) -> bool:
        """
        Check whether a dataset is currently loaded.
        """

        with self._lock:
            return self._dataframe is not None

    def clear(self) -> None:
        """
        Remove the currently loaded dataset.
        """

        with self._lock:
            self._dataframe = None
            self._filename = None
            self._cache = {}

    def get_cached(self, key: str, builder):
        """
        Return a cached per-dataset computation, building it
        on first access. The builder receives the active
        DataFrame. Cache is invalidated automatically when a
        new dataset is loaded.
        """

        with self._lock:
            if self._dataframe is None:
                raise RuntimeError("No dataset has been loaded.")

            if key in self._cache:
                return self._cache[key]

            df = self._dataframe

        # Build outside the lock so slow computations do not
        # block other readers.
        value = builder(df)

        with self._lock:
            # Only store if the dataset was not swapped
            # while we were computing.
            if self._dataframe is df:
                self._cache[key] = value

        return value


dataset_manager = DatasetManager()
