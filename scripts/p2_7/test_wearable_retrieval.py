#!/usr/bin/env python3
"""
P2-7：穿戴设备 FAISS 检索验收脚本

本脚本直接调用正式检索服务：
    backend/services/wearable_retrieval_service.py

覆盖内容：
    - 6组基础操作FAQ检索
    - 6组产品参数检索
    - 3组跨产品类别/主题检索
    - 输入异常处理
    - FAISS索引、Metadata与manifest一致性

用法（在仓库根目录执行）：
    python scripts/p2_7/test_wearable_retrieval.py

输出：
    docs/p2_7/retrieval_test_report.json
    docs/p2_7/retrieval_test_report.md
    docs/p2_7/retrieval_test_log.txt
"""

from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============================================================
# 仓库路径
# ============================================================
REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.services.wearable_retrieval_service import (  # noqa: E402
    reset_wearable_retrieval_cache,
    search_wearable_knowledge,
)

VECTOR_STORE_DIR = REPO_ROOT / "vector_store" / "wearables"
INDEX_PATH = VECTOR_STORE_DIR / "wearable.faiss"
METADATA_PATH = VECTOR_STORE_DIR / "wearable_metadata.jsonl"
MANIFEST_PATH = VECTOR_STORE_DIR / "manifest.json"

DOCS_DIR = REPO_ROOT / "docs" / "p2_7"
REPORT_JSON_PATH = DOCS_DIR / "retrieval_test_report.json"
REPORT_MD_PATH = DOCS_DIR / "retrieval_test_report.md"
TEST_LOG_PATH = DOCS_DIR / "retrieval_test_log.txt"

EXPECTED_VECTOR_COUNT = 240
EXPECTED_METADATA_COUNT = 240
EXPECTED_PRODUCT_COUNT = 16
EXPECTED_PARAMETER_CHUNKS = 144
EXPECTED_FAQ_CHUNKS = 96


# ============================================================
# 日志
# ============================================================
def setup_logger() -> logging.Logger:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("p2_7_retrieval_test")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(
        TEST_LOG_PATH,
        mode="w",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


LOGGER = setup_logger()


# ============================================================
# 测试用例
# ============================================================
@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    query: str
    description: str
    top_k: int = 3
    product_id: str | None = None
    device_type: str | None = None
    topic: str | None = None
    chunk_type: str | None = None

    expected_top1_product_id: str | None = None
    expected_product_ids_in_top_n: set[str] = field(
        default_factory=set
    )
    expected_device_type: str | None = None
    expected_topic: str | None = None
    expected_chunk_type: str | None = None

    expected_keywords_all: tuple[str, ...] = ()
    expected_keywords_any: tuple[str, ...] = ()


TEST_CASES: tuple[RetrievalCase, ...] = (
    # -------------------- FAQ：基础操作问答 --------------------
    RetrievalCase(
        case_id="FAQ01",
        query="Xiaomi Smart Band 10怎么连接手机？",
        description="B02连接绑定FAQ",
        product_id="B02",
        topic="连接绑定",
        chunk_type="manual_faq",
        expected_top1_product_id="B02",
        expected_device_type="smart_band",
        expected_topic="连接绑定",
        expected_chunk_type="manual_faq",
        expected_keywords_all=("Mi Fitness", "蓝牙"),
    ),
    RetrievalCase(
        case_id="FAQ02",
        query="Xiaomi Smart Band 9 Pro怎么充电？",
        description="B03充电FAQ",
        product_id="B03",
        topic="充电续航",
        chunk_type="manual_faq",
        expected_top1_product_id="B03",
        expected_device_type="smart_band",
        expected_topic="充电续航",
        expected_chunk_type="manual_faq",
        expected_keywords_any=("充电", "5V", "磁吸"),
    ),
    RetrievalCase(
        case_id="FAQ03",
        query="REDMI Watch 5怎么恢复出厂设置？",
        description="W03系统操作FAQ",
        product_id="W03",
        topic="系统操作",
        chunk_type="manual_faq",
        expected_top1_product_id="W03",
        expected_device_type="smart_watch",
        expected_topic="系统操作",
        expected_chunk_type="manual_faq",
        expected_keywords_any=("恢复出厂设置", "重启", "系统"),
    ),
    RetrievalCase(
        case_id="FAQ04",
        query="Xiaomi Watch S4为什么收不到应用通知？",
        description="W02通知FAQ",
        product_id="W02",
        topic="通知功能",
        chunk_type="manual_faq",
        expected_top1_product_id="W02",
        expected_device_type="smart_watch",
        expected_topic="通知功能",
        expected_chunk_type="manual_faq",
        expected_keywords_any=("通知", "Mi Fitness", "蓝牙"),
    ),
    RetrievalCase(
        case_id="FAQ05",
        query="REDMI Watch 5 Active怎么更换表盘？",
        description="W05表盘FAQ",
        product_id="W05",
        topic="表盘功能",
        chunk_type="manual_faq",
        expected_top1_product_id="W05",
        expected_device_type="smart_watch",
        expected_topic="表盘功能",
        expected_chunk_type="manual_faq",
        expected_keywords_all=("表盘",),
    ),
    RetrievalCase(
        case_id="FAQ06",
        query="Xiaomi Watch S3心率测量不准怎么办？",
        description="W08健康监测FAQ",
        product_id="W08",
        topic="健康监测",
        chunk_type="manual_faq",
        expected_top1_product_id="W08",
        expected_device_type="smart_watch",
        expected_topic="健康监测",
        expected_chunk_type="manual_faq",
        expected_keywords_any=("心率", "佩戴", "传感器"),
    ),

    # -------------------- 参数知识检索 --------------------
    RetrievalCase(
        case_id="PAR01",
        query="Xiaomi Smart Band 10典型续航多少天？",
        description="B02电池参数",
        product_id="B02",
        topic="battery",
        chunk_type="battery",
        expected_top1_product_id="B02",
        expected_device_type="smart_band",
        expected_topic="battery",
        expected_chunk_type="battery",
        expected_keywords_all=("续航", "21", "天"),
    ),
    RetrievalCase(
        case_id="PAR02",
        query="Xiaomi Watch S4屏幕最高亮度是多少？",
        description="W02显示参数",
        product_id="W02",
        topic="display",
        chunk_type="display",
        expected_top1_product_id="W02",
        expected_device_type="smart_watch",
        expected_topic="display",
        expected_chunk_type="display",
        expected_keywords_all=("亮度", "2200", "尼特"),
    ),
    RetrievalCase(
        case_id="PAR03",
        query="REDMI Watch 5 Active是否需要连接手机定位？",
        description="W05定位参数",
        product_id="W05",
        topic="positioning",
        chunk_type="positioning",
        expected_top1_product_id="W05",
        expected_device_type="smart_watch",
        expected_topic="positioning",
        expected_chunk_type="positioning",
        expected_keywords_all=("手机", "定位"),
    ),
    RetrievalCase(
        case_id="PAR04",
        query="Xiaomi Watch 2支持iPhone吗？",
        description="W06兼容性参数",
        product_id="W06",
        topic="compatibility",
        chunk_type="compatibility",
        expected_top1_product_id="W06",
        expected_device_type="smart_watch",
        expected_topic="compatibility",
        expected_chunk_type="compatibility",
        expected_keywords_all=("不支持", "iOS"),
    ),
    RetrievalCase(
        case_id="PAR05",
        query="Xiaomi Smart Band 8支持5ATM防水吗？",
        description="B07防水参数",
        product_id="B07",
        topic="design",
        chunk_type="design",
        expected_top1_product_id="B07",
        expected_device_type="smart_band",
        expected_topic="design",
        expected_chunk_type="design",
        expected_keywords_all=("5ATM", "防水"),
    ),
    RetrievalCase(
        case_id="PAR06",
        query="Xiaomi Watch 2 Pro是否支持NFC？",
        description="W07通信参数",
        product_id="W07",
        topic="communication",
        chunk_type="communication",
        expected_top1_product_id="W07",
        expected_device_type="smart_watch",
        expected_topic="communication",
        expected_chunk_type="communication",
        expected_keywords_all=("NFC",),
    ),

    # -------------------- 跨产品筛选与综合检索 --------------------
    RetrievalCase(
        case_id="GEN01",
        query="支持NFC的智能手表",
        description="智能手表类别过滤",
        device_type="smart_watch",
        topic="communication",
        chunk_type="communication",
        expected_device_type="smart_watch",
        expected_topic="communication",
        expected_chunk_type="communication",
        expected_keywords_all=("NFC",),
    ),
    RetrievalCase(
        case_id="GEN02",
        query="支持5ATM防水的智能手环",
        description="智能手环类别过滤",
        device_type="smart_band",
        topic="design",
        chunk_type="design",
        expected_device_type="smart_band",
        expected_topic="design",
        expected_chunk_type="design",
        expected_keywords_all=("5ATM", "防水"),
    ),
    RetrievalCase(
        case_id="GEN03",
        query="手表收不到应用通知怎么办？",
        description="手表通知FAQ综合检索",
        device_type="smart_watch",
        topic="通知功能",
        chunk_type="manual_faq",
        expected_device_type="smart_watch",
        expected_topic="通知功能",
        expected_chunk_type="manual_faq",
        expected_keywords_any=("通知", "蓝牙", "Mi Fitness"),
    ),
)


# ============================================================
# 报告数据结构
# ============================================================
def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)
    if not isinstance(data, dict):
        raise RuntimeError(f"{path.name}顶层必须为JSON对象")
    return data


def count_jsonl(path: Path) -> int:
    with path.open("r", encoding="utf-8") as file_obj:
        return sum(1 for line in file_obj if line.strip())


def validate_artifacts() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    for path in (INDEX_PATH, METADATA_PATH, MANIFEST_PATH):
        if not path.exists():
            errors.append(f"缺少文件：{path}")

    if errors:
        return {
            "errors": errors,
            "warnings": warnings,
        }

    manifest = load_json(MANIFEST_PATH)
    metadata_count = count_jsonl(METADATA_PATH)

    expected_checks = {
        "manifest.vector_count": (
            manifest.get("vector_count"),
            EXPECTED_VECTOR_COUNT,
        ),
        "manifest.metadata_count": (
            manifest.get("metadata_count"),
            EXPECTED_METADATA_COUNT,
        ),
        "manifest.product_count": (
            manifest.get("product_count"),
            EXPECTED_PRODUCT_COUNT,
        ),
        "manifest.parameter_chunk_count": (
            manifest.get("parameter_chunk_count"),
            EXPECTED_PARAMETER_CHUNKS,
        ),
        "manifest.faq_chunk_count": (
            manifest.get("faq_chunk_count"),
            EXPECTED_FAQ_CHUNKS,
        ),
        "metadata实际行数": (
            metadata_count,
            EXPECTED_METADATA_COUNT,
        ),
    }

    for label, (actual, expected) in expected_checks.items():
        if actual != expected:
            errors.append(
                f"{label}应为{expected}，实际为{actual}"
            )

    return {
        "errors": errors,
        "warnings": warnings,
        "manifest": manifest,
        "metadata_count": metadata_count,
    }


def result_text(results: list[dict[str, Any]], top_n: int = 3) -> str:
    return " ".join(
        str(item.get("text", ""))
        for item in results[:top_n]
    )


def required_result_fields_missing(
    result: dict[str, Any],
) -> list[str]:
    required_fields = (
        "rank",
        "score",
        "chunk_id",
        "qa_id",
        "product_id",
        "product_name",
        "device_type",
        "product_category",
        "chunk_type",
        "topic",
        "text",
        "source_url",
    )

    return [
        field_name
        for field_name in required_fields
        if field_name not in result
    ]


def run_case(case: RetrievalCase) -> dict[str, Any]:
    started = time.time()

    LOGGER.info("")
    LOGGER.info("[%s] %s", case.case_id, case.description)
    LOGGER.info("查询：%s", case.query)

    try:
        results = search_wearable_knowledge(
            query=case.query,
            top_k=case.top_k,
            product_id=case.product_id,
            device_type=case.device_type,
            topic=case.topic,
            chunk_type=case.chunk_type,
        )
    except Exception as exc:
        LOGGER.error("查询异常：%s", exc)
        LOGGER.debug(traceback.format_exc())
        return {
            "case_id": case.case_id,
            "description": case.description,
            "query": case.query,
            "passed": False,
            "checks": {
                "query_completed": False,
            },
            "error": f"{type(exc).__name__}: {exc}",
            "results": [],
            "elapsed_seconds": round(time.time() - started, 4),
        }

    checks: dict[str, bool] = {}
    details: list[str] = []

    checks["has_results"] = bool(results)
    if not results:
        details.append("没有返回检索结果")

    if results:
        expected_ranks = list(range(1, len(results) + 1))
        actual_ranks = [item.get("rank") for item in results]
        checks["rank_is_sequential"] = (
            actual_ranks == expected_ranks
        )
        if not checks["rank_is_sequential"]:
            details.append(
                f"rank异常：{actual_ranks}，预期{expected_ranks}"
            )

        missing_fields = required_result_fields_missing(results[0])
        checks["required_fields_complete"] = not missing_fields
        if missing_fields:
            details.append(f"结果缺少字段：{missing_fields}")

        if case.expected_top1_product_id is not None:
            actual_top1 = str(results[0].get("product_id", ""))
            checks["top1_product_match"] = (
                actual_top1 == case.expected_top1_product_id
            )
            if not checks["top1_product_match"]:
                details.append(
                    "Top1产品不匹配："
                    f"实际{actual_top1}，"
                    f"预期{case.expected_top1_product_id}"
                )

        if case.expected_product_ids_in_top_n:
            top_product_ids = {
                str(item.get("product_id", ""))
                for item in results
            }
            checks["expected_product_in_top_n"] = bool(
                top_product_ids
                & case.expected_product_ids_in_top_n
            )
            if not checks["expected_product_in_top_n"]:
                details.append(
                    "Top结果未包含预期产品："
                    f"实际{sorted(top_product_ids)}，"
                    f"预期任一{sorted(case.expected_product_ids_in_top_n)}"
                )

        if case.expected_device_type is not None:
            actual_types = {
                str(item.get("device_type", ""))
                for item in results
            }
            checks["device_type_filter_enforced"] = (
                actual_types == {case.expected_device_type}
            )
            if not checks["device_type_filter_enforced"]:
                details.append(
                    "设备类型筛选未严格生效："
                    f"实际{sorted(actual_types)}，"
                    f"预期{case.expected_device_type}"
                )

        if case.expected_topic is not None:
            actual_topics = {
                str(item.get("topic", ""))
                for item in results
            }
            checks["topic_filter_enforced"] = (
                actual_topics == {case.expected_topic}
            )
            if not checks["topic_filter_enforced"]:
                details.append(
                    "topic筛选未严格生效："
                    f"实际{sorted(actual_topics)}，"
                    f"预期{case.expected_topic}"
                )

        if case.expected_chunk_type is not None:
            actual_chunk_types = {
                str(item.get("chunk_type", ""))
                for item in results
            }
            checks["chunk_type_filter_enforced"] = (
                actual_chunk_types == {case.expected_chunk_type}
            )
            if not checks["chunk_type_filter_enforced"]:
                details.append(
                    "chunk_type筛选未严格生效："
                    f"实际{sorted(actual_chunk_types)}，"
                    f"预期{case.expected_chunk_type}"
                )

        joined_text = result_text(results)

        if case.expected_keywords_all:
            missing_keywords = [
                keyword
                for keyword in case.expected_keywords_all
                if keyword not in joined_text
            ]
            checks["all_keywords_found"] = not missing_keywords
            if missing_keywords:
                details.append(
                    f"缺少必须关键词：{missing_keywords}"
                )

        if case.expected_keywords_any:
            hit_keywords = [
                keyword
                for keyword in case.expected_keywords_any
                if keyword in joined_text
            ]
            checks["any_keyword_found"] = bool(hit_keywords)
            if not hit_keywords:
                details.append(
                    "未命中任一候选关键词："
                    f"{list(case.expected_keywords_any)}"
                )

        if case.chunk_type == "manual_faq":
            faq_ids = [
                item.get("qa_id")
                for item in results
            ]
            checks["faq_has_qa_id"] = all(faq_ids)
            if not checks["faq_has_qa_id"]:
                details.append("FAQ结果存在空qa_id")

    passed = bool(checks) and all(checks.values())

    for item in results[:3]:
        LOGGER.info(
            "  #%s score=%.6f %s %s %s %s",
            item.get("rank"),
            float(item.get("score", 0.0)),
            item.get("product_id"),
            item.get("chunk_type"),
            item.get("topic"),
            str(item.get("text", ""))[:80].replace("\n", " "),
        )

    LOGGER.info("结果：%s", "PASS" if passed else "FAIL")
    for detail in details:
        LOGGER.warning("  %s", detail)

    return {
        "case_id": case.case_id,
        "description": case.description,
        "query": case.query,
        "filters": {
            "product_id": case.product_id,
            "device_type": case.device_type,
            "topic": case.topic,
            "chunk_type": case.chunk_type,
            "top_k": case.top_k,
        },
        "passed": passed,
        "checks": checks,
        "details": details,
        "results": results,
        "elapsed_seconds": round(time.time() - started, 4),
    }


def run_invalid_input_tests() -> list[dict[str, Any]]:
    tests = (
        {
            "test_id": "ERR01",
            "description": "空查询应抛出ValueError",
            "call": lambda: search_wearable_knowledge(""),
            "expected_exception": ValueError,
        },
        {
            "test_id": "ERR02",
            "description": "top_k=0应抛出ValueError",
            "call": lambda: search_wearable_knowledge(
                "测试",
                top_k=0,
            ),
            "expected_exception": ValueError,
        },
        {
            "test_id": "ERR03",
            "description": "未知product_id应抛出ValueError",
            "call": lambda: search_wearable_knowledge(
                "测试",
                product_id="UNKNOWN",
            ),
            "expected_exception": ValueError,
        },
        {
            "test_id": "ERR04",
            "description": "未知topic应抛出ValueError",
            "call": lambda: search_wearable_knowledge(
                "测试",
                topic="不存在的主题",
            ),
            "expected_exception": ValueError,
        },
    )

    results: list[dict[str, Any]] = []

    for item in tests:
        passed = False
        actual_exception = None

        try:
            item["call"]()
        except item["expected_exception"] as exc:
            passed = True
            actual_exception = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            actual_exception = f"{type(exc).__name__}: {exc}"

        LOGGER.info(
            "[%s] %s：%s",
            item["test_id"],
            item["description"],
            "PASS" if passed else "FAIL",
        )

        results.append(
            {
                "test_id": item["test_id"],
                "description": item["description"],
                "passed": passed,
                "actual_exception": actual_exception,
            }
        )

    return results


def write_markdown_report(report: dict[str, Any]) -> None:
    artifact = report["artifact_validation"]
    summary = report["summary"]

    lines = [
        "# P2-7穿戴设备检索测试报告",
        "",
        "## 总结",
        "",
        f"- 检索测试用例：{summary['retrieval_cases_total']}",
        f"- 检索测试通过：{summary['retrieval_cases_passed']}",
        f"- 检索测试失败：{summary['retrieval_cases_failed']}",
        f"- 异常输入测试：{summary['invalid_input_tests_total']}",
        f"- 异常输入测试通过：{summary['invalid_input_tests_passed']}",
        f"- 最终结果：{'通过' if summary['all_passed'] else '未通过'}",
        f"- 总耗时：{report['elapsed_seconds']:.2f}秒",
        "",
        "## 构建产物校验",
        "",
        f"- errors：{len(artifact.get('errors', []))}",
        f"- warnings：{len(artifact.get('warnings', []))}",
        "",
        "## 检索用例",
        "",
        "| ID | 描述 | 结果 | Top1产品 | Top1主题 |",
        "|---|---|---|---|---|",
    ]

    for case in report["retrieval_cases"]:
        results = case.get("results", [])
        top1_product = results[0].get("product_id", "") if results else ""
        top1_topic = results[0].get("topic", "") if results else ""

        lines.append(
            f"| {case['case_id']} | {case['description']} | "
            f"{'PASS' if case['passed'] else 'FAIL'} | "
            f"{top1_product} | {top1_topic} |"
        )

    lines.extend(
        [
            "",
            "## 失败明细",
            "",
        ]
    )

    failures = [
        case
        for case in report["retrieval_cases"]
        if not case["passed"]
    ]

    if failures:
        for case in failures:
            lines.append(
                f"### {case['case_id']} {case['description']}"
            )
            lines.append("")
            for detail in case.get("details", []):
                lines.append(f"- {detail}")
            if case.get("error"):
                lines.append(f"- {case['error']}")
            lines.append("")
    else:
        lines.append("- 无")
        lines.append("")

    REPORT_MD_PATH.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> int:
    started = time.time()

    LOGGER.info("=" * 64)
    LOGGER.info("P2-7：穿戴设备FAISS检索验收")
    LOGGER.info("=" * 64)

    artifact_validation = validate_artifacts()

    if artifact_validation.get("errors"):
        for error in artifact_validation["errors"]:
            LOGGER.error(error)

        report = {
            "artifact_validation": artifact_validation,
            "summary": {
                "retrieval_cases_total": len(TEST_CASES),
                "retrieval_cases_passed": 0,
                "retrieval_cases_failed": len(TEST_CASES),
                "invalid_input_tests_total": 0,
                "invalid_input_tests_passed": 0,
                "all_passed": False,
            },
            "retrieval_cases": [],
            "invalid_input_tests": [],
            "elapsed_seconds": round(time.time() - started, 3),
        }

        REPORT_JSON_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        write_markdown_report(report)
        return 1

    reset_wearable_retrieval_cache()

    retrieval_results = [
        run_case(case)
        for case in TEST_CASES
    ]
    invalid_input_results = run_invalid_input_tests()

    retrieval_passed = sum(
        1
        for result in retrieval_results
        if result["passed"]
    )
    invalid_input_passed = sum(
        1
        for result in invalid_input_results
        if result["passed"]
    )

    all_passed = (
        retrieval_passed == len(retrieval_results)
        and invalid_input_passed == len(invalid_input_results)
        and not artifact_validation.get("errors")
    )

    report = {
        "artifact_validation": artifact_validation,
        "summary": {
            "retrieval_cases_total": len(retrieval_results),
            "retrieval_cases_passed": retrieval_passed,
            "retrieval_cases_failed": (
                len(retrieval_results) - retrieval_passed
            ),
            "invalid_input_tests_total": len(invalid_input_results),
            "invalid_input_tests_passed": invalid_input_passed,
            "all_passed": all_passed,
        },
        "retrieval_cases": retrieval_results,
        "invalid_input_tests": invalid_input_results,
        "elapsed_seconds": round(time.time() - started, 3),
    }

    REPORT_JSON_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_markdown_report(report)

    LOGGER.info("")
    LOGGER.info("=" * 64)
    LOGGER.info("测试汇总")
    LOGGER.info("=" * 64)
    LOGGER.info(
        "检索用例：%s/%s通过",
        retrieval_passed,
        len(retrieval_results),
    )
    LOGGER.info(
        "异常输入测试：%s/%s通过",
        invalid_input_passed,
        len(invalid_input_results),
    )
    LOGGER.info(
        "最终结果：%s",
        "全部通过" if all_passed else "存在失败项",
    )
    LOGGER.info(
        "JSON报告：%s",
        REPORT_JSON_PATH,
    )
    LOGGER.info(
        "Markdown报告：%s",
        REPORT_MD_PATH,
    )

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
