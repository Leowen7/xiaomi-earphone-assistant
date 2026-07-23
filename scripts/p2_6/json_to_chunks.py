#!/usr/bin/env python3
"""

P2-6: 穿戴设备 JSON → 参数文本块转换脚本

输入:
data/wearables/processed/all_wearables.jsonl

输出:
data/wearables/processed/chunks/wearable_parameter_chunks.jsonl
"""


import json
import sys
from pathlib import Path

# ---------- 仓库路径配置 ----------
REPO_ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    REPO_ROOT
    / "data"
    / "wearables"
    / "processed"
    / "all_wearables.jsonl"
)

OUTPUT_DIR = (
    REPO_ROOT
    / "data"
    / "wearables"
    / "processed"
    / "chunks"
)

OUTPUT_FILE = OUTPUT_DIR / "wearable_parameter_chunks.jsonl"

# 9 个主题定义
CHUNK_TYPES = [
    "basic_info", "display", "battery", "positioning", "communication",
    "health", "sports", "compatibility", "design",
]

# 产品类别中文映射
CATEGORY_MAP = {
    "smart_band": "智能手环",
    "smart_watch": "智能手表",
}

# 运动功能标签中文字典
FEATURE_LABELS = {
    "gnss_tracking": "GNSS运动轨迹记录",
    "swim_tracking": "游泳运动记录",
    "heart_rate_broadcast": "心率广播",
    "running_courses": "跑步课程",
    "pebble_mode": "豆形模式",
}

# 定位类型中文映射
POSITIONING_LABELS = {
    "built_in_gnss": "支持内置GNSS独立定位",
    "connected_phone": "不支持独立GNSS定位，运动轨迹需要使用手机定位",
    "none": "官方明确标注不支持定位功能",
}


def find_source_url(record, field_keywords):
    """根据字段关键词在 source_records 中找到最匹配的 source_url"""
    best_url = None
    best_score = 0
    for sr in record.get("source_records", []):
        scope = sr.get("field_scope", [])
        if not isinstance(scope, list):
            scope = []
        score = sum(1 for kw in field_keywords if any(kw in s for s in scope))
        if score > best_score:
            best_score = score
            best_url = sr.get("source_url")
    return best_url or record.get("official_url", "")


def generate_chunks(record):
    """为一条记录生成所有主题的文本块"""
    pid = record.get("product_id", "")
    pname = record.get("product_name", "")
    pcat = record.get("product_category", "")
    pcat_cn = CATEGORY_MAP.get(pcat, pcat)  # 中文产品类型
    specs = record.get("wearable_specs", {}) or {}
    summary = record.get("product_summary", "") or ""
    chunks = []
    data_status = record.get("data_quality", {}).get("status", "approved")

    # --- basic_info ---
    text_parts = []
    if pname:
        text_parts.append(f"{pname}是{record.get('brand', '')}的一款{pcat_cn}。")
    if summary:
        text_parts.append(f"产品简介：{summary}")
    source_url = find_source_url(record, ["basic_info"]) or record.get("official_url", "")
    chunks.append({
        "product_id": pid, "product_name": pname, "product_category": pcat,
        "chunk_id": f"{pid}_basic_info", "chunk_type": "basic_info",
        "text": " ".join(text_parts), "source_url": source_url,
        "data_status": data_status,
    })

    # --- display ---
    display_parts = []
    if specs.get("display_size_in"):
        display_parts.append(f"{pname}配备{specs['display_size_in']}英寸{specs.get('display_type', '')}显示屏。")
    elif specs.get("display_type"):
        display_parts.append(f"{pname}采用{specs['display_type']}显示屏。")
    if specs.get("screen_resolution"):
        display_parts.append(f"屏幕分辨率为{specs['screen_resolution']}。")
    if specs.get("max_brightness_nits"):
        display_parts.append(f"最高亮度可达{specs['max_brightness_nits']}尼特。")
    source_url = find_source_url(record, ["display_size_in", "display_type", "screen_resolution", "max_brightness"])
    if not display_parts:
        display_parts.append(f"{pname}的显示信息官方未提供。")
    chunks.append({
        "product_id": pid, "product_name": pname, "product_category": pcat,
        "chunk_id": f"{pid}_display", "chunk_type": "display",
        "text": " ".join(display_parts), "source_url": source_url,
        "data_status": data_status,
    })

    # --- battery ---
    battery_parts = []
    if specs.get("battery_life_typical_days") is not None:
        battery_parts.append(f"{pname}典型续航为{specs['battery_life_typical_days']}天。")
    if specs.get("battery_life_heavy_days") is not None:
        battery_parts.append(f"重度续航为{specs['battery_life_heavy_days']}天。")
    if specs.get("charging_time_minutes") is not None:
        battery_parts.append(f"充电时间约为{specs['charging_time_minutes']}分钟。")
    source_url = find_source_url(record, ["battery"])
    if not battery_parts:
        battery_parts.append(f"{pname}的续航信息官方未提供。")
    chunks.append({
        "product_id": pid, "product_name": pname, "product_category": pcat,
        "chunk_id": f"{pid}_battery", "chunk_type": "battery",
        "text": " ".join(battery_parts), "source_url": source_url,
        "data_status": data_status,
    })

    # --- positioning ---
    positioning_parts = []
    pos_type = specs.get("positioning_type")
    if pos_type == "built_in_gnss":
        features = specs.get("sports_features", []) or []
        # 中文映射已由 FEATURE_LABELS 处理，这里只找中文标注的 GNSS 描述
        gnss_info = [FEATURE_LABELS.get(f, f) for f in features
                     if any(kw in f for kw in ["GNSS", "GPS", "Galileo", "GLONASS", "BeiDou", "QZSS"])]
        if gnss_info:
            positioning_parts.append(f"{pname}支持的定位技术：{'，'.join(gnss_info)}。")
        else:
            positioning_parts.append(f"{pname}{POSITIONING_LABELS['built_in_gnss']}。")
    elif pos_type == "connected_phone":
        positioning_parts.append(f"{pname}{POSITIONING_LABELS['connected_phone']}。")
    elif pos_type == "none":
        positioning_parts.append(f"{pname}{POSITIONING_LABELS['none']}。")
    else:  # null 或其他未知值
        positioning_parts.append(f"{pname}的独立定位支持情况官方未明确说明。")
    source_url = find_source_url(record, ["positioning_type", "positioning"])
    chunks.append({
        "product_id": pid, "product_name": pname, "product_category": pcat,
        "chunk_id": f"{pid}_positioning", "chunk_type": "positioning",
        "text": " ".join(positioning_parts), "source_url": source_url,
        "data_status": data_status,
    })

    # --- communication ---
    comm_parts = []
    if specs.get("bluetooth_call"):
        comm_parts.append(f"{pname}支持蓝牙通话功能。")
    if specs.get("nfc_support") is True:
        comm_parts.append(f"{pname}支持NFC功能。")
    elif specs.get("nfc_support") is None:
        comm_parts.append(f"{pname}的NFC支持情况官方未明确说明。")
    source_url = find_source_url(record, ["bluetooth_call", "nfc_support"])
    if not comm_parts:
        comm_parts.append(f"{pname}未提供蓝牙通话和NFC功能信息。")
    chunks.append({
        "product_id": pid, "product_name": pname, "product_category": pcat,
        "chunk_id": f"{pid}_communication", "chunk_type": "communication",
        "text": " ".join(comm_parts), "source_url": source_url,
        "data_status": data_status,
    })

    # --- health ---
    health_parts = []
    health_features = []
    if specs.get("heart_rate_monitoring"): health_features.append("心率监测")
    if specs.get("blood_oxygen_monitoring"): health_features.append("血氧监测")
    if specs.get("sleep_monitoring"): health_features.append("睡眠监测")
    if specs.get("stress_monitoring"): health_features.append("压力监测")
    if health_features:
        health_parts.append(f"{pname}支持{'、'.join(health_features)}等健康监测功能。")
    else:
        health_parts.append(f"{pname}未提供健康监测功能信息。")
    source_url = find_source_url(record, ["heart_rate", "blood_oxygen", "sleep_monitoring", "stress"])
    chunks.append({
        "product_id": pid, "product_name": pname, "product_category": pcat,
        "chunk_id": f"{pid}_health", "chunk_type": "health",
        "text": " ".join(health_parts), "source_url": source_url,
        "data_status": data_status,
    })

    # --- sports ---
    sports_parts = []
    mode_count = specs.get("sports_modes_count")
    if mode_count is not None:
        sports_parts.append(f"{pname}提供{mode_count}种运动模式。")
    features = specs.get("sports_features", []) or []
    if features:
        non_gnss = [FEATURE_LABELS.get(f, f) for f in features
                     if not any(kw in f for kw in ["GNSS", "GPS", "Galileo", "GLONASS", "BeiDou", "QZSS", "双频"])]
        if non_gnss:
            sports_parts.append(f"特色运动功能包括：{'、'.join(non_gnss)}。")
    # 加入防水信息
    water = specs.get("water_resistance")
    if water:
        sports_parts.append(f"{pname}支持{water}防水。")
    source_url = find_source_url(record, ["sports_modes", "sports_feature"])
    if not sports_parts:
        sports_parts.append(f"{pname}的运动模式信息官方未提供。")
    chunks.append({
        "product_id": pid, "product_name": pname, "product_category": pcat,
        "chunk_id": f"{pid}_sports", "chunk_type": "sports",
        "text": " ".join(sports_parts), "source_url": source_url,
        "data_status": data_status,
    })

    # --- compatibility ---
    compat = specs.get("system_compatibility", "")
    if compat:
        compat_text = f"{pname}兼容系统：{compat}。"
    else:
        compat_text = f"{pname}的系统兼容信息官方未提供。"
    source_url = find_source_url(record, ["system_compatibility", "compatibility"])
    chunks.append({
        "product_id": pid, "product_name": pname, "product_category": pcat,
        "chunk_id": f"{pid}_compatibility", "chunk_type": "compatibility",
        "text": compat_text, "source_url": source_url,
        "data_status": data_status,
    })

    # --- design ---
    design_parts = []
    if specs.get("weight_g") is not None:
        design_parts.append(f"{pname}重量约为{specs['weight_g']}克。")
    if specs.get("dimensions_mm"):
        design_parts.append(f"尺寸为{specs['dimensions_mm']}毫米。")
    if specs.get("strap_material"):
        design_parts.append(f"表带材质为{specs['strap_material']}。")
    # 加入防水信息（确保每款产品都能回答"是否防水"）
    water = specs.get("water_resistance")
    if water:
        design_parts.append(f"{pname}支持{water}防水。")
    source_url = find_source_url(record, ["weight_g", "dimensions_mm", "strap_material"])
    if not design_parts:
        design_parts.append(f"{pname}的设计信息官方未提供。")
    chunks.append({
        "product_id": pid, "product_name": pname, "product_category": pcat,
        "chunk_id": f"{pid}_design", "chunk_type": "design",
        "text": " ".join(design_parts), "source_url": source_url,
        "data_status": data_status,
    })

    return chunks


def load_products(path):
    """加载所有产品 JSON 记录"""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def write_jsonl(chunks, path):
    """写入 JSONL 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def main():
    print("=" * 55)
    print("  P2-6 JSON → 参数文本块转换")
    print("=" * 55)

    # 检查输入文件
    print(f"\n[1] 检查输入文件: {INPUT_FILE}")
    if not INPUT_FILE.exists():
        print(f"[ERROR] 输入文件不存在: {INPUT_FILE}")
        sys.exit(1)
    print(f"  文件存在")

    # 加载产品数据
    print(f"\n[2] 加载产品数据")
    products = load_products(INPUT_FILE)
    print(f"  共加载 {len(products)} 款产品")

    # 生成文本块
    print(f"\n[3] 生成参数文本块")
    all_chunks = []
    for prod in products:
        chunks = generate_chunks(prod)
        all_chunks.extend(chunks)
    print(f"  生成 {len(all_chunks)} 个文本块")

    # 校验
    print(f"\n[4] 校验")
    errors = []
    from collections import Counter
    type_counter = Counter()
    product_ids = set()
    for c in all_chunks:
        type_counter[(c["product_id"], c["chunk_type"])] += 1
        product_ids.add(c["product_id"])

    for pid in sorted(product_ids):
        for ct in CHUNK_TYPES:
            if type_counter.get((pid, ct), 0) == 0:
                errors.append(f"产品 {pid} 缺少主题: {ct}")

    if errors:
        for e in errors:
            print(f"  [ERROR] {e}")
        print(f"\n[FAIL] 校验未通过")
        sys.exit(1)
    print(f"  校验通过，{len(product_ids)} 款产品 × {len(CHUNK_TYPES)} 主题 = {len(all_chunks)} 块")

    # 写入
    print(f"\n[5] 写入输出: {OUTPUT_FILE}")
    write_jsonl(all_chunks, OUTPUT_FILE)
    file_size = OUTPUT_FILE.stat().st_size
    print(f"  文件大小: {file_size} 字节")

    print(f"\n{'='*55}")
    print(f"  转换完成!")
    print(f"  产品数: {len(product_ids)}")
    print(f"  文本块总数: {len(all_chunks)}")
    print(f"  输出文件: {OUTPUT_FILE}")
    print(f"{'='*55}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
