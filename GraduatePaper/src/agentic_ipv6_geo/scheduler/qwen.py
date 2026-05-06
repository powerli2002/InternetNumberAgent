from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from agentic_ipv6_geo.common.logger import JsonlLogger
from agentic_ipv6_geo.common.models import GeoResult, Target
from agentic_ipv6_geo.fusion import FusionTool
from agentic_ipv6_geo.tools import ActiveTriangulationTool, ModuGeoTool, PassiveIpDbGeoTool, RDnsGeoTool, WhoisBgpContextTool


class QwenToolUseScheduler:
    """受限 LLM baseline：Qwen 只选择工具动作，不直接预测经纬度。"""

    ACTIONS = {"stop", "rdns", "active", "passive", "all"}

    def __init__(
        self,
        modugeo: ModuGeoTool,
        rdns: RDnsGeoTool,
        active_triangulation: ActiveTriangulationTool,
        whois_bgp: WhoisBgpContextTool,
        passive_ipdb: PassiveIpDbGeoTool,
        fusion: FusionTool,
        config: dict[str, Any] | None = None,
        service_config: dict[str, Any] | None = None,
        logger: JsonlLogger | None = None,
    ):
        self.modugeo = modugeo
        self.rdns = rdns
        self.active_triangulation = active_triangulation
        self.whois_bgp = whois_bgp
        self.passive_ipdb = passive_ipdb
        self.fusion = fusion
        self.config = config or {}
        self.service_config = service_config or {}
        self.logger = logger or JsonlLogger(None)
        self.enabled = bool(self.config.get("enabled", False))
        self.model = str(self.config.get("model") or self.service_config.get("model") or "qwen3.5")
        self.max_steps = int(self.config.get("max_steps", 4))

    def run(self, target: Target) -> GeoResult:
        base = self.modugeo.run(target)
        context = self._context(target, base)
        action, prompt, raw_response, failure_reason = self._select_action(context)
        self.logger.log("qwen_action", target_ip=target.ip, action=action, failure_reason=failure_reason)
        result = self._run_action(target, base, action)
        result.evidence["scheduler"] = {
            "type": "qwen_tool_use_baseline",
            "model": self.model,
            "enabled": self.enabled,
            "selected_action": action,
            "prompt": prompt,
            "raw_response": raw_response,
            "failure_reason": failure_reason,
            "context": context,
        }
        return result

    def _select_action(self, context: dict[str, Any]) -> tuple[str, str, str | None, str | None]:
        prompt = self._prompt(context)
        if not self.enabled:
            return "stop", prompt, None, "Qwen baseline 未启用"
        api_key_env = self.service_config.get("api_key_env", "QWEN_API_KEY")
        base_url_env = self.service_config.get("base_url_env", "QWEN_BASE_URL")
        api_key = os.environ.get(str(api_key_env))
        base_url = os.environ.get(str(base_url_env))
        if not api_key or not base_url:
            return "stop", prompt, None, "缺少 Qwen API key 或 base URL 环境变量"
        try:
            raw = self._call_openai_compatible(base_url, api_key, prompt)
        except Exception as exc:
            return "stop", prompt, None, f"Qwen 调用失败: {exc}"
        action = self._parse_action(raw)
        if action not in self.ACTIONS:
            return "stop", prompt, raw, f"Qwen 返回非法动作: {action}"
        return action, prompt, raw, None

    def _call_openai_compatible(self, base_url: str, api_key: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你只能从 stop, rdns, active, passive, all 中选择一个动作，并返回 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        request = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(request, timeout=int(self.service_config.get("timeout_seconds", 60))) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def _parse_action(self, raw: str) -> str:
        try:
            data = json.loads(raw)
            return str(data.get("action", "")).strip().lower()
        except Exception:
            for action in self.ACTIONS:
                if action in raw.lower():
                    return action
        return ""

    def _run_action(self, target: Target, base: GeoResult, action: str) -> GeoResult:
        results = [base, self.whois_bgp.run(target)]
        if action in {"rdns", "all"}:
            results.append(self.rdns.run(target))
        if action in {"active", "all"}:
            results.append(self.active_triangulation.run(target))
        if action in {"passive", "all"}:
            results.append(self.passive_ipdb.run(target))
        fused = self.fusion.run(results)
        return fused if fused.status == "ok" else base

    def _context(self, target: Target, base: GeoResult) -> dict[str, Any]:
        return {
            "target_ip": target.ip,
            "asn": target.asn,
            "operator": target.operator,
            "modugeo_status": base.status,
            "modugeo_confidence": base.confidence,
            "rdns_available": self.rdns.repo.rdns_for(target.ip) is not None,
            "active_constraint_count": len(self.active_triangulation._constraints(target)),
            "passive_ipdb_enabled": self.passive_ipdb.enabled,
            "allowed_actions": sorted(self.ACTIONS),
        }

    def _prompt(self, context: dict[str, Any]) -> str:
        return (
            "根据以下 IPv6 定位状态选择下一步工具动作。"
            "只能返回 JSON，例如 {\"action\":\"stop\",\"reason\":\"...\"}。"
            "不要输出经纬度。\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
        )
