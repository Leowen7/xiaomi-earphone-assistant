
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app import create_app


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name}失败：{detail}")
    print(f"✅ {name}")


def main() -> None:
    client = create_app(testing=True).test_client()

    response = client.get("/api/health")
    check("健康检查", response.status_code == 200, response.get_data(as_text=True))

    response = client.get("/api/products?category=earphone")
    body = response.get_json()
    check(
        "产品列表接口",
        response.status_code == 200
        and body.get("success") is True
        and len(body.get("products", [])) == 8,
        str(body),
    )

    response = client.post(
        "/api/compare",
        json={"product_ids": ["EAR001", "EAR002"]},
    )
    body = response.get_json()
    check(
        "产品对比接口",
        response.status_code == 200
        and body.get("success") is True
        and len(body.get("comparison", [])) > 0,
        str(body),
    )

    response = client.post(
        "/api/compare",
        json={"product_ids": ["EAR001", "EAR001"]},
    )
    body = response.get_json()
    check(
        "相同产品校验",
        response.status_code == 400
        and body.get("error_code") == "INVALID_REQUEST",
        str(body),
    )

    response = client.post(
        "/api/recommend",
        json={
            "budget_max": 500,
            "scenario": "daily",
            "preferences": ["lightweight"],
            "must_have": [],
            "excluded_wearing_types": [],
            "top_k": 3,
        },
    )
    body = response.get_json()
    check(
        "个性化推荐接口",
        response.status_code == 200
        and body.get("success") is True
        and 1 <= len(body.get("recommendations", [])) <= 3,
        str(body),
    )

    response = client.post(
        "/api/chat",
        json={
            "product_id": "EAR001",
            "question": "如何配对？",
            "top_k": 3,
        },
    )
    body = response.get_json()
    check(
        "问答占位接口（等待任务17）",
        response.status_code == 503
        and body.get("error_code") == "NO_KNOWLEDGE_FOUND"
        and body.get("knowledge_ready") is False,
        str(body),
    )

    print("\n当前阶段可完成的任务19后端检查全部通过。")
    print("/api/chat 返回503属于预期结果，待任务17完成后再接入真实检索。")


if __name__ == "__main__":
    main()
