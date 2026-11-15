#!/bin/bash
cd "$(dirname "$0")"
if command -v python3 > /dev/null 2>&1 && python3 -c "import sys; sys.exit(sys.version_info < (3, 10))"; then
    python3 easy_start.py
else
    echo "Python 3.10 以上が見つかりません。"
    echo "開いたページから Python をインストールして、もう一度このファイルを開いてください。"
    open https://www.python.org/downloads/
fi
echo
read -n 1 -s -r -p "何かキーを押すと閉じます"
