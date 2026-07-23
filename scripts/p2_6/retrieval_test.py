#!/usr/bin/env python3
"""
P2-7: 穿戴设备 FAISS 知识库检索验证脚本

加载 data/wearables/faiss_index/ 下的 FAISS 索引和 metadata，
执行 6 组标准检索测试，验证知识库的检索能力。

涵盖:
  - 智能手环/智能手表分类检索
  - 具体参数问题 (续航/NFC/定位/兼容性/屏幕/防水)

用法（在仓库根目录执行）:
    python scripts/p2_6/retrieval_test.py
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

FAISS_DIR = REPO_ROOT / "data" / "wearables" / "faiss_index"
INDEX_PATH = FAISS_DIR / "index.faiss"
METADATA_PATH = FAISS_DIR / "metadata.jsonl"
REPORT_PATH = FAISS_DIR / "retrieval_test_report.json"

MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# FAISS C++ 层不支持中文路径，使用 ASCII 路径作为中转
FAISS_TEMP_DIR = Path("F:/sprint-2/wearable_faiss_temp")
FAISS_TEMP_INDEX = FAISS_TEMP_DIR / "index.faiss"

# 6 组标准检索测试用例
TEST_CASES = [
    {
        "id": "T01",
        "query": "续航最长的智能手环",
        "description": "验证电池续航检索能力 (smart_band)",
        "expected_product_category": "smart_band",
        "expected_keywords": ["续航", "天"],
    },
    {
        "id": "T02",
        "query": "支持NFC的智能手表",
        "description": "验证功能过滤检索能力 (smart_watch + NFC)",
        "expected_product_category": "smart_watch",
        "expected_keywords": ["NFC"],
    },
    {
        "id": "T03",
        "query": "支持独立GNSS定位的设备",
        "description": "验证定位功能检索能力",
        "expected_keywords": ["GNSS", "定位"],
    },
    {
        "id": "T04",
        "query": "兼容iPhone的穿戴设备",
        "description": "验证兼容性信息检索能力",
        "expected_keywords": ["兼容", "iOS"],
    },
    {
        "id": "T05",
        "query": "屏幕亮度最高的智能手表",
        "description": "验证显示屏参数检索能力 (smart_watch)",
        "expected_product_category": "smart_watch",
        "expected_keywords": ["亮度", "尼特"],
    },
    {
        "id": "T06",
        "query": "支持5ATM防水的智能手环",
        "description": "验证防水参数检索能力 (smart_band)",
        "expected_product_category": "smart_band",
        "expected_keywords": ["防水", "5ATM"],
    },
]

PASS = 0
FAIL = 0
RESULTS = []


# ===========================================================
#  资源加载
# ===========================================================
_model: SentenceTransformer | None = None
_index: faiss.IndexFlatIP | None = None
_metadata: list[dict] | None = None


def load_resources():
    global _model, _index, _metadata
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
    return _model, _index, _metadata


# ===========================================================
#  检索函数
# ===========================================================
def search(query: str, top_k: int = 5) -> list[dict]:
    """
    在穿戴设备知识库中检索。

    参数:
        query:  查询文本
        top_k:  返回结果数量 (默认 5)

    返回:
        list[dict]: 每个结果包含 metadata 字段 + score
    """
    model, index, metadata = load_resources()

    # 生成查询向量
    query_vec = model.encode(
        [query],
        normalize_embeddings=True,
    ).astype(np.float32)

    # FAISS 检索
    search_k = min(top_k * 3, index.ntotal)  # 多搜一些用于去重
    scores, indices = index.search(query_vec, search_k)

    results = []
    seen_ids = set()

    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:
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
            "text": meta["text"][:100] + ("..." if len(meta["text"]) > 100 else ""),
            "source_url": meta["source_url"],
            "score": round(float(score), 4),
        })

        if len(results) >= top_k:
            break

    return results


# ===========================================================
#  测试函数
# ===========================================================
def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"    PASS  {label}")
    else:
        FAIL += 1
        print(f"    FAIL  {label}  — {detail}")


def run_test_case(case: dict) -> dict:
    """执行单个测试用例并返回结果"""
    print(f"\n  [{case['id']}] {case['description']}")
    print(f"    查询: \"{case['query']}\"")

    results = search(case["query"], top_k=5)
    print(f"    返回: {len(results)} 条结果")

    case_result = {
        "case_id": case["id"],
        "query": case["query"],
        "description": case["description"],
        "results_count": len(results),
        "results": results,
        "checks": {},
    }

    # 检查1: 返回结果 > 0
    has_results = len(results) > 0
    check("返回结果 > 0", has_results)
    case_result["checks"]["has_results"] = has_results

    if not results:
        return case_result

    # 检查2: 产品类别过滤 (如果期望)
    exp_cat = case.get("expected_product_category")
    if exp_cat:
        cats_in_results = {r["product_category"] for r in results}
        cat_match = exp_cat in cats_in_results
        check(f"产品类别包含 {exp_cat}", cat_match, f"实际: {cats_in_results}")
        case_result["checks"]["product_category_match"] = cat_match

    # 检查3: 关键词匹配
    exp_kw = case.get("expected_keywords", [])
    if exp_kw:
        all_text = " ".join(r["text"] for r in results)
        kw_hits = [kw for kw in exp_kw if kw in all_text]
        kw_ok = len(kw_hits) == len(exp_kw)
        check(f"关键词全命中 {exp_kw}", kw_ok, f"命中: {kw_hits}, 缺失: {set(exp_kw) - set(kw_hits)}")
        case_result["checks"]["keyword_match"] = kw_ok
        case_result["checks"]["keyword_hits"] = kw_hits

    # 检查4: 字段完整性
    required = ["chunk_id", "product_id", "product_name", "product_category",
                 "chunk_type", "text", "source_url", "score"]
    missing = [f for f in required if f not in results[0]]
    field_ok = len(missing) == 0
    check("结果字段完整", field_ok, f"缺少: {missing}")
    case_result["checks"]["field_completeness"] = field_ok

    # 打印结果摘要
    for r in results[:3]:
        print(f"      [{r['score']:.4f}] {r['product_id']} {r['chunk_type']} — {r['text'][:60]}...")

    return case_result


# ===========================================================
#  主流程
# ===========================================================
def main():
    global PASS, FAIL
    PASS = 0
    FAIL = 0
    start_time = time.time()

    print("=" * 60)
    print("  P2-7: 穿戴设备 FAISS 知识库 — 检索验证")
    print("=" * 60)

    # 检查索引文件
    print(f"\n[检查] FAISS 索引: {INDEX_PATH}")
    if not INDEX_PATH.exists():
        print("[ERROR] 索引文件不存在，请先运行 build_index.py")
        sys.exit(1)
    print(f"  [OK] 索引文件存在")

    print(f"\n[检查] Metadata: {METADATA_PATH}")
    if not METADATA_PATH.exists():
        print("[ERROR] metadata 文件不存在")
        sys.exit(1)
    print(f"  [OK] metadata 文件存在")

    # 加载资源
    print(f"\n[加载] Embedding 模型 + FAISS 索引 + metadata...")
    load_resources()
    print(f"  [OK] 索引规模: {_index.ntotal} 个向量, {_index.d} 维")
    print(f"  [OK] metadata: {len(_metadata)} 条")

    # 向量-元数据一致性校验
    idx_match = _index.ntotal == len(_metadata)
    print(f"\n[校验] FAISS 索引与 metadata 数量一致: {idx_match}")
    if not idx_match:
        print("  [FAIL] 数量不一致，请重建索引")
        sys.exit(1)

    # 执行 6 组测试
    print(f"\n{'=' * 60}")
    print("  执行 6 组标准检索测试")
    print(f"{'=' * 60}")

    all_results = []
    for case in TEST_CASES:
        result = run_test_case(case)
        all_results.append(result)

    # 汇总
    total = PASS + FAIL
    print(f"\n{'=' * 60}")
    print(f"  测试汇总")
    print(f"{'=' * 60}")
    print(f"  通过: {PASS}/{total}")
    print(f"  失败: {FAIL}/{total}")
    all_pass = FAIL == 0
    print(f"  结果: {'全部通过' if all_pass else f'{FAIL} 项未通过'}")

    # 生成报告
    report = {
        "test_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "index_info": {
            "vector_count": _index.ntotal,
            "dimension": _index.d,
            "metadata_count": len(_metadata),
        },
        "summary": {
            "total_checks": total,
            "passed": PASS,
            "failed": FAIL,
            "all_passed": all_pass,
        },
        "test_cases": all_results,
        "elapsed_seconds": round(time.time() - start_time, 1),
    }

    FAISS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  报告已保存: {REPORT_PATH}")

    print(f"\n{'=' * 60}")
    print(f"  耗时: {report['elapsed_seconds']:.1f} 秒")
    print(f"{'=' * 60}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
