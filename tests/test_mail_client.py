"""メールクライアント化（0930最終成果物の動画用）のテスト。

- 平井さん0909改訂版プロンプトが v2 として登録されている（旧版は残す）
- デモの返信3択の定義
- 返信案を n 案まとめて生成する `generate_reply_set`
"""
from __future__ import annotations

import pytest

import prompt_loader
import reply_generator
from conftest import FakeClient
from prompts import registry


# --------------------------------------------------------------------------
# プロンプト（v2）
# --------------------------------------------------------------------------
def test_v2_reply_prompts_are_registered_and_old_ones_kept():
    ids = {spec.id for spec in registry.list_prompts(kind="reply")}
    assert {"reply_r1_plain_v2", "reply_r1_verbalize_v2"} <= ids
    # 改訂前との比較ができるよう旧版は消さない
    assert {"reply_r1_plain", "reply_r1_verbalize"} <= ids


@pytest.mark.parametrize("prompt_id", ["reply_r1_plain_v2", "reply_r1_verbalize_v2"])
def test_v2_prompts_have_same_tokens_as_existing(prompt_id):
    text = registry.load_prompt(prompt_id)
    assert set(prompt_loader.find_tokens(text)) == {"PARAMETERS", "EMAIL"}
    spec = registry.get_spec(prompt_id)
    assert spec.tokens == ("PARAMETERS", "EMAIL")
    assert "0909" in spec.group


def test_plain_v2_expresses_care_without_verbalizing_emotion():
    text = registry.load_prompt("reply_r1_plain_v2")
    assert "相手の感情や心情を直接言語化しない" in text
    assert "対応の誠実さ・先回りした説明・次の行動の明示" in text
    assert "文体のイメージ" in text


def test_verbalize_v2_has_avoid_list_and_order():
    text = registry.load_prompt("reply_r1_verbalize_v2")
    assert "# 避ける表現" in text
    assert "共感 → 状況整理 → 対応策提示" in text
    assert "共感直後の打ち消し" in text
    assert "状況表現を中心に穏やかに反映する" in text


def test_demo_reply_prompts_are_three_user_facing_choices():
    labels = [label for label, _ in registry.DEMO_REPLY_PROMPTS]
    ids = [pid for _, pid in registry.DEMO_REPLY_PROMPTS]
    assert labels == ["簡潔に伝える", "配慮を添える", "配慮＋論点整理"]
    assert ids == ["reply_r1_plain_v2", "reply_r1_verbalize_v2", "reply_r2_empathy_organized"]
    for pid in ids:
        registry.get_spec(pid)  # 未登録なら KeyError
    # 画面に出すのは利用者の言葉（研究用語は出さない）
    assert all("案" not in label for label in labels)


def test_demo_reply_scenes_cover_every_choice():
    assert set(registry.DEMO_REPLY_SCENES) == {label for label, _ in registry.DEMO_REPLY_PROMPTS}
    assert all(text for text in registry.DEMO_REPLY_SCENES.values())


# --------------------------------------------------------------------------
# generate_reply_set
# --------------------------------------------------------------------------
def test_generate_reply_set_keeps_order_labels_and_settings():
    client = FakeClient(["返信1", "返信2", "返信3"])
    results = reply_generator.generate_reply_set(
        [("簡潔", "指示1\n{{EMAIL}}"), ("配慮", "指示2\n{{EMAIL}}"), ("整理", "指示3\n{{EMAIL}}")],
        mail_text="本文",
        parameters={"priorityLabel": "高"},
        client=client,
        model_name="gemini-x",
        max_workers=1,
    )
    assert [r.text for r in results] == ["返信1", "返信2", "返信3"]
    assert [r.meta["label"] for r in results] == ["簡潔", "配慮", "整理"]
    assert len({(r.meta["provider"], r.meta["model"], r.meta["temperature"]) for r in results}) == 1
    assert [c["contents"].splitlines()[0] for c in client.calls] == ["指示1", "指示2", "指示3"]


def test_generate_reply_set_in_parallel_returns_results_in_input_order():
    class EchoClient(FakeClient):
        """呼ばれた順ではなく、プロンプトの中身で応答する（並列実行の検証用）。"""

        def __init__(self) -> None:
            super().__init__([])
            owner = self

            class _Models:
                def generate_content(self, *, model, contents, config=None):
                    owner.calls.append({"model": model, "contents": contents, "config": config})
                    return type("R", (), {"text": "返信:" + contents.splitlines()[0]})()

            self.models = _Models()

    client = EchoClient()
    templates = [(f"L{i}", f"指示{i}\n{{{{EMAIL}}}}") for i in range(3)]
    results = reply_generator.generate_reply_set(
        templates, mail_text="本文", parameters={}, client=client, max_workers=3
    )
    assert [r.text for r in results] == ["返信:指示0", "返信:指示1", "返信:指示2"]
    assert len(client.calls) == 3


def test_generate_reply_set_rejects_empty():
    with pytest.raises(ValueError):
        reply_generator.generate_reply_set([], mail_text="本文", parameters={}, client=FakeClient([]))
