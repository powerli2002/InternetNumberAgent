from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
from urllib.request import Request, urlopen


_MONTH_NAMES = {
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
}

_PAGE_HEADER_RE = re.compile(
    r"^RFC\s+\d+\s+.+\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\s*$"
)
_PAGE_FOOTER_RE = re.compile(r"^.+\[Page\s+\d+\]\s*$")
_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s{2,}(.+?)\s*$")
_APPENDIX_HEADING_RE = re.compile(r"^(Appendix\s+[A-Z](?:\.[A-Z])?)\.\s{2,}(.+?)\s*$")
_TOC_BLOCK_RE = re.compile(
    r"Table of Contents\s+.*?(?=^\d+\.\s{2,}.+$)", re.MULTILINE | re.DOTALL
)

_SPECIAL_HEADINGS = {
    "Acknowledgements",
    "Security Considerations",
    "IANA Considerations",
    "Normative References",
    "Informative References",
    "References",
    "Authors' Addresses",
    "Author's Address",
}


@dataclass(frozen=True)
class RFCSyncTarget:
    number: int
    topic: str
    slug: str
    tags: tuple[str, ...]

    @property
    def doc_id(self) -> str:
        return f"RFC{self.number}"

    @property
    def text_url(self) -> str:
        return f"https://www.rfc-editor.org/rfc/rfc{self.number}.txt"

    @property
    def json_url(self) -> str:
        return f"https://www.rfc-editor.org/rfc/rfc{self.number}.json"


RFC_SYNC_TARGETS = [
    RFCSyncTarget(
        4271, "bgp", "bgp4", ("BGP-4", "边界网关协议", "BGP 基础协议", "BGP 报文格式")
    ),
    RFCSyncTarget(
        4760,
        "bgp",
        "multiprotocol_extensions",
        ("MP-BGP", "多协议 BGP", "地址族扩展", "MP_REACH_NLRI"),
    ),
    RFCSyncTarget(
        6793,
        "bgp",
        "four_octet_as_number",
        ("四字节 ASN", "4-byte AS number", "四字节自治系统号"),
    ),
    RFCSyncTarget(
        7606,
        "bgp",
        "error_handling",
        ("BGP 错误处理", "UPDATE 报文错误处理", "属性错误处理"),
    ),
    RFCSyncTarget(
        3912,
        "whois",
        "whois_protocol_specification",
        ("WHOIS", "whois 协议", "端口 43", "注册信息查询"),
    ),
    RFCSyncTarget(
        7480,
        "rdap",
        "http_usage",
        ("RDAP", "RDAP HTTP", "RDAP over HTTP", "RESTful 注册数据访问"),
    ),
    RFCSyncTarget(
        7481,
        "rdap",
        "security_services",
        ("RDAP 安全", "RDAP 认证", "RDAP TLS", "安全服务"),
    ),
    RFCSyncTarget(
        7482,
        "rdap",
        "legacy_query_format",
        ("旧版 RDAP 查询格式", "RDAP Query Format", "已废弃 RDAP 查询格式"),
    ),
    RFCSyncTarget(
        7483,
        "rdap",
        "json_responses",
        ("RDAP JSON", "RDAP JSON 响应", "注册数据 JSON 格式"),
    ),
    RFCSyncTarget(
        9082,
        "rdap",
        "query_format",
        ("RDAP 查询格式", "现行 RDAP Query Format", "RDAP URL 模式"),
    ),
    RFCSyncTarget(
        9083,
        "rdap",
        "json_response_format",
        ("RDAP JSON 响应", "现行 RDAP JSON 响应", "RDAP 返回格式"),
    ),
]


def _http_get_json(url: str, timeout: int) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "fusionprocessing-rfc-sync/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError(f"RFC 元数据返回格式异常: {url}")
    return data


def _http_get_text(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": "fusionprocessing-rfc-sync/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def _normalize_lines(raw_text: str) -> list[str]:
    normalized = (
        raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    )
    lines: list[str] = []
    for line in normalized.split("\n"):
        stripped = line.rstrip()
        if _PAGE_HEADER_RE.match(stripped):
            continue
        if _PAGE_FOOTER_RE.match(stripped):
            continue
        lines.append(stripped)
    return lines


def _extract_rfc_body(raw_text: str) -> str:
    lines = _normalize_lines(raw_text)
    text = "\n".join(lines)
    text = _TOC_BLOCK_RE.sub("", text)
    first_heading = re.search(r"^\d+\.\s{2,}.+$", text, flags=re.MULTILINE)
    if first_heading is not None:
        text = text[first_heading.start() :]
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _convert_rfc_body_to_markdown(body_text: str) -> str:
    markdown_lines: list[str] = []
    for line in body_text.splitlines():
        stripped = line.strip()
        if not stripped:
            markdown_lines.append("")
            continue

        numbered_match = _NUMBERED_HEADING_RE.match(stripped)
        if numbered_match:
            section_number = numbered_match.group(1)
            title = numbered_match.group(2).strip()
            level = min(6, 2 + section_number.count("."))
            markdown_lines.append(f"{'#' * level} {section_number}. {title}")
            continue

        appendix_match = _APPENDIX_HEADING_RE.match(stripped)
        if appendix_match:
            appendix_label = appendix_match.group(1).strip()
            title = appendix_match.group(2).strip()
            markdown_lines.append(f"## {appendix_label}. {title}")
            continue

        if stripped in _SPECIAL_HEADINGS:
            markdown_lines.append(f"## {stripped}")
            continue

        markdown_lines.append(stripped)

    markdown = "\n".join(markdown_lines)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip()


def _format_list(values: Any) -> str:
    if not values:
        return "无"
    if isinstance(values, list):
        cleaned = [str(item).strip() for item in values if str(item).strip()]
        return ", ".join(cleaned) if cleaned else "无"
    return str(values).strip() or "无"


def _clean_abstract(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _render_rfc_markdown(
    target: RFCSyncTarget, metadata: dict[str, Any], body_markdown: str
) -> str:
    title = str(metadata.get("title") or target.doc_id).strip()
    abstract = _clean_abstract(str(metadata.get("abstract") or ""))
    lines = [
        f"# {target.doc_id} - {title}",
        "",
        "## 元数据",
        f"- RFC 编号: {target.doc_id}",
        f"- 主题目录: {target.topic}",
        f"- 发布状态: {_format_list(metadata.get('pub_status'))}",
        f"- 当前状态: {_format_list(metadata.get('status'))}",
        f"- 发布时间: {_format_list(metadata.get('pub_date'))}",
        f"- 来源工作组: {_format_list(metadata.get('source'))}",
        f"- 作者: {_format_list(metadata.get('authors'))}",
        f"- 关键标签: {_format_list(list(target.tags) + list(metadata.get('keywords') or []))}",
        f"- 废弃旧文档: {_format_list(metadata.get('obsoletes'))}",
        f"- 被这些 RFC 更新: {_format_list(metadata.get('updated_by'))}",
        f"- 被这些 RFC 废弃: {_format_list(metadata.get('obsoleted_by'))}",
        f"- 原始格式: {_format_list(metadata.get('format'))}",
        f"- DOI: {_format_list(metadata.get('doi'))}",
        f"- 元数据地址: {target.json_url}",
        f"- 正文地址: {target.text_url}",
        "",
    ]
    if abstract:
        lines.extend(["## 摘要", "", abstract, ""])
    lines.extend(["## 正文", "", body_markdown.strip(), ""])
    return "\n".join(lines).strip() + "\n"


def _resolve_targets(requested: list[int] | None) -> list[RFCSyncTarget]:
    if not requested:
        return RFC_SYNC_TARGETS
    target_map = {target.number: target for target in RFC_SYNC_TARGETS}
    missing = sorted(number for number in requested if number not in target_map)
    if missing:
        missing_text = ", ".join(str(number) for number in missing)
        raise RuntimeError(f"存在未配置的 RFC 编号: {missing_text}")
    return [target_map[number] for number in requested]


def _write_file_if_changed(path: Path, content: str) -> str:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "written"


def sync_rfc_docs(
    root_dir: Path, targets: list[RFCSyncTarget], timeout: int
) -> list[dict[str, str]]:
    output_root = root_dir / "agent" / "knowledge" / "rfc"
    results: list[dict[str, str]] = []
    for target in targets:
        metadata = _http_get_json(target.json_url, timeout=timeout)
        raw_text = _http_get_text(target.text_url, timeout=timeout)
        body_text = _extract_rfc_body(raw_text)
        body_markdown = _convert_rfc_body_to_markdown(body_text)
        markdown = _render_rfc_markdown(target, metadata, body_markdown)
        output_path = (
            output_root / target.topic / f"rfc{target.number}_{target.slug}.md"
        )
        status = _write_file_if_changed(output_path, markdown)
        results.append(
            {
                "doc_id": target.doc_id,
                "topic": target.topic,
                "status": status,
                "path": str(output_path.relative_to(root_dir)),
            }
        )
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取指定 RFC 并写入 agent/knowledge/rfc"
    )
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument(
        "--rfc",
        nargs="*",
        type=int,
        default=None,
        help="可选指定 RFC 编号列表；留空时同步脚本内置目标集",
    )
    parser.add_argument(
        "--timeout", type=int, default=60, help="单次 HTTP 请求超时时间（秒）"
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    root_dir = Path(args.root).resolve()
    targets = _resolve_targets(args.rfc)
    results = sync_rfc_docs(
        root_dir=root_dir, targets=targets, timeout=max(5, int(args.timeout))
    )
    written = sum(1 for item in results if item["status"] == "written")
    unchanged = sum(1 for item in results if item["status"] == "unchanged")
    for item in results:
        print(f"[{item['status']}] {item['doc_id']} -> {item['path']}")
    print(f"RFC 同步完成 total={len(results)} written={written} unchanged={unchanged}")


if __name__ == "__main__":
    main()
