@echo off
chcp 65001 > nul
cd /d "%~dp0"
where py > nul 2> nul
if %errorlevel% == 0 (
    py -3 easy_start.py
    goto end
)
where python > nul 2> nul
if %errorlevel% == 0 (
    python easy_start.py
    goto end
)
echo Python が見つかりません。
echo 開いたページから Python をインストールしてください。
echo インストール画面では「Add python.exe to PATH」にチェックを入れてください。
echo インストール後、もう一度このファイルをダブルクリックしてください。
start https://www.python.org/downloads/
:end
pause
