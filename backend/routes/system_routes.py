
from flask import Blueprint

from backend.utils.api import success_response

system_bp = Blueprint("system", __name__, url_prefix="/api")


@system_bp.get("/health")
def health():
    return success_response(message="service is running")
