from pathlib import Path

import pandas as pd


class DatasetLoadError(Exception):
    """Raised when a dataset cannot be loaded."""


def load_csv(
    path: str | Path,
) -> pd.DataFrame:

    dataset_path = Path(path)

    if not dataset_path.exists():
        raise DatasetLoadError(f"Dataset not found: {dataset_path}")

    if not dataset_path.is_file():
        raise DatasetLoadError(f"Dataset path is not a file: {dataset_path}")

    if dataset_path.suffix.lower() != ".csv":
        raise DatasetLoadError("Only CSV datasets are currently supported.")

    try:
        df = pd.read_csv(dataset_path)

    except Exception as exc:
        raise DatasetLoadError(f"Failed to load dataset: {exc}") from exc

    if df.empty:
        raise DatasetLoadError("Dataset is empty.")

    return df
