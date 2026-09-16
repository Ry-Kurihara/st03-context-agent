"""プロンプトのメタ情報レジストリ。

- 組み込みプロンプト: このファイルの `_BUILTIN` と同ディレクトリの `.md`
- ユーザー追加プロンプト: `user/` ディレクトリ＋`user/index.json`
  （画面「⚙️ プロンプト管理」から保存されたもの）
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_USER_DIR = _DIR / "user"
_USER_INDEX = _USER_DIR / "index.json"


@dataclass(frozen=True)
class PromptSpec:
    id: str
    label: str
    kind: str  # "analysis" | "reply"
    file: str
    input_unit: str = "thread"  # "thread" | "mail" | "-"
    schema_version: str = "v3"  # "v3" | "v0" | "-"
    notes: str = ""
    tokens: tuple[str, ...] = ()
    group: str = ""
    builtin: bool = True
    extra: dict = field(default_factory=dict)


_BUILTIN: tuple[PromptSpec, ...] = (
    PromptSpec(
        id="analysis_v3_20260729",
        label="【最新】改良版（2026-07-29）",
        kind="analysis",
        file="analysis_v3_20260729.md",
        input_unit="thread",
        schema_version="v3",
        tokens=("EMAIL_THREAD",),
        group="ステージ1：感情パラメータ化",
        notes="ルーブリック／立場・役職補正／相談メールの初動リスクを含む。7指標＋論拠＋総合評価をJSONで返す。",
    ),
    PromptSpec(
        id="analysis_v0_baseline",
        label="【旧版】プロトタイプ初期版（比較用）",
        kind="analysis",
        file="analysis_v0_baseline.md",
        input_unit="mail",
        schema_version="v0",
        tokens=("SUBJECT", "SENDER", "RECEIVED_AT", "BODY"),
        group="ステージ1：感情パラメータ化",
        notes="3指標＋優先度のみ。改良の効果を比較するためのベースライン。",
    ),
    PromptSpec(
        id="reply_r1_plain",
        label="案①-A 感情言語化なし（事実ベース）",
        kind="reply",
        file="reply_r1_plain.md",
        input_unit="-",
        schema_version="-",
        tokens=("PARAMETERS", "EMAIL"),
        group="案① 感情の言語化",
    ),
    PromptSpec(
        id="reply_r1_verbalize",
        label="案①-B 感情言語化あり",
        kind="reply",
        file="reply_r1_verbalize.md",
        input_unit="-",
        schema_version="-",
        tokens=("PARAMETERS", "EMAIL"),
        group="案① 感情の言語化",
    ),
    PromptSpec(
        id="reply_r1_plain_v2",
        label="案①-A 感情言語化なし・配慮はにじませる（0909改訂版）",
        kind="reply",
        file="reply_r1_plain_v2.md",
        input_unit="-",
        schema_version="-",
        tokens=("PARAMETERS", "EMAIL"),
        group="案① 感情の言語化（0909改訂版）",
        notes="配慮は感情への言及ではなく、対応の誠実さ・先回りした説明・次の行動の明示で表現する。",
    ),
    PromptSpec(
        id="reply_r1_verbalize_v2",
        label="案①-B 感情言語化あり・断定しない（0909改訂版）",
        kind="reply",
        file="reply_r1_verbalize_v2.md",
        input_unit="-",
        schema_version="-",
        tokens=("PARAMETERS", "EMAIL"),
        group="案① 感情の言語化（0909改訂版）",
        notes="共感→状況整理→対応策提示の順。避ける表現（強い断定・共感直後の打ち消し等）を明記。",
    ),
    PromptSpec(
        id="reply_r2_fact",
        label="案②-A 事実重視型",
        kind="reply",
        file="reply_r2_fact.md",
        input_unit="-",
        schema_version="-",
        tokens=("PARAMETERS", "EMAIL"),
        group="案② 共感の出し方",
    ),
    PromptSpec(
        id="reply_r2_empathy_first",
        label="案②-B 共感先行型",
        kind="reply",
        file="reply_r2_empathy_first.md",
        input_unit="-",
        schema_version="-",
        tokens=("PARAMETERS", "EMAIL"),
        group="案② 共感の出し方",
    ),
    PromptSpec(
        id="reply_r2_empathy_organized",
        label="案②-C 共感＋整理型",
        kind="reply",
        file="reply_r2_empathy_organized.md",
        input_unit="-",
        schema_version="-",
        tokens=("PARAMETERS", "EMAIL"),
        group="案② 共感の出し方",
    ),
    PromptSpec(
        id="reply_r3_no_hypothesis",
        label="案③-A 背景に触れない",
        kind="reply",
        file="reply_r3_no_hypothesis.md",
        input_unit="-",
        schema_version="-",
        tokens=("PARAMETERS", "EMAIL"),
        group="案③ 背景仮説の提示",
    ),
    PromptSpec(
        id="reply_r3_hypothesis",
        label="案③-B 背景仮説あり（スレッド全文推奨）",
        kind="reply",
        file="reply_r3_hypothesis.md",
        input_unit="-",
        schema_version="-",
        tokens=("PARAMETERS", "EMAIL"),
        group="案③ 背景仮説の提示",
    ),
    PromptSpec(
        id="reply_blank",
        label="自由記述の雛形（自分で書く用）",
        kind="reply",
        file="reply_blank.md",
        input_unit="-",
        schema_version="-",
        tokens=("PARAMETERS", "EMAIL"),
        group="自由",
        notes="コピーして書き換える出発点。",
    ),
)

DEFAULT_ANALYSIS_PROMPT = "analysis_v3_20260729"
DEFAULT_REPLY_PROMPT_A = "reply_r1_plain"
DEFAULT_REPLY_PROMPT_B = "reply_r1_verbalize"

# 受信トレイ（デモ）の返信3択。画面には研究用語ではなく利用者の言葉を出す。
DEMO_REPLY_PROMPTS: tuple[tuple[str, str], ...] = (
    ("簡潔に伝える", "reply_r1_plain_v2"),
    ("配慮を添える", "reply_r1_verbalize_v2"),
    ("配慮＋論点整理", "reply_r2_empathy_organized"),
)

# 各書き方が向く場面（最終報告（３）の結論に対応させる）
DEMO_REPLY_SCENES: dict[str, str] = {
    "簡潔に伝える": "通常の確認・進捗連絡向け。感情には触れず、対応方針・連絡予定・見通しで配慮を示します。",
    "配慮を添える": "お詫び・念のための確認・相手への寄り添いが必要な場面向け。受け止めてから対応へつなぎます。",
    "配慮＋論点整理": "行き違いや未解決事項がある場面向け。共感のうえで経緯と論点を整理します（検証で最高評価）。",
}


def prompts_dir() -> Path:
    return _DIR


def user_dir() -> Path:
    return _USER_DIR


def _load_user_specs() -> list[PromptSpec]:
    if not _USER_INDEX.exists():
        return []
    try:
        raw = json.loads(_USER_INDEX.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    specs: list[PromptSpec] = []
    for item in raw:
        # ファイルが無い（手で消した・コンテナが再作成された）エントリは無視する
        if not (_USER_DIR / str(item.get("file", ""))).exists():
            continue
        try:
            specs.append(
                PromptSpec(
                    id=item["id"],
                    label=item.get("label", item["id"]),
                    kind=item.get("kind", "analysis"),
                    file=item["file"],
                    input_unit=item.get("input_unit", "thread"),
                    schema_version=item.get("schema_version", "v3"),
                    notes=item.get("notes", ""),
                    tokens=tuple(item.get("tokens", ())),
                    group=item.get("group", "追加ぶん（アプリから保存）"),
                    builtin=False,
                )
            )
        except KeyError:
            continue
    return specs


def _all_specs() -> list[PromptSpec]:
    return list(_BUILTIN) + _load_user_specs()


def list_prompts(kind: str | None = None) -> list[PromptSpec]:
    specs = _all_specs()
    if kind is None:
        return specs
    return [spec for spec in specs if spec.kind == kind]


def get_spec(prompt_id: str) -> PromptSpec:
    for spec in _all_specs():
        if spec.id == prompt_id:
            return spec
    raise KeyError(f"未登録のプロンプトIDです: {prompt_id}")


def _path_of(spec: PromptSpec) -> Path:
    return (_USER_DIR if not spec.builtin else _DIR) / spec.file


def load_prompt(prompt_id: str) -> str:
    """指示文の原文をそのまま返す（加工しない）。"""
    return _path_of(get_spec(prompt_id)).read_text(encoding="utf-8")


def _slugify(label: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", label).strip("_").lower()
    return slug or "prompt"


def save_prompt(
    text: str,
    *,
    label: str,
    kind: str = "analysis",
    input_unit: str = "thread",
    schema_version: str = "v3",
    notes: str = "",
    prompt_id: str | None = None,
) -> PromptSpec:
    """アプリから編集した指示文を `user/` に保存し、レジストリに登録する。

    組み込みプロンプトは上書きしない（原文を残すため）。同名IDは上書き。
    """
    import prompt_loader  # 遅延importで循環を避ける

    _USER_DIR.mkdir(parents=True, exist_ok=True)
    pid = prompt_id or f"user_{kind}_{_slugify(label)}"
    if any(spec.id == pid for spec in _BUILTIN):
        pid = f"{pid}_edited"
    filename = f"{pid}.md"
    (_USER_DIR / filename).write_text(text, encoding="utf-8")

    entries = [
        item
        for item in (json.loads(_USER_INDEX.read_text(encoding="utf-8")) if _USER_INDEX.exists() else [])
        if item.get("id") != pid
    ]
    entries.append(
        {
            "id": pid,
            "label": label,
            "kind": kind,
            "file": filename,
            "input_unit": input_unit,
            "schema_version": schema_version,
            "notes": notes,
            "tokens": list(prompt_loader.find_tokens(text)),
        }
    )
    _USER_INDEX.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_spec(pid)


def delete_user_prompt(prompt_id: str) -> None:
    spec = get_spec(prompt_id)
    if spec.builtin:
        raise ValueError("組み込みプロンプトは削除できません")
    path = _path_of(spec)
    if path.exists():
        path.unlink()
    entries = [
        item
        for item in (json.loads(_USER_INDEX.read_text(encoding="utf-8")) if _USER_INDEX.exists() else [])
        if item.get("id") != prompt_id
    ]
    _USER_INDEX.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
