from __future__ import annotations

from typing import Any

from data_engine.dataset import Dataset
from data_engine.metadata import get_metadata
from data_engine.metadata_engine.base import MetadataEngine


class PandasMetadataEngine(MetadataEngine):
    """
    Pandas-backed adapter satisfying the MetadataEngine contract.

    A thin wrapper around the existing, unmodified
    data_engine.metadata.get_metadata() baseline - it introduces no
    new metadata logic of its own, only bridges the storage contract's
    to_dataframe() compatibility boundary into the shared
    MetadataEngine.get_metadata(dataset) shape.
    """

    def get_metadata(self, dataset: Dataset) -> dict[str, Any]:
        # Strictly through the storage contract - never dataset.dataframe,
        # never an isinstance check on the concrete storage backend.
        return get_metadata(dataset.storage.to_dataframe())
