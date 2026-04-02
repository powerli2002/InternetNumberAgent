## Harness 工程

Harness Engineering 是围绕 AI Agent（特别是 Coding Agent）设计和构建**约束机制、反馈回路、工作流控制和持续改进循环**的系统工程实践。

"Harness" 本意是马具——缰绳、鞍具那一套东西，把马的力气引到正确方向上。拿来类比 AI Agent 挺合适：LLM 就像一匹蛮力十足但方向感不太行的马，跑得快但容易跑偏.

### OPENAI 报告和路径

出现的问题：

`AGENTS.md ` 产生大量说明指令，反直觉的没有带来如预期中的效果改进。

| 经验             | 表现                | 根本原因           |
| -------------- | ----------------- | -------------- |
| 上下文（Context）稀缺 | 巨大的指令文件挤掉任务和代码    | 上下文是有限资源       |
| 指令失效           | 指令中过多规则导致模式匹配而非理解 | 注意力被稀释，无法区分优先级 |
| 知识腐烂           | 手册变成陈旧规则的坟场       | 缺乏有效的维护机制      |
| 难以核实           | 单一文本块无法进行结构化检查    | 缺乏可验证的知识组织形式   |

> 改进

**一、将 AGENTS. md 重新定位为内容目录**，指向结构化的 `docs` 目录，在这个目录存放代码仓库的知识库。

把 AGENTS.md 从一本“百科全书”变成了“索引地图”，其大小变得仅 100 行左右

**类似于另一种的渐进式披露**

**二、提高 Agent 的可读性**(优化可观测，并且扫描丢弃无用文档，类似垃圾回收)

将 Chrome DevTools 协议接入智能体运行时，创建用于处理 DOM 快照、截图和导航的技能。
使用了专职的 linter 和 CI 作业，验证知识库的更新状况、是否已交叉链接且结构正确。一个定期运行的“doc-gardening”智能体会扫描那些不再反映真实代码行为的过时或废弃文档，并发起修复用的 Pull Request。

**第三，规范架构与品味**
通过自定义的 lint 和 CI 作业，自动化强制执行严格的系统约束如本次实验中的架构模型

**第四，管理熵增**
完全自主的智能体会复现代码仓库中已存在的模式，包括那些不均衡或不够理想的模式，随着时间的推移不可避免地导致代码库逐渐“腐烂”。
将“黄金原则”（带有主观意见的自动化规则）直接编码到代码仓库中，并建立了一个循环清理流程。定期运行后台 Codex 任务，它会扫描偏差、更新质量等级，并发起有针对性的重构 Pull Request，类似于系统的“垃圾回收”机制。

### Anthropic 的双重 Agent

由于 Claude 上下文窗口有限，而且大多数复杂项目无法在单个窗口内完成，智能体需要一种方法来弥合多个编码会话之间的空白。

- **初始化智能体（Initializer Agent）**：在首次运行时设置环境，包括编写全面的功能需求列表（JSON 格式，初始标记为“失败”）、创建 `init.sh` 脚本、一个记录任务进度的 claude-progress.txt 文件和初始 Git 提交。
- **编码智能体（Coding Agent）**：在后续会话中，被提示每次只处理一个功能，通过阅读进度文件和 Git 日志快速了解现状，并在完成后提交带有描述性信息的 Git 提交 。

## Deerflow

不再把自己定位为一个 Deep Research 框架，而是一个 Super Agent Harness，—个开箱即用、完全可扩展的超级智能体运行时。

**Long-horizon Agent（长程智能体）：**
- **运行时间更长**：不再是“调用一次 LLM 就结束”或“简单的 Re-Act 过程”，而是能够持续运行数分钟甚至数小时
- **自主决策能力**：LLM 在循环中不断决定下一步行动，而不是按照预设的流程执行，这一点和 Re-Act Agent 仍然保持了传承性
- **产出“初稿”而非最终产品**：当前阶段，Long-horizon Agent 最擅长的是生成高质量的”first draft”——无论是代码 PR、研究报告还是数据分析，人类用户沿着这份初稿可以进行后续的修改，或继续通过新的指令进行迭代，用户正在学会与 Agent 进行类似“伙伴”的平等关系相处，而不是“master/slave”般的命令其完成某一个端到端的工作

**skills**
出厂自带 若干个 skills

**沙箱（Sandbox）**
```
/mnt/user-data/
├── uploads/          ← 你上传的文件
├── workspace/        ← Agent 的工作目录
└── outputs/          ← 最终交付物
```

- **Local**：直接在宿主机上执行，适合开发调试
- **Docker（推荐）**：每个任务运行在独立容器中，完全隔离，使用了字节跳动开源的 [AIO Sandbox](https://sandbox.agent-infra.com/)
- **Kubernetes**：通过 Provisioner 服务在 K8s Pod 中执行，适合生产环境

**子智能体（Sub-agent）**
 Lead Agent 可以随时拆分任务，将子任务委派给 Sub-agent 并行执行
 - **general-purpose**：通用型，继承父 Agent 的所有工具（除了 `task` 本身），最多 50 轮对话
- **bash**：命令行专家，只配备沙箱工具（`bash`、`ls`、`read_file`、`write_file`、`str_replace`），最多 30 轮对话

每个 Sub-agent 运行在自己独立的上下文中——它看不到主 Agent 和其他 Sub-agent 的上下文

**上下文工程（Context Engineering）**

- **多层 Middleware 链**：DeerFlow 的每一次 Agent 调用都要经过一条精心编排的 Middleware 链。从线程数据初始化、文件上传注入、沙箱分配，到上下文摘要、记忆提取、图像注入、子任务限流——11 个 Middleware 各司其职，严格按序执行。
- **上下文摘要（Summarization）**：当对话接近 token 上限时，DeerFlow 会自动对较早的消息进行摘要压缩，只保留最近的 N 条消息原文。这让 Agent 在跨越数十轮对话的长任务中始终保持清醒。
- **子 Agent 上下文隔离**：如前所述，每个 Sub-agent 都运行在独立上下文中。这不仅防止了上下文膨胀，也避免了子任务之间的信息互相干扰。
- **文件系统作为外部存储**：Agent 可以随时将中间结果写入文件系统，然后在需要时重新读取。这等于给 Agent 配了一块「硬盘」——上下文窗口是内存，文件系统是磁盘，需要时换入换出。

**智能体架构改进**

原本的：
```
Coordinator → Planner → Researcher / Coder（并行）→ Reporter
```

- **角色固化**：5 个 Agent 的职责是写死的。想加一个「设计师 Agent」或「运维 Agent」？得改图、加节点、调边——本质上是在改框架
- **上下文浪费**：所有 Agent 共享同一份 State，Researcher 搜回来的大段网页内容，Reporter 不需要看到，但它就在那里占着 token
- **扩展性差**：想让 DeerFlow 做 Deep Research 以外的事情，要么往图里硬塞节点，要么另起炉灶 这些不是 bug，而是架构选型带来的天花板。

改进后：

从固定角色的 Multi-Agent 图，变为单一 Lead Agent + 中间件链 + 动态 Sub-agent。
四个参数决定了 Agent 的一切：
- `model`：动态选择的大语言模型，支持 Thinking 模式和视觉能力
- `tools`：动态组装的工具集——沙箱工具 + 内置工具 + MCP 工具 + 社区工具 + Sub-agent 工具
- `middleware`：11 层中间件链（下一节详述）
- `system_prompt`：动态生成的系统提示词，按需注入 Skill 列表、Sub-agent 调度指令和用户记忆

> 2.0 的能力集中在一个 Agent 的 **工具集** 和 **中间件链** 上。这个设计的好处是：想扩展能力？加一个 Tool 或 Skill 就行，不用动图。

*Middleware 链*
DeerFlow 2.0 的每一次 Agent 调用，都要经过一条精心编排的 Middleware 链。这些 Middleware 在 Agent 调用前后执行，负责上下文管理、状态同步、资源分配等”基础设施”工作：

```python
def _build_middlewares(config: RunnableConfig):
    middlewares = [
        ThreadDataMiddleware(),        # 1. 创建线程目录结构
        UploadsMiddleware(),           # 2. 注入新上传的文件
        SandboxMiddleware(),           # 3. 分配沙箱
        DanglingToolCallMiddleware(),  # 4. 修补中断的工具调用
    ]

    # 5. 上下文摘要（可选）
    # 6. TodoList 计划模式（可选）
    # 7. 自动生成会话标题
    # 8. 异步记忆更新
    # 9. 图像注入（视觉模型）
    # 10. Sub-agent 并发限流
    # 11. 用户澄清拦截（必须最后）

    middlewares.append(ClarificationMiddleware())  # 必须是最后一个
    return middlewares
```

Middleware 的顺序不是随意的，每一层都有明确的依赖关系。
每个中间件相当于一个 横切关注点（Cross-cutting Concerns）——上传、沙箱、记忆、摘要、限流——与 Agent 的核心逻辑完全解耦。

中间件的执行过程，也类似于 环绕通知

```python
def memory_middleware(request, next_layer):
    # ---------------- 1. 入站（预处理） ----------------
    print("进入记忆层：提取历史对话...")
    request["context"] = "这是历史上下文"
    
    # ---------------- 2. 核心调用与挂起 ----------------
    # 关键点：调用 next_layer，程序会在这里“暂停”，
    # 等待内层所有的中间件和大模型全部执行完毕，再返回结果。
    response = next_layer(request) 
    
    # ---------------- 3. 出站（后处理） ----------------
    print("离开记忆层：将新对话压缩存入数据库...")
    response["saved"] = True
    
    return response
```

当你把多个这样的中间件组合在一起时，它们就像俄罗斯套娃一样层层嵌套：`安全层( 记忆层( 路由层( 大模型() ) ) )`。

1. **入站阶段：** 请求进入第一层（安全层），执行它的“预处理”代码，然后遇到 `next()`。
2. **不断深入：** 程序暂停当前安全层的执行，跳入第二层（记忆层）的预处理，遇到 `next()` 又暂停，跳入第三层... 直到最核心的大模型生成了答案。
3. **出站阶段（重点）：** 大模型返回答案后，调用栈开始 **“原路返回”（出栈）**。程序会回到之前暂停的第三层，执行 `next()` 后面的“后处理”代码；接着回到第二层执行后处理；最后回到第一层。

**Sub-agent 执行引擎**

当 Lead Agent 遇到复杂任务时，它会通过 `task` 工具将子任务委派给 Sub-agent。Sub-agent 的执行由 `SubagentExecutor` 管理，采用**双线程池**架构：

```python
# 调度线程池：负责任务排队和编排
_scheduler_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-scheduler-")

# 执行线程池：负责实际的 Agent 执行（支持超时）
_execution_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-exec-")
```

Sub-agent 是一个**精简版的 Lead Agent**——同样由 `create_agent()` 创建，但只配备 2 个 Middleware（`ThreadDataMiddleware` + `SandboxMiddleware`），工具集根据类型过滤，没有记忆注入、没有标题生成、没有上下文摘要。

