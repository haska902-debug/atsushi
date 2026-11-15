"""バッテリー残量の確認（Windows / Mac / Linux）。標準機能だけで動く。"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DEFAULT_BATTERY_LIMIT = 20  # 電源につながず、残量がこの % 以下になったら一時停止する


def battery_status() -> tuple[int, bool] | None:
    """(残量 %, 電源につながっているか) を返す。バッテリーが無い・分からない場合は None。"""
    try:
        if sys.platform == "win32":
            return _windows()
        if sys.platform == "darwin":
            out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
            return parse_pmset(out)
        return _linux()
    except Exception:
        return None


def _windows() -> tuple[int, bool] | None:
    import ctypes
    from ctypes import wintypes

    class SystemPowerStatus(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", wintypes.BYTE),
            ("BatteryFlag", wintypes.BYTE),
            ("BatteryLifePercent", wintypes.BYTE),
            ("SystemStatusFlag", wintypes.BYTE),
            ("BatteryLifeTime", wintypes.DWORD),
            ("BatteryFullLifeTime", wintypes.DWORD),
        ]

    status = SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    flag = status.BatteryFlag & 0xFF
    percent = status.BatteryLifePercent & 0xFF
    if flag == 128 or percent == 255:  # バッテリー無し（デスクトップ PC）・不明
        return None
    return percent, (status.ACLineStatus & 0xFF) != 0


def parse_pmset(out: str) -> tuple[int, bool] | None:
    match = re.search(r"(\d+)%", out)
    if not match:
        return None
    return int(match.group(1)), "AC Power" in out


def _linux() -> tuple[int, bool] | None:
    for bat in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        percent = int((bat / "capacity").read_text().strip())
        status = (bat / "status").read_text().strip()
        return percent, status != "Discharging"
    return None


def low_battery_message(limit: int = DEFAULT_BATTERY_LIMIT) -> str | None:
    """電源につながっておらず残量が limit % 以下なら、止める理由を返す。"""
    status = battery_status()
    if status is None or limit <= 0:
        return None
    percent, plugged = status
    if not plugged and percent <= limit:
        return (
            f"バッテリー残量が {percent}% になったので、安全のため一時停止しました。\n"
            "電源アダプターにつないでから、もう一度実行すると続きから再開します。"
        )
    return None
