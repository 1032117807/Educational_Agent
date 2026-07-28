from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    app_name: str = "个性化学习助手"
    organization: str = "LocalLearning"
    version: str = "1.0.0"
    data_dir: Path = Path.home() / ".personal_learning_desktop"
    model_config = SettingsConfigDict(env_prefix="LEARNING_", extra="ignore")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'learning.db').as_posix()}"

    @property
    def workspace_dir(self) -> Path:
        return self.data_dir / "workspace"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.workspace_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = AppSettings()
