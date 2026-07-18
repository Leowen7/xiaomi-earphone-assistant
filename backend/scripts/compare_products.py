import json
import os
import sys

# ========== 路径配置（和任务12完全一致的相对路径写法）==========
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRODUCT_DATA_PATH = os.path.join(BASE_DIR, "data", "processed", "product_data_clean.json")

# ========== 字段配置（固定顺序对齐 data_dictionary.xlsx）==========
# 对比字段固定顺序（与数据字典保持一致，避免字段漂移）
COMPARE_FIELD_ORDER = [
    "brand", "category", "product_level", "wearing_type",
    "reference_price", "single_weight_g", "single_battery_h", "total_battery_h",
    "anc_supported", "anc_depth_db", "dual_device", "low_latency",
    "bluetooth_version", "waterproof", "codec", "driver_size_mm",
    "manual_available", "data_status",
]

# 字段中文标签
FIELD_LABELS = {
    "brand": "品牌",
    "category": "产品品类",
    "product_level": "产品定位",
    "wearing_type": "佩戴方式",
    "reference_price": "参考价格",
    "single_weight_g": "单耳重量",
    "single_battery_h": "单次续航",
    "total_battery_h": "总续航",
    "anc_supported": "主动降噪",
    "anc_depth_db": "降噪深度",
    "dual_device": "双设备连接",
    "low_latency": "低延迟模式",
    "bluetooth_version": "蓝牙版本",
    "waterproof": "防水等级",
    "codec": "音频编码",
    "driver_size_mm": "驱动单元尺寸",
    "manual_available": "说明书",
    "data_status": "数据状态",
}

# 字段单位
FIELD_UNITS = {
    "reference_price": "元",
    "single_weight_g": "g",
    "single_battery_h": "小时",
    "total_battery_h": "小时",
    "anc_depth_db": "dB",
    "driver_size_mm": "mm",
}

# 数值型字段（可计算差值）—— bluetooth_version 为字符串语义，不算差值
NUMERIC_FIELDS = {
    "reference_price", "single_weight_g", "single_battery_h",
    "total_battery_h", "anc_depth_db", "driver_size_mm"
}

# 布尔型字段（转"支持/不支持"文案）—— manual_available 是枚举，不转换
BOOLEAN_FIELDS = {"anc_supported", "dual_device", "low_latency"}

# 展示层特殊映射（原始value不变，仅display用）
DISPLAY_OVERRIDE = {
    "category": {"earphone": "耳机"},
}

# 产品基础信息字段（products数组返回，不参与对比）
PRODUCT_BASIC_FIELDS = [
    "product_id", "product_name", "model", "source_url", "update_date", "remarks"
]

# 有效产品ID白名单
VALID_PRODUCT_IDS = {f"EAR{i:03d}" for i in range(1, 9)}

# ========== 工具函数 ==========
def load_products() -> list[dict]:
    """加载清洗后的产品数据"""
    if not os.path.exists(PRODUCT_DATA_PATH):
        raise FileNotFoundError(f"产品数据文件不存在：{PRODUCT_DATA_PATH}，请先运行任务12")
    with open(PRODUCT_DATA_PATH, "r", encoding="utf-8") as f:
        products = json.load(f)
    
    # 防御性校验：确保是列表
    if not isinstance(products, list):
        raise ValueError("产品数据格式错误：根节点应为数组")
    if len(products) != 8:
        raise ValueError(f"产品数据异常：应为8款，实际{len(products)}款")
    return products

def normalize_product_id(product_id: str) -> str:
    """标准化产品ID：去空格、转大写"""
    return str(product_id).strip().upper()

def get_product_by_id(products: list[dict], product_id: str) -> dict:
    """根据ID获取单个产品，不存在直接报错"""
    pid = normalize_product_id(product_id)
    for p in products:
        if p["product_id"] == pid:
            return p
    raise ValueError(f"产品ID不存在：{pid}，有效ID为EAR001-EAR008")

def format_number_display(value) -> str:
    """数值格式化：整数去掉.0后缀，统一int/float处理"""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)

def format_display_value(field: str, value) -> str:
    """格式化展示值（原始value保持不变，仅display层处理）"""
    if value is None:
        return "暂无官方数据"
    
    # 展示层特殊映射（category等）
    if field in DISPLAY_OVERRIDE and value in DISPLAY_OVERRIDE[field]:
        return DISPLAY_OVERRIDE[field][value]
    
    # 布尔字段转文案（严格判断 is True，避免脏数据误判）
    if field in BOOLEAN_FIELDS:
        return "支持" if value is True else "不支持"
    
    # 蓝牙版本加前缀
    if field == "bluetooth_version":
        return f"蓝牙 {format_number_display(value)}"
    
    # 数值字段加单位 + 整数去.0
    if field in FIELD_UNITS and FIELD_UNITS[field]:
        return f"{format_number_display(value)}{FIELD_UNITS[field]}"
    
    # 其余（含枚举、字符串）原样展示
    return str(value)

def calc_difference(field: str, val_a, val_b):
    """
    计算数值型字段差值
    约定：difference = 产品A - 产品B
    非数值型或任意一侧为null时返回None
    """
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
    """
    判断是否相同，三态逻辑：
    - 两边都为null → None（双方均无数据）
    - 一侧有值一侧null → False（存在差异）
    - 两边都有值且相等 → True
    - 两边都有值且不等 → False
    """
    if val_a is None and val_b is None:
        return None
    return val_a == val_b

def compare_product_dicts(product_a: dict, product_b: dict) -> list[dict]:
    """
    内部函数：直接对比两个产品dict，返回comparison数组
    供任务14/15复用，避免重复加载文件
    """
    comparison = []
    for field in COMPARE_FIELD_ORDER:
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
    return comparison

def compare_products(id_a: str, id_b: str) -> dict:
    """
    对外主接口：对比两款产品参数（前端友好结构）
    入参：两款产品ID（如 "EAR002", "EAR006"）
    返回：{success, products: [...], comparison: [...]}
    差值约定：difference = 产品A - 产品B
    """
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
            raise ValueError(f"产品ID不存在：{id_a_norm}，有效ID为EAR001-EAR008")
        if id_b_norm not in VALID_PRODUCT_IDS:
            raise ValueError(f"产品ID不存在：{id_b_norm}，有效ID为EAR001-EAR008")
        if id_a_norm == id_b_norm:
            raise ValueError(f"不能对比同一款产品：{id_a_norm}")

        # 3. 加载数据
        products = load_products()
        product_a = get_product_by_id(products, id_a_norm)
        product_b = get_product_by_id(products, id_b_norm)

        # 4. 产品基础信息
        basic_a = {k: product_a.get(k) for k in PRODUCT_BASIC_FIELDS}
        basic_b = {k: product_b.get(k) for k in PRODUCT_BASIC_FIELDS}

        # 5. 逐项对比
        comparison = compare_product_dicts(product_a, product_b)

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
        print(f"❌ 对比失败：{result['error']}")
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
    print(f"总参数字段：{total}，相同：{same_count}，差异：{diff_count}，无数据：{null_count}")
    print(f"{'='*60}")
    
    print(f"\n【差异参数】")
    for item in result["comparison"]:
        if item["same"] is False:
            print(f"  {item['label']}:")
            print(f"    {a_name}: {item['display_a']}")
            print(f"    {b_name}: {item['display_b']}")
            if item["difference"] is not None:
                print(f"    差值(A-B)：{item['difference']}{item['unit']}")
    
    print(f"\n【相同参数】")
    for item in result["comparison"]:
        if item["same"] is True:
            print(f"  {item['label']}: {item['display_a']}")
    
    if null_count > 0:
        print(f"\n【双方均无数据】{null_count} 项")
    print()

# ========== 主入口（命令行测试用）==========
def main():
    if len(sys.argv) >= 3:
        id_a, id_b = sys.argv[1], sys.argv[2]
    else:
        # 默认测试用例：两款ANC耳机对比
        id_a, id_b = "EAR002", "EAR006"
    
    print(f"任务13：产品参数对比工具")
    print(f"对比产品：{id_a} vs {id_b}")
    
    result = compare_products(id_a, id_b)
    print_compare_result(result)
    return result

if __name__ == "__main__":
    main()