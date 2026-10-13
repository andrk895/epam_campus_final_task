"""Unit tests for password hashing and JWT access tokens (``app.core.security``)."""

import base64
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal

import jwt
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.security import (
    MAX_USER_ID,
    InvalidTokenError,
    TokenPayload,
    create_access_token,
    decode_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)

SECRET = "unit-test-secret-that-is-long-enough-for-hs512-" + "x" * 32
OTHER_SECRET = "another-secret-that-is-also-long-enough-for-hs512-" + "y" * 32

Algorithm = Literal["HS256", "HS384", "HS512"]


def make_settings(
    *, secret: str = SECRET, algorithm: Algorithm = "HS256", expire_minutes: int = 60
) -> Settings:
    """Settings built only from the arguments (the `.env` file is ignored)."""
    values: dict[str, Any] = {
        "jwt_secret": SecretStr(secret),
        "jwt_algorithm": algorithm,
        "jwt_expire_minutes": expire_minutes,
        "_env_file": None,
    }
    return Settings(**values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_json(value: object) -> str:
    return b64url(json.dumps(value, separators=(",", ":")).encode())


def b64url_decode_json(segment: str) -> Any:
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def sign(claims: dict[str, Any], *, secret: str = SECRET, algorithm: str = "HS256") -> str:
    """Encode arbitrary claims directly with PyJWT (bypassing ``create_access_token``)."""
    return jwt.encode(claims, secret, algorithm=algorithm)


def valid_claims(**overrides: Any) -> dict[str, Any]:
    now = int(datetime.now(UTC).timestamp())
    return {"sub": "42", "iat": now, "exp": now + 3600, **overrides}


# ---------------------------------------------------------------- passwords


def test_hash_password_verifies_with_the_correct_password() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", password_hash) is True


def test_verify_password_rejects_a_wrong_password() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery stapl", password_hash) is False
    assert verify_password("Correct horse battery staple", password_hash) is False
    assert verify_password("", password_hash) is False


def test_hash_password_uses_argon2_and_never_stores_the_plain_password() -> None:
    password_hash = hash_password("s3cret-password")

    assert password_hash.startswith("$argon2id$")
    assert "s3cret-password" not in password_hash


def test_hashes_are_salted_and_unique() -> None:
    first = hash_password("same password")
    second = hash_password("same password")

    assert first != second
    assert verify_password("same password", first)
    assert verify_password("same password", second)


def test_unicode_passwords_round_trip() -> None:
    password_hash = hash_password("jelszó-パスワード-🔑")

    assert verify_password("jelszó-パスワード-🔑", password_hash)
    assert not verify_password("jelszo-パスワード-🔑", password_hash)


@pytest.mark.parametrize(
    "stored_hash",
    [
        "",
        "not-a-hash",
        "$2b$12$abcdefghijklmnopqrstuuJ8lZ6XrLzYt1Hc5bD3kTq0lV0p6m7yW",  # bcrypt-shaped
        "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$broken",
    ],
)
def test_verify_password_with_an_invalid_stored_hash_returns_false(stored_hash: str) -> None:
    assert verify_password("anything", stored_hash) is False


def test_password_needs_rehash() -> None:
    assert password_needs_rehash(hash_password("pw")) is False
    # Weaker (older) argon2 parameters, or something that is not an argon2 hash at all.
    weak = "$argon2id$v=19$m=8,t=1,p=1$c29tZXNhbHQ$Yr2Bc1fC2KBgeVZz1V1ZhQ"
    assert password_needs_rehash(weak) is True
    assert password_needs_rehash("not-a-hash") is True
    assert password_needs_rehash("$argon2id$v=19$m=x,t=1,p=1$c2FsdA$aGFzaA") is True
    # Looks like argon2 (parameters but no salt/digest), yet argon2 itself cannot parse it.
    assert password_needs_rehash("$argon2id$v=19$m=65536,t=3,p=4") is True


# ---------------------------------------------------------------- access tokens: valid


def test_valid_token_round_trips(settings: Settings) -> None:
    before = datetime.now(UTC).replace(microsecond=0)
    token = create_access_token(42, settings)
    after = datetime.now(UTC)

    payload = decode_token(token, settings)

    assert isinstance(payload, TokenPayload)
    assert payload.user_id == 42
    assert before <= payload.issued_at <= after
    assert payload.expires_at - payload.issued_at == timedelta(hours=1)
    assert payload.issued_at.tzinfo is not None


def test_token_claims_are_sub_iat_exp_and_header_uses_configured_algorithm(
    settings: Settings,
) -> None:
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    token = create_access_token(7, settings, now=now)

    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, options={"verify_signature": False})

    assert header["alg"] == "HS256"
    assert claims == {
        "sub": "7",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 3600,
    }


def test_expiry_follows_jwt_expire_minutes() -> None:
    settings = make_settings(expire_minutes=5)
    payload = decode_token(create_access_token(1, settings), settings)

    assert payload.expires_at - payload.issued_at == timedelta(minutes=5)


@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512"])
def test_each_supported_algorithm_round_trips(algorithm: Algorithm) -> None:
    settings = make_settings(algorithm=algorithm)
    token = create_access_token(MAX_USER_ID, settings)

    assert jwt.get_unverified_header(token)["alg"] == algorithm
    assert decode_token(token, settings).user_id == MAX_USER_ID


def test_token_issued_almost_an_hour_ago_is_still_valid(settings: Settings) -> None:
    now = datetime.now(UTC) - timedelta(minutes=59)
    token = create_access_token(5, settings, now=now)

    assert decode_token(token, settings).user_id == 5


def test_create_access_token_accepts_a_non_utc_aware_now(settings: Settings) -> None:
    budapest_summer = datetime.now(UTC).astimezone(timezone(timedelta(hours=2)))
    payload = decode_token(create_access_token(3, settings, now=budapest_summer), settings)

    assert payload.issued_at == budapest_summer.replace(microsecond=0)


@pytest.mark.parametrize("user_id", [0, -1, MAX_USER_ID + 1, True])
def test_create_access_token_rejects_invalid_user_ids(settings: Settings, user_id: int) -> None:
    with pytest.raises(ValueError, match="user_id"):
        create_access_token(user_id, settings)


def test_create_access_token_rejects_a_naive_now(settings: Settings) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        create_access_token(1, settings, now=datetime(2026, 1, 1))


# ---------------------------------------------------------------- access tokens: rejected


def test_expired_token_is_rejected(settings: Settings) -> None:
    issued = datetime.now(UTC) - timedelta(minutes=61)
    token = create_access_token(42, settings, now=issued)

    with pytest.raises(InvalidTokenError, match="expired"):
        decode_token(token, settings)


def test_short_expiry_token_is_rejected_once_expired() -> None:
    settings = make_settings(expire_minutes=1)
    token = create_access_token(42, settings, now=datetime.now(UTC) - timedelta(seconds=61))

    with pytest.raises(InvalidTokenError):
        decode_token(token, settings)


def test_token_issued_in_the_future_is_rejected(settings: Settings) -> None:
    token = create_access_token(42, settings, now=datetime.now(UTC) + timedelta(minutes=10))

    with pytest.raises(InvalidTokenError):
        decode_token(token, settings)


def test_tampered_payload_is_rejected(settings: Settings) -> None:
    header, payload, signature = create_access_token(42, settings).split(".")
    claims = b64url_decode_json(payload)
    claims["sub"] = "1"  # try to become another user, keeping the original signature
    forged = f"{header}.{b64url_json(claims)}.{signature}"

    with pytest.raises(InvalidTokenError, match="Signature verification failed"):
        decode_token(forged, settings)


def test_tampered_signature_is_rejected(settings: Settings) -> None:
    header, payload, signature = create_access_token(42, settings).split(".")
    raw = bytearray(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)))
    raw[0] ^= 0x01
    forged = f"{header}.{payload}.{b64url(bytes(raw))}"

    with pytest.raises(InvalidTokenError, match="Signature verification failed"):
        decode_token(forged, settings)


def test_token_signed_with_another_secret_is_rejected(settings: Settings) -> None:
    token = create_access_token(42, make_settings(secret=OTHER_SECRET))

    with pytest.raises(InvalidTokenError, match="Signature verification failed"):
        decode_token(token, settings)


def test_alg_none_token_is_rejected(settings: Settings) -> None:
    unsigned = jwt.encode(valid_claims(), None, algorithm="none")
    handmade = f"{b64url_json({'alg': 'none', 'typ': 'JWT'})}.{b64url_json(valid_claims())}."

    for token in (unsigned, handmade):
        with pytest.raises(InvalidTokenError, match="alg value is not allowed"):
            decode_token(token, settings)


@pytest.mark.parametrize("algorithm", ["HS384", "HS512"])
def test_token_with_another_algorithm_is_rejected(settings: Settings, algorithm: str) -> None:
    # Same secret, but not the configured algorithm (HS256): no algorithm substitution.
    token = sign(valid_claims(), algorithm=algorithm)

    with pytest.raises(InvalidTokenError, match="alg value is not allowed"):
        decode_token(token, settings)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-jwt",
        "a.b.c",
        "a.b",
        "....",
        "Bearer abc",
        f"{b64url(b'[1,2]')}.{b64url_json(valid_claims())}.sig",
        f"{b64url_json({'alg': 'HS256'})}.{b64url(b'[1,2]')}.sig",
        "ű.ő.ü",
    ],
)
def test_malformed_token_is_rejected(settings: Settings, token: str) -> None:
    with pytest.raises(InvalidTokenError):
        decode_token(token, settings)


@pytest.mark.parametrize("missing", ["sub", "iat", "exp"])
def test_token_missing_a_required_claim_is_rejected(settings: Settings, missing: str) -> None:
    claims = valid_claims()
    del claims[missing]

    with pytest.raises(InvalidTokenError, match=missing):
        decode_token(sign(claims), settings)


@pytest.mark.parametrize(
    "sub",
    [42, None, "", "0", "-1", "+1", "01", " 1", "1 ", "1.0", "abc", "\u0661", str(MAX_USER_ID + 1)],
)
def test_token_with_an_invalid_sub_is_rejected(settings: Settings, sub: object) -> None:
    with pytest.raises(InvalidTokenError):
        decode_token(sign(valid_claims(sub=sub)), settings)


@pytest.mark.parametrize(
    "overrides",
    [
        {"iat": "1700000000"},
        {"exp": str(int(datetime.now(UTC).timestamp()) + 3600)},
        {"exp": int(datetime.now(UTC).timestamp()) + 3600.5},
        {"iat": None},
        {"exp": 10**15},
    ],
)
def test_token_with_invalid_iat_or_exp_is_rejected(
    settings: Settings, overrides: dict[str, Any]
) -> None:
    with pytest.raises(InvalidTokenError):
        decode_token(sign(valid_claims(**overrides)), settings)


def test_invalid_token_error_is_the_only_exception_and_chains_the_cause(
    settings: Settings,
) -> None:
    with pytest.raises(InvalidTokenError) as exc_info:
        decode_token("not-a-jwt", settings)

    assert isinstance(exc_info.value.__cause__, jwt.PyJWTError)
    assert not isinstance(exc_info.value, jwt.PyJWTError)
