from contextlib import contextmanager
from time import perf_counter


@contextmanager
def measure(label: str, timings: dict):
    start = perf_counter()

    try:
        yield

    finally:
        elapsed_ms = (perf_counter() - start) * 1000
        timings[label] = round(elapsed_ms, 2)
