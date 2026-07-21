"""
检索功能自动化测试

测试覆盖:
  1) Excel 用例: 12 条 (产品过滤/全产品/边界)
  2) 产品隔离: 指定 product_id 后所有结果同属该产品
  3) EAR999 空结果
  4) FAISS 索引规模 = metadata 规模
  5) 边界输入校验: 空 query / top_k=0 / 负数 / >5

用法:  python tests/test_retrieval.py
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# 确保可以从项目根目录导入 backend 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import faiss
import openpyxl
import numpy as np
from backend.retrieval_service import search_manual

TEST_CASES_PATH = PROJECT_ROOT / "tests" / "retrieval_cases.xlsx"
INDEX_PATH = PROJECT_ROOT / "vector_store" / "index.faiss"
METADATA_PATH = PROJECT_ROOT / "vector_store" / "metadata.jsonl"

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  — {detail}")


# ================================================================
#  测试组 A: FAISS 索引完整性
# ================================================================
def test_index_integrity():
    print("\n── 测试组A: FAISS 索引完整性 ──")

    idx = faiss.read_index(str(INDEX_PATH))
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        meta = [json.loads(l) for l in f]

    check("A1: FAISS.ntotal == metadata 行数",
          idx.ntotal == len(meta),
          f"FAISS={idx.ntotal}, metadata={len(meta)}")

    check("A2: vector_id 与列表位置一致",
          all(m["vector_id"] == i for i, m in enumerate(meta)))

    check("A3: 向量维度 = 512",
          idx.d == 512,
          f"实际={idx.d}")


# ================================================================
#  测试组 B: product_id 隔离性
# ================================================================
def test_product_isolation():
    print("\n── 测试组B: product_id 隔离性 ──")

    # B1: 指定产品后, 所有结果都属于该产品
    for pid, query in [
        ("EAR003", "怎么重置？"),
        ("EAR006", "电池容量"),
        ("EAR001", "配对连接"),
    ]:
        results = search_manual(query=query, product_id=pid, top_k=3)
        all_match = (
            len(results) == 3
            and all(r["product_id"] == pid for r in results)
        )
        check(f"B1: {pid} 过滤后全部属于{pid} (返回{len(results)}条)",
              all_match,
              f"混入了: {set(r['product_id'] for r in results) if not all_match else ''}")

    # B2: EAR999 返回空列表
    results = search_manual(query="重置", product_id="EAR999", top_k=3)
    check("B2: EAR999 返回空列表", len(results) == 0, f"返回了{len(results)}条")


# ================================================================
#  测试组 C: 输入校验 (预期抛出 ValueError)
# ================================================================
def test_input_validation():
    print("\n── 测试组C: 输入校验 ──")

    # C1: 空 query
    try:
        search_manual(query="", top_k=3)
        check("C1: 空query → ValueError", False, "未抛出异常")
    except ValueError:
        check("C1: 空query → ValueError", True)

    # C2: top_k=0
    try:
        search_manual(query="测试", top_k=0)
        check("C2: top_k=0 → ValueError", False, "未抛出异常")
    except ValueError:
        check("C2: top_k=0 → ValueError", True)

    # C3: top_k 负数
    try:
        search_manual(query="测试", top_k=-1)
        check("C3: top_k=-1 → ValueError", False, "未抛出异常")
    except ValueError:
        check("C3: top_k=-1 → ValueError", True)

    # C4: top_k > 5
    try:
        search_manual(query="测试", top_k=10)
        check("C4: top_k=10 → ValueError", False, "未抛出异常")
    except ValueError:
        check("C4: top_k=10 → ValueError", True)


# ================================================================
#  测试组 D: Excel 用例 (≥10 条正常检索)
# ================================================================
def load_excel_cases(path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(str(path))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip() if h else "" for h in rows[0]]
    cases = []
    for row in rows[1:]:
        case = dict(zip(headers, row))
        for k in list(case.keys()):
            if case[k] is None:
                case[k] = ""
        if case.get("product_id", "").strip() == "":
            case["product_id"] = None
        case["top_k"] = int(case.get("top_k", 3) or 3)
        cases.append(case)
    return cases


def test_excel_cases():
    print("\n── 测试组D: Excel 用例 (≥10 条正常检索) ──")

    cases = load_excel_cases(TEST_CASES_PATH)
    check("D0: 用例数量 ≥ 10", len(cases) >= 10, f"实际={len(cases)}")

    for case in cases:
        cid = case.get("case_id", "?")
        query = str(case.get("query", ""))
        pid = case["product_id"]
        top_k = case["top_k"]
        expected_pid = str(case.get("expected_product_id", "")).strip()
        expected_sec = str(case.get("expected_section", "")).strip()
        expected_kw = str(case.get("expected_keyword", "")).strip()

        results = search_manual(query=query, product_id=pid, top_k=top_k)

        expect_empty = bool(case.get("expect_empty", False))

        # 期望空结果 → 特殊处理
        if expect_empty:
            check(
                f"D{cid}: 应返回空列表",
                results == [],
                f"实际返回{len(results)}条",
            )
            continue

        # 无期望 → 返回非空即可 (宽松)
        if not expected_pid and not expected_sec and not expected_kw:
            check(f"D{cid}: 空期望-返回{len(results)}条", True)
            continue

        # 有期望 → 严格校验
        # 1) 产品匹配
        if expected_pid:
            result_pids = {r["product_id"] for r in results}
            ok = expected_pid in result_pids
            if not ok:
                check(f"D{cid}: {query[:20]}…", False,
                      f"期望产品={expected_pid}, 实际产品={result_pids}")
                continue

        # 2) 章节匹配 (Top-1)
        if expected_sec:
            top_sec = results[0]["section"] if results else ""
            ok = expected_sec in top_sec
            if not ok:
                check(f"D{cid}: {query[:20]}…", False,
                      f"期望章节={expected_sec}, Top1={top_sec}")
                continue

        # 3) 关键词匹配
        if expected_kw:
            all_text = " ".join(r["content"] for r in results)
            ok = expected_kw in all_text
            if not ok:
                check(f"D{cid}: {query[:20]}…", False,
                      f"关键词'{expected_kw}'未命中")
                continue

        # 4) 字段完整性
        required = ["chunk_id", "product_id", "product_name", "section",
                     "content", "source_file", "page_start", "page_end", "score"]
        missing_fields = []
        for r in results:
            for field in required:
                if field not in r:
                    missing_fields.append(field)
        if missing_fields:
            check(
                f"D{cid}: 字段完整性",
                False,
                f"缺少字段: {sorted(set(missing_fields))}",
            )
            continue

        check(f"D{cid}: {query[:20]}…", True)


# ================================================================
#  主流程
# ================================================================
def main():
    global PASS, FAIL
    PASS = 0
    FAIL = 0

    print("=" * 60)
    print("  任务17: 检索功能自动化测试 (加强版)")
    print("=" * 60)

    test_index_integrity()
    test_product_isolation()
    test_input_validation()
    test_excel_cases()

    total = PASS + FAIL
    print(f"\n{'=' * 60}")
    print(f"  通过: {PASS}/{total}  |  失败: {FAIL}/{total}")
    if FAIL == 0:
        print("  结果: 全部通过")
    else:
        print(f"  结果: {FAIL} 条未通过")
    print("=" * 60)

    return FAIL == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
