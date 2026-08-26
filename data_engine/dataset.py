from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd


@dataclass(eq=False)
class Dataset:
    """
    Domain representation of a single loaded dataset: its identity
    and lifecycle metadata.

    This is a plain data holder, not a service. It deliberately knows
    nothing about HTTP/FastAPI, the frontend, AI planning, query
    execution, visualization, or any specific dataset's business
    columns (Walmart or otherwise) - callers own all of that. Keeping
    it dependency-free here is what lets a later migration phase
    introduce multi-dataset support (a registry of these) and,
    eventually, a storage/execution abstraction, without this class
    needing to change.

    `eq=False`: dataclass-generated equality would compare every
    field, including `dataframe` - comparing two DataFrames with `==`
    doesn't return a bool, so default equality would raise on the
    very first `dataset_a == dataset_b`. Falls back to identity
    (`is`) comparison, which is the correct semantics here anyway:
    two Dataset instances are never "the same dataset" just because
    their contents happen to match. Use `.dataset_id` to compare
    identity by value instead.
    """

    # The dataset's contents, as loaded by the current (pandas,
    # in-memory) execution engine. TEMPORARY: a later migration phase
    # replaces this with a storage/execution abstraction so Dataset
    # no longer holds pandas directly. Nothing outside DatasetManager
    # should assume this field's shape survives that phase.
    dataframe: pd.DataFrame

    # Original filename, or any other human-readable label a caller
    # wants attached. Optional - a Dataset can exist without one.
    name: str | None = None

    # Globally-unique, assigned once at construction and never
    # reassigned. Used as this dataset's identity for the lifetime of
    # the process (and, once a registry exists, as its lookup key).
    dataset_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # When this Dataset object was created (UTC). Not "when the file
    # was uploaded" in any external sense - just this object's
    # lifecycle start, which today happens to be the same moment.
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Per-dataset memoized computations (metadata/profile/quality/
    # plan cache, etc.). Dataset itself is opaque to what's stored
    # here - callers decide the keys and values. Exists so each
    # dataset owns its own cache rather than sharing one process-wide
    # cache, which is what makes multiple simultaneously-loaded
    # datasets safe in a later phase.
    cache: dict = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.dataframe)

    @property
    def column_count(self) -> int:
        return len(self.dataframe.columns)
