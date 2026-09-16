"""プロンプトの `{{TOKEN}}` を置換するだけの薄いレンダラ。

`str.format` を使わない理由:
ステージ1の指示文は出力フォーマット例としてJSONの `{` `}` を多数含む。
`format` を使うと全ての中括弧を `{{` `}}` にエスケープする必要があり、
「指示文を原文のまま保存する」という方針と両立しない。
そのため独自トークンの単純置換とし、未解決トークンが残ったら例外にする。
"""
from __future__ import annotations

import re

TOKEN_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


class UnresolvedTokenError(ValueError):
    """テンプレート中のトークンに値が渡されなかった。"""


def find_tokens(text: str) -> tuple[str, ...]:
    """出現順・重複なしでトークン名を返す。"""
    seen: list[str] = []
    for match in TOKEN_RE.finditer(text):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def render(template: str, values: dict[str, str]) -> str:
    """`{{TOKEN}}` を values で置換する。

    - 値が渡されていないトークンが残る場合は `UnresolvedTokenError`
    - テンプレートに存在しないキーを渡した場合は `ValueError`（呼び出し側のタイポ検出）
    """
    tokens = set(find_tokens(template))
    unused = sorted(set(values) - tokens)
    if unused:
        raise ValueError(f"テンプレートに存在しないキーが渡されました: {', '.join(unused)}")

    missing = sorted(tokens - set(values))
    if missing:
        raise UnresolvedTokenError(f"値が渡されていないトークンがあります: {', '.join(missing)}")

    # 置換値に含まれる `\` や `{{...}}` を再解釈しないよう、関数で置換する
    return TOKEN_RE.sub(lambda m: str(values[m.group(1)]), template)


def render_available(template: str, values: dict[str, str]) -> str:
    """values のうち、テンプレートが実際に使うキーだけを渡して置換する。"""
    tokens = set(find_tokens(template))
    return render(template, {k: v for k, v in values.items() if k in tokens})
