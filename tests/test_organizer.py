import json
from datetime import datetime
from pathlib import Path

import anthropic
import httpx2 as httpx
from PIL import Image

from photo_organizer.images import taken_at
from photo_organizer.organize import INDEX_FILENAME, organize, sanitize_title, unique_path
from photo_organizer.titles import TitleGenerator, TitleResult


def make_photo(path: Path, color: str, dt: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (64, 64), color)
    exif = Image.Exif()
    if dt:
        exif.get_ifd(0x8769)[36867] = dt
    img.save(path, exif=exif)
    return path


class ColorMatcher:
    """赤い写真だけを「同じ人物」とみなすテスト用の照合器。"""

    def similarity(self, image):
        r, g, b = image.convert("RGB").getpixel((0, 0))
        return 0.9 if r > 200 and g < 50 else 0.1

    def is_match(self, score):
        return score is not None and score >= 0.363


class FakeTitler:
    def generate(self, image):
        return TitleResult(title="公園で/遊ぶ: 子ども?", description="公園で遊んでいる。")


def test_sanitize_title():
    assert sanitize_title('海辺で/夕日:を*見る?') == "海辺で夕日を見る"
    assert sanitize_title("  雪の 公園  ") == "雪の_公園"
    assert len(sanitize_title("あ" * 100)) == 40


def test_unique_path(tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")
    reserved = set()
    assert unique_path(p, reserved).name == "a_2.jpg"
    assert unique_path(p, reserved).name == "a_3.jpg"


def test_taken_at_reads_exif(tmp_path):
    photo = make_photo(tmp_path / "p.jpg", "red", "2023:08:10 14:05:00")
    assert taken_at(photo) == datetime(2023, 8, 10, 14, 5)


def test_organize_copies_matching_photos_by_month(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    make_photo(src / "1.jpg", "red", "2024:03:15 12:00:00")
    make_photo(src / "2.jpg", "red", "2024:03:15 13:00:00")
    make_photo(src / "deep" / "3.jpg", "red", "2024:05:01 08:00:00")
    make_photo(src / "other.jpg", "blue", "2024:03:15 12:00:00")

    records = organize(src, out, ColorMatcher(), FakeTitler(), log=lambda _: None)

    assert len(records) == 3
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.jpg"))
    assert files == [
        "2024-03/2024-03-15_公園で遊ぶ_子ども.jpg",
        "2024-03/2024-03-15_公園で遊ぶ_子ども_2.jpg",
        "2024-05/2024-05-01_公園で遊ぶ_子ども.jpg",
    ]
    assert (src / "1.jpg").exists()  # コピーなので元は残る
    assert "公園で遊んでいる" in (out / INDEX_FILENAME).read_text(encoding="utf-8-sig")


def test_organize_move_and_dry_run(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    make_photo(src / "1.jpg", "red", "2024:01:02 03:04:05")

    organize(src, out, ColorMatcher(), None, dry_run=True, log=lambda _: None)
    assert not out.exists()

    organize(src, out, ColorMatcher(), None, move=True, log=lambda _: None)
    assert not (src / "1.jpg").exists()
    assert (out / "2024-01" / "2024-01-02_写真_030405.jpg").exists()


def test_output_inside_input_is_not_rescanned(tmp_path):
    src = tmp_path / "in"
    out = src / "整理済み"
    make_photo(src / "1.jpg", "red", "2024:01:02 03:04:05")
    organize(src, out, ColorMatcher(), None, log=lambda _: None)
    records = organize(src, out, ColorMatcher(), None, log=lambda _: None)
    assert [r.source.name for r in records] == ["1.jpg"]


def fake_client(handler) -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def api_response(text: str, stop_reason: str = "end_turn") -> httpx.Response:
    return httpx.Response(200, json={
        "id": "msg_test", "type": "message", "role": "assistant",
        "model": "claude-opus-5-5", "stop_reason": stop_reason, "stop_sequence": None,
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 10, "output_tokens": 10},
    })


def test_title_generator_request_and_parse():
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["body"] = json.loads(request.content)
        sent["beta"] = request.headers.get("anthropic-beta")
        return api_response(json.dumps({"title": "海辺で夕日を眺める", "description": "夕暮れの海辺。"}))

    gen = TitleGenerator(client=fake_client(handler))
    result = gen.generate(Image.new("RGB", (3000, 2000), "orange"))

    assert result == TitleResult("海辺で夕日を眺める", "夕暮れの海辺。")
    body = sent["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in sent["beta"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"


def test_title_generator_refusal_returns_none():
    gen = TitleGenerator(client=fake_client(lambda r: api_response("", "refusal")))
    assert gen.generate(Image.new("RGB", (10, 10))) is None
