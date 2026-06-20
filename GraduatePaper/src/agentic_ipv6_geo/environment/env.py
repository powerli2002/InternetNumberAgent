from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

from agentic_ipv6_geo.common.geo import Point, haversine_km
from agentic_ipv6_geo.environment.leakage import assert_no_private_truth
from agentic_ipv6_geo.environment.schemas import AgentAction, PrivateTruth, RewardBreakdown, ToolObservation


class GeoAgentEnv:
    """基于离线工具回放的确定性多轮 Agent 环境。"""

    def __init__(
        self,
        tasks: dict[str, dict[str, Any]],
        replay: dict[str, dict[str, ToolObservation]],
        private_truth: dict[str, PrivateTruth],
        max_steps: int = 4,
        max_probe_count: int = 12,
    ):
        self.tasks = tasks
        self.replay = replay
        self.private_truth = private_truth
        self.max_steps = max_steps
        self.max_probe_count = max_probe_count
        self.task_id: str | None = None
        self.history: list[dict[str, Any]] = []
        self.visible_candidates: dict[str, dict[str, Any]] = {}
        self.steps = 0
        self.probe_count = 0
        self.done = False
        self.invalid_actions = 0

    def reset(self, task_id: str) -> dict[str, Any]:
        if task_id not in self.tasks or task_id not in self.replay or task_id not in self.private_truth:
            raise KeyError(f"未知或不完整的任务：{task_id}")
        self.task_id = task_id
        self.history = []
        self.visible_candidates = {}
        self.steps = 0
        self.probe_count = 0
        self.done = False
        self.invalid_actions = 0
        base = self.replay[task_id].get("modugeo")
        if base and base.candidate:
            self.visible_candidates[base.candidate.candidate_id] = base.candidate.to_dict()
        return self._observation()

    def step(self, action: AgentAction | dict[str, Any]) -> tuple[dict[str, Any], RewardBreakdown | None, bool]:
        if self.task_id is None:
            raise RuntimeError("必须先调用 reset")
        if self.done:
            raise RuntimeError("episode 已结束")
        if isinstance(action, dict):
            action = AgentAction(name=str(action.get("name") or action.get("action") or ""), arguments=action.get("arguments") or {})
        try:
            action.validate()
        except ValueError as exc:
            return self._invalid_step(action, str(exc))

        self.steps += 1
        event: dict[str, Any] = {"step": self.steps, "action": asdict(action)}
        reward = None

        if action.name in {"finalize", "abstain"}:
            reward = self._finish(action, event)
        elif action.name == "compare_candidates":
            event["observation"] = {"candidates": list(self.visible_candidates.values())}
        else:
            tool_id = action.tool_id()
            tool_observation = self.replay[self.task_id].get(tool_id or "")
            if tool_observation is None:
                return self._invalid_step(action, f"任务不存在工具回放结果：{tool_id}")
            if action.name in {"inspect_tool_applicability", "inspect_result_quality"}:
                event["observation"] = {
                    "tool_id": tool_observation.tool_id,
                    "status": tool_observation.status,
                    "applicability": tool_observation.applicability,
                    "failure_type": tool_observation.failure_type,
                    "quality": tool_observation.quality,
                }
            else:
                event["observation"] = tool_observation.to_dict()
                self.probe_count += int(tool_observation.cost.get("probe_count", 0))
                if tool_observation.candidate:
                    self.visible_candidates[tool_observation.candidate.candidate_id] = tool_observation.candidate.to_dict()

        self.history.append(event)
        if not self.done and (self.steps >= self.max_steps or self.probe_count > self.max_probe_count):
            self.done = True
            reward = RewardBreakdown(total=-1.0, cost_penalty=-0.5, invalid_penalty=-0.5)
        return self._observation(), reward, self.done

    def trajectory(self) -> dict[str, Any]:
        """导出不含私有真值和奖励的完整 episode 轨迹。"""

        if self.task_id is None:
            raise RuntimeError("必须先调用 reset")
        payload = {
            "task_id": self.task_id,
            "history": list(self.history),
            "steps": self.steps,
            "probe_count": self.probe_count,
            "invalid_actions": self.invalid_actions,
            "done": self.done,
        }
        assert_no_private_truth(payload)
        return payload

    def _invalid_step(self, action: AgentAction, reason: str) -> tuple[dict[str, Any], RewardBreakdown | None, bool]:
        self.steps += 1
        self.invalid_actions += 1
        self.history.append({"step": self.steps, "action": asdict(action), "error": reason})
        self.done = self.steps >= self.max_steps
        reward = RewardBreakdown(total=-1.0, invalid_penalty=-1.0) if self.done else None
        return self._observation(), reward, self.done

    def _finish(self, action: AgentAction, event: dict[str, Any]) -> RewardBreakdown:
        self.done = True
        cost_penalty = -0.02 * self.steps - 0.01 * self.probe_count
        if action.name == "abstain":
            event["observation"] = {"done_reason": "abstain"}
            return RewardBreakdown(total=cost_penalty, cost_penalty=cost_penalty)
        candidate_id = str(action.arguments.get("candidate_id") or "")
        candidate = self.visible_candidates.get(candidate_id)
        if not candidate or candidate["location"].get("lat") is None or candidate["location"].get("lon") is None:
            event["observation"] = {"done_reason": "unsupported_candidate", "candidate_id": candidate_id}
            return RewardBreakdown(total=-1.0 + cost_penalty, cost_penalty=cost_penalty, unsupported_penalty=-1.0)
        truth = self.private_truth[self.task_id].location
        prediction = Point(float(candidate["location"]["lat"]), float(candidate["location"]["lon"]))
        truth_point = Point(float(truth.lat), float(truth.lon))  # type: ignore[arg-type]
        error = haversine_km(truth_point, prediction)
        base_error = self._base_error(truth_point)
        geo = math.exp(-error / 100.0)
        improve = max(-1.0, min(1.0, (base_error - error) / 100.0))
        total = geo + improve + cost_penalty
        event["observation"] = {"done_reason": "finalize", "candidate_id": candidate_id}
        return RewardBreakdown(total=total, geo=geo, improve=improve, cost_penalty=cost_penalty)

    def _base_error(self, truth: Point) -> float:
        base = self.replay[self.task_id or ""].get("modugeo")
        if not base or not base.candidate or not base.candidate.has_coordinate:
            return 1000.0
        location = base.candidate.location
        return haversine_km(truth, Point(float(location.lat), float(location.lon)))  # type: ignore[arg-type]

    def _observation(self) -> dict[str, Any]:
        task = dict(self.tasks[self.task_id or ""])
        payload = {
            **task,
            "history": list(self.history),
            "visible_candidates": list(self.visible_candidates.values()),
            "remaining_budget": {
                "steps": max(0, self.max_steps - self.steps),
                "probe_count": max(0, self.max_probe_count - self.probe_count),
            },
            "done": self.done,
        }
        assert_no_private_truth(payload)
        return payload
