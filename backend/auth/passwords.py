"""
Auth Step 1: password hashing with the standard library's hashlib.scrypt.

Stored format (self-describing, one ASCII line):

    scrypt$ln=<log2 N>,r=<r>,p=<p>$<base64 salt>$<base64 derived key>

e.g. ``scrypt$ln=17,r=8,p=1$<24 chars>$<44 chars>``. Keeping the
parameters inside every hash lets them be raised later without breaking
hashes already stored: verification always uses the parameters the hash
was created with, never the current defaults.

Default parameters follow the OWASP Password Storage Cheat Sheet floor
for scrypt: N=2**17, r=8, p=1. Memory per hash is 128 * r * N bytes =
128 MiB, which is what makes offline GPU/ASIC cracking expensive - and
also why callers must bound how many hashes run concurrently (that is a
login-endpoint concern, not this module's).

Nothing in this module logs or echoes passwords, salts or derived keys,
and errors never include them.
"""

import base64
import binascii
import hashlib
import hmac
import re
import secrets


ALGORITHM = "scrypt"

# Explicit, documented defaults for newly created hashes.
SCRYPT_LOG2_N = 17  # N = 131072
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
DERIVED_KEY_BYTES = 32

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256

# Upper bounds on parameters accepted from a *stored* hash. The stored
# string decides how much memory/CPU verification costs, so a corrupted
# or planted hash must not be able to demand an arbitrarily expensive
# scrypt call. Lower bounds reject hashes too weak to trust.
_MIN_LOG2_N = 14
_MAX_LOG2_N = 20
_MAX_R = 16
_MAX_P = 4
_MAX_SCRYPT_MEMORY_BYTES = 256 * 1024 * 1024

_HASH_PATTERN = re.compile(
    r"^scrypt\$ln=(\d{1,2}),r=(\d{1,2}),p=(\d{1,2})\$([A-Za-z0-9+/=]+)\$([A-Za-z0-9+/=]+)$"
)


class PasswordPolicyError(ValueError):
    """The candidate password does not meet the length policy."""


def validate_password_policy(password: object) -> str:
    """
    Return `password` unchanged if it is a str of 12-256 characters,
    otherwise raise PasswordPolicyError. The message never contains the
    password itself.
    """

    if not isinstance(password, str):
        raise PasswordPolicyError("Password must be a string.")

    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be between {MIN_PASSWORD_LENGTH} and "
            f"{MAX_PASSWORD_LENGTH} characters."
        )

    return password


def _scrypt_memory_bytes(log2_n: int, r: int) -> int:
    return 128 * r * (1 << log2_n)


def _derive(password: str, salt: bytes, log2_n: int, r: int, p: int, dklen: int) -> bytes:
    # maxmem must exceed scrypt's working set or OpenSSL refuses the
    # call; double the nominal 128*r*N leaves room for its overhead.
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=1 << log2_n,
        r=r,
        p=p,
        maxmem=2 * _scrypt_memory_bytes(log2_n, r),
        dklen=dklen,
    )


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    """
    Hash `password` with a fresh random 16-byte salt and the default
    parameters, returning the self-describing stored format. Raises
    PasswordPolicyError for a password outside the length policy.
    """

    validate_password_policy(password)

    salt = secrets.token_bytes(SALT_BYTES)
    derived = _derive(password, salt, SCRYPT_LOG2_N, SCRYPT_R, SCRYPT_P, DERIVED_KEY_BYTES)

    return (
        f"{ALGORITHM}$ln={SCRYPT_LOG2_N},r={SCRYPT_R},p={SCRYPT_P}"
        f"${_b64encode(salt)}${_b64encode(derived)}"
    )


def _parse_stored_hash(stored_hash: object):
    """
    Return (log2_n, r, p, salt, derived) for a well-formed, supported
    hash, or None for anything else. Never raises.
    """

    if not isinstance(stored_hash, str):
        return None

    match = _HASH_PATTERN.match(stored_hash)
    if match is None:
        return None

    log2_n, r, p = (int(match.group(i)) for i in (1, 2, 3))

    if not (_MIN_LOG2_N <= log2_n <= _MAX_LOG2_N):
        return None
    if not (1 <= r <= _MAX_R and 1 <= p <= _MAX_P):
        return None
    if _scrypt_memory_bytes(log2_n, r) > _MAX_SCRYPT_MEMORY_BYTES:
        return None

    try:
        salt = base64.b64decode(match.group(4), validate=True)
        derived = base64.b64decode(match.group(5), validate=True)
    except (binascii.Error, ValueError):
        return None

    if len(salt) != SALT_BYTES or len(derived) != DERIVED_KEY_BYTES:
        return None

    return log2_n, r, p, salt, derived


def is_supported_hash(stored_hash: object) -> bool:
    """True if `stored_hash` is a well-formed hash this module can verify."""

    return _parse_stored_hash(stored_hash) is not None


def verify_password(password: object, stored_hash: object) -> bool:
    """
    Return True only if `password` matches `stored_hash`.

    Never raises for bad input: a non-str or out-of-policy password, or
    a malformed, unsupported or over-expensive stored hash, all return
    False. The final comparison is constant-time (hmac.compare_digest).
    """

    parsed = _parse_stored_hash(stored_hash)
    if parsed is None:
        return False

    try:
        validate_password_policy(password)
    except PasswordPolicyError:
        return False

    log2_n, r, p, salt, expected = parsed

    try:
        candidate = _derive(password, salt, log2_n, r, p, len(expected))
    except (ValueError, MemoryError):
        return False

    return hmac.compare_digest(candidate, expected)
