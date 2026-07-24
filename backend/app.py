
from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.routes import ALL_BLUEPRINTS
from backend.utils.api import ApiError, error_response


def create_app(testing: bool = False) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(REPO_ROOT / "frontend" / "templates"),
        static_folder=str(REPO_ROOT / "frontend" / "static"),
    )
    app.config.update(TESTING=testing)
    app.json.ensure_ascii = False

    CORS(app, resources={r"/api/*": {"origins": "*"}})
    @app.after_request
    def ensure_utf8_json(response):
        if response.mimetype == "application/json":
            response.headers["Content-Type"] = (
                "application/json; charset=utf-8"
            )
        return response

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return error_response(error)

    @app.errorhandler(404)
    def handle_not_found(_error):
        if request.path.startswith("/api/"):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "接口不存在",
                        "error_code": "INVALID_REQUEST",
                    }
                ),
                404,
            )
        return _error

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        app.logger.exception("Unhandled server error: %s", error)
        return (
            jsonify(
                {
                    "success": False,
                    "message": "服务器内部错误",
                    "error_code": "INTERNAL_ERROR",
                }
            ),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
