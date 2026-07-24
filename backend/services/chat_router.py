import re
from typing import Any


# 明确的小米产品或型号词
SPECIFIC_PRODUCT_WORDS = [
    "xiaomi buds",
    "redmi buds",
    "xiaomi watch",
    "redmi watch",
    "xiaomi smart band",
    "小米耳机",
    "红米耳机",
    "小米手环",
    "红米手环",
    "小米手表",
    "红米手表",
    "ear001",
    "ear002",
    "ear003",
    "ear004",
    "ear005",
    "ear006",
    "ear007",
    "ear008",
]

# 产品类别
PRODUCT_CATEGORY_WORDS = [
    "耳机",
    "手环",
    "手表",
    "buds",
    "band",
    "watch",
]

# 产品客服常见意图
PRODUCT_SERVICE_WORDS = [
    "推荐",
    "对比",
    "区别",
    "参数",
    "续航",
    "降噪",
    "充电",
    "连接",
    "蓝牙连接",
    "恢复出厂",
    "重置",
    "佩戴",
    "配对",
    "故障",
    "支持",
    "兼容",
    "防水",
    "定位",
    "nfc",
    "gps",
    "屏幕",
    "健康监测",
    "睡眠监测",
    "心率",
    "血氧",
    "怎么选",
    "哪款",
    "哪个好",
    "为什么没声音",
    "只有一边",
]

# 多轮对话中的指代词
FOLLOW_UP_WORDS = [
    "第一款",
    "第二款",
    "第三款",
    "上一款",
    "下一款",
    "这个呢",
    "那个呢",
    "它呢",
    "这款呢",
    "前面那个",
    "刚才那款",
]

# 目前不适合直接回答的内容
LIMITED_WORDS = [
    "今天价格",
    "今日价格",
    "实时价格",
    "最低价",
    "当前促销",
    "最新优惠",
    "明天会不会降价",
    "今天新闻",
    "实时新闻",
    "实时天气",
    "诊断疾病",
    "开什么药",
    "法律判决",
    "一定上涨",
    "稳赚",
]


def _contains_any(text: str, words: list[str]) -> bool:
    """判断文本是否包含任意关键词。"""
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def _history_to_text(history: list[dict[str, Any]] | None) -> str:
    """将最近几轮对话转换为文本，便于识别‘第二款呢’等追问。"""
    if not history:
        return ""

    texts: list[str] = []

    for item in history[-6:]:
        if not isinstance(item, dict):
            continue

        role = str(item.get("role", ""))
        content = str(item.get("content", ""))

        if role in {"user", "assistant"} and content:
            texts.append(content)

    return "\n".join(texts)


def classify_chat_mode(
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """
    返回：
    product：小米产品知识库问答
    general：普通开放式问答
    limited：实时或高风险问题
    """

    question = question.strip()

    if not question:
        return "general"

    # 1. 能力边界问题优先判断
    if _contains_any(question, LIMITED_WORDS):
        return "limited"

    history_text = _history_to_text(history)
    combined_text = f"{history_text}\n{question}"

    # 2. 出现明确型号或具体小米产品名称
    if _contains_any(question, SPECIFIC_PRODUCT_WORDS):
        return "product"

    # 支持 EAR001、B01、W01 等编号
    if re.search(r"\b(EAR\d{3}|B\d{2}|W\d{2})\b", question, re.IGNORECASE):
        return "product"

    has_product_category = _contains_any(question, PRODUCT_CATEGORY_WORDS)
    has_product_service = _contains_any(question, PRODUCT_SERVICE_WORDS)

    # 3. 产品类别 + 客服意图
    if has_product_category and has_product_service:
        return "product"

    # 4. 多轮对话追问
    history_has_product = (
        _contains_any(history_text, SPECIFIC_PRODUCT_WORDS)
        or _contains_any(history_text, PRODUCT_CATEGORY_WORDS)
    )

    if history_has_product and _contains_any(question, FOLLOW_UP_WORDS):
        return "product"

    # 5. 其余问题进入有限通用问答
    return "general"