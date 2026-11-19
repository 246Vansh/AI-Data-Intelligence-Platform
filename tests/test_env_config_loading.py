"""
Regression tests: the repository .env is loaded at backend startup,
BEFORE the modules that read settings at import time.

backend/jobs.py reads ANALYSIS_JOB_WORKERS / ANALYSIS_JOB_RETENTION and
creates the shared job pool at import; backend/routes/dataset.py reads
MAX_UPLOAD_BYTES at import. Previously .env was only loaded as a side
effect of importing ai.planner - after both - so .env values for these
settings were silently ignored.

Isolation: every test copies the backend code packages into a fresh
temporary directory, writes its own .env there, and imports
backend.main in a NEW Python subprocess. That exercises the real
__file__-relative .env path in backend/main.py, keeps import caches
from leaking between tests, and never reads the developer's real .env
(the copy's own .env is the one next to the copied code).
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_PACKAGES = ("backend", "data_engine", "ai")
SETTINGS = ("ANALYSIS_JOB_WORKERS", "ANALYSIS_JOB_RETENTION", "MAX_UPLOAD_BYTES")
SENTINEL = "ENV_LOAD_ORDER_SENTINEL"

# Runs inside the subprocess. Records, at the moment backend.jobs and
# backend.routes.dataset START importing, whether a value that exists
# only in .env is already in os.environ - i.e. whether .env was loaded
# first. Then reports the values those modules initialized.
PROBE = r"""
import importlib.abc
import json
import os
import sys

WATCH = ("backend.jobs", "backend.routes.dataset")
env_loaded_at_import = {}


class OrderProbe(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name in WATCH and name not in env_loaded_at_import:
            env_loaded_at_import[name] = os.environ.get("ENV_LOAD_ORDER_SENTINEL") == "from-dotenv"
        return None


sys.meta_path.insert(0, OrderProbe())

import backend.main as main
import backend.jobs as jobs
import backend.routes.dataset as dataset

print(json.dumps({
    "env_loaded_at_import": env_loaded_at_import,
    "default_max_workers": jobs.DEFAULT_MAX_WORKERS,
    "default_max_retained_jobs": jobs.DEFAULT_MAX_RETAINED_JOBS,
    "pool_max_workers": jobs.job_manager._executor._max_workers,
    "pool_max_retained_jobs": jobs.job_manager._max_retained_jobs,
    "max_upload_bytes": dataset.MAX_UPLOAD_BYTES,
    "main_max_upload_bytes": main.MAX_UPLOAD_BYTES,
    "default_upload_bytes": dataset._DEFAULT_MAX_UPLOAD_BYTES,
}))
"""


def _run_startup(tmp_path: Path, dotenv_lines: list[str], os_env: dict[str, str] | None = None) -> dict:
    """Import backend.main from an isolated copy of the code; return the probe report."""
    app_dir = tmp_path / "app"
    for package in CODE_PACKAGES:
        shutil.copytree(
            REPO_ROOT / package,
            app_dir / package,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    (app_dir / ".env").write_text("\n".join(dotenv_lines) + "\n", encoding="utf-8")

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in SETTINGS and key != SENTINEL and key != "PYTHONPATH"
    }
    env.update(os_env or {})
    env["PYTHONPATH"] = str(app_dir)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    completed = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=app_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_dotenv_is_loaded_before_settings_modules_initialize(tmp_path):
    report = _run_startup(tmp_path, [f"{SENTINEL}=from-dotenv"])

    assert report["env_loaded_at_import"] == {
        "backend.routes.dataset": True,
        "backend.jobs": True,
    }


def test_dotenv_worker_count_retention_and_upload_limit_take_effect(tmp_path):
    report = _run_startup(
        tmp_path,
        [
            "ANALYSIS_JOB_WORKERS=3",
            "ANALYSIS_JOB_RETENTION=50",
            "MAX_UPLOAD_BYTES=1234",
        ],
    )

    assert report["default_max_workers"] == 3
    assert report["pool_max_workers"] == 3
    assert report["default_max_retained_jobs"] == 50
    assert report["pool_max_retained_jobs"] == 50
    assert report["max_upload_bytes"] == 1234
    assert report["main_max_upload_bytes"] == 1234


def test_os_environment_overrides_dotenv(tmp_path):
    report = _run_startup(
        tmp_path,
        [
            "ANALYSIS_JOB_WORKERS=3",
            "ANALYSIS_JOB_RETENTION=50",
            "MAX_UPLOAD_BYTES=1234",
        ],
        os_env={
            "ANALYSIS_JOB_WORKERS": "5",
            "ANALYSIS_JOB_RETENTION": "70",
            "MAX_UPLOAD_BYTES": "5678",
        },
    )

    assert report["pool_max_workers"] == 5
    assert report["pool_max_retained_jobs"] == 70
    assert report["max_upload_bytes"] == 5678


def test_defaults_unchanged_when_values_are_absent(tmp_path):
    report = _run_startup(tmp_path, ["# no settings configured"])

    assert report["default_max_workers"] == 2
    assert report["pool_max_workers"] == 2
    assert report["default_max_retained_jobs"] == 1000
    assert report["pool_max_retained_jobs"] == 1000
    assert report["max_upload_bytes"] == report["default_upload_bytes"] == 10 * 1024 * 1024 * 1024


@pytest.mark.parametrize("bad_value", ["0", "-4", "not-a-number"])
def test_invalid_dotenv_values_fall_back_to_defaults(tmp_path, bad_value):
    report = _run_startup(
        tmp_path,
        [
            f"ANALYSIS_JOB_WORKERS={bad_value}",
            f"ANALYSIS_JOB_RETENTION={bad_value}",
            f"MAX_UPLOAD_BYTES={bad_value}",
        ],
    )

    assert report["pool_max_workers"] == 2
    assert report["pool_max_retained_jobs"] == 1000
    assert report["max_upload_bytes"] == report["default_upload_bytes"]
