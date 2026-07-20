
from __future__ import annotations

from backend.utils.api import ApiError


def answer_manual_question(
    product_id: str,
    question: str,
    top_k: int = 3,
) -> dict:
    """任务17合并前的占位服务。

    旦同学交付 retrieval_service 后，只需要替换此函数内部实现，
    /api/chat 的前端接口格式无需再修改。
    """
    if not isinstance(product_id, str) or not product_id.strip():
        raise ApiError("product_id 不能为空", "INVALID_REQUEST", 400)
    if not isinstance(question, str) or not question.strip():
        raise ApiError("question 不能为空", "INVALID_REQUEST", 400)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 5:
        raise ApiError("top_k 必须是1到5之间的整数", "INVALID_REQUEST", 400)

    raise ApiError(
        "说明书知识库尚未完成，待AJ15XIAOMI-17合并后开放问答服务",
        "NO_KNOWLEDGE_FOUND",
        503,
        sources=[],
        knowledge_ready=False,
    )
