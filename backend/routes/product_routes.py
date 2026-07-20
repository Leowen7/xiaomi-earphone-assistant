
from flask import Blueprint, request

from backend.services.product_service import list_products
from backend.utils.api import success_response

product_bp = Blueprint("products", __name__, url_prefix="/api")


@product_bp.get("/products")
def products():
    category = request.args.get("category")
    return success_response(products=list_products(category))
