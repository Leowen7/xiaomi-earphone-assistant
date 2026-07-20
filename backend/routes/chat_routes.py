
from flask import Blueprint, request

from backend.services.chat_service import answer_manual_question
from backend.utils.api import ApiError, success_response

chat_bp = Blueprint("chat", __name__, url_prefix="/api")


@chat_bp.post("/chat")
def chat():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("请求体必须是JSON对象", "INVALID_REQUEST", 400)

    result = answer_manual_question(
        product_id=payload.get("product_id"),
        question=payload.get("question"),
        top_k=payload.get("top_k", 3),
    )
    return success_response(**result)
