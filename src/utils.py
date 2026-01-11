import subprocess
import winreg
import ctypes
import sys
import logging
import re
from pathlib import Path
from config import APP_NAME

# --- WINDOWS DARK MODE HACK ---
def apply_dark_title_bar(window):
    try:
        window.update()
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        get_parent = ctypes.windll.user32.GetParent
        hwnd = get_parent(window.winfo_id())
        rendering_policy = DWMWA_USE_IMMERSIVE_DARK_MODE
        value = ctypes.c_int(1)
        set_window_attribute(hwnd, rendering_policy, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass

# --- AUTORUN LOGIC ---
class AutoRun:
    KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def get_state():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AutoRun.KEY, 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        except (FileNotFoundError, Exception):
            return False

    @staticmethod
    def set_state(enable):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AutoRun.KEY, 0, winreg.KEY_WRITE) as key:
                if enable:
                    exe = sys.executable
                    if "python.exe" in exe:
                        exe = exe.replace("python.exe", "pythonw.exe")
                    script = str(Path(sys.argv[0]).resolve()) # Берем путь к запущенному скрипту
                    cmd = f'"{exe}" "{script}"'
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                    logging.info("Autorun enabled.")
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                        logging.info("Autorun disabled.")
                    except FileNotFoundError:
                        pass
        except Exception as e:
            logging.error("Failed to change autorun state: %s", e)

# --- POWER PLAN LOGIC ---
def get_system_power_plans():
    plans = {}
    try:
        result = subprocess.run(["powercfg", "/list"], capture_output=True, text=True, encoding='cp866', errors='ignore')
        output = result.stdout
        pattern = re.compile(r"GUID:\s+([a-fA-F0-9\-]+)\s+\((.+)\)")
        for line in output.splitlines():
            match = pattern.search(line)
            if match:
                plans[match.group(2)] = match.group(1)
    except Exception as e:
        logging.error("Failed to list power plans", exc_info=e)
    return plans

def set_power_mode(mode_guid):
    if not mode_guid: return
    try:
        res = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, check=False)
        if mode_guid.lower() not in res.stdout.lower():
            subprocess.run(["powercfg", "/setactive", mode_guid], check=False)
            logging.info(f"Power scheme switched to GUID: {mode_guid}")
    except Exception as e:
        logging.error("Failed to switch power scheme.", exc_info=e)