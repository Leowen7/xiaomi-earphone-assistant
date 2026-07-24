from __future__ import annotations

from typing import Any

from backend.recommendation.recommend_wearables import (
    recommend as recommend_wearables,
)
from backend.scripts.filter_recommend import filter_recommend
from backend.services.product_service import load_wearables
from backend.utils.api import ApiError


CATEGORY_ALIASES = {
    "earphone": "earphone",
    "earphones": "earphone",
    "headphone": "earphone",
    "smart_band": "smart_band",
    "smartband": "smart_band",
    "band": "smart_band",
    "smart_watch": "smart_watch",
    "smartwatch": "smart_watch",
    "watch": "smart_watch",
}

VALID_EARPHONE_SCENARIOS = {
    "daily",
    "commuting",
    "sports",
    "gaming",
}

VALID_EARPHONE_PREFERENCES = {
    "lightweight",
    "long_battery",
}

VALID_EARPHONE_MUST_HAVE = {
    "anc",
    "waterproof",
    "low_latency",
    "dual_device",
}

FRONTEND_SCENARIO_MAP = {
    "通勤听歌": "commuting",
    "办公降噪": "commuting",
    "运动健身": "sports",
    "游戏电竞": "gaming",
    "日常休闲": "daily",
}

FRONTEND_EARPHONE_BUDGET_MAX = {
    "200元以内": 200,
    "200-500元": 500,
    "500-1000元": 1000,
    "1000元以上": None,
}

WEARABLE_FEATURE_FILTERS = {
    "NFC": "nfc_support=true",
    "独立GPS": "positioning_type=built_in_gnss",
    "独立GNSS": "positioning_type=built_in_gnss",
    "蓝牙通话": "bluetooth_call=true",
    "血氧监测": "blood_oxygen_monitoring=true",
}

WEARABLE_FEATURE_DEMANDS = {
    "NFC": "需要NFC",
    "独立GPS": "需要独立GNSS定位",
    "独立GNSS": "需要独立GNSS定位",
    "蓝牙通话": "需要蓝牙通话",
    "血氧监测": "需要血氧监测",
    "GMS兼容": "需要兼容GMS并优先考虑Wear OS",
}

WEARABLE_DEVICE_ALIASES = {
    "全部": "android_gms",
    "all": "android_gms",
    "Android": "android",
    "android": "android",
    "Android(GMS)": "android_gms",
    "android_gms": "android_gms",
    "GMS": "android_gms",
    "iOS": "iOS",
    "ios": "iOS",
    "iPhone": "iOS",
    "android_no_gms": "android_no_gms",
    "Android(无GMS)": "android_no_gms",
}


def _normalize_category(value: Any) -> str:
    if value is None:
        return "earphone"

    normalized = (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    category = CATEGORY_ALIASES.get(normalized)
    if category is None:
        raise ApiError(
            "category仅支持earphone、smart_band、smart_watch",
            "INVALID_REQUEST",
            400,
        )

    return category


def _require_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        return [value] if value.strip() else []

    if not isinstance(value, list):
        raise ApiError(
            f"{field_name} 必须是字符串数组",
            "INVALID_REQUEST",
            400,
        )

    if any(not isinstance(item, str) for item in value):
        raise ApiError(
            f"{field_name} 必须是字符串数组",
            "INVALID_REQUEST",
            400,
        )

    return [
        item.strip()
        for item in value
        if item.strip()
    ]


def _split_text(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    text = str(value).strip()
    if not text:
        return []

    for separator in ("、", "；", ";", "\n"):
        text = text.replace(separator, "|")

    return [
        part.strip()
        for part in text.split("|")
        if part.strip()
    ]


def _get_frontend_preferences(payload: dict) -> dict:
    value = payload.get("preferences")

    if isinstance(value, dict):
        return value

    filters = payload.get("filters")
    if isinstance(filters, dict):
        return filters

    return {}


def _get_top_k(payload: dict) -> int:
    top_k = payload.get("top_k", 3)

    if (
        isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or not 1 <= top_k <= 3
    ):
        raise ApiError(
            "top_k 必须是1到3之间的整数",
            "INVALID_REQUEST",
            400,
        )

    return top_k


def _frontend_earphone_request(payload: dict) -> dict:
    preferences = _get_frontend_preferences(payload)

    scenes = _require_string_list(
        preferences.get("scene"),
        "preferences.scene",
    )

    scenario = "daily"
    for scene in scenes:
        mapped = FRONTEND_SCENARIO_MAP.get(scene)
        if mapped is not None:
            scenario = mapped
            break

    budget_label = preferences.get("budget")
    budget_max = FRONTEND_EARPHONE_BUDGET_MAX.get(
        str(budget_label).strip()
        if budget_label is not None
        else None
    )

    wear = preferences.get("wear")
    excluded_wearing_types: list[str] = []

    if wear == "入耳式":
        excluded_wearing_types = ["半入耳式", "头戴式"]
    elif wear == "半入耳式":
        excluded_wearing_types = ["入耳式", "头戴式"]
    elif wear == "头戴式":
        excluded_wearing_types = ["入耳式", "半入耳式"]

    return {
        "scenario": scenario,
        "budget_max": budget_max,
        "preferences": [],
        "must_have": [],
        "excluded_wearing_types": excluded_wearing_types,
        "top_k": _get_top_k(payload),
        "frontend_preferences": preferences,
    }


def _legacy_earphone_request(payload: dict) -> dict:
    scenario = payload.get("scenario", "daily")

    if (
        not isinstance(scenario, str)
        or scenario not in VALID_EARPHONE_SCENARIOS
    ):
        raise ApiError(
            (
                "scenario 必须是以下之一："
                f"{sorted(VALID_EARPHONE_SCENARIOS)}"
            ),
            "INVALID_REQUEST",
            400,
        )

    budget_max = payload.get("budget_max")
    if budget_max is not None:
        if (
            isinstance(budget_max, bool)
            or not isinstance(budget_max, (int, float))
        ):
            raise ApiError(
                "budget_max 必须是数字或 null",
                "INVALID_REQUEST",
                400,
            )

        if budget_max < 0:
            raise ApiError(
                "budget_max 不能小于0",
                "INVALID_REQUEST",
                400,
            )

    preferences = _require_string_list(
        payload.get("preferences"),
        "preferences",
    )
    must_have = _require_string_list(
        payload.get("must_have"),
        "must_have",
    )
    excluded_wearing_types = _require_string_list(
        payload.get("excluded_wearing_types"),
        "excluded_wearing_types",
    )

    unknown_preferences = sorted(
        set(preferences) - VALID_EARPHONE_PREFERENCES
    )
    if unknown_preferences:
        raise ApiError(
            f"不支持的 preferences：{unknown_preferences}",
            "INVALID_REQUEST",
            400,
        )

    unknown_must_have = sorted(
        set(must_have) - VALID_EARPHONE_MUST_HAVE
    )
    if unknown_must_have:
        raise ApiError(
            f"不支持的 must_have：{unknown_must_have}",
            "INVALID_REQUEST",
            400,
        )

    return {
        "scenario": scenario,
        "budget_max": budget_max,
        "preferences": preferences,
        "must_have": must_have,
        "excluded_wearing_types": excluded_wearing_types,
        "top_k": _get_top_k(payload),
        "frontend_preferences": None,
    }


def _recommend_earphones(payload: dict) -> dict:
    if isinstance(payload.get("preferences"), dict) or isinstance(
        payload.get("filters"),
        dict,
    ):
        request_data = _frontend_earphone_request(payload)
    else:
        request_data = _legacy_earphone_request(payload)

    scenario = request_data["scenario"]
    budget_max = request_data["budget_max"]
    preferences = request_data["preferences"]
    must_have = request_data["must_have"]
    excluded_wearing_types = request_data[
        "excluded_wearing_types"
    ]
    top_k = request_data["top_k"]

    result = filter_recommend(
        scenario=scenario,
        top_k=top_k,
        reference_price_max=budget_max,
        anc_supported="anc" in must_have,
        low_latency="low_latency" in must_have,
        dual_device="dual_device" in must_have,
        waterproof_min=(
            "IPX4"
            if "waterproof" in must_have
            else None
        ),
        excluded_wearing_types=(
            excluded_wearing_types or None
        ),
        prioritize_lightweight=(
            "lightweight" in preferences
        ),
        prioritize_long_battery=(
            "long_battery" in preferences
        ),
    )

    if not result.get("success"):
        raise ApiError(
            result.get("error", "耳机推荐服务执行失败"),
            "INVALID_REQUEST",
            400,
        )

    products = result.get("products", [])
    if not products:
        raise ApiError(
            "当前耳机库中没有同时满足条件的产品",
            "NO_MATCHED_PRODUCT",
            404,
            suggestions=[
                "提高预算上限",
                "减少必须条件",
                "允许更多佩戴方式",
            ],
        )

    recommendations = []

    for rank, item in enumerate(products[:top_k], start=1):
        product = item.get("product", {})
        breakdown = item.get("breakdown", [])

        score_details = {}
        missing_fields = []

        for detail in breakdown:
            field = detail.get("field")
            if not field:
                continue

            if detail.get("is_missing"):
                score_details[field] = None
                missing_fields.append(field)
            else:
                field_score = detail.get("field_score")
                score_details[field] = (
                    round(float(field_score) * 100, 1)
                    if field_score is not None
                    else None
                )

        source_url = product.get("source_url")
        sources = (
            [
                {
                    "source_url": source_url,
                    "source_type": "official",
                }
            ]
            if source_url
            else []
        )

        reasons = _split_text(
            item.get("recommendation_reason")
        )

        recommendations.append(
            {
                "rank": rank,
                "product_id": product.get("product_id"),
                "product_name": product.get("product_name"),
                "model": product.get("model"),
                "brand": product.get("brand"),
                "category": "earphone",
                "price": product.get("reference_price"),
                "official_price": product.get(
                    "reference_price"
                ),
                "reference_price": product.get(
                    "reference_price"
                ),
                "currency": "CNY",
                "wearing_type": product.get("wearing_type"),
                "anc_supported": product.get(
                    "anc_supported"
                ),
                "low_latency": product.get("low_latency"),
                "dual_device": product.get("dual_device"),
                "waterproof": product.get("waterproof"),
                "total_battery_h": product.get(
                    "total_battery_h"
                ),
                "single_weight_g": product.get(
                    "single_weight_g"
                ),
                "source_url": source_url,
                "official_url": source_url,
                "sources": sources,
                "source_records": sources,
                "score": item.get("score"),
                "score_details": score_details,
                "reasons": reasons,
                "match_reasons": reasons,
                "limitations": _split_text(
                    item.get("limitations")
                ),
                "missing_fields": missing_fields,
            }
        )

    return {
        "category": "earphone",
        "request_summary": {
            "scenario": scenario,
            "budget_max": budget_max,
            "preferences": preferences,
            "must_have": must_have,
            "excluded_wearing_types": (
                excluded_wearing_types
            ),
            "frontend_preferences": request_data[
                "frontend_preferences"
            ],
            "top_k": top_k,
        },
        "recommendations": recommendations,
    }


def _normalize_wearable_device(
    preferences: dict,
    payload: dict,
) -> str:
    direct_value = payload.get("user_device")

    if direct_value is not None:
        direct_text = str(direct_value).strip()
        return WEARABLE_DEVICE_ALIASES.get(
            direct_text,
            direct_text,
        )

    os_value = preferences.get("os")
    if os_value is None:
        return "android_gms"

    os_text = str(os_value).strip()
    return WEARABLE_DEVICE_ALIASES.get(
        os_text,
        "android_gms",
    )


def _normalize_wearable_features(
    preferences: dict,
) -> list[str]:
    return _require_string_list(
        preferences.get("feature"),
        "preferences.feature",
    )


def _build_wearable_request(
    category: str,
    payload: dict,
) -> dict:
    preferences = _get_frontend_preferences(payload)
    features = _normalize_wearable_features(preferences)

    if "eSIM" in features:
        raise ApiError(
            (
                "当前冻结数据没有可验证的eSIM字段，"
                "不能据此给出可靠推荐"
            ),
            "NO_MATCHED_PRODUCT",
            404,
            suggestions=[
                "取消eSIM硬性条件",
                "改选蓝牙通话",
                "查看官方产品页面确认蜂窝网络版本",
            ],
        )

    hard_filters = [
        f"product_category={category}"
    ]
    demand_parts = [
        (
            "只推荐智能手环"
            if category == "smart_band"
            else "只推荐智能手表"
        )
    ]

    for feature in features:
        expression = WEARABLE_FEATURE_FILTERS.get(feature)
        if expression and expression not in hard_filters:
            hard_filters.append(expression)

        demand = WEARABLE_FEATURE_DEMANDS.get(feature)
        if demand:
            demand_parts.append(demand)

    user_device = _normalize_wearable_device(
        preferences,
        payload,
    )

    if "GMS兼容" in features:
        user_device = "android_gms"
        hard_filters.append(
            "product_summary contains Wear OS"
        )

    explicit_hard_filters = payload.get("hard_filters")
    if explicit_hard_filters is None:
        explicit_hard_filters = payload.get("hard_filter")

    for expression in _require_string_list(
        explicit_hard_filters,
        "hard_filters",
    ):
        if expression not in hard_filters:
            hard_filters.append(expression)

    explicit_demand = payload.get("user_demand")
    if explicit_demand:
        demand_parts.append(str(explicit_demand).strip())

    budget_label = preferences.get("budget")
    warnings = []

    max_budget = payload.get("max_budget")
    currency = payload.get("currency")

    if max_budget is not None:
        if (
            isinstance(max_budget, bool)
            or not isinstance(max_budget, (int, float))
            or max_budget < 0
        ):
            raise ApiError(
                "max_budget 必须是非负数字或 null",
                "INVALID_REQUEST",
                400,
            )

    if max_budget is None and budget_label:
        warnings.append(
            (
                "前端预算标签使用人民币，"
                "穿戴设备冻结价格币种为AUD，"
                "本次未将该标签作为价格硬过滤"
            )
        )
        demand_parts.append(
            f"预算偏好为{budget_label}"
        )

    return {
        "preferences": preferences,
        "features": features,
        "user_device": user_device,
        "hard_filters": hard_filters,
        "user_demand": "，".join(
            part
            for part in demand_parts
            if part
        ),
        "max_budget": max_budget,
        "currency": currency,
        "warnings": warnings,
        "top_k": _get_top_k(payload),
    }


def _wearable_product_index() -> dict[str, dict]:
    return {
        product.get("product_id"): product
        for product in load_wearables()
        if product.get("product_id")
    }


def _recommend_wearable_category(
    category: str,
    payload: dict,
) -> dict:
    request_data = _build_wearable_request(
        category,
        payload,
    )

    result = recommend_wearables(
        user_demand=request_data["user_demand"],
        user_device=request_data["user_device"],
        hard_filters=request_data["hard_filters"],
        max_budget=request_data["max_budget"],
        currency=request_data["currency"],
    )

    if not result.get("success"):
        raise ApiError(
            result.get("error", "穿戴设备推荐服务执行失败"),
            "INVALID_REQUEST",
            400,
        )

    raw_recommendations = result.get(
        "recommendations",
        [],
    )

    if not raw_recommendations:
        suggestions = [
            "减少必须功能",
            "切换手机系统兼容条件",
            "查看近似匹配产品",
        ]

        near_match = result.get("near_match")
        if isinstance(near_match, dict):
            near_id = near_match.get("product_id")
            if near_id:
                suggestions.insert(
                    0,
                    f"可查看近似匹配产品 {near_id}",
                )

        raise ApiError(
            "当前穿戴设备库中没有完全满足条件的产品",
            "NO_MATCHED_PRODUCT",
            404,
            suggestions=suggestions,
        )

    product_index = _wearable_product_index()
    recommendations = []

    for position, item in enumerate(
        raw_recommendations[
            : request_data["top_k"]
        ],
        start=1,
    ):
        product_id = item.get("product_id")
        product = product_index.get(product_id, {})

        source_records = product.get(
            "source_records",
            [],
        )
        official_url = product.get("official_url")

        if not source_records and official_url:
            source_records = [
                {
                    "source_url": official_url,
                    "source_type": "product_page",
                    "source_region": product.get(
                        "source_region"
                    ),
                }
            ]

        reasons = _split_text(
            item.get("match_reasons")
        )

        recommendations.append(
            {
                "rank": item.get("rank", position),
                "product_id": product_id,
                "product_name": (
                    item.get("product_name")
                    or product.get("product_name")
                ),
                "brand": product.get("brand"),
                "category": category,
                "product_category": category,
                "series": product.get("series"),
                "variant": product.get("variant"),
                "price": item.get(
                    "official_price",
                    product.get("official_price"),
                ),
                "official_price": item.get(
                    "official_price",
                    product.get("official_price"),
                ),
                "currency": (
                    item.get("currency")
                    or product.get("currency")
                ),
                "score": None,
                "raw_score": item.get("score"),
                "group_score": item.get(
                    "group_score"
                ),
                "scene_score": item.get(
                    "scene_score"
                ),
                "reasons": reasons,
                "match_reasons": reasons,
                "summary": product.get(
                    "product_summary"
                ),
                "product_summary": product.get(
                    "product_summary"
                ),
                "official_url": official_url,
                "source_url": official_url,
                "sources": source_records,
                "source_records": source_records,
                "wearable_specs": product.get(
                    "wearable_specs"
                ),
            }
        )

    return {
        "category": category,
        "request_summary": {
            "preferences": request_data[
                "preferences"
            ],
            "features": request_data["features"],
            "user_demand": request_data[
                "user_demand"
            ],
            "user_device": request_data[
                "user_device"
            ],
            "hard_filters": request_data[
                "hard_filters"
            ],
            "max_budget": request_data[
                "max_budget"
            ],
            "currency": request_data["currency"],
            "top_k": request_data["top_k"],
            "warnings": request_data["warnings"],
        },
        "recommendations": recommendations,
        "expected_candidates": result.get(
            "expected_candidates",
            [],
        ),
        "near_match": result.get("near_match"),
    }


def recommend_for_request(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ApiError(
            "请求体必须是JSON对象",
            "INVALID_REQUEST",
            400,
        )

    category = _normalize_category(
        payload.get("category")
        or payload.get("product_type")
    )

    if category == "earphone":
        return _recommend_earphones(payload)

    return _recommend_wearable_category(
        category,
        payload,
    )
