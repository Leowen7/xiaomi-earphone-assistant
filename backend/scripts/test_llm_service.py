# -*- coding: utf-8 -*-
"""测试 Gemini 说明书问答服务。"""

from backend.services.llm_service import generate_manual_answer


def main() -> None:
    mock_contexts = [
        {
            "product_id": "EAR006",
            "source_file": "Redmi Buds 4 Pro说明书.pdf",
            "page": 6,
            "section": "恢复出厂设置",
            "content": (
                "将左右耳机放入充电盒，保持盒盖打开，"
                "长按充电盒功能键约10秒，指示灯连续闪烁后，"
                "耳机恢复出厂设置。"
            ),
        }
    ]

    answer = generate_manual_answer(
        question="如何恢复出厂设置？",
        contexts=mock_contexts,
        product_name="Redmi Buds 4 Pro",
    )

    print("大模型回答：")
    print(answer)


if __name__ == "__main__":
    main()