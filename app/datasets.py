"""同梱メールデータセットの定義と読み込み。

チーム全員が同じサンプルで検証できるよう、3種類を最初から同梱する。
変換（xlsx / .eml → JSON）はアプリ起動時には走らせず、
`scripts/convert_sources.py` で事前に1回だけ実施して `data/` に置いてある。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass(frozen=True)
class DatasetSpec:
    id: str
    label: str
    file: str
    description: str
    source: str = ""
    note: str = ""


BUILTIN: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        id="akagi_demo",
        label="① 赤木さんデモメール（関係良好10通／関係険悪5通）",
        file="akagi_demo_emails.json",
        description="吉田さん・廣瀬さんの検証で使われたデモメール。プロンプト改良の定点観測に使う。",
        source="デモ用サンプルメール（赤木さん・良好険悪）/インプットデータ（良好、険悪）.xlsx",
        note="xlsxの「関係険悪」シート6〜10行目は「関係良好」と同一文面（お礼メール）のため除外し、険悪は5通としている。",
    ),
    DatasetSpec(
        id="mixed_emotion_50",
        label="② 混在感情メール（50通）",
        file="mixed_emotion_50.json",
        description="丁寧だが婉曲な断り・混在感情のサンプル。平井さんのIBMツールと同一入力。",
        source="デモ用サンプルメール（感情入り混じった版✕50通）/*.eml",
    ),
    DatasetSpec(
        id="sample_v2",
        label="③ プロトタイプ用モックメール（TO/CC・署名の役職つき）",
        file="sample_emails_v2.json",
        description="スレッド・役職・CC補正ルールの動作確認用。役職あり／なしの対照ペアを含む。",
        source="data/sample_emails.json を拡張",
    ),
    DatasetSpec(
        id="sample_v1",
        label="（旧）プロトタイプ用モックメール 20通",
        file="sample_emails.json",
        description="中間発表2時点のデータ。TO/CC・署名を持たない。互換確認用。",
    ),
)


def data_dir() -> Path:
    return _DATA_DIR


def list_datasets() -> list[DatasetSpec]:
    return [spec for spec in BUILTIN if (_DATA_DIR / spec.file).exists()]


def get_spec(dataset_id: str) -> DatasetSpec:
    for spec in BUILTIN:
        if spec.id == dataset_id:
            return spec
    raise KeyError(f"未登録のデータセットIDです: {dataset_id}")


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value)
    parts = [part.strip() for part in text.replace(";", ",").split(",")]
    return [part for part in parts if part]


def normalize_mail(raw: dict[str, Any], *, index: int = 0, prefix: str = "mail") -> dict[str, Any]:
    """アプリ内で扱う形にそろえる（欠けているキーを埋める）。"""
    mail_id = str(raw.get("id") or f"{prefix}-{index + 1:03d}")
    mail: dict[str, Any] = {
        "id": mail_id,
        "thread_id": str(raw.get("thread_id") or mail_id),
        "subject": str(raw.get("subject") or ""),
        "sender": str(raw.get("sender") or raw.get("from") or ""),
        "to": _as_list(raw.get("to")),
        "cc": _as_list(raw.get("cc")),
        "received_at": raw.get("received_at") or raw.get("date") or None,
        "body": str(raw.get("body") or ""),
    }
    for optional in ("signature", "category", "source", "message_id", "references", "in_reply_to", "note"):
        if raw.get(optional) not in (None, "", []):
            mail[optional] = raw[optional]
    return mail


def normalize_all(raws: Iterable[dict[str, Any]], *, prefix: str = "mail") -> list[dict[str, Any]]:
    return [normalize_mail(raw, index=i, prefix=prefix) for i, raw in enumerate(raws)]


def load_dataset(dataset_id: str) -> list[dict[str, Any]]:
    spec = get_spec(dataset_id)
    path = _DATA_DIR / spec.file
    with path.open(encoding="utf-8") as f:
        raws = json.load(f)
    return normalize_all(raws, prefix=dataset_id)


def merge_datasets(*mail_lists: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """複数のメール一覧を連結する。IDが衝突したら `#2` を付けて一意にする。"""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mails in mail_lists:
        for mail in mails:
            item = dict(mail)
            base_id = str(item.get("id") or "mail")
            mail_id = base_id
            suffix = 2
            while mail_id in seen:
                mail_id = f"{base_id}#{suffix}"
                suffix += 1
            if mail_id != base_id:
                if item.get("thread_id") == base_id:
                    item["thread_id"] = mail_id
                item["id"] = mail_id
            seen.add(mail_id)
            merged.append(item)
    return merged


def to_json(mails: Iterable[dict[str, Any]]) -> str:
    """日本語をそのまま読める形（\\uXXXX にしない）で書き出す。"""
    return json.dumps(list(mails), ensure_ascii=False, indent=2)
