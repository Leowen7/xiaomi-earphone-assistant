from flask import Blueprint, request

from backend.services.chat_service import (
    answer_general_question,
    answer_manual_question,
)
from backend.utils.api import ApiError, success_response


chat_bp = Blueprint(
    "chat",
    __name__,
    url_prefix="/api",
)


@chat_bp.post("/chat")
def chat():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        raise ApiError(
            "请求体必须是JSON对象",
            "INVALID_REQUEST",
            400,
        )

    product_id = payload.get("product_id")
    question = payload.get("question")

    # 有产品ID：进入小米产品知识库问答
    if isinstance(product_id, str) and product_id.strip():
        result = answer_manual_question(
            product_id=product_id,
            question=question,
            top_k=payload.get("top_k", 3),
        )

    # 没有产品ID：进入有限通用开放式问答
    else:
        result = answer_general_question(
            question=question,
            history=payload.get("history"),
        )

    return success_response(**result)