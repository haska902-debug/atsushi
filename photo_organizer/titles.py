"""Claude API で写真の内容が分かる日本語タイトルを作る。"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass

import anthropic
from PIL import Image

DEFAULT_MODEL = "claude-opus-5-5"

# API に送る画像の長辺（これ以上大きくしても認識精度はほぼ変わらない）
MAX_SIDE = 1568

SYSTEM_PROMPT = """\
あなたは写真整理アシスタントです。渡された写真の内容がひと目で分かる、
ファイル名に使う短い日本語タイトルを付けてください。

- タイトルは8〜20文字程度。場所・行事・行動・季節など、写真を見分けるのに役立つ要素を入れる
  （例:「海辺で夕日を眺める」「誕生日ケーキのろうそくを吹き消す」「雪の公園で雪だるま作り」）
- 写っている人物が誰かは推測・特定しない。人物は「人物」「子ども」などと書くか省略する
- 記号や絵文字、日付は入れない
- description には写真の内容を1〜2文で説明する
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["title", "description"],
    "additionalProperties": False,
}


@dataclass
class TitleResult:
    title: str
    description: str


def encode_image(image: Image.Image) -> str:
    img = image.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


class TitleGenerator:
    def __init__(self, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None):
        self.model = model
        self.client = client or anthropic.Anthropic()

    def generate(self, image: Image.Image) -> TitleResult | None:
        """タイトルを生成する。拒否・解析失敗時は None。"""
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            # 安全分類器に断られた場合はサーバー側で別モデルに切り替えて再実行する
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": encode_image(image),
                            },
                        },
                        {"type": "text", "text": "この写真のタイトルを付けてください。"},
                    ],
                }
            ],
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            return None
        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        title = data.get("title", "").strip()
        if not title:
            return None
        return TitleResult(title=title, description=data.get("description", "").strip())
