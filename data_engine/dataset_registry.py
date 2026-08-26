from __future__ import annotations

from threading import Lock

from data_engine.dataset import Dataset


class DatasetNotFoundError(LookupError):
    """
    Raised when a dataset_id has no corresponding Dataset in the
    registry (never registered, or already deleted).

    A plain, framework-free exception on purpose - this is a domain
    error, not an HTTP concern. Callers at the API layer translate it
    into whatever response shape they need (e.g. a 404) rather than
    this module knowing anything about FastAPI.
    """

    def __init__(self, dataset_id: str):
        self.dataset_id = dataset_id
        super().__init__(f"No dataset found for dataset_id: {dataset_id!r}")


class DatasetRegistry:
    """
    In-memory catalog of Dataset instances, keyed by dataset_id.

    This is a deliberate intermediate architecture: a plain
    dict-backed registry today, standing in for a persistent
    catalog/database later. It knows nothing about HTTP/FastAPI, the
    frontend, AI, query/analysis logic, Pandas-specific business
    rules, or any particular dataset's shape (Walmart or otherwise) -
    it only stores and retrieves opaque Dataset objects by id. That's
    what keeps it swappable for a real catalog without any caller
    needing to change.
    """

    def __init__(self):
        self._datasets: dict[str, Dataset] = {}
        self._lock = Lock()

    def register(self, dataset: Dataset) -> str:
        """
        Add a Dataset to the registry (or replace the entry for its
        dataset_id if one already exists). Returns the dataset_id for
        convenience.

        The registry does not generate ids itself - Dataset already
        assigns its own UUID on construction. This just files it
        under that id.
        """

        with self._lock:
            self._datasets[dataset.dataset_id] = dataset

        return dataset.dataset_id

    def get(self, dataset_id: str) -> Dataset:
        """
        Return the Dataset registered under dataset_id.

        Raises DatasetNotFoundError - a clear, controlled error -
        rather than a bare KeyError or returning None, so callers
        never have to guess whether "None" meant "not found" or "a
        dataset that happens to be falsy".
        """

        with self._lock:
            dataset = self._datasets.get(dataset_id)

        if dataset is None:
            raise DatasetNotFoundError(dataset_id)

        return dataset

    def exists(self, dataset_id: str) -> bool:
        """
        Check whether dataset_id is currently registered.
        """

        with self._lock:
            return dataset_id in self._datasets

    def delete(self, dataset_id: str) -> None:
        """
        Remove dataset_id from the registry.

        Raises DatasetNotFoundError if it isn't registered, for the
        same "clear, controlled error" reason as get(): deleting
        something that was never there is surfaced, not silently
        ignored. A caller that wants idempotent-delete semantics can
        guard with exists() first.
        """

        with self._lock:
            if dataset_id not in self._datasets:
                raise DatasetNotFoundError(dataset_id)

            del self._datasets[dataset_id]

    def list(self) -> list[Dataset]:
        """
        Return every currently registered Dataset.

        Returns a new list each call - a snapshot, not a live view -
        so a caller can never mutate the registry's own bookkeeping
        by holding onto what this returns (append/remove/clear on the
        result has no effect on the registry itself).
        """

        with self._lock:
            return list(self._datasets.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._datasets)


# Shared, process-wide registry. DatasetManager (data_engine/dataset_manager.py)
# routes through this by default, so every dataset it makes active is
# also discoverable here by id - the first step toward multi-dataset
# support, without yet changing single-dataset callers' behavior.
dataset_registry = DatasetRegistry()
