"""DNS 主动查询工具。

封装 dig CLI（类似 zdns 的外部 CLI 包装思路），支持批量查询多域名、多记录类型，
输出结构化结果供 FusionAgent 直接消费或接入 fusiondata 入库流水线。

支持的记录类型：
  A / AAAA / MX / NS / TXT / PTR / CNAME / SOA
  SPF   — 查 TXT 后过滤 v=spf1 前缀
  DMARC — 查 _dmarc.<domain> 的 TXT 记录
"""

from __future__ import annotations

import asyncio
import re
import shutil
from typing import Any, Dict, List, Optional

from agent.tools.base import BaseTool, ToolResult
from fusiondata.src.utils.logging_manager import logger

__all__ = ["DNSLookupTool"]

# 原生 dig 支持的记录类型（传给 dig 命令）
_NATIVE_TYPES = {"A", "AAAA", "MX", "NS", "TXT", "PTR", "CNAME", "SOA"}

# 虚拟类型：需要预处理后转为真实类型查询
_VIRTUAL_TYPES = {"SPF", "DMARC"}

_DEFAULT_TIMEOUT = 10  # 单次 dig 调用超时秒数
_DEFAULT_NAMESERVER = ""  # 空串 = 使用系统默认 DNS


def _find_dig() -> str:
    """定位 dig 可执行文件路径，找不到则报错。"""
    path = shutil.which("dig")
    if not path:
        raise RuntimeError("未找到 dig 命令，请安装 bind-utils 或 dnsutils。")
    return path


def _parse_answer_section(raw: str, qtype: str) -> List[Dict[str, Any]]:
    """解析 dig +noall +answer 输出，返回记录列表。

    每行格式：  name  TTL  class  type  rdata
    """
    records: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        name, ttl, _cls, rtype, rdata = parts
        records.append(
            {
                "name": name.rstrip("."),
                "ttl": int(ttl) if ttl.isdigit() else ttl,
                "type": rtype,
                "data": rdata.strip(),
            }
        )
    return records


async def _run_dig(
    domain: str,
    qtype: str,
    nameserver: str,
    timeout: int,
    dig_bin: str,
) -> List[Dict[str, Any]]:
    """异步执行 dig 并返回解析后的记录列表。"""
    cmd = [dig_bin, "+noall", "+answer", "+time=5", "+tries=2", domain, qtype]
    if nameserver:
        cmd.insert(1, f"@{nameserver}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        raise RuntimeError(f"dig 查询超时（{timeout}s）: {domain} {qtype}")
    except Exception as exc:
        raise RuntimeError(f"dig 执行失败: {exc}") from exc

    raw = stdout.decode("utf-8", errors="replace")
    return _parse_answer_section(raw, qtype)


async def _lookup_single(
    domain: str,
    qtype: str,
    nameserver: str,
    timeout: int,
    dig_bin: str,
) -> Dict[str, Any]:
    """查询单个域名的单个类型，处理虚拟类型的转换逻辑。"""
    qt_upper = qtype.strip().upper()

    # SPF：查 TXT，过滤 v=spf1 开头的记录
    if qt_upper == "SPF":
        records = await _run_dig(domain, "TXT", nameserver, timeout, dig_bin)
        spf_records = [r for r in records if r["data"].strip('"').startswith("v=spf1")]
        return {"domain": domain, "type": "SPF", "records": spf_records}

    # DMARC：查 _dmarc.<domain> 的 TXT
    if qt_upper == "DMARC":
        dmarc_domain = f"_dmarc.{domain}"
        records = await _run_dig(dmarc_domain, "TXT", nameserver, timeout, dig_bin)
        dmarc_records = [r for r in records if "v=DMARC1" in r["data"]]
        return {"domain": domain, "type": "DMARC", "records": dmarc_records}

    if qt_upper not in _NATIVE_TYPES:
        raise ValueError(f"不支持的记录类型: {qtype}")

    records = await _run_dig(domain, qt_upper, nameserver, timeout, dig_bin)
    return {"domain": domain, "type": qt_upper, "records": records}


class DNSLookupTool(BaseTool):
    """DNS 主动查询工具，封装 dig CLI，支持批量域名和多记录类型。

    设计参考 zdns 的外部 CLI + JSON 输出思路：
    - 批量并发查询（asyncio.gather），单次超时保护；
    - 结构化输出可直接接入 fusiondata 入库流水线；
    - 支持 SPF/DMARC 等虚拟类型（内部转换为 TXT 查询）。
    """

    schema: Dict[str, Any] = {
        "name": "dns_lookup",
        "description": (
            "对指定域名执行主动 DNS 查询，返回结构化记录。"
            "支持 A/AAAA/MX/NS/TXT/PTR/CNAME/SOA/SPF/DMARC 类型，可批量查询多个域名。"
            "用于回答「该域名现在解析到哪里」「邮件安全策略是什么」等实时问题。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要查询的域名列表，如 [\"example.com\", \"google.com\"]",
                },
                "record_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "要查询的记录类型列表，默认 [\"A\"]。"
                        "支持: A, AAAA, MX, NS, TXT, PTR, CNAME, SOA, SPF, DMARC"
                    ),
                    "default": ["A"],
                },
                "nameserver": {
                    "type": "string",
                    "description": "指定 DNS 服务器地址，如 \"8.8.8.8\"，留空使用系统默认。",
                    "default": "",
                },
                "timeout": {
                    "type": "integer",
                    "description": "单次查询超时秒数，默认 10。",
                    "default": 10,
                },
            },
            "required": ["domains"],
        },
    }

    def __init__(self, nameserver: str = "", timeout: int = _DEFAULT_TIMEOUT) -> None:
        self._default_nameserver = nameserver
        self._default_timeout = timeout
        self._dig_bin: Optional[str] = None

    def _ensure_dig(self) -> str:
        if self._dig_bin is None:
            self._dig_bin = _find_dig()
        return self._dig_bin

    async def aexecute(
        self,
        domains: List[str],
        record_types: Optional[List[str]] = None,
        nameserver: str = "",
        timeout: int = 0,
    ) -> ToolResult:
        """批量查询 DNS 记录，并发执行所有（域名, 类型）组合。"""
        if not domains:
            return ToolResult(success=False, error="domains 不能为空")

        types = [t.strip().upper() for t in (record_types or ["A"]) if t.strip()]
        if not types:
            return ToolResult(success=False, error="record_types 不能为空")

        all_types = _NATIVE_TYPES | _VIRTUAL_TYPES
        invalid = [t for t in types if t not in all_types]
        if invalid:
            return ToolResult(
                success=False,
                error=f"不支持的记录类型: {invalid}，支持: {sorted(all_types)}",
            )

        ns = nameserver or self._default_nameserver
        to = timeout if timeout > 0 else self._default_timeout

        try:
            dig_bin = self._ensure_dig()
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))

        # 生成所有（域名, 类型）任务，并发执行
        tasks = [
            _lookup_single(domain, qtype, ns, to, dig_bin)
            for domain in domains
            for qtype in types
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: List[Dict[str, Any]] = []
        errors: List[str] = []
        for r in results:
            if isinstance(r, Exception):
                errors.append(str(r))
                logger.warning("DNS 查询异常: %s", r)
            else:
                output.append(r)

        # 部分失败时仍返回已成功的结果，通过 metadata 暴露错误详情
        return ToolResult(
            success=len(errors) == 0,
            output=output,
            error="; ".join(errors) if errors else None,
            metadata={
                "domains": domains,
                "record_types": types,
                "nameserver": ns or "system_default",
                "total": len(tasks),
                "succeeded": len(output),
                "failed": len(errors),
            },
        )
