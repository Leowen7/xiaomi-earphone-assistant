
from __future__ import annotations

from typing import Any

from flask import jsonify


class ApiError(Exception):
    """可安全返回给前端的业务异常。"""

    def __init__(
        self,
        message: str,
        error_code: str = "INVALID_REQUEST",
        status_code: int = 400,
        **extra: Any,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.extra = extra


def success_response(**payload: Any):
    return jsonify({"success": True, **payload})


def error_response(error: ApiError):
    body = {
        "success": False,
        "message": error.message,
        "error_code": error.error_code,
        **error.extra,
    }
    return jsonify(body), error.status_code
