
from __future__ import annotations

from typing import Any

from backend.scripts.filter_recommend import filter_recommend
from backend.utils.api import ApiError

VALID_SCENARIOS = {"daily", "commuting", "sports", "gaming"}
VALID_PREFERENCES = {"lightweight", "long_battery"}
VALID_MUST_HAVE = {"anc", "waterproof", "low_latency", "dual_device"}


def _require_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ApiError(
            f"{field_name} 必须是字符串数组",
            "INVALID_REQUEST",
            400,
        )
    return value


def _split_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    for separator in ("、", "；", ";"):
        text = text.replace(separator, "|")
    return [part.strip() for part in text.split("|") if part.strip()]


def recommend_for_request(payload: dict) -> dict:
    scenario = payload.get("scenario")
    if not isinstance(scenario, str) or scenario not in VALID_SCENARIOS:
        raise ApiError(
            f"scenario 必须是以下之一：{sorted(VALID_SCENARIOS)}",
            "INVALID_REQUEST",
            400,
        )

    budget_max = payload.get("budget_max")
    if budget_max is not None:
        if isinstance(budget_max, bool) or not isinstance(budget_max, (int, float)):
            raise ApiError("budget_max 必须是数字或 null", "INVALID_REQUEST", 400)
        if budget_max < 0:
            raise ApiError("budget_max 不能小于0", "INVALID_REQUEST", 400)

    preferences = _require_string_list(payload.get("preferences"), "preferences")
    must_have = _require_string_list(payload.get("must_have"), "must_have")
    excluded_wearing_types = _require_string_list(
        payload.get("excluded_wearing_types"),
        "excluded_wearing_types",
    )

    unknown_preferences = sorted(set(preferences) - VALID_PREFERENCES)
    if unknown_preferences:
        raise ApiError(
            f"不支持的 preferences：{unknown_preferences}",
            "INVALID_REQUEST",
            400,
        )

    unknown_must_have = sorted(set(must_have) - VALID_MUST_HAVE)
    if unknown_must_have:
        raise ApiError(
            f"不支持的 must_have：{unknown_must_have}",
            "INVALID_REQUEST",
            400,
        )

    top_k = payload.get("top_k", 3)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 3:
        raise ApiError("top_k 必须是1到3之间的整数", "INVALID_REQUEST", 400)

    result = filter_recommend(
        scenario=scenario,
        top_k=top_k,
        reference_price_max=budget_max,
        anc_supported="anc" in must_have,
        low_latency="low_latency" in must_have,
        dual_device="dual_device" in must_have,
        waterproof_min="IPX4" if "waterproof" in must_have else None,
        excluded_wearing_types=excluded_wearing_types or None,
        prioritize_lightweight="lightweight" in preferences,
        prioritize_long_battery="long_battery" in preferences,
    )

    if not result.get("success"):
        message = result.get("error", "推荐服务执行失败")
        raise ApiError(message, "INVALID_REQUEST", 400)

    products = result.get("products", [])
    if not products:
        raise ApiError(
            "当前产品库中没有同时满足全部必须条件的产品",
            "NO_MATCHED_PRODUCT",
            404,
            suggestions=[
                "提高预算上限",
                "减少必须条件",
                "允许更多佩戴方式",
            ],
        )

    recommendations = []
    for rank, item in enumerate(products, start=1):
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

        recommendations.append(
            {
                "rank": rank,
                "product_id": product.get("product_id"),
                "product_name": product.get("product_name"),
                "model": product.get("model"),
                "brand": product.get("brand"),
                "reference_price": product.get("reference_price"),
                "wearing_type": product.get("wearing_type"),
                "anc_supported": product.get("anc_supported"),
                "low_latency": product.get("low_latency"),
                "dual_device": product.get("dual_device"),
                "waterproof": product.get("waterproof"),
                "total_battery_h": product.get("total_battery_h"),
                "single_weight_g": product.get("single_weight_g"),
                "source_url": product.get("source_url"),
                "score": item.get("score"),
                "score_details": score_details,
                "reasons": _split_text(item.get("recommendation_reason")),
                "limitations": _split_text(item.get("limitations")),
                "missing_fields": missing_fields,
            }
        )

    return {
        "request_summary": {
            "budget_max": budget_max,
            "scenario": scenario,
            "preferences": preferences,
            "must_have": must_have,
            "excluded_wearing_types": excluded_wearing_types,
            "top_k": top_k,
        },
        "recommendations": recommendations,
    }
