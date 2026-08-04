"""研究ステージ2：返信案の生成。

固定Input（① 分析結果パラメータ ／ ② メール本文）と、
可変Input（③④ 返信生成プロンプト A・B）を組み合わせてLLMに投げる。
返信文を書くのは人ではなくLLMで、人が書き分けるのは指示文だけ、という切り分け。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import llm
import prompt_loader


class ReplyGenerationError(RuntimeError):
    """返信案を生成できなかった。"""


@dataclass
class ReplyResult:
    text: str
    prompt: str
    meta: dict[str, Any] = field(default_factory=dict)


def parameters_from_result(result: Any) -> dict[str, Any]:
    """`AnalysisResult` を、返信生成プロンプトに渡す形へ整える（未評価の項目は落とす）。"""
    scores = {k: v for k, v in (result.scores or {}).items() if v is not None}
    reasoning = {k: v for k, v in (result.reasoning or {}).items() if v}
    params: dict[str, Any] = {"scores": scores}
    if result.priority_score is not None:
        params["priorityScore"] = result.priority_score
    params["priorityLabel"] = result.priority_label
    if result.summary:
        params["summary"] = result.summary
    if reasoning:
        params["reasoning"] = reasoning
    return params


def _as_text(parameters: Any) -> str:
    if isinstance(parameters, str):
        return parameters
    # 日本語をそのまま読めるようにする（\uXXXX にしない）
    return json.dumps(parameters, ensure_ascii=False, indent=2)


def build_reply_prompt(template: str, *, mail_text: str, parameters: Any) -> str:
    return prompt_loader.render_available(
        template,
        {"PARAMETERS": _as_text(parameters), "EMAIL": mail_text},
    )


def _strip_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def generate_reply(
    template: str,
    *,
    mail_text: str,
    parameters: Any,
    client: Any = None,
    model_name: str | None = None,
    temperature: float = llm.DEFAULT_TEMPERATURE,
    label: str = "",
) -> ReplyResult:
    prompt = build_reply_prompt(template, mail_text=mail_text, parameters=parameters)
    model = model_name or llm.default_model()
    text = llm.call_text(prompt, client=client, model_name=model, temperature=temperature)
    body = _strip_fence(text)
    if not body:
        raise ReplyGenerationError("返信案が空でした。もう一度実行してください。")
    return ReplyResult(
        text=body,
        prompt=prompt,
        meta={"model": model, "temperature": temperature, "label": label},
    )


def generate_reply_pair(
    template_a: str,
    template_b: str,
    *,
    mail_text: str,
    parameters: Any,
    client: Any = None,
    model_name: str | None = None,
    temperature: float = llm.DEFAULT_TEMPERATURE,
) -> tuple[ReplyResult, ReplyResult]:
    """A/Bを**同じモデル・同じ設定**で生成する（差が指示文の差だけになるように）。"""
    model = model_name or llm.default_model()
    common = {
        "mail_text": mail_text,
        "parameters": parameters,
        "client": client,
        "model_name": model,
        "temperature": temperature,
    }
    res_a = generate_reply(template_a, label="A", **common)
    res_b = generate_reply(template_b, label="B", **common)
    return res_a, res_b
