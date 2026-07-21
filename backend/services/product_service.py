
from __future__ import annotations

import json
from pathlib import Path

from backend.utils.api import ApiError

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_DATA_PATH = REPO_ROOT / "data" / "processed" / "product_data_clean.json"

PRODUCT_LIST_FIELDS = (
    "product_id",
    "product_name",
    "model",
    "brand",
    "category",
    "product_level",
    "wearing_type",
    "reference_price",
)


def load_products() -> list[dict]:
    if not PRODUCT_DATA_PATH.exists():
        raise ApiError(
            f"产品数据文件不存在：{PRODUCT_DATA_PATH}",
            "INTERNAL_ERROR",
            500,
        )

    try:
        with PRODUCT_DATA_PATH.open("r", encoding="utf-8") as file:
            products = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiError("产品数据读取失败", "INTERNAL_ERROR", 500) from exc

    if not isinstance(products, list):
        raise ApiError("产品数据格式错误：根节点应为数组", "INTERNAL_ERROR", 500)

    if len(products) != 8:
        raise ApiError(
            f"产品数据异常：第一阶段应为8款，实际为{len(products)}款",
            "INTERNAL_ERROR",
            500,
        )

    product_ids = [product.get("product_id") for product in products]
    if len(set(product_ids)) != len(product_ids) or any(not pid for pid in product_ids):
        raise ApiError("产品ID缺失或重复", "INTERNAL_ERROR", 500)

    return products


def list_products(category: str | None = None) -> list[dict]:
    if category is not None:
        normalized = category.strip().lower()
        if normalized != "earphone":
            raise ApiError(
                "第一阶段仅支持 category=earphone",
                "INVALID_REQUEST",
                400,
            )

    products = load_products()
    return [
        {field: product.get(field) for field in PRODUCT_LIST_FIELDS}
        for product in products
        if product.get("category") == "earphone"
    ]
