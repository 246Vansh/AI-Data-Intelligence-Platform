from __future__ import annotations

from typing import Any

from data_engine.data_quality import check_data_quality
from data_engine.dataset import Dataset
from data_engine.quality.base import QualityEngine


class PandasQualityEngine(QualityEngine):
    """
    Pandas-backed adapter satisfying the QualityEngine contract.

    A thin wrapper around the existing, unmodified
    data_engine.data_quality.check_data_quality() baseline - it
    introduces no new quality-check logic of its own, only bridges the
    storage contract's to_dataframe() compatibility boundary into the
    shared QualityEngine.check_quality(dataset) shape.
    """

    def check_quality(self, dataset: Dataset) -> dict[str, Any]:
        # Strictly through the storage contract - never dataset.dataframe,
        # never an isinstance check on the concrete storage backend.
        return check_data_quality(dataset.storage.to_dataframe())
