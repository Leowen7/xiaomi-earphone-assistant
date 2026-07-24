from __future__ import annotations

from numbers import Real
from typing import Any

from backend.scripts.compare_products import (
    compare_products as compare_earphone_products,
)
from backend.scripts.compare_wearables import (
    compare_products as compare_wearable_products,
)
from backend.utils.api import ApiError


LOWER_IS_BETTER = {
    # 耳机
    "reference_price": "价格更低",
    "single_weight_g": "单耳重量更轻",
    # 手环 / 手表
    "official_price": "价格更低",
    "weight_g": "重量更轻",
    "charging_time_minutes": "充电时间更短",
}

HIGHER_IS_BETTER = {
    # 耳机
    "single_battery_h": "单次续航更长",
    "total_battery_h": "总续航更长",
    "anc_depth_db": "降噪深度更高",
    "bluetooth_version": "蓝牙版本更高",
    # 手环 / 手表
    "display_size_in": "屏幕尺寸更大",
    "max_brightness_nits": "屏幕亮度更高",
    "battery_life_typical_days": "典型续航更长",
    "battery_life_heavy_days": "重度使用续航更长",
    "sports_modes_count": "运动模式更多",
}
COMPARISON_WORDS = {
    "reference_price": "更低",
    "official_price": "更低",
    "single_weight_g": "更轻",
    "weight_g": "更轻",
    "charging_time_minutes": "更短",
    "single_battery_h": "更长",
    "total_battery_h": "更长",
    "anc_depth_db": "更高",
    "bluetooth_version": "更新",
    "display_size_in": "更大",
    "max_brightness_nits": "更高",
    "battery_life_typical_days": "更长",
    "battery_life_heavy_days": "更长",
    "sports_modes_count": "更多",
}

BOOLEAN_ADVANTAGES = {
    # 耳机
    "anc_supported": "支持主动降噪",
    "dual_device": "支持双设备连接",
    "low_latency": "支持低延迟模式",
    # 手环 / 手表
    "bluetooth_call": "支持蓝牙通话",
    "nfc_support": "支持NFC",
    "heart_rate_monitoring": "支持心率监测",
    "blood_oxygen_monitoring": "支持血氧监测",
    "sleep_monitoring": "支持睡眠监测",
    "stress_monitoring": "支持压力监测",
}

WATERPROOF_RANK = {
    None: -1,
    "无": 0,
    "IPX4": 1,
    "IP54": 2,
    "IPX5": 3,
    "IP55": 4,
    "5ATM": 5,
    "IPX8": 6,
    "IP68": 6,
    "10ATM": 7,
}

POSITIONING_RANK = {
    None: -1,
    "connected_phone": 0,
    "built_in_gnss": 1,
}


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _append_unique(target: list[str], text: str) -> None:
    if text and text not in target:
        target.append(text)


def _detect_category(product_id: str) -> str | None:
    """根据产品 ID 判断产品类别。"""
    normalized = product_id.strip().upper()

    if normalized.startswith("EAR") and normalized[3:].isdigit():
        return "earphone"

    if normalized.startswith("B") and normalized[1:].isdigit():
        return "smart_band"

    if normalized.startswith("W") and normalized[1:].isdigit():
        return "smart_watch"

    return None


def _display_value(item: dict, key: str, raw_value: Any) -> str:
    """统一空值展示，避免前端出现 null、None 或不同占位词。"""
    if raw_value is None:
        return "暂无官方信息"

    display = item.get(key)
    if display is None or display == "":
        return str(raw_value)

    return str(display)


def _build_conclusion(item: dict, pid_a: str, pid_b: str) -> str:
    value_a = item.get("value_a")
    value_b = item.get("value_b")
    display_a = _display_value(item, "display_a", value_a)
    display_b = _display_value(item, "display_b", value_b)
    label = item.get("label", item.get("field", "参数"))

    if value_a is None and value_b is None:
        return f"两款产品的{label}均暂无官方信息"

    if value_a is None:
        return f"{pid_a} 的{label}暂无官方信息，{pid_b} 为{display_b}"

    if value_b is None:
        return f"{pid_b} 的{label}暂无官方信息，{pid_a} 为{display_a}"

    if value_a == value_b:
        return f"两款产品的{label}相同，均为{display_a}"

    field = item.get("field")

    if (
        field in LOWER_IS_BETTER
        and _is_number(value_a)
        and _is_number(value_b)
    ):
        better = pid_a if value_a < value_b else pid_b
        gap = abs(float(value_a) - float(value_b))
        gap_text = str(int(gap)) if gap.is_integer() else str(round(gap, 2))
        unit = item.get("unit") or ""
        comparison_word = COMPARISON_WORDS.get(field, "更有优势")
        return f"{better} 的{label}{comparison_word}，差值为{gap_text}{unit}"

    if (
        field in HIGHER_IS_BETTER
        and _is_number(value_a)
        and _is_number(value_b)
    ):
        better = pid_a if value_a > value_b else pid_b
        gap = abs(float(value_a) - float(value_b))
        gap_text = str(int(gap)) if gap.is_integer() else str(round(gap, 2))
        unit = item.get("unit") or ""
        comparison_word = COMPARISON_WORDS.get(field, "更有优势")
        return f"{better} 的{label}{comparison_word}，差值为{gap_text}{unit}"     

    if field in BOOLEAN_ADVANTAGES:
        if value_a is True and value_b is not True:
            return f"{pid_a} {BOOLEAN_ADVANTAGES[field]}，另一款不支持"

        if value_b is True and value_a is not True:
            return f"{pid_b} {BOOLEAN_ADVANTAGES[field]}，另一款不支持"

    if field in {"waterproof", "water_resistance"}:
        rank_a = WATERPROOF_RANK.get(value_a, -1)
        rank_b = WATERPROOF_RANK.get(value_b, -1)

        if rank_a != rank_b:
            better = pid_a if rank_a > rank_b else pid_b
            return (
                f"{better} 的防水等级更高"
                f"（{display_a} vs {display_b}）"
            )

    if field == "positioning_type":
        rank_a = POSITIONING_RANK.get(value_a, -1)
        rank_b = POSITIONING_RANK.get(value_b, -1)

        if rank_a != rank_b:
            better = pid_a if rank_a > rank_b else pid_b
            return f"{better} 的独立定位能力更完整"

    return (
        f"两款产品的{label}不同："
        f"{pid_a} 为{display_a}，{pid_b} 为{display_b}"
    )


def _add_advantage(
    item: dict,
    pid_a: str,
    pid_b: str,
    advantages: dict[str, list[str]],
) -> None:
    field = item.get("field")
    value_a = item.get("value_a")
    value_b = item.get("value_b")

    if value_a is None or value_b is None or value_a == value_b:
        return

    if (
        field in LOWER_IS_BETTER
        and _is_number(value_a)
        and _is_number(value_b)
    ):
        better = pid_a if value_a < value_b else pid_b
        _append_unique(advantages[better], LOWER_IS_BETTER[field])
        return

    if (
        field in HIGHER_IS_BETTER
        and _is_number(value_a)
        and _is_number(value_b)
    ):
        better = pid_a if value_a > value_b else pid_b
        _append_unique(advantages[better], HIGHER_IS_BETTER[field])
        return

    if field in BOOLEAN_ADVANTAGES:
        if value_a is True and value_b is not True:
            _append_unique(
                advantages[pid_a],
                BOOLEAN_ADVANTAGES[field],
            )
        elif value_b is True and value_a is not True:
            _append_unique(
                advantages[pid_b],
                BOOLEAN_ADVANTAGES[field],
            )
        return

    if field in {"waterproof", "water_resistance"}:
        rank_a = WATERPROOF_RANK.get(value_a, -1)
        rank_b = WATERPROOF_RANK.get(value_b, -1)

        if rank_a != rank_b:
            better = pid_a if rank_a > rank_b else pid_b
            _append_unique(
                advantages[better],
                "防水等级更高",
            )
        return

    if field == "positioning_type":
        rank_a = POSITIONING_RANK.get(value_a, -1)
        rank_b = POSITIONING_RANK.get(value_b, -1)

        if rank_a != rank_b:
            better = pid_a if rank_a > rank_b else pid_b
            _append_unique(
                advantages[better],
                "独立定位能力更完整",
            )


def _run_compare(
    category: str,
    product_id_a: str,
    product_id_b: str,
) -> dict:
    if category == "earphone":
        return compare_earphone_products(product_id_a, product_id_b)

    return compare_wearable_products(product_id_a, product_id_b)


def compare_two_products(product_ids: list[str]) -> dict:
    if not isinstance(product_ids, list) or len(product_ids) != 2:
        raise ApiError(
            "product_ids 必须恰好包含2个产品ID",
            "INVALID_REQUEST",
            400,
        )

    normalized = [
        str(product_id).strip().upper()
        for product_id in product_ids
    ]

    if any(not product_id for product_id in normalized):
        raise ApiError(
            "产品ID不能为空",
            "INVALID_REQUEST",
            400,
        )

    if normalized[0] == normalized[1]:
        raise ApiError(
            "请选择两款不同的产品进行对比",
            "INVALID_REQUEST",
            400,
        )

    category_a = _detect_category(normalized[0])
    category_b = _detect_category(normalized[1])

    if category_a is None or category_b is None:
        raise ApiError(
            "产品ID格式不正确",
            "INVALID_REQUEST",
            400,
        )

    if category_a != category_b:
        raise ApiError(
            "请选择同一类别的两款产品进行对比",
            "INVALID_REQUEST",
            400,
        )

    result = _run_compare(
        category_a,
        normalized[0],
        normalized[1],
    )

    if not result.get("success"):
        message = result.get("error", "产品对比失败")

        if "不存在" in message or "有效ID" in message:
            raise ApiError(
                message,
                "PRODUCT_NOT_FOUND",
                404,
            )

        raise ApiError(
            message,
            "INVALID_REQUEST",
            400,
        )

    products = result.get("products", [])
    if len(products) != 2:
        raise ApiError(
            "产品对比结果格式错误",
            "INTERNAL_ERROR",
            500,
        )

    pid_a = products[0].get("product_id", normalized[0])
    pid_b = products[1].get("product_id", normalized[1])

    advantages = {
        pid_a: [],
        pid_b: [],
    }
    comparison = []
    missing_fields = []

    for item in result.get("comparison", []):
        field = item.get("field")
        value_a = item.get("value_a")
        value_b = item.get("value_b")

        display_a = _display_value(
            item,
            "display_a",
            value_a,
        )
        display_b = _display_value(
            item,
            "display_b",
            value_b,
        )

        if value_a is None or value_b is None:
            missing_fields.append(
                {
                    "field": field,
                    "label": item.get("label", field),
                    "missing_product_ids": [
                        product_id
                        for product_id, value in (
                            (pid_a, value_a),
                            (pid_b, value_b),
                        )
                        if value is None
                    ],
                }
            )

        comparison.append(
            {
                "field": field,
                "label": item.get("label", field),
                "unit": item.get("unit") or None,
                "values": {
                    pid_a: value_a,
                    pid_b: value_b,
                },
                "display_values": {
                    pid_a: display_a,
                    pid_b: display_b,
                },
                "conclusion": _build_conclusion(
                    item,
                    pid_a,
                    pid_b,
                ),
            }
        )

        _add_advantage(
            item,
            pid_a,
            pid_b,
            advantages,
        )

    return {
        "category": category_a,
        "products": products,
        "comparison": comparison,
        "advantages": advantages,
        "missing_fields": missing_fields,
    }
