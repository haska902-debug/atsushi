"""無料版のかんたん実行: 準備（1〜3）から写真の整理（4）までを順番に行う。

start_windows.bat / start_mac.command から呼び出される。
Python の標準機能だけで動くように書いてある（部品のインストール前に動かすため）。
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = "gemma3:4b"
OLLAMA_URL = "http://localhost:11434"
DOWNLOAD_PAGE = "https://ollama.com/download"
IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


def step(n: int, text: str) -> None:
    print(f"\n===== {n}. {text} =====")


def ask_yes(question: str) -> bool:
    return input(f"{question} (y/n): ").strip().lower() in ("y", "yes", "はい")


# ---------- 1. Ollama のインストール ----------

def find_ollama() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    candidates = []
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        candidates.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
    if IS_MAC:
        candidates += [
            Path("/usr/local/bin/ollama"),
            Path("/opt/homebrew/bin/ollama"),
            Path("/Applications/Ollama.app/Contents/Resources/ollama"),
        ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def install_ollama() -> str | None:
    if IS_WINDOWS and shutil.which("winget"):
        print("Ollama をインストールします（画面の指示に従ってください）...")
        subprocess.run(["winget", "install", "-e", "--id", "Ollama.Ollama",
                        "--accept-source-agreements", "--accept-package-agreements"])
    elif IS_MAC and shutil.which("brew"):
        print("Ollama をインストールします...")
        subprocess.run(["brew", "install", "--cask", "ollama"])
    return find_ollama()


def server_running() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=3) as res:
            json.loads(res.read())
        return True
    except Exception:
        return False


def start_server(ollama: str) -> bool:
    if server_running():
        return True
    print("Ollama を起動しています...")
    if IS_MAC and Path("/Applications/Ollama.app").exists():
        subprocess.run(["open", "-a", "Ollama"])
    else:
        flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
        subprocess.Popen([ollama, "serve"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags)
    for _ in range(30):
        time.sleep(1)
        if server_running():
            return True
    return False


# ---------- 2. AI モデルの取得 ----------

def model_installed() -> bool:
    with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=10) as res:
        names = {m.get("name") for m in json.loads(res.read()).get("models", [])}
    return MODEL in names


# ---------- 3. アプリの部品のインストール ----------

def install_requirements() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(HERE / "requirements.txt")]
    )
    return result.returncode == 0


# ---------- 4. 写真の整理 ----------

def choose_folder(title: str, must_exist: bool = True) -> Path | None:
    """フォルダ選択画面を出す。使えない環境ではパスを入力してもらう。"""
    print(f"→ {title}")
    try:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title=title, mustexist=must_exist)
        root.destroy()
        if chosen:
            print(f"   {chosen}")
            return Path(chosen)
        return None
    except Exception:
        text = input("   フォルダの場所を入力してください（フォルダをここにドラッグしても可）: ")
        text = text.strip().strip('"').strip("'")
        return Path(text) if text else None


def run_organizer(args: list[str]) -> int:
    return subprocess.run(
        [sys.executable, "-m", "photo_organizer", *args], cwd=HERE
    ).returncode


def main() -> int:
    print("写真整理アプリ（無料版）のかんたん実行です。")

    step(1, "Ollama（パソコンで動く AI）の準備")
    ollama = find_ollama()
    if not ollama:
        ollama = install_ollama()
    if not ollama:
        print("Ollama を自動でインストールできませんでした。")
        print(f"ブラウザでダウンロードページを開きます: {DOWNLOAD_PAGE}")
        print("インストールが終わったら、もう一度このファイルを実行してください。")
        webbrowser.open(DOWNLOAD_PAGE)
        return 1
    if not start_server(ollama):
        print("Ollama を起動できませんでした。Ollama アプリを手動で起動してから、もう一度実行してください。")
        return 1
    print("Ollama の準備ができました。")

    step(2, f"AI モデル（{MODEL}）の取得")
    if model_installed():
        print("取得済みです。")
    else:
        print("初回のみ約 3GB をダウンロードします。しばらくお待ちください...")
        if subprocess.run([ollama, "pull", MODEL]).returncode != 0:
            print("モデルの取得に失敗しました。インターネット接続を確認して、もう一度実行してください。")
            return 1

    step(3, "アプリの部品のインストール")
    if not install_requirements():
        print("部品のインストールに失敗しました。上に表示されたエラーを確認してください。")
        return 1

    step(4, "写真の整理")
    photos = choose_folder("整理したい写真が入っているフォルダを選んでください")
    ref = choose_folder("探したい人物の顔がはっきり写った写真（1〜数枚）を入れたフォルダを選んでください")
    output = choose_folder("整理した写真を保存するフォルダを選んでください", must_exist=False)
    if not (photos and ref and output):
        print("フォルダが選ばれなかったので終了します。")
        return 1

    args = [str(photos), str(output), "--ref", str(ref), "--free"]
    print("\nまず、保存せずに同じ人物の写真がどれかを確認します（お試し実行・タイトルなし）。\n")
    if run_organizer([*args, "--dry-run", "--no-title"]) != 0:
        return 1

    if not ask_yes("\nこの写真をタイトル付きで保存しますか？（元の写真はそのまま残ります）"):
        print("保存せずに終了しました。")
        print("別人が混ざる・取りこぼしが多いときは、参照写真を増やすと精度が上がります。")
        return 0
    print("\nAI がタイトルを考えながら保存します（1 枚あたり数秒〜十数秒かかります）...\n")
    code = run_organizer(args)
    if code == 0:
        print(f"\n完了しました。保存先: {output}")
        if IS_WINDOWS:
            os.startfile(output)  # 保存先フォルダを開く
        elif IS_MAC:
            subprocess.run(["open", str(output)])
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断しました。")
        sys.exit(1)
