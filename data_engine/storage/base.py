from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class DatasetStorage(ABC):
    """
    Abstract storage contract for a dataset.

    The rest of the application should depend on this contract rather
    than knowing how or where the dataset is physically stored.

    The initial implementation is Pandas-backed. Later implementations
    may use Parquet, DuckDB, object storage, or another execution/storage
    system without changing the Dataset domain model.
    """

    @abstractmethod
    def to_dataframe(self) -> pd.DataFrame:
        """
        Materialize the dataset as a Pandas DataFrame.

        This is currently the compatibility boundary for existing
        DataFrame-based application components.
        """
        raise NotImplementedError

    @abstractmethod
    def row_count(self) -> int:
        """Return the number of rows in the dataset."""
        raise NotImplementedError

    @abstractmethod
    def column_count(self) -> int:
        """Return the number of columns in the dataset."""
        raise NotImplementedError

    @abstractmethod
    def column_names(self) -> list[str]:
        """Return the dataset's column names."""
        raise NotImplementedError
