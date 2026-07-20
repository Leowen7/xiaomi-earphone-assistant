
from __future__ import annotations

from numbers import Real
from typing import Any

from backend.scripts.compare_products import compare_products
from backend.utils.api import ApiError

LOWER_IS_BETTER = {
    "reference_price": "价格更低",
    "single_weight_g": "单耳重量更轻",
}

HIGHER_IS_BETTER = {
    "single_battery_h": "单次续航更长",
    "total_battery_h": "总续航更长",
    "anc_depth_db": "降噪深度更高",
    "bluetooth_version": "蓝牙版本更高",
}

BOOLEAN_ADVANTAGES = {
    "anc_supported": "支持主动降噪",
    "dual_device": "支持双设备连接",
    "low_latency": "支持低延迟模式",
}

WATERPROOF_RANK = {
    None: -1,
    "无": 0,
    "IPX4": 1,
    "IP54": 2,
    "IPX5": 3,
    "IP55": 4,
    "IPX8": 5,
    "IP68": 5,
}


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _append_unique(target: list[str], text: str) -> None:
    if text and text not in target:
        target.append(text)


def _build_conclusion(item: dict, pid_a: str, pid_b: str) -> str:
    value_a = item.get("value_a")
    value_b = item.get("value_b")
    display_a = item.get("display_a", str(value_a))
    display_b = item.get("display_b", str(value_b))
    label = item.get("label", item.get("field", "参数"))

    if value_a is None and value_b is None:
        return f"两款产品的{label}均暂无官方数据"
    if value_a is None:
        return f"{pid_a} 的{label}暂无官方数据，{pid_b} 为{display_b}"
    if value_b is None:
        return f"{pid_b} 的{label}暂无官方数据，{pid_a} 为{display_a}"
    if value_a == value_b:
        return f"两款产品的{label}相同，均为{display_a}"

    field = item.get("field")
    if field in LOWER_IS_BETTER and _is_number(value_a) and _is_number(value_b):
        better = pid_a if value_a < value_b else pid_b
        gap = abs(float(value_a) - float(value_b))
        gap_text = str(int(gap)) if gap.is_integer() else str(round(gap, 2))
        unit = item.get("unit") or ""
        return f"{better} 的{label}更低，差值为{gap_text}{unit}"

    if field in HIGHER_IS_BETTER and _is_number(value_a) and _is_number(value_b):
        better = pid_a if value_a > value_b else pid_b
        gap = abs(float(value_a) - float(value_b))
        gap_text = str(int(gap)) if gap.is_integer() else str(round(gap, 2))
        unit = item.get("unit") or ""
        return f"{better} 的{label}更高，差值为{gap_text}{unit}"

    if field in BOOLEAN_ADVANTAGES:
        supporter = pid_a if value_a is True else pid_b
        return f"{supporter} 支持{label}，另一款不支持"

    if field == "waterproof":
        rank_a = WATERPROOF_RANK.get(value_a, -1)
        rank_b = WATERPROOF_RANK.get(value_b, -1)
        if rank_a != rank_b:
            better = pid_a if rank_a > rank_b else pid_b
            return f"{better} 的防水等级更高（{display_a} vs {display_b}）"

    return f"两款产品的{label}不同：{pid_a} 为{display_a}，{pid_b} 为{display_b}"


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

    if field in LOWER_IS_BETTER and _is_number(value_a) and _is_number(value_b):
        better = pid_a if value_a < value_b else pid_b
        _append_unique(advantages[better], LOWER_IS_BETTER[field])
    elif field in HIGHER_IS_BETTER and _is_number(value_a) and _is_number(value_b):
        better = pid_a if value_a > value_b else pid_b
        _append_unique(advantages[better], HIGHER_IS_BETTER[field])
    elif field in BOOLEAN_ADVANTAGES:
        if value_a is True and value_b is not True:
            _append_unique(advantages[pid_a], BOOLEAN_ADVANTAGES[field])
        elif value_b is True and value_a is not True:
            _append_unique(advantages[pid_b], BOOLEAN_ADVANTAGES[field])
    elif field == "waterproof":
        rank_a = WATERPROOF_RANK.get(value_a, -1)
        rank_b = WATERPROOF_RANK.get(value_b, -1)
        if rank_a != rank_b:
            better = pid_a if rank_a > rank_b else pid_b
            _append_unique(advantages[better], "防水等级更高")


def compare_two_products(product_ids: list[str]) -> dict:
    if not isinstance(product_ids, list) or len(product_ids) != 2:
        raise ApiError(
            "product_ids 必须恰好包含2个产品ID",
            "INVALID_REQUEST",
            400,
        )

    normalized = [str(product_id).strip().upper() for product_id in product_ids]
    if any(not product_id for product_id in normalized):
        raise ApiError("产品ID不能为空", "INVALID_REQUEST", 400)
    if normalized[0] == normalized[1]:
        raise ApiError(
            "请选择两款不同的耳机进行对比",
            "INVALID_REQUEST",
            400,
        )

    result = compare_products(normalized[0], normalized[1])
    if not result.get("success"):
        message = result.get("error", "产品对比失败")
        error_code = "PRODUCT_NOT_FOUND" if "不存在" in message else "INVALID_REQUEST"
        status_code = 404 if error_code == "PRODUCT_NOT_FOUND" else 400
        raise ApiError(message, error_code, status_code)

    products = result.get("products", [])
    if len(products) != 2:
        raise ApiError("产品对比结果格式错误", "INTERNAL_ERROR", 500)

    pid_a = products[0].get("product_id", normalized[0])
    pid_b = products[1].get("product_id", normalized[1])
    advantages = {pid_a: [], pid_b: []}
    comparison = []
    missing_fields = []

    for item in result.get("comparison", []):
        field = item.get("field")
        value_a = item.get("value_a")
        value_b = item.get("value_b")

        if value_a is None or value_b is None:
            missing_fields.append(
                {
                    "field": field,
                    "label": item.get("label", field),
                    "missing_product_ids": [
                        pid
                        for pid, value in ((pid_a, value_a), (pid_b, value_b))
                        if value is None
                    ],
                }
            )

        comparison.append(
            {
                "field": field,
                "label": item.get("label", field),
                "unit": item.get("unit") or None,
                "values": {pid_a: value_a, pid_b: value_b},
                "display_values": {
                    pid_a: item.get("display_a"),
                    pid_b: item.get("display_b"),
                },
                "conclusion": _build_conclusion(item, pid_a, pid_b),
            }
        )
        _add_advantage(item, pid_a, pid_b, advantages)

    return {
        "products": products,
        "comparison": comparison,
        "advantages": advantages,
        "missing_fields": missing_fields,
    }
