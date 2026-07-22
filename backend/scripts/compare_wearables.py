import json
import os
import sys
from pathlib import Path

# ========== 路径配置 ==========
BASE_DIR = Path(__file__).resolve().parents[2]
# 统一数据路径：data/wearables/processed/
WEARABLE_DATA_PATH = BASE_DIR / "data" / "wearables" / "processed" / "all_wearables.jsonl"

# ========== 穿戴设备对比字段配置 ==========
# 通用字段（smart_band和smart_watch都有）
COMMON_COMPARE_FIELDS = [
    "display_size_in",
    "display_type",
    "screen_resolution",
    "max_brightness_nits",
    "battery_life_typical_days",
    "battery_life_heavy_days",
    "charging_time_minutes",
    "water_resistance",
    "positioning_type",
    "bluetooth_call",
    "nfc_support",
    "heart_rate_monitoring",
    "blood_oxygen_monitoring",
    "sleep_monitoring",
    "stress_monitoring",
    "sports_modes_count",
    "sports_features",
    "system_compatibility",
    "weight_g",
    "dimensions_mm",
    "strap_material",
]

# 基础信息字段（含价格）
BASIC_COMPARE_FIELDS = [
    "official_price",
    "currency",
]

# 字段中文标签
FIELD_LABELS = {
    "official_price": "官方参考售价",
    "currency": "货币单位",
    "display_size_in": "显示屏尺寸",
    "display_type": "显示屏类型",
    "screen_resolution": "屏幕分辨率",
    "max_brightness_nits": "最大亮度",
    "battery_life_typical_days": "典型续航",
    "battery_life_heavy_days": "重度续航",
    "charging_time_minutes": "充电时间",
    "water_resistance": "防水等级",
    "positioning_type": "定位类型",
    "bluetooth_call": "蓝牙通话",
    "nfc_support": "NFC支持",
    "heart_rate_monitoring": "心率监测",
    "blood_oxygen_monitoring": "血氧监测",
    "sleep_monitoring": "睡眠监测",
    "stress_monitoring": "压力监测",
    "sports_modes_count": "运动模式数量",
    "sports_features": "运动功能",
    "system_compatibility": "系统兼容性",
    "weight_g": "重量",
    "dimensions_mm": "尺寸",
    "strap_material": "表带材质",
}

# 字段单位
FIELD_UNITS = {
    "official_price": "AUD",
    "display_size_in": "英寸",
    "max_brightness_nits": "尼特",
    "battery_life_typical_days": "天",
    "battery_life_heavy_days": "天",
    "charging_time_minutes": "分钟",
    "weight_g": "g",
}

# 数值型字段
NUMERIC_FIELDS = {
    "official_price",
    "display_size_in", "max_brightness_nits",
    "battery_life_typical_days", "battery_life_heavy_days",
    "charging_time_minutes", "sports_modes_count", "weight_g"
}

# 布尔型字段
BOOLEAN_FIELDS = {
    "bluetooth_call", "nfc_support",
    "heart_rate_monitoring", "blood_oxygen_monitoring",
    "sleep_monitoring", "stress_monitoring"
}

# 产品基础信息字段
PRODUCT_BASIC_FIELDS = [
    "product_id", "product_name", "product_category", "brand",
    "variant", "source_region", "official_url", "product_summary"
]

# 有效产品ID白名单
VALID_PRODUCT_IDS = {f"B{i:02d}" for i in range(1, 9)} | {f"W{i:02d}" for i in range(1, 9)}


def load_wearables() -> list[dict]:
    """加载穿戴设备数据"""
    if not WEARABLE_DATA_PATH.exists():
        raise FileNotFoundError(
            f"穿戴设备数据文件不存在：{WEARABLE_DATA_PATH}，请先确保数据文件已生成"
        )
    with open(WEARABLE_DATA_PATH, "r", encoding="utf-8") as f:
        records = []
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    if len(records) != 16:
        print(f"警告：期望16条记录，实际{len(records)}条")
    return records


def normalize_product_id(product_id: str) -> str:
    """标准化产品ID"""
    return str(product_id).strip().upper()


def get_product_by_id(products: list[dict], product_id: str) -> dict:
    """根据ID获取单个产品"""
    pid = normalize_product_id(product_id)
    for p in products:
        if p["product_id"] == pid:
            return p
    raise ValueError(f"产品ID不存在：{pid}，有效ID为B01-B08（手环）或W01-W08（手表）")


def format_number_display(value) -> str:
    """数值格式化"""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def format_display_value(field: str, value) -> str:
    """格式化展示值（含单位）"""
    if value is None:
        # 价格为null时显示"官方价格暂缺"，其他字段显示"官方未提供"
        if field == "official_price":
            return "官方价格暂缺"
        return "官方未提供"

    # 布尔字段转文案
    if field in BOOLEAN_FIELDS:
        return "支持" if value is True else "不支持"

    # 数值字段加单位
    if field in FIELD_UNITS and FIELD_UNITS[field]:
        return f"{format_number_display(value)}{FIELD_UNITS[field]}"

    # 列表类型（sports_features）
    if field == "sports_features":
        if isinstance(value, list) and value:
            return ", ".join(str(v) for v in value)
        return "无"

    # 其余原样展示
    return str(value)


def calc_difference(field: str, val_a, val_b):
    """计算数值型字段差值"""
    if field not in NUMERIC_FIELDS:
        return None
    if val_a is None or val_b is None:
        return None
    try:
        diff = float(val_a) - float(val_b)
        return int(diff) if diff.is_integer() else round(diff, 2)
    except (TypeError, ValueError):
        return None


def is_same(val_a, val_b):
    """判断是否相同"""
    if val_a is None and val_b is None:
        return None
    return val_a == val_b


def compare_wearable_dicts(product_a: dict, product_b: dict) -> list[dict]:
    """对比两个穿戴设备dict"""
    comparison = []

    # 1. 先对比基础信息（含价格）
    for field in BASIC_COMPARE_FIELDS:
        val_a = product_a.get(field)
        val_b = product_b.get(field)
        comparison.append({
            "field": field,
            "label": FIELD_LABELS.get(field, field),
            "unit": FIELD_UNITS.get(field, ""),
            "value_a": val_a,
            "value_b": val_b,
            "display_a": format_display_value(field, val_a),
            "display_b": format_display_value(field, val_b),
            "difference": calc_difference(field, val_a, val_b),
            "same": is_same(val_a, val_b),
        })

    # 2. 再对比规格参数
    for field in COMMON_COMPARE_FIELDS:
        specs_a = product_a.get("wearable_specs", {})
        specs_b = product_b.get("wearable_specs", {})
        val_a = specs_a.get(field)
        val_b = specs_b.get(field)

        comparison.append({
            "field": field,
            "label": FIELD_LABELS.get(field, field),
            "unit": FIELD_UNITS.get(field, ""),
            "value_a": val_a,
            "value_b": val_b,
            "display_a": format_display_value(field, val_a),
            "display_b": format_display_value(field, val_b),
            "difference": calc_difference(field, val_a, val_b),
            "same": is_same(val_a, val_b),
        })
    return comparison


def compare_products(id_a: str, id_b: str) -> dict:
    """对比两款穿戴设备"""
    try:
        # 1. 空ID校验
        id_a_clean = str(id_a).strip()
        id_b_clean = str(id_b).strip()
        if not id_a_clean or not id_b_clean:
            raise ValueError("产品ID不能为空")

        # 2. 标准化ID并校验
        id_a_norm = normalize_product_id(id_a_clean)
        id_b_norm = normalize_product_id(id_b_clean)

        if id_a_norm not in VALID_PRODUCT_IDS:
            raise ValueError(f"产品ID不存在：{id_a_norm}，有效ID为B01-B08或W01-W08")
        if id_b_norm not in VALID_PRODUCT_IDS:
            raise ValueError(f"产品ID不存在：{id_b_norm}，有效ID为B01-B08或W01-W08")
        if id_a_norm == id_b_norm:
            raise ValueError(f"不能对比同一款产品：{id_a_norm}")

        # 3. 加载数据
        products = load_wearables()
        product_a = get_product_by_id(products, id_a_norm)
        product_b = get_product_by_id(products, id_b_norm)

        # 4. 产品基础信息
        basic_a = {k: product_a.get(k) for k in PRODUCT_BASIC_FIELDS}
        basic_b = {k: product_b.get(k) for k in PRODUCT_BASIC_FIELDS}

        # 5. 逐项对比
        comparison = compare_wearable_dicts(product_a, product_b)

        return {
            "success": True,
            "products": [basic_a, basic_b],
            "comparison": comparison,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def print_compare_result(result: dict):
    """格式化打印对比结果"""
    if not result["success"]:
        print(f"对比失败：{result['error']}")
        return

    p_a = result["products"][0]
    p_b = result["products"][1]
    a_name = p_a["product_name"]
    b_name = p_b["product_name"]

    diff_count = sum(1 for item in result["comparison"] if item["same"] is False)
    same_count = sum(1 for item in result["comparison"] if item["same"] is True)
    null_count = sum(1 for item in result["comparison"] if item["same"] is None)
    total = len(result["comparison"])

    print(f"\n{'='*60}")
    print(f"对比：{a_name}  vs  {b_name}")
    print(f"品类：{p_a['product_category']} vs {p_b['product_category']}")
    print(f"总参数字段：{total}，相同：{same_count}，差异：{diff_count}，无数据：{null_count}")
    print(f"{'='*60}")

    print(f"\n【价格信息】")
    for item in result["comparison"]:
        if item["field"] in BASIC_COMPARE_FIELDS:
            print(f"  {item['label']}:")
            print(f"    {a_name}: {item['display_a']}")
            print(f"    {b_name}: {item['display_b']}")
            if item["difference"] is not None:
                print(f"    差值(A-B)：{item['difference']}{item['unit']}")

    print(f"\n【规格参数差异】")
    spec_diffs = [item for item in result["comparison"]
                  if item["field"] in COMMON_COMPARE_FIELDS and item["same"] is False]
    for item in spec_diffs:
        print(f"  {item['label']}:")
        print(f"    {a_name}: {item['display_a']}")
        print(f"    {b_name}: {item['display_b']}")
        if item["difference"] is not None:
            print(f"    差值(A-B)：{item['difference']}{item['unit']}")

    print(f"\n【规格参数相同】")
    spec_same = [item for item in result["comparison"]
                 if item["field"] in COMMON_COMPARE_FIELDS and item["same"] is True]
    for item in spec_same:
        print(f"  {item['label']}: {item['display_a']}")

    null_specs = [item for item in result["comparison"]
                  if item["field"] in COMMON_COMPARE_FIELDS and item["same"] is None]
    if null_specs:
        print(f"\n【双方均无数据】{len(null_specs)} 项")
    print()


def main():
    if len(sys.argv) >= 3:
        id_a, id_b = sys.argv[1], sys.argv[2]
    else:
        # 默认测试用例：两款智能手环对比
        id_a, id_b = "B01", "B02"

    print(f"穿戴设备产品对比工具")
    print(f"数据来源：{WEARABLE_DATA_PATH}")
    print(f"对比产品：{id_a} vs {id_b}")

    result = compare_products(id_a, id_b)
    print_compare_result(result)
    return result


if __name__ == "__main__":
    main()
