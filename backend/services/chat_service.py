"""说明书问答流程服务。

负责串联：
1. 产品校验；
2. FAISS说明书检索；
3. Gemini生成回答；
4. 返回答案和来源。
"""

from __future__ import annotations

from backend.services.llm_service import (
    LLMServiceError,
    generate_manual_answer,
)
from backend.services.product_service import load_products
from backend.services.retrieval_service import (
    KnowledgeBaseNotReadyError,
    search_manuals,
)
from backend.utils.api import ApiError


def _get_product(product_id: str) -> dict:
    """根据产品编号查找当前耳机。"""
    products = load_products()

    for product in products:
        if product.get("product_id") == product_id:
            return product

    raise ApiError(
        f"未找到产品：{product_id}",
        "PRODUCT_NOT_FOUND",
        404,
    )


def answer_manual_question(
    product_id: str,
    question: str,
    top_k: int = 3,
) -> dict:
    """根据指定耳机说明书回答用户问题。"""

    # 1. 请求参数校验
    if not isinstance(product_id, str) or not product_id.strip():
        raise ApiError(
            "product_id 不能为空",
            "INVALID_REQUEST",
            400,
        )

    if not isinstance(question, str) or not question.strip():
        raise ApiError(
            "question 不能为空",
            "INVALID_REQUEST",
            400,
        )

    if (
        isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or not 1 <= top_k <= 5
    ):
        raise ApiError(
            "top_k 必须是1到5之间的整数",
            "INVALID_REQUEST",
            400,
        )

    cleaned_product_id = product_id.strip()
    cleaned_question = question.strip()

    # 2. 确认产品存在
    product = _get_product(cleaned_product_id)
    product_name = product.get("product_name") or cleaned_product_id

    # 3. 调用任务17提供的说明书检索服务
    try:
        contexts = search_manuals(
            product_id=cleaned_product_id,
            query=cleaned_question,
            top_k=top_k,
        )
    except KnowledgeBaseNotReadyError as exc:
        raise ApiError(
            str(exc),
            "NO_KNOWLEDGE_FOUND",
            503,
            sources=[],
            knowledge_ready=False,
        ) from exc
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            "说明书检索服务运行失败",
            "RETRIEVAL_ERROR",
            500,
            sources=[],
            knowledge_ready=True,
        ) from exc

    if not isinstance(contexts, list):
        raise ApiError(
            "说明书检索结果格式错误",
            "RETRIEVAL_ERROR",
            500,
            sources=[],
            knowledge_ready=True,
        )

    # 4. 防止任务17返回其他产品的说明书内容
    valid_contexts = [
        item
        for item in contexts
        if isinstance(item, dict)
        and item.get("product_id") == cleaned_product_id
        and str(item.get("content") or "").strip()
    ]

    if not valid_contexts:
        raise ApiError(
            "未在该产品说明书中找到可靠依据",
            "NO_KNOWLEDGE_FOUND",
            404,
            sources=[],
            knowledge_ready=True,
        )

    # 5. 将检索片段交给Gemini生成回答
    try:
        answer = generate_manual_answer(
            question=cleaned_question,
            contexts=valid_contexts,
            product_name=product_name,
        )
    except LLMServiceError as exc:
        raise ApiError(
            str(exc),
            "LLM_SERVICE_ERROR",
            502,
            sources=valid_contexts,
            knowledge_ready=True,
        ) from exc

    # 6. 返回给赵阳前端
    return {
        "product_id": cleaned_product_id,
        "product_name": product_name,
        "question": cleaned_question,
        "answer": answer,
        "sources": valid_contexts,
        "knowledge_ready": True,
    }