#!/usr/bin/env python3
"""
P2-7: 穿戴设备 FAISS 向量知识库构建脚本

基于 P2-6 生成的 240 条穿戴设备文本块，构建独立 FAISS 向量知识库。

流程:
  1) 读取 wearable_all_chunks.jsonl (240 条, 16 款产品)
  2) 使用 BAAI/bge-small-zh-v1.5 对 text 生成 512 维归一化向量
  3) 建立 FAISS IndexFlatIP 索引 (内积 = 余弦相似度)
  4) 保存 index.faiss 到 data/wearables/faiss_index/
  5) 保存 metadata.jsonl (一行一条, 与向量顺序严格一致)

输出目录:
  data/wearables/faiss_index/
    ├── index.faiss
    └── metadata.jsonl

用法（在仓库根目录执行）:
    python scripts/p2_6/build_index.py
"""

import json
import os
import sys
import time
from pathlib import Path

# ── HuggingFace 国内镜像 (必须在 import sentence_transformers 之前设置) ──
if not os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import faiss
import numpy as np
import shutil
from sentence_transformers import SentenceTransformer

# ---------- 仓库路径配置 ----------
REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    REPO_ROOT
    / "data"
    / "wearables"
    / "processed"
    / "chunks"
    / "wearable_all_chunks.jsonl"
)

FAISS_DIR = REPO_ROOT / "data" / "wearables" / "faiss_index"
INDEX_PATH = FAISS_DIR / "index.faiss"
METADATA_PATH = FAISS_DIR / "metadata.jsonl"

# FAISS C++ 层不支持中文路径，使用 ASCII 路径作为中转
FAISS_TEMP_DIR = Path("F:/sprint-2/wearable_faiss_temp")
FAISS_TEMP_INDEX = FAISS_TEMP_DIR / "index.faiss"

# ── 模型配置 (与耳机知识库保持一致) ──
MODEL_NAME = "BAAI/bge-small-zh-v1.5"
# 512 维, 中文优化, 归一化向量 + IndexFlatIP = 余弦相似度


# ===========================================================
#  数据校验
# ===========================================================
def validate_chunks(chunks: list[dict]) -> None:
    """验证穿戴设备文本块数据完整性"""
    product_ids = set()
    empty_text = 0
    chunk_ids = []
    chunk_types = set()

    for c in chunks:
        product_ids.add(c.get("product_id", ""))
        chunk_ids.append(c.get("chunk_id", ""))
        chunk_types.add(c.get("chunk_type", ""))
        if not c.get("text", "").strip():
            empty_text += 1

    duplicates = [cid for cid in set(chunk_ids) if chunk_ids.count(cid) > 1]

    print(f"  总计: {len(chunks)} 条")
    print(f"  覆盖产品: {sorted(product_ids)} ({len(product_ids)} 款)")
    print(f"  文本块类型: {sorted(chunk_types)}")
    print(f"  空正文: {empty_text} 条 (应为 0)")
    print(f"  重复 chunk_id: {len(duplicates)} 个 (应为 0)")

    if empty_text > 0:
        raise ValueError(f"发现 {empty_text} 条空正文字段, 请检查输入文件")
    if duplicates:
        raise ValueError(f"发现重复 chunk_id: {duplicates}")


# ===========================================================
#  主流程
# ===========================================================
def build():
    """读取 → 向量化 → 建索引 → 保存"""
    start_time = time.time()

    print("=" * 56)
    print("  P2-7: 构建穿戴设备 FAISS 向量知识库")
    print("=" * 56)

    # ── 1. 读取文本块 ──
    print(f"\n[1/5] 读取文本块: {INPUT_FILE}")
    if not INPUT_FILE.exists():
        print(f"[ERROR] 输入文件不存在: {INPUT_FILE}")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]
    print(f"  共 {len(chunks)} 条文本块")
    validate_chunks(chunks)

    # ── 2. 加载 Embedding 模型 ──
    print(f"\n[2/5] 加载 Embedding 模型: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)
    dim = model.get_sentence_embedding_dimension()
    print(f"  向量维度: {dim}")

    # ── 3. 生成向量 ──
    print(f"\n[3/5] 生成向量 (BGE 归一化, 内积=余弦相似度)...")
    texts = [c["text"] for c in chunks]
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    print(f"  向量矩阵: {embeddings.shape}")

    # ── 4. 建立 FAISS 索引 ──
    print(f"\n[4/5] 建立 FAISS 索引...")
    index = faiss.IndexFlatIP(dim)           # 内积索引 (向量已归一化 → 余弦相似度)
    index.add(embeddings.astype(np.float32))
    print(f"  索引规模: {index.ntotal} 个向量")

    # ── 5. 保存索引 ──
    # FAISS C++ 层不支持中文路径 → 先写入 ASCII 临时路径, 再复制到目标目录
    FAISS_DIR.mkdir(parents=True, exist_ok=True)
    FAISS_TEMP_DIR.mkdir(parents=True, exist_ok=True)

    faiss.write_index(index, str(FAISS_TEMP_INDEX))
    shutil.copy2(str(FAISS_TEMP_INDEX), str(INDEX_PATH))
    # 清理临时文件
    FAISS_TEMP_INDEX.unlink(missing_ok=True)
    try:
        FAISS_TEMP_DIR.rmdir()
    except OSError:
        pass
    print(f"\n[5/5] 索引已保存: {INDEX_PATH}")

    # ── 6. 保存 metadata (与 FAISS 索引顺序严格一致) ──
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        for i, c in enumerate(chunks):
            meta = {
                "vector_id": i,
                "chunk_id": c["chunk_id"],
                "product_id": c["product_id"],
                "product_name": c["product_name"],
                "product_category": c["product_category"],
                "chunk_type": c["chunk_type"],
                "text": c["text"],
                "source_url": c["source_url"],
                "data_status": c.get("data_status", ""),
            }
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
    print(f"  Metadata 已保存: {METADATA_PATH} ({i + 1} 条, vector_id 0~{i})")

    elapsed = time.time() - start_time
    print(f"\n  总耗时: {elapsed:.1f} 秒")

    print("\n" + "=" * 56)
    print("  构建完成!")
    print(f"  输入: {len(chunks)} 条文本块")
    print(f"  索引: {index.ntotal} 个向量, {dim} 维")
    print(f"  输出: {FAISS_DIR}")
    print("=" * 56)


if __name__ == "__main__":
    build()
