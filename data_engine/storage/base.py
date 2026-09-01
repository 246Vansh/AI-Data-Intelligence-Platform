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

    @abstractmethod
    def close(self) -> None:
        """
        Release any resources held by this storage instance (e.g. an
        open database connection, file handles).

        Called once, when this storage is no longer needed - e.g.
        when its owning Dataset is removed from the registry. After
        close() returns, this instance should no longer be used.

        Implementations that hold no closeable resources (e.g. a
        pure in-memory DataFrame) provide a safe no-op.
        """
        raise NotImplementedError

    @property
    def artifact_path(self) -> str | None:
        """
        Filesystem path of this storage's persistent on-disk artifact
        (e.g. a Parquet file backing it), if it has one.

        A minimal, storage-agnostic primitive: callers that need to
        clean up a dataset's on-disk footprint (e.g. dataset deletion)
        can go through this instead of knowing which concrete storage
        backend - or whether it is backed by a file at all - they are
        talking to.

        Defaults to None (no on-disk artifact). Concrete
        implementations override it where relevant; not abstract
        because "no artifact" is a perfectly valid answer, not a
        missing implementation.
        """
        return None
