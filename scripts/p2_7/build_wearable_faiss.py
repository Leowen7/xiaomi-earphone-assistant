#!/usr/bin/env python3
"""
P2-7：穿戴设备 FAISS 向量知识库构建脚本

输入：
    data/wearables/processed/chunks/wearable_all_chunks.jsonl

输出：
    vector_store/wearables/wearable.faiss
    vector_store/wearables/wearable_metadata.jsonl
    vector_store/wearables/manifest.json
    docs/p2_7/validation_report.md
    docs/p2_7/run_log.txt

用法（在仓库根目录执行）：
    python scripts/p2_7/build_wearable_faiss.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 必须在导入 sentence_transformers 前设置。
if not os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


# ============================================================
# 路径与模型配置
# ============================================================
REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_CHUNKS_PATH = (
    REPO_ROOT
    / "data"
    / "wearables"
    / "processed"
    / "chunks"
    / "wearable_all_chunks.jsonl"
)

VECTOR_STORE_DIR = REPO_ROOT / "vector_store" / "wearables"
INDEX_PATH = VECTOR_STORE_DIR / "wearable.faiss"
METADATA_PATH = VECTOR_STORE_DIR / "wearable_metadata.jsonl"
MANIFEST_PATH = VECTOR_STORE_DIR / "manifest.json"

DOCS_DIR = REPO_ROOT / "docs" / "p2_7"
VALIDATION_REPORT_PATH = DOCS_DIR / "validation_report.md"
RUN_LOG_PATH = DOCS_DIR / "run_log.txt"

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
INDEX_TYPE = "IndexFlatIP"

EXPECTED_TOTAL_CHUNKS = 240
EXPECTED_PRODUCTS = 16
EXPECTED_PARAMETER_CHUNKS = 144
EXPECTED_FAQ_CHUNKS = 96


# ============================================================
# 日志
# ============================================================
def setup_logger() -> logging.Logger:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("p2_7_build")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(
        RUN_LOG_PATH,
        mode="w",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


LOGGER = setup_logger()


# ============================================================
# 工具函数
# ============================================================
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for block in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"输入文件不存在：{path}")

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file_obj:
        for line_no, line in enumerate(file_obj, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                item = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"JSONL 第 {line_no} 行解析失败：{exc}"
                ) from exc

            if not isinstance(item, dict):
                raise ValueError(f"JSONL 第 {line_no} 行不是 JSON 对象")
            records.append(item)

    return records


def normalize_device_type(chunk: dict[str, Any]) -> str:
    return str(
        chunk.get("device_type")
        or chunk.get("product_category")
        or ""
    ).strip()


def normalize_topic(chunk: dict[str, Any]) -> str:
    topic = chunk.get("topic")
    if topic:
        return str(topic).strip()

    chunk_type = str(chunk.get("chunk_type", "")).strip()
    return chunk_type


def validate_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """严格校验 P2-6 输出，返回统计信息。"""
    errors: list[str] = []
    warnings: list[str] = []

    chunk_ids: list[str] = []
    product_ids: set[str] = set()
    device_types: Counter[str] = Counter()
    chunk_types: Counter[str] = Counter()

    required_fields = (
        "chunk_id",
        "product_id",
        "product_name",
        "chunk_type",
        "text",
        "source_url",
    )

    for index, chunk in enumerate(chunks):
        row_no = index + 1

        for field in required_fields:
            value = chunk.get(field)
            if value is None or str(value).strip() == "":
                errors.append(f"第 {row_no} 条缺少必填字段：{field}")

        chunk_id = str(chunk.get("chunk_id", "")).strip()
        product_id = str(chunk.get("product_id", "")).strip()
        chunk_type = str(chunk.get("chunk_type", "")).strip()
        text = str(chunk.get("text", "")).strip()
        source_url = str(chunk.get("source_url", "")).strip()
        device_type = normalize_device_type(chunk)

        chunk_ids.append(chunk_id)
        product_ids.add(product_id)
        chunk_types[chunk_type] += 1
        device_types[device_type] += 1

        if not text:
            errors.append(f"{chunk_id or row_no}：text 为空")
        if not source_url.startswith(("https://", "http://")):
            warnings.append(
                f"{chunk_id or row_no}：source_url 不是完整 HTTP(S) 链接"
            )
        if chunk_type == "manual_faq" and not chunk.get("qa_id"):
            errors.append(f"{chunk_id or row_no}：FAQ 缺少 qa_id")
        if chunk_type == "manual_faq" and not chunk.get("topic"):
            errors.append(f"{chunk_id or row_no}：FAQ 缺少 topic")
        if not device_type:
            warnings.append(f"{chunk_id or row_no}：缺少 device_type")

    duplicate_chunk_ids = sorted(
        chunk_id
        for chunk_id, count in Counter(chunk_ids).items()
        if chunk_id and count > 1
    )
    if duplicate_chunk_ids:
        errors.append(f"发现重复 chunk_id：{duplicate_chunk_ids[:10]}")

    total = len(chunks)
    parameter_count = total - chunk_types.get("manual_faq", 0)
    faq_count = chunk_types.get("manual_faq", 0)

    if total != EXPECTED_TOTAL_CHUNKS:
        errors.append(
            f"文本块总数应为 {EXPECTED_TOTAL_CHUNKS}，实际为 {total}"
        )
    if len(product_ids) != EXPECTED_PRODUCTS:
        errors.append(
            f"产品数应为 {EXPECTED_PRODUCTS}，实际为 {len(product_ids)}"
        )
    if parameter_count != EXPECTED_PARAMETER_CHUNKS:
        errors.append(
            f"参数文本块应为 {EXPECTED_PARAMETER_CHUNKS}，实际为 {parameter_count}"
        )
    if faq_count != EXPECTED_FAQ_CHUNKS:
        errors.append(
            f"FAQ 文本块应为 {EXPECTED_FAQ_CHUNKS}，实际为 {faq_count}"
        )

    stats = {
        "total_chunks": total,
        "product_count": len(product_ids),
        "product_ids": sorted(product_ids),
        "parameter_chunk_count": parameter_count,
        "faq_chunk_count": faq_count,
        "chunk_type_counts": dict(chunk_types),
        "device_type_counts": dict(device_types),
        "errors": errors,
        "warnings": warnings,
    }

    LOGGER.info("数据校验结果：")
    LOGGER.info("  文本块总数：%s", total)
    LOGGER.info("  产品数：%s", len(product_ids))
    LOGGER.info("  参数文本块：%s", parameter_count)
    LOGGER.info("  FAQ 文本块：%s", faq_count)
    LOGGER.info("  重复 chunk_id：%s", len(duplicate_chunk_ids))
    LOGGER.info("  errors：%s", len(errors))
    LOGGER.info("  warnings：%s", len(warnings))

    if errors:
        error_text = "\n".join(f"- {item}" for item in errors)
        raise ValueError(f"输入数据校验失败：\n{error_text}")

    return stats


def make_metadata(
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    metadata: list[dict[str, Any]] = []

    for vector_id, chunk in enumerate(chunks):
        device_type = normalize_device_type(chunk)
        topic = normalize_topic(chunk)

        metadata.append(
            {
                "vector_id": vector_id,
                "chunk_id": chunk["chunk_id"],
                "qa_id": chunk.get("qa_id"),
                "product_id": chunk["product_id"],
                "product_name": chunk["product_name"],
                "device_type": device_type,
                # 保留兼容字段，避免旧服务读取失败。
                "product_category": chunk.get(
                    "product_category",
                    device_type,
                ),
                "chunk_type": chunk["chunk_type"],
                "topic": topic,
                "text": chunk["text"],
                "source_url": chunk["source_url"],
                "data_status": chunk.get("data_status", ""),
                "source_domain_verified": chunk.get(
                    "source_domain_verified",
                    False,
                ),
                "source_content_verified": chunk.get(
                    "source_content_verified",
                    False,
                ),
            }
        )

    return metadata


def save_faiss_index(index: faiss.Index, path: Path) -> None:
    """
    使用序列化字节保存索引，避免 FAISS C++ 直接处理中文路径。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = faiss.serialize_index(index)

    with path.open("wb") as file_obj:
        file_obj.write(np.asarray(serialized, dtype=np.uint8).tobytes())


def write_jsonl(
    path: Path,
    records: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="\n") as file_obj:
        for record in records:
            file_obj.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )


def write_manifest(
    *,
    dimension: int,
    vector_count: int,
    metadata_count: int,
    stats: dict[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    manifest = {
        "knowledge_base": "wearables",
        "version": "p2_7",
        "embedding_model": MODEL_NAME,
        "embedding_dimension": dimension,
        "index_type": INDEX_TYPE,
        "vector_count": vector_count,
        "metadata_count": metadata_count,
        "product_count": stats["product_count"],
        "product_ids": stats["product_ids"],
        "parameter_chunk_count": stats["parameter_chunk_count"],
        "faq_chunk_count": stats["faq_chunk_count"],
        "source_file": str(INPUT_CHUNKS_PATH.relative_to(REPO_ROOT)),
        "source_sha256": sha256_file(INPUT_CHUNKS_PATH),
        "index_file": str(INDEX_PATH.relative_to(REPO_ROOT)),
        "metadata_file": str(METADATA_PATH.relative_to(REPO_ROOT)),
        "normalized_embeddings": True,
        "similarity": "cosine_via_inner_product",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "build_elapsed_seconds": round(elapsed_seconds, 3),
    }

    with MANIFEST_PATH.open("w", encoding="utf-8") as file_obj:
        json.dump(
            manifest,
            file_obj,
            ensure_ascii=False,
            indent=2,
        )
        file_obj.write("\n")

    return manifest


def write_validation_report(
    *,
    stats: dict[str, Any],
    dimension: int,
    vector_count: int,
    metadata_count: int,
    elapsed_seconds: float,
) -> None:
    warnings = stats.get("warnings", [])

    lines = [
        "# P2-7 FAISS知识库构建校验报告",
        "",
        "## 构建结果",
        "",
        f"- 输入文本块：{stats['total_chunks']}",
        f"- 产品数量：{stats['product_count']}",
        f"- 参数文本块：{stats['parameter_chunk_count']}",
        f"- FAQ文本块：{stats['faq_chunk_count']}",
        f"- FAISS向量数量：{vector_count}",
        f"- Metadata数量：{metadata_count}",
        f"- Embedding模型：`{MODEL_NAME}`",
        f"- Embedding维度：{dimension}",
        f"- 索引类型：`{INDEX_TYPE}`",
        f"- 构建耗时：{elapsed_seconds:.2f}秒",
        "",
        "## 一致性校验",
        "",
        f"- 向量数量与输入一致：{'通过' if vector_count == stats['total_chunks'] else '失败'}",
        f"- Metadata数量与输入一致：{'通过' if metadata_count == stats['total_chunks'] else '失败'}",
        f"- 产品覆盖16款：{'通过' if stats['product_count'] == EXPECTED_PRODUCTS else '失败'}",
        f"- errors：{len(stats.get('errors', []))}",
        f"- warnings：{len(warnings)}",
        "",
        "## 警告",
        "",
    ]

    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "## 输出文件",
            "",
            f"- `{INDEX_PATH.relative_to(REPO_ROOT)}`",
            f"- `{METADATA_PATH.relative_to(REPO_ROOT)}`",
            f"- `{MANIFEST_PATH.relative_to(REPO_ROOT)}`",
            "",
        ]
    )

    VALIDATION_REPORT_PATH.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


# ============================================================
# 主流程
# ============================================================
def build() -> None:
    start_time = time.time()

    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    LOGGER.info("=" * 60)
    LOGGER.info("P2-7：构建穿戴设备FAISS向量知识库")
    LOGGER.info("=" * 60)
    LOGGER.info("输入文件：%s", INPUT_CHUNKS_PATH)
    LOGGER.info("索引输出：%s", INDEX_PATH)
    LOGGER.info("元数据输出：%s", METADATA_PATH)

    chunks = load_jsonl(INPUT_CHUNKS_PATH)
    stats = validate_chunks(chunks)

    LOGGER.info("加载Embedding模型：%s", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)

    dimension = model.get_sentence_embedding_dimension()
    if not dimension:
        raise RuntimeError("无法获取Embedding维度")

    texts = [str(chunk["text"]).strip() for chunk in chunks]

    LOGGER.info("开始生成向量，共%s条文本", len(texts))
    embeddings = model.encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    embeddings = np.asarray(embeddings, dtype=np.float32)

    if embeddings.shape != (len(chunks), dimension):
        raise RuntimeError(
            "向量矩阵形状异常："
            f"预期 {(len(chunks), dimension)}，"
            f"实际 {embeddings.shape}"
        )

    LOGGER.info("建立FAISS索引：%s", INDEX_TYPE)
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)

    if index.ntotal != len(chunks):
        raise RuntimeError(
            f"索引向量数异常：{index.ntotal} != {len(chunks)}"
        )

    metadata = make_metadata(chunks)
    if len(metadata) != index.ntotal:
        raise RuntimeError(
            f"Metadata数量异常：{len(metadata)} != {index.ntotal}"
        )

    save_faiss_index(index, INDEX_PATH)
    write_jsonl(METADATA_PATH, metadata)

    elapsed_seconds = time.time() - start_time

    write_manifest(
        dimension=dimension,
        vector_count=index.ntotal,
        metadata_count=len(metadata),
        stats=stats,
        elapsed_seconds=elapsed_seconds,
    )
    write_validation_report(
        stats=stats,
        dimension=dimension,
        vector_count=index.ntotal,
        metadata_count=len(metadata),
        elapsed_seconds=elapsed_seconds,
    )

    LOGGER.info("构建完成")
    LOGGER.info("  输入文本块：%s", len(chunks))
    LOGGER.info("  FAISS向量：%s", index.ntotal)
    LOGGER.info("  Metadata：%s", len(metadata))
    LOGGER.info("  产品覆盖：%s/16", stats["product_count"])
    LOGGER.info("  参数文本块：%s", stats["parameter_chunk_count"])
    LOGGER.info("  FAQ文本块：%s", stats["faq_chunk_count"])
    LOGGER.info("  errors：0")
    LOGGER.info("  warnings：%s", len(stats["warnings"]))
    LOGGER.info("  耗时：%.2f秒", elapsed_seconds)


def main() -> int:
    try:
        build()
        return 0
    except Exception as exc:
        LOGGER.exception("构建失败：%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
