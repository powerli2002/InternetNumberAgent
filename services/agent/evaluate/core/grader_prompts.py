"""自定义评分提示模板。"""

from __future__ import annotations

LAST_MESSAGE_TASK_DESCRIPTION = """
评估互联网号码资源问答系统的最终回复质量，关注准确性、完整性、可解释性与表达清晰度。
""".strip()

LAST_MESSAGE_SCENARIO = """
用户提出关于 AS、前缀、组织归属、RDAP/WHOIS/BGP 的问题，系统需给出可读结论并体现证据意识。
""".strip()

# 自定义 LastMessage 评分模板（0~1）。
LAST_MESSAGE_QUALITY_TEMPLATE = """
你是评测专家。请评估最终回复的质量，输出 0 到 1 的分数。

评分参考：
{rubrics_text}

评测输入：
- 用户问题：{query}
- 最终回复：{response}
- 证据摘要：{evidence_summary}

评分要求：
1) 回复是否准确回答问题。
2) 表达是否清晰，是否易于理解。
3) 是否体现证据意识（例如说明数据来源或检索依据）。
4) 若信息不足，是否明确指出限制，而非臆造。

输出格式（严格 JSON）：
{{
  "reason": "简明说明",
  "score": 0.0
}}
""".strip()

# 自定义 OutcomeConsistency 评分模板（0~1）。
OUTCOME_CONSISTENCY_TEMPLATE = """
你是评测专家。请评估最终回复与系统执行结果的一致性，输出 0 到 1 的分数。

评测输入：
- 用户问题：{query}
- 最终回复：{response}
- 执行证据摘要：{evidence_summary}
- 参考答案（可为空）：{reference_response}

评分规则：
1) 优先检查回复是否与执行证据一致。
2) 若提供了参考答案，再额外检查与参考答案的一致性。
3) 若参考答案为空，不得因此扣分；仅依据证据一致性评分。
4) 回复出现明显幻觉、与证据矛盾或自相矛盾应显著降分。

输出格式（严格 JSON）：
{{
  "reason": "简明说明",
  "score": 0.0
}}
""".strip()
