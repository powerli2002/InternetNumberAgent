from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass
class AgentConfig:
    """统一管理智能体运行参数。"""

    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    env_path: Optional[Path] = None
    config_yaml: Optional[Path] = None

    # 数据库与中间件
    postgres_url: Optional[str] = None
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j123"

    # LLM（阿里云百炼兼容 OpenAI 模式）
    dashscope_api_key: Optional[str] = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen3-max-preview"
    dashscope_embedding_model: str = "text-embedding-v3"

    # 记忆与上下文
    working_memory_size: int = 200
    episodic_memory_size: int = 1000
    semantic_memory_size: int = 5000
    max_context_tokens: int = 4096

    # 工具与目录
    notes_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1] / "notes")
    notes_index: Path = field(init=False)
    vector_collection: str = "fusion_docs"
    allowed_tables: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.notes_index = self.notes_dir / "notes_index.json"

    @classmethod
    def load(cls, project_root: Optional[Path] = None) -> "AgentConfig":
        """从 conf/.env 与 conf/config.yaml 加载配置。"""
        root = project_root or Path(__file__).resolve().parents[1]
        cfg = cls(project_root=root)

        # 读取 conf/.env
        env_path = root / "conf" / ".env"
        if env_path.exists():
            cfg.env_path = env_path
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

        # 读取 conf/config.yaml
        config_yaml = root / "conf" / "config.yaml"
        if config_yaml.exists():
            cfg.config_yaml = config_yaml
            data = yaml.safe_load(config_yaml.read_text(encoding="utf-8")) or {}
            # 使用传统配置生成 PostgreSQL 连接字符串
            if not os.environ.get("POSTGRES_URL"):
                db = data.get("postgresql_database")
                user = data.get("postgresql_user")
                pwd = data.get("postgresql_password")
                host = data.get("postgresql_host", "127.0.0.1")
                port = data.get("postgresql_port", "5432")
                if db and user and pwd:
                    cfg.postgres_url = f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"

        # 环境变量覆盖
        cfg.postgres_url = os.environ.get("POSTGRES_URL") or cfg.postgres_url
        cfg.milvus_host = os.environ.get("MILVUS_HOST", cfg.milvus_host)
        cfg.milvus_port = int(os.environ.get("MILVUS_PORT", cfg.milvus_port))
        cfg.neo4j_uri = os.environ.get("NEO4J_URI", cfg.neo4j_uri)
        cfg.neo4j_user = os.environ.get("NEO4J_USER", cfg.neo4j_user)
        cfg.neo4j_password = os.environ.get("NEO4J_PASSWORD", cfg.neo4j_password)
        cfg.dashscope_api_key = os.environ.get("DASHSCOPE_API_KEY", cfg.dashscope_api_key)
        cfg.dashscope_base_url = os.environ.get("DASHSCOPE_BASE_URL", cfg.dashscope_base_url)
        cfg.dashscope_model = os.environ.get("DASHSCOPE_MODEL", cfg.dashscope_model)
        cfg.dashscope_embedding_model = os.environ.get("DASHSCOPE_EMBEDDING_MODEL", cfg.dashscope_embedding_model)

        # 默认暴露的表
        cfg.allowed_tables = [
            "as_entity",
            "asn_entity",
            "country_entity",
            "industry_entity",
            "ip_bgp_entity",
            "ip_inetnum_entity",
            "ip_rdap_entity",
            "ip_route_entity",
            "ipv4_entity",
            "ipv6_bgp_entity",
            "ipv6_entity",
            "ipv6_inetnum_entity",
            "ipv6_rdap_entity",
            "ipv6_route_entity",
            "org_entity",
            "website_entity",
        ]

        return cfg
