import pytest

from server.config import ServerSettings


def test_production_requires_authenticated_redis_url() -> None:
    settings = {
        "app_env": "production",
        "secret_key": "a" * 32,
        "database_url": "postgresql+psycopg://learning:secure-password@postgres/learning",
        "object_storage_endpoint": "http://minio:9000",
        "object_storage_access_key": "storage-key",
        "object_storage_secret_key": "storage-secret",
        "cors_origins": "https://app.example.com",
        "redis_password": "redis-secret-value-123",
    }
    with pytest.raises(ValueError, match="REDIS_URL"):
        ServerSettings(**settings)
    settings["redis_url"] = "redis://:different-secret@redis:6379/0"
    with pytest.raises(ValueError, match="must match"):
        ServerSettings(**settings)
    settings["redis_url"] = "redis://:redis-secret-value-123@redis:6379/0"
    assert ServerSettings(**settings).redis_password == "redis-secret-value-123"
    settings["redis_password"] = "bad@redis-password-value"
    settings["redis_url"] = "redis://:bad%40redis-password-value@redis:6379/0"
    with pytest.raises(ValueError, match="URL-safe"):
        ServerSettings(**settings)
from server.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hash_round_trip() -> None:
    encoded = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", encoded)
    assert not verify_password("wrong-password", encoded)


def test_access_token_contains_user_and_tenant() -> None:
    settings = ServerSettings(secret_key="a" * 32)
    token = create_access_token(user_id="user-1", organization_id="tenant-1", settings=settings)
    assert decode_access_token(token, settings)["tenant_id"] == "tenant-1"


def test_production_rejects_default_secret() -> None:
    try:
        ServerSettings(app_env="production")
    except ValueError as exc:
        assert "SECRET_KEY" in str(exc)
    else:
        raise AssertionError("production must reject the default secret")


def test_production_requires_object_storage_credentials() -> None:
    try:
        ServerSettings(app_env="production", secret_key="a" * 32, database_url="postgresql+psycopg://user:password@host/database")
    except ValueError as exc:
        assert "object storage" in str(exc)
    else:
        raise AssertionError("production must require object storage")


def test_production_rejects_wildcard_cors_origin() -> None:
    try:
        ServerSettings(
            app_env="production",
            secret_key="a" * 32,
            database_url="postgresql+psycopg://user:password@host/database",
            object_storage_endpoint="https://storage.example.test",
            object_storage_access_key="access",
            object_storage_secret_key="secret",
            cors_origins="*",
            redis_password="redis-secret-value-123",
            redis_url="redis://:redis-secret-value-123@redis:6379/0",
        )
    except ValueError as exc:
        assert "CORS" in str(exc)
    else:
        raise AssertionError("production must reject wildcard CORS")


def test_cors_origin_list_strips_whitespace_and_trailing_slashes() -> None:
    settings = ServerSettings(cors_origins=" http://localhost:3000/ , https://app.example.test ")
    assert settings.cors_origin_list == ["http://localhost:3000", "https://app.example.test"]
