"""
构建 FAISS 向量库

流程:
  1) 读取 processed/chunks.jsonl (46 个文本块, 8 款产品)
  2) 使用 BAAI/bge-small-zh-v1.5 对 content 生成 512 维归一化向量
  3) 建立 FAISS IndexFlatIP 索引 (内积 = 余弦相似度)
  4) 保存 index.faiss 到 vector_store/
  5) 保存 metadata.jsonl (一行一条, 与向量顺序严格一致)

用法:  python backend/build_vector_store.py
"""
import json
import os
import sys
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
CHUNKS_PATH = PROJECT_ROOT / "data" / "processed" / "chunks.jsonl"
VECTOR_STORE_DIR = PROJECT_ROOT / "vector_store"
INDEX_PATH = VECTOR_STORE_DIR / "index.faiss"
METADATA_PATH = VECTOR_STORE_DIR / "metadata.jsonl"

# ── 模型配置 ──
# 不要写死本地 snapshot 哈希路径, 使用模型名让 sentence-transformers 自动处理缓存
MODEL_NAME = "BAAI/bge-small-zh-v1.5"
# 说明: BGE small zh v1.5, 512 维, 中文优化, 归一化向量 + IndexFlatIP = 余弦相似度, 离线可用无须 API Key


def _validate_chunks(chunks: list[dict]) -> None:
    """验证输入数据完整性"""
    product_ids = {c["product_id"] for c in chunks}
    empty = sum(1 for c in chunks if not c.get("content", "").strip())
    chunk_ids = [c.get("chunk_id") for c in chunks]
    duplicates = [cid for cid in set(chunk_ids) if chunk_ids.count(cid) > 1]

    print(f"  总计: {len(chunks)} 条")
    print(f"  覆盖产品: {sorted(product_ids)} ({len(product_ids)} 款)")
    print(f"  空正文: {empty} 条 (应为0)")
    print(f"  重复 chunk_id: {len(duplicates)} 个 (应为0)")

    if empty > 0:
        raise ValueError(f"发现 {empty} 条空正文字段, 请检查输入文件")
    if duplicates:
        raise ValueError(f"发现重复 chunk_id: {duplicates}")


def build():
    """主流程: 读取 → 向量化 → 建索引 → 保存"""

    # ── 1. 读取 chunks ──
    print("=" * 56)
    print("  任务17: 构建 FAISS 向量库")
    print("=" * 56)

    print(f"\n[1/4] 读取文本块: {CHUNKS_PATH}")
    with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]
    _validate_chunks(chunks)

    # ── 2. 加载 Embedding 模型 ──
    print(f"\n[2/4] 加载 Embedding 模型: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)
    dim = model.get_sentence_embedding_dimension() if hasattr(model, 'get_sentence_embedding_dimension') else model.get_embedding_dimension()
    print(f"  向量维度: {dim}")

    # ── 3. 生成向量 ──
    print(f"\n[3/4] 生成向量 (BGE 归一化, 内积=余弦相似度)...")
    texts = [c["content"] for c in chunks]
    # BGE 模型推荐 normalize_embeddings=True, 配合 IndexFlatIP 实现余弦相似度检索
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    print(f"  向量矩阵: {embeddings.shape}")

    # ── 4. 建立 FAISS 索引 ──
    index = faiss.IndexFlatIP(dim)           # 内积索引 (向量已归一化 → 余弦相似度)
    index.add(embeddings.astype(np.float32))
    print(f"  索引规模: {index.ntotal} 个向量")

    # ── 5. 保存索引 ──
    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))
    print(f"\n[4/4] 索引已保存: {INDEX_PATH}")

    # ── 6. 保存 metadata (与 FAISS 索引顺序严格一致) ──
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        for i, c in enumerate(chunks):
            meta = {
                "vector_id": i,                    # vector_id ↔ FAISS 索引位置
                "chunk_id": c["chunk_id"],
                "product_id": c["product_id"],
                "product_name": c["product_name"],
                "model": c["model"],
                "section": c["section"],
                "content": c["content"],
                "source_file": c["source_file"],
                "source_url": c["source_url"],
                "page": c["page"],
                "page_start": c["page_start"],
                "page_end": c["page_end"],
            }
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
    print(f"  Metadata 已保存: {METADATA_PATH} ({i + 1} 条, vector_id 0~{i})")

    print("\n" + "=" * 56)
    print("  构建完成! 下一步: python backend/retrieval_service.py")
    print("=" * 56)


if __name__ == "__main__":
    build()
