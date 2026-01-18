"""
智能体配置管理模块

提供统一的配置参数管理，支持从环境变量和 YAML 文件加载配置。
配置层次：
1. 环境变量（conf/.env）：运行时动态配置，包含敏感信息如 API 密钥
2. YAML 文件（conf/config.yaml）：静态配置，区分本机和容器环境
3. 默认值：代码中的默认参数，确保系统能正常启动

配置分类：
- 数据库连接：PostgreSQL、Neo4j、Milvus
- LLM 服务：阿里云百炼 API 配置
- 记忆系统：各类型记忆的容量和行为参数
- 工具配置：索引缓存、向量集合等
- 系统参数：上下文长度、超时时间等
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass
class AgentConfig:
    """
    智能体统一配置类

    整合所有组件的配置参数，支持从多种来源加载：
    - 环境变量（优先级最高）
    - YAML 配置文件
    - 代码默认值

    配置加载顺序：
    1. 从项目根目录加载 conf/.env 文件
    2. 如果未找到，则尝试加载 conf/config.yaml
    3. 使用代码中定义的默认值兜底
    """

    # 路径配置
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    """项目根目录路径，自动从当前文件位置推导"""

    env_path: Optional[Path] = None
    """环境变量文件路径，默认使用 conf/.env"""

    config_yaml: Optional[Path] = None
    """YAML 配置文件路径，默认使用 conf/config.yaml"""

    # 数据库与中间件连接配置
    postgres_url: Optional[str] = None
    """PostgreSQL 连接字符串，格式：postgresql+psycopg2://user:pass@host:port/db"""

    milvus_host: str = "localhost"
    """Milvus 向量数据库主机地址"""

    milvus_port: int = 19530
    """Milvus 向量数据库端口"""

    neo4j_uri: str = "bolt://localhost:7687"
    """Neo4j 图数据库连接 URI"""

    neo4j_user: str = "neo4j"
    """Neo4j 用户名"""

    neo4j_password: str = "neo4j123"
    """Neo4j 密码"""

    # LLM 服务配置（阿里云百炼兼容 OpenAI 模式）
    dashscope_api_key: Optional[str] = None
    """阿里云百炼 API 密钥，用于 LLM 调用和向量嵌入"""

    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    """阿里云百炼 API 基础 URL"""

    dashscope_model: str = "qwen3-max-preview"
    """默认使用的 LLM 模型"""

    dashscope_embedding_model: str = "text-embedding-v3"
    """用于向量嵌入的模型"""

    # 记忆系统配置
    working_memory_size: int = 200
    """工作记忆容量：短期对话上下文的最大条目数"""

    episodic_memory_size: int = 1000
    """情景记忆容量：PostgreSQL/SQLite 中存储的重要对话片段最大条目数"""

    semantic_memory_size: int = 5000
    """语义记忆容量：Neo4j 中存储的概念节点最大数量"""

    max_context_tokens: int = 4096
    """上下文最大 token 数，控制发送给 LLM 的上下文长度"""

    request_timeout_seconds: int = 60
    """单次请求超时时间（秒）"""

    semantic_memory_enabled: bool = True
    """是否启用语义记忆抽取功能"""

    semantic_memory_max_items: int = 3
    """每次对话最多抽取的语义记忆条目数"""

    semantic_memory_min_importance: float = 0.6
    """语义记忆抽取的最小重要性阈值（0.0-1.0）"""

    # NL2SQL 索引缓存配置
    nl2sql_index_cache_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / "agent" / "index_store" / "nl2sql"
    )
    """NL2SQL 索引缓存目录：存储表结构和列值的向量索引"""

    nl2sql_index_cache_enabled: bool = True
    """是否启用 NL2SQL 索引缓存，提高查询性能"""

    nl2sql_index_cache_force_rebuild: bool = False
    """是否强制重建索引缓存，表结构变更时使用"""

    # 工具与目录配置
    notes_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1] / "notes")
    """笔记存储目录"""

    notes_index: Path = field(init=False)
    """笔记索引文件路径（自动生成）"""

    vector_collection: str = "fusion_docs"
    """Milvus 中的文档向量集合名称"""

    allowed_tables: List[str] = field(default_factory=list)
    """NL2SQL 允许查询的表名列表，用于安全控制"""

    def __post_init__(self) -> None:
        self.notes_index = self.notes_dir / "notes_index.json"

    @classmethod
    def load(cls, project_root: Optional[Path] = None) -> "AgentConfig":
        """
        从配置文件加载智能体配置

        加载顺序：
        1. 读取 conf/.env 文件，将环境变量设置到 os.environ
        2. 读取 conf/config.yaml 文件，解析 YAML 配置
        3. 使用环境变量覆盖 YAML 配置
        4. 返回完整的配置对象

        环境变量优先级高于 YAML 配置，便于运行时动态调整。

        Args:
            project_root: 项目根目录路径，如果不提供则自动推导

        Returns:
            AgentConfig: 加载完成的配置对象
        """
        root = project_root or Path(__file__).resolve().parents[1]
        cfg = cls(project_root=root)

        # 第一步：读取环境变量文件 conf/.env
        # 将文件中的 KEY=VALUE 格式转换为环境变量
        env_path = root / "conf" / ".env"
        if env_path.exists():
            cfg.env_path = env_path
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                # 使用 setdefault 避免覆盖已存在的环境变量
                os.environ.setdefault(key.strip(), value.strip())

        # 第二步：读取 YAML 配置文件
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
        # 兼容多种环境变量命名，优先使用 DASHSCOPE_API_KEY
        dashscope_key = (
            os.environ.get("DASHSCOPE_API_KEY")
            or os.environ.get("BAILIAN_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        if dashscope_key:
            os.environ.setdefault("DASHSCOPE_API_KEY", dashscope_key)
        cfg.dashscope_api_key = dashscope_key or cfg.dashscope_api_key
        cfg.dashscope_base_url = os.environ.get("DASHSCOPE_BASE_URL", cfg.dashscope_base_url)
        cfg.dashscope_model = os.environ.get("DASHSCOPE_MODEL", cfg.dashscope_model)
        cfg.dashscope_embedding_model = os.environ.get("DASHSCOPE_EMBEDDING_MODEL", cfg.dashscope_embedding_model)

        # 请求超时配置（秒）
        timeout_value = os.environ.get("REQUEST_TIMEOUT_SECONDS") or os.environ.get("AGENT_REQUEST_TIMEOUT_SECONDS")
        if timeout_value:
            try:
                cfg.request_timeout_seconds = int(timeout_value)
            except ValueError:
                pass

        # 语义记忆配置
        enabled_value = os.environ.get("SEMANTIC_MEMORY_ENABLED")
        if enabled_value is not None:
            cfg.semantic_memory_enabled = enabled_value.strip().lower() in {"1", "true", "yes", "on"}
        max_items_value = os.environ.get("SEMANTIC_MEMORY_MAX_ITEMS")
        if max_items_value:
            try:
                cfg.semantic_memory_max_items = max(1, int(max_items_value))
            except ValueError:
                pass
        min_importance_value = os.environ.get("SEMANTIC_MEMORY_MIN_IMPORTANCE")
        if min_importance_value:
            try:
                cfg.semantic_memory_min_importance = float(min_importance_value)
            except ValueError:
                pass

        # NL2SQL 索引缓存配置
        cache_dir_value = os.environ.get("NL2SQL_INDEX_CACHE_DIR")
        if cache_dir_value:
            cfg.nl2sql_index_cache_dir = Path(cache_dir_value)
        cache_enabled_value = os.environ.get("NL2SQL_INDEX_CACHE_ENABLED")
        if cache_enabled_value is not None:
            cfg.nl2sql_index_cache_enabled = cache_enabled_value.strip().lower() in {"1", "true", "yes", "on"}
        force_rebuild_value = os.environ.get("NL2SQL_INDEX_CACHE_FORCE_REBUILD")
        if force_rebuild_value is not None:
            cfg.nl2sql_index_cache_force_rebuild = force_rebuild_value.strip().lower() in {"1", "true", "yes", "on"}

        # 为依赖 OpenAI 兼容接口的组件兜底注入 KEY，避免默认 OpenAIEmbedding 报错
        if cfg.dashscope_api_key:
            os.environ.setdefault("OPENAI_API_KEY", cfg.dashscope_api_key)

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
