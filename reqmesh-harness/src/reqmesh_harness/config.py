"""harness 配置：全部经环境变量（`REQMESH_*`）注入，支持 .env（已 gitignore）。"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BASE_URL = "http://172.16.100.2:8000"


def _default_xdg(kind: str) -> Path:
    """XDG 基础目录（kind: config/state），遵循 XDG 规范的环境变量覆盖。"""
    import os

    env = {"config": "XDG_CONFIG_HOME", "state": "XDG_STATE_HOME"}[kind]
    override = os.environ.get(env)
    if override:
        return Path(override)
    return Path.home() / (".config" if kind == "config" else Path(".local") / "state")


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

    # P2 审批门：白名单文件（XDG config）/ 审计日志（XDG state）/ ADMIN 层显式开启
    approvals_file: Path | None = None
    audit_file: Path | None = None
    enable_admin: bool = False

    # streamable-HTTP transport
    harness_host: str = "127.0.0.1"
    harness_port: int = 8123

    # P3 复合技能：本地 quality lint 过线标准与确定性修正轮数上限
    lint_min_score: int = 90
    lint_max_rounds: int = 3

    # P5 内置运行时：provider 选择（dsh 默认 | openai | fake）
    provider: str = "dsh"
    show_reasoning: bool = False

    # P5 DSH 适配器（委托式；loopback RPC + WS events.mux；harness 侧零凭据）
    dsh_url: str = "http://127.0.0.1:8080"
    dsh_cwd: str | None = None          # None → 当前工作目录
    dsh_idle_timeout: float = 600.0     # 秒；事件流空闲防御（自最后一帧起计）
    dsh_max_rounds: int = 8

    # P5 会话内存：run 目录（默认 XDG state reqmesh-harness/runs）
    runs_dir: Path | None = None

    # P5 OpenAI 兼容 provider（自驱；本环境无 key——D5，仅离线验证）
    openai_base_url: str = "https://api.deepseek.com"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "deepseek-chat"

    def resolved_session_file(self) -> Path:
        if self.session_file is not None:
            return self.session_file
        return _default_xdg("state") / "reqmesh-harness" / "session.json"

    def resolved_approvals_file(self) -> Path:
        if self.approvals_file is not None:
            return self.approvals_file
        return _default_xdg("config") / "reqmesh-harness" / "approvals.toml"

    def resolved_audit_file(self) -> Path:
        if self.audit_file is not None:
            return self.audit_file
        return _default_xdg("state") / "reqmesh-harness" / "audit.jsonl"

    def resolved_runs_dir(self) -> Path:
        if self.runs_dir is not None:
            return self.runs_dir
        return _default_xdg("state") / "reqmesh-harness" / "runs"

    def has_password_credentials(self) -> bool:
        return bool(self.username and self.password.get_secret_value())

    def has_credentials(self) -> bool:
        return self.has_password_credentials() or bool(self.token.get_secret_value())


def get_settings() -> Settings:
    return Settings()
