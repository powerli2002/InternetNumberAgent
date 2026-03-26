from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from agent.core.config import AgentConfig
from agent.tools.rag_tool import DocumentChunk, RAGTool, build_rag_embedding


@dataclass(frozen=True)
class RFCRAGCase:
    case_id: str
    query: str
    expected_doc_id: str
    intent: str


RFC_RAG_CASES = [
    RFCRAGCase(
        "bgp_base_protocol",
        "BGP-4 的基础协议规范和 OPEN/UPDATE/KEEPALIVE/NOTIFICATION 报文格式定义在哪篇 RFC？",
        "RFC4271",
        "验证 BGP 基础协议文档召回",
    ),
    RFCRAGCase(
        "bgp_multiprotocol",
        "BGP 支持多协议地址族以及 MP_REACH_NLRI 和 MP_UNREACH_NLRI 的扩展定义在哪篇 RFC？",
        "RFC4760",
        "验证 MP-BGP 文档召回",
    ),
    RFCRAGCase(
        "bgp_four_octet_asn",
        "BGP 四字节自治系统号能力定义在哪篇 RFC？",
        "RFC6793",
        "验证 4-byte ASN 文档召回",
    ),
    RFCRAGCase(
        "bgp_error_handling",
        "BGP UPDATE 报文属性错误后的 revised error handling 定义在哪篇 RFC？",
        "RFC7606",
        "验证 BGP 错误处理文档召回",
    ),
    RFCRAGCase(
        "whois_protocol",
        "WHOIS 协议规范定义在哪篇 RFC？",
        "RFC3912",
        "验证 WHOIS 文档召回",
    ),
    RFCRAGCase(
        "rdap_http",
        "RDAP 如何使用 HTTP 进行访问？",
        "RFC7480",
        "验证 RDAP HTTP 文档召回",
    ),
    RFCRAGCase(
        "rdap_security",
        "RDAP 的认证、保密性和完整性安全服务定义在哪篇 RFC？",
        "RFC7481",
        "验证 RDAP 安全文档召回",
    ),
    RFCRAGCase(
        "rdap_legacy_query",
        "被 RFC 9082 废弃的旧版 RDAP 查询格式是哪篇 RFC？",
        "RFC7482",
        "验证旧版 RDAP Query Format 文档召回",
    ),
    RFCRAGCase(
        "rdap_json_legacy",
        "RDAP 的 JSON 响应格式定义在哪篇 RFC？",
        "RFC7483",
        "验证旧版 RDAP JSON 响应文档召回",
    ),
    RFCRAGCase(
        "rdap_query_current",
        "现行 RDAP 查询格式标准是哪篇 RFC？",
        "RFC9082",
        "验证现行 RDAP Query Format 文档召回",
    ),
    RFCRAGCase(
        "rdap_json_current",
        "现行 RDAP JSON 响应标准是哪篇 RFC？",
        "RFC9083",
        "验证现行 RDAP JSON 响应文档召回",
    ),
]


def _find_expected_rank(
    chunks: list[DocumentChunk], expected_doc_id: str
) -> int | None:
    expected = expected_doc_id.lower()
    for index, chunk in enumerate(chunks, start=1):
        source = str(chunk.source).lower()
        if expected in source:
            return index
    return None


def _preview_chunks(chunks: list[DocumentChunk], limit: int) -> list[dict[str, str]]:
    previews: list[dict[str, str]] = []
    for chunk in chunks[:limit]:
        previews.append(
            {
                "source": str(chunk.source),
                "text_prefix": str(chunk.text).replace("\n", " ").strip()[:160],
            }
        )
    return previews


def evaluate_rfc_rag(tool: RAGTool, top_k: int, preview_limit: int) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    reciprocal_rank_sum = 0.0
    hit_at_1 = 0
    hit_at_3 = 0
    hit_at_5 = 0

    for case in RFC_RAG_CASES:
        chunks = tool.search(case.query, top_k=top_k)
        rank = _find_expected_rank(chunks, case.expected_doc_id)
        if rank == 1:
            hit_at_1 += 1
        if rank is not None and rank <= 3:
            hit_at_3 += 1
        if rank is not None and rank <= 5:
            hit_at_5 += 1
        if rank is not None:
            reciprocal_rank_sum += 1.0 / rank
        details.append(
            {
                **asdict(case),
                "rank": rank,
                "top_hits": _preview_chunks(chunks, limit=preview_limit),
            }
        )

    total = len(RFC_RAG_CASES)
    summary = {
        "cases": total,
        "hit_at_1": hit_at_1 / total,
        "hit_at_3": hit_at_3 / total,
        "hit_at_5": hit_at_5 / total,
        "mrr": reciprocal_rank_sum / total,
    }
    return {"summary": summary, "details": details}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="评估 RFC 语料在当前 RAG collection 中的召回效果"
    )
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument(
        "--collection", default=None, help="Milvus collection 名称；留空时读取配置"
    )
    parser.add_argument("--top-k", type=int, default=5, help="单条查询检索条数")
    parser.add_argument(
        "--preview-limit", type=int, default=3, help="每条用例输出前几条命中摘要"
    )
    parser.add_argument("--json-out", default="", help="可选输出 JSON 报告路径")
    parser.add_argument(
        "--fail-under-hit3", type=float, default=0.0, help="若 Hit@3 低于阈值则返回失败"
    )
    parser.add_argument(
        "--fail-under-mrr", type=float, default=0.0, help="若 MRR 低于阈值则返回失败"
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    root_dir = Path(args.root).resolve()
    config = AgentConfig.load(project_root=root_dir)
    collection_name = args.collection or config.vector_collection
    rag_tool = RAGTool(
        host=config.milvus_host,
        port=config.milvus_port,
        collection_name=collection_name,
        embedding=build_rag_embedding(config),
        enable_mqe=config.rag_enable_mqe,
        mqe_max_queries=config.rag_mqe_max_queries,
        candidate_multiplier=config.rag_candidate_multiplier,
        rrf_k=config.rag_rrf_k,
    )
    report = evaluate_rfc_rag(
        tool=rag_tool,
        top_k=max(1, int(args.top_k)),
        preview_limit=max(1, int(args.preview_limit)),
    )
    summary = report["summary"]
    print(
        "RFC RAG 评估完成 "
        f"collection={collection_name} "
        f"cases={summary['cases']} "
        f"hit@1={summary['hit_at_1']:.3f} "
        f"hit@3={summary['hit_at_3']:.3f} "
        f"hit@5={summary['hit_at_5']:.3f} "
        f"mrr={summary['mrr']:.3f}"
    )
    for item in report["details"]:
        top_sources = ", ".join(hit["source"] for hit in item["top_hits"])
        print(
            f"- {item['case_id']} expected={item['expected_doc_id']} rank={item['rank']} top={top_sources}"
        )

    if args.json_out:
        output_path = (root_dir / args.json_out).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON 报告已写入: {output_path.relative_to(root_dir)}")

    if float(summary["hit_at_3"]) < float(args.fail_under_hit3):
        raise SystemExit(
            f"Hit@3 {summary['hit_at_3']:.3f} 低于阈值 {float(args.fail_under_hit3):.3f}"
        )
    if float(summary["mrr"]) < float(args.fail_under_mrr):
        raise SystemExit(
            f"MRR {summary['mrr']:.3f} 低于阈值 {float(args.fail_under_mrr):.3f}"
        )


if __name__ == "__main__":
    main()
