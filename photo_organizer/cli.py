"""コマンドラインから使うための入口。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .faces import DEFAULT_MODEL_DIR, DEFAULT_THRESHOLD, FaceMatcher
from .images import IMAGE_EXTENSIONS, find_images, load_image
from .local_titles import DEFAULT_LOCAL_MODEL, DEFAULT_OLLAMA_URL, LocalTitleGenerator, OllamaError
from .organize import organize
from .titles import DEFAULT_MODEL, TitleGenerator


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="photo_organizer",
        description="同じ人物の写真を見つけ、月別フォルダに分けて内容が分かるタイトルを付けます。",
    )
    p.add_argument("input", type=Path, help="整理したい写真が入っているフォルダ")
    p.add_argument("output", type=Path, help="整理した写真を保存するフォルダ")
    p.add_argument(
        "-r", "--ref", type=Path, nargs="+", required=True,
        help="探したい人物がはっきり写った写真（複数可・フォルダ指定可）",
    )
    p.add_argument(
        "-t", "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"同一人物とみなす類似度 (既定 {DEFAULT_THRESHOLD})。下げると多く拾い、上げると厳しくなる",
    )
    p.add_argument("--move", action="store_true", help="コピーではなく移動する")
    p.add_argument("--dry-run", action="store_true", help="実際には保存せず、結果だけ表示する")
    p.add_argument("--no-title", action="store_true", help="AI によるタイトル付けをしない")
    p.add_argument(
        "--free", action="store_true",
        help="無料版: パソコン内の AI（Ollama）でタイトルを作る。API キー不要",
    )
    p.add_argument(
        "--model",
        help=f"タイトル作成に使うモデル (既定: 通常 {DEFAULT_MODEL} / --free 時 {DEFAULT_LOCAL_MODEL})",
    )
    p.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL, help=f"Ollama の URL (既定 {DEFAULT_OLLAMA_URL})")
    p.add_argument("--workers", type=int, help="タイトル作成の同時実行数 (既定: 通常 4 / --free 時 1)")
    p.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR, help="顔認識モデルの保存先")
    return p


def collect_refs(paths: list[Path]) -> list[Path]:
    refs = []
    for p in paths:
        if p.is_dir():
            refs.extend(find_images(p))
        elif p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            refs.append(p)
        else:
            print(f"参照写真が見つかりません: {p}", file=sys.stderr)
    return refs


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.input.is_dir():
        print(f"入力フォルダがありません: {args.input}", file=sys.stderr)
        return 1

    titler = None
    workers = args.workers or (1 if args.free else 4)
    if args.no_title:
        pass
    elif args.free:
        titler = LocalTitleGenerator(model=args.model or DEFAULT_LOCAL_MODEL, url=args.ollama_url)
        try:
            titler.check()
        except OllamaError as e:
            print(e, file=sys.stderr)
            return 1
        print(f"無料版: パソコン内の AI ({titler.model}) でタイトルを作成します")
    else:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            print("注意: ANTHROPIC_API_KEY が未設定です。ログイン済みプロファイルが無い場合は失敗します。")
        titler = TitleGenerator(model=args.model or DEFAULT_MODEL)

    matcher = FaceMatcher(model_dir=args.model_dir, threshold=args.threshold)
    registered = 0
    for ref in collect_refs(args.ref):
        if matcher.add_reference(load_image(ref)):
            registered += 1
        else:
            print(f"参照写真に顔が見つかりません: {ref}", file=sys.stderr)
    if registered == 0:
        print("顔を登録できる参照写真がありませんでした。", file=sys.stderr)
        return 1
    print(f"参照写真 {registered} 枚から人物を登録しました")

    records = organize(
        args.input, args.output, matcher, titler,
        move=args.move, dry_run=args.dry_run, workers=workers,
    )

    months = sorted({r.taken.strftime("%Y-%m") for r in records})
    action = "（お試し実行のため保存していません）" if args.dry_run else ""
    print(f"\n完了: {len(records)} 枚を {len(months)} か月分のフォルダに整理しました{action}")
    for m in months:
        print(f"  {m}: {sum(r.taken.strftime('%Y-%m') == m for r in records)} 枚")
    return 0


if __name__ == "__main__":
    sys.exit(main())
