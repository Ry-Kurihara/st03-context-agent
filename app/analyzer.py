"""ステージ1：感情パラメータ化（Gemini呼び出し）。

プロンプトはこのファイルに埋め込まず `prompts/` から読む。
指示文の更新主体（吉田さん）がPythonを触らずに差し替えられるようにするため。
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Sequence

import llm
import prompt_loader
import schema
import thread as thread_mod
from llm import DEFAULT_MODEL, DEFAULT_TEMPERATURE  # noqa: F401 (再公開)
from prompts import registry
from schema import AnalysisParseError, AnalysisResult

DEFAULT_PROMPT_ID = registry.DEFAULT_ANALYSIS_PROMPT

RETRY_SUFFIX = (
    "\n\n# 追加指示（再出力）\n"
    "先ほどの応答からJSONを読み取れませんでした。"
    "解説や前置きを一切付けず、指定された構造のJSONだけを出力してください。"
)


def _token_values(target: thread_mod.Thread | dict[str, Any]) -> dict[str, str]:
    """プロンプトが要求しうるトークンの値をまとめて作る。"""
    if isinstance(target, thread_mod.Thread):
        last = target.last_mail
        thread_text = thread_mod.format_thread(target)
    else:
        last = target
        thread_text = thread_mod.format_mail(target)
    return {
        "EMAIL_THREAD": thread_text,
        "SUBJECT": str(last.get("subject", "")),
        "SENDER": str(last.get("sender", "")),
        "RECEIVED_AT": str(last.get("received_at", "")),
        "BODY": str(last.get("body", "")),
    }


def build_prompt(target: thread_mod.Thread | dict[str, Any], *, prompt_id: str) -> str:
    """指示文にメール（スレッド）を差し込んだ、実際に送るプロンプト全文。"""
    spec = registry.get_spec(prompt_id)
    template = registry.load_prompt(prompt_id)
    return prompt_loader.render_available(template, _token_values(target))


def cache_key(
    target: thread_mod.Thread | dict[str, Any],
    *,
    prompt_id: str,
    model_name: str | None,
    temperature: float,
) -> str:
    """同じ条件の再実行で二重課金しないためのキー。"""
    payload = {
        "input": thread_mod.target_text(target),
        "prompt_id": prompt_id,
        "prompt": registry.load_prompt(prompt_id) if _prompt_exists(prompt_id) else "",
        "model": model_name or llm.default_model(),
        "temperature": temperature,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _prompt_exists(prompt_id: str) -> bool:
    try:
        registry.get_spec(prompt_id)
    except KeyError:
        return False
    return True


def analyze(
    target: thread_mod.Thread | dict[str, Any],
    *,
    prompt_id: str = DEFAULT_PROMPT_ID,
    model_name: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    client: Any = None,
) -> AnalysisResult:
    """1スレッド（または1通）を解析する。JSONが読めなければ1回だけ再試行する。"""
    spec = registry.get_spec(prompt_id)  # 未登録なら KeyError（API呼び出し前に落とす）
    prompt = build_prompt(target, prompt_id=prompt_id)
    model = model_name or llm.default_model()
    meta = {
        "prompt_id": prompt_id,
        "prompt_label": spec.label,
        "schema_version": spec.schema_version,
        "input_unit": "thread" if isinstance(target, thread_mod.Thread) else "mail",
        "model": model,
        "temperature": temperature,
        "target_key": thread_mod.target_key(target),
    }

    text = llm.call_text(prompt, client=client, model_name=model, temperature=temperature)
    try:
        return schema.parse_analysis(text, meta=meta)
    except AnalysisParseError:
        retry_text = llm.call_text(
            prompt + RETRY_SUFFIX, client=client, model_name=model, temperature=temperature
        )
        result = schema.parse_analysis(retry_text, meta={**meta, "retried": True})
        return result


def analyze_email(
    email: dict[str, Any],
    *,
    model_name: str | None = None,
    prompt_id: str = DEFAULT_PROMPT_ID,
    temperature: float = DEFAULT_TEMPERATURE,
    client: Any = None,
) -> AnalysisResult:
    """旧APIの互換ラッパ（1通ずつ解析）。"""
    return analyze(
        email,
        prompt_id=prompt_id,
        model_name=model_name,
        temperature=temperature,
        client=client,
    )


def analyze_many(
    targets: Sequence[thread_mod.Thread | dict[str, Any]],
    *,
    prompt_id: str = DEFAULT_PROMPT_ID,
    model_name: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    client: Any = None,
    max_workers: int = 4,
    on_done: Callable[[int, int, str, Exception | None], None] | None = None,
) -> dict[str, AnalysisResult]:
    """複数を並列に解析し、`{target_key: AnalysisResult}` を返す。

    失敗したものは結果に含めず、`on_done` に例外を渡す（呼び出し側で表示する）。
    """
    results: dict[str, AnalysisResult] = {}
    total = len(targets)
    if total == 0:
        return results

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, total))) as executor:
        futures = {
            executor.submit(
                analyze,
                target,
                prompt_id=prompt_id,
                model_name=model_name,
                temperature=temperature,
                client=client,
            ): target
            for target in targets
        }
        done = 0
        for future in as_completed(futures):
            target = futures[future]
            key = thread_mod.target_key(target)
            error: Exception | None = None
            try:
                results[key] = future.result()
            except Exception as exc:  # UIに出すため握る
                error = exc
            done += 1
            if on_done is not None:
                on_done(done, total, key, error)
    return results
