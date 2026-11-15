"""写真を判定・タイトル付け・月別フォルダへ振り分ける本体処理。"""

from __future__ import annotations

import csv
import os
import re
import shutil
import threading
import time
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
    rest: float = 0.0,
    log: Callable[[str], None] = print,
) -> list[PhotoRecord]:
    """写真を整理する。

    1 枚ごとにすぐ保存して整理結果.csv に記録するので、途中で止まっても
    もう一度実行すれば、記録済みの写真は飛ばして続きから再開する。
    rest は 1 枚ごとに休む秒数（パソコンの負荷を下げるため）。
    """
    index_path = output_dir / INDEX_FILENAME
    done = load_done_sources(index_path)
    images = [p for p in find_images(input_dir, exclude=output_dir) if str(p) not in done]
    if done:
        log(f"前回までに整理済みの {len(done)} 枚は飛ばして、続きから再開します")
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
        if rest:
            time.sleep(rest / 10)

    log(f"同じ人物の写真: {len(matched)} 枚")
    matched.sort(key=lambda r: r.taken)

    # 2. タイトルを付けて、1 枚ずつ月別フォルダへコピー（または移動）する
    if titler is not None and matched:
        log("タイトルを作成しながら保存します...")
    reserved: set[Path] = set()
    lock = threading.Lock()
    total = len(matched)

    def process(numbered: tuple[int, PhotoRecord]) -> None:
        n, record = numbered
        if titler is not None:
            try:
                result = titler.generate(load_image(record.source))
            except Exception as e:
                log(f"タイトル作成失敗: {record.source.name} ({e})")
                result = None
            if result:
                record.title = result.title
                record.description = result.description
        with lock:
            record.dest = destination_for(record, output_dir, reserved)
            log(f"[{n}/{total}] {record.source.name} -> {record.dest.relative_to(output_dir)}")
            if not dry_run:
                record.dest.parent.mkdir(parents=True, exist_ok=True)
                if move:
                    shutil.move(record.source, record.dest)
                else:
                    # 途中で電源が切れても壊れたファイルが残らないよう、一時ファイル経由でコピー
                    tmp = record.dest.with_name(record.dest.name + ".part")
                    shutil.copy2(record.source, tmp)
                    tmp.replace(record.dest)
                append_index(index_path, record)
        if rest and titler is not None:
            time.sleep(rest)

    if workers <= 1:
        for numbered in enumerate(matched, 1):
            process(numbered)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(process, enumerate(matched, 1)))
    return matched


def load_done_sources(path: Path) -> set[str]:
    """整理結果.csv に記録済みの元ファイルの一覧。"""
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {row["元ファイル"] for row in csv.DictReader(f) if row.get("元ファイル")}


def append_index(path: Path, r: PhotoRecord) -> None:
    """整理結果を CSV に 1 行追記する（Excel で開けるよう BOM 付き UTF-8）。"""
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig" if new_file else "utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["撮影日時", "保存先", "元ファイル", "タイトル", "説明", "類似度"])
        writer.writerow([
            r.taken.strftime("%Y-%m-%d %H:%M:%S"),
            str(r.dest),
            str(r.source),
            r.title,
            r.description,
            f"{r.score:.3f}",
        ])
        f.flush()
        os.fsync(f.fileno())
