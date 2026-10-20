"""写真を判定・タイトル付け・月別フォルダへ振り分ける本体処理。"""

from __future__ import annotations

import csv
import re
import shutil
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .images import find_images, load_image, taken_at

MAX_TITLE_LEN = 40
INDEX_FILENAME = "整理結果.csv"


@dataclass
class PhotoRecord:
    source: Path
    taken: datetime
    score: float
    title: str = ""
    description: str = ""
    dest: Path | None = None


def sanitize_title(title: str) -> str:
    """ファイル名に使えない文字を取り除き、長さを制限する。"""
    title = unicodedata.normalize("NFKC", title)
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", title)
    title = re.sub(r"\s+", "_", title.strip()).strip("._")
    return title[:MAX_TITLE_LEN]


def unique_path(path: Path, reserved: set[Path]) -> Path:
    candidate = path
    n = 2
    while candidate.exists() or candidate in reserved:
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    reserved.add(candidate)
    return candidate


def destination_for(record: PhotoRecord, output_dir: Path, reserved: set[Path]) -> Path:
    month_dir = output_dir / record.taken.strftime("%Y-%m")
    title = sanitize_title(record.title) or f"写真_{record.taken:%H%M%S}"
    name = f"{record.taken:%Y-%m-%d}_{title}{record.source.suffix.lower()}"
    return unique_path(month_dir / name, reserved)


def organize(
    input_dir: Path,
    output_dir: Path,
    matcher,
    titler=None,
    move: bool = False,
    dry_run: bool = False,
    workers: int = 4,
    log: Callable[[str], None] = print,
) -> list[PhotoRecord]:
    images = find_images(input_dir, exclude=output_dir)
    log(f"{len(images)} 枚の写真を確認します")

    # 1. 同じ人物が写っている写真を選ぶ
    matched: list[PhotoRecord] = []
    for i, path in enumerate(images, 1):
        try:
            score = matcher.similarity(load_image(path))
        except Exception as e:  # 壊れた画像などは飛ばして続ける
            log(f"[{i}/{len(images)}] 読み込み失敗: {path.name} ({e})")
            continue
        if matcher.is_match(score):
            matched.append(PhotoRecord(source=path, taken=taken_at(path), score=score))
            log(f"[{i}/{len(images)}] 一致 ({score:.2f}): {path.name}")
        else:
            reason = "顔なし" if score is None else f"別人 ({score:.2f})"
            log(f"[{i}/{len(images)}] 対象外 {reason}: {path.name}")

    log(f"同じ人物の写真: {len(matched)} 枚")

    # 2. 内容が分かるタイトルを付ける（API 呼び出しは並列で行う）
    if titler is not None and matched:
        log("タイトルを作成しています...")

        def make_title(record: PhotoRecord) -> None:
            try:
                result = titler.generate(load_image(record.source))
            except Exception as e:
                log(f"タイトル作成失敗: {record.source.name} ({e})")
                return
            if result:
                record.title = result.title
                record.description = result.description

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(make_title, matched))

    # 3. 月別フォルダへコピー（または移動）
    matched.sort(key=lambda r: r.taken)
    reserved: set[Path] = set()
    for record in matched:
        record.dest = destination_for(record, output_dir, reserved)
        log(f"{record.source.name} -> {record.dest.relative_to(output_dir)}")
        if dry_run:
            continue
        record.dest.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(record.source, record.dest)
        else:
            shutil.copy2(record.source, record.dest)

    if not dry_run and matched:
        write_index(output_dir / INDEX_FILENAME, matched)
    return matched


def write_index(path: Path, records: list[PhotoRecord]) -> None:
    """整理結果を CSV に追記する（Excel で開けるよう BOM 付き UTF-8）。"""
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig" if new_file else "utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["撮影日時", "保存先", "元ファイル", "タイトル", "説明", "類似度"])
        for r in records:
            writer.writerow([
                r.taken.strftime("%Y-%m-%d %H:%M:%S"),
                str(r.dest),
                str(r.source),
                r.title,
                r.description,
                f"{r.score:.3f}",
            ])
