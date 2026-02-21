# Agent Store

统一运行时存储目录，避免状态文件分散在多个位置。

- `memory/`：情景记忆 SQLite 等本地状态文件。
- `index/`：NL2SQL 索引缓存。
- `notes/`：笔记索引与内容缓存。

统一策略：
- 所有新代码只读取本目录。
- 如需自定义路径，请通过环境变量 `AGENT_STORE_DIR` / `MEMORY_STORE_DIR` / `NL2SQL_INDEX_CACHE_DIR` / `NOTES_DIR` 指定。
