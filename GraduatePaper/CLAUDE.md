# GraduatePaper — Claude 工作规范

## 进度看板

**`GraduatePaper/DASHBOARD.md`** — 进度总控入口，实验状态、阻塞项、任务列表、目录说明均在此文件。开始任何任务前先读它。

## 本目录是什么

毕业论文实验区：基于 Agent 调度的 IPv6 地理位置推断系统。系统已实现，当前专注实验（E02/E03/E04）和数据覆盖率突破。论文撰写暂缓。

## 关键命令

```bash
# 在 GraduatePaper/ 目录下运行，无需 export PYTHONPATH
UV_CACHE_DIR=.uv-cache uv sync                          # 安装环境
UV_CACHE_DIR=.uv-cache uv run ipv6geo-eval \            # 主评测
  --config configs/trustgeo.json \
  --output-dir outputs/trustgeo
```

## 工作规范

- 代码注释使用简体中文。
- 实验完成后立即更新 `DASHBOARD.md`（实验台账 + 阻塞项），不要只改代码。
- 工具输出不可伪造：输入缺失时返回 `unavailable`，不要硬凑坐标。
- 不把本目录原型代码迁入 `services/`，除非用户明确要求集成。

## 与主仓库的关系

本目录运行环境独立（uv 管理），不需要 `export PYTHONPATH=services`。主仓库硬约束（16张核心表、Harness 规范等）不约束本目录实验代码。
