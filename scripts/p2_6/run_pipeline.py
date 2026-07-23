#!/usr/bin/env python3
"""
P2-6 全流程运行脚本

依次执行:
  1. json_to_chunks.py     — 从 all_wearables.jsonl 生成 144 条参数文本块
  2. word_faq_to_chunks.py — 从 P2-14.docx 生成 96 条 FAQ 文本块
  3. 合并两个 JSONL        — 生成 ~240 条全量文本块
  4. 全面校验               — 字段完整性、ID 唯一性、产品覆盖
  5. 更新 data_status      — draft → approved
  6. 生成校验报告和运行日志

使用方式（在仓库根目录执行）:
    python scripts/p2_6/run_pipeline.py

输入文件不存在或校验失败时返回非 0 退出状态。
"""

import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

# ---------- 仓库路径配置 ----------
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent

OUTPUT_DIR = (
    REPO_ROOT
    / "data"
    / "wearables"
    / "processed"
    / "chunks"
)

REPORTS_DIR = REPO_ROOT / "docs" / "p2_6"

PARAM_CHUNKS_FILE = OUTPUT_DIR / "wearable_parameter_chunks.jsonl"
FAQ_CHUNKS_FILE = OUTPUT_DIR / "wearable_manualfaq_chunks.jsonl"
ALL_CHUNKS_FILE = OUTPUT_DIR / "wearable_all_chunks.jsonl"

VALIDATION_REPORT = REPORTS_DIR / "validation_report.md"
RUN_LOG = REPORTS_DIR / "run_log.txt"

# 预期的产品和问答数量
EXPECTED_PARAM_CHUNKS = 144  # 16 款 × 9 主题
EXPECTED_FAQ_CHUNKS = 96     # 16 款 × 6 问答
EXPECTED_TOTAL = EXPECTED_PARAM_CHUNKS + EXPECTED_FAQ_CHUNKS

# 产品 ID 列表
PRODUCT_IDS = [f"B{i:02d}" for i in range(1, 9)] + [f"W{i:02d}" for i in range(1, 9)]


# ===========================================================
#  日志
# ===========================================================
class Logger:
    def __init__(self, log_path):
        self.log_path = log_path
        self.lines = []
        self.start_time = time.time()

    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {msg}"
        print(line)
        self.lines.append(line)

    def save(self):
        elapsed = time.time() - self.start_time
        self.lines.append(f"\n--- 总耗时: {elapsed:.1f} 秒 ---")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines) + "\n")


# ===========================================================
#  JSONL 读写
# ===========================================================
def read_jsonl(path):
    chunks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def write_jsonl(chunks, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def run_script(script_name, logger):
    """运行子脚本并检查退出状态"""
    script_path = SCRIPTS_DIR / script_name
    logger.log(f"  执行: {script_path}")
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
text=True,
cwd=REPO_ROOT,
    )
    # 输出子脚本的 stdout
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            logger.log(f"    {line.strip()}")
    if result.stderr.strip():
        for line in result.stderr.strip().split("\n"):
            logger.log(f"    [STDERR] {line.strip()}")
    if result.returncode != 0:
        logger.log(f"  [FAIL] {script_name} 退出码 {result.returncode}")
        return False
    logger.log(f"  [OK] {script_name} 完成")
    return True


# ===========================================================
#  校验器
# ===========================================================
def validate_all(param_chunks, faq_chunks, logger):
    """综合校验所有文本块"""
    errors = []
    warnings = []

    # --- 基本数量校验 ---
    logger.log(f"\n  参数块: {len(param_chunks)} 条 (预期 {EXPECTED_PARAM_CHUNKS})")
    logger.log(f"  FAQ块:   {len(faq_chunks)} 条 (预期 {EXPECTED_FAQ_CHUNKS})")

    if len(param_chunks) != EXPECTED_PARAM_CHUNKS:
        errors.append(f"参数文本块数量异常: {len(param_chunks)} ≠ {EXPECTED_PARAM_CHUNKS}")
    if len(faq_chunks) != EXPECTED_FAQ_CHUNKS:
        errors.append(f"FAQ 文本块数量异常: {len(faq_chunks)} ≠ {EXPECTED_FAQ_CHUNKS}")

    all_chunks = param_chunks + faq_chunks
    logger.log(f"  合并后共计: {len(all_chunks)} 条 (预期 {EXPECTED_TOTAL})")

    if len(all_chunks) != EXPECTED_TOTAL:
        errors.append(f"合并后总数异常: {len(all_chunks)} ≠ {EXPECTED_TOTAL}")

    # --- 产品覆盖 ---
    covered_pids = set()
    for c in all_chunks:
        covered_pids.add(c.get("product_id", ""))
    missing_pids = set(PRODUCT_IDS) - covered_pids
    if missing_pids:
        errors.append(f"以下产品缺少文本块: {sorted(missing_pids)}")
    else:
        logger.log(f"  产品覆盖: {len(covered_pids)}/16 款")

    # --- 参数块产品 × 主题覆盖 ---
    param_type_count = Counter()
    for c in param_chunks:
        param_type_count[(c["product_id"], c["chunk_type"])] += 1
    for pid in PRODUCT_IDS:
        for ct in ["basic_info", "display", "battery", "positioning", "communication",
                     "health", "sports", "compatibility", "design"]:
            if param_type_count.get((pid, ct), 0) == 0:
                errors.append(f"参数块: 产品 {pid} 缺少主题 {ct}")
            elif param_type_count[(pid, ct)] > 1:
                errors.append(f"参数块: 产品 {pid} 主题 {ct} 有 {param_type_count[(pid, ct)]} 个块 (预期 1)")

    # --- FAQ 块产品覆盖（每款 6 条） ---
    faq_pid_count = Counter(c["product_id"] for c in faq_chunks)
    for pid in PRODUCT_IDS:
        cnt = faq_pid_count.get(pid, 0)
        if cnt == 0:
            errors.append(f"FAQ块: 产品 {pid} 缺失")
        elif cnt != 6:
            errors.append(f"FAQ块: 产品 {pid} 有 {cnt} 条问答 (预期 6)")

    # --- chunk_id 唯一性 ---
    chunk_ids = [c["chunk_id"] for c in all_chunks]
    dup_chunk_ids = [cid for cid, cnt in Counter(chunk_ids).items() if cnt > 1]
    if dup_chunk_ids:
        errors.append(f"chunk_id 重复: {dup_chunk_ids}")

    # --- qa_id 唯一性（仅 FAQ） ---
    qa_ids = [c.get("qa_id", "") for c in faq_chunks if c.get("qa_id")]
    dup_qa_ids = [qid for qid, cnt in Counter(qa_ids).items() if cnt > 1]
    if dup_qa_ids:
        errors.append(f"qa_id 重复: {dup_qa_ids}")

    # --- 必填字段非空 ---
    for c in all_chunks:
        for field in ["product_id", "product_name", "chunk_id", "text", "source_url"]:
            if not c.get(field):
                errors.append(f"块 {c.get('chunk_id', '?')} 缺少字段: {field}")

    # --- FAQ 块特殊校验 ---
    for c in faq_chunks:
        if not c.get("qa_id"):
            errors.append(f"FAQ块 {c.get('chunk_id', '?')} 缺少 qa_id")
        if not c.get("topic"):
            errors.append(f"FAQ块 {c.get('chunk_id', '?')} 缺少 topic")
        if not c.get("question"):
            errors.append(f"FAQ块 {c.get('chunk_id', '?')} 缺少 question")
        if not c.get("answer"):
            errors.append(f"FAQ块 {c.get('chunk_id', '?')} 缺少 answer")
        if c.get("chunk_type") != "manual_faq":
            errors.append(f"FAQ块 {c.get('chunk_id', '?')} chunk_type 不为 manual_faq")

        # QA ID 格式校验
        expected_qa_prefix = c["product_id"] + "_QA_"
        if not c["qa_id"].startswith(expected_qa_prefix):
            errors.append(f"产品 {c['product_id']}: QA ID '{c['qa_id']}' 不以 '{expected_qa_prefix}' 开头")

    # --- 来源 URL 空值检查 ---
    empty_urls = [c["chunk_id"] for c in all_chunks if not c.get("source_url")]
    if empty_urls:
        errors.append(f"以下文本块 source_url 为空: {empty_urls[:10]}")

    # --- 来源 URL 域名白名单校验 ---
    # ---- 来源 URL 域名白名单校验 ----
    ALLOWED_DOMAINS = {"mi.com", "xiaomi.com"}

    for c in all_chunks:
        url = c.get("source_url", "")

        if url:
            from urllib.parse import urlparse

            try:
                domain = urlparse(url).netloc.lower()

                is_official_domain = any(
                    domain == allowed
                    or domain.endswith("." + allowed)
                    for allowed in ALLOWED_DOMAINS
                )

                if not is_official_domain:
                    warnings.append(
                        f"{c.get('chunk_id', '?')}: "
                        f"来源 URL 域名 {domain} 不属于小米官方域名"
                    )

            except Exception:
                warnings.append(
                    f"{c.get('chunk_id', '?')}: "
                    f"来源 URL 解析失败: {url}"
                )



        return errors, warnings


# ===========================================================
#  主流程
# ===========================================================
def main():
    # 初始化日志
    logger = Logger(RUN_LOG)
    logger.log("=" * 55)
    logger.log("  P2-6 全流程运行")
    logger.log(f"  开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.log("=" * 55)

    # === 步骤 1: 生成参数文本块 ===
    logger.log("\n[STEP 1/5] 生成参数文本块 (144 条)")
    if not run_script("json_to_chunks.py", logger):
        logger.log("[FAIL] 参数文本块生成失败")
        logger.save()
        sys.exit(1)

    # === 步骤 2: 生成 FAQ 文本块 ===
    logger.log("\n[STEP 2/5] 生成 FAQ 文本块 (96 条)")
    if not run_script("word_faq_to_chunks.py", logger):
        logger.log("[FAIL] FAQ 文本块生成失败")
        logger.save()
        sys.exit(1)

    # === 步骤 3: 读取并合并 ===
    logger.log("\n[STEP 3/5] 读取并合并文本块")
    param_chunks = read_jsonl(PARAM_CHUNKS_FILE)
    faq_chunks = read_jsonl(FAQ_CHUNKS_FILE)
    logger.log(f"  参数块: {len(param_chunks)} 条")
    logger.log(f"  FAQ块:   {len(faq_chunks)} 条")

    all_chunks = param_chunks + faq_chunks
    write_jsonl(all_chunks, ALL_CHUNKS_FILE)
    logger.log(f"  合并写入: {ALL_CHUNKS_FILE} ({len(all_chunks)} 条)")

    # === 步骤 4: 全面校验 ===
    logger.log("\n[STEP 4/5] 全面校验")
    errors, warnings = validate_all(param_chunks, faq_chunks, logger)

    if warnings:
        logger.log(f"\n  [WARNINGS] {len(warnings)} 条:")
        for w in warnings:
            logger.log(f"    [WARN] {w}")

    if errors:
        logger.log(f"\n  [ERRORS] {len(errors)} 条:")
        for e in errors:
            logger.log(f"    ✗ {e}")
        logger.log("\n[FAIL] 校验未通过，终止流程")
        logger.save()
        sys.exit(1)

    logger.log("  [OK] 校验通过，0 错误")

    # === 步骤 5: 更新 data_status ===
    # 仅当 0 错误且 0 警告时自动标记为 approved，否则需人工干预
    can_auto_approve = len(errors) == 0 and len(warnings) == 0
    if can_auto_approve:
        logger.log("\n[STEP 5/5] 自动批准: 0 错误 + 0 警告，更新 FAQ 文本块 data_status (draft \u2192 approved)")
        updated_count = 0
        for c in all_chunks:
            if c.get("chunk_type") == "manual_faq" and c.get("data_status") == "draft":
                c["data_status"] = "approved"

                # 仅表示链接属于小米官方域名，
                # 不表示网页内容已经逐条人工核验
                c.pop("source_verified", None)
                c["source_domain_verified"] = True
                c["source_content_verified"] = False

                updated_count += 1
        logger.log(f"  更新了 {updated_count} 条 FAQ 文本块的 data_status")
    else:
        logger.log("\n[STEP 5/5] 存在未解决警告，跳过自动批准，data_status 保持 draft")
        logger.log(f"  原因: {len(errors)} 错误 + {len(warnings)} 警告未解决")
        # 仍将参数块的 data_status 置为 approved（参数块来自已审核源数据）
        for c in all_chunks:
            if c.get("chunk_type") != "manual_faq" and c.get("data_status") is None:
                c["data_status"] = c.get("data_status", "approved")
    
    # 重新写入合并文件
    write_jsonl(all_chunks, ALL_CHUNKS_FILE)
    
    # 单独写入 FAQ 文件
    faq_chunks_updated = [c for c in all_chunks if c.get("chunk_type") == "manual_faq"]
    write_jsonl(faq_chunks_updated, FAQ_CHUNKS_FILE)
    logger.log(f"  已更新: {FAQ_CHUNKS_FILE}")

    # ===========================================================
    #  生成校验报告
    # ===========================================================
    logger.log("\n  生成校验报告...")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # 统计
    param_by_pid = Counter(c["product_id"] for c in param_chunks)
    faq_by_pid = Counter(c["product_id"] for c in all_chunks if c.get("chunk_type") == "manual_faq")
    chunk_types = Counter(c["chunk_type"] for c in all_chunks)
    topics = Counter(c.get("topic", "") for c in all_chunks if c.get("topic"))
    # 按产品统计 FAQ topic 分布
    faq_topics_by_product = {}
    for c in all_chunks:
        if c.get("chunk_type") == "manual_faq":
            pid = c["product_id"]
            if pid not in faq_topics_by_product:
                faq_topics_by_product[pid] = []
            faq_topics_by_product[pid].append(c.get("topic", ""))
    # 统计产品覆盖
    covered_pids = set(c["product_id"] for c in all_chunks)
    missing_pids = set(PRODUCT_IDS) - covered_pids

    report_lines = [
        "# P2-6 穿戴设备 RAG 文本块 — 校验报告",
        "",
        f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
        "## 1. 数据概览",
        "",
        f"| 指标 | 值 |",
        "|------|-----|",
        f"| 参数文本块 | {len(param_chunks)} 条 (预期 {EXPECTED_PARAM_CHUNKS}) |",
        f"| FAQ 文本块 | {len(faq_chunks_updated)} 条 (预期 {EXPECTED_FAQ_CHUNKS}) |",
        f"| 合并后总计 | {len(all_chunks)} 条 (预期 {EXPECTED_TOTAL}) |",
        f"| 产品覆盖 | {len(covered_pids)} / 16 款 |",
        f"| 校验结果 | {'**通过** ✅' if not errors else '**失败** ❌'} |",
        "",
        "## 2. chunk_type 分布",
        "",
        "| chunk_type | 数量 |",
        "|------------|------|",
    ]
    for ct, cnt in sorted(chunk_types.items()):
        report_lines.append(f"| {ct} | {cnt} |")

    report_lines += [
        "",
        "## 3. 产品分布",
        "",
        "| 产品 ID | 参数块数 | FAQ 块数 | FAQ 主题 |",
        "|---------|---------|---------|---------|",
    ]
    for pid in PRODUCT_IDS:
        p = param_by_pid.get(pid, 0)
        f = faq_by_pid.get(pid, 0)
        ft = ", ".join(faq_topics_by_product.get(pid, []))
        report_lines.append(f"| {pid} | {p} | {f} | {ft} |")

    report_lines += [
        "",
        "## 4. 数据状态",
        "",
        f"- **参数文本块**: 所有 {len(param_chunks)} 条 data_status = {param_chunks[0].get('data_status', 'approved') if param_chunks else 'N/A'}",
        f"- **FAQ 文本块**: 所有 {len(faq_chunks_updated)} 条 data_status = {'`approved`' if can_auto_approve else '`draft` (需人工审核)'}",
        f"- **结构校验状态**: "
f"{'已通过并更新数据状态' if can_auto_approve else '因警告未通过，需人工干预'}",

"- **来源核验说明**: "
"`source_domain_verified=true`仅表示链接属于小米官方域名；"
"`source_content_verified=false`表示网页内容未由程序逐条人工核验。",
        "",
        "## 5. 校验明细",
        "",
        f"- chunk_id 唯一性: **{'通过' if not any('chunk_id 重复' in e for e in errors) else '失败'}**",
        f"- qa_id 唯一性: **{'通过' if not any('qa_id 重复' in e for e in errors) else '失败'}**",
        f"- 来源 URL 非空: **{'通过' if not any('source_url 为空' in e for e in errors) else '失败'}**",
        f"- 产品全覆盖: **{'通过' if not missing_pids else '失败'}**",
        f"- 参数块 9 主题完整: **通过**",
        f"- FAQ 块每款 6 条: **通过**",
    ]
    if warnings:
        report_lines += [
            "",
            "## 6. 警告",
            "",
        ]
        for w in warnings:
            report_lines.append(f"- ⚠ {w}")

    if errors:
        report_lines += [
            "",
            "## 7. 错误",
            "",
        ]
        for e in errors:
            report_lines.append(f"- ❌ {e}")

    with open(VALIDATION_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines) + "\n")

    logger.log(f"  校验报告: {VALIDATION_REPORT}")

    # ===========================================================
    #  完成
    # ===========================================================
    logger.log(f"\n{'='*55}")
    if errors:
        logger.log("  流程完成: FAIL (存在错误)")
    else:
        logger.log("  流程完成: SUCCESS")
        logger.log(f"  输出文件:")
        logger.log(f"    - {PARAM_CHUNKS_FILE} ({len(param_chunks)} 条)")
        logger.log(f"    - {FAQ_CHUNKS_FILE} ({len(faq_chunks_updated)} 条)")
        logger.log(f"    - {ALL_CHUNKS_FILE} ({len(all_chunks)} 条)")
        logger.log(f"    - {VALIDATION_REPORT}")
        logger.log(f"    - {RUN_LOG}")
    logger.log(f"{'='*55}")

    logger.save()
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
