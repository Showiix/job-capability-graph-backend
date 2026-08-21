from app.core.security import (
    constant_time_equal,
    hash_password,
    new_token,
    token_digest,
    verify_password,
)


def test_password_hash_is_argon2_and_verifies_only_correct_password() -> None:
    encoded = hash_password("correct-password")

    assert encoded.startswith("$argon2id$")
    assert verify_password("correct-password", encoded)
    assert not verify_password("wrong-password", encoded)


def test_token_digest_is_stable_and_does_not_store_plaintext() -> None:
    token = new_token()
    digest = token_digest(token, "test-secret-at-least-32-characters")

    assert len(token) >= 32
    assert len(digest) == 64
    assert token not in digest
    assert constant_time_equal(
        digest,
        token_digest(token, "test-secret-at-least-32-characters"),
    )
