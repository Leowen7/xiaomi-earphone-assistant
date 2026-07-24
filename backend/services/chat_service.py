"""统一产品知识问答服务。

处理策略：
1. 多产品推荐/比较问题：引导至对应功能；
2. 参数类问题：优先读取结构化产品字段；
3. 操作类问题：进入耳机或穿戴设备知识库检索；
4. Gemini 不可用时：仅返回与问题主题匹配的知识片段；
5. 返回来源时按官方链接去重。
"""

from __future__ import annotations

from typing import Any, Callable

from backend.services.llm_service import (
    LLMServiceError,
    LLMTemporaryUnavailableError,
    generate_general_answer,
    generate_manual_answer,
)
from backend.services.product_service import (
    load_products,
    load_wearables,
)
from backend.services.retrieval_service import (
    KnowledgeBaseNotReadyError,
    search_manuals,
)
from backend.services.wearable_retrieval_service import (
    search_wearable_knowledge,
)
from backend.utils.api import ApiError


MULTI_PRODUCT_KEYWORDS = (
    "哪款",
    "推荐",
    "最好",
    "性价比",
    "哪个更好",
    "哪一个更好",
    "对比",
    "比较",
)

OPERATION_TOPICS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("恢复出厂", "恢复设置", "重置", "清除连接记录"),
        ("重置", "恢复出厂", "清除连接", "长按", "白灯"),
    ),
    (
        ("连接不上", "连不上", "如何连接", "怎么连接", "配对", "蓝牙连接"),
        ("连接", "配对", "蓝牙", "搜索设备", "回连"),
    ),
    (
        ("怎么充电", "如何充电", "充电方法", "充不上电"),
        ("充电", "电量", "充电盒", "接口", "电源"),
    ),
    (
        ("怎么接电话", "接听电话", "挂断电话", "通话操作"),
        ("接听", "挂断", "电话", "通话"),
    ),
    (
        ("怎么操作", "触摸操作", "手势", "双击", "长按"),
        ("操作", "触摸", "双击", "三击", "长按"),
    ),
)


def _normalize_product_id(product_id: str) -> str:
    return product_id.strip().upper()


def _detect_category(product_id: str) -> str | None:
    if product_id.startswith("EAR"):
        return "earphone"
    if product_id.startswith("B"):
        return "smart_band"
    if product_id.startswith("W"):
        return "smart_watch"
    return None


def _get_product(product_id: str) -> dict[str, Any]:
    category = _detect_category(product_id)

    if category == "earphone":
        products = load_products()
    elif category in {"smart_band", "smart_watch"}:
        products = load_wearables()
    else:
        raise ApiError(
            f"产品ID格式不正确：{product_id}",
            "INVALID_REQUEST",
            400,
        )

    for product in products:
        current_id = str(product.get("product_id") or "").strip().upper()
        if current_id == product_id:
            return product

    raise ApiError(
        f"未找到产品：{product_id}",
        "PRODUCT_NOT_FOUND",
        404,
    )


def _product_source_url(product: dict[str, Any]) -> str | None:
    return (
        product.get("official_url")
        or product.get("source_url")
    )


def _make_structured_source(
    product: dict[str, Any],
    answer: str,
) -> list[dict[str, Any]]:
    source_url = _product_source_url(product)
    if not source_url:
        return []

    return [
        {
            "product_id": product.get("product_id"),
            "product_name": product.get("product_name"),
            "section": "官方参数",
            "source_name": "官方产品参数页",
            "source_type": "structured_product_data",
            "source_url": source_url,
            "content": answer,
            "text": answer,
        }
    ]


def _wearable_specs(product: dict[str, Any]) -> dict[str, Any]:
    specs = product.get("wearable_specs")
    return specs if isinstance(specs, dict) else {}


def _yes_no_answer(
    product_name: str,
    label: str,
    value: Any,
    *,
    true_suffix: str = "",
    false_suffix: str = "",
) -> str:
    if value is True:
        return f"是的，{product_name}支持{label}。{true_suffix}".strip()

    if value is False:
        return f"不支持。根据当前官方参数，{product_name}不支持{label}。{false_suffix}".strip()

    return f"当前官方资料暂未明确说明{product_name}是否支持{label}。"


def _format_number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _answer_battery(
    product: dict[str, Any],
    category: str,
) -> str:
    name = product.get("product_name") or product.get("product_id")

    if category == "earphone":
        single = product.get("single_battery_h")
        total = product.get("total_battery_h")

        parts = []
        if single is not None:
            parts.append(f"耳机单次续航约{_format_number(single)}小时")
        if total is not None:
            parts.append(f"搭配充电盒总续航约{_format_number(total)}小时")

        if parts:
            return f"{name}的" + "，".join(parts) + "。"

        return f"当前官方资料暂未提供{name}的明确续航数据。"

    specs = _wearable_specs(product)
    typical = specs.get("battery_life_typical_days")
    heavy = specs.get("battery_life_heavy_days")

    parts = []
    if typical is not None:
        parts.append(f"典型使用续航约{_format_number(typical)}天")
    if heavy is not None:
        parts.append(f"重度使用续航约{_format_number(heavy)}天")

    if parts:
        return f"{name}的" + "，".join(parts) + "。"

    return f"当前官方资料暂未提供{name}的明确续航数据。"


def _answer_price(
    product: dict[str, Any],
    category: str,
) -> str:
    name = product.get("product_name") or product.get("product_id")

    if category == "earphone":
        price = product.get("reference_price")
        if price is None:
            return f"当前官方资料暂未提供{name}的参考价格。"
        return f"{name}的参考价格为{_format_number(price)}元。"

    price = product.get("official_price")
    currency = product.get("currency")
    if price is None:
        return f"当前官方资料暂未提供{name}的官方价格。"

    currency_text = f" {currency}" if currency else ""
    return f"{name}的官方价格为{_format_number(price)}{currency_text}。"


def _answer_positioning(product: dict[str, Any]) -> str:
    name = product.get("product_name") or product.get("product_id")
    value = _wearable_specs(product).get("positioning_type")

    if value == "built_in_gnss":
        return f"是的，{name}支持内置GNSS，可进行独立定位。"

    if value == "connected_phone":
        return f"{name}不具备独立GNSS，需要连接手机使用辅助定位。"

    return f"当前官方资料暂未明确说明{name}的定位方式。"


def _answer_display(
    product: dict[str, Any],
    field: str,
    label: str,
    unit: str = "",
) -> str:
    name = product.get("product_name") or product.get("product_id")
    value = _wearable_specs(product).get(field)

    if value is None:
        return f"当前官方资料暂未提供{name}的{label}。"

    return f"{name}的{label}为{_format_number(value)}{unit}。"


def _answer_simple_field(
    product: dict[str, Any],
    category: str,
    field: str,
    label: str,
    unit: str = "",
    *,
    nested: bool = False,
) -> str:
    name = product.get("product_name") or product.get("product_id")
    value = (
        _wearable_specs(product).get(field)
        if nested
        else product.get(field)
    )

    if value is None:
        return f"当前官方资料暂未提供{name}的{label}。"

    return f"{name}的{label}为{_format_number(value)}{unit}。"


def _structured_parameter_answer(
    question: str,
    product: dict[str, Any],
    category: str,
) -> str | None:
    """识别参数类问题并直接从结构化字段回答。"""

    q = question.lower()
    name = product.get("product_name") or product.get("product_id")
    specs = _wearable_specs(product)

    # 耳机专用参数
    if category == "earphone":
        if any(word in q for word in ("主动降噪", "anc", "降噪")):
            return _yes_no_answer(
                name,
                "主动降噪",
                product.get("anc_supported"),
            )

        if any(word in q for word in ("低延迟", "游戏模式")):
            return _yes_no_answer(
                name,
                "低延迟模式",
                product.get("low_latency"),
            )

        if any(word in q for word in ("双设备", "多设备连接")):
            return _yes_no_answer(
                name,
                "双设备连接",
                product.get("dual_device"),
            )

        if any(word in q for word in ("佩戴方式", "入耳", "半入耳", "头戴")):
            return _answer_simple_field(
                product,
                category,
                "wearing_type",
                "佩戴方式",
            )

        if any(word in q for word in ("蓝牙版本",)):
            return _answer_simple_field(
                product,
                category,
                "bluetooth_version",
                "蓝牙版本",
            )

        if any(word in q for word in ("编码", "codec")):
            return _answer_simple_field(
                product,
                category,
                "codec",
                "音频编码",
            )

        if any(word in q for word in ("驱动单元", "单元尺寸")):
            return _answer_simple_field(
                product,
                category,
                "driver_size_mm",
                "驱动单元尺寸",
                "mm",
            )

    # 穿戴设备专用参数
    if category in {"smart_band", "smart_watch"}:
        boolean_rules = (
            (("nfc",), "nfc_support", "NFC"),
            (("蓝牙通话", "接打电话", "打电话"), "bluetooth_call", "蓝牙通话"),
            (("心率",), "heart_rate_monitoring", "心率监测"),
            (("血氧",), "blood_oxygen_monitoring", "血氧监测"),
            (("睡眠",), "sleep_monitoring", "睡眠监测"),
            (("压力监测", "压力检测"), "stress_monitoring", "压力监测"),
        )

        for keywords, field, label in boolean_rules:
            if any(word in q for word in keywords):
                suffix = (
                    "具体公交、门禁和支付服务可能因地区及版本而异。"
                    if field == "nfc_support"
                    else ""
                )
                return _yes_no_answer(
                    name,
                    label,
                    specs.get(field),
                    true_suffix=suffix,
                )

        if any(word in q for word in ("gps", "gnss", "独立定位", "定位方式")):
            return _answer_positioning(product)

        if any(word in q for word in ("屏幕尺寸", "显示屏尺寸")):
            return _answer_display(
                product,
                "display_size_in",
                "屏幕尺寸",
                "英寸",
            )

        if any(word in q for word in ("屏幕类型", "显示屏类型")):
            return _answer_display(
                product,
                "display_type",
                "屏幕类型",
            )

        if any(word in q for word in ("分辨率",)):
            return _answer_display(
                product,
                "screen_resolution",
                "屏幕分辨率",
            )

        if any(word in q for word in ("亮度", "尼特")):
            return _answer_display(
                product,
                "max_brightness_nits",
                "最大亮度",
                "尼特",
            )

        if any(word in q for word in ("运动模式", "运动种类")):
            return _answer_display(
                product,
                "sports_modes_count",
                "运动模式数量",
                "种",
            )

        if any(word in q for word in ("系统兼容", "兼容安卓", "兼容android", "兼容ios", "兼容iphone", "gms")):
            return _answer_display(
                product,
                "system_compatibility",
                "系统兼容性",
            )

        if any(word in q for word in ("表带材质", "腕带材质")):
            return _answer_display(
                product,
                "strap_material",
                "表带材质",
            )

        if any(word in q for word in ("充电时间", "多久充满", "充满要多久")):
            return _answer_display(
                product,
                "charging_time_minutes",
                "充电时间",
                "分钟",
            )

        if any(word in q for word in ("尺寸", "长宽高")):
            return _answer_display(
                product,
                "dimensions_mm",
                "机身尺寸",
                "mm",
            )

    # 三类产品通用参数
    if any(word in q for word in ("续航", "电池能用多久", "能用几天", "能用几小时")):
        return _answer_battery(product, category)

    if any(word in q for word in ("防水", "防水等级")):
        field = "waterproof" if category == "earphone" else "water_resistance"
        return _answer_simple_field(
            product,
            category,
            field,
            "防水等级",
            nested=category != "earphone",
        )

    if any(word in q for word in ("重量", "多重", "轻不轻")):
        field = "single_weight_g" if category == "earphone" else "weight_g"
        label = "单耳重量" if category == "earphone" else "机身重量"
        return _answer_simple_field(
            product,
            category,
            field,
            label,
            "g",
            nested=category != "earphone",
        )

    if any(word in q for word in ("价格", "多少钱", "售价", "预算")):
        return _answer_price(product, category)

    return None


def _normalize_context(
    item: dict[str, Any],
    *,
    wearable: bool,
) -> dict[str, Any]:
    content = str(
        item.get("text")
        or item.get("content")
        or ""
    ).strip()

    section = str(
        item.get("section")
        or item.get("topic")
        or item.get("chunk_type")
        or "相关说明"
    ).strip()

    source_url = item.get("source_url") or item.get("url")

    return {
        **item,
        "content": content,
        "text": content,
        "section": section,
        "source_name": (
            item.get("source_name")
            or section
            or ("官方穿戴资料" if wearable else "官方说明书")
        ),
        "source_url": source_url,
    }


def _search_product_knowledge(
    product_id: str,
    question: str,
    top_k: int,
    category: str,
) -> list[dict[str, Any]]:
    if category == "earphone":
        raw_contexts = search_manuals(
            product_id=product_id,
            query=question,
            top_k=top_k,
        )
        return [
            _normalize_context(item, wearable=False)
            for item in raw_contexts
            if isinstance(item, dict)
        ]

    raw_contexts = search_wearable_knowledge(
        query=question,
        product_id=product_id,
        device_type=category,
        top_k=top_k,
    )
    return [
        _normalize_context(item, wearable=True)
        for item in raw_contexts
        if isinstance(item, dict)
    ]


def _topic_terms(question: str) -> tuple[str, ...]:
    for question_terms, content_terms in OPERATION_TOPICS:
        if any(term in question for term in question_terms):
            return content_terms
    return ()


def _prioritize_relevant_contexts(
    question: str,
    contexts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    terms = _topic_terms(question)
    if not terms:
        return contexts

    matched = []
    unmatched = []

    for context in contexts:
        content = str(context.get("content") or "")
        section = str(context.get("section") or "")
        haystack = f"{section}\n{content}"

        if any(term in haystack for term in terms):
            matched.append(context)
        else:
            unmatched.append(context)

    return matched + unmatched


def _dedupe_sources(
    contexts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique = []
    seen: set[str] = set()

    for context in contexts:
        source_url = str(context.get("source_url") or "").strip()
        source_file = str(context.get("source_file") or "").strip()

        key = source_url or source_file
        if not key:
            key = f"{context.get('product_id')}|{context.get('section')}"

        if key in seen:
            continue

        seen.add(key)
        unique.append(context)

    return unique


def _fallback_context(
    question: str,
    contexts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not contexts:
        return None

    terms = _topic_terms(question)
    if not terms:
        return contexts[0]

    for context in contexts:
        content = str(context.get("content") or "")
        section = str(context.get("section") or "")
        haystack = f"{section}\n{content}"
        if any(term in haystack for term in terms):
            return context

    return None


def _build_fallback_answer(
    question: str,
    contexts: list[dict[str, Any]],
) -> str:
    context = _fallback_context(question, contexts)

    if context is None:
        return (
            "当前智能整理服务繁忙，且知识库中没有检索到"
            "与这个问题直接相关的可靠原文。请换一种问法，"
            "或查看页面中的官方来源。"
        )

    content = str(context.get("content") or "").strip()
    section = str(context.get("section") or "相关说明").strip()

    if not content:
        return (
            "当前智能整理服务繁忙，且最相关知识片段"
            "没有有效正文。"
        )

    return (
        "当前智能整理服务繁忙，先为你返回知识库中"
        "与问题最相关的原文：\n\n"
        f"【{section}】\n"
        f"{content}"
    )


def _route_hint_answer(
    product_name: str,
) -> str:
    return (
        f"这是一个需要比较多款产品的问题。当前已选择的产品是"
        f"“{product_name}”，单产品问答不能可靠判断“哪款最好”。"
        "请点击左侧“智能推荐”填写预算和需求，或进入“产品对比”"
        "选择两款产品查看真实参数差异。"
    )


def answer_manual_question(
    product_id: str,
    question: str,
    top_k: int = 3,
) -> dict[str, Any]:
    if not isinstance(product_id, str) or not product_id.strip():
        raise ApiError(
            "product_id 不能为空",
            "INVALID_REQUEST",
            400,
        )

    if not isinstance(question, str) or not question.strip():
        raise ApiError(
            "question 不能为空",
            "INVALID_REQUEST",
            400,
        )

    if (
        isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or not 1 <= top_k <= 5
    ):
        raise ApiError(
            "top_k 必须是1到5之间的整数",
            "INVALID_REQUEST",
            400,
        )

    cleaned_product_id = _normalize_product_id(product_id)
    cleaned_question = question.strip()
    category = _detect_category(cleaned_product_id)

    if category is None:
        raise ApiError(
            f"产品ID格式不正确：{cleaned_product_id}",
            "INVALID_REQUEST",
            400,
        )

    product = _get_product(cleaned_product_id)
    product_name = product.get("product_name") or cleaned_product_id

    # 1. 多产品问题不进入单产品知识库
    if any(keyword in cleaned_question for keyword in MULTI_PRODUCT_KEYWORDS):
        answer = _route_hint_answer(product_name)
        return {
            "category": category,
            "product_id": cleaned_product_id,
            "product_name": product_name,
            "question": cleaned_question,
            "answer": answer,
            "answer_mode": "route_hint",
            "sources": [],
            "knowledge_ready": True,
            "llm_degraded": False,
        }

    # 2. 参数类问题直接读取结构化产品字段
    parameter_answer = _structured_parameter_answer(
        cleaned_question,
        product,
        category,
    )

    if parameter_answer is not None:
        return {
            "category": category,
            "product_id": cleaned_product_id,
            "product_name": product_name,
            "question": cleaned_question,
            "answer": parameter_answer,
            "answer_mode": "structured_parameter",
            "sources": _make_structured_source(
                product,
                parameter_answer,
            ),
            "knowledge_ready": True,
            "llm_degraded": False,
        }

    # 3. 操作类或说明书问题进入知识库
    try:
        contexts = _search_product_knowledge(
            product_id=cleaned_product_id,
            question=cleaned_question,
            top_k=top_k,
            category=category,
        )

    except KnowledgeBaseNotReadyError as exc:
        raise ApiError(
            str(exc),
            "NO_KNOWLEDGE_FOUND",
            503,
            sources=[],
            knowledge_ready=False,
        ) from exc

    except ApiError:
        raise

    except FileNotFoundError as exc:
        raise ApiError(
            str(exc),
            "NO_KNOWLEDGE_FOUND",
            503,
            sources=[],
            knowledge_ready=False,
        ) from exc

    except Exception as exc:
        raise ApiError(
            "知识库检索服务运行失败",
            "RETRIEVAL_ERROR",
            500,
            sources=[],
            knowledge_ready=True,
        ) from exc

    if not isinstance(contexts, list):
        raise ApiError(
            "知识库检索结果格式错误",
            "RETRIEVAL_ERROR",
            500,
            sources=[],
            knowledge_ready=True,
        )

    valid_contexts = [
        item
        for item in contexts
        if (
            isinstance(item, dict)
            and str(item.get("product_id") or "").strip().upper()
            == cleaned_product_id
            and str(item.get("content") or "").strip()
        )
    ]

    if not valid_contexts:
        raise ApiError(
            "未在该产品知识库中找到可靠依据",
            "NO_KNOWLEDGE_FOUND",
            404,
            sources=[],
            knowledge_ready=True,
        )

    # 旧耳机向量库可能只有 source_file，补充产品官方链接
    fallback_source_url = (
    product.get("manual_url")
    or _product_source_url(product)
)

    for context in valid_contexts:
        if not context.get("source_url") and fallback_source_url:
            context["source_url"] = fallback_source_url
            context["source_type"] = "official_product_page_fallback"
            context["source_name"] = (
                context.get("section")
                or context.get("source_file")
                or "官方说明书"
            )

    valid_contexts = _prioritize_relevant_contexts(
        cleaned_question,
        valid_contexts,
    )

    try:
        answer = generate_manual_answer(
            question=cleaned_question,
            contexts=valid_contexts,
            product_name=product_name,
        )
        llm_degraded = False

    except (LLMTemporaryUnavailableError, LLMServiceError):
        answer = _build_fallback_answer(
            cleaned_question,
            valid_contexts,
        )
        llm_degraded = True

    return {
        "category": category,
        "product_id": cleaned_product_id,
        "product_name": product_name,
        "question": cleaned_question,
        "answer": answer,
        "answer_mode": "knowledge_base",
        "sources": _dedupe_sources(valid_contexts),
        "knowledge_ready": True,
        "llm_degraded": llm_degraded,
    }
def _format_general_history(
    history: Any,
) -> str:
    """
    将前端传入的最近对话整理为大模型可读文本。
    最多保留最近6条消息，避免上下文过长。
    """
    if not isinstance(history, list):
        return ""

    lines: list[str] = []

    for item in history[-6:]:
        if not isinstance(item, dict):
            continue

        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()

        if not content:
            continue

        if role == "user":
            role_name = "用户"
        elif role == "assistant":
            role_name = "助手"
        else:
            continue

        lines.append(
            f"{role_name}：{content}"
        )

    return "\n".join(lines)


def answer_general_question(
    question: str,
    history: Any = None,
) -> dict[str, Any]:
    """
    处理有限通用开放式问答。

    该模式不会检索产品知识库，也不会返回产品来源。
    """
    if not isinstance(question, str) or not question.strip():
        raise ApiError(
            "question 不能为空",
            "INVALID_REQUEST",
            400,
        )

    cleaned_question = question.strip()
    history_text = _format_general_history(history)

    try:
        answer = generate_general_answer(
            question=cleaned_question,
            history_text=history_text,
        )

        answer_mode = "general"
        llm_degraded = False

    except (
        LLMTemporaryUnavailableError,
        LLMServiceError,
    ):
        answer = (
            "通用对话服务暂时不可用。"
            "小米产品参数查询、说明书问答、"
            "智能推荐和产品对比功能仍可继续使用。"
        )

        answer_mode = "general_fallback"
        llm_degraded = True

    return {
        "category": "general",
        "product_id": None,
        "product_name": None,
        "question": cleaned_question,
        "answer": answer,
        "answer_mode": answer_mode,
        "sources": [],
        "knowledge_ready": True,
        "llm_degraded": llm_degraded,
    }