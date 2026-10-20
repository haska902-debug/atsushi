import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PIL import Image

from photo_organizer.local_titles import LocalTitleGenerator, OllamaError
from photo_organizer.titles import TitleResult


@pytest.fixture
def fake_ollama():
    """Ollama の API を真似るテスト用サーバー。"""
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, data):
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.reply({"models": [{"name": "gemma3:4b"}]})

        def do_POST(self):
            received["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            content = json.dumps({"title": "公園で桜を見上げる", "description": "満開の桜の下。"})
            self.reply({"message": {"role": "assistant", "content": content}, "done": True})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()


def test_generate_title(fake_ollama):
    url, received = fake_ollama
    gen = LocalTitleGenerator(url=url)
    gen.check()
    result = gen.generate(Image.new("RGB", (2000, 1500), "pink"))

    assert result == TitleResult("公園で桜を見上げる", "満開の桜の下。")
    body = received["body"]
    assert body["model"] == "gemma3:4b"
    assert body["stream"] is False
    assert body["format"]["required"] == ["title", "description"]
    assert len(body["messages"][1]["images"]) == 1


def test_missing_model_message(fake_ollama):
    url, _ = fake_ollama
    with pytest.raises(OllamaError, match="ollama pull qwen2.5vl"):
        LocalTitleGenerator(model="qwen2.5vl", url=url).check()


def test_ollama_not_running():
    with pytest.raises(OllamaError, match="起動してください"):
        LocalTitleGenerator(url="http://127.0.0.1:9").check()
