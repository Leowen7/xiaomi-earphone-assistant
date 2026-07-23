#!/usr/bin/env python3
"""
P2-14基础问答Word文档 → RAG文本块

输入:
data/wearables/manuals/raw/P2-14_Wearable_FAQ_Compatible.docx

输出:
data/wearables/processed/chunks/wearable_manualfaq_chunks.jsonl
"""

import json
import re
import sys
from pathlib import Path

try:
    import docx
except ImportError:
    print("[ERROR] 缺少 python-docx 库，请执行: pip install python-docx")
    sys.exit(1)

# ---------- 仓库路径配置 ----------
REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    REPO_ROOT
    / "data"
    / "wearables"
    / "manuals"
    / "raw"
    / "P2-14_Wearable_FAQ_Compatible.docx"
)

OUTPUT_DIR = (
    REPO_ROOT
    / "data"
    / "wearables"
    / "processed"
    / "chunks"
)

OUTPUT_FILE = OUTPUT_DIR / "wearable_manualfaq_chunks.jsonl"

# 产品 ID → 产品类别映射
PRODUCT_CATEGORY = {}
for i in range(1, 9):
    PRODUCT_CATEGORY[f"B{i:02d}"] = "smart_band"
    PRODUCT_CATEGORY[f"W{i:02d}"] = "smart_watch"


def extract_products_and_qas(paras):
    """
    从段落列表中解析出所有产品及其问答对。
    返回: {product_id: {
        "product_name": str,
        "product_category": str,
        "qas": [{
            "qa_id": str,
            "topic": str,
            "question": str,
            "answer": str,
            "source_url": str,
        }]
    }}
    """
    products = {}
    current_pid = None
    current_pname = None

    # 先找到所有产品标题段落
    product_headers = []
    for i, p in enumerate(paras):
        m = re.match(r'^\d+[.．]\s*([BW]\d{2})\s+(.+)', p)
        if m:
            product_headers.append((i, m.group(1), m.group(2).strip()))

    if not product_headers:
        print("[ERROR] 未找到任何产品标题，文档格式可能不兼容")
        sys.exit(1)

    print(f"  发现 {len(product_headers)} 个产品标题")

    # 遍历每个产品的段落区间
    for idx, (start_idx, pid, pname) in enumerate(product_headers):
        end_idx = product_headers[idx + 1][0] if idx + 1 < len(product_headers) else len(paras)
        product_paras = paras[start_idx:end_idx]

        category = PRODUCT_CATEGORY.get(pid)
        if not category:
            print(f"  [WARNING] 产品 {pid} 无法确定产品类别，跳过")
            continue

        # 在 product_paras 中找到所有 QA 标题
        qas = []
        qa_title_indices = []
        for j, p in enumerate(product_paras):
            if re.match(r'^[BW]\d{2}-\d\s', p):
                qa_title_indices.append(j)

        # 处理每个 QA
        for qa_idx, title_j in enumerate(qa_title_indices):
            qa_title = product_paras[title_j]

            # 提取 question 文本（去掉 "B01-1  " 前缀）
            question = re.sub(r'^[BW]\d{2}-\d\s+', '', qa_title).strip()

            # 元数据行: 标题 + 1
            if title_j + 1 >= len(product_paras):
                print(f"  [WARNING] {pid} QA#{qa_idx+1}: 缺少元数据行")
                continue
            meta_line = product_paras[title_j + 1]

            # 答案行: 标题 + 2
            if title_j + 2 >= len(product_paras):
                print(f"  [WARNING] {pid} QA#{qa_idx+1}: 缺少答案行")
                continue
            answer_line = product_paras[title_j + 2]

            # 来源行: 标题 + 3
            if title_j + 3 >= len(product_paras):
                print(f"  [WARNING] {pid} QA#{qa_idx+1}: 缺少来源行")
                continue
            source_line = product_paras[title_j + 3]

            # 解析元数据
            qa_id = ""
            topic = ""
            meta_match = re.search(r'QA ID[：:]\s*(\S+)', meta_line)
            if meta_match:
                qa_id = meta_match.group(1).strip()
            topic_match = re.search(r'主题[：:]\s*(\S+)', meta_line)
            if topic_match:
                topic = topic_match.group(1).strip()

            # 解析答案（去掉 "答案：" 前缀）
            answer = re.sub(r'^答案[：:]\s*', '', answer_line).strip()

            # 解析来源 URL
            source_url = ""
            url_match = re.search(r'(https?://\S+)', source_line)
            if url_match:
                source_url = url_match.group(1).strip().rstrip('。，,./')

            qas.append({
                "qa_id": qa_id,
                "topic": topic,
                "question": question,
                "answer": answer,
                "source_url": source_url,
            })

        products[pid] = {
            "product_name": pname,
            "product_category": category,
            "qas": qas,
        }

        print(f"  {pid} {pname}: {len(qas)} 条问答")

    return products


def validate_qas(products):
    """验证问答数据完整性"""
    errors = []
    warnings = []
    qa_ids = set()
    chunk_ids = set()

    for pid, pdata in products.items():
        if len(pdata["qas"]) != 6:
            errors.append(f"产品 {pid} 应有 6 条问答，实际 {len(pdata['qas'])} 条")

        for qa in pdata["qas"]:
            # QA ID 唯一性
            if qa["qa_id"] in qa_ids:
                errors.append(f"QA ID 重复: {qa['qa_id']}")
            qa_ids.add(qa["qa_id"])

            # chunk_id 唯一性（使用 qa_id 作为 chunk_id）
            cid = qa["qa_id"]
            if cid in chunk_ids:
                errors.append(f"chunk_id 重复: {cid}")
            chunk_ids.add(cid)

            # 必填字段非空
            if not qa["qa_id"]:
                errors.append(f"{pid}: QA ID 为空")
            if not qa["question"]:
                errors.append(f"{pid}: question 为空")
            if not qa["answer"]:
                errors.append(f"{pid}: answer 为空")
            if not qa["source_url"]:
                errors.append(f"{pid}: source_url 为空")

            # QA ID 格式校验
            expected_prefix = f"{pid}_QA_"
            if not qa["qa_id"].startswith(expected_prefix):
                errors.append(f"{pid}: QA ID '{qa['qa_id']}' 格式异常，期望以 '{expected_prefix}' 开头")

            # 来源 URL 与产品 ID 对应（抽查）
            if pid in ["B01", "W06"]:
                if not qa["source_url"]:
                    errors.append(f"{pid}: 来源 URL 为空")

    return errors, warnings


def build_chunks(products):
    """将解析结果转为文本块列表"""
    chunks = []
    for pid, pdata in sorted(products.items()):
        for qa in pdata["qas"]:
            # text 字段 = question + "\n" + answer（兼容 FAISS 检索）
            text = qa["question"] + "\n" + qa["answer"]

            chunk = {
                "product_id": pid,
                "product_name": pdata["product_name"],
                "product_category": pdata["product_category"],
                "chunk_id": qa["qa_id"],
                "chunk_type": "manual_faq",
                "qa_id": qa["qa_id"],
                "topic": qa["topic"],
                "question": qa["question"],
                "answer": qa["answer"],
                "text": text,
                "source_url": qa["source_url"],
                "data_status": "draft",
            }
            chunks.append(chunk)
    return chunks


def write_jsonl(chunks, path):
    """写入 JSONL 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def main():
    print("=" * 55)
    print("  P2-14 Word → FAQ 文本块转换")
    print("=" * 55)

    # 检查输入文件
    print(f"\n[1] 检查输入文件: {INPUT_FILE}")
    if not INPUT_FILE.exists():
        print(f"[ERROR] 输入文件不存在: {INPUT_FILE}")
        sys.exit(1)
    print(f"  文件存在")

    # 读取 Word 文档
    print(f"\n[2] 读取 Word 文档")
    try:
        doc = docx.Document(str(INPUT_FILE))
    except Exception as e:
        print(f"[ERROR] 读取 Word 文档失败: {e}")
        sys.exit(1)

    paras = [p.text.strip() for p in doc.paragraphs]
    print(f"  共 {len(paras)} 个段落")

    # 提取产品和问答
    print(f"\n[3] 提取产品和问答")
    products = extract_products_and_qas(paras)
    total_qas = sum(len(pd["qas"]) for pd in products.values())
    print(f"\n  合计: {len(products)} 款产品, {total_qas} 条问答")

    # 校验
    print(f"\n[4] 校验数据完整性")
    errors, warnings = validate_qas(products)
    if warnings:
        for w in warnings:
            print(f"  [WARNING] {w}")
    if errors:
        for e in errors:
            print(f"  [ERROR] {e}")
        print(f"\n[FAIL] 校验未通过，{len(errors)} 个错误")
        sys.exit(1)
    print(f"  校验通过，0 错误")

    # 构建文本块
    print(f"\n[5] 构建文本块")
    chunks = build_chunks(products)
    print(f"  生成 {len(chunks)} 个文本块")

    # 写入输出
    print(f"\n[6] 写入输出: {OUTPUT_FILE}")
    write_jsonl(chunks, OUTPUT_FILE)
    print(f"  文件大小: {OUTPUT_FILE.stat().st_size} 字节")

    # 输出统计
    from collections import Counter
    type_counter = Counter(c["chunk_type"] for c in chunks)
    print(f"\n{'='*55}")
    print(f"  转换完成!")
    print(f"  产品数: {len(products)}")
    print(f"  问答总数: {len(chunks)}")
    print(f"  chunk_type 分布: {dict(type_counter)}")
    print(f"  输出文件: {OUTPUT_FILE}")
    print(f"{'='*55}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
