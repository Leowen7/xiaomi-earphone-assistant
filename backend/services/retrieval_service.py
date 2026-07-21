"""说明书检索服务接口。

当前文件先定义任务19所需要的统一调用格式。
AJ15XIAOMI-17完成后，旦同学的FAISS检索代码应接入
search_manuals() 函数。
"""

from __future__ import annotations

from typing import Any


class KnowledgeBaseNotReadyError(RuntimeError):
    """说明书知识库尚未准备完成。"""


def search_manuals(
    product_id: str,
    query: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """检索指定耳机说明书中的相关片段。

    Args:
        product_id: 耳机产品编号，例如 EAR006。
        query: 用户提出的问题。
        top_k: 返回的相关片段数量，取值范围为1到5。

    Returns:
        说明书检索结果列表。每条结果至少应包含：
        product_id、chunk_id、source_file、page、
        section、content、score。

    Raises:
        KnowledgeBaseNotReadyError:
            当AJ15XIAOMI-17尚未完成或知识库文件不存在时抛出。
    """
    raise KnowledgeBaseNotReadyError(
        "说明书知识库尚未完成，待AJ15XIAOMI-17合并后开放问答服务"
    )