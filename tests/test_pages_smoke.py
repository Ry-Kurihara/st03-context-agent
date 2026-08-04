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


def test_all_seven_pages_exist():
    names = sorted(p.name for p in (APP / "pages").glob("*.py"))
    assert len(names) == 7, names
    assert names[0].startswith("1_")
    assert names[-1].startswith("7_")


def test_stage1_page_renders_with_api_key(monkeypatch):
    """APIキーがある場合も、押すまではAPIを呼ばずに描画できること。"""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-for-test")
    at = _run(APP / "pages" / "2_🔍_ステージ1_感情分析.py")
    assert not at.exception
