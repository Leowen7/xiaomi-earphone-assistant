"""
P2-10 智能穿戴选购推荐引擎

依据 recommendation_rules.md（P2-9最终版）实现：
  加载冻结数据 → 系统兼容性检查 → 硬过滤 → 人群匹配加分 → 场景匹配加分 → 综合排序

规则要点：
- 数据源：data/wearables/processed/all_wearables.jsonl（冻结，禁止修改）
- 字段值为 null 时不得作为正向条件命中，也不得作为产品优势描述
- 全局执行顺序：系统兼容性 → 硬过滤 → 人群分（0—4） → 场景分（0—9） → 综合排序
- iOS / android_no_gms 必须剔除 W06、W07；android_gms 允许
- 无任何产品满足硬过滤时 expected_candidates=[]，near_match 仅作近似不混入正式候选
"""

import json
import re
from pathlib import Path

# ========== 路径配置 ==========
BASE_DIR = Path(__file__).resolve().parents[2]
WEARABLE_DATA_PATH = BASE_DIR / "data" / "wearables" / "processed" / "all_wearables.jsonl"

# ========== 系统兼容性：W06/W07 仅 android_gms 允许 ==========
GMS_ONLY_WATCHES = {"W06", "W07"}

# ========== 枚举 ==========
VALID_USER_DEVICES = {"iOS", "android_gms", "android_no_gms", "android"}
VALID_PRODUCT_IDS = {f"B{i:02d}" for i in range(1, 9)} | {f"W{i:02d}" for i in range(1, 9)}

# ========== 价格字段中文标签 ==========
FIELD_LABELS = {
    "official_price": "官方参考售价",
    "currency": "货币单位",
    "battery_life_typical_days": "典型续航",
    "display_size_in": "显示屏尺寸",
    "weight_g": "重量",
    "sports_modes_count": "运动模式数量",
    "bluetooth_call": "蓝牙通话",
    "nfc_support": "NFC支持",
    "positioning_type": "定位类型",
    "heart_rate_monitoring": "心率监测",
    "blood_oxygen_monitoring": "血氧监测",
    "sleep_monitoring": "睡眠监测",
    "stress_monitoring": "压力监测",
    "water_resistance": "防水等级",
}

# ========== 数值型字段 ==========
NUMERIC_FIELDS = {
    "official_price", "display_size_in", "max_brightness_nits",
    "battery_life_typical_days", "battery_life_heavy_days",
    "charging_time_minutes", "sports_modes_count", "weight_g",
}

# ========== 布尔型字段 ==========
BOOLEAN_FIELDS = {
    "bluetooth_call", "nfc_support",
    "heart_rate_monitoring", "blood_oxygen_monitoring",
    "sleep_monitoring", "stress_monitoring",
}


# ========== 预算范围解析 ==========
def normalize_budget_text(value) -> str:
    """统一前端预算文本中的横线、空格和货币写法。"""
    if value is None:
        return ""
    return (
        str(value)
        .strip()
        .replace("–", "-")
        .replace("—", "-")
        .replace("－", "-")
        .replace("～", "-")
        .replace("~", "-")
        .replace("Ａ＄", "A$")
        .replace("A＄", "A$")
        .replace("ａ＄", "A$")
        .replace("，", ",")
    )


def infer_budget_currency(value=None, currency=None) -> str | None:
    """根据显式币种或预算文本推断币种。

    前端穿戴设备预算使用 A$，因此即使服务层没有单独传 currency，
    也能从 ``A$50-120``、``AUD 100以下`` 或 ``100澳元以上`` 中识别 AUD。
    """
    if currency:
        return str(currency).strip().upper()

    text = normalize_budget_text(value).lower()
    if any(token in text for token in ("a$", "aud", "澳元")):
        return "AUD"
    if any(token in text for token in ("cny", "rmb", "人民币", "￥", "¥", "元")):
        return "CNY"
    if any(token in text for token in ("usd", "美元", "us$")):
        return "USD"
    return None


def parse_budget_range(value) -> tuple[float | None, float | None] | None:
    """解析人民币或澳元预算区间。

    支持示例：
      - A$50以下
      - A$50-120
      - A$120以上
      - 500元以内
      - 500-1000元

    返回 ``(min_budget, max_budget)``；None 表示该端不设限制。
    只有文本明确包含货币或预算语义时才解析，避免把 41mm、
    150种运动模式等普通数字误判成预算。
    """
    text = normalize_budget_text(value)
    if not text:
        return None

    lower = text.lower()
    has_budget_context = any(
        token in lower
        for token in (
            "元", "预算", "价格", "cny", "rmb", "￥", "¥",
            "a$", "aud", "澳元",
        )
    )
    if not has_budget_context:
        return None

    compact = re.sub(r"\s+", "", text)

    # 区间：500-1000元
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:元|cny|rmb|aud|澳元)?",
        compact,
        flags=re.IGNORECASE,
    )
    if match:
        low = float(match.group(1))
        high = float(match.group(2))
        if low > high:
            low, high = high, low
        return low, high

    # 上限：500元以内 / 500元以下 / 不超过500元
    match = re.search(
        r"(?:不超过|低于|小于)?\s*(\d+(?:\.\d+)?)\s*(?:元|cny|rmb|aud|澳元)?\s*(?:以内|以下|及以下|以内均可)?",
        compact,
        flags=re.IGNORECASE,
    )
    if match and any(token in compact for token in ("以内", "以下", "及以下", "不超过", "低于", "小于")):
        return None, float(match.group(1))

    # 下限：2000元以上 / 2000元起 / 不低于2000元
    match = re.search(
        r"(?:不低于|高于|大于)?\s*(\d+(?:\.\d+)?)\s*(?:元|cny|rmb|aud|澳元)?\s*(?:以上|及以上|起)?",
        compact,
        flags=re.IGNORECASE,
    )
    if match and any(token in compact for token in ("以上", "及以上", "起", "不低于", "高于", "大于")):
        return float(match.group(1)), None

    return None


def resolve_budget_range(user_demand: str = "", min_budget=None,
                         max_budget=None, budget_text=None
                         ) -> tuple[float | None, float | None]:
    """解析最终预算区间。

    优先级：显式 budget_text → user_demand 中的预算文本 → 数值参数。
    这样既兼容现有调用，也能直接识别前端传入的“500-1000元”。
    """
    parsed = parse_budget_range(budget_text)
    if parsed is None:
        parsed = parse_budget_range(user_demand)
    if parsed is not None:
        return parsed

    low = float(min_budget) if isinstance(min_budget, (int, float)) else None
    high = float(max_budget) if isinstance(max_budget, (int, float)) else None
    if low is not None and high is not None and low > high:
        low, high = high, low
    return low, high


def format_budget_range(min_budget=None, max_budget=None, currency=None) -> str:
    """生成用于推荐理由和诊断信息的预算区间文本。"""
    code = str(currency or "").strip().upper()
    prefix = {
        "AUD": "A$",
        "CNY": "¥",
        "USD": "$",
        "EUR": "€",
    }.get(code, "")
    suffix = "" if prefix else (f" {code}" if code else "")

    if isinstance(min_budget, (int, float)) and isinstance(max_budget, (int, float)):
        return (
            f"{prefix}{_format_money(min_budget)}-"
            f"{_format_money(max_budget)}{suffix}"
        )
    if isinstance(max_budget, (int, float)):
        return f"{prefix}{_format_money(max_budget)}{suffix}以下"
    if isinstance(min_budget, (int, float)):
        return f"{prefix}{_format_money(min_budget)}{suffix}以上"
    return "未设置"


# ============================================================
# 1. 数据加载
# ============================================================

def load_wearables() -> list[dict]:
    """加载穿戴设备数据；要求正好16条。"""
    if not WEARABLE_DATA_PATH.exists():
        raise FileNotFoundError(
            f"穿戴设备数据文件不存在：{WEARABLE_DATA_PATH}"
        )
    products: list[dict] = []
    with open(WEARABLE_DATA_PATH, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"数据文件第 {lineno} 行不是合法 JSON：{e}"
                ) from e
            if "product_id" not in obj:
                raise ValueError(f"数据文件第 {lineno} 行缺少 product_id")
            products.append(obj)
    if len(products) != 16:
        print(f"警告：期望16条记录，实际{len(products)}条")
    return products


def build_product_index(products: list[dict]) -> dict[str, dict]:
    """按 product_id 建立索引，便于 O(1) 查询。"""
    index: dict[str, dict] = {}
    for p in products:
        pid = str(p.get("product_id", "")).strip().upper()
        if not pid:
            continue
        index[pid] = p
    return index


def get_spec_value(product: dict, field: str):
    """获取某个字段的取值：wearable_specs 内的字段从子字典读取，其他从顶层读取。"""
    specs = product.get("wearable_specs") or {}
    if field in specs:
        return specs.get(field)
    return product.get(field)


# ============================================================
# 2. 系统兼容性
# ============================================================

def is_compatible_with_device(product: dict, user_device: str) -> bool:
    """判断产品在指定 user_device 下是否兼容。

    规则 §一 / §二：
      - W06、W07 仅在 user_device="android_gms" 时放行；
      - user_device="android"（不带 GMS 标记）必须剔除 W06、W07；
      - iOS / android_no_gms 一律剔除 W06、W07。
    """
    if user_device not in VALID_USER_DEVICES:
        raise ValueError(
            f"未知 user_device：{user_device}，仅支持 {sorted(VALID_USER_DEVICES)}"
        )
    pid = str(product.get("product_id", "")).strip().upper()
    if pid in GMS_ONLY_WATCHES and user_device != "android_gms":
        return False
    return True


# ============================================================
# 3. 硬过滤表达式解析与判定
# ============================================================

def _parse_operand(token: str):
    """解析硬过滤中的字段值：'true'/'false'/纯数字/带引号文本/裸字符串。"""
    t = token.strip()
    if t.lower() == "true":
        return True
    if t.lower() == "false":
        return False
    if t.lower() == "null":
        return None
    if t.startswith('"') and t.endswith('"'):
        return t[1:-1]
    if t.startswith("'") and t.endswith("'"):
        return t[1:-1]
    try:
        if "." in t:
            return float(t)
        return int(t)
    except ValueError:
        return t


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() == "true"
    return None


def _spec_value_for_filter(product: dict, field: str):
    """硬过滤统一从 wearable_specs 取数值；顶层字段按需取。"""
    specs = product.get("wearable_specs") or {}
    if field in specs:
        return specs.get(field)
    return product.get(field)


def _positive_swim_token(value) -> bool:
    """判定 sports_features 中是否存在正向游泳词条（且无否定表达）。"""
    if not isinstance(value, list):
        return False
    positive_keys = {"游泳", "泳池", "水上", "水上运动", "开放水域", "浅水", "近岸", "泳池游泳"}
    negative_keys = {"不支持", "无", "不提供"}
    for item in value:
        s = str(item)
        if any(n in s for n in negative_keys):
            continue
        if any(k in s for k in positive_keys):
            return True
        # 兼容英文：swim / open water / pool swim
        ls = s.lower()
        if any(n in ls for n in ("not support", "no ", "not ")):
            continue
        if any(k in ls for k in ("swim", "open water", "pool")):
            return True
    return False


def evaluate_hard_filter(product: dict, expr: str) -> bool:
    """评估单条 hard_filter 表达式。"""
    expr = expr.strip()

    # product_id in [a,b,c]
    m = re.match(r"^([\w]+)\s+in\s+\[(.*)\]$", expr)
    if m:
        field = m.group(1).strip()
        ids = [s.strip().strip("'\"") for s in m.group(2).split(",") if s.strip()]
        v = _spec_value_for_filter(product, field)
        return v in ids

    # 文本包含：<field> contains <text>
    m = re.match(r"^([\w]+)\s+contains\s+(.+)$", expr)
    if m:
        field = m.group(1).strip()
        needle = _parse_operand(m.group(2))
        if needle is None:
            return False
        v = _spec_value_for_filter(product, field)
        if v is None:
            return False
        if isinstance(v, list):
            return any(needle in str(x) for x in v)
        return needle in str(v)

    # 数组包含正向游泳能力：sports_features has_positive_swim_tracking=true
    m = re.match(r"^([\w]+)\s+has_positive_swim_tracking\s*=\s*(true|false)$", expr)
    if m:
        field = m.group(1).strip()
        target = m.group(2).lower() == "true"
        v = _spec_value_for_filter(product, field)
        return _positive_swim_token(v) == target

    # 数值比较：<field> >= <num> / > / <= / < / ==
    m = re.match(r"^([\w]+)\s*(>=|<=|>|<|==|!=)\s*(.+)$", expr)
    if m:
        field = m.group(1).strip()
        op = m.group(2)
        rhs = _to_float(_parse_operand(m.group(3)))
        lhs = _to_float(_spec_value_for_filter(product, field))
        if lhs is None or rhs is None:
            return False
        if op == ">=":
            return lhs >= rhs
        if op == "<=":
            return lhs <= rhs
        if op == ">":
            return lhs > rhs
        if op == "<":
            return lhs < rhs
        if op == "==":
            return lhs == rhs
        if op == "!=":
            return lhs != rhs
        return False

    # 布尔等值：<field>=true / false
    m = re.match(r"^([\w]+)\s*=\s*(true|false)$", expr)
    if m:
        field = m.group(1).strip()
        target = m.group(2).lower() == "true"
        v = _spec_value_for_filter(product, field)
        b = _to_bool(v)
        if b is None:
            # 规则 §全局约束1：null 既不等于 true 也不等于 false，直接跳过
            return False
        return b == target

    # 等值：<field>=<value>（数值/字符串）
    m = re.match(r"^([\w]+)\s*=\s*(.+)$", expr)
    if m:
        field = m.group(1).strip()
        rhs = _parse_operand(m.group(2))
        v = _spec_value_for_filter(product, field)
        if field in NUMERIC_FIELDS:
            lv, rv = _to_float(v), _to_float(rhs)
            if lv is None or rv is None:
                return False
            return lv == rv
        if field in BOOLEAN_FIELDS:
            # 规则 §全局约束1：null 字段不参与布尔等值判定
            lv = _to_bool(v)
            rv = _to_bool(rhs) if isinstance(rhs, bool) else None
            if lv is None or rv is None:
                return False
            return lv == rv
        return v == rhs

    raise ValueError(f"不支持的 hard_filter 表达式：{expr}")


def evaluate_all_hard_filters(product: dict, hard_filters: list[str]) -> bool:
    return all(evaluate_hard_filter(product, expr) for expr in hard_filters)


# ============================================================
# 4. 人群匹配加分
# ============================================================

USER_GROUP_KEYWORDS = {
    # key: 归一化人群标签；value: 用户需求关键词同义词
    "学生群体": ["学生", "预算有限", "预算敏感", "入门"],
    "细手腕用户": ["细手腕", "手腕纤细", "小表盘", "女生", "41mm"],
    "日常健康管理用户": ["长辈", "健康关注", "健康管理", "老年人"],
    "户外运动用户": ["户外", "跑步", "徒步", "滑雪"],
    "Wear OS应用需求用户": ["Wear OS", "Google", "谷歌生态"],
    "商务办公人士": ["商务", "上班族", "办公"],
}

USER_DEMAND_KEYWORDS = [
    "学生", "预算有限", "预算敏感", "入门",
    "细手腕", "手腕纤细", "小表盘", "女生", "41mm",
    "长辈", "健康关注", "健康管理",
    "户外", "跑步", "徒步", "滑雪",
    "Wear OS", "Google", "谷歌生态",
    "商务", "上班族", "办公",
]


def calc_user_group_score(product: dict, user_demand: str) -> int:
    """命中 target_users 标签则加分（每个+1，最多4分）。"""
    if not user_demand:
        return 0
    demand = user_demand.lower()
    target_users = product.get("target_users") or []
    if not isinstance(target_users, list):
        return 0

    matched = 0
    for label in target_users:
        label_lower = str(label).lower()
        # 1) 直接标签命中：用户需求关键词在标签里
        direct_hit = False
        for kw in USER_DEMAND_KEYWORDS:
            if kw.lower() in demand and kw in label:
                direct_hit = True
                break
        # 2) 归一化人群命中
        group_hit = False
        for group_label, synonyms in USER_GROUP_KEYWORDS.items():
            if group_label == label or any(s in label for s in synonyms):
                if any(s in user_demand for s in [group_label] + synonyms):
                    group_hit = True
                    break
        if direct_hit or group_hit:
            matched += 1
    return min(matched, 4)


# ============================================================
# 5. 场景匹配加分
# ============================================================

def calc_scene_score(product: dict, user_demand: str) -> tuple[int, list[str]]:
    """计算场景匹配加分；返回 (场景分, 命中说明列表)。

    只有用户明确提出功能/场景时才触发对应加分；不设任何默认通用场景分。
    """
    if not user_demand:
        return 0, []
    score = 0
    notes: list[str] = []
    specs = product.get("wearable_specs") or {}

    if any(k in user_demand for k in ("NFC", "nfc", "刷卡", "公交卡", "门禁卡", "银行卡支付", "Google Wallet")):
        if specs.get("nfc_support") is True:
            score += 2
            notes.append("NFC")

    if any(k in user_demand for k in ("蓝牙通话", "接电话", "打电话", "来电接听")):
        if specs.get("bluetooth_call") is True:
            score += 2
            notes.append("蓝牙通话")

    if any(k in user_demand for k in ("独立GNSS", "内置GNSS", "内置gnss", "独立定位", "不带手机", "脱离手机", "轨迹记录")):
        if specs.get("positioning_type") == "built_in_gnss":
            score += 1
            notes.append("独立GNSS")

    if any(k in user_demand for k in ("游泳", "水上运动", "泳池", "泳姿")):
        if _positive_swim_token(specs.get("sports_features")):
            score += 1
            notes.append("游泳记录")

    if any(k in user_demand for k in ("运动模式", "多运动", "丰富运动", "140种", "150种")):
        modes = specs.get("sports_modes_count")
        if isinstance(modes, (int, float)) and modes >= 140:
            score += 1
            notes.append("高运动模式")

    if any(k in user_demand for k in ("健康监测", "健康管理", "完整健康", "四项健康", "心率", "血氧", "睡眠", "压力")):
        if all(specs.get(k) is True for k in ("heart_rate_monitoring", "blood_oxygen_monitoring", "sleep_monitoring", "stress_monitoring")):
            score += 1
            notes.append("四项健康监测")

    if any(k in user_demand for k in ("长续航", "续航", "不频繁充电", "减少充电")):
        days = specs.get("battery_life_typical_days")
        if isinstance(days, (int, float)) and days >= 15:
            score += 1
            notes.append("长续航")

    return min(score, 9), notes


# ============================================================
# 6. 推荐理由生成
# ============================================================

def generate_match_reasons(product: dict, max_budget=None, currency=None,
                          hard_filters=None, user_demand="",
                          min_budget=None, budget_text=None) -> list[str]:
    """生成恰好 3 条客观中文推荐理由。

    优先顺序：
      1. 用户明确提出的功能需求命中（价格、蓝牙通话、NFC、GNSS、游泳等）
      2. 硬过滤命中的关键字段（续航达标、屏幕类型等）
      3. 客观补充字段（续航、运动模式、屏幕、重量、防水等）

    严格输出 3 条，不足时自动用补充字段补足。
    """
    specs = product.get("wearable_specs") or {}

    # 判断产品类型（影响阈值判断）
    pid = str(product.get("product_id", "") or "")
    is_band = pid.startswith("B")

    # 收集每条候选理由及其优先级（priority 越小越靠前）
    priority_reasons: list[tuple[int, str]] = []
    seen: set[str] = set()

    def add(priority: int, reason: str):
        if reason and reason not in seen:
            seen.add(reason)
            priority_reasons.append((priority, reason))

    user_demand_lower = (user_demand or "").lower()

    # ============================================================
    # 第一优先级 P0：用户明确提出 + 数据直接验证
    # ============================================================

    # 价格在预算范围内。支持“500-1000元”双边区间，不再只判断上限。
    resolved_min, resolved_max = resolve_budget_range(
        user_demand=user_demand,
        min_budget=min_budget,
        max_budget=max_budget,
        budget_text=budget_text,
    )
    price = product.get("official_price")
    cur = product.get("currency") or currency or "AUD"
    currency_matches = currency is None or cur == currency
    has_budget = resolved_min is not None or resolved_max is not None
    if isinstance(price, (int, float)) and has_budget and currency_matches:
        lower_ok = resolved_min is None or price >= resolved_min
        upper_ok = resolved_max is None or price <= resolved_max
        if lower_ok and upper_ok:
            price_display = {
                "AUD": "A$",
                "CNY": "¥",
                "USD": "$",
                "EUR": "€",
            }.get(str(cur).upper(), f"{cur} ")
            add(
                0,
                f"价格{price_display}{_format_money(price)}，符合"
                f"{format_budget_range(resolved_min, resolved_max, cur)}预算",
            )

    # 蓝牙通话（用户明确提"蓝牙通话"且产品支持）
    if any(k in user_demand for k in ["蓝牙通话", "打电话", "手腕接听"]):
        if specs.get("bluetooth_call") is True:
            add(0, "支持蓝牙通话")

    # NFC（用户明确提"NFC/刷公交/刷门禁/NFC支付/Google Wallet"）
    nfc_demand = any(k in user_demand for k in [
        "nfc", "NFC", "刷公交", "公交卡", "刷门禁", "门禁卡", "NFC支付",
        "银行卡支付", "Google Wallet",
    ])
    if nfc_demand and specs.get("nfc_support") is True:
        add(0, "支持NFC，具体公交、门禁、支付服务视地区和版本可用性而定")

    # 内置 GNSS（用户明确提"独立定位/内置GNSS/不带手机/脱离手机/轨迹记录"）
    if any(k in user_demand for k in [
        "独立定位", "内置GNSS", "内置gnss", "不带手机", "脱离手机", "轨迹记录",
    ]):
        if specs.get("positioning_type") == "built_in_gnss":
            add(0, "支持内置GNSS，可脱离手机独立记录轨迹")

    # 游泳记录（用户明确提"游泳/水上运动/泳池"）
    if any(k in user_demand for k in ["游泳", "水上运动", "泳池", "泳姿"]):
        feats = specs.get("sports_features")
        if isinstance(feats, list) and _positive_swim_token(feats):
            add(0, "支持游泳运动记录")

    # Google Wallet（用户明确提"Google Wallet/银行卡支付/Wear OS支付"）
    if any(k in user_demand for k in ["Google Wallet", "银行卡支付"]):
        us = product.get("usage_scenarios") or []
        for s in us:
            if "Google Wallet" in str(s):
                add(0, "支持Google Wallet银行卡支付（视地区可用性）")
                break

    # Wear OS（用户明确提"Wear OS/谷歌"）
    if "Wear OS" in user_demand or "wear os" in user_demand_lower:
        ps = product.get("product_summary") or ""
        if "Wear OS" in ps:
            add(0, "搭载Wear OS by Google")

    # 体成分测量（用户明确提"体成分"）
    if "体成分" in user_demand:
        feats = specs.get("sports_features")
        if isinstance(feats, list):
            for f in feats:
                if "体成分" in str(f):
                    add(0, "支持体成分测量")
                    break

    # 41mm 细手腕（用户明确提"细手腕/手腕纤细/41mm"）
    if any(k in user_demand for k in ["细手腕", "手腕纤细", "41mm", "小表盘"]):
        name = product.get("product_name") or ""
        if "41mm" in name:
            add(0, "采用41mm规格表盘，适合细手腕用户")

    # TFT 屏幕（用户明确提"TFT/入门"）
    if "TFT" in user_demand or "入门" in user_demand:
        if specs.get("display_type") == "TFT":
            add(0, "配备TFT显示屏")

    # ============================================================
    # 第二优先级 P1：硬过滤命中但未在 P0 出现的（用客观中文描述）
    # ============================================================
    # 注意：分类筛选（product_category）属于默认入参，不写进推荐理由

    if hard_filters:
        for hf in hard_filters:
            # 显示类型硬过滤
            m = re.match(r"^display_type\s*=\s*(.+)$", hf.strip())
            if m:
                target_display = _parse_operand(m.group(1))
                if specs.get("display_type") == target_display and target_display:
                    add(1, f"配备{target_display}显示屏")
                continue

            # 电池续航硬过滤（>=N 天）
            m = re.match(r"^battery_life_typical_days\s*>=\s*(\d+)$", hf.strip())
            if m:
                threshold = int(m.group(1))
                bl = specs.get("battery_life_typical_days")
                if isinstance(bl, (int, float)) and bl >= threshold:
                    add(1, f"典型续航{int(bl)}天，达到{threshold}天以上要求")
                continue

            # 防水/游泳能力硬过滤
            m = re.match(r"^water_resistance\s*=\s*(.+)$", hf.strip())
            if m:
                target = _parse_operand(m.group(1))
                wr = specs.get("water_resistance")
                if wr == target and target:
                    add(1, f"防水等级{target}")
                continue

    # ============================================================
    # 第三优先级 P1：场景默认权重贡献（用户在通勤/上班族/商务/办公场景）
    # ============================================================
    GENERIC_SCENE_KEYWORDS = ["通勤", "上班族", "商务", "办公", "日常通勤", "上下班"]
    in_generic_scene = any(k in user_demand for k in GENERIC_SCENE_KEYWORDS)
    if in_generic_scene:
        # 典型续航（去重：若硬过滤已写续航则跳过）
        bl = specs.get("battery_life_typical_days")
        if isinstance(bl, (int, float)) and bl >= 15:
            add(1, f"典型续航{int(bl)}天，减少充电频次")

    # ============================================================
    # 第四优先级 P2：用户场景/人群命中的额外理由
    # ============================================================

    # 长时间户外 / 户外运动（usage_scenarios 命中）
    tu = product.get("target_users") or []
    us = product.get("usage_scenarios") or []

    # 长续航偏好（用户需求提"续航"+"长续航"）
    # 注意：若硬过滤中已有 battery_life_typical_days>=N，本节不重复添加
    has_battery_hard_filter = any(
        hf.strip().startswith("battery_life_typical_days>=")
        for hf in (hard_filters or [])
    )
    if not has_battery_hard_filter and any(k in user_demand for k in ["续航", "长续航", "不想充电", "减少充电"]):
        bl = specs.get("battery_life_typical_days")
        if isinstance(bl, (int, float)) and bl >= 18:
            add(2, f"典型续航{int(bl)}天")

    # 健康监测需求
    if any(k in user_demand for k in ["健康监测", "健康管理", "四项监测", "体脂", "血氧"]):
        four_true = all(specs.get(k) is True for k in (
            "heart_rate_monitoring", "blood_oxygen_monitoring",
            "sleep_monitoring", "stress_monitoring",
        ))
        if four_true:
            add(2, "支持心率、血氧、睡眠、压力四项健康监测")
        else:
            # 列出已支持的监测项
            supported = []
            for k, label in [
                ("heart_rate_monitoring", "心率"),
                ("blood_oxygen_monitoring", "血氧"),
                ("sleep_monitoring", "睡眠"),
                ("stress_monitoring", "压力"),
            ]:
                if specs.get(k) is True:
                    supported.append(label)
            if supported:
                add(2, f"支持{'/'.join(supported)}监测")

    # 运动模式数量
    if any(k in user_demand for k in ["运动模式", "多运动", "丰富运动", "150种运动", "140种运动"]):
        sm = specs.get("sports_modes_count")
        if isinstance(sm, (int, float)) and sm >= 140:
            add(2, f"支持{int(sm)}种运动模式")

    # 户外运动人群标签命中
    if any(k in user_demand for k in ["户外", "跑步", "徒步", "滑雪", "登山"]):
        if specs.get("positioning_type") == "built_in_gnss":
            # 已在 P0 处理过，这里跳过避免重复
            pass
        elif "户外运动用户" in tu or "户外运动人群" in tu:
            add(2, "定位为户外运动用户群体")

    # 长辈/健康关注
    if any(k in user_demand for k in ["长辈", "健康关注", "老年人"]):
        if "日常健康管理用户" in tu or "健康关注者" in tu:
            add(2, "定位为日常健康关注用户群体")

    # 学生/预算敏感
    if any(k in user_demand for k in ["学生", "预算有限", "预算敏感", "入门"]):
        if "预算敏感用户" in tu or "学生群体" in tu or "智能手环入门用户" in tu:
            add(2, "定位为预算敏感/入门用户群体")

    # ============================================================
    # 第五优先级 P3：补充信息（屏幕、重量、系统兼容等用户能感知的字段）
    # ============================================================

    # 系统兼容性（仅在用户提 iOS/Android 时补充）
    sys_compat = specs.get("system_compatibility")
    if sys_compat:
        if "iOS" in user_demand and "iOS" in str(sys_compat):
            add(3, f"兼容iOS系统")
        elif "Android" in user_demand and "Android" in str(sys_compat):
            add(3, f"兼容Android {str(sys_compat).split(';')[0].strip().replace('Android ', '')}及以上")

    # 重量（常识阈值：手环<25g / 手表<40g 才算轻便）
    w_g = specs.get("weight_g")
    threshold = 25 if is_band else 40
    if isinstance(w_g, (int, float)) and w_g <= threshold:
        add(3, f"机身重量{_format_number(w_g)}g")

    # 屏幕尺寸（常识阈值：手环≥1.7" / 手表≥1.4" 才算大屏）
    ds = specs.get("display_size_in")
    threshold = 1.7 if is_band else 1.4
    if isinstance(ds, (int, float)) and ds >= threshold:
        add(3, f"屏幕尺寸{_format_number(ds)}英寸")

    # 按优先级排序并取前 3
    priority_reasons.sort(key=lambda x: x[0])
    reasons = [r for _, r in priority_reasons[:3]]

    # 严格补足 3 条：根据用户场景选相关正向属性补足
    if len(reasons) < 3:
        demand = user_demand or ""

        # 识别用户场景
        scene_sports = any(k in demand for k in ("运动", "户外", "跑步", "徒步", "滑雪", "登山", "GNSS", "定位", "游泳", "水上"))
        scene_commute = any(k in demand for k in ("通勤", "上班", "商务", "办公", "日常", "学生", "预算", "入门"))
        scene_health = any(k in demand for k in ("健康", "长辈", "老年", "体脂", "血压", "心率监", "血氧", "睡眠"))

        fallbacks: list[str] = []

        # 运动/户外场景：优先补防水、运动模式、全天健康监测
        if scene_sports:
            wr = specs.get("water_resistance")
            if wr and "5ATM" in str(wr) and not any("防水" in r for r in reasons):
                if _positive_swim_token(specs.get("sports_features")):
                    fallbacks.append(f"防水等级{str(wr)}，支持游泳运动记录")
                else:
                    fallbacks.append(f"防水等级{str(wr)}，适用于泳池及近岸浅水环境佩戴")
            sm = specs.get("sports_modes_count")
            if isinstance(sm, (int, float)) and sm >= 150 and not any("运动模式" in r for r in reasons):
                fallbacks.append(f"支持{int(sm)}种运动模式")
            four = all(specs.get(k) is True for k in ("heart_rate_monitoring", "blood_oxygen_monitoring", "sleep_monitoring", "stress_monitoring"))
            if four and not any("四项" in r or "监测" in r for r in reasons):
                fallbacks.append("支持全天健康监测")

        # 通勤/日常/学生场景：优先补续航、蓝牙通话、轻便
        if scene_commute and not scene_sports:
            bl = specs.get("battery_life_typical_days")
            bl_thresh = 14 if is_band else 7
            if isinstance(bl, (int, float)) and bl >= bl_thresh and not any("续航" in r for r in reasons):
                fallbacks.append(f"典型续航{int(bl)}天，减少充电频次")
            if specs.get("bluetooth_call") is True and not any("蓝牙通话" in r for r in reasons):
                fallbacks.append("支持蓝牙通话")
            w_g = specs.get("weight_g")
            thr = 25 if is_band else 40
            if isinstance(w_g, (int, float)) and w_g <= thr and not any("重量" in r for r in reasons):
                fallbacks.append(f"机身重量{_format_number(w_g)}g")

        # 健康/长辈场景：优先补健康监测、续航、防水
        if scene_health and not scene_sports and not scene_commute:
            four = all(specs.get(k) is True for k in ("heart_rate_monitoring", "blood_oxygen_monitoring", "sleep_monitoring", "stress_monitoring"))
            if four and not any("四项" in r or "监测" in r for r in reasons):
                fallbacks.append("支持心率、血氧、睡眠、压力四项健康监测")
            bl = specs.get("battery_life_typical_days")
            bl_thresh = 14 if is_band else 7
            if isinstance(bl, (int, float)) and bl >= bl_thresh and not any("续航" in r for r in reasons):
                fallbacks.append(f"典型续航{int(bl)}天")
            wr = specs.get("water_resistance")
            if wr and not any("防水" in r for r in reasons):
                fallbacks.append(f"防水等级{str(wr)}")

        # 补足 3 条（去重）
        for fb in fallbacks:
            if fb not in reasons:
                reasons.append(fb)
            if len(reasons) >= 3:
                break

        # 最后兜底：任何场景下按防水→续航→运动模式→健康监测→屏幕补
        if len(reasons) < 3:
            more: list[str] = []
            wr = specs.get("water_resistance")
            if wr and "5ATM" in str(wr) and not any("防水" in r for r in reasons):
                if _positive_swim_token(specs.get("sports_features")):
                    more.append(f"防水等级{str(wr)}，支持游泳运动记录")
                else:
                    more.append(f"防水等级{str(wr)}，适用于泳池及近岸浅水环境佩戴")
            bl = specs.get("battery_life_typical_days")
            if isinstance(bl, (int, float)) and not any("续航" in r for r in reasons):
                more.append(f"典型续航{int(bl)}天")
            sm = specs.get("sports_modes_count")
            if isinstance(sm, (int, float)) and sm >= 100 and not any("运动模式" in r for r in reasons):
                more.append(f"支持{int(sm)}种运动模式")

            ds = specs.get("display_size_in")
            dt = specs.get("display_type")
            if isinstance(ds, (int, float)) and not any("屏幕尺寸" in r for r in reasons):
                if dt:
                    more.append(f"屏幕尺寸{_format_number(ds)}英寸，显示类型{dt}")
                else:
                    more.append(f"屏幕尺寸{_format_number(ds)}英寸")

            w_g = specs.get("weight_g")
            if isinstance(w_g, (int, float)) and not any("机身重量" in r for r in reasons):
                more.append(f"机身重量{_format_number(w_g)}g")

            four = all(specs.get(k) is True for k in (
                "heart_rate_monitoring", "blood_oxygen_monitoring",
                "sleep_monitoring", "stress_monitoring",
            ))
            if four and not any("健康监测" in r or "四项" in r for r in reasons):
                more.append("支持心率、血氧、睡眠、压力四项健康监测")

            if specs.get("bluetooth_call") is True and not any("蓝牙通话" in r for r in reasons):
                more.append("支持蓝牙通话")
            if specs.get("nfc_support") is True and not any("NFC" in r for r in reasons):
                more.append("支持NFC，具体服务视地区和版本可用性而定")
            if specs.get("positioning_type") == "built_in_gnss" and not any("GNSS" in r for r in reasons):
                more.append("支持内置GNSS")

            sys_compat = specs.get("system_compatibility")
            if sys_compat and not any("兼容" in r for r in reasons):
                more.append(f"系统兼容性：{sys_compat}")

            for fb in more:
                if fb not in reasons:
                    reasons.append(fb)
                if len(reasons) >= 3:
                    break

    return reasons[:3]


# ============================================================
# 7. 综合排序
# ============================================================

def sort_candidates(candidates: list[dict]) -> list[dict]:
    """综合排序（与耳机 + 组长最终版完全一致）。

    五层稳定排序：
      1. total_score 降序（最重要）
      2. preference_hits 降序（命中数越多越靠前）
      3. 价格已知优先（known=0 排前，unknown=1 排后）
      4. 价格升序（已知价格越低越靠前，null=+∞ 排末尾）
      5. product_id 升序（保证结果确定性）
    """
    INF = float("inf")

    def key(c: dict):
        p = c.get("product") or {}
        price = p.get("official_price")
        known = 0 if isinstance(price, (int, float)) else 1
        price_val = float(price) if isinstance(price, (int, float)) else INF
        return (
            -int(c.get("total_score", 0)),
            -int(c.get("preference_hits", 0)),
            known,
            price_val,
            str(p.get("product_id", "")),
        )

    return sorted(candidates, key=key)


# ============================================================
# 8. 推荐主流程
# ============================================================

def _filter_and_score(products: list[dict], user_demand: str, user_device: str,
                     hard_filters: list[str],
                     max_budget=None, currency=None,
                     min_budget=None, budget_text=None
                     ) -> tuple[list[dict], dict[str, dict], list[tuple[dict, list[str]]], list[str], str | None]:
    """阶段一：系统兼容 → 硬过滤 → 价格筛选 → 人群/场景打分。

    Returns:
        scored:                 list[{product, group_score, scene_score, total_score, preference_hits}]
        scoring_summary:        {"<pid>": {"group_score", "scene_score", "total_score"}}
        near_candidate_pool:    list[(product, missing_exprs)]   ← 仅缺 1 条硬过滤的近似候选
        excluded_compat_notes:  list[str]                        ← 被系统兼容剔除的提示
        budget_near_pid:        str|None                         ← 价格未知触发的预算型 near_match
    """
    full_pass: list[dict] = []
    excluded_compat_notes: list[str] = []
    for p in products:
        pid = str(p.get("product_id"))
        if not is_compatible_with_device(p, user_device):
            excluded_compat_notes.append(
                f"{pid}: 系统不兼容 user_device={user_device}（W06/W07 仅支持 android_gms）"
            )
            continue
        if not evaluate_all_hard_filters(p, hard_filters):
            continue
        full_pass.append(p)

    near_candidate_pool: list[tuple[dict, list[str]]] = []
    if hard_filters:
        for p in products:
            if not is_compatible_with_device(p, user_device):
                continue
            missing = [expr for expr in hard_filters
                    if not evaluate_hard_filter(p, expr)]
            if 0 < len(missing) <= 1:
                near_candidate_pool.append((p, missing))

    # 预算是硬过滤：同时支持下限与上限。
    # 旧代码只判断 price <= max_budget，导致 A$215 也会进入“500-1000”结果。
    resolved_min, resolved_max = resolve_budget_range(
        user_demand=user_demand,
        min_budget=min_budget,
        max_budget=max_budget,
        budget_text=budget_text,
    )
    budget_near_pid: str | None = None
    has_budget = resolved_min is not None or resolved_max is not None
    if has_budget:
        kept: list[dict] = []
        for p in full_pass:
            price = p.get("official_price")
            cur = p.get("currency")
            if not isinstance(price, (int, float)):
                if budget_near_pid is None:
                    budget_near_pid = str(p.get("product_id"))
                continue
            # 指定币种时必须严格一致，避免把不同币种的数字直接比较。
            if currency and cur != currency:
                continue
            if resolved_min is not None and price < resolved_min:
                continue
            if resolved_max is not None and price > resolved_max:
                continue
            kept.append(p)
        full_pass = kept

    scored: list[dict] = []
    scoring_summary: dict = {}
    for p in full_pass:
        g_score = calc_user_group_score(p, user_demand)
        s_score, scene_notes = calc_scene_score(p, user_demand)
        total = g_score + s_score
        scored.append({
            "product": p,
            "group_score": g_score,
            "scene_score": s_score,
            "total_score": total,
            "preference_hits": g_score + len(scene_notes),
        })
        scoring_summary[str(p.get("product_id"))] = {
            "group_score": g_score,
            "scene_score": s_score,
            "total_score": total,
            "preference_hits": g_score + len(scene_notes),
        }
    return scored, scoring_summary, near_candidate_pool, excluded_compat_notes, budget_near_pid


def _select_near_match(expected: list[dict],
                       near_candidate_pool: list[tuple[dict, list[str]]],
                       budget_near_pid: str | None,
                       ) -> tuple[str | None, list[str]]:
    """阶段二：挑选 near_match_product_id 并生成对应 unmet_conditions。

    顺序：先看预算触发的 near_match（price=null），再看候选不足 3 时的 feature 近似候选。
    """
    unmet_conditions: list[str] = []
    near_match_pid: str | None = None

    if budget_near_pid:
        near_match_pid = budget_near_pid

    NEAR_MISSING_ALLOWED_PREFIXES = (
        "sports_features contains",
        "product_summary contains",
        "usage_scenarios contains",
    )

    if near_candidate_pool and len(expected) < 3 and not near_match_pid:
        feature_near = [
            (p, missing) for (p, missing) in near_candidate_pool
            if all(expr.startswith(NEAR_MISSING_ALLOWED_PREFIXES)
                   or expr.startswith("sports_features has_positive_swim_tracking")
                   for expr in missing)
        ]
        if feature_near:
            def affinity_key(item):
                p, _missing = item
                pid = str(p.get("product_id"))
                category = p.get("product_category", "")
                in_same_category = 0 if any(
                    (c["product_id"].startswith("B") and category == "smart_band")
                    or (c["product_id"].startswith("W") and category == "smart_watch")
                    for c in expected
                ) else 1
                return (in_same_category, pid)

            feature_near_sorted = sorted(feature_near, key=affinity_key)
            p, missing = feature_near_sorted[0]
            near_match_pid = str(p.get("product_id"))
            for expr in missing:
                if "sports_features contains" in expr:
                    needle = expr.split("contains")[-1].strip().strip("'\"")
                    unmet_conditions.append(f"sports_features不包含{needle}")
                elif "product_summary contains" in expr:
                    needle = expr.split("contains")[-1].strip().strip("'\"")
                    unmet_conditions.append(f"product_summary不包含{needle}")
                elif "usage_scenarios contains" in expr:
                    needle = expr.split("contains")[-1].strip().strip("'\"")
                    unmet_conditions.append(f"usage_scenarios不包含{needle}")
                elif "has_positive_swim_tracking" in expr:
                    unmet_conditions.append("sports_features无正向游泳词条")
                else:
                    unmet_conditions.append(f"未满足硬过滤：{expr}")
    return near_match_pid, unmet_conditions


def _build_expected_candidates(scored: list[dict],
                               max_budget=None,
                               currency=None,
                               hard_filters=None,
                               user_demand: str = "",
                               min_budget=None,
                               budget_text=None,
                               ) -> tuple[list[dict], str | None, list[str]]:
    """阶段三：综合排序 → 生成 expected_candidates 与预算型 near_match。

    Returns:
        expected:            list[{product_id, match_reasons}]
        budget_near_pid:     近似的预算型 near_match（仅当候选中存在 price=null 且被价格过滤剔除）
        price_unmet_notes:   对应的 unmet_conditions 列表
    """
    scored_sorted = sort_candidates(scored)
    expected: list[dict] = []
    for c in scored_sorted:
        pid = str(c["product"].get("product_id"))
        reasons = generate_match_reasons(
            c["product"], max_budget=max_budget, currency=currency,
            hard_filters=hard_filters, user_demand=user_demand,
            min_budget=min_budget, budget_text=budget_text,
        )
        expected.append({
            "product_id": pid,
            "match_reasons": reasons,
        })
    return expected, None, []


def recommend(user_demand: str, user_device: str, hard_filters: list[str],
              max_budget=None, currency=None, products=None,
              top_k: int = 3, min_budget=None, budget_text=None) -> dict:
    """主推荐函数（编排三阶段，与耳机 recommend_products 接口对齐）。

    参数：
        top_k:  返回前 k 个推荐结果（默认 3），传 None 返回全部

    返回：
      {
        "success": True,
        "total_candidates": ...,
        "expected_candidates": [...],
        "recommendations": [...],
        "near_match_product_id": str | None,
        "unmet_conditions": [...],
        ...
      }
    """
    if products is None:
        products = load_wearables()

    if user_device not in VALID_USER_DEVICES:
        return {"success": False, "error": f"未知 user_device：{user_device}"}

    # 穿戴设备前端使用 A$。即使服务层只传 budget_text 而遗漏 currency，
    # 也从预算文本中自动识别 AUD，防止跨币种直接比较。
    currency = infer_budget_currency(
        budget_text if budget_text not in (None, "") else user_demand,
        currency,
    )

    # 前端可能只把预算文本拼进 user_demand；这里统一解析成双边区间。
    resolved_min, resolved_max = resolve_budget_range(
        user_demand=user_demand,
        min_budget=min_budget,
        max_budget=max_budget,
        budget_text=budget_text,
    )

    # 阶段一：系统兼容 + 硬过滤 + 价格 + 打分
    scored, scoring_summary, near_candidate_pool, excluded_compat_notes, budget_near_pid = \
        _filter_and_score(
            products=products,
            user_demand=user_demand,
            user_device=user_device,
            hard_filters=hard_filters,
            max_budget=resolved_max,
            currency=currency,
            min_budget=resolved_min,
            budget_text=budget_text,
        )

    # 阶段三：排序 + 生成 expected（按耳机的三层稳定排序）
    # 注意：expected 保留全部候选用于 near_match 逻辑；top_k 仅截断返回
    all_expected, _, _ = _build_expected_candidates(
        scored, max_budget=resolved_max, currency=currency,
        hard_filters=hard_filters, user_demand=user_demand,
        min_budget=resolved_min, budget_text=budget_text,
    )

    # expected_candidates 始终保留完整硬过滤候选集合；
    # top_k 只限制最终 recommendations，不截断完整候选。
    expected = all_expected

    # 阶段二：挑选 near_match（near_match 基于全部候选，不受 top_k 影响）
    budget_unmet: list[str] = []
    if budget_near_pid is not None:
        budget_unmet = [
            "official_price=null，价格未知，无法确认是否满足"
            f"{format_budget_range(resolved_min, resolved_max, currency)}预算"
        ]
    near_match_pid, feature_unmet = _select_near_match(
        all_expected, near_candidate_pool, budget_near_pid,
    )
    unmet_conditions = budget_unmet + feature_unmet

    # 系统兼容剔除记录（仅当无候选时附注，便于诊断）
    if excluded_compat_notes and not all_expected and not near_match_pid:
        unmet_conditions = excluded_compat_notes + unmet_conditions

    # 构建 recommendations（rank / name / score / price / currency + match_reasons）
    # recommendations 基于 scored 列表（包含完整 product 数据），按 sort_candidates 排序
    scored_sorted = sort_candidates(scored)
    pid_to_reasons = {c["product_id"]: c["match_reasons"] for c in all_expected}
    if top_k is None:
        recommendation_items = scored_sorted
    elif isinstance(top_k, int) and top_k > 0:
        recommendation_items = scored_sorted[:top_k]
    else:
        recommendation_items = scored_sorted

    recommendations: list[dict] = []
    for rank, item in enumerate(recommendation_items, 1):
        prod = item["product"]
        pid = str(prod.get("product_id", ""))
        recommendations.append({
            "rank": rank,
            "product_id": pid,
            "product_name": prod.get("product_name", ""),
            "score": item.get("total_score", 0),
            "group_score": item.get("group_score", 0),
            "scene_score": item.get("scene_score", 0),
            "official_price": prod.get("official_price"),
            "currency": prod.get("currency"),
            "match_reasons": pid_to_reasons.get(pid, []),
        })

    return {
        "success": True,
        "total_candidates": len(all_expected),
        "expected_candidates": expected,
        "recommendations": recommendations,
        "near_match_product_id": near_match_pid,
        "unmet_conditions": unmet_conditions,
        "user_device": user_device,
        "hard_filter_applied": list(hard_filters),
        "budget_applied": {
            "min": resolved_min,
            "max": resolved_max,
            "currency": currency,
        },
        "scoring_summary": scoring_summary,
    }


# ============================================================
# 9. 工具函数
# ============================================================

def _format_number(v) -> str:
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:g}"
    return str(v)


def _format_money(v) -> str:
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:g}"
    return str(v)


# ============================================================
# 10. CLI 调试
# ============================================================

def main():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"

    products = load_wearables()
    index = build_product_index(products)

    if cmd == "demo":
        # 默认演示：找一个手环+内置GNSS+游泳
        result = recommend(
            user_demand="户外跑步游泳",
            user_device="iOS",
            hard_filters=[
                "product_category=smart_band",
                "positioning_type=built_in_gnss",
            ],
            products=products,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "by_id":
        pid = sys.argv[2] if len(sys.argv) > 2 else "B01"
        p = index.get(pid.upper())
        if not p:
            print(f"产品不存在：{pid}")
            return
        print(json.dumps(p, ensure_ascii=False, indent=2))
    else:
        print("用法：python recommend_wearables.py [demo|by_id <pid>]")


if __name__ == "__main__":
    main()
