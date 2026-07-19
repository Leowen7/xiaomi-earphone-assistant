"""
parse_manuals.py — PDF 说明书解析与结构化脚本
================================================
将 raw/manuals/ 下的 8 份 PDF 说明书解析为结构化 JSONL 文本块。

用法:
    python backend/scripts/parse_manuals.py

输入:
    data/raw/manuals/          — PDF 说明书目录
    data/raw/manuals_manifest.xlsx — 说明书清单

输出:
    data/processed/manual_chunks.jsonl       — 结构化文本块 (JSONL)
    data/processed/manual_parsing_report.md  — 解析报告 (Markdown)

技术栈: PyMuPDF, pandas, openpyxl
"""

import fitz  # PyMuPDF
import os
import re
import json
import sys
import hashlib
from pathlib import Path
from datetime import datetime

import pandas as pd

# ──────────────────────────────────────────────
# 0. 路径配置（使用相对路径，避免绝对路径硬编码）
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[2]  # f:\data
RAW_DIR = BASE_DIR / "raw"
MANUALS_DIR = RAW_DIR / "manuals"
MANIFEST_PATH = RAW_DIR / "manuals_manifest.xlsx"
OUTPUT_DIR = BASE_DIR / "processed"
OUTPUT_JSONL = OUTPUT_DIR / "chunks.jsonl"
OUTPUT_REPORT = OUTPUT_DIR / "manual_parsing_report.md"

# ──────────────────────────────────────────────
# 1. 文本清洗规则
# ──────────────────────────────────────────────

# 不可删除的关键词（确保有用的操作说明不丢失）
PROTECTED_KEYWORDS = [
    "配对", "连接", "充电", "重置", "通话操作",
    "低延迟", "指示灯", "故障处理", "降噪",
    "触控", "唤醒", "恢复出厂", "佩戴检测",
]

# 固定参数字段列表：在基本参数文本中，每个字段前插入换行
PARAMETER_LABELS = [
    "产品名称", "产品型号", "耳机输入", "充电盒输入", "充电盒输出",
    "额定输入", "额定输出", "电池容量", "充电时间", "无线连接",
    "蓝牙工作频率", "执行标准", "CMIIT ID", "喇叭阻抗", "充电接口",
    "通讯距离", "蓝牙版本",
]

# 已知跨页数字污染修复：精准替换已知的模型号碎片污染，不误伤合法数字
# PDF解析中模型号（如 M2110E1）的 '2110' 片段可能出现在正文中
KNOWN_DIGIT_POLLUTION = [
    "切2110换",  # EAR004: "切" + 模型号碎片2110 + "换"
    "切2110\n换",
    "切2110\n\n换",
]
# PDF 跨页断行：中文字符 + 一个或多个换行 + 中文字符 → 删除中间换行
# 如"通透\n模式"→"通透模式"、"机\n\n电"→"机电"
CROSS_PAGE_NEWLINE_RE = re.compile(r"([\u4e00-\u9fff])\n+([\u4e00-\u9fff])")

# 一级章节标记: （数字）标题名 — 必须是行首，标题名不超过15字
SECTION_HEADER_RE = re.compile(
    r"^[（(]\s*(\d+)\s*[）)]\s*(.{1,20}?)$"
)
# 二级标记: 操作说明 / 功能介绍 / 基本参数 等大标题（行首精确匹配）
MAJOR_HEADER_RE = re.compile(
    r"^(操作说明|功能介绍|基本参数|产品参数|规格参数)$"
)
# 参数子标题
PARAM_SUB_RE = re.compile(r"^(耳机参数|充电盒参数|耳塞参数)$")

# 已知的关键章节名 → 标准化名称（按优先级排序：更具体的在前）
SECTION_NAME_MAP = [
    (re.compile(r"配对|连接"), "配对与连接"),
    (re.compile(r"充电"), "充电"),
    # 功能相关模式优先于故障处理（避免"其他常用操作（含故障处理）"被误判）
    (re.compile(r"功能介绍|其他常用操作|操作说明|开关机|通话|音乐|降噪|触控|佩戴|唤醒"), "功能与操作"),
    (re.compile(r"重置|恢复出厂|故障处理"), "重置与故障处理"),
    (re.compile(r"基本参数|产品参数|规格参数|耳机参数|充电盒参数"), "基本参数"),
    (re.compile(r"充电与续航"), "充电"),
]

def _normalize_section_name(raw: str) -> str:
    """将原始章节名标准化。"""
    raw = raw.strip()
    # 移除尾部的 （ 或 ( 残留
    raw = re.sub(r"[（(]\s*$", "", raw).strip()
    for pattern, name in SECTION_NAME_MAP:
        if pattern.search(raw):
            return name
    # 没匹配到的，返回清理后的原名
    if len(raw) > 20:
        raw = raw[:20]
    return raw if raw else "其他"


def clean_text(text: str) -> str:
    """清洗从 PDF 提取的原始文本。"""
    if not text or not text.strip():
        return ""

    # 1) 移除控制字符（保留常见空白符）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)

    # 2) 统一换行为 \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3) 把 PDF 造成的断行合并：行末是中文字符/逗号/顿号则与下行合并
    #    中文断行特征：上一行以汉字或中文标点结尾（非句号/问号/感叹号/冒号）
    lines = text.split("\n")
    merged = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            merged.append("")
            continue
        if merged and merged[-1]:
            prev = merged[-1]
            # 上一行结尾是中文字符、逗号、顿号、分号等未完结标点 → 合并
            if re.search(r"[\u4e00-\u9fff，、；：\)）\w\-]$", prev):
                merged[-1] = prev + stripped
                continue
            # 上一行以 '•' 结尾 → 下一行是续行
            if prev.rstrip().endswith("•"):
                merged[-1] = prev + stripped
                continue
            # 下一行以编号开头 (如 "3."、"3）"、"(3)") → 可能是同一节的续行
            if re.match(r"^[\d（(][\d一二三四五六七八九十]|^[•\-]", stripped):
                # 但如果上一行以句号结尾，则不合并
                if not re.search(r"[。！？]$", prev):
                    merged[-1] = prev + " " + stripped
                    continue
        merged.append(stripped)

    text = "\n".join(merged)

    # 4) 把连续多个空白行压缩为单个空白行
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 5) 压缩连续空格
    text = re.sub(r"[ \t]{2,}", " ", text)

    # 6) 移除完全空白的行首尾
    lines = text.split("\n")
    lines = [l.strip() for l in lines]
    text = "\n".join(lines)

    # 7) 把行内的多个换行变成段落分隔
    text = re.sub(r"\n{2,}", "\n\n", text)

    return text.strip()


def extract_metadata_from_text(text: str) -> dict:
    """从 PDF 首段文字中提取产品名称和型号。"""
    meta = {}
    m = re.search(r"产品名称[：:]\s*(.+)", text)
    if m:
        meta["name_in_pdf"] = m.group(1).strip()
    m = re.search(r"产品型号[：:]\s*(\S+)", text)
    if m:
        meta["model_in_pdf"] = m.group(1).strip()
    return meta


def identify_sections(text: str) -> list:
    """
    将清洗后的文本按语义章节拆分。
    只将 （数字）标题名 和 大标题（操作说明/功能介绍/基本参数）视为章节边界。
    编号子项（1. 2. 3.）不创建新章节。
    返回: [(section_name, content_text), ...]
    """
    lines = text.split("\n")

    # 找出所有章节边界行（只识别一级标题）
    section_boundaries = []  # (line_index, section_name)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # 匹配 （数字）标题名  — 一级章节
        m = SECTION_HEADER_RE.match(stripped)
        if m:
            raw_name = m.group(2).strip()
            sec_name = _normalize_section_name(raw_name)
            section_boundaries.append((i, sec_name))
            continue

        # 匹配大标题（操作说明 / 功能介绍 / 基本参数）
        m = MAJOR_HEADER_RE.match(stripped)
        if m:
            sec_name = _normalize_section_name(m.group(1))
            section_boundaries.append((i, sec_name))
            continue

        # 匹配子参数标题
        m = PARAM_SUB_RE.match(stripped)
        if m:
            section_boundaries.append((i, "基本参数"))
            continue

    # 按章节边界切分
    sections = []
    if not section_boundaries:
        sections.append(("产品概述", text))
        return sections

    # 第一个章节之前的内容 → "产品概述"
    first_boundary = section_boundaries[0][0]
    header_lines = lines[:first_boundary]
    header_text = "\n".join(header_lines).strip()
    if header_text:
        sections.append(("产品概述", header_text))

    # 中间章节
    for idx, (line_idx, sec_name) in enumerate(section_boundaries):
        start = line_idx + 1  # 跳过标题行本身
        if idx + 1 < len(section_boundaries):
            end = section_boundaries[idx + 1][0]
        else:
            end = len(lines)
        content_lines = lines[start:end]
        content = "\n".join(content_lines).strip()
        if content:
            # 检查是否包含嵌入的子章节（如 "清除连接记录（重置）"）
            sub_sections = _split_embedded_subsections(content, sec_name)
            sections.extend(sub_sections)

    return sections


# 内嵌子章节标记模式（行首出现的关键词 + 冒号）
EMBEDDED_SUB_RE = re.compile(
    r"^(清除连接记录|恢复出厂设置|耳机重置|重置操作|复位操作|重置／复位)"
    r"[（(]?(重置|复位|恢复)?[）)]?[：:]"
)


def _split_embedded_subsections(content: str, parent_section: str) -> list:
    """
    检测章节内容中的内嵌子标题（如配对章节中的"清除连接记录（重置）："），
    并将其拆分为独立子章节（归属到对应语义类别）。
    """
    lines = content.split("\n")
    
    # 找出内嵌子标题的位置
    boundaries = []  # (line_index, target_section)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if EMBEDDED_SUB_RE.match(stripped):
            # 包含重置/复位关键词 → 归属到重置与故障处理
            boundaries.append((i, "重置与故障处理"))
    
    if not boundaries:
        return [(parent_section, content)]
    
    # 按边界切分
    result = []
    # 第一个边界之前的内容归属原章节
    first_idx = boundaries[0][0]
    pre_content = "\n".join(lines[:first_idx]).strip()
    if pre_content:
        result.append((parent_section, pre_content))
    
    for j, (line_idx, target_sec) in enumerate(boundaries):
        start = line_idx  # 包含标题行本身
        if j + 1 < len(boundaries):
            end = boundaries[j + 1][0]
        else:
            end = len(lines)
        sub_content = "\n".join(lines[start:end]).strip()
        if sub_content:
            result.append((target_sec, sub_content))
    
    return result


def smart_chunk(
    content: str,
    section_name: str,
    target_min: int = 300,
    target_max: int = 500,
    overlap: int = 80,
) -> list:
    """
    将章节内容按语义切分为文本块。
    - 优先按自然段落切分
    - 每块目标 300-500 中文字符
    - 相邻块重叠 50-100 字符
    - 同一章节内尽量合并以达到合理长度
    - 不将不同语义主题强行合并
    """
    # 先按双换行分段
    raw_paras = re.split(r"\n\n+", content)
    raw_paras = [p.strip() for p in raw_paras if p.strip()]

    if not raw_paras:
        return []

    # 将过短的段落与相邻段落合并（贪心合并至接近 target_min）
    merged_paras = []
    buffer = ""
    for para in raw_paras:
        candidate = (buffer + "\n" + para).strip() if buffer else para
        if len(candidate) <= target_max:
            # 还能继续装 → 合并
            buffer = candidate
        else:
            # 装不下了
            if buffer:
                merged_paras.append(buffer)
            buffer = para
    if buffer:
        # 最后一个 buffer 如果太短则合并到前一个块
        if merged_paras and len(buffer) < target_min:
            merged_paras[-1] = (merged_paras[-1] + "\n" + buffer).strip()
        else:
            merged_paras.append(buffer)

    # 最终切分：超长块按句子切分 + 重叠
    chunks = []
    for para in merged_paras:
        if len(para) <= target_max:
            chunks.append(para)
        else:
            # 按句子切分（以 。！？ 为界）
            sentences = re.split(r"(?<=[。！？])", para)
            sub_chunk = ""
            for sent in sentences:
                if len(sub_chunk) + len(sent) > target_max and sub_chunk:
                    chunks.append(sub_chunk.strip())
                    # 保留重叠：取上一块末尾若干字符
                    overlap_text = sub_chunk[-overlap:] if len(sub_chunk) > overlap else sub_chunk
                    sub_chunk = overlap_text + sent
                else:
                    sub_chunk += sent
            if sub_chunk.strip():
                chunks.append(sub_chunk.strip())

    return chunks


def generate_chunk_id(product_id: str, section: str, index: int) -> str:
    """生成唯一的 chunk_id。"""
    raw = f"{product_id}_{section}_{index}"
    hash_suffix = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"{product_id}_chunk_{index:04d}_{hash_suffix}"


def parse_single_pdf(
    pdf_path: Path,
    meta_row: pd.Series,
    chunk_index_start: int,
) -> tuple:
    """
    解析单个 PDF，返回 (chunks_list, stats_dict)。
    流程: 提取原始文本 → 轻清洗 → 识别章节 → 按章节深度清洗 → 切块
    """
    stats = {
        "file": pdf_path.name,
        "pages": 0,
        "raw_chars": 0,
        "cleaned_chars": 0,
        "chunks": 0,
        "sections_found": [],
        "errors": [],
    }
    chunks = []

    # ── 打开 PDF ──
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        stats["errors"].append(f"无法打开PDF: {e}")
        return chunks, stats

    stats["pages"] = doc.page_count

    # ── 逐页提取原始文字 ──
    raw_text_parts = []
    for page_num, page in enumerate(doc, start=1):
        page_text = page.get_text()
        raw_text_parts.append((page_num, page_text))
        stats["raw_chars"] += len(page_text)
    doc.close()

    # 合并全部原始文本
    full_raw = "\n".join(t for _, t in raw_text_parts)
    if not full_raw.strip():
        stats["errors"].append("PDF 无文本内容")
        return chunks, stats

    # ── 轻清洗：只做控制字符清理和断行合并 ──
    lightly_cleaned = _light_clean(full_raw)

    # ── 识别并切分章节 ──
    sections = identify_sections(lightly_cleaned)
    stats["sections_found"] = [s[0] for s in sections]

    # ── 获取产品元数据 ──
    product_id = str(meta_row.get("product_id", ""))
    product_name = str(meta_row.get("product_name", ""))
    model = str(meta_row.get("model", ""))
    source_url = str(meta_row.get("source_url", ""))

    # ── 按章节深度清洗 + 切块 ──
    chunk_idx = chunk_index_start
    for sec_name, sec_content in sections:
        # 在深度清洗前，先用轻清洗文本定位章节页码
        sec_page_start, sec_page_end = _locate_pages(sec_content, raw_text_parts)

        # 对每个章节内容进行深度清洗
        cleaned_content = _deep_clean(sec_content)
        if not cleaned_content.strip():
            continue

        # 后处理：针对特定产品/章节的精准修正
        cleaned_content = _post_process(
            cleaned_content, product_id, sec_name, pdf_path.name
        )
        if not cleaned_content.strip():
            continue

        stats["cleaned_chars"] += len(cleaned_content)

        # 按目标大小切块
        sub_chunks = smart_chunk(cleaned_content, sec_name)
        for sub in sub_chunks:
            chunk = {
                "chunk_id": generate_chunk_id(product_id, sec_name, chunk_idx),
                "product_id": product_id,
                "product_name": product_name,
                "model": model,
                "source_file": pdf_path.name,
                "source_url": source_url,
                "section": sec_name,
                "page": sec_page_start,          # 保持兼容：起始页
                "page_start": sec_page_start,    # 新增：起始页
                "page_end": sec_page_end,        # 新增：结束页
                "content": sub,
            }
            chunks.append(chunk)
            chunk_idx += 1
            stats["chunks"] += 1

    return chunks, stats


def _light_clean(text: str) -> str:
    """
    轻清洗：仅移除控制字符 + 合并 PDF 断行，保留章节标题的换行结构。
    在章节识别之前调用。
    """
    # 移除控制字符
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 在章节标题前插入空行，确保它们不会被合并
    # 匹配行首的 （数字）标题模式
    text = re.sub(r"\n([（(]\s*\d+\s*[）)][^\n]{1,30})\n", r"\n\n\1\n\n", text)
    # 匹配 "操作说明" "功能介绍" "基本参数" 等大标题
    text = re.sub(
        r"\n(操作说明|功能介绍|基本参数|产品参数|规格参数)\n",
        r"\n\n\1\n\n",
        text,
    )
    # 匹配 "耳机参数" "充电盒参数" 子标题
    text = re.sub(r"\n(耳机参数|充电盒参数|耳塞参数)\n", r"\n\n\1\n\n", text)

    # 合并 PDF 断行（行末是中文字符则合并）
    lines = text.split("\n")
    merged = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            merged.append("")
            continue
        # 章节标题行不合并
        if SECTION_HEADER_RE.match(stripped) or MAJOR_HEADER_RE.match(stripped) or PARAM_SUB_RE.match(stripped):
            merged.append(stripped)
            continue
        if merged and merged[-1]:
            prev = merged[-1]
            # 上一行是中文字符或未完结标点结尾 → 合并
            if re.search(r"[\u4e00-\u9fff，、；：\w\-]$", prev):
                merged[-1] = prev + stripped
                continue
        merged.append(stripped)

    return "\n".join(merged)


def _deep_clean(text: str) -> str:
    """
    深度清洗：对已识别的章节内容做精细清理。
    1) 精准替换已知的跨页数字污染（如"切2110换"→"切换"）
    2) 中文间跨页换行合并（如"通透\n模式"→"通透模式"）
    3) 项目符号 • 转为换行
    4) 在固定参数字段前插入换行
    5) 压缩空白和多余空格
    在章节切分之后调用。
    """
    if not text or not text.strip():
        return ""

    # 1) 精准替换已知的跨页数字污染（不误伤合法数字）
    for pattern in KNOWN_DIGIT_POLLUTION:
        if pattern in text:
            text = text.replace(pattern, "切换")
    # 2) 中文间跨页换行合并
    text = CROSS_PAGE_NEWLINE_RE.sub(r"\1\2", text)

    # 3) 项目符号 • 统一转为换行（避免•残留在正文中）
    text = re.sub(r"\s*•\s*", "\n", text)

    # 4) 在固定参数字段前插入换行（避免全部连写）
    for label in PARAMETER_LABELS:
        if label in text:
            text = text.replace(label, f"\n{label}")

    # 5) 压缩多余空白行
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 6) 压缩行内连续空格
    text = re.sub(r"[ \t]{2,}", " ", text)

    # 7) 行首尾去空格，移除纯空白行
    lines = [l.strip() for l in text.split("\n")]
    lines = [l for l in lines if l]

    return "\n".join(lines).strip()


def _post_process(text: str, product_id: str, section: str, source_file: str) -> str:
    """
    后处理：针对特定产品/章节的精准内容修正。
    在深度清洗之后、切块之前调用。
    """
    if not text.strip():
        return text

    # ── Fix1: EAR004 产品概述文件名修正 ──
    if product_id == "EAR004" and section == "产品概述":
        text = text.replace(
            "文件名：ME1_Redmi Buds 3 青春版.pdf",
            f"文件名：{source_file}"
        )

    # ── Fix2: EAR005 产品概述字段换行 ──
    if product_id == "EAR005" and section == "产品概述":
        # 产品型号 + 文件名 + 来源粘连在同一行，需要分离
        text = text.replace("文件名：", "\n文件名：")
        text = text.replace("来源：", "\n来源：")
        # 去掉多余的空白行
        text = re.sub(r"\n{3,}", "\n\n", text)

    # ── Fix3: EAR006 充电电池参数整理 ──
    if product_id == "EAR006" and section == "充电":
        # 当前: 电池参数：单耳机\n电池容量54mAh / 0.2Wh，充电盒\n电池容量590mAh / 2.28Wh。
        # 目标: 单耳机电池容量：54mAh / 0.2Wh\n充电盒电池容量：590mAh / 2.28Wh
        text = re.sub(
            r"电池参数：单耳机\n电池容量(\d+mAh)\s*/\s*([\d.]+Wh)，充电盒\n电池容量(\d+mAh)\s*/\s*([\d.]+Wh)。",
            r"单耳机电池容量：\1 / \2\n充电盒电池容量：\3 / \4",
            text
        )

    # ── Fix4: EAR007 参数顺序修正 ──
    if product_id == "EAR007" and section == "基本参数":
        # 当前: 无障碍空旷环境\n通讯距离：10 米\n...
        # 目标: 通讯距离：10米（无障碍空旷环境）\n...
        text = re.sub(
            r"无障碍空旷环境\n通讯距离：10 米",
            r"通讯距离：10米（无障碍空旷环境）",
            text
        )

    # ── Fix5: 所有产品概述的文件名对齐 source_file ──
    if section == "产品概述":
        # 找到正文中的"文件名：XXX"并替换为正确的 source_file
        # 只替换文件名行，保留其他内容不变
        text = re.sub(
            r"文件名：[^\n]*",
            f"文件名：{source_file}",
            text
        )

    return text


def _locate_pages(text: str, raw_text_parts: list) -> tuple:
    """
    根据文本内容推断起始页和结束页。
    使用短子串模糊匹配，容忍清洗带来的文本变化。
    返回: (page_start, page_end)
    """
    if not text.strip() or not raw_text_parts:
        return (1, 1)

    # 取文本首尾各取30字符作为搜索特征
    needle_start = text.strip()[:30]
    needle_end = text.strip()[-30:]

    page_start = 1
    page_end = 1

    # 首页：找匹配得分最高的页
    best_score = 0
    for page_num, page_text in raw_text_parts:
        score = _match_score(needle_start, page_text)
        if score > best_score:
            best_score = score
            page_start = page_num

    # 末页：同上
    best_score = 0
    for page_num, page_text in reversed(raw_text_parts):
        score = _match_score(needle_end, page_text)
        if score > best_score:
            best_score = score
            page_end = page_num

    # 兜底：如果末页 < 首页，取首页
    if page_end < page_start:
        page_end = page_start

    return (page_start, page_end)


def _match_score(needle: str, haystack: str) -> int:
    """计算 needle 在 haystack 中的最长连续匹配字符数。"""
    max_len = 0
    for i in range(len(needle)):
        for j in range(i + 1, len(needle) + 1):
            if needle[i:j] in haystack:
                if j - i > max_len:
                    max_len = j - i
            else:
                break
    return max_len


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  parse_manuals.py — PDF 说明书解析")
    print("=" * 60)

    # ── 读取元数据 ──
    print("\n[1/5] 读取元数据清单...")
    if not MANIFEST_PATH.exists():
        print(f"  ERROR: 找不到 {MANIFEST_PATH}")
        sys.exit(1)
    manifest = pd.read_excel(MANIFEST_PATH)
    # 修正可能的编码列名
    # 列顺序: 产品名称, product_id, 型号, 文件名, 来源, 数据采集日期
    expected_cols = ["product_name", "product_id", "model", "filename", "source_url"]
    if len(manifest.columns) >= 5:
        manifest.columns = expected_cols + list(manifest.columns[5:])
    print(f"  OK: 加载 {len(manifest)} 条产品记录")

    # ── 遍历 PDF ──
    print("\n[2/5] 解析 PDF 文件...")
    pdf_files = sorted(MANUALS_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"  ERROR: {MANUALS_DIR} 下无 PDF 文件")
        sys.exit(1)

    all_chunks = []
    report_lines = []
    total_success = 0
    total_fail = 0
    global_chunk_idx = 0

    for pdf_path in pdf_files:
        # 在 manifest 中查找对应行
        match = manifest[manifest["filename"] == pdf_path.name]
        if match.empty:
            print(f"  [SKIP] {pdf_path.name} — manifest 中无对应记录")
            total_fail += 1
            continue

        meta_row = match.iloc[0]
        pid = meta_row.get("product_id", "?")

        print(f"  [解析] {pid} ← {pdf_path.name} ...", end=" ")
        chunks, stats = parse_single_pdf(pdf_path, meta_row, global_chunk_idx)

        if stats["errors"]:
            print(f"WARN: {'; '.join(stats['errors'])}")
            total_fail += 1
        else:
            print(f"OK ({stats['pages']}页, {stats['chunks']}块, {len(stats['sections_found'])}章节)")
            total_success += 1

        all_chunks.extend(chunks)
        global_chunk_idx += len(chunks)

        # 记录到报告
        report_lines.append({
            "product_id": pid,
            "product_name": meta_row.get("product_name", ""),
            "file": stats["file"],
            "pages": stats["pages"],
            "raw_chars": stats["raw_chars"],
            "cleaned_chars": stats["cleaned_chars"],
            "chunks": stats["chunks"],
            "sections": ", ".join(stats["sections_found"]),
            "errors": "; ".join(stats["errors"]),
        })

    # ── 输出 JSONL ──
    print("\n[3/5] 写入 JSONL 文件...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    print(f"  OK: {OUTPUT_JSONL} ({len(all_chunks)} 行)")

    # ── 验证 JSONL 可读 ──
    print("\n[4/5] 验证 JSONL 可读性...")
    try:
        with open(OUTPUT_JSONL, "r", encoding="utf-8") as f:
            line_count = 0
            for line in f:
                json.loads(line)
                line_count += 1
        print(f"  OK: {line_count} 行全部可被 Python 解析")
    except Exception as e:
        print(f"  ERROR: JSONL 解析失败: {e}")

    # ── 生成 Markdown 报告 ──
    print("\n[5/5] 生成解析报告...")
    _write_report(report_lines, all_chunks, total_success, total_fail)
    print(f"  OK: {OUTPUT_REPORT}")

    # ── 汇总 ──
    print("\n" + "=" * 60)
    print(f"  解析完成!")
    print(f"  成功: {total_success} 份 PDF  |  失败: {total_fail} 份")
    print(f"  文本块总数: {len(all_chunks)}")
    print(f"  输出文件: {OUTPUT_JSONL}")
    print(f"  报告文件: {OUTPUT_REPORT}")
    print("=" * 60)


def _write_report(report_lines, all_chunks, total_success, total_fail):
    """生成 Markdown 格式的解析报告。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 统计各产品 chunk 数
    product_chunk_counts = {}
    for c in all_chunks:
        pid = c["product_id"]
        product_chunk_counts[pid] = product_chunk_counts.get(pid, 0) + 1

    # 检测空块和重复 chunk_id
    empty_chunks = [c for c in all_chunks if not c["content"].strip()]
    chunk_ids = [c["chunk_id"] for c in all_chunks]
    duplicate_ids = len(chunk_ids) - len(set(chunk_ids))

    lines = []
    lines.append(f"# PDF 说明书解析报告\n")
    lines.append(f"**生成时间**: {now}\n")
    lines.append(f"## 汇总\n")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 成功解析 PDF 数量 | {total_success} |")
    lines.append(f"| 失败数量 | {total_fail} |")
    lines.append(f"| 文本块总数 | {len(all_chunks)} |")
    lines.append(f"| 空文本块数量 | {len(empty_chunks)} |")
    lines.append(f"| 重复 chunk_id 数量 | {duplicate_ids} |")
    lines.append(f"| 覆盖产品 | {', '.join(sorted(product_chunk_counts.keys()))} |\n")

    lines.append(f"## 各产品详情\n")
    lines.append(f"| product_id | 产品名称 | 文件 | 页数 | 原始字符 | 清洗后 | 块数 | 章节 | 错误 |")
    lines.append(f"|------------|----------|------|------|----------|--------|------|------|------|")
    for r in report_lines:
        lines.append(
            f"| {r['product_id']} | {r['product_name']} | {r['file']} | "
            f"{r['pages']} | {r['raw_chars']} | {r['cleaned_chars']} | "
            f"{r['chunks']} | {r['sections']} | {r['errors'] or '无'} |"
        )

    lines.append(f"\n## 各产品块数分布\n")
    for pid in sorted(product_chunk_counts.keys()):
        lines.append(f"- **{pid}**: {product_chunk_counts[pid]} 块")

    if empty_chunks:
        lines.append(f"\n## ⚠ 空文本块\n")
        for c in empty_chunks:
            lines.append(f"- {c['chunk_id']} ({c['product_id']})")

    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
