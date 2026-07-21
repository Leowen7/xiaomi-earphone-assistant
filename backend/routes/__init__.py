
from backend.routes.chat_routes import chat_bp
from backend.routes.compare_routes import compare_bp
from backend.routes.product_routes import product_bp
from backend.routes.recommend_routes import recommend_bp
from backend.routes.system_routes import system_bp

ALL_BLUEPRINTS = (
    system_bp,
    product_bp,
    compare_bp,
    recommend_bp,
    chat_bp,
)
