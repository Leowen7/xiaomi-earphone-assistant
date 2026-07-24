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
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)

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

    product_text = (
        product_name
        or "当前所选产品"
    )

    system_prompt = """
你是“小米智能产品选购与客服助手”中的说明书问答模块。

必须严格遵守以下规则：

1. 只能根据系统提供的说明书片段回答。
2. 不得使用说明书片段之外的模型知识补充答案。
3. 不得混用其他型号产品的信息。
4. 如果片段不足以回答，必须回答：
“未在该产品说明书中找到可靠依据。”
5. 操作类问题应使用清晰的分步表达。
6. 不得虚构文件名、页码、参数、功能或操作步骤。
7. 使用简洁、自然、容易理解的中文回答。
8. 来源由后端单独返回，回答正文中不需要重复列出来源。
""".strip()

    user_prompt = f"""
【当前产品】
{product_text}

【用户问题】
{cleaned_question}

【说明书检索片段】
{context_text}

请严格依据以上说明书片段回答。
""".strip()

    answer = _generate_dual_mode_text(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=0.2,
        max_attempts=3,
    )

    if not answer:
        raise LLMServiceError(
            "硅基流动没有返回有效文本"
        )

    return answer
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types


# ============================================================
# 1. 小米产品知识库问答提示词
# ============================================================

PRODUCT_SYSTEM_PROMPT = """
你是“小米智能客服机器人”，主要负责回答小米和REDMI耳机、
智能手环、智能手表相关的问题。

系统会向你提供产品参数、官方资料或产品说明书片段。

你必须遵守以下规则：

1. 产品参数、功能、兼容性和操作步骤必须以提供的资料为准。
2. 不允许使用模型记忆补充资料中没有的产品参数。
3. 不允许编造产品价格、促销、功能、发布日期或操作步骤。
4. 如果提供的资料中没有答案，应明确回答：
“当前知识库中没有找到足够的可靠资料。”
5. 如果用户没有说明具体产品，应提醒用户补充产品名称或型号。
6. 推荐产品时，需要说明推荐理由和适用场景。
7. 对比产品时，应根据资料客观说明差异。
8. 心率、血氧和睡眠数据只能作为日常健康参考，不能用于医疗诊断。
9. 使用简洁、自然、容易理解的中文回答。
"""


# ============================================================
# 2. 有限通用开放式问答提示词
# ============================================================

GENERAL_SYSTEM_PROMPT = """
你是嵌入在“小米智能客服机器人”中的通用对话助手。

系统的核心任务是提供小米耳机、智能手环和智能手表客服，
同时允许你处理有限的通用开放式问题，例如：

- 普通常识；
- 学习类问题；
- 简单写作；
- 日常交流；
- 非实时生活建议。

你必须遵守以下规则：

1. 回答应简洁、自然、友好。
2. 不得声称自己查询了实时网络。
3. 不得编造实时价格、促销、新闻、天气或库存信息。
4. 不进行医疗诊断、法律裁决或投资收益保证。
5. 用户询问具体小米产品参数时，不得凭模型记忆回答。
6. 遇到无法可靠回答的问题，应明确说明能力边界。
7. 不需要在每次回答中强行推荐小米产品。
"""


# ============================================================
# 3. Gemini客户端
# ============================================================

_dual_mode_client: OpenAI | None = None


_RETRYABLE_SILICONFLOW_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}


def _get_dual_mode_client() -> OpenAI:
    """
    创建硅基流动客户端。

    使用延迟初始化，避免导入模块时就发起网络请求。
    """
    global _dual_mode_client

    if _dual_mode_client is not None:
        return _dual_mode_client

    api_key = os.getenv(
        "SILICONFLOW_API_KEY",
        "",
    ).strip()

    base_url = os.getenv(
        "SILICONFLOW_BASE_URL",
        "https://api.siliconflow.cn/v1",
    ).strip()

    if not api_key:
        raise LLMServiceError(
            "没有读取到 SILICONFLOW_API_KEY，"
            "请检查仓库根目录下的 .env 文件。"
        )

    if not base_url:
        raise LLMServiceError(
            "SILICONFLOW_BASE_URL 不能为空。"
        )

    _dual_mode_client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=60.0,
        # 由下面的函数统一控制重试，避免重复重试。
        max_retries=0,
    )

    return _dual_mode_client


def _generate_dual_mode_text(
    user_prompt: str,
    system_prompt: str,
    temperature: float = 0.3,
    max_attempts: int = 3,
) -> str:
    """
    产品问答和通用问答共用的硅基流动调用函数。
    """
    client = _get_dual_mode_client()

    model_name = os.getenv(
        "SILICONFLOW_MODEL",
        "Qwen/Qwen3-8B",
    ).strip()

    if not model_name:
        raise LLMServiceError(
            "SILICONFLOW_MODEL 不能为空。"
        )

    request_kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": temperature,
        "max_tokens": 1000,
    }

    # Qwen3 默认可能启用思考模式。
    # 客服问答关闭思考可以降低延迟和Token消耗。
    if "qwen3" in model_name.lower():
        request_kwargs["extra_body"] = {
            "enable_thinking": False,
        }

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.chat.completions.create(
                **request_kwargs
            )

            if not response.choices:
                raise LLMServiceError(
                    "硅基流动没有返回任何候选回答。"
                )

            answer = str(
                response.choices[0].message.content or ""
            ).strip()

            if not answer:
                raise LLMServiceError(
                    "硅基流动返回了空回答。"
                )

            return answer

        except APIStatusError as exc:
            status_code = getattr(
                exc,
                "status_code",
                None,
            )

            if status_code == 401:
                raise LLMServiceError(
                    "硅基流动 API Key 无效，"
                    "请检查 SILICONFLOW_API_KEY。"
                ) from exc

            if status_code == 402:
                raise LLMServiceError(
                    "硅基流动账户余额不足，"
                    "请充值后重新尝试。"
                ) from exc

            if status_code == 403:
                raise LLMServiceError(
                    "当前账户没有该模型的使用权限，"
                    "请检查实名认证和模型权限。"
                ) from exc

            if status_code in _RETRYABLE_SILICONFLOW_STATUS_CODES:
                if attempt < max_attempts:
                    wait_seconds = 2 ** (attempt - 1)
                    time.sleep(wait_seconds)
                    continue

                raise LLMTemporaryUnavailableError(
                    "硅基流动服务当前繁忙，"
                    "多次重试后仍未恢复。"
                ) from exc

            raise LLMServiceError(
                f"硅基流动调用失败，"
                f"HTTP状态码：{status_code}。"
            ) from exc

        except (APIConnectionError, APITimeoutError) as exc:
            if attempt < max_attempts:
                wait_seconds = 2 ** (attempt - 1)
                time.sleep(wait_seconds)
                continue

            raise LLMTemporaryUnavailableError(
                "连接硅基流动服务失败，"
                "请检查网络后重试。"
            ) from exc

        except LLMServiceError:
            raise

        except Exception as exc:
            raise LLMServiceError(
                f"硅基流动服务调用异常：{exc}"
            ) from exc

    raise LLMTemporaryUnavailableError(
        "硅基流动服务暂时不可用。"
    )

# ============================================================
# 5. 产品知识库问答函数
# ============================================================

def generate_product_answer(
    question: str,
    context: str,
    history_text: str = "",
) -> str:
    """
    根据知识库资料回答小米产品问题。

    question：
        用户提出的问题。

    context：
        FAISS检索到的产品参数、说明书或官方资料。

    history_text：
        最近几轮对话，可不传。
    """
    question = str(question or "").strip()
    context = str(context or "").strip()
    history_text = str(history_text or "").strip()

    if not question:
        raise ValueError("question不能为空。")

    if not context:
        return (
            "当前知识库中没有找到足够的可靠资料。"
            "请补充具体产品名称或型号后重新提问。"
        )

    user_prompt = f"""
【最近对话】
{history_text if history_text else "无"}

【知识库资料】
{context}

【用户问题】
{question}

请严格根据知识库资料回答用户问题。

要求：
1. 资料中没有明确说明的内容不得推测。
2. 不得编造产品参数或功能。
3. 回答中不要提到“提示词”或“上下文”。
"""

    return _generate_dual_mode_text(
        user_prompt=user_prompt,
        system_prompt=PRODUCT_SYSTEM_PROMPT,
        temperature=0.2,
    )


# ============================================================
# 6. 通用开放式问答函数
# ============================================================

def generate_general_answer(
    question: str,
    history_text: str = "",
) -> str:
    """
    回答有限的通用开放式问题。

    该函数不会使用产品知识库。
    """
    question = str(question or "").strip()
    history_text = str(history_text or "").strip()

    if not question:
        raise ValueError("question不能为空。")

    user_prompt = f"""
【最近对话】
{history_text if history_text else "无"}

【用户问题】
{question}

请直接回答用户问题。

如果问题涉及实时价格、实时新闻、实时天气、医疗诊断、
法律裁决或投资收益保证，请明确说明当前系统无法提供可靠结论。
"""

    return _generate_dual_mode_text(
        user_prompt=user_prompt,
        system_prompt=GENERAL_SYSTEM_PROMPT,
        temperature=0.5,
    )