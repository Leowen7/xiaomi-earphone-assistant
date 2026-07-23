#!/usr/bin/env python3
"""
P2-7：穿戴设备 FAISS 检索服务

加载已经构建完成的穿戴设备 FAISS 索引与元数据，不在查询阶段重新构建索引。

默认资源位置：
    vector_store/wearables/wearable.faiss
    vector_store/wearables/wearable_metadata.jsonl
    vector_store/wearables/manifest.json

核心接口：
    search_wearable_knowledge(
        query,
        top_k=5,
        product_id=None,
        device_type=None,
        topic=None,
        chunk_type=None,
    )

兼容旧接口：
    search_wearable(...)
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

# 必须在导入 sentence_transformers 前设置。
if not os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


# ============================================================
# 路径与配置
# ============================================================
# 当前文件位于 backend/services/wearable_retrieval_service.py
REPO_ROOT = Path(__file__).resolve().parents[2]

VECTOR_STORE_DIR = REPO_ROOT / "vector_store" / "wearables"
INDEX_PATH = VECTOR_STORE_DIR / "wearable.faiss"
METADATA_PATH = VECTOR_STORE_DIR / "wearable_metadata.jsonl"
MANIFEST_PATH = VECTOR_STORE_DIR / "manifest.json"

DEFAULT_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
DEFAULT_TOP_K = 5
MAX_TOP_K = 20


# ============================================================
# 全局缓存
# ============================================================
_model: SentenceTransformer | None = None
_index: faiss.Index | None = None
_metadata: list[dict[str, Any]] | None = None
_manifest: dict[str, Any] | None = None
_resource_lock = threading.Lock()


# ============================================================
# 资源加载
# ============================================================
def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {
            "embedding_model": DEFAULT_MODEL_NAME,
        }

    try:
        with MANIFEST_PATH.open("r", encoding="utf-8") as file_obj:
            manifest = json.load(file_obj)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"manifest.json 解析失败：{MANIFEST_PATH}"
        ) from exc

    if not isinstance(manifest, dict):
        raise RuntimeError("manifest.json 顶层必须是JSON对象")

    return manifest


def _load_faiss_index(path: Path) -> faiss.Index:
    """
    通过Python读取字节后反序列化索引，避免FAISS C++层直接处理中文路径。
    """
    if not path.exists():
        raise FileNotFoundError(
            f"穿戴设备FAISS索引不存在：{path}。"
            "请先运行 scripts/p2_7/build_wearable_faiss.py"
        )

    raw = path.read_bytes()
    if not raw:
        raise RuntimeError(f"FAISS索引文件为空：{path}")

    buffer = np.frombuffer(raw, dtype=np.uint8)
    try:
        return faiss.deserialize_index(buffer)
    except Exception as exc:
        raise RuntimeError(f"FAISS索引加载失败：{path}") from exc


def _load_metadata(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"穿戴设备元数据不存在：{path}。"
            "请先运行 scripts/p2_7/build_wearable_faiss.py"
        )

    metadata: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as file_obj:
        for line_no, line in enumerate(file_obj, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            try:
                item = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Metadata第{line_no}行解析失败：{exc}"
                ) from exc

            if not isinstance(item, dict):
                raise RuntimeError(
                    f"Metadata第{line_no}行不是JSON对象"
                )

            metadata.append(item)

    return metadata


def _validate_loaded_resources(
    index: faiss.Index,
    metadata: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    if index.ntotal != len(metadata):
        raise RuntimeError(
            "FAISS索引与Metadata数量不一致："
            f"index.ntotal={index.ntotal}，"
            f"metadata={len(metadata)}"
        )

    for position, item in enumerate(metadata):
        vector_id = item.get("vector_id")
        if vector_id is not None and vector_id != position:
            raise RuntimeError(
                "Metadata顺序与vector_id不一致："
                f"第{position}条的vector_id={vector_id}"
            )

        for field in (
            "chunk_id",
            "product_id",
            "product_name",
            "chunk_type",
            "text",
        ):
            if item.get(field) is None or str(item.get(field)).strip() == "":
                raise RuntimeError(
                    f"Metadata第{position}条缺少字段：{field}"
                )

    expected_dimension = manifest.get("embedding_dimension")
    if expected_dimension is not None:
        try:
            expected_dimension = int(expected_dimension)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "manifest中的embedding_dimension不是整数"
            ) from exc

        if index.d != expected_dimension:
            raise RuntimeError(
                "FAISS维度与manifest不一致："
                f"index.d={index.d}，"
                f"manifest={expected_dimension}"
            )


def _load_resources() -> tuple[
    SentenceTransformer,
    faiss.Index,
    list[dict[str, Any]],
    dict[str, Any],
]:
    """
    线程安全懒加载。资源仅在首次查询时加载一次。
    """
    global _model, _index, _metadata, _manifest

    if (
        _model is not None
        and _index is not None
        and _metadata is not None
        and _manifest is not None
    ):
        return _model, _index, _metadata, _manifest

    with _resource_lock:
        if _manifest is None:
            _manifest = _load_manifest()

        if _index is None:
            _index = _load_faiss_index(INDEX_PATH)

        if _metadata is None:
            _metadata = _load_metadata(METADATA_PATH)

        _validate_loaded_resources(
            _index,
            _metadata,
            _manifest,
        )

        if _model is None:
            model_name = str(
                _manifest.get(
                    "embedding_model",
                    DEFAULT_MODEL_NAME,
                )
            ).strip() or DEFAULT_MODEL_NAME

            _model = SentenceTransformer(model_name)

            model_dimension = (
                _model.get_sentence_embedding_dimension()
            )
            if model_dimension and model_dimension != _index.d:
                raise RuntimeError(
                    "查询模型维度与FAISS索引不一致："
                    f"model={model_dimension}，index={_index.d}"
                )

    return _model, _index, _metadata, _manifest


def reset_wearable_retrieval_cache() -> None:
    """
    清空资源缓存，主要用于测试或索引文件更新后重新加载。
    """
    global _model, _index, _metadata, _manifest

    with _resource_lock:
        _model = None
        _index = None
        _metadata = None
        _manifest = None


# ============================================================
# 输入与筛选
# ============================================================
def _normalize_optional_filter(
    value: str | None,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError(
            f"{field_name}必须是字符串或None，"
            f"实际类型为{type(value).__name__}"
        )

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name}不能是空字符串")

    return normalized


def _validate_search_input(
    query: str,
    top_k: int,
    product_id: str | None,
    device_type: str | None,
    topic: str | None,
    chunk_type: str | None,
) -> tuple[str, str | None, str | None, str | None, str | None]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query必须是非空字符串")

    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise ValueError("top_k必须是整数")

    if top_k < 1 or top_k > MAX_TOP_K:
        raise ValueError(
            f"top_k必须在1到{MAX_TOP_K}之间，实际为{top_k}"
        )

    return (
        query.strip(),
        _normalize_optional_filter(product_id, "product_id"),
        _normalize_optional_filter(device_type, "device_type"),
        _normalize_optional_filter(topic, "topic"),
        _normalize_optional_filter(chunk_type, "chunk_type"),
    )


def _metadata_device_type(item: dict[str, Any]) -> str:
    return str(
        item.get("device_type")
        or item.get("product_category")
        or ""
    ).strip()


def _metadata_matches(
    item: dict[str, Any],
    *,
    product_id: str | None,
    device_type: str | None,
    topic: str | None,
    chunk_type: str | None,
) -> bool:
    if (
        product_id is not None
        and str(item.get("product_id", "")).strip() != product_id
    ):
        return False

    if (
        device_type is not None
        and _metadata_device_type(item) != device_type
    ):
        return False

    if (
        topic is not None
        and str(item.get("topic", "")).strip() != topic
    ):
        return False

    if (
        chunk_type is not None
        and str(item.get("chunk_type", "")).strip() != chunk_type
    ):
        return False

    return True


def _validate_filter_values(
    metadata: list[dict[str, Any]],
    *,
    product_id: str | None,
    device_type: str | None,
    topic: str | None,
    chunk_type: str | None,
) -> None:
    if product_id is not None:
        valid_product_ids = {
            str(item.get("product_id", "")).strip()
            for item in metadata
            if item.get("product_id")
        }
        if product_id not in valid_product_ids:
            raise ValueError(
                f"未知product_id：{product_id}；"
                f"可用值：{sorted(valid_product_ids)}"
            )

    if device_type is not None:
        valid_device_types = {
            _metadata_device_type(item)
            for item in metadata
            if _metadata_device_type(item)
        }
        if device_type not in valid_device_types:
            raise ValueError(
                f"未知device_type：{device_type}；"
                f"可用值：{sorted(valid_device_types)}"
            )

    if topic is not None:
        valid_topics = {
            str(item.get("topic", "")).strip()
            for item in metadata
            if item.get("topic")
        }
        if topic not in valid_topics:
            raise ValueError(
                f"未知topic：{topic}；"
                f"可用值：{sorted(valid_topics)}"
            )

    if chunk_type is not None:
        valid_chunk_types = {
            str(item.get("chunk_type", "")).strip()
            for item in metadata
            if item.get("chunk_type")
        }
        if chunk_type not in valid_chunk_types:
            raise ValueError(
                f"未知chunk_type：{chunk_type}；"
                f"可用值：{sorted(valid_chunk_types)}"
            )


# ============================================================
# 检索接口
# ============================================================
def search_wearable_knowledge(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    product_id: str | None = None,
    device_type: str | None = None,
    topic: str | None = None,
    chunk_type: str | None = None,
    *,
    product_category: str | None = None,
) -> list[dict[str, Any]]:
    """
    检索穿戴设备知识库。

    参数：
        query:
            用户中文查询。
        top_k:
            返回结果数量，范围1到20。
        product_id:
            可选产品ID过滤，如B02或W01。
        device_type:
            可选设备类型过滤，如smart_band或smart_watch。
        topic:
            可选主题过滤，如pairing、charging、reset。
        chunk_type:
            可选文本块类型过滤，如manual_faq。
        product_category:
            旧接口兼容参数，等价于device_type。新代码建议使用device_type。

    返回：
        每条结果包含rank、score、chunk_id、qa_id、product_id、
        product_name、device_type、product_category、chunk_type、topic、
        text、source_url和数据状态。
    """
    if product_category is not None:
        product_category = _normalize_optional_filter(
            product_category,
            "product_category",
        )

        if (
            device_type is not None
            and str(device_type).strip() != product_category
        ):
            raise ValueError(
                "device_type与product_category不能设置为不同值"
            )

        device_type = product_category

    (
        normalized_query,
        product_id,
        device_type,
        topic,
        chunk_type,
    ) = _validate_search_input(
        query=query,
        top_k=top_k,
        product_id=product_id,
        device_type=device_type,
        topic=topic,
        chunk_type=chunk_type,
    )

    model, index, metadata, _ = _load_resources()

    _validate_filter_values(
        metadata,
        product_id=product_id,
        device_type=device_type,
        topic=topic,
        chunk_type=chunk_type,
    )

    candidate_count = sum(
        1
        for item in metadata
        if _metadata_matches(
            item,
            product_id=product_id,
            device_type=device_type,
            topic=topic,
            chunk_type=chunk_type,
        )
    )

    if candidate_count == 0:
        return []

    query_vector = model.encode(
        [normalized_query],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    query_vector = np.asarray(query_vector, dtype=np.float32)

    if query_vector.shape != (1, index.d):
        raise RuntimeError(
            "查询向量维度异常："
            f"预期(1, {index.d})，实际{query_vector.shape}"
        )

    # 数据规模仅240条。搜索全库后再过滤，可保证过滤条件下的Top K正确。
    scores, indices = index.search(
        query_vector,
        index.ntotal,
    )

    results: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()

    for score, vector_id in zip(scores[0], indices[0]):
        vector_id = int(vector_id)
        if vector_id < 0:
            continue

        item = metadata[vector_id]

        if not _metadata_matches(
            item,
            product_id=product_id,
            device_type=device_type,
            topic=topic,
            chunk_type=chunk_type,
        ):
            continue

        chunk_id = str(item["chunk_id"]).strip()
        if chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_id)

        device_type_value = _metadata_device_type(item)

        result = {
            "rank": len(results) + 1,
            "score": round(float(score), 6),
            "vector_id": vector_id,
            "chunk_id": chunk_id,
            "qa_id": item.get("qa_id"),
            "product_id": item["product_id"],
            "product_name": item["product_name"],
            "device_type": device_type_value,
            # 保留旧字段，方便既有代码继续使用。
            "product_category": item.get(
                "product_category",
                device_type_value,
            ),
            "chunk_type": item["chunk_type"],
            "topic": item.get("topic"),
            "text": item["text"],
            "source_url": item.get("source_url", ""),
            "data_status": item.get("data_status", ""),
            "source_domain_verified": item.get(
                "source_domain_verified",
                False,
            ),
            "source_content_verified": item.get(
                "source_content_verified",
                False,
            ),
        }

        results.append(result)

        if len(results) >= top_k:
            break

    return results


def search_wearable(
    query: str,
    product_id: str | None = None,
    product_category: str | None = None,
    top_k: int = 3,
    topic: str | None = None,
    chunk_type: str | None = None,
) -> list[dict[str, Any]]:
    """
    兼容原P2-7接口。新代码优先调用search_wearable_knowledge。
    """
    return search_wearable_knowledge(
        query=query,
        top_k=top_k,
        product_id=product_id,
        device_type=product_category,
        topic=topic,
        chunk_type=chunk_type,
    )


__all__ = [
    "search_wearable_knowledge",
    "search_wearable",
    "reset_wearable_retrieval_cache",
]
