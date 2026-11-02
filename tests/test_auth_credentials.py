"""
Auth Step 1 - standalone password hashing and SQLite credential store.

Every test runs against a temporary SQLite file; AUTH_DB_PATH is
redirected for the whole module so nothing can touch data/auth.db.
"""

import base64
import os
import sqlite3
import time

import pytest

from backend.auth import passwords
from backend.auth.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    is_supported_hash,
    verify_password,
)
from backend.auth.store import (
    AUTH_DB_PATH_ENV_VAR,
    CredentialStore,
    DuplicateEmailError,
    InvalidEmailError,
    normalize_email,
)


PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def _isolated_auth_db(tmp_path, monkeypatch):
    monkeypatch.setenv(AUTH_DB_PATH_ENV_VAR, str(tmp_path / "default_auth.db"))


@pytest.fixture
def store(tmp_path):
    return CredentialStore(str(tmp_path / "auth.db"))


# =========================================================
# PASSWORD HASHING
# =========================================================


def test_hash_and_verify_round_trip():
    stored = hash_password(PASSWORD)

    assert verify_password(PASSWORD, stored) is True


def test_hash_format_is_self_describing_with_documented_parameters():
    stored = hash_password(PASSWORD)

    algorithm, params, salt_b64, key_b64 = stored.split("$")

    assert algorithm == "scrypt"
    assert params == (
        f"ln={passwords.SCRYPT_LOG2_N},r={passwords.SCRYPT_R},p={passwords.SCRYPT_P}"
    )
    assert len(base64.b64decode(salt_b64)) == 16
    assert len(base64.b64decode(key_b64)) == passwords.DERIVED_KEY_BYTES
    assert PASSWORD not in stored
    assert is_supported_hash(stored)


def test_same_password_gets_different_salts_and_hashes():
    first = hash_password(PASSWORD)
    second = hash_password(PASSWORD)

    assert first != second
    assert first.split("$")[2] != second.split("$")[2]
    assert verify_password(PASSWORD, first)
    assert verify_password(PASSWORD, second)


def test_wrong_password_is_rejected():
    stored = hash_password(PASSWORD)

    assert verify_password("correct horse battery!", stored) is False
    assert verify_password("Correct horse battery", stored) is False


def test_tampered_derived_key_is_rejected():
    stored = hash_password(PASSWORD)
    prefix, key_b64 = stored.rsplit("$", 1)
    key = bytearray(base64.b64decode(key_b64))
    key[0] ^= 0x01
    tampered = f"{prefix}${base64.b64encode(bytes(key)).decode('ascii')}"

    assert verify_password(PASSWORD, tampered) is False


@pytest.mark.parametrize(
    "stored",
    [
        None,
        123,
        b"scrypt$ln=17,r=8,p=1$AAAA$AAAA",
        "",
        "not-a-hash",
        "plaintext-password-12345",
        "bcrypt$ln=17,r=8,p=1$AAAAAAAAAAAAAAAAAAAAAA==$" + "A" * 44,
        "scrypt$ln=17,r=8$AAAAAAAAAAAAAAAAAAAAAA==$" + "A" * 44,
        "scrypt$ln=17,r=8,p=1$AAAAAAAAAAAAAAAAAAAAAA==",
        "scrypt$ln=17,r=8,p=1$!!!notbase64!!!$" + "A" * 44,
        # wrong salt / key lengths
        "scrypt$ln=17,r=8,p=1$AAAA$" + "A" * 44,
        "scrypt$ln=17,r=8,p=1$AAAAAAAAAAAAAAAAAAAAAA==$AAAA",
        # trailing junk / extra fields
        "scrypt$ln=17,r=8,p=1$AAAAAAAAAAAAAAAAAAAAAA==$" + "A" * 43 + "=$x",
    ],
)
def test_malformed_or_unsupported_hash_is_rejected_safely(stored):
    assert is_supported_hash(stored) is False
    assert verify_password(PASSWORD, stored) is False


@pytest.mark.parametrize(
    "params",
    [
        "ln=13,r=8,p=1",  # too weak to trust
        "ln=21,r=8,p=1",  # N above cap
        "ln=99,r=8,p=1",
        "ln=17,r=0,p=1",
        "ln=17,r=17,p=1",
        "ln=17,r=8,p=0",
        "ln=17,r=8,p=5",
        "ln=20,r=16,p=1",  # 2 GiB working set, above the memory cap
    ],
)
def test_out_of_bounds_stored_parameters_are_rejected_without_hashing(params):
    salt = base64.b64encode(b"\x00" * 16).decode("ascii")
    key = base64.b64encode(b"\x00" * 32).decode("ascii")
    stored = f"scrypt${params}${salt}${key}"

    started = time.perf_counter()
    assert verify_password(PASSWORD, stored) is False
    # Rejected at parse time - no expensive scrypt call was attempted.
    assert time.perf_counter() - started < 0.05


def test_password_length_boundaries():
    with pytest.raises(PasswordPolicyError):
        hash_password("a" * (MIN_PASSWORD_LENGTH - 1))

    with pytest.raises(PasswordPolicyError):
        hash_password("a" * (MAX_PASSWORD_LENGTH + 1))

    shortest = "a" * MIN_PASSWORD_LENGTH
    longest = "b" * MAX_PASSWORD_LENGTH
    assert verify_password(shortest, hash_password(shortest))
    assert verify_password(longest, hash_password(longest))


@pytest.mark.parametrize("bad", [None, 12345678901234, b"bytes-password-123"])
def test_non_string_password_is_rejected(bad):
    with pytest.raises(PasswordPolicyError):
        hash_password(bad)


def test_verify_rejects_out_of_policy_candidates_without_raising():
    stored = hash_password(PASSWORD)

    assert verify_password(None, stored) is False
    assert verify_password("short", stored) is False
    assert verify_password("x" * (MAX_PASSWORD_LENGTH + 1), stored) is False


def test_policy_error_message_does_not_echo_password():
    secret = "tiny-pw"

    with pytest.raises(PasswordPolicyError) as excinfo:
        hash_password(secret)

    assert secret not in str(excinfo.value)


# =========================================================
# EMAIL NORMALIZATION
# =========================================================


def test_normalize_email_strips_and_lowercases():
    assert normalize_email("  Alice.Smith@Example.COM \n") == "alice.smith@example.com"


@pytest.mark.parametrize(
    "bad",
    [None, "", "   ", "no-at-sign", "@example.com", "alice@", "a@b@c.com",
     "alice smith@example.com", "a" * 250 + "@x.com"],
)
def test_normalize_email_rejects_invalid(bad):
    with pytest.raises(InvalidEmailError):
        normalize_email(bad)


# =========================================================
# CREDENTIAL STORE
# =========================================================


def test_create_user_and_lookup(store):
    created = store.create_user("alice@example.com", PASSWORD)

    by_email = store.get_user_by_email("alice@example.com")
    by_id = store.get_user_by_id(created.id)

    assert by_email == created
    assert by_id == created
    assert len(created.id) == 36 and created.id.count("-") == 4
    assert created.created_at.endswith("+00:00")
    assert verify_password(PASSWORD, by_email.password_hash)


def test_lookup_of_unknown_or_invalid_user_returns_none(store):
    assert store.get_user_by_email("nobody@example.com") is None
    assert store.get_user_by_email("not an email") is None
    assert store.get_user_by_id("00000000-0000-0000-0000-000000000000") is None
    assert store.get_user_by_id("") is None


def test_email_is_normalized_for_storage_and_lookup(store):
    created = store.create_user("  Bob@Example.COM ", PASSWORD)

    assert created.email == "bob@example.com"
    assert store.get_user_by_email("BOB@example.com").id == created.id


def test_duplicate_email_is_rejected_including_case_variants(store):
    store.create_user("carol@example.com", PASSWORD)

    with pytest.raises(DuplicateEmailError):
        store.create_user("carol@example.com", "another strong password")

    with pytest.raises(DuplicateEmailError):
        store.create_user(" CAROL@Example.com", "another strong password")

    with sqlite3.connect(store.db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert count == 1


def test_invalid_input_creates_no_row(store):
    with pytest.raises(InvalidEmailError):
        store.create_user("bad email", PASSWORD)

    with pytest.raises(PasswordPolicyError):
        store.create_user("dave@example.com", "short")

    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_plaintext_password_is_never_stored(store):
    store.create_user("erin@example.com", PASSWORD)

    with open(store.db_path, "rb") as fh:
        raw = fh.read()

    assert PASSWORD.encode("utf-8") not in raw

    with sqlite3.connect(store.db_path) as connection:
        (stored,) = connection.execute("SELECT password_hash FROM users").fetchone()
    assert stored.startswith("scrypt$") and is_supported_hash(stored)


def test_user_record_repr_omits_password_hash(store):
    created = store.create_user("frank@example.com", PASSWORD)

    assert created.password_hash not in repr(created)
    assert "password_hash" not in repr(created)


def test_persistence_across_separate_store_instances(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "auth.db")

    created = CredentialStore(path).create_user("grace@example.com", PASSWORD)

    reopened = CredentialStore(path)
    found = reopened.get_user_by_email("grace@example.com")

    assert found == created
    assert verify_password(PASSWORD, found.password_hash)


def test_schema_initialization_is_idempotent(tmp_path):
    path = str(tmp_path / "auth.db")

    CredentialStore(path).create_user("heidi@example.com", PASSWORD)
    CredentialStore(path)
    CredentialStore(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_default_path_comes_from_env_var_read_at_construction(tmp_path, monkeypatch):
    configured = tmp_path / "configured.db"
    monkeypatch.setenv(AUTH_DB_PATH_ENV_VAR, str(configured))

    store = CredentialStore()

    assert store.db_path == str(configured)
    assert configured.exists()


def test_sql_metacharacters_in_email_are_treated_as_data(store):
    tricky = "o'brien\"--;@example.com"
    created = store.create_user(tricky, PASSWORD)

    assert store.get_user_by_email(tricky).id == created.id
    assert store.get_user_by_email("x' OR '1'='1@example.com") is None


def test_tests_never_touch_the_production_default_db():
    assert not os.path.exists(os.path.join("data", "auth.db"))
