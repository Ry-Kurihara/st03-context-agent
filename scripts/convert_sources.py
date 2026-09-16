#!/usr/bin/env python3
"""元データ（xlsx / .eml / 旧JSON）を、アプリ同梱の JSON に変換する開発用スクリプト。

メンバーがこれを実行する必要はない（生成済みJSONをリポジトリに同梱している）。
元データが更新されたときだけ、開発側でこれを回して `data/*.json` を作り直す。

    python scripts/convert_sources.py            # 3ファイルすべて生成
    python scripts/convert_sources.py relation      # 一部だけ生成

生成物:
    data/relation_mixed_emails.json   関係性混在メール（関係良好10通／関係険悪5通）
    data/mixed_emotion_50.json    混在感情メール50通（.eml から）
    data/sample_emails_v2.json    モックメール（TO/CC・署名の役職つき／対照ペア追加）
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT.parent
DATA_DIR = REPO_ROOT / "data"
sys.path.insert(0, str(REPO_ROOT / "app"))

import eml_loader  # noqa: E402
from datasets import normalize_all, to_json  # noqa: E402

# 元データのフォルダ名は作成者名を含むため、ワイルドカードで探す
RELATION_XLSX = next(
    iter(sorted(WORKSPACE.glob("デモ用サンプルメール（*良好険悪）/インプットデータ（良好、険悪）.xlsx"))),
    WORKSPACE / "デモ用サンプルメール（良好険悪）" / "インプットデータ（良好、険悪）.xlsx",
)
EML_DIR = WORKSPACE / "デモ用サンプルメール（感情入り混じった版✕50通）"

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_SUBJECT_LINE_RE = re.compile(r"^\s*(?:件)?名[：:]\s*(.*)$")

ME = "me@your-company.com"


# --------------------------------------------------------------------------
# ① 関係性混在メール（xlsx）
# --------------------------------------------------------------------------
def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(NS + "t")) for si in root.iter(NS + "si")]


def _sheet_rows(zf: zipfile.ZipFile, sheet_path: str) -> list[list[str]]:
    strings = _shared_strings(zf)
    root = ET.fromstring(zf.read(sheet_path))
    rows = []
    for row in root.iter(NS + "row"):
        cells = []
        for cell in row.iter(NS + "c"):
            v = cell.find(NS + "v")
            is_ = cell.find(NS + "is")
            if cell.get("t") == "s" and v is not None:
                cells.append(strings[int(v.text)])
            elif is_ is not None:
                cells.append("".join(t.text or "" for t in is_.iter(NS + "t")))
            elif v is not None:
                cells.append(v.text or "")
        if cells:
            rows.append(cells)
    return rows


def _split_subject_and_body(raw: str) -> tuple[str, str]:
    lines = [line.rstrip() for line in raw.strip().splitlines()]
    subject = ""
    body_lines = []
    for line in lines:
        match = _SUBJECT_LINE_RE.match(line) if not subject else None
        if match:
            subject = match.group(1).strip()
            continue
        body_lines.append(line)
    body = "\n".join(body_lines).strip()
    return subject or "（件名なし）", body


def build_relation_mixed() -> list[dict]:
    if not RELATION_XLSX.exists():
        raise SystemExit(f"元データが見つかりません: {RELATION_XLSX}")
    zf = zipfile.ZipFile(RELATION_XLSX)
    sheets = {"関係良好": "xl/worksheets/sheet1.xml", "関係険悪": "xl/worksheets/sheet2.xml"}

    mails: list[dict] = []
    seen_bodies: set[str] = set()
    for category, sheet_path in sheets.items():
        rows = _sheet_rows(zf, sheet_path)
        texts = [row[1] for row in rows if len(row) >= 2 and row[0].strip().isdigit()]
        index = 0
        for text in texts:
            subject, body = _split_subject_and_body(text)
            # 「関係険悪」シートの6〜10行目は「関係良好」と同一文面のため取り込まない
            if body in seen_bodies:
                print(f"  - 重複のためスキップ（{category}）: {subject}")
                continue
            seen_bodies.add(body)
            index += 1
            prefix = "good" if category == "関係良好" else "bad"
            base_day = datetime(2026, 6, 2, 9, 0) if prefix == "good" else datetime(2026, 6, 16, 14, 0)
            received = base_day + timedelta(days=index - 1, minutes=17 * index)
            recipient = "a@your-company.com" if prefix == "good" else "b@your-company.com"
            mails.append(
                {
                    "id": f"rel-{prefix}-{index:02d}",
                    "thread_id": f"rel-{prefix}-{index:02d}",
                    "subject": subject,
                    "sender": "taro@partner-corp.co.jp",
                    "to": [recipient],
                    "cc": [],
                    "received_at": received.isoformat(),
                    "body": body,
                    "signature": "株式会社パートナーコープ 太郎\ntaro@partner-corp.co.jp",
                    "category": category,
                    "source": "関係性混在メール（xlsx由来）",
                }
            )
    return mails


# --------------------------------------------------------------------------
# ② 混在感情メール50通（.eml）
# --------------------------------------------------------------------------
def build_mixed_emotion() -> list[dict]:
    if not EML_DIR.exists():
        raise SystemExit(f"元データが見つかりません: {EML_DIR}")
    mails = eml_loader.load_eml_dir(EML_DIR)
    for mail in mails:
        mail["source"] = "混在感情メール50通（.eml）"
    return mails


# --------------------------------------------------------------------------
# ③ モックメール v2（TO/CC・署名の役職つき）
# --------------------------------------------------------------------------
# 新プロンプトは「署名欄の役職」「CCの管理職」を判定材料にするため、既存20通に追記する
ENRICHMENT: dict[str, dict] = {
    "mail-001": {"cc": [], "signature": "株式会社パートナー商事 営業部 山田太郎\nyamada@partner.co.jp"},
    "mail-002": {"cc": [], "signature": ""},
    "mail-003": {"cc": ["nakamura@partner.co.jp"], "signature": "株式会社パートナー商事 田中一郎"},
    "mail-004": {"cc": [], "signature": "鈴木"},
    "mail-005": {"cc": [], "signature": "株式会社パートナー商事 営業部 部長 伊藤誠\nito@partner.co.jp"},
    "mail-006": {"cc": [], "signature": "株式会社パートナー商事 営業部 部長 伊藤誠\nito@partner.co.jp"},
    "mail-007": {
        "cc": ["sales-bucho@your-company.com"],
        "signature": "株式会社パートナー商事 営業部 部長 伊藤誠\nito@partner.co.jp",
    },
    "mail-008": {
        "cc": ["yakuin@client.example.com", "cs-manager@your-company.com"],
        "signature": "クライアント株式会社 情報システム部 マネージャー 渡辺健",
    },
    "mail-009": {"cc": [], "signature": "株式会社パートナー商事 中村"},
    "mail-010": {"cc": ["keiri@vendor.example.com"], "signature": "ベンダー株式会社 経理課 小林"},
    "mail-011": {"cc": ["team-all@example.com"], "signature": "加藤"},
    "mail-012": {"cc": ["bucho@partner.co.jp"], "signature": "株式会社パートナー商事 竹内"},
    "mail-013": {"cc": [], "signature": "クライアント株式会社 購買部 部長 山本浩"},
    "mail-014": {"cc": [], "signature": "クライアント株式会社 松田"},
    "mail-015": {"cc": [], "signature": "クライアント株式会社 松田"},
    "mail-016": {
        "cc": ["yakuin@client.example.com"],
        "signature": "クライアント株式会社 松田",
    },
    "mail-017": {"cc": [], "signature": "株式会社パートナー商事 林"},
    "mail-018": {
        "cc": ["homu@client.example.com"],
        "signature": "クライアント株式会社 経営企画部 部長 清水結衣",
    },
    "mail-019": {"cc": [], "signature": "ベンダー株式会社 森"},
    "mail-020": {"cc": [], "signature": "池田"},
}

CONSULT_BODY = (
    "お世話になっております。佐々木です。\n"
    "新サービスの導入について、一度ご相談させてください。\n"
    "まだ社内で検討を始めた段階ですが、御社にもぜひご意見を伺いたいと考えております。\n"
    "お手すきの際にご都合を教えていただけますでしょうか。"
)

ADDITIONAL: list[dict] = [
    # 役職あり／なしの対照ペア（本文は完全に同一。差は署名の役職だけ）
    {
        "id": "mail-101",
        "thread_id": "T-Q1",
        "sender": "sasaki@client.example.com",
        "subject": "新サービス導入のご相談",
        "received_at": "2026-05-20T10:00:00",
        "to": [ME],
        "cc": [],
        "body": CONSULT_BODY,
        "signature": "クライアント株式会社 事業推進部 部長 佐々木裕子",
        "note": "役職あり（対照ペアA）。mail-102 と本文は同一。",
    },
    {
        "id": "mail-102",
        "thread_id": "T-Q2",
        "sender": "sasaki@client.example.com",
        "subject": "新サービス導入のご相談",
        "received_at": "2026-05-20T10:05:00",
        "to": [ME],
        "cc": [],
        "body": CONSULT_BODY,
        "signature": "クライアント株式会社 佐々木裕子",
        "note": "役職なし（対照ペアB）。mail-101 と本文は同一。",
    },
    # 決定権の所在（承認・決裁要求）＋ 役員CC
    {
        "id": "mail-103",
        "thread_id": "T-R",
        "sender": "okada@client.example.com",
        "subject": "追加開発のご可否について",
        "received_at": "2026-05-20T16:00:00",
        "to": [ME],
        "cc": ["yakuin@client.example.com", "sales-bucho@your-company.com"],
        "body": (
            "お世話になっております。岡田です。\n"
            "先日ご提示いただいた追加開発の範囲について、実施のご可否をご判定ください。\n"
            "社内の稟議締切が近いため、判断の可否だけでも先にお知らせいただけますと助かります。"
        ),
        "signature": "クライアント株式会社 情報システム部 岡田",
        "note": "承認・決裁要求＋役員CC。決定権の所在ルールの確認用。",
    },
]


def build_sample_v2() -> list[dict]:
    base = json.loads((DATA_DIR / "sample_emails.json").read_text(encoding="utf-8"))
    mails = []
    for mail in base:
        enriched = dict(mail)
        enriched.setdefault("to", [ME])
        extra = ENRICHMENT.get(mail["id"], {})
        if extra.get("cc"):
            enriched["cc"] = extra["cc"]
        else:
            enriched["cc"] = []
        if extra.get("signature"):
            enriched["signature"] = extra["signature"]
        enriched["source"] = "モックメール（プロトタイプ）"
        mails.append(enriched)
    mails.extend(dict(item, source="モックメール（追加：役職・決定権の検証用）") for item in ADDITIONAL)
    return mails


# --------------------------------------------------------------------------
BUILDERS = {
    "relation": ("relation_mixed_emails.json", build_relation_mixed),
    "mixed": ("mixed_emotion_50.json", build_mixed_emotion),
    "sample_v2": ("sample_emails_v2.json", build_sample_v2),
}


def main(argv: list[str]) -> int:
    targets = argv[1:] or list(BUILDERS)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in targets:
        if name not in BUILDERS:
            print(f"不明な対象: {name}（{', '.join(BUILDERS)} のいずれか）")
            return 1
        filename, builder = BUILDERS[name]
        print(f"[{name}] 生成中 …")
        mails = normalize_all(builder(), prefix=name)
        (DATA_DIR / filename).write_text(to_json(mails) + "\n", encoding="utf-8")
        print(f"[{name}] {len(mails)}通 → data/{filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
