"""無料版: パソコン内で動く AI（Ollama）で写真のタイトルを作る。

Ollama (https://ollama.com) を起動しておき、画像が分かるモデルを
`ollama pull gemma3:4b` のように取得しておく必要がある。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from PIL import Image

from .titles import OUTPUT_SCHEMA, SYSTEM_PROMPT, TitleResult, encode_image

DEFAULT_LOCAL_MODEL = "gemma3:4b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"

# パソコン内の AI は大きな画像だと遅いので、送る画像を小さめにする
LOCAL_MAX_SIDE = 896


class OllamaError(RuntimeError):
    pass


class LocalTitleGenerator:
    def __init__(
        self,
        model: str = DEFAULT_LOCAL_MODEL,
        url: str = DEFAULT_OLLAMA_URL,
        timeout: float = 600,
    ):
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.url + path, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")
            raise OllamaError(f"Ollama がエラーを返しました ({e.code}): {detail}") from e
        except urllib.error.URLError as e:
            raise OllamaError(
                f"Ollama に接続できません ({self.url})。Ollama を起動してください。"
            ) from e

    def check(self) -> None:
        """Ollama が起動していて、モデルが取得済みか確認する。"""
        tags = self._request("/api/tags")
        names = {m.get("name") for m in tags.get("models", [])}
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        if wanted not in names:
            raise OllamaError(
                f"モデル {self.model} がありません。先に次を実行してください:\n"
                f"  ollama pull {self.model}"
            )

    def generate(self, image: Image.Image) -> TitleResult | None:
        """タイトルを生成する。解析失敗時は None。"""
        response = self._request("/api/chat", {
            "model": self.model,
            "stream": False,
            "format": OUTPUT_SCHEMA,
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "この写真のタイトルを付けてください。JSON で答えてください。",
                    "images": [encode_image(image, LOCAL_MAX_SIDE)],
                },
            ],
        })
        text = response.get("message", {}).get("content", "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        title = str(data.get("title", "")).strip()
        if not title:
            return None
        return TitleResult(title=title, description=str(data.get("description", "")).strip())
