import os
import sys
from typing import Optional

# ========== 路径配置（兼容本地 v4 / 仓库 backend/scripts 两种部署）==========
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 本地 v4 平级：脚本目录就是 base；仓库 backend/scripts：脚本同目录就是 recommend_products.py
sys.path.insert(0, SCRIPT_DIR)

# 直接导入任务14的接口，不修改任务14任何代码
try:
    from .recommend_products import recommend_products
except ImportError:
    from recommend_products import recommend_products

# ========== 场景自动匹配规则（组长要求）==========
# 优先级：低延迟(游戏) > 高防水(运动) > ANC(通勤) > 默认日常
WATERPROOF_RANK = {"无": 0, "IPX4": 1, "IP54": 2, "IPX5": 3, "IP55": 4, "IPX8": 5, "IP68": 5}
SPORTS_WATERPROOF_THRESHOLD = 3  # ≥IPX5自动匹配运动场景


def _auto_match_scenario(preferences: dict) -> str:
    """根据用户筛选条件自动匹配最合适的场景，用户手动指定场景时不触发"""
    if preferences.get("low_latency") is True:
        return "gaming"
    wp_min = preferences.get("waterproof_min")
    if wp_min and WATERPROOF_RANK.get(wp_min, 0) >= SPORTS_WATERPROOF_THRESHOLD:
        return "sports"
    if preferences.get("anc_supported") is True:
        return "commuting"
    return "daily"


def filter_recommend(
    scenario: Optional[str] = None,
    min_score: float = 0.0,
    top_k: int = 3,
    sort_by: str = "score",
    prioritize_lightweight: bool = False,
    prioritize_long_battery: bool = False,
    reference_price_min: Optional[float] = None,
    reference_price_max: Optional[float] = None,
    anc_supported: bool = False,
    low_latency: bool = False,
    dual_device: bool = False,
    wearing_type: Optional[str] = None,
    waterproof_min: Optional[str] = None,
    excluded_wearing_types: Optional[list] = None,
) -> dict:
    """
    任务15：用户筛选推荐主接口
    完全基于任务14的recommend_products实现，不修改任何评分逻辑

    :param scenario: 手动指定场景，不填自动匹配
    :param min_score: 最低分数门槛 0-100
    :param top_k: 返回前k个结果，默认3
    :param sort_by: 排序方式 score/price/weight
    :param prioritize_lightweight: 优先轻便（动态提权）
    :param prioritize_long_battery: 优先长续航（动态提权）
    :param reference_price_min: 最低价格
    :param reference_price_max: 最高价格
    :param anc_supported: 必须支持ANC
    :param low_latency: 必须支持低延迟
    :param dual_device: 必须支持双设备
    :param wearing_type: 必须匹配佩戴方式
    :param waterproof_min: 最低防水等级
    :param excluded_wearing_types: 排除的佩戴方式列表
    """
    try:
        # 参数校验
        if not (0 <= min_score <= 100):
            raise ValueError(f"min_score应在0~100之间，当前：{min_score}")
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k必须是大于0的整数")
        if sort_by not in ["score", "price", "weight"]:
            raise ValueError(f"sort_by仅支持score/price/weight，当前：{sort_by}")
        if excluded_wearing_types is not None and not isinstance(excluded_wearing_types, list):
            raise ValueError("excluded_wearing_types必须是列表类型")

        # 组装任务14要求的preferences字典
        preferences = {}
        if reference_price_min is not None:
            preferences["reference_price_min"] = reference_price_min
        if reference_price_max is not None:
            preferences["reference_price_max"] = reference_price_max
        if anc_supported:
            preferences["anc_supported"] = True
        if low_latency:
            preferences["low_latency"] = True
        if dual_device:
            preferences["dual_device"] = True
        if wearing_type is not None:
            preferences["wearing_type"] = wearing_type
        if waterproof_min is not None:
            if waterproof_min not in WATERPROOF_RANK:
                raise ValueError(f"防水等级不合法，支持：{list(WATERPROOF_RANK.keys())}")
            preferences["waterproof_min"] = waterproof_min
        if excluded_wearing_types:
            preferences["excluded_wearing_types"] = excluded_wearing_types

        # 自动匹配场景（用户没手动指定时才触发）
        target_scenario = scenario if scenario is not None else _auto_match_scenario(preferences)

        # 调用任务14的推荐接口，所有参数直接透传
        result = recommend_products(
            scenario=target_scenario,
            min_score=min_score,
            top_k=top_k,
            sort_by=sort_by,
            prioritize_lightweight=prioritize_lightweight,
            prioritize_long_battery=prioritize_long_battery,
            preferences=preferences if preferences else None,
        )

        # 补充场景匹配信息，前端可展示
        result["auto_scenario"] = scenario is None
        result["matched_scenario"] = target_scenario
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def _print_result(res: dict, verbose: bool = False):
    """打印结果，和任务14格式保持一致"""
    if not res["success"]:
        print(f"❌ 错误：{res['error']}")
        return
    auto_tag = "（自动匹配）" if res.get("auto_scenario") else ""
    print(f"\n=== 筛选推荐结果 {auto_tag} ===")
    print(f"匹配场景：{res['scenario_label']}")
    if res.get("weight_adjusted"):
        print("⚙️  已应用动态权重调整")
    if res["message"]:
        print(f"⚠️  {res['message']}\n")
        return
    print(f"共找到{res['total_count']}款符合条件的产品（返回Top{len(res['products'])}）：\n")
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
    parser = argparse.ArgumentParser(description="任务15：用户筛选推荐工具")
    parser.add_argument("--scenario", type=str, default=None,
                        help="手动指定场景daily/commuting/sports/gaming，不填自动匹配")
    parser.add_argument("--min-score", type=float, default=0.0, help="最低得分0-100")
    parser.add_argument("--top-k", type=int, default=3, help="返回前k个，默认3")
    parser.add_argument("--sort-by", choices=["score", "price", "weight"], default="score",
                        help="排序方式")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示评分明细")
    parser.add_argument("--price-min", type=float, default=None, help="最低价格")
    parser.add_argument("--price-max", type=float, default=None, help="最高价格")
    parser.add_argument("--anc", action="store_true", help="必须支持ANC")
    parser.add_argument("--low-latency", action="store_true", help="必须支持低延迟")
    parser.add_argument("--dual-device", action="store_true", help="必须支持双设备连接")
    parser.add_argument("--wearing-type", type=str, default=None, help="必须匹配佩戴方式")
    parser.add_argument("--waterproof-min", type=str, default=None, help="最低防水等级")
    parser.add_argument("--exclude-wearing", action="append", default=[],
                        help="排除佩戴方式，可多次传")
    parser.add_argument("--prioritize-lightweight", action="store_true", help="优先轻便")
    parser.add_argument("--prioritize-long-battery", action="store_true", help="优先长续航")
    args = parser.parse_args()

    result = filter_recommend(
        scenario=args.scenario,
        min_score=args.min_score,
        top_k=args.top_k,
        sort_by=args.sort_by,
        prioritize_lightweight=args.prioritize_lightweight,
        prioritize_long_battery=args.prioritize_long_battery,
        reference_price_min=args.price_min,
        reference_price_max=args.price_max,
        anc_supported=args.anc,
        low_latency=args.low_latency,
        dual_device=args.dual_device,
        wearing_type=args.wearing_type,
        waterproof_min=args.waterproof_min,
        excluded_wearing_types=args.exclude_wearing if args.exclude_wearing else None,
    )
    _print_result(result, verbose=args.verbose)