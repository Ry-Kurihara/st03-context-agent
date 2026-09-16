#!/usr/bin/env python3
"""デモ用のサンプルメールを、Gmail の受信トレイへ「送信せずに」直接入れる。

IMAP の APPEND で受信トレイに置くだけなので、SMTP送信は発生しない。
差出人は架空（`example.co.jp` 等）にしてあり、実在のアドレスは使わない。

    python scripts/seed_sample_mails.py --list          # 何が入るかを一覧で見る
    python scripts/seed_sample_mails.py --dry-run       # 接続せず中身だけ表示
    python scripts/seed_sample_mails.py                 # 投入（アドレスとアプリパスワードを聞かれる）
    python scripts/seed_sample_mails.py --only role,dissatisfied
    python scripts/seed_sample_mails.py --cleanup       # 投入したメールをゴミ箱へ（後片付け）

前提:
    個人のGmailで2段階認証を有効にし、アプリパスワードを発行しておくこと
    （手順は `202609_最終成果物作成/003_動画用にアプリをブラッシュアップ/004_COWK_Gmail連携方法.md`）。

    アドレスとパスワードは、環境変数 `ST03_SEED_USER` / `ST03_SEED_APP_PASSWORD` でも渡せる
    （未設定なら対話的に入力。パスワードは画面に表示されず、ファイルにも保存しない）。

後片付け:
    `--cleanup` で、このスクリプトが入れたメール（`X-ST03-Sample` ヘッダ付き）だけをゴミ箱へ移す。
    Gmailのラベル「ST03-sample」からも辿れる。
"""
from __future__ import annotations

import argparse
import getpass
import imaplib
import os
import re
import sys
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

LABEL = "ST03-sample"
MARKER_HEADER = "X-ST03-Sample"
DEFAULT_HOST = "imap.gmail.com"
DEFAULT_INTERVAL_MINUTES = 3


@dataclass(frozen=True)
class Sample:
    key: str  # --only で指定する識別子
    note: str  # このメールで何を見せたいか
    sender_name: str
    sender_addr: str
    subject: str
    body: str
    signature: str = ""
    cc: tuple[str, ...] = field(default_factory=tuple)


# 受信トレイには「上から順に新しい」形で並ぶ（リストの後ろほど新しい）。
# 研究の結論（優先度の読み取り／返信の書き分け）が見える組み合わせにしてある。
SAMPLES: tuple[Sample, ...] = (
    Sample(
        key="thanks",
        note="低優先度。お礼メールでノイズが増えていないことの確認に使う",
        sender_name="田中 美咲",
        sender_addr="m.tanaka@example.co.jp",
        subject="先日はありがとうございました",
        body="""ご担当者様

いつもお世話になっております。サンプル物産の田中です。

先日はお忙しいところ、資料のご共有をいただきありがとうございました。
社内でも「わかりやすい」と好評でした。

取り急ぎ、お礼まで申し上げます。
""",
        signature="サンプル物産株式会社\n企画部 田中 美咲",
    ),
    Sample(
        key="invite",
        note="低〜中優先度。案内メール（すぐ返信しなくてよいもの）",
        sender_name="社内イベント事務局",
        sender_addr="events@example.org",
        subject="【ご案内】社内勉強会「生成AI活用入門」開催のお知らせ",
        body="""各位

社内イベント事務局です。下記のとおり社内勉強会を開催します。

■テーマ：生成AI活用入門
■日時：10月15日（木）17:00〜18:00
■形式：オンライン
■申込締切：10月10日（土）

参加をご希望の方は、本メールに「参加」とご返信ください。
""",
        signature="社内イベント事務局",
    ),
    Sample(
        key="consult",
        note="相談メール。文面は穏やかだが、初動の遅れが機会損失につながる例",
        sender_name="山本 由美",
        sender_addr="y.yamamoto@example.com",
        subject="AI導入支援についてご相談させてください",
        body="""ご担当者様

はじめてご連絡いたします。テスト工業の山本と申します。

弊社では問い合わせ対応業務の効率化を検討しており、
生成AIを活用した導入支援について、概算のお見積りを伺えればと考えております。

・対象業務：社内ヘルプデスク（月間問い合わせ 約800件）
・希望時期：年内にPoC開始
・予算感：未定（概算を伺ったうえで社内稟議の予定）

一度オンラインでお打ち合わせの機会をいただけますでしょうか。
""",
        signature="テスト工業株式会社\n情報システム部 山本 由美",
    ),
    Sample(
        key="urgent",
        note="緊急度が高い依頼。返信は「簡潔に伝える」が向く場面",
        sender_name="鈴木 大輔",
        sender_addr="d.suzuki@example.net",
        subject="至急：納品資料の差し替えについて",
        body="""ご担当者様

お疲れさまです。鈴木です。

昨日お送りいただいた納品資料ですが、12ページ目のグラフの数値が
最新版（9月末時点）になっていないようです。

明日10時から先方への報告があるため、
本日中に差し替え版をお送りいただけますでしょうか。

急なお願いで申し訳ありませんが、よろしくお願いします。
""",
        signature="サンプルシステム株式会社\n開発部 鈴木 大輔",
    ),
    Sample(
        key="role",
        note="役職補正のデモ。文面は穏やかだが、署名が部長でCCに役員が入る",
        sender_name="中村 章",
        sender_addr="a.nakamura@example.co.jp",
        subject="次期システムの進め方についてのご確認",
        body="""ご担当者様

いつもお世話になっております。サンプル商事の中村です。

次期システムの進め方について、社内で検討を進めております。
つきましては、現時点での想定スケジュールと概算費用をお知らせいただけますでしょうか。

社内の稟議締切が近く、可否の見通しだけでも先に伺えますと助かります。
""",
        signature="サンプル商事株式会社\n事業推進部 部長 中村 章",
        cc=("executive@example.co.jp",),
    ),
    Sample(
        key="dissatisfied",
        note="表面と裏のズレ。丁寧な文面だが不満と行き違いが読み取れる。「配慮＋論点整理」が向く場面",
        sender_name="小林 直樹",
        sender_addr="n.kobayashi@example.net",
        subject="対応範囲の認識について",
        body="""ご担当者様

お世話になっております。小林です。

先日ご連絡した不具合の件ですが、こちらで修正対応を行いました。
ただ、本来はそちらでご対応いただく範囲の内容かと認識しております。

同様のやり取りが続いており、都度こちらで巻き取る形になっております。
一度、役割分担について整理させていただけますでしょうか。

お手数をおかけしますが、よろしくお願いいたします。
""",
        signature="サンプルパートナーズ株式会社\n第二システム部 小林 直樹",
    ),
)


def pick_samples(keys: list[str] | None) -> list[Sample]:
    """`--only` の指定に従って絞り込む（指定なしは全部）。"""
    if not keys:
        return list(SAMPLES)
    known = {s.key: s for s in SAMPLES}
    unknown = [k for k in keys if k not in known]
    if unknown:
        raise SystemExit(f"知らないキーです: {', '.join(unknown)}（使えるキー: {', '.join(known)}）")
    return [known[k] for k in keys]


def timestamps(count: int, *, interval_minutes: int = DEFAULT_INTERVAL_MINUTES, now: float | None = None) -> list[float]:
    """古い順に等間隔、最後の1通が「今」になる受信日時。"""
    base = time.time() if now is None else now
    step = interval_minutes * 60
    return [base - step * (count - 1 - i) for i in range(count)]


def build_message(sample: Sample, to_addr: str, ts: float) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((sample.sender_name, sample.sender_addr))
    msg["To"] = to_addr
    if sample.cc:
        msg["Cc"] = ", ".join(sample.cc)
    msg["Subject"] = sample.subject
    msg["Date"] = formatdate(ts, localtime=True)
    msg["Message-ID"] = make_msgid(domain=sample.sender_addr.split("@")[1])
    msg[MARKER_HEADER] = "1"  # 後片付け（--cleanup）で自分が入れた分だけを探すための目印
    body = sample.body.rstrip() + ("\n\n" + sample.signature if sample.signature else "") + "\n"
    msg.set_content(body)
    return msg


def append_samples(imap, samples: list[Sample], to_addr: str, *, label: str | None = LABEL,
                   interval_minutes: int = DEFAULT_INTERVAL_MINUTES) -> list[str]:
    """受信トレイへ投入し、付与できたUIDを返す。"""
    uids: list[str] = []
    for sample, ts in zip(samples, timestamps(len(samples), interval_minutes=interval_minutes)):
        message = build_message(sample, to_addr, ts)
        status, data = imap.append("INBOX", "", imaplib.Time2Internaldate(ts), message.as_bytes())
        if status != "OK":
            raise SystemExit(f"投入に失敗しました（{sample.key}）: {data}")
        hit = re.search(rb"APPENDUID \d+ (\d+)", (data[0] or b"") if data else b"")
        if hit:
            uids.append(hit.group(1).decode())
        print(f"  投入: [{sample.key}] {sample.subject}")

    if label and uids:
        try:
            imap.create(label)  # 既にあればエラーになるので握りつぶす
        except Exception:
            pass
        imap.select("INBOX")
        status, _ = imap.uid("STORE", ",".join(uids), "+X-GM-LABELS", f'("{label}")')
        print(f"  ラベル「{label}」: {'付与しました' if status == 'OK' else '付与できませんでした'}")
    return uids


def cleanup(imap, *, label: str | None = LABEL) -> int:
    """このスクリプトが入れたメール（目印ヘッダ付き）をゴミ箱へ移す。件数を返す。"""
    imap.select("INBOX")
    status, data = imap.uid("SEARCH", None, "HEADER", MARKER_HEADER, "1")
    if status != "OK":
        raise SystemExit("検索に失敗しました")
    uids = (data[0] or b"").split() if data else []
    if not uids:
        return 0
    joined = b",".join(uids).decode()
    # Gmail は \\Deleted より「ゴミ箱ラベルを付ける」方が確実
    status, _ = imap.uid("STORE", joined, "+X-GM-LABELS", "(\\Trash)")
    if status != "OK":
        imap.uid("STORE", joined, "+FLAGS", "(\\Deleted)")
        imap.expunge()
    return len(uids)


def _connect(host: str, user: str, password: str):
    imap = imaplib.IMAP4_SSL(host, timeout=30)
    try:
        imap.login(user, password)
    except imaplib.IMAP4.error as exc:
        raise SystemExit(
            "ログインに失敗しました。通常のパスワードではなく「アプリパスワード」を使っているか、"
            f"2段階認証が有効かを確認してください（{exc}）"
        )
    return imap


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="デモ用サンプルメールをGmailの受信トレイへ直接入れる")
    ap.add_argument("--list", action="store_true", help="入るメールの一覧（キーと狙い）を表示して終了")
    ap.add_argument("--dry-run", action="store_true", help="接続せず、組み立てた内容だけ表示")
    ap.add_argument("--cleanup", action="store_true", help="このスクリプトで入れたメールをゴミ箱へ移す")
    ap.add_argument("--only", help="投入するキーをカンマ区切りで指定（例: role,dissatisfied）")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--user", default=os.environ.get("ST03_SEED_USER", ""), help="Gmailアドレス（環境変数 ST03_SEED_USER でも可）")
    ap.add_argument("--interval-min", type=int, default=DEFAULT_INTERVAL_MINUTES, help="受信日時の間隔（分）")
    ap.add_argument("--no-label", action="store_true", help=f"ラベル「{LABEL}」を付けない")
    args = ap.parse_args(argv)

    if args.list:
        for s in SAMPLES:
            print(f"{s.key:14} {s.subject}\n{'':14} └ {s.note}")
        return

    samples = pick_samples(args.only.split(",") if args.only else None)

    if args.dry_run:
        for sample, ts in zip(samples, timestamps(len(samples), interval_minutes=args.interval_min)):
            message = build_message(sample, "you@example.com", ts)
            print("=" * 68)
            print(f"[{sample.key}] {sample.note}")
            print(f"From: {message['From']}\nCc: {message['Cc'] or '(なし)'}\nDate: {message['Date']}")
            print(f"Subject: {message['Subject']}\n")
            print(message.get_content().rstrip()[:400])
        print(f"\n{len(samples)} 通ぶんを組み立てました（dry-run のため投入していません）")
        return

    user = args.user or input("Gmailアドレス: ").strip()
    password = (os.environ.get("ST03_SEED_APP_PASSWORD") or getpass.getpass("アプリパスワード（16桁・表示されません）: ")).replace(" ", "")
    imap = _connect(args.host, user, password)
    del password

    try:
        if args.cleanup:
            removed = cleanup(imap)
            print(f"{removed} 通をゴミ箱へ移しました。" if removed else "投入済みのサンプルメールは見つかりませんでした。")
            return
        print(f"{len(samples)} 通を投入します（{user}）")
        append_samples(imap, samples, user, label=None if args.no_label else LABEL, interval_minutes=args.interval_min)
        print(
            f"\n完了しました。アプリの「📥 メールデータ → 📮 個人のメールアカウントから取り込む」で、"
            f"取り込む件数を {len(samples)} にして取り込んでください。"
        )
    finally:
        try:
            imap.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main(sys.argv[1:])
