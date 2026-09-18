"""プロンプト（指示文）のパッケージ。

指示文は Markdown ファイルとして原文のまま保存し、`registry` がメタ情報を持つ。
Pythonのソースに文字列として埋め込まないのは、指示文の更新主体が
Pythonを触らない担当者であり、コピペで差し替えられる必要があるため。
"""
from __future__ import annotations

from .registry import (  # noqa: F401
    PromptSpec,
    delete_user_prompt,
    get_spec,
    list_prompts,
    load_prompt,
    prompts_dir,
    save_prompt,
)
