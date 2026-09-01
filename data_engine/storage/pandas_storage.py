from __future__ import annotations

import pandas as pd

from data_engine.storage.base import DatasetStorage


class PandasStorage(DatasetStorage):
    """
    Initial in-memory storage implementation backed by Pandas.

    This class intentionally contains the current DataFrame storage
    behavior behind the DatasetStorage contract.

    It is an implementation detail of the storage layer. Future
    storage implementations can replace it without changing the
    Dataset identity/lifecycle model.
    """

    def __init__(self, dataframe: pd.DataFrame):
        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError("dataframe must be a pandas DataFrame.")

        if dataframe.empty:
            raise ValueError("The dataset is empty.")

        self._dataframe = dataframe

    def to_dataframe(self) -> pd.DataFrame:
        """
        Return the currently stored DataFrame.

        The existing application is DataFrame-based, so this method
        intentionally provides a compatibility boundary during the
        migration.
        """
        return self._dataframe

    def row_count(self) -> int:
        return len(self._dataframe)

    def column_count(self) -> int:
        return len(self._dataframe.columns)

    def column_names(self) -> list[str]:
        return self._dataframe.columns.tolist()

    def close(self) -> None:
        """
        Safe no-op.

        PandasStorage holds no closeable resource - no open
        connection, no file handle - just a DataFrame reference, which
        Python's own garbage collector reclaims once nothing
        references this instance anymore. Present only to satisfy the
        DatasetStorage lifecycle contract.
        """
        pass
