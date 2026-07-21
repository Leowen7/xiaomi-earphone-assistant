"""说明书检索服务适配层。

将 AJ15XIAOMI-17 提供的 FAISS 检索函数，
接入现有后端问答流程使用的 search_manuals 接口。
"""

from __future__ import annotations

from typing import Any

from ..retrieval_service import (
    INDEX_PATH,
    METADATA_PATH,
    search_manual,
)


class KnowledgeBaseNotReadyError(RuntimeError):
    """说明书知识库文件尚未准备完成。"""


def search_manuals(
    product_id: str,
    query: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """检索指定产品的说明书片段。"""

    if not INDEX_PATH.exists():
        raise KnowledgeBaseNotReadyError(
            f"FAISS索引不存在：{INDEX_PATH}"
        )

    if not METADATA_PATH.exists():
        raise KnowledgeBaseNotReadyError(
            f"知识库元数据不存在：{METADATA_PATH}"
        )

    try:
        results = search_manual(
            query=query,
            product_id=product_id,
            top_k=top_k,
        )
    except (FileNotFoundError, OSError) as exc:
        raise KnowledgeBaseNotReadyError(
            f"说明书知识库加载失败：{exc}"
        ) from exc

    normalized_results: list[dict[str, Any]] = []

    for result in results:
        item = dict(result)

        page_start = item.get("page_start")
        page_end = item.get("page_end")

        if item.get("page") is None:
            if page_start is None:
                item["page"] = None
            elif page_end in (None, page_start):
                item["page"] = page_start
            else:
                item["page"] = f"{page_start}-{page_end}"

        normalized_results.append(item)

    return normalized_results