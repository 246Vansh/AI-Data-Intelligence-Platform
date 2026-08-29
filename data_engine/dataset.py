from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from data_engine.storage import DatasetStorage


@dataclass(eq=False)
class Dataset:
    """
    Domain representation of a single loaded dataset.

    Dataset owns dataset identity and lifecycle metadata. It does not
    know how the dataset is physically stored or executed.

    Dataset contents are accessed through the DatasetStorage abstraction.
    The current implementation is PandasStorage, but Dataset itself
    remains independent of Pandas and any specific storage technology.

    `eq=False`: Dataset identity is object-based rather than based on
    comparing every field. Use `.dataset_id` when value-based dataset
    identity is required.
    """

    # Storage abstraction containing the dataset contents.
    #
    # Dataset deliberately depends on the interface rather than on a
    # concrete implementation such as PandasStorage.
    storage: DatasetStorage

    # Original filename, or any other human-readable label a caller
    # wants attached.
    name: str | None = None

    # Globally unique dataset identity.
    dataset_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # When this Dataset object was created (UTC).
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Per-dataset memoized computations.
    #
    # Examples:
    #   profile
    #   metadata
    #   quality
    #   analysis plans
    #
    # The Dataset does not interpret these values.
    cache: dict = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        """
        Return the number of rows in the dataset.
        """

        return self.storage.row_count()

    @property
    def column_count(self) -> int:
        """
        Return the number of columns in the dataset.
        """

        return self.storage.column_count()

    @property
    def column_names(self) -> list[str]:
        """
        Return the dataset's column names.
        """

        return self.storage.column_names()
