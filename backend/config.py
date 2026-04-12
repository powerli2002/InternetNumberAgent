"""产品后端配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agent.core.config import AgentConfig


@dataclass
class BackendConfig:
    """产品后端配置。"""

    agent_config: AgentConfig = field(default_factory=AgentConfig.load)
    host: str = "0.0.0.0"
    port: int = 2026
    session_cookie_name: str = "fusion_session"
    session_ttl_hours: int = 168
    secret_key: str = "fusion-backend-dev-secret"
    sandbox_service_token: str = "fusion-sandbox-dev-token"
    opensandbox_domain: str = "127.0.0.1:8080"
    opensandbox_api_key: Optional[str] = None
    opensandbox_template: str = (
        "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.2"
    )
    opensandbox_timeout_seconds: int = 600
    opensandbox_python_version: str = "3.11"
    artifact_root: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / "backend" / "store" / "artifacts"
    )

    @property
    def postgres_url(self) -> str:
        """统一读取 Agent 已有 PostgreSQL 配置。"""
        if not self.agent_config.postgres_url:
            raise RuntimeError("缺少 POSTGRES_URL，无法启动产品后端。")
        return self.agent_config.postgres_url

    @classmethod
    def load(cls) -> "BackendConfig":
        """从环境变量与 AgentConfig 加载配置。"""
        cfg = cls()
        cfg.host = os.environ.get("BACKEND_HOST", cfg.host)
        port_value = os.environ.get("BACKEND_PORT")
        if port_value:
            try:
                cfg.port = int(port_value)
            except ValueError:
                pass
        cfg.session_cookie_name = os.environ.get(
            "BACKEND_SESSION_COOKIE_NAME", cfg.session_cookie_name
        )
        ttl_value = os.environ.get("BACKEND_SESSION_TTL_HOURS")
        if ttl_value:
            try:
                cfg.session_ttl_hours = max(1, int(ttl_value))
            except ValueError:
                pass
        cfg.secret_key = os.environ.get("BACKEND_SECRET_KEY", cfg.secret_key)
        cfg.sandbox_service_token = os.environ.get(
            "BACKEND_SANDBOX_SERVICE_TOKEN", cfg.sandbox_service_token
        )
        cfg.opensandbox_domain = os.environ.get(
            "OPENSANDBOX_DOMAIN", cfg.opensandbox_domain
        )
        cfg.opensandbox_api_key = os.environ.get("OPENSANDBOX_API_KEY")
        cfg.opensandbox_template = os.environ.get(
            "OPENSANDBOX_TEMPLATE", cfg.opensandbox_template
        )
        timeout_value = os.environ.get("OPENSANDBOX_TIMEOUT_SECONDS")
        if timeout_value:
            try:
                cfg.opensandbox_timeout_seconds = max(5, int(timeout_value))
            except ValueError:
                pass
        cfg.opensandbox_python_version = os.environ.get(
            "OPENSANDBOX_PYTHON_VERSION", cfg.opensandbox_python_version
        )
        artifact_root_value = os.environ.get("BACKEND_ARTIFACT_ROOT")
        if artifact_root_value:
            cfg.artifact_root = Path(artifact_root_value)
        return cfg
