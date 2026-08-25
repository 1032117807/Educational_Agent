import pytest

from server.config import ServerSettings
from scripts.validate_production_env import validate
from scripts.backup_saas import create_backup
from scripts.restore_saas import restore_backup
from scripts.postgres_urls import postgres_client_url


def test_saas_runtime_includes_postgresql_client_for_recovery_drills() -> None:
    dockerfile = open("docker/saas/Dockerfile", encoding="utf-8").read()
    assert "postgresql-client-16" in dockerfile


def test_postgresql_client_url_removes_sqlalchemy_driver_name() -> None:
    assert postgres_client_url("postgresql+psycopg://owner:secret@db:5432/learning") == "postgresql://owner:secret@db:5432/learning"
    assert postgres_client_url("postgresql://owner:secret@db/learning") == "postgresql://owner:secret@db/learning"


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


def test_production_rejects_placeholder_credentials() -> None:
    settings = {
        "app_env": "production",
        "secret_key": "replace-with-a-long-random-secret-value",
        "database_url": "postgresql+psycopg://learning:replace-with-a-runtime-password@postgres/learning",
        "object_storage_endpoint": "https://storage.example.test",
        "object_storage_access_key": "storage-key",
        "object_storage_secret_key": "replace-with-a-long-minio-password",
        "cors_origins": "https://app.example.test",
        "redis_password": "redis-secret-value-123",
        "redis_url": "redis://:redis-secret-value-123@redis:6379/0",
    }
    with pytest.raises(ValueError, match="SECRET_KEY"):
        ServerSettings(**settings)
    settings["secret_key"] = "a" * 32
    with pytest.raises(ValueError, match="DATABASE_URL"):
        ServerSettings(**settings)
    settings["database_url"] = "postgresql+psycopg://learning:real-password@postgres/learning"
    with pytest.raises(ValueError, match="object storage"):
        ServerSettings(**settings)


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


@pytest.mark.parametrize("cors_origins", ("", "http://learn.example.com", "https://localhost:3000"))
def test_production_rejects_missing_or_non_public_https_cors(cors_origins: str) -> None:
    with pytest.raises(ValueError, match="CORS"):
        ServerSettings(
            app_env="production",
            secret_key="a" * 32,
            database_url="postgresql+psycopg://user:password@host/database",
            object_storage_endpoint="https://storage.example.test",
            object_storage_access_key="access",
            object_storage_secret_key="secret",
            cors_origins=cors_origins,
            redis_password="redis-secret-value-123",
            redis_url="redis://:redis-secret-value-123@redis:6379/0",
        )


def test_cors_origin_list_strips_whitespace_and_trailing_slashes() -> None:
    settings = ServerSettings(cors_origins=" http://localhost:3000/ , https://app.example.test ")
    assert settings.cors_origin_list == ["http://localhost:3000", "https://app.example.test"]


def test_web_coding_is_disabled_by_default() -> None:
    assert ServerSettings(secret_key="a" * 32).web_coding_enabled is False


def test_web_coding_can_be_explicitly_enabled() -> None:
    assert ServerSettings(secret_key="a" * 32, web_coding_enabled=True).web_coding_enabled is True


def test_production_environment_preflight_accepts_complete_values() -> None:
    values = {
        "APP_ENV": "production", "SECRET_KEY": "s" * 40,
        "POSTGRES_PASSWORD": "owner-password", "APP_DB_PASSWORD": "runtime-password",
        "REDIS_PASSWORD": "redis-password-1234", "REDIS_URL": "redis://:redis-password-1234@redis:6379/0",
        "DATABASE_URL": "postgresql+psycopg://learning_app:runtime-password@postgres:5432/learning",
        "OBJECT_STORAGE_ACCESS_KEY": "storage-access", "OBJECT_STORAGE_SECRET_KEY": "storage-secret",
        "CORS_ORIGINS": "https://learn.example.com", "DEPLOYMENT_DOMAIN": "learn.example.com",
        "CADDY_ACME_EMAIL": "ops@example.com", "LEARNING_AI_ENABLED": "false",
    }
    assert validate(values) == []


def test_production_environment_preflight_rejects_insecure_values() -> None:
    errors = validate({"APP_ENV": "development", "CORS_ORIGINS": "*", "LEARNING_AI_ENABLED": "true"})
    assert any("APP_ENV" in error for error in errors)
    assert any("CORS_ORIGINS" in error for error in errors)
    assert any("LEARNING_AI_API_KEY" in error for error in errors)


def test_backup_requires_postgresql_url(tmp_path) -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        create_backup("sqlite:///learning.db", tmp_path / "learning.dump")


def test_restore_requires_confirmation_and_disposable_target(tmp_path) -> None:
    archive = tmp_path / "learning.dump"
    archive.write_bytes(b"backup")
    with pytest.raises(ValueError, match="confirm-restore"):
        restore_backup("postgresql://owner:secret@db/learning_restore", archive)
    with pytest.raises(ValueError, match="disposable"):
        restore_backup("postgresql://owner:secret@db/learning", archive, confirmed=True)


def test_restore_verifies_archive_before_replacing_disposable_target(tmp_path, monkeypatch) -> None:
    archive = tmp_path / "learning.dump"
    archive.write_bytes(b"backup")
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)

    monkeypatch.setattr("scripts.restore_saas.subprocess.run", fake_run)
    restore_backup("postgresql://owner:secret@db/learning_recovery_drill", archive, confirmed=True)
    assert commands[0][:2] == ["pg_restore", "--list"]
    assert commands[1][0] == "pg_restore"
    assert "--clean" in commands[1]
    assert "--single-transaction" in commands[1]
