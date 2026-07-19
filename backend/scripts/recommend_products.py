import json
import os
import sys
from typing import Optional, List

# ========== 路径配置 ==========
# 兼容两种部署位置（与 compare_products.py / clean_product_data.py 风格一致）：
# 1. 仓库部署：脚本在 <repo_root>/backend/scripts/，3 层 dirname = 仓库根
# 2. 本地 v4 测试：脚本在 v4/，BASE_DIR 实际指向 v4 的父目录，自动找 v4/data 和 v4/earphone_rules.json
#    （通过 os.path.exists 探测实际文件位置，优先仓库布局）
from pathlib import Path

# 项目仓库根目录：
# xiaomi-earphone-assistant/
REPO_ROOT = Path(__file__).resolve().parents[2]

# 任务12标准化产品数据
PRODUCT_DATA_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "product_data_clean.json"
)

# 任务14推荐规则配置
RULES_CONFIG_PATH = (
    REPO_ROOT
    / "configs"
    / "earphone_rules.json"
)

# ========== 场景配置 ==========
VALID_SCENARIOS = ["daily", "commuting", "sports", "gaming"]
SCENARIO_LABELS = {
    "daily": "日常使用",
    "commuting": "通勤出行",
    "sports": "运动健身",
    "gaming": "游戏娱乐",
}

# 动态权重调整幅度（默认值，可被配置文件覆盖）
DEFAULT_WEIGHT_ADJUST_DELTA = 0.2

# ========== 默认评分配置（配置文件缺失时兜底） ==========
DEFAULT_SCENARIO_WEIGHTS = {
    "daily": {
        "reference_price": 0.25,
        "single_weight_g": 0.25,
        "wearing_type": 0.15,
        "total_battery_h": 0.15,
        "codec": 0.10,
        "bluetooth_version": 0.05,
        "anc_supported": 0.05,
    },
    "commuting": {
        "anc_supported": 0.30,
        "total_battery_h": 0.20,
        "single_weight_g": 0.15,
        "dual_device": 0.15,
        "reference_price": 0.10,
        "bluetooth_version": 0.10,
    },
    "sports": {
        "waterproof": 0.30,
        "single_weight_g": 0.20,
        "wearing_type": 0.20,
        "total_battery_h": 0.15,
        "reference_price": 0.10,
        "anc_supported": 0.05,
    },
    "gaming": {
        "low_latency": 0.35,
        "bluetooth_version": 0.20,
        "total_battery_h": 0.15,
        "single_weight_g": 0.15,
        "reference_price": 0.15,
    },
}

# 数值字段阈值（min/max 控制线性映射范围，optimal_min/max 字段已废弃但保留兼容性）
DEFAULT_NUMERIC_THRESHOLDS = {
    "reference_price": {"min": 50, "max": 2000, "higher_is_better": False},
    "single_weight_g": {"min": 3, "max": 15, "higher_is_better": False},
    "total_battery_h": {"min": 15, "max": 50, "higher_is_better": True},
    "anc_depth_db": {"min": 20, "max": 50, "higher_is_better": True},
    "bluetooth_version": {"min": 5.0, "max": 5.4, "higher_is_better": True},
}

DEFAULT_ENUM_SCORES = {
    "wearing_type": {
        "开放式": 0.3, "半入耳式": 0.5, "入耳式": 0.7,
        "耳夹式": 0.4, "骨传导": 0.3, "待核验": 0.0,
    },
    "waterproof": {
        "IPX8": 0.9, "IP68": 0.9, "IP55": 0.5, "IP54": 0.5,
        "IPX5": 0.3, "IPX4": 0.3, "无": 0.0, "待核验": 0.0,
    },
    "codec": {
        "SBC": 0.2, "AAC": 0.5, "aptX": 0.7, "aptX LL": 0.8,
        "LDAC": 0.9, "LHDC": 0.9, "待核验": 0.5, None: 0.0,
    },
}

_config_cache = None


def _load_config() -> dict:
    """加载配置文件，缺失时使用默认配置兜底。权重幅度 weight_adjust_delta 可从配置文件覆盖。"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config = {
        "scenarios": {},
        "numeric_thresholds": {},
        "enum_scores": {},
        "weight_adjust_delta": DEFAULT_WEIGHT_ADJUST_DELTA,
    }

    if os.path.exists(RULES_CONFIG_PATH):
        with open(RULES_CONFIG_PATH, "r", encoding="utf-8") as f:
            file_config = json.load(f)
        if "scenarios" in file_config:
            for s, cfg in file_config["scenarios"].items():
                config["scenarios"][s] = cfg.get("weights", {})
        if "numeric_thresholds" in file_config:
            config["numeric_thresholds"] = file_config["numeric_thresholds"]
        if "enum_scores" in file_config:
            config["enum_scores"] = file_config["enum_scores"]
        if "weight_adjust_delta" in file_config:
            config["weight_adjust_delta"] = float(file_config["weight_adjust_delta"])

    for s in VALID_SCENARIOS:
        if s not in config["scenarios"]:
            config["scenarios"][s] = DEFAULT_SCENARIO_WEIGHTS.get(s, {})
    for f, cfg in DEFAULT_NUMERIC_THRESHOLDS.items():
        if f not in config["numeric_thresholds"]:
            config["numeric_thresholds"][f] = cfg
    for f, scores in DEFAULT_ENUM_SCORES.items():
        if f not in config["enum_scores"]:
            config["enum_scores"][f] = scores

    _config_cache = config
    return config


def _adjust_weights(
    base_weights: dict,
    prioritize_lightweight: bool = False,
    prioritize_long_battery: bool = False,
) -> dict:
    """动态调整权重并重新归一化，保证权重和为1.0。"""
    config = _load_config()
    delta = config.get("weight_adjust_delta", DEFAULT_WEIGHT_ADJUST_DELTA)
    weights = base_weights.copy()

    if prioritize_lightweight and "single_weight_g" in weights:
        weights["single_weight_g"] += delta
    if prioritize_long_battery and "total_battery_h" in weights:
        weights["total_battery_h"] += delta

    for k in weights:
        if weights[k] < 0:
            weights[k] = 0

    total = sum(weights.values())
    if total == 0:
        return base_weights
    for k in weights:
        weights[k] = round(weights[k] / total, 3)
    return weights


def load_products() -> list[dict]:
    if not os.path.exists(PRODUCT_DATA_PATH):
        raise FileNotFoundError(
            f"产品数据文件不存在：{PRODUCT_DATA_PATH}，请先运行任务12"
        )
    with open(PRODUCT_DATA_PATH, "r", encoding="utf-8") as f:
        products = json.load(f)
    if not isinstance(products, list) or len(products) != 8:
        raise ValueError(
            f"产品数据异常：应为8款，实际{len(products) if isinstance(products, list) else type(products)}款"
        )
    return products


def score_boolean(field: str, value) -> float:
    if field in ["anc_supported", "dual_device", "low_latency"]:
        return 1.0 if value is True else 0.0
    return 0.0


def score_enum(field: str, value) -> float:
    config = _load_config()
    enum_scores = config.get("enum_scores", {})
    if field in enum_scores and value in enum_scores[field]:
        return enum_scores[field][value]
    if field in enum_scores and value is None:
        return enum_scores[field].get(None, 0.0)
    return 0.5


def score_numeric(field: str, value) -> float:
    config = _load_config()
    thresholds = config.get("numeric_thresholds", {})
    if field not in thresholds or value is None:
        return 0.0
    try:
        val = float(value)
    except (TypeError, ValueError):
        return 0.0
    cfg = thresholds[field]
    min_v, max_v = float(cfg["min"]), float(cfg["max"])
    if max_v == min_v:
        return 0.0
    higher_better = bool(cfg.get("higher_is_better", True))
    val = max(min_v, min(max_v, val))
    score = (val - min_v) / (max_v - min_v) if higher_better else (max_v - val) / (max_v - min_v)
    return round(max(0.0, min(score, 1.0)), 3)


def score_field(field: str, value) -> float:
    config = _load_config()
    if value is True or value is False:
        return score_boolean(field, value)
    if field in config.get("numeric_thresholds", {}):
        return score_numeric(field, value)
    if field in config.get("enum_scores", {}):
        return score_enum(field, value)
    return 0.5


def score_product(product: dict, adjusted_weights: dict) -> dict:
    """对单个产品按调整后的权重计算总分和明细。"""
    breakdown = []
    total_weighted = 0.0
    total_valid_weight = 0.0

    for field, weight in adjusted_weights.items():
        field_score = score_field(field, product.get(field))
        is_missing = product.get(field) is None
        if is_missing:
            breakdown.append({
                "field": field,
                "weight": 0.0,
                "original_weight": weight,
                "field_score": None,
                "weighted_score": 0.0,
                "is_missing": True,
            })
        else:
            weighted = field_score * weight
            breakdown.append({
                "field": field,
                "weight": weight,
                "original_weight": weight,
                "field_score": field_score,
                "weighted_score": round(weighted, 3),
                "is_missing": False,
            })
            total_weighted += weighted
            total_valid_weight += weight

    total_score = round(total_weighted / total_valid_weight * 100, 1) if total_valid_weight > 0 else 0.0
    return {"total_score": total_score, "breakdown": breakdown}


def apply_preferences(products: list[dict], preferences: dict) -> list[dict]:
    """在评分前对产品列表进行硬筛选过滤。"""
    if not preferences:
        return list(products)

    filtered = []
    wp_rank = {"无": 0, "IPX4": 1, "IP54": 2, "IPX5": 3, "IP55": 4, "IPX8": 5, "IP68": 5}
    min_wp = wp_rank.get(preferences.get("waterproof_min", "无"), 0)
    excluded_wearing = set(preferences.get("excluded_wearing_types", []) or [])
    required_wearing = preferences.get("wearing_type")

    for p in products:
        if required_wearing and p.get("wearing_type") != required_wearing:
            continue
        if p.get("wearing_type") in excluded_wearing:
            continue
        if preferences.get("reference_price_min") is not None:
            if p.get("reference_price") is None or p["reference_price"] < preferences["reference_price_min"]:
                continue
        if preferences.get("reference_price_max") is not None:
            if p.get("reference_price") is None or p["reference_price"] > preferences["reference_price_max"]:
                continue
        if preferences.get("anc_supported") is True and p.get("anc_supported") is not True:
            continue
        if preferences.get("low_latency") is True and p.get("low_latency") is not True:
            continue
        if preferences.get("dual_device") is True and p.get("dual_device") is not True:
            continue
        if preferences.get("waterproof_min") is not None:
            if wp_rank.get(p.get("waterproof", "无"), 0) < min_wp:
                continue
        filtered.append(p)
    return filtered


def _gen_reason(top_factors: list[str]) -> str:
    """生成推荐理由（优势）。"""
    reason_map = {
        "reference_price": "参考价格较低",
        "single_weight_g": "单耳重量较轻",
        "total_battery_h": "续航时间较长",
        "anc_supported": "支持主动降噪",
        "low_latency": "支持低延迟模式",
        "dual_device": "支持双设备连接",
        "bluetooth_version": "蓝牙版本较新",
        "wearing_type": "佩戴方式匹配",
        "waterproof": "防水等级匹配",
        "codec": "音频编码支持",
    }
    reasons = [reason_map[f] for f in top_factors if f in reason_map]
    return "、".join(reasons) if reasons else "综合表现均衡"


def _gen_limitations(breakdown: list[dict]) -> str:
    """生成产品不足/限制描述（客观事实）。阈值 0.3：得分低于 0.3 的数值/枚举字段算不足。"""
    limit_map = {
        "reference_price": "参考价格较高",
        "single_weight_g": "单耳重量较重",
        "total_battery_h": "续航时间较短",
        "anc_supported": "不支持主动降噪",
        "low_latency": "不支持低延迟模式",
        "dual_device": "不支持双设备连接",
        "bluetooth_version": "蓝牙版本较低",
        "wearing_type": "佩戴方式匹配度一般",
        "waterproof": "防水等级较低",
        "codec": "音频编码支持一般",
    }
    issues = []
    for b in breakdown:
        if b.get("is_missing") or b.get("field_score") is None:
            continue
        if b["field"] in ["anc_supported", "low_latency", "dual_device"] and b["field_score"] == 0:
            issues.append((0, b["field"]))
        elif b["field_score"] < 0.3:
            issues.append((b["field_score"], b["field"]))
    issues.sort(key=lambda x: x[0])
    top_issues = [f[1] for f in issues[:2]]
    limitations = [limit_map[f] for f in top_issues if f in limit_map]
    return "、".join(limitations) if limitations else "无明显短板"


def recommend_products(
    scenario: str,
    min_score: float = 0.0,
    top_k: Optional[int] = 3,
    sort_by: str = "score",
    prioritize_lightweight: bool = False,
    prioritize_long_battery: bool = False,
    preferences: Optional[dict] = None,
) -> dict:
    """
    耳机个性化推荐主接口（v4.2.1 验收修正版）。

    参数：
        scenario:           场景，daily / commuting / sports / gaming
        min_score:          最低分数门槛（0~100），默认 0
        top_k:              返回前 k 个结果，默认 3（返回 Top3），传 None 返回全部
        sort_by:            平局排序键：score / price / weight，默认 score
        prioritize_lightweight: 【评分调整】动态提权，重视轻便，默认 False
        prioritize_long_battery:  【评分调整】动态提权，重视长续航，默认 False
        preferences:        【硬筛选】过滤条件字典，默认无筛选
                           支持 key：reference_price_min/max, anc_supported,
                           low_latency, dual_device, wearing_type, waterproof_min,
                           excluded_wearing_types
    """
    try:
        scenario_norm = scenario.strip().lower()
        if scenario_norm not in VALID_SCENARIOS:
            raise ValueError(f"无效场景：{scenario}，有效场景：{VALID_SCENARIOS}")
        if not (0 <= min_score <= 100):
            raise ValueError(f"min_score 应在 0~100 之间，当前：{min_score}")
        if top_k is not None and (not isinstance(top_k, int) or top_k <= 0):
            raise ValueError("top_k 必须是大于 0 的整数")
        if preferences and "excluded_wearing_types" in preferences:
            if not isinstance(preferences["excluded_wearing_types"], list):
                raise ValueError("excluded_wearing_types 必须是列表类型")

        products = load_products()
        config = _load_config()
        base_weights = config["scenarios"][scenario_norm]
        adjusted_weights = _adjust_weights(base_weights, prioritize_lightweight, prioritize_long_battery)
        scenario_label = SCENARIO_LABELS[scenario_norm]

        products = apply_preferences(products, preferences)

        scored = []
        for p in products:
            res = score_product(p, adjusted_weights)
            if res["total_score"] >= min_score:
                scored.append({
                    "product": {
                        "product_id": p["product_id"],
                        "product_name": p["product_name"],
                        "model": p.get("model"),
                        "reference_price": p.get("reference_price"),
                        "brand": p.get("brand"),
                        "single_weight_g": p.get("single_weight_g"),
                        "source_url": p.get("source_url"),
                        "update_date": p.get("update_date"),
                        "remarks": p.get("remarks"),
                        "wearing_type": p.get("wearing_type"),
                        "anc_supported": p.get("anc_supported"),
                        "low_latency": p.get("low_latency"),
                        "dual_device": p.get("dual_device"),
                        "waterproof": p.get("waterproof"),
                        "total_battery_h": p.get("total_battery_h"),
                        "codec": p.get("codec"),
                    },
                    "score": res["total_score"],
                    "breakdown": res["breakdown"],
                })

        def _price(x):
            v = x["product"].get("reference_price")
            return float("inf") if v is None else float(v)

        def _weight(x):
            v = x["product"].get("single_weight_g")
            return float("inf") if v is None else float(v)

        def _pid(x):
            return x["product"].get("product_id", "") or ""

        if sort_by == "price":
            scored.sort(key=lambda x: (-x["score"], _price(x), _pid(x)))
        elif sort_by == "weight":
            scored.sort(key=lambda x: (-x["score"], _weight(x), _pid(x)))
        else:
            scored.sort(key=lambda x: (-x["score"], _price(x), _pid(x)))

        # Top-K截取前，先记录全部符合条件的产品数量
        matched_count = len(scored)

        if top_k is not None:
            scored = scored[:top_k]

        for item in scored:
            valid_factors = [
                b for b in item["breakdown"]
                if not b.get("is_missing")
                and b.get("weighted_score", 0) > 0
                and b.get("field_score") is not None
            ]
            top3 = sorted(valid_factors, key=lambda x: x["weighted_score"], reverse=True)[:3]
            item["top_factors"] = [f["field"] for f in top3]
            item["recommendation_reason"] = _gen_reason(item["top_factors"])
            item["limitations"] = _gen_limitations(item["breakdown"])

        weight_adjusted = prioritize_lightweight or prioritize_long_battery

        if scored:
            return {
                "success": True,
                "scenario": scenario_norm,
                "scenario_label": scenario_label,
                "total_count": matched_count,
                "returned_count": len(scored),
                "products": scored,
                "message": None,
                "weight_adjusted": weight_adjusted,
            }
        else:
            return {
                "success": True,
                "scenario": scenario_norm,
                "scenario_label": scenario_label,
                "total_count": 0,
                "products": [],
                "message": (
                    "暂无完全满足条件的产品。可尝试："
                    "① 放宽价格区间；② 取消 ANC/低延迟/双设备 等硬性要求；"
                    "③ 减少排除的佩戴方式；④ 更换佩戴方式偏好。"
                ),
                "weight_adjusted": weight_adjusted,
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _print_result(res: dict, verbose: bool = False):
    if not res["success"]:
        print(f"❌ 错误：{res['error']}")
        return
    print(f"\n=== {res['scenario_label']}场景推荐结果 ===")
    if res.get("weight_adjusted"):
        print("⚙️  已应用动态权重调整")
    if res["message"]:
        print(f"⚠️  {res['message']}\n")
        return
    returned_count = res.get("returned_count", len(res["products"]))
    print(
        f"共找到{res['total_count']}款符合条件的产品"
        f"（当前返回Top{returned_count}）：\n"
    )
    for i, item in enumerate(res["products"], 1):
        p = item["product"]
        print(f"{i}. {p['product_name']}（{p['product_id']}）")
        print(f"   价格：{p['reference_price']}元 | 重量：{p['single_weight_g']}g | 得分：{item['score']}")
        print(f"   ✅ 优势：{item['recommendation_reason']}")
        print(f"   ⚠️  不足：{item['limitations']}")
        if verbose:
            print("   评分明细：")
            for b in item["breakdown"]:
                if not b["is_missing"]:
                    print(f"     - {b['field']}: 权重{b['weight']}，得分{b['field_score']}，加权{b['weighted_score']}")
        print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="小米耳机个性化推荐 v4.2.1")
    parser.add_argument("scenario", nargs="?", default="daily", help="推荐场景：daily/commuting/sports/gaming")
    parser.add_argument("--min-score", type=float, default=0.0, help="最低得分 0~100")
    parser.add_argument("--top-k", type=int, default=3, help="返回前 k 个，默认 3")
    parser.add_argument("--sort-by", choices=["score", "price", "weight"], default="score", help="排序方式")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示评分明细")
    parser.add_argument("--price-min", type=float, default=None, help="最低价格")
    parser.add_argument("--price-max", type=float, default=None, help="最高价格")
    parser.add_argument("--anc", action="store_true", help="必须支持 ANC")
    parser.add_argument("--low-latency", action="store_true", help="必须支持低延迟")
    parser.add_argument("--dual-device", action="store_true", help="必须支持双设备连接")
    parser.add_argument("--wearing-type", type=str, default=None, help="必须匹配佩戴方式")
    parser.add_argument("--waterproof-min", type=str, default=None, help="最低防水等级")
    parser.add_argument(
        "--exclude-wearing", action="append", default=[],
        help="排除佩戴方式，可多次传，如 --exclude-wearing 入耳式"
    )
    parser.add_argument("--prioritize-lightweight", action="store_true", help="动态权重：重视轻便")
    parser.add_argument("--prioritize-long-battery", action="store_true", help="动态权重：重视长续航")
    args = parser.parse_args()

    prefs = {}
    if args.price_min is not None:
        prefs["reference_price_min"] = args.price_min
    if args.price_max is not None:
        prefs["reference_price_max"] = args.price_max
    if args.anc:
        prefs["anc_supported"] = True
    if args.low_latency:
        prefs["low_latency"] = True
    if args.dual_device:
        prefs["dual_device"] = True
    if args.wearing_type:
        prefs["wearing_type"] = args.wearing_type
    if args.waterproof_min:
        prefs["waterproof_min"] = args.waterproof_min
    if args.exclude_wearing:
        prefs["excluded_wearing_types"] = args.exclude_wearing

    result = recommend_products(
        scenario=args.scenario,
        min_score=args.min_score,
        top_k=args.top_k,
        sort_by=args.sort_by,
        prioritize_lightweight=args.prioritize_lightweight,
        prioritize_long_battery=args.prioritize_long_battery,
        preferences=prefs if prefs else None,
    )
    _print_result(result, verbose=args.verbose)
