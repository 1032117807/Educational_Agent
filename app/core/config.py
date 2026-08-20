from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    app_name: str = "个性化学习助手"
    organization: str = "LocalLearning"
    version: str = "1.0.0"
    data_dir: Path = Path.home() / ".personal_learning_desktop"
    saas_api_url: str = ""
    saas_access_token: str = ""
    saas_refresh_token: str = ""
    desktop_companion_id: str = ""
    agent_runtime_v2: bool = True
    skill_progressive_disclosure: bool = True
    context_status_bar: bool = True
    agent_max_iterations: int = 10
    agent_max_tool_calls: int = 12
    agent_max_same_tool_retries: int = 2
    agent_max_rag_searches: int = 4
    agent_max_subagents: int = 4
    agent_max_context_tokens: int = 12000
    agent_max_tool_result_chars: int = 12000
    model_config = SettingsConfigDict(
        env_prefix="LEARNING_", env_file=".env", env_file_encoding="utf-8", extra="ignore",
    )

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
