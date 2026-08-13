from server.security import create_refresh_token, hash_refresh_token


def test_refresh_tokens_are_random_and_hashed() -> None:
    raw, digest = create_refresh_token()
    assert raw != digest
    assert hash_refresh_token(raw) == digest
