"""画面が例外なく描画できるかのスモークテスト（APIキー無しでも開けること）。

Streamlit の AppTest でページスクリプトを実際に実行する。
LLM呼び出しはボタンを押さない限り走らないため、APIキーは不要。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"

PAGES = [
    APP / "main.py",
    *sorted((APP / "pages").glob("*.py")),
]


def _run(path: Path) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=30)
    at.run()
    return at


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.name)
def test_page_renders_without_exception(path: Path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    at = _run(path)
    assert not at.exception, f"{path.name} で例外: {[str(e) for e in at.exception]}"


def test_pages_are_demo_first_and_research_last():
    """受信トレイが先頭、研究用（比較・答え合わせ・プロンプト管理）は 9x_🔬 で末尾にまとまる。"""
    names = sorted(p.name for p in (APP / "pages").glob("*.py"))
    assert len(names) == 8, names
    assert names[0] == "0_📬_受信トレイ.py"
    research = [n for n in names if n.startswith("9")]
    assert research == [
        "91_🔬_研究_ステージ1プロンプト比較.py",
        "92_🔬_研究_返信案ペア比較.py",
        "93_🔬_研究_答え合わせ.py",
        "94_🔬_研究_プロンプト管理.py",
    ]
    assert names[-len(research):] == research


def test_main_page_links_point_to_existing_files():
    import re

    source = (APP / "main.py").read_text(encoding="utf-8")
    links = re.findall(r'"(pages/[^"]+\.py)"', source)
    assert "pages/0_📬_受信トレイ.py" in links
    for link in links:
        assert (APP / link).exists(), link


def test_stage1_page_renders_with_api_key(monkeypatch):
    """APIキーがある場合も、押すまではAPIを呼ばずに描画できること。"""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-for-test")
    at = _run(APP / "pages" / "2_🔍_ステージ1_感情分析.py")
    assert not at.exception
