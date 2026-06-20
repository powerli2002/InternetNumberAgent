# GeoAgent-R1 完整研究与实施报告

> 日期：2026-06-08  
> 项目：基于监督微调与可验证强化学习的 IPv6 地理位置推断 Agent  
> 主线：LLM Agent、SFT、GRPO、多轮工具调用、可验证奖励  
> 关键问题之一：主动与被动 IPv6 定位工具无法有效作用于当前数据集

## 1. 执行摘要

本毕业设计的主要目标不是从头训练一个 IPv6 领域大模型，也不是单纯实现若干定位工具，而是：

> 构建一个可验证的 IPv6 地理位置推断多轮环境，通过 SFT 冷启动和 GRPO 强化学习，训练 LLM Agent 学会判断工具适用性、按需获取主动与被动证据、比较候选位置、及时停止并可信拒答。

当前系统已经完成基础定位工具、调度器和评测链路，但尚不具备直接训练 SFT/GRPO Agent 的条件：

1. ModuGeo 是唯一稳定工具，Median 误差为 31.8 km，覆盖率 100%。
2. rDNS 评测覆盖率为 0%，全量 PTR 命中约 1%。
3. CBG 主动定位仅有 3 个 probes，Median 误差为 678 km。
4. 被动 IPDB 缺少可用 IPv6 数据库，覆盖率为 0%。
5. 当前 Qwen 调度器是一次性动作分类器，不是多轮 Agent。
6. 当前 SFT 状态包含 `truth_region` 和 `truth_city`，存在标签泄漏。
7. 当前离线奖励策略不是真正的 GRPO 或 PPO 训练。

因此，实施顺序必须是：

```text
数据治理与严格划分
  -> 工具适配与效用审计
  -> 多轮环境
  -> 无泄漏教师轨迹
  -> SFT
  -> GRPO
  -> 泛化与消融评测
```

工具与数据集不匹配是实现主线必须解决的关键问题之一。解决它的目的不是将毕设改成工具适配研究，而是确保 Agent 拥有真实、互补、可学习的动作空间。

## 2. 零基础概念导读

本节先解释后文使用的核心概念。这里的 `GRPO` 全称是 **Group Relative Policy Optimization**，中文常译为“群组相对策略优化”。`GPRO` 通常是对 `GRPO` 的误写。

### 2.1 先理解：本项目到底训练什么

本项目不要求 LLM 记住每个 IPv6 地址的真实经纬度，也不要求它从零学习完整的定位算法。系统中已经存在 ModuGeo、rDNS、主动定位、被动定位和 WHOIS/BGP 等工具。

LLM Agent 需要学习的是一个决策过程：

```text
看到目标与当前状态
  -> 判断是否需要更多证据
  -> 选择合适的工具及参数
  -> 阅读工具返回结果
  -> 判断结果是否可信
  -> 决定继续调用、选择候选、停止或拒答
```

因此，训练目标类似于培养一个“会使用定位工具并做决策的操作员”，而不是重新训练所有定位工具。

### 2.2 什么是 LLM Agent

普通 LLM 通常执行一次输入到一次输出：

```text
用户问题 -> LLM -> 文本答案
```

LLM Agent 可以在得到最终答案前与环境进行多轮交互：

```text
用户任务
  -> Agent 选择工具
  -> 环境执行工具并返回观察
  -> Agent 根据新观察继续决策
  -> ...
  -> Agent 输出最终答案
```

在本项目中，Agent 的一次动作可以是：

```json
{"action": "query_rdns", "arguments": {}}
```

环境随后返回：

```json
{
  "tool": "rdns",
  "status": "unavailable",
  "failure_reason": "coverage_miss"
}
```

Agent 应理解“该目标没有 PTR 记录”，避免继续依赖 rDNS，并选择其他动作或直接停止。

### 2.3 什么是 Prompt、Action、Observation 和 Environment

#### Prompt

Prompt 是模型当前可见的输入，包括系统规则、目标信息、已有工具结果和剩余预算。真实位置不能出现在 Prompt 中。

#### Action

Action 是 Agent 输出的下一步操作，例如调用主动定位、检查工具质量或选择最终候选。

#### Observation

Observation 是环境执行 Action 后返回给 Agent 的新信息，例如工具状态、候选位置、置信度和失败原因。

#### Environment

Environment 是执行动作、返回观察、维护预算并计算最终奖励的程序。在本项目中，它相当于一个可反复训练的 IPv6 定位模拟器。

一次交互可以表示为：

```text
状态 s_t
  -> Agent 输出动作 a_t
  -> Environment 执行动作
  -> 返回观察 o_t 和新状态 s_(t+1)
```

### 2.4 什么是 Trajectory、Episode 和 Rollout

这三个词在 Agent 强化学习中经常出现。

- **Episode**：从任务开始到任务结束的一整局交互。
- **Trajectory**：这一整局交互中按顺序记录的状态、动作和观察。
- **Rollout**：让当前模型在环境中实际执行一次，从而产生一条 trajectory。

例如：

```text
目标 IPv6
  -> inspect active
  -> active 可用但质量一般
  -> query passive
  -> passive 与 ModuGeo 一致
  -> finalize ModuGeo
```

这是一个 episode，也是一条 trajectory；模型实际跑出这条轨迹的过程叫一次 rollout。

### 2.5 什么是 SFT

SFT 全称是 **Supervised Fine-Tuning**，中文为“监督微调”。

它的基本思想是：

> 给模型大量“在某个输入下，正确输出应该是什么”的示范，让模型模仿这些示范。

普通问答 SFT 示例：

```text
输入：法国首都是什么？
正确输出：巴黎
```

本项目中的 Agent SFT 示例不是简单答案，而是一条多轮工具调用示范：

```text
输入：ModuGeo 置信度低，active 有 8 个约束
正确动作：检查 active 是否适用
工具返回：active 条件可用
正确动作：执行质量过滤后的 active solver
工具返回：候选位置 A
正确动作：比较候选
正确动作：选择候选 A
```

SFT 主要教会 Agent：

1. 输出合法 JSON 和工具参数。
2. 理解工具状态和失败原因。
3. 学习基本调用顺序。
4. 在明显场景中停止或跳过工具。

SFT 的局限是：模型主要模仿教师数据。如果教师轨迹不够好、动作分布失衡或困难情况覆盖不足，模型很难自己发现更优策略。

### 2.6 SFT 数据是怎么训练模型的

一条 SFT 数据通常包含多条 `messages`：

```json
{
  "messages": [
    {"role": "system", "content": "你是 IPv6 定位 Agent。"},
    {"role": "user", "content": "当前目标和环境状态"},
    {"role": "assistant", "content": "{\"action\":\"query_rdns\"}"},
    {"role": "tool", "content": "{\"status\":\"unavailable\"}"},
    {"role": "assistant", "content": "{\"action\":\"finalize\",\"candidate_id\":\"modugeo:1\"}"}
  ]
}
```

训练时，通常只计算模型应生成部分的损失，即让模型学习 assistant 消息。简化理解：

```text
模型预测的动作与教师动作越不同 -> loss 越高 -> 更新模型参数
模型预测的动作与教师动作越接近 -> loss 越低
```

SFT 完成后，模型应当从“不会稳定使用工具”变成“能够按照示范完成基本工具交互”。

### 2.7 什么是强化学习与 Reward

强化学习不要求为每一步都提供唯一正确答案，而是让模型尝试不同策略，并根据最终收益调整行为。

Reward 是评价一次 rollout 好坏的数值。例如：

```text
定位更准确              -> 加分
修正 ModuGeo 尾部错误   -> 加分
正确判断工具不可用      -> 加分
无效调用很多工具        -> 扣分
将正确结果改坏          -> 扣分
输出非法动作            -> 扣分
```

例如同一个任务产生两条轨迹：

```text
轨迹 A：立即使用 ModuGeo，误差 50 km，成本低，奖励 0.40
轨迹 B：调用 active 后修正结果，误差 10 km，成本较高，奖励 0.72
```

强化学习会提高产生轨迹 B 中有效行为的概率。但如果 active 结果错误：

```text
轨迹 C：调用 active 后误差变成 500 km，奖励 -0.80
```

模型应降低这种调用与融合行为的概率。

### 2.8 什么是 GRPO

GRPO 是一种用于训练生成模型策略的强化学习方法。它的核心思想可以简化为：

> 对同一道任务，让模型生成一组不同尝试；比较组内每个尝试的奖励；提高相对较好尝试的概率，降低相对较差尝试的概率。

假设同一个 IPv6 目标采样 4 条 rollout：

| Rollout | 行为 | 奖励 |
| --- | --- | ---: |
| A | 立即采用 ModuGeo | 0.40 |
| B | 调用主动定位并正确修正 | 0.72 |
| C | 调用所有工具后错误融合 | -0.80 |
| D | 无证据时合理拒答 | 0.25 |

GRPO 会在这一组内部计算相对优势：

- B 明显优于组内平均，增强其行为概率。
- C 明显差于组内平均，抑制其行为概率。
- A、D 是否被增强取决于它们相对组内平均的表现。

GRPO 与传统 PPO 的一个重要区别是：GRPO 通常利用同组样本的相对奖励估计优势，不需要单独训练一个 critic/value model，因此更适合具有可自动验证奖励的任务。

本项目适合 GRPO 的原因：

1. 每个目标都可以生成多条不同工具调用轨迹。
2. 最终位置可以用隐藏真值自动计算误差。
3. 工具调用次数、probe 数、非法动作都可以自动计分。
4. 同一任务的不同策略可以直接比较。

### 2.9 为什么需要先 SFT，再 GRPO

如果直接对一个不会使用工具的模型进行 GRPO，大部分 rollout 可能都是：

- 非法 JSON。
- 不存在的工具名称。
- 参数格式错误。
- 无意义重复调用。
- 无法完成 episode。

这会导致奖励普遍很低、组内差异很小，训练难以进行。

推荐流程：

```text
预训练指令模型
  -> SFT：先学会合法、基本合理地使用工具
  -> GRPO：再从多个合法策略中学习更高收益的决策
```

二者分工：

| 方法 | 主要解决的问题 |
| --- | --- |
| SFT | “应该如何合法地完成任务” |
| GRPO | “多个可行策略中哪个收益更高” |

### 2.10 什么是 Oracle

Oracle 是实验阶段可以访问真实位置的理想决策器。它不参与部署，也不能把真值展示给 Agent。

Oracle 用来回答：

> 假设每次都能从现有工具候选中选出最接近真实位置的结果，理论上最多能比 ModuGeo 提升多少？

如果 Oracle 都无法超过 ModuGeo，说明其他工具没有互补信息，Agent 无论通过 SFT 还是 GRPO 都没有值得学习的定位提升空间。

Oracle 还可以用于在训练集上搜索高质量 SFT 教师轨迹，但必须保证生成给模型的输入不包含真实位置。

### 2.11 什么是标签泄漏

标签泄漏是指模型在训练或评测时看到了本不应该知道的答案信息。

当前代码中的 SFT 状态包含：

```json
{
  "truth_region": "北京",
  "truth_city": "北京"
}
```

模型看到真实城市后再选择工具，评测结果没有意义。正确设计必须将数据分成：

```text
模型可见：目标特征、工具状态、工具结果
奖励侧私有：真实经纬度、真实城市、候选误差
```

### 2.12 什么是 LoRA/QLoRA

完整微调会更新模型的全部参数，显存和计算成本较高。

- **LoRA**：冻结大部分原模型参数，只训练少量低秩适配参数。
- **QLoRA**：在量化模型基础上使用 LoRA，进一步降低显存需求。

对于本毕业设计，建议使用 Qwen 1.5B 或 3B 指令模型配合 LoRA/QLoRA。研究重点是 Agent 环境、数据和奖励，不需要为了模型规模牺牲完整实验。

### 2.13 什么是 DPO，它与 GRPO 有什么区别

DPO 是一种偏好优化方法。数据通常是：

```json
{
  "prompt": "当前任务",
  "chosen": "较好的回答或轨迹",
  "rejected": "较差的回答或轨迹"
}
```

DPO 学习偏好对，不需要在线环境 rollout，训练相对简单。GRPO 则让当前模型在环境中生成多条轨迹，再根据自动奖励进行优化。

本项目可将 DPO 作为对比方法：

- SFT：学习教师示范。
- DPO：学习好轨迹优于坏轨迹。
- GRPO：通过环境 rollout 和可验证奖励继续探索策略。

### 2.14 一条完整训练链路示例

以一个 ModuGeo 置信度较低的 IPv6 目标为例：

#### 第一步：准备隐藏真值

```json
{"task_id": "task-1", "truth_lat": 39.90, "truth_lon": 116.32}
```

真值只保留在奖励侧。

#### 第二步：构建模型可见任务

```json
{
  "task_id": "task-1",
  "modugeo_candidate": "candidate-m",
  "modugeo_confidence": 0.42,
  "active_constraint_count": 8,
  "remaining_steps": 4
}
```

#### 第三步：生成 SFT 教师轨迹

教师通过训练真值发现主动定位候选更优，生成不含真值的合法工具调用示范。

#### 第四步：训练 SFT

模型学习在类似状态下检查并调用主动定位。

#### 第五步：执行 GRPO rollout

SFT 模型针对该任务采样多条轨迹，包括立即停止、主动定位、被动定位等。

#### 第六步：计算奖励

环境根据隐藏真值计算每条轨迹的定位误差和成本。

#### 第七步：GRPO 更新

模型提高高奖励工具决策的概率，降低错误融合和无效调用概率。

#### 第八步：独立测试

在模型从未见过的前缀上评测定位误差、调用成本和策略稳定性。

## 3. 研究目标与假设

### 3.1 核心研究问题

> 在主动与被动定位证据覆盖不足、质量不稳定的条件下，经过 SFT 与 GRPO 训练的 LLM Agent，能否学习工具适用性判断、多轮取证和动态停止，并以可控成本改善 ModuGeo 的定位结果？

### 3.2 可检验假设

- **H1：工具环境成立性。** 经过数据适配和质量过滤后，至少一种主动或被动工具能够为部分样本提供相对 ModuGeo 的可靠互补候选。
- **H2：SFT 冷启动有效性。** SFT 能显著提高合法工具调用率、工具适用性识别率和停止决策准确率。
- **H3：GRPO 决策有效性。** SFT + GRPO 在成本约束下优于 SFT-only、Prompt-only、规则调度和固定全工具调用。
- **H4：尾部纠错有效性。** Agent 的主要收益体现在降低 ModuGeo 的 P90/P95 误差和提高尾部样本挽救率，而不是盲目改变所有预测。
- **H5：泛化有效性。** Agent 在未见 `/48`、未见 ASN 和工具缺失条件下仍能保持稳定决策。

### 3.3 主要贡献定位

1. 面向 IPv6 定位的可验证多轮 Agent 环境。
2. 工具适用性感知的动作、观察与质量控制机制。
3. 无标签泄漏的 SFT 轨迹构造方法。
4. 面向 ModuGeo 尾部纠错和工具成本控制的 GRPO 奖励。

## 4. 当前数据与系统基础

### 4.1 当前已适配数据

| 数据文件 | 数据行数 | 作用 |
| --- | ---: | --- |
| `targets.csv` | 929 | 当前定位目标与真值 |
| `modugeo_predictions.csv` | 929 | ModuGeo 基础候选 |
| `traces.csv` | 58,363 hops | 主动路径与 RTT 观察 |
| `probes.csv` | 3 | 当前主动探针 |
| `landmarks.csv` | 2,290 | 潜在主动约束来源 |
| `metadata.csv` | 106 | Prefix、ASN、组织与注册位置 |
| `rdns.csv` | 212 | 已采集 PTR 记录 |
| TrustGeo 原始地理样本 | 83,012 | 扩展训练任务池的候选来源 |

当前 E01 使用 325 个测试 IP，ModuGeo Median 为 31.8 km、Mean 为 68.0 km、P90 为 140.9 km。当前其他工具尚未构成稳定互补证据。

### 4.2 当前代码与训练差距

| 当前实现 | 问题 | 目标状态 |
| --- | --- | --- |
| 一次性 `stop/rdns/active/passive/all` 分类 | 无多轮观察与动态停止 | 多轮环境中的结构化动作 |
| SFT 输入包含真实地区与城市 | 标签泄漏 | 真值完全位于奖励侧 |
| 每个策略只输出单步轨迹 | 无长期信用分配 | 完整 episode 轨迹 |
| 离线平均奖励策略 | 不是真正 RL | 多轨迹采样与 GRPO 更新 |
| 工具失败返回不统一 | Agent 无法学习适用性 | 统一状态、失败原因和质量字段 |

## 5. 数据集总体设计

训练数据必须分为五个逻辑层，禁止把所有字段放在一个 JSON 中交给模型。

```text
L1 原始事实层
  -> L2 划分与规范化层
     -> L3 工具回放环境层
        -> L4 SFT 教师轨迹层
        -> L5 GRPO 任务与隐藏奖励层
```

### 5.1 L1：原始事实层

每个原始目标记录包含：

```json
{
  "target_ip": "240e:...",
  "truth": {
    "lat": 39.90948,
    "lon": 116.32864,
    "region": "北京",
    "city": "北京",
    "source": "gps",
    "observed_at": "2026-01-17"
  },
  "network": {
    "prefix": "240e:504::/30",
    "asn": "AS4134",
    "operator": "China Telecom"
  }
}
```

该层可以包含真实位置，但仅允许数据构建器、Oracle、奖励计算器和评测器访问。

### 5.2 L2：规范化与数据划分层

必须先划分，再构建工具索引、邻居证据和教师轨迹，防止测试信息泄漏。

推荐划分：

| 划分 | 比例 | 用途 |
| --- | ---: | --- |
| Train | 70% | 工具索引、SFT、GRPO |
| Validation | 10% | 奖励权重、早停和超参数 |
| Test-ID | 10% | 同分布测试 |
| Test-Prefix-OOD | 10% | 未见 `/48` 或 `/56` 前缀测试 |

附加泛化测试：

- 未见 ASN/运营商。
- 不同时间快照。
- 不同工具缺失组合。
- ModuGeo 高误差尾部样本。

划分规则：

1. 同一 `/48` 默认只能出现在一个划分中。
2. 同设备、同 MAC、同目标 IP 的重复样本必须去重或归入同一划分。
3. 测试划分不能进入前缀邻居、同 ASN 历史位置或教师轨迹搜索索引。
4. 真值字段不能进入模型可见 observation。
5. 每次数据构建保存输入文件哈希、随机种子和划分清单。

### 5.3 L3：工具回放环境层

为每个目标离线执行或回放所有允许的工具，形成可复现环境。每个工具返回统一 `ToolObservation`：

```json
{
  "tool": "active_triangulation",
  "status": "ok",
  "applicability": "conditional",
  "failure_reason": null,
  "candidate": {
    "candidate_id": "active:candidate:001",
    "lat": 39.91,
    "lon": 116.39,
    "region": "北京",
    "city": null,
    "granularity": "region"
  },
  "quality": {
    "constraint_count": 8,
    "intersection_area_km2": 310.5,
    "geometry_score": 0.78,
    "confidence": 0.63
  },
  "cost": {
    "tool_calls": 1,
    "probe_count": 8,
    "latency_ms": 25
  }
}
```

失败结果同样需要保留：

```json
{
  "tool": "rdns",
  "status": "unavailable",
  "applicability": "not_applicable",
  "failure_reason": "coverage_miss",
  "candidate": null,
  "quality": {"confidence": 0.0},
  "cost": {"tool_calls": 1, "probe_count": 0, "latency_ms": 3}
}
```

该层的作用：

- 支持确定性离线训练和重复 rollout。
- 让 Agent 学习工具是否适用，而不仅是学习工具名称。
- 为 Oracle 审计、SFT 教师搜索和 GRPO 环境提供统一接口。

### 5.4 Agent 可见状态

Agent 每一步只能看到：

```json
{
  "task_id": "geoagent-train-000001",
  "target": {
    "ip_features": {"prefix_48": "240e:504:1910::/48"},
    "asn": "AS4134",
    "operator": "China Telecom"
  },
  "base_prediction": {
    "candidate_id": "modugeo:000001",
    "lat": 39.90,
    "lon": 116.28,
    "confidence": 0.71
  },
  "tool_state": {
    "rdns": {"known_available": false},
    "active": {"constraint_count": 8},
    "passive": {"enabled": true}
  },
  "history": [],
  "remaining_budget": {"steps": 4, "probe_count": 12}
}
```

禁止出现：

- `truth_lat`、`truth_lon`。
- `truth_region`、`truth_city`。
- 根据测试真值计算的候选误差。
- 来自测试集历史样本的近邻统计。

## 6. 工具与数据集不匹配问题

该问题是 SFT/GRPO 主线成立的必要条件之一。

### 6.1 rDNS

问题：

- 中国 ISP 的 IPv6 PTR 结构性稀疏。
- 当前评测样本未匹配到有效 rDNS 结果。
- 即使命中 PTR，也不一定包含地理语义。

解决路径：

1. 使用不同 resolver 验证真实 PTR 上限。
2. 对已有 PTR 进行地名、机场码、机房和运营商解析。
3. 输出直接 PTR、同前缀弱证据和不可用三种状态。
4. 将 rDNS 定位为低覆盖、高潜在精度工具，而不是默认工具。
5. 若有效覆盖仍低，保留为 Agent 适用性判断与负面结果。

### 6.2 主动定位

问题：

- 当前只有 3 个 probes。
- CBG 约束不足且几何分布差。
- 直接融合会显著恶化 ModuGeo。

解决路径：

1. 验证 2,290 个 landmarks 与 traceroute 跳点能否形成有效约束。
2. 对 RTT、位置、路径方向和可达性做质量过滤。
3. 构建不同约束子集与求解器候选。
4. 输出约束数量、几何质量、交集范围等可供 Agent 判断的特征。
5. 训练 Agent 学习何时主动定位值得调用、哪个结果值得使用。

### 6.3 被动定位

问题：

- 当前缺少可用 IPv6 IPDB。
- WHOIS/BGP 通常是注册位置，不是实际位置。

解决路径：

1. 评估可合法使用的 IPv6 IPDB。
2. 将 WHOIS、BGP、ASN、运营商和训练集历史位置构造成分级被动证据。
3. 标注国家、省份、城市、坐标等证据粒度。
4. 严格隔离训练与测试索引。
5. 不允许粗粒度注册地直接伪装成精确坐标。

### 6.4 工具效用门禁

在生成大量 SFT/GRPO 数据前，执行 Oracle 审计：

```text
Oracle error = min(error(candidate_1), ..., error(candidate_n))
```

必须报告：

- 原始工具和适配后工具的有效覆盖率。
- Oracle Median、P90、P95。
- 相比 ModuGeo 可修正的目标比例。
- ModuGeo 尾部样本挽救率。
- 错误候选率和融合退化风险。

进入完整 Agent 训练的最低条件：

1. 至少一种非 ModuGeo 工具能在部分样本上产生可靠互补候选。
2. 适配后 Oracle 相比 ModuGeo 有明确提升。
3. 工具质量特征能够区分高价值与高风险结果。

如果不满足，必须先继续解决工具环境问题，不能直接训练 GRPO。

## 7. 多轮 Agent 环境设计

### 7.1 动作空间

```json
[
  {"action": "inspect_tool_applicability", "arguments": {"tool": "active"}},
  {"action": "query_rdns", "arguments": {}},
  {"action": "run_active_solver", "arguments": {"strategy": "quality_filtered"}},
  {"action": "query_passive_evidence", "arguments": {"granularity": "region"}},
  {"action": "inspect_result_quality", "arguments": {"tool": "active"}},
  {"action": "compare_candidates", "arguments": {}},
  {"action": "finalize", "arguments": {"candidate_id": "modugeo:000001", "confidence": 0.71}},
  {"action": "abstain", "arguments": {"granularity": "city"}}
]
```

最终定位应优先选择已有候选，而不是让 LLM 自由生成任意经纬度。

### 7.2 Episode 状态转换

```text
reset(task_id)
  -> 初始观测
step(action)
  -> 工具执行或环境回放
  -> 新观测、成本、终止状态
  -> Agent 下一步动作
finalize/abstain
  -> 隐藏奖励计算
```

### 7.3 终止条件

- Agent 执行 `finalize`。
- Agent 执行 `abstain`。
- 达到最大步骤数。
- 超出 probe 或工具成本预算。
- 连续非法动作达到阈值。

## 8. SFT 数据集构造

### 8.1 SFT 的目标

SFT 负责教会模型：

- 工具调用语法。
- 工具适用性与失败状态理解。
- 基本证据比较。
- 简单场景停止。
- 低质量结果过滤。

SFT 不负责保证最终策略最优，这部分由 GRPO 优化。

### 8.2 教师轨迹来源

1. **规则教师**：生成合法、基础的工具调用流程。
2. **Oracle/束搜索教师**：利用训练集隐藏真值搜索高收益动作序列。
3. **高质量模型教师**：在严格检查后补充困难轨迹。
4. **负面轨迹修正**：将非法调用、盲目全调用和错误融合改写为正确轨迹。

教师可以访问训练真值用于选择轨迹，但输出给 SFT 模型的 messages 中不能包含真值。

### 8.3 SFT JSONL 格式

每行是一条完整多轮轨迹，采用 messages 格式：

```json
{
  "id": "sft-train-000001",
  "split": "train",
  "messages": [
    {
      "role": "system",
      "content": "你是 IPv6 地理位置推断 Agent。只能调用允许的工具或从候选中选择最终位置。"
    },
    {
      "role": "user",
      "content": "{\"task_id\":\"geoagent-train-000001\",\"base_prediction\":{\"candidate_id\":\"modugeo:000001\",\"confidence\":0.42},\"tool_state\":{\"rdns\":{\"known_available\":false},\"active\":{\"constraint_count\":8},\"passive\":{\"enabled\":true}},\"remaining_budget\":{\"steps\":4,\"probe_count\":12}}"
    },
    {
      "role": "assistant",
      "content": "{\"action\":\"inspect_tool_applicability\",\"arguments\":{\"tool\":\"active\"}}"
    },
    {
      "role": "tool",
      "name": "inspect_tool_applicability",
      "content": "{\"tool\":\"active\",\"applicability\":\"conditional\",\"quality\":{\"constraint_count\":8,\"geometry_score\":0.78}}"
    },
    {
      "role": "assistant",
      "content": "{\"action\":\"run_active_solver\",\"arguments\":{\"strategy\":\"quality_filtered\"}}"
    },
    {
      "role": "tool",
      "name": "run_active_solver",
      "content": "{\"status\":\"ok\",\"candidate\":{\"candidate_id\":\"active:001\",\"region\":\"北京\"},\"quality\":{\"confidence\":0.63}}"
    },
    {
      "role": "assistant",
      "content": "{\"action\":\"compare_candidates\",\"arguments\":{}}"
    },
    {
      "role": "tool",
      "name": "compare_candidates",
      "content": "{\"preferred_candidate\":\"active:001\",\"support\":\"active constraints are consistent; ModuGeo confidence is low\"}"
    },
    {
      "role": "assistant",
      "content": "{\"action\":\"finalize\",\"arguments\":{\"candidate_id\":\"active:001\",\"confidence\":0.63}}"
    }
  ],
  "metadata": {
    "difficulty": "hard",
    "teacher": "oracle_beam_search",
    "available_tools": ["modugeo", "active", "passive"],
    "trajectory_length": 4
  }
}
```

注意：

- `metadata` 不参与模型输入。
- 不保存教师的隐藏真值推理文本。
- 可以保留简短、可验证的决策理由，但不把长篇思维链作为优化目标。
- 工具返回必须来源于真实执行或确定性回放。

### 8.4 SFT 数据配比

建议初始配比：

| 轨迹类型 | 比例 |
| --- | ---: |
| ModuGeo 足够可靠，立即停止 | 25% |
| 单工具有效纠错 | 25% |
| 工具不可用或低质量，正确跳过 | 20% |
| 多工具冲突与候选比较 | 15% |
| 拒答或降低粒度 | 10% |
| 格式修复与边界场景 | 5% |

必须按任务难度、工具类型和动作类型平衡采样，避免模型只学习 `stop`。

### 8.5 SFT 质量门禁

- 真值泄漏扫描通过。
- JSON schema 合法率达到 100%。
- 每个工具调用都有对应真实/回放结果。
- 轨迹动作可在环境中重放。
- 训练集与测试集前缀无交叉。
- `stop`、工具调用、拒答等动作分布不过度失衡。

## 9. GRPO 数据与训练格式

### 9.1 GRPO 的数据职责分离

GRPO 数据必须拆成模型可见任务与奖励侧私有真值。

#### 模型可见任务文件：`grpo_prompts.jsonl`

```json
{
  "task_id": "grpo-train-000001",
  "split": "train",
  "prompt": [
    {
      "role": "system",
      "content": "你是 IPv6 地理位置推断 Agent。通过工具调用完成定位，不得访问隐藏真值。"
    },
    {
      "role": "user",
      "content": "{\"target\":{\"prefix_48\":\"240e:504:1910::/48\",\"asn\":\"AS4134\"},\"base_prediction\":{\"candidate_id\":\"modugeo:000001\",\"confidence\":0.42},\"remaining_budget\":{\"steps\":4,\"probe_count\":12}}"
    }
  ],
  "environment_ref": "geoagent-env:train:v1",
  "max_steps": 4,
  "reward_profile": "geoagent_reward_v1"
}
```

#### 奖励侧私有文件：`grpo_private_truth.jsonl`

```json
{
  "task_id": "grpo-train-000001",
  "truth": {
    "lat": 39.90948,
    "lon": 116.32864,
    "region": "北京",
    "city": "北京"
  },
  "modugeo_error_km": 42.6,
  "allowed_candidate_ids": ["modugeo:000001", "active:001", "passive:003"]
}
```

私有文件只能由环境和 reward function 访问，不能进入 prompt、日志文本或模型上下文。

#### Rollout 轨迹文件：`grpo_rollouts.jsonl`

```json
{
  "task_id": "grpo-train-000001",
  "group_id": "grpo-train-000001-step-000120",
  "rollout_id": 3,
  "trajectory": [
    {
      "step": 0,
      "action": {"name": "inspect_tool_applicability", "arguments": {"tool": "active"}},
      "observation_ref": "obs:grpo-train-000001:0",
      "cost": {"tool_calls": 0, "probe_count": 0}
    },
    {
      "step": 1,
      "action": {"name": "run_active_solver", "arguments": {"strategy": "quality_filtered"}},
      "observation_ref": "obs:grpo-train-000001:1",
      "cost": {"tool_calls": 1, "probe_count": 8}
    },
    {
      "step": 2,
      "action": {"name": "finalize", "arguments": {"candidate_id": "active:001", "confidence": 0.63}},
      "observation_ref": null,
      "cost": {"tool_calls": 0, "probe_count": 0}
    }
  ],
  "reward": {
    "total": 0.71,
    "geo": 0.62,
    "improve": 0.35,
    "applicability": 0.10,
    "tail": 0.0,
    "cost_penalty": -0.16,
    "invalid_penalty": 0.0,
    "bad_fusion_penalty": 0.0
  },
  "final": {
    "candidate_id": "active:001",
    "error_km": 15.4,
    "done_reason": "finalize"
  }
}
```

### 9.2 GRPO 组采样

对于每个 `task_id`，采样 `G` 条轨迹：

```text
同一 prompt
  -> rollout 1: 立即 stop
  -> rollout 2: 调用 active 后 finalize
  -> rollout 3: 调用 passive 后 finalize
  -> rollout 4: 无效全工具调用
  -> 组内相对奖励归一化
```

建议从 `G=4` 或 `G=8` 起步。只有组内存在奖励差异时，GRPO 才能获得有效学习信号。

### 9.3 奖励函数

```text
R = R_geo + R_improve + R_applicability + R_tail + R_granularity
    - R_cost - R_invalid - R_bad_fusion - R_unsupported
```

推荐定义：

```text
R_geo = exp(-error_agent / tau_geo)
R_improve = clip((error_modugeo - error_agent) / tau_improve, -1, 1)
R_cost = lambda_tool * tool_calls + lambda_probe * probe_count + lambda_step * steps
```

其他奖励：

- `R_applicability`：正确识别工具不可用、条件可用或高质量。
- `R_tail`：修正 ModuGeo P90/P95 样本。
- `R_granularity`：正确选择坐标、城市、省份或拒答。
- `R_invalid`：非法 JSON、非法工具、超预算。
- `R_bad_fusion`：融合低质量工具后导致结果退化。
- `R_unsupported`：最终候选不在环境候选集合或缺少证据。

奖励设计原则：

1. 不奖励冗长思维文本。
2. 强惩罚将正确 ModuGeo 结果改坏的行为。
3. 避免覆盖奖励过高导致始终输出结果。
4. 监控始终停止、始终全调用、始终拒答等策略退化。
5. 在 Validation 集上确定奖励权重，不使用 Test 集调参。

### 9.4 GRPO 课程训练

| 阶段 | 训练内容 | 进入条件 |
| --- | --- | --- |
| G1 | 合法动作、停止与继续 | SFT 合法动作率达标 |
| G2 | 工具适用性判断 | 工具状态标签可用 |
| G3 | 单工具纠错 | 至少一种工具有互补候选 |
| G4 | 多轮多工具决策 | 单工具策略稳定 |
| G5 | 未见前缀与尾部样本 | 常规验证集无明显退化 |

## 10. 必须解决的问题与解决路径

| 优先级 | 必须解决的问题 | 当前影响 | 解决路径 | 完成门禁 |
| --- | --- | --- | --- | --- |
| P0 | SFT/轨迹包含真值泄漏 | 训练结果无效 | 分离可见状态与私有真值；增加泄漏扫描 | 可见数据无真值字段 |
| P0 | 非 ModuGeo 工具无互补价值 | Agent 退化为固定动作 | 工具适配、质量过滤、Oracle 审计 | Oracle 明显优于 ModuGeo |
| P0 | 当前只有单步调度 | 无法训练多轮 Agent | 实现 `reset/step/finalize` 环境 | 轨迹可重放 |
| P0 | 当前并未实现 GRPO | 无真实 RL 贡献 | 接入 GRPO trainer 与环境 rollout | 能完成小规模稳定训练 |
| P1 | 原始 929 目标规模偏小 | 易过拟合 | 从 83,012 原始样本构建训练任务池 | 获得可用训练/验证划分 |
| P1 | 主动约束不足 | CBG 误差高 | 验证 landmarks、质量过滤和求解器 | 有效覆盖和 Oracle 提升 |
| P1 | 被动证据缺失或粗糙 | 被动工具 0% 覆盖 | 多源被动证据与粒度标注 | 可输出可靠候选/不可用状态 |
| P1 | rDNS 结构性稀疏 | 调用多数无收益 | 确认覆盖上限，训练适用性识别 | 无效调用率下降 |
| P1 | 候选与工具状态 schema 不统一 | 环境难以训练 | 统一 `ToolObservation` 和候选 ID | 全工具通过 schema 校验 |
| P1 | 奖励可能被投机 | GRPO 策略退化 | 奖励分解、策略分布监控、对抗样本 | 无固定动作塌缩 |
| P2 | 算力限制 | 难以完成多轮 RL | Qwen 1.5B/3B + LoRA，短轨迹，先小规模 | 小模型完成完整消融 |
| P2 | 实验不可复现 | 论文证据不足 | 固化数据哈希、配置、W&B runs/artifacts | 每个结论可回溯 |

## 11. 实施模块与建议目录

```text
GraduatePaper/
├── data/
│   └── geoagent/
│       ├── splits/
│       ├── environment/
│       ├── sft/
│       └── grpo/
├── src/agentic_ipv6_geo/
│   ├── environment/
│   │   ├── geoagent_env.py
│   │   ├── schemas.py
│   │   └── reward.py
│   ├── data/
│   │   ├── build_splits.py
│   │   ├── build_tool_replay.py
│   │   ├── build_sft_dataset.py
│   │   └── build_grpo_dataset.py
│   ├── training/
│   │   ├── train_sft.py
│   │   └── train_grpo.py
│   └── evaluation/
│       ├── oracle_audit.py
│       └── agent_evaluator.py
├── configs/
│   ├── geoagent_data.json
│   ├── geoagent_sft.json
│   └── geoagent_grpo.json
└── experiments/
    ├── E05_tool_utility_audit/
    ├── E06_geoagent_environment/
    ├── E07_sft/
    └── E08_grpo/
```

## 12. 实验设计

### 12.1 对比方法

- ModuGeo。
- 固定调用全部工具。
- 规则调度。
- 当前单步 Qwen 调度器。
- Prompt-only 多轮 Agent。
- SFT-only Agent。
- SFT + DPO Agent。
- SFT + GRPO Agent。
- Oracle 上界。

### 12.2 主要指标

定位效果：

- Median、Mean、P90、P95 error。
- 相对 ModuGeo 改善率与退化率。
- 尾部样本挽救率。
- 城市级、省级准确率。

Agent 能力：

- 合法动作率。
- 工具适用性识别准确率。
- 有效工具调用率。
- 无效调用率。
- 平均步骤、probe 数和成本。
- 停止决策准确率。
- 拒答后的 selective risk。

训练稳定性：

- 组内奖励方差。
- KL divergence。
- 各动作占比。
- 奖励各分量。
- 固定动作塌缩比例。
- Validation 相对 ModuGeo 的退化比例。

### 12.3 必做消融

- 原始工具与适配后工具。
- 单步调度与多轮 Agent。
- Prompt-only、SFT、SFT + GRPO。
- 去掉工具适用性观察。
- 去掉 ModuGeo 相对改善奖励。
- 去掉成本惩罚。
- 去掉错误融合惩罚。
- 去掉拒答动作。

## 13. W&B 实验与数据管理

W&B 项目：

- Entity/Team：`powerli_team`
- Project：`GraduateProject`
- URL：`https://wandb.ai/powerli_team/GraduateProject`

### 13.1 Run 组织

建议使用：

| 字段 | 示例 |
| --- | --- |
| `group` | `E07_sft_qwen3b`、`E08_grpo_reward_v1` |
| `job_type` | `data_build`、`oracle_audit`、`sft`、`grpo`、`evaluation` |
| `tags` | `prefix-ood`、`tool-adapted`、`qwen3b`、`lora` |
| `config` | 数据版本、模型、奖励权重、seed、最大步数 |

### 13.2 Artifact 组织

| Artifact | 类型 | 内容 |
| --- | --- | --- |
| `geoagent-raw-manifest` | `dataset` | 原始文件哈希和来源 |
| `geoagent-splits` | `dataset` | Train/Validation/Test 清单 |
| `geoagent-tool-replay` | `dataset` | 工具观察与候选 |
| `geoagent-sft` | `dataset` | SFT JSONL |
| `geoagent-grpo-prompts` | `dataset` | GRPO 可见任务 |
| `geoagent-private-truth` | `dataset-private` | 隐藏真值，仅限受控环境 |
| `geoagent-sft-model` | `model` | SFT LoRA checkpoint |
| `geoagent-grpo-model` | `model` | GRPO checkpoint |
| `geoagent-evaluation` | `evaluation` | 预测、指标和图表 |
| `geoagent-research-report` | `report` | 本报告 |

禁止将 API Key、未授权私有数据和包含测试真值的模型输入上传为公开 artifact。

### 13.3 关键日志

SFT：

- `train/loss`
- `eval/loss`
- `eval/json_valid_rate`
- `eval/tool_call_valid_rate`

GRPO：

- `train/reward_total`
- `train/reward_geo`
- `train/reward_improve`
- `train/reward_applicability`
- `train/cost_penalty`
- `train/group_reward_std`
- `train/kl`
- `policy/action_stop_rate`
- `policy/action_tool_rate`
- `policy/abstain_rate`

最终评测：

- `eval/median_error_km`
- `eval/p90_error_km`
- `eval/p95_error_km`
- `eval/improvement_rate`
- `eval/regression_rate`
- `eval/tail_rescue_rate`
- `eval/invalid_tool_call_rate`
- `eval/avg_tool_cost`

## 14. 分阶段实施计划

### 阶段 0：修复训练数据有效性

任务：

1. 删除当前 SFT 和 trajectory 中的真值字段。
2. 定义统一 ToolObservation、Action 和 Episode schema。
3. 实现数据泄漏扫描器和 schema 校验器。

产物：

- 数据 schema。
- 无泄漏样例数据。
- 校验测试。

### 阶段 1：工具环境可行性

任务：

1. 完成 rDNS、主动定位、被动定位适配实验。
2. 构建工具回放数据。
3. 运行 Oracle 效用审计。

进入下一阶段条件：

- 至少一种非 ModuGeo 工具存在可靠互补价值。
- 工具状态与质量特征可用于判断适用性。

### 阶段 2：多轮环境与教师轨迹

任务：

1. 实现环境 `reset/step/finalize`。
2. 实现动作预算与工具回放。
3. 使用规则、Oracle 和束搜索生成教师轨迹。

进入下一阶段条件：

- 轨迹可确定性重放。
- 教师轨迹优于随机和固定全调用。
- 无真值泄漏。

### 阶段 3：SFT

任务：

1. 使用 Qwen 1.5B/3B + LoRA 训练。
2. 评测合法调用、适用性识别和停止能力。
3. 生成 GRPO 冷启动模型。

进入下一阶段条件：

- 合法动作率达到可用水平。
- Agent 不出现明显固定动作塌缩。
- SFT 至少达到规则调度水平。

### 阶段 4：GRPO

任务：

1. 小规模验证 reward function。
2. 逐步增加任务难度和多轮长度。
3. 监控奖励投机和策略退化。

完成条件：

- 相比 SFT-only 在 Validation 上有稳定改善。
- Test 集上不显著恶化 ModuGeo。
- 完成奖励与动作空间消融。

## 15. 风险、停止条件与替代结论

### 15.1 主要风险

- 工具适配后仍无互补定位价值。
- 83,012 原始样本无法全部构造成有工具观察的任务。
- SFT 数据动作分布失衡，模型只学习停止。
- GRPO 奖励被投机或组内奖励方差过低。
- 未见前缀上历史证据失效。
- 算力不足以支持大模型多轮 rollout。

### 15.2 停止条件

- 如果 Oracle 无法明显超过 ModuGeo，暂停完整调度 GRPO。
- 如果工具只能产生高风险候选，将研究收缩为适用性判断、风险控制和可信停止。
- 如果 3B 模型即可完成核心消融，不为追求模型规模牺牲实验完整性。
- 如果 rDNS 结构性覆盖不足，保留其负面结论，不继续投入无效采集。

### 15.3 可接受的论文结论

即使最终 Median 未明显提升，以下结果仍具有研究价值：

1. SFT/GRPO Agent 显著降低无效工具调用和融合退化。
2. Agent 能识别 ModuGeo 尾部风险并提高选择性预测可靠性。
3. 系统明确量化不同 IPv6 定位工具在当前数据集上的适用边界。
4. 证明可验证强化学习在网络工具 Agent 中的收益或限制。

## 16. 最终建议

最优先工作不是立即启动 SFT 或 GRPO，而是完成以下三个 P0 任务：

1. 修复当前 SFT/trajectory 的真值泄漏。
2. 建立可重放的多轮环境和统一工具 schema。
3. 完成工具适配后的 Oracle 效用审计。

在此基础上，先用 Qwen 1.5B/3B + LoRA 完成小规模 SFT，再进行短轨迹 GRPO。整个过程通过 W&B 记录数据版本、训练曲线、奖励分解、模型 artifact 和最终评测，确保所有论文结论可追溯。

## 17. 关键词

中文关键词：

`大语言模型智能体`、`IPv6 地理位置推断`、`监督微调`、`群组相对策略优化`、`可验证强化学习`、`多轮工具调用`、`工具适用性`、`主动与被动定位`、`尾部错误修正`、`可信拒答`

英文关键词：

`LLM Agent`、`IPv6 Geolocation`、`Supervised Fine-Tuning`、`Group Relative Policy Optimization`、`Verifiable Reinforcement Learning`、`Multi-turn Tool Use`、`Tool Applicability`、`Active and Passive Geolocation`、`Tail Error Correction`、`Selective Prediction`
