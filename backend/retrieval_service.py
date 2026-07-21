"""
检索服务: 加载 FAISS 索引 + metadata, 提供 search_manual 函数

核心接口:
    search_manual(query, product_id=None, top_k=3) -> list[dict]

用法:
    from backend.retrieval_service import search_manual
    results = search_manual("怎么重置耳机?", product_id="EAR003")
"""
import json
import os
from pathlib import Path

# ── HuggingFace 国内镜像 (必须在 import sentence_transformers 之前设置) ──
if not os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

# ── 路径 (基于项目根目录, 不硬编码绝对路径) ──
SCRIPT_DIR = Path(__file__).resolve().parent          # backend/
PROJECT_ROOT = SCRIPT_DIR.parent                      # f:\data
VECTOR_STORE_DIR = PROJECT_ROOT / "vector_store"
INDEX_PATH = VECTOR_STORE_DIR / "index.faiss"
METADATA_PATH = VECTOR_STORE_DIR / "metadata.jsonl"

# ── 模型配置 (与 build_vector_store.py 保持一致) ──
# 不要写死本地 snapshot 哈希路径, 使用模型名让 sentence-transformers 自动处理缓存
MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# ── 全局缓存: 资源只加载一次 ──
_model: SentenceTransformer | None = None
_index: faiss.IndexFlatIP | None = None
_metadata: list[dict] | None = None
# 产品 → 向量索引列表的懒加载映射 (用于快速过滤)
_product_to_indices: dict[str, list[int]] | None = None


def _load_resources():
    """懒加载: 模型 + FAISS 索引 + metadata + 产品索引映射"""
    global _model, _index, _metadata, _product_to_indices

    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    if _index is None:
        _index = faiss.read_index(str(INDEX_PATH))
    if _metadata is None:
        with open(METADATA_PATH, "r", encoding="utf-8") as f:
            _metadata = [json.loads(line) for line in f]
    if _product_to_indices is None:
        _product_to_indices = {}
        for i, m in enumerate(_metadata):
            pid = m["product_id"]
            _product_to_indices.setdefault(pid, []).append(i)

    return _model, _index, _metadata, _product_to_indices


# ── 合法产品ID集合 (从 metadata 动态获取) ──
_VALID_PRODUCT_IDS: set[str] | None = None


def _get_valid_product_ids() -> set[str]:
    """获取合法产品ID列表 (懒加载)"""
    global _VALID_PRODUCT_IDS
    if _VALID_PRODUCT_IDS is None:
        _, _, metadata, _ = _load_resources()
        _VALID_PRODUCT_IDS = {m["product_id"] for m in metadata}
    return _VALID_PRODUCT_IDS


def _validate_input(query: str, product_id: str | None, top_k: int) -> None:
    """输入参数校验, 非法参数抛出 ValueError"""
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

    # 3) product_id 格式校验 (不存在的 product_id 由搜索层返回空列表, 不抛异常)
    if product_id is not None:
        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("product_id 必须为非空字符串")


def search_manual(
    query: str,
    product_id: str | None = None,
    top_k: int = 3,
) -> list[dict]:
    """
    检索说明书内容

    参数:
        query:      用户查询文本 (如 "怎么恢复出厂设置?")
        product_id: 可选产品ID过滤 (如 "EAR003"), None=全部8款
        top_k:      返回最相关的结果数量, 1~5, 默认3

    返回:
        list[dict]: 每个结果包含:
            chunk_id, product_id, product_name, section,
            content, source_file, page_start, page_end, score

    异常:
        ValueError: query 为空、top_k 越界、product_id 格式非法
    """
    # ── 输入校验 ──
    _validate_input(query, product_id, top_k)

    model, index, metadata, product_to_indices = _load_resources()

    # ── 1. 生成查询向量 ──
    query_vec = model.encode(
        [query],
        normalize_embeddings=True,
    ).astype(np.float32)

    # ── 2. 确定搜索范围 ──
    if product_id is not None:
        target_indices = product_to_indices.get(product_id, [])
        if not target_indices:
            return []  # 无匹配产品
        # 错误: 先 limit(top_k×3) 再 filter → 可能漏掉目标产品
        # 正确: 先搜全库再 filter, 最后取 top_k
        search_k = index.ntotal
    else:
        target_indices = None
        search_k = min(top_k, index.ntotal)

    # ── 3. FAISS 向量检索 ──
    scores, indices = index.search(query_vec, search_k)

    # ── 4. 组装结果 ──
    results = []
    seen_ids: set[str] = set()

    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:
            continue

        # 产品过滤
        if target_indices is not None and idx not in target_indices:
            continue

        meta = metadata[idx]

        # 去重 (同 chunk_id 只保留最高分)
        if meta["chunk_id"] in seen_ids:
            continue
        seen_ids.add(meta["chunk_id"])

        results.append({
            "chunk_id": meta["chunk_id"],
            "product_id": meta["product_id"],
            "product_name": meta["product_name"],
            "section": meta["section"],
            "content": meta["content"],
            "source_file": meta["source_file"],
            "page_start": meta["page_start"],
            "page_end": meta["page_end"],
            "score": round(float(score), 4),
        })

        if len(results) >= top_k:
            break

    # ── 5. 过滤后不足 top_k 时返回实际数量 (不报错) ──
    return results
