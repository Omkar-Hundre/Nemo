"""Windows startup registration via Startup folder and HKCU Run registry key."""

# 1. Standard library imports
import logging
import os
from pathlib import Path
import shutil
import sys
import winreg

# 2. Third-party imports
# (None)

logger = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "NemoDesktopVoice"


def _get_startup_cmd_path() -> Path:
    startup_dir = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    return startup_dir / "nemo-voice-avatar.cmd"


def set_autostart(enable: bool = True) -> bool:
    """Register or deregister Nemo to automatically launch when user logs in."""
    cmd_file = _get_startup_cmd_path()
    try:
        if enable:
            # 1. Write Startup folder launcher
            cmd_file.parent.mkdir(parents=True, exist_ok=True)
            nemo_exe = shutil.which("nemo")
            if nemo_exe:
                content = f'@echo off\r\nstart "" /B "{nemo_exe}" voice\r\n'
            else:
                content = f'@echo off\r\nstart "" /B "{sys.executable}" -m nemo voice\r\n'
            cmd_file.write_text(content, encoding="utf-8")

            # 2. Also register in HKCU Run for redundancy
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    RUN_KEY,
                    0,
                    winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
                )
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, str(cmd_file))
                winreg.CloseKey(key)
            except Exception:
                pass

            logger.info("Successfully enabled auto-start for Nemo voice: %s", cmd_file)
            return True
        else:
            # 1. Delete Startup folder launcher
            if cmd_file.exists():
                cmd_file.unlink()

            # 2. Delete HKCU Run
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(key, APP_NAME)
                winreg.CloseKey(key)
            except Exception:
                pass

            logger.info("Successfully removed auto-start for Nemo voice")
            return True
    except Exception as e:
        logger.error("Failed to update Windows auto-start: %s", e)
        return False


def is_autostart_enabled() -> bool:
    """Check if Nemo voice avatar is set to launch on boot."""
    cmd_file = _get_startup_cmd_path()
    if cmd_file.exists():
        return True
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE)
        val, _ = winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return bool(val)
    except Exception:
        return False
