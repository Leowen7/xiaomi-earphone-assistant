"""
穿戴设备 FAISS 检索服务

加载 data/wearables/faiss_index/ 下的 FAISS 索引 + metadata，
提供 search_wearable 函数。

核心接口:
    search_wearable(query, product_id=None, product_category=None, top_k=3) -> list[dict]

与耳机检索服务的区别:
    - 加载 data/wearables/faiss_index/ 而非 vector_store/
    - 返回字段包含 product_category、chunk_type
    - 支持 product_category 过滤 (smart_band / smart_watch)

用法:
    from backend.wearable_retrieval_service import search_wearable
    results = search_wearable("续航最长的智能手环", product_category="smart_band")
"""

import json
import os
from pathlib import Path

# ── HuggingFace 国内镜像 (必须在 import sentence_transformers 之前设置) ──
if not os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import faiss
import numpy as np
import shutil
from sentence_transformers import SentenceTransformer

# ── 路径 ──
SCRIPT_DIR = Path(__file__).resolve().parent          # backend/
PROJECT_ROOT = SCRIPT_DIR.parent                      # 仓库根目录
FAISS_DIR = PROJECT_ROOT / "data" / "wearables" / "faiss_index"
INDEX_PATH = FAISS_DIR / "index.faiss"
METADATA_PATH = FAISS_DIR / "metadata.jsonl"
FAISS_TEMP_DIR = Path("F:/sprint-2/wearable_faiss_temp")
FAISS_TEMP_INDEX = FAISS_TEMP_DIR / "index.faiss"

# ── 模型配置 (与耳机检索服务保持一致) ──
MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# ── 全局缓存: 资源只加载一次 ──
_model: SentenceTransformer | None = None
_index: faiss.IndexFlatIP | None = None
_metadata: list[dict] | None = None
# 产品ID → 向量索引列表
_product_to_indices: dict[str, list[int]] | None = None
# 产品类别 → 向量索引列表
_category_to_indices: dict[str, list[int]] | None = None


def _load_resources():
    """懒加载: 模型 + FAISS 索引 + metadata + 索引映射"""
    global _model, _index, _metadata, _product_to_indices, _category_to_indices

    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    if _index is None:
        # FAISS C++ 层不支持中文路径 → 复制到 ASCII 临时路径再读取
        FAISS_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(INDEX_PATH), str(FAISS_TEMP_INDEX))
        _index = faiss.read_index(str(FAISS_TEMP_INDEX))
    if _metadata is None:
        with open(METADATA_PATH, "r", encoding="utf-8") as f:
            _metadata = [json.loads(line) for line in f if line.strip()]
    if _product_to_indices is None:
        _product_to_indices = {}
        _category_to_indices = {}
        for i, m in enumerate(_metadata):
            pid = m["product_id"]
            _product_to_indices.setdefault(pid, []).append(i)
            cat = m.get("product_category", "")
            if cat:
                _category_to_indices.setdefault(cat, []).append(i)

    return _model, _index, _metadata, _product_to_indices, _category_to_indices


# ── 合法筛选值集合 ──
_VALID_PRODUCT_IDS: set[str] | None = None
_VALID_CATEGORIES: set[str] | None = None


def _get_valid_ids_and_categories():
    global _VALID_PRODUCT_IDS, _VALID_CATEGORIES
    if _VALID_PRODUCT_IDS is None:
        _, _, metadata, _, _ = _load_resources()
        _VALID_PRODUCT_IDS = {m["product_id"] for m in metadata}
        _VALID_CATEGORIES = {m.get("product_category", "") for m in metadata if m.get("product_category")}
    return _VALID_PRODUCT_IDS, _VALID_CATEGORIES


def _validate_input(query: str, product_id: str | None, product_category: str | None, top_k: int) -> None:
    """输入参数校验"""
    # 1) query 不能为空
    if not query or not isinstance(query, str) or not query.strip():
        raise ValueError("query 不能为空字符串")

    # 2) top_k 必须在 1~5 范围内
    if not isinstance(top_k, int):
        raise ValueError(f"top_k 必须为整数, 实际类型: {type(top_k).__name__}")
    if top_k < 1:
        raise ValueError(f"top_k 必须 >= 1, 实际: {top_k}")
    if top_k > 5:
        raise ValueError(f"top_k 不能超过 5, 实际: {top_k}")

    # 3) product_id 格式校验
    if product_id is not None:
        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("product_id 必须为非空字符串")

    # 4) product_category 格式校验
    if product_category is not None:
        if not isinstance(product_category, str) or not product_category.strip():
            raise ValueError("product_category 必须为非空字符串")


def search_wearable(
    query: str,
    product_id: str | None = None,
    product_category: str | None = None,
    top_k: int = 3,
) -> list[dict]:
    """
    检索穿戴设备知识库。

    参数:
        query:             用户查询文本 (如 "续航最长的智能手环")
        product_id:        可选产品ID过滤 (如 "B01"), None=全部产品
        product_category:  可选产品类别过滤 ("smart_band" / "smart_watch"), None=全部
        top_k:             返回最相关的结果数量, 1~5, 默认3

    返回:
        list[dict]: 每个结果包含:
            chunk_id, product_id, product_name, product_category,
            chunk_type, text, source_url, score

    异常:
        ValueError: query 为空、top_k 越界、筛选参数格式非法
    """
    _validate_input(query, product_id, product_category, top_k)

    model, index, metadata, product_to_indices, category_to_indices = _load_resources()

    # ── 1. 确定搜索范围 ──
    # 优先用 product_id 过滤，其次用 product_category
    if product_id is not None:
        target_indices = product_to_indices.get(product_id, [])
        if not target_indices:
            return []
        search_k = index.ntotal
    elif product_category is not None:
        target_indices = category_to_indices.get(product_category, [])
        if not target_indices:
            return []
        search_k = index.ntotal
    else:
        target_indices = None
        search_k = min(top_k, index.ntotal)

    # ── 2. 生成查询向量 ──
    query_vec = model.encode(
        [query],
        normalize_embeddings=True,
    ).astype(np.float32)

    # ── 3. FAISS 向量检索 ──
    scores, indices = index.search(query_vec, search_k)

    # ── 4. 组装结果 ──
    results = []
    seen_ids: set[str] = set()

    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:
            continue

        if target_indices is not None and idx not in target_indices:
            continue

        meta = metadata[idx]

        if meta["chunk_id"] in seen_ids:
            continue
        seen_ids.add(meta["chunk_id"])

        results.append({
            "chunk_id": meta["chunk_id"],
            "product_id": meta["product_id"],
            "product_name": meta["product_name"],
            "product_category": meta["product_category"],
            "chunk_type": meta["chunk_type"],
            "text": meta["text"],
            "source_url": meta["source_url"],
            "score": round(float(score), 4),
        })

        if len(results) >= top_k:
            break

    return results
