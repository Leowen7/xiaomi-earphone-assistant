
from flask import Blueprint, request

from backend.services.recommend_service import recommend_for_request
from backend.utils.api import ApiError, success_response

recommend_bp = Blueprint("recommend", __name__, url_prefix="/api")


@recommend_bp.post("/recommend")
def recommend():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("请求体必须是JSON对象", "INVALID_REQUEST", 400)

    result = recommend_for_request(payload)
    return success_response(**result)
