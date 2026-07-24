from __future__ import annotations

import json
from pathlib import Path

from backend.utils.api import ApiError


REPO_ROOT = Path(__file__).resolve().parents[2]

# 第一阶段耳机数据
EARPHONE_DATA_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "product_data_clean.json"
)

# 第二阶段手环、手表统一数据
WEARABLE_DATA_PATH = (
    REPO_ROOT
    / "data"
    / "wearables"
    / "processed"
    / "all_wearables.jsonl"
)


EARPHONE_LIST_FIELDS = (
    "product_id",
    "product_name",
    "model",
    "brand",
    "category",
    "product_level",
    "wearing_type",
    "reference_price",
)


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


def _validate_product_ids(products: list[dict]) -> None:
    """检查产品 ID 是否存在并且不重复。"""
    product_ids = [
        product.get("product_id")
        for product in products
    ]

    if any(not product_id for product_id in product_ids):
        raise ApiError(
            "产品ID存在缺失",
            "INTERNAL_ERROR",
            500,
        )

    if len(set(product_ids)) != len(product_ids):
        raise ApiError(
            "产品ID存在重复",
            "INTERNAL_ERROR",
            500,
        )


def load_products() -> list[dict]:
    """
    读取第一阶段耳机数据。

    保留原函数名称，避免影响已有的耳机对比和推荐模块。
    """
    if not EARPHONE_DATA_PATH.exists():
        raise ApiError(
            f"耳机数据文件不存在：{EARPHONE_DATA_PATH}",
            "INTERNAL_ERROR",
            500,
        )

    try:
        with EARPHONE_DATA_PATH.open(
            "r",
            encoding="utf-8",
        ) as file:
            products = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiError(
            "耳机数据读取失败",
            "INTERNAL_ERROR",
            500,
        ) from exc

    if not isinstance(products, list):
        raise ApiError(
            "耳机数据格式错误：根节点应为数组",
            "INTERNAL_ERROR",
            500,
        )

    if len(products) != 8:
        raise ApiError(
            f"耳机数据异常：应为8款，实际为{len(products)}款",
            "INTERNAL_ERROR",
            500,
        )

    _validate_product_ids(products)
    return products


def load_wearables() -> list[dict]:
    """读取第二阶段智能手环和智能手表 JSONL 数据。"""
    if not WEARABLE_DATA_PATH.exists():
        raise ApiError(
            f"穿戴设备数据文件不存在：{WEARABLE_DATA_PATH}",
            "INTERNAL_ERROR",
            500,
        )

    products: list[dict] = []

    try:
        with WEARABLE_DATA_PATH.open(
            "r",
            encoding="utf-8",
        ) as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()

                if not line:
                    continue

                try:
                    product = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ApiError(
                        f"穿戴设备数据第{line_number}行不是合法JSON",
                        "INTERNAL_ERROR",
                        500,
                    ) from exc

                if not isinstance(product, dict):
                    raise ApiError(
                        f"穿戴设备数据第{line_number}行应为JSON对象",
                        "INTERNAL_ERROR",
                        500,
                    )

                products.append(product)

    except OSError as exc:
        raise ApiError(
            "穿戴设备数据读取失败",
            "INTERNAL_ERROR",
            500,
        ) from exc

    if not products:
        raise ApiError(
            "穿戴设备数据为空",
            "INTERNAL_ERROR",
            500,
        )

    _validate_product_ids(products)
    return products


def normalize_category(category: str | None) -> str:
    """
    统一产品分类名称。

    为兼容第一阶段，未传 category 时默认返回耳机。
    """
    if category is None or not category.strip():
        return "earphone"

    normalized = (
        category
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    resolved = CATEGORY_ALIASES.get(normalized)

    if resolved is None:
        raise ApiError(
            "category仅支持earphone、smart_band、smart_watch",
            "INVALID_REQUEST",
            400,
        )

    return resolved


def _format_earphone_product(product: dict) -> dict:
    """生成耳机产品列表接口字段。"""
    return {
        field: product.get(field)
        for field in EARPHONE_LIST_FIELDS
    }


def _format_wearable_product(product: dict) -> dict:
    """生成手环、手表产品列表接口字段。"""
    official_url = product.get("official_url")

    return {
        "product_id": product.get("product_id"),
        "product_name": product.get("product_name"),
        "brand": product.get("brand"),
        "category": product.get("product_category"),
        "product_category": product.get("product_category"),
        "series": product.get("series"),
        "variant": product.get("variant"),
        "source_region": product.get("source_region"),
        "reference_price": product.get("official_price"),
        "official_price": product.get("official_price"),
        "currency": product.get("currency"),
        "product_summary": product.get("product_summary"),
        "official_url": official_url,

        # 兼容前端读取官方来源的不同字段名
        "official_source": official_url,
        "source_url": official_url,

        "wearable_specs": product.get("wearable_specs"),
        "source_records": product.get("source_records", []),
    }


def list_products(category: str | None = None) -> list[dict]:
    """根据分类返回耳机、智能手环或智能手表列表。"""
    normalized_category = normalize_category(category)

    if normalized_category == "earphone":
        products = load_products()

        return [
            _format_earphone_product(product)
            for product in products
            if product.get("category") == "earphone"
        ]

    wearable_products = load_wearables()

    selected_products = [
        product
        for product in wearable_products
        if product.get("product_category")
        == normalized_category
    ]

    if len(selected_products) != 8:
        category_name = (
            "智能手环"
            if normalized_category == "smart_band"
            else "智能手表"
        )

        raise ApiError(
            (
                f"{category_name}数据异常："
                f"应为8款，实际为{len(selected_products)}款"
            ),
            "INTERNAL_ERROR",
            500,
        )

    return [
        _format_wearable_product(product)
        for product in selected_products
    ]