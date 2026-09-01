"""harness 配置：全部经环境变量（`REQMESH_*`）注入，支持 .env（已 gitignore）。"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BASE_URL = "http://172.16.100.2:8000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REQMESH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 实例与凭据
    base_url: str = DEFAULT_BASE_URL
    username: str = ""
    password: SecretStr = SecretStr("")
    # Bearer 兜底：设置后走 Authorization: Bearer <token>，跳过 cookie 登录流程
    token: SecretStr = SecretStr("")

    # HTTP
    timeout: float = 30.0

    # 会话持久化文件；默认 XDG state 目录
    session_file: Path | None = None

    # streamable-HTTP transport
    harness_host: str = "127.0.0.1"
    harness_port: int = 8123

    def resolved_session_file(self) -> Path:
        if self.session_file is not None:
            return self.session_file
        state_home = Path.home() / ".local" / "state"
        import os

        if os.environ.get("XDG_STATE_HOME"):
            state_home = Path(os.environ["XDG_STATE_HOME"])
        return state_home / "reqmesh-harness" / "session.json"

    def has_password_credentials(self) -> bool:
        return bool(self.username and self.password.get_secret_value())

    def has_credentials(self) -> bool:
        return self.has_password_credentials or bool(self.token.get_secret_value())


def get_settings() -> Settings:
    return Settings()
