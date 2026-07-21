"""Gemini 大模型服务。

该模块负责：

1. 读取本地 Gemini 配置；
2. 将用户问题和说明书检索片段组合成提示词；
3. 调用 Gemini 生成基于说明书的回答；
4. 遇到 503、429、超时等临时错误时自动重试。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai


REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"

# 本地开发时，从仓库根目录读取 .env。
load_dotenv(dotenv_path=ENV_PATH)


class LLMServiceError(RuntimeError):
    """大模型服务调用失败。"""


class LLMTemporaryUnavailableError(LLMServiceError):
    """Gemini 临时繁忙，可由上层降级返回说明书原文。"""


_RETRYABLE_GEMINI_ERRORS = (
    "429",
    "503",
    "deadline exceeded",
    "high demand",
    "rate limit",
    "resource exhausted",
    "resource_exhausted",
    "service unavailable",
    "timeout",
    "timed out",
    "unavailable",
)


def _get_client() -> genai.Client:
    """创建 Gemini 客户端。"""

    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        raise LLMServiceError(
            "没有读取到 GEMINI_API_KEY，请检查仓库根目录下的 .env 文件"
        )

    return genai.Client(api_key=api_key)


def _is_retryable_gemini_error(exc: Exception) -> bool:
    """判断异常是否属于可重试的临时错误。"""

    error_text = str(exc).lower()

    return any(
        marker in error_text
        for marker in _RETRYABLE_GEMINI_ERRORS
    )


def _generate_content_with_retry(
    client: genai.Client,
    model: str,
    prompt: str,
    max_attempts: int = 3,
) -> Any:
    """调用 Gemini，遇到临时异常时自动重试。

    等待间隔：
    第一次失败后等待 1 秒；
    第二次失败后等待 2 秒；
    第三次仍失败则抛出临时不可用异常。
    """

    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return client.models.generate_content(
                model=model,
                contents=prompt,
            )

        except Exception as exc:
            last_error = exc

            if not _is_retryable_gemini_error(exc):
                raise LLMServiceError(
                    "智能回答服务调用失败，请检查配置或稍后重试。"
                ) from exc

            if attempt < max_attempts:
                wait_seconds = 2 ** (attempt - 1)
                time.sleep(wait_seconds)

    raise LLMTemporaryUnavailableError(
        "当前智能回答服务繁忙，已暂时切换为说明书原文回答。"
    ) from last_error


def _format_contexts(
    contexts: list[dict[str, Any]],
) -> str:
    """把检索返回的说明书片段整理成提示词文本。"""

    if not contexts:
        raise LLMServiceError(
            "没有可供大模型参考的说明书片段"
        )

    max_chars_text = os.getenv(
        "LLM_MAX_CONTEXT_CHARS",
        "12000",
    )

    try:
        max_chars = int(max_chars_text)
    except ValueError:
        max_chars = 12000

    blocks: list[str] = []

    for index, item in enumerate(contexts, start=1):
        source_file = (
            item.get("source_file")
            or "未知文件"
        )

        page = item.get("page")

        section = (
            item.get("section")
            or "未标注章节"
        )

        content = str(
            item.get("content") or ""
        ).strip()

        if not content:
            continue

        page_text = (
            f"第{page}页"
            if page not in (None, "")
            else "页码未知"
        )

        blocks.append(
            "\n".join(
                [
                    f"〖片段{index}〗",
                    f"文件：{source_file}",
                    f"页码：{page_text}",
                    f"章节：{section}",
                    f"原文：{content}",
                ]
            )
        )

    context_text = "\n\n".join(blocks)

    if not context_text:
        raise LLMServiceError(
            "说明书片段中没有有效正文"
        )

    return context_text[:max_chars]


def generate_manual_answer(
    question: str,
    contexts: list[dict[str, Any]],
    product_name: str | None = None,
) -> str:
    """严格根据说明书片段生成回答。

    Args:
        question: 用户问题。
        contexts: 检索出的说明书片段。
        product_name: 当前咨询的产品名称。

    Returns:
        Gemini 生成的回答文本。
    """

    cleaned_question = question.strip()

    if not cleaned_question:
        raise LLMServiceError(
            "用户问题不能为空"
        )

    context_text = _format_contexts(contexts)

    model = os.getenv(
        "GEMINI_MODEL",
        "gemini-3.5-flash",
    ).strip()

    if not model:
        raise LLMServiceError(
            "GEMINI_MODEL 不能为空"
        )

    product_text = (
        product_name
        or "当前所选耳机"
    )

    prompt = f"""
你是“小米智能产品选购与客服助手”中的说明书问答模块。

当前产品：{product_text}

请严格遵守以下规则：
1. 只能根据下方提供的说明书片段回答。
2. 不得使用片段之外的常识补充答案。
3. 不得混用其他型号产品的信息。
4. 如果片段不足以回答，请只说明：
“未在该产品说明书中找到可靠依据。”
5. 操作类问题请使用清晰的分步表达。
6. 不要虚构文件名、页码、参数或功能。
7. 使用简洁、自然的中文回答。
8. 来源信息由后端单独返回，回答正文中不必重复列出来源。

用户问题：
{cleaned_question}

说明书片段：
{context_text}
""".strip()

    client = _get_client()

    response = _generate_content_with_retry(
        client=client,
        model=model,
        prompt=prompt,
        max_attempts=3,
    )

    answer = str(
        response.text or ""
    ).strip()

    if not answer:
        raise LLMServiceError(
            "Gemini 没有返回有效文本"
        )

    return answer