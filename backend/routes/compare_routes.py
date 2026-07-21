
from flask import Blueprint, request

from backend.services.compare_service import compare_two_products
from backend.utils.api import ApiError, success_response

compare_bp = Blueprint("compare", __name__, url_prefix="/api")


@compare_bp.post("/compare")
def compare():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("请求体必须是JSON对象", "INVALID_REQUEST", 400)

    result = compare_two_products(payload.get("product_ids"))
    return success_response(**result)
