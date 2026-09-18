"""提出物（コード・データ・ドキュメント）に研究メンバーの実名が残っていないことの確認。

成果物として公開されるため、研究メンバーの氏名は画面にもソースにも出さない
（役割で書く：「ステージ1の指示文」「検証②で最高評価」など）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# 研究メンバーの姓（漢字・ローマ字）
MEMBER_NAMES = ("平井", "赤木", "廣瀬", "大淵", "大渕", "吉田", "栗原", "akagi", "yoshida", "hirai", "hirose", "kurihara")


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return [ROOT / name for name in out]


@pytest.mark.parametrize("name", MEMBER_NAMES)
def test_member_name_is_absent_from_tracked_files(name):
    hits = []
    for path in _tracked_files():
        if path.name == Path(__file__).name or not path.exists():
            continue
        if name.lower() in path.as_posix().lower():
            hits.append(f"{path.relative_to(ROOT)}（ファイル名）")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if name.lower() in line.lower():
                hits.append(f"{path.relative_to(ROOT)}:{i}")
    assert not hits, f"「{name}」が残っています: " + ", ".join(hits[:20])
