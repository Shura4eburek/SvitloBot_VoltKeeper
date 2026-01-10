import asyncio
import configparser
import logging
import subprocess
import sys
import threading
import webbrowser
import io
import winreg
import re
import ctypes
from datetime import datetime, timezone
from pathlib import Path
from tkinter import Tk, Label, Entry, Button, Toplevel, Checkbutton, BooleanVar, scrolledtext, END, Frame
from tkinter import ttk

try:
    # Добавили ImageTk для иконок окон
    from PIL import Image, ImageTk
    import pystray
    from telethon import TelegramClient, events
except ImportError as e:
    logging.basicConfig(level=logging.DEBUG)
    logging.error("A required library is not installed. Please run 'pip install pystray pillow telethon'. Details: %s",
                  e)
    sys.exit(1)

# --- LOGGING SETUP ---
log_stream = io.StringIO()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(log_stream)
    ]
)

# --- GLOBAL STATE & CONFIG ---
CONFIG_FILE = Path(__file__).parent / 'config.ini'
APP_NAME = "SvitloBot"


class State:
    last_status = None
    last_change_time = None
    last_break_time = None
    last_msg_text = ""

    def __init__(self):
        self.last_change_time = datetime.min.replace(tzinfo=timezone.utc)
        self.last_break_time = datetime.min.replace(tzinfo=timezone.utc)


state = State()
client = None
loop = None
app_running = True
root = None
tray_icon = None
console_window = None
settings_window = None


# --- WINDOWS DARK MODE HACK ---
def apply_dark_title_bar(window):
    """
    Принудительно включает темный заголовок окна (Title Bar) в Windows 10/11.
    """
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


# --- ICONS ---
ICONS_DIR = Path(__file__).parent / 'icons'


def load_icon(filename, fallback_color):
    icon_path = ICONS_DIR / filename
    try:
        img = Image.open(icon_path).convert("RGBA")
        return img
    except FileNotFoundError:
        logging.warning(f"Icon file missing: {filename}. Using fallback color box.")
        return Image.new('RGBA', (16, 16), fallback_color)


# Иконки трея
red_image = load_icon('thunder_red.png', 'red')
green_image = load_icon('thunder_green.png', 'green')
grey_image = load_icon('thunder_grey.png', 'grey')
trouble_image = load_icon('troubleshooting.png', 'yellow')


# --- AUTORUN LOGIC ---
class AutoRun:
    KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def get_state():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AutoRun.KEY, 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    @staticmethod
    def set_state(enable):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AutoRun.KEY, 0, winreg.KEY_WRITE) as key:
                if enable:
                    exe = sys.executable
                    if "python.exe" in exe:
                        exe = exe.replace("python.exe", "pythonw.exe")
                    script = str(Path(__file__).resolve())
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
        result = subprocess.run(["powercfg", "/list"], capture_output=True, text=True, encoding='cp866',
                                errors='ignore')
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


# --- CONFIGURATION ---
def load_config():
    config = configparser.ConfigParser()
    if not CONFIG_FILE.exists():
        config['telegram'] = {'api_id': '', 'api_hash': '', 'channel_username': ''}
        config['general'] = {'developer_mode': 'false'}
        config['power'] = {'on_guid': '', 'off_guid': ''}
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)
    config.read(CONFIG_FILE, encoding='utf-8')
    if 'power' not in config:
        config.add_section('power')
        plans = get_system_power_plans()
        high = next((g for n, g in plans.items() if "High" in n or "Висока" in n or "Максимальная" in n), "")
        save = next((g for n, g in plans.items() if "Save" in n or "Економ" in n or "Эконом" in n), "")
        config.set('power', 'on_guid', high)
        config.set('power', 'off_guid', save)
    if 'general' not in config:
        config.add_section('general')
        config.set('general', 'developer_mode', 'false')
    return config


config = load_config()


# --- TELETHON LOGIC ---
def format_duration(start_time):
    if not start_time or start_time == datetime.min.replace(tzinfo=timezone.utc): return "N/A"
    diff = datetime.now(timezone.utc) - start_time
    total_seconds = int(diff.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m"


async def process_status(message, current_tray_icon):
    if not message or not message.text: return False
    text = " ".join(message.text.split())

    if "Канал зупинено на технічну перерву!" in text:
        logging.info("Message detected: Channel on Technical Break!")
        state.last_break_time = message.date
        update_tray_icon(current_tray_icon)
        return False

    new_status = "OFF" if "Світло зникло" in text else "ON" if "Світло з'явилося" in text else None

    if new_status and new_status != state.last_status:
        logging.info("Status change detected: %s -> %s", state.last_status, new_status)
        state.last_status = new_status
        state.last_change_time = message.date
        state.last_msg_text = text.split('🕓')[0].strip()

        target_guid = config.get('power', 'off_guid', fallback='') if new_status == "OFF" else config.get('power',
                                                                                                          'on_guid',
                                                                                                          fallback='')
        if target_guid:
            set_power_mode(target_guid)
        else:
            logging.warning(f"Power plan for {new_status} is not configured!")

        update_tray_icon(current_tray_icon)
        return True
    return False


def update_tray_icon(current_tray_icon):
    if not current_tray_icon or not current_tray_icon.visible: return
    if state.last_break_time > state.last_change_time:
        current_tray_icon.icon = trouble_image
        current_tray_icon.title = f"Channel Maintenance (since {state.last_break_time.strftime('%H:%M')})"
        return
    if state.last_status == "ON":
        current_tray_icon.icon = green_image
        current_tray_icon.title = f"Electricity is ON for {format_duration(state.last_change_time)}"
    elif state.last_status == "OFF":
        current_tray_icon.icon = red_image
        current_tray_icon.title = f"Electricity is OFF for {format_duration(state.last_change_time)}"
    else:
        current_tray_icon.icon = grey_image
        current_tray_icon.title = "Status unknown"


async def telegram_main(current_tray_icon):
    global client
    api_id = config.get('telegram', 'api_id')
    api_hash = config.get('telegram', 'api_hash')
    channel = config.get('telegram', 'channel_username')
    if any(s in str(v) for s in ('YOUR_API', 'YOUR_CHANNEL') for v in (api_id, api_hash, channel)):
        logging.warning("API details or channel are not configured. Please open Settings.")
        update_tray_icon(current_tray_icon)
        return
    client = TelegramClient(str(Path(__file__).parent / 'energy_control_session'), api_id, api_hash, loop=loop)

    @client.on(events.NewMessage(chats=channel))
    async def handler(event):
        await process_status(event.message, current_tray_icon)

    try:
        logging.info("Connecting to Telegram as %s...", api_id)
        await client.start()
        logging.info("Telethon client started. Listening on channel: %s", channel)
        async for message in client.iter_messages(channel, limit=10):
            if await process_status(message, current_tray_icon): logging.info("Initial status found."); break
        else:
            logging.warning("No initial status found in the last 10 messages.")
        update_tray_icon(current_tray_icon)
        while app_running: await asyncio.sleep(0.2)
    except Exception as e:
        logging.error("A critical error occurred in the Telegram thread.", exc_info=e)
    finally:
        if client and not loop.is_closed():
            try:
                if client.is_connected():
                    logging.info("Disconnecting client...")
                    await asyncio.wait_for(client.disconnect(), timeout=5.0)
            except Exception as e:
                logging.debug("Silent error during disconnect: %s", e)
        logging.info("Telegram thread finished.")


def run_telegram_thread(current_tray_icon):
    global loop
    loop = asyncio.new_event_loop();
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(telegram_main(current_tray_icon))
    finally:
        loop.close()

1
# --- GUI ---
class ConsoleWindow:
    def __init__(self, master):
        global console_window
        if console_window: console_window.lift(); return
        self.win = Toplevel(master);
        self.win.title("Console Log");
        self.win.geometry("600x400");
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)

        # Установка иконки окна
        try:
            icon_img = load_icon("terminal.png", "white")
            self.icon = ImageTk.PhotoImage(icon_img)
            self.win.iconphoto(False, self.icon)
        except Exception:
            pass

        self.win.configure(bg='black')
        apply_dark_title_bar(self.win)

        self.text_area = scrolledtext.ScrolledText(self.win, state='normal', wrap='word', background='black',
                                                   foreground='white', insertbackground='white', borderwidth=0)
        self.text_area.pack(expand=True, fill='both')
        self.text_area.insert(END, log_stream.getvalue());
        self.text_area.see(END)
        self.handler = self.LogHandler(self.text_area);
        logging.getLogger().addHandler(self.handler)
        console_window = self.win

    def on_close(self):
        global console_window
        logging.getLogger().removeHandler(self.handler);
        self.win.destroy();
        console_window = None

    class LogHandler(logging.Handler):
        def __init__(self, text_widget): super().__init__(); self.text_widget = text_widget

        def emit(self, record): self.text_widget.insert(END, self.format(record) + '\n'); self.text_widget.see(END)


class SettingsWindow:
    def __init__(self, master, on_close_callback):
        self.master, self.on_close_callback = master, on_close_callback
        self.win = Toplevel(master)
        self.win.title("Settings")

        # Установка иконки окна
        try:
            icon_img = load_icon("settings.png", "white")
            self.icon = ImageTk.PhotoImage(icon_img)
            self.win.iconphoto(False, self.icon)
        except Exception:
            pass

        # Цвета
        bg_color = "#1e1e1e"
        fg_color = "#ffffff"
        entry_bg = "#2d2d2d"
        entry_border = "#3f3f3f"
        accent_color = "#0078d7"
        header_color = "#3a9ad9"

        # --- НАСТРОЙКА СТИЛЕЙ ---
        self.style = ttk.Style()
        self.style.theme_use('clam')

        self.style.configure("Dark.TCombobox",
                             fieldbackground=entry_bg,
                             background=bg_color,
                             foreground=fg_color,
                             darkcolor=bg_color,
                             lightcolor=bg_color,
                             selectbackground=accent_color,
                             selectforeground=fg_color,
                             bordercolor=entry_border,
                             arrowcolor=fg_color)

        self.style.map("Dark.TCombobox",
                       fieldbackground=[('readonly', entry_bg)],
                       selectbackground=[('readonly', entry_bg)],
                       selectforeground=[('readonly', fg_color)])

        self.win.option_add('*TCombobox*Listbox.background', entry_bg)
        self.win.option_add('*TCombobox*Listbox.foreground', fg_color)
        self.win.option_add('*TCombobox*Listbox.selectBackground', accent_color)
        self.win.option_add('*TCombobox*Listbox.selectForeground', fg_color)

        self.win.configure(bg=bg_color)
        self.win.resizable(False, False)

        apply_dark_title_bar(self.win)

        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        self.win.grab_set()

        self.power_plans = get_system_power_plans()
        self.plan_names = list(self.power_plans.keys())

        self.win.columnconfigure(1, weight=1)
        pad_x, pad_y = 20, 8

        # --- ХЕЛПЕРЫ ---
        def create_header(row, text, top_pad=0):
            Label(self.win, text=text, bg=bg_color, fg=header_color,
                  font=("Segoe UI", 11, "bold")).grid(
                row=row, column=0, columnspan=2, pady=(top_pad, 5))

        def create_separator(row):
            sep = Frame(self.win, bg=entry_border, height=1)
            sep.grid(row=row, column=0, columnspan=2, sticky="ew", padx=pad_x, pady=(15, 5))

        def create_entry(row, label_text):
            Label(self.win, text=label_text, bg=bg_color, fg=fg_color, font=("Segoe UI", 9)).grid(
                row=row, column=0, padx=(pad_x, 5), pady=pad_y, sticky="w")
            entry = Entry(self.win, bg=entry_bg, fg=fg_color,
                          insertbackground="white", relief="flat",
                          highlightbackground=entry_border, highlightcolor=accent_color,
                          highlightthickness=1, font=("Segoe UI", 10), width=35)
            entry.grid(row=row, column=1, padx=(5, pad_x), pady=pad_y, sticky="we")
            return entry

        # === БЛОК 1: TELEGRAM API ===
        create_header(0, "Telegram API", top_pad=15)

        self.api_id_entry = create_entry(1, "API ID:")
        self.api_hash_entry = create_entry(2, "API Hash:")

        btn_get_api = Button(self.win, text="🌐 Get API Credentials",
                             command=lambda: webbrowser.open("https://my.telegram.org/apps"),
                             bg=bg_color, fg="#3a9ad9", bd=0, cursor="hand2",
                             font=("Segoe UI", 9, "underline"), activebackground=bg_color,
                             activeforeground=accent_color)
        btn_get_api.grid(row=3, column=1, sticky="w", padx=pad_x, pady=(0, 5))

        create_separator(4)

        # === БЛОК 2: МОНИТОРИНГ И ПИТАНИЕ ===
        create_header(5, "Monitoring & Control")

        self.channel_entry = create_entry(6, "TG Channel:")

        Label(self.win, text="Power (Light ON):", bg=bg_color, fg=fg_color, font=("Segoe UI", 9)).grid(
            row=7, column=0, padx=(pad_x, 5), pady=pad_y, sticky="w")

        self.combo_on = ttk.Combobox(self.win, values=self.plan_names, state="readonly",
                                     font=("Segoe UI", 9), width=33, style="Dark.TCombobox")
        self.combo_on.grid(row=7, column=1, padx=(5, pad_x), pady=pad_y, sticky="we")

        Label(self.win, text="Power (Light OFF):", bg=bg_color, fg=fg_color, font=("Segoe UI", 9)).grid(
            row=8, column=0, padx=(pad_x, 5), pady=pad_y, sticky="w")

        self.combo_off = ttk.Combobox(self.win, values=self.plan_names, state="readonly",
                                      font=("Segoe UI", 9), width=33, style="Dark.TCombobox")
        self.combo_off.grid(row=8, column=1, padx=(5, pad_x), pady=pad_y, sticky="we")

        create_separator(9)

        # === БЛОК 3: СИСТЕМА ===
        create_header(10, "System Settings")

        self.autorun_var = BooleanVar()
        self.dev_mode_var = BooleanVar()
        cb_style = {'bg': bg_color, 'fg': fg_color, 'selectcolor': '#333333',
                    'activebackground': bg_color, 'activeforeground': fg_color, 'font': ("Segoe UI", 9)}

        Checkbutton(self.win, text="Start with Windows", variable=self.autorun_var, **cb_style).grid(
            row=11, column=0, columnspan=2, padx=pad_x, pady=(5, 0), sticky="w")
        Checkbutton(self.win, text="Developer Mode (Show Console)", variable=self.dev_mode_var, **cb_style).grid(
            row=12, column=0, columnspan=2, padx=pad_x, pady=(2, 5), sticky="w")

        # === КНОПКИ ===
        btn_frame = Frame(self.win, bg=bg_color)
        btn_frame.grid(row=13, column=0, columnspan=2, pady=(20, 20))

        Button(btn_frame, text="Save", command=self.save_and_close,
               bg=accent_color, fg="white", bd=0, width=12, height=1, font=("Segoe UI", 9, "bold")).pack(side="left",
                                                                                                         padx=10)
        Button(btn_frame, text="Cancel", command=self.cancel,
               bg="#444444", fg="white", bd=0, width=12, height=1, font=("Segoe UI", 9)).pack(side="left", padx=10)

        self.load_settings()
        self.win.protocol("WM_DELETE_WINDOW", self.cancel)

        self.win.attributes('-topmost', True)
        self.win.after(100, lambda: self.win.attributes('-topmost', False))
        self.win.update_idletasks()

    def load_settings(self):
        self.api_id_entry.insert(0, config.get('telegram', 'api_id'))
        self.api_hash_entry.insert(0, config.get('telegram', 'api_hash'))
        self.channel_entry.insert(0, config.get('telegram', 'channel_username'))
        self.dev_mode_var.set(config.getboolean('general', 'developer_mode'))
        self.autorun_var.set(AutoRun.get_state())
        saved_on = config.get('power', 'on_guid', fallback='')
        saved_off = config.get('power', 'off_guid', fallback='')
        guid_to_name = {v: k for k, v in self.power_plans.items()}
        if saved_on in guid_to_name:
            self.combo_on.set(guid_to_name[saved_on])
        elif self.plan_names:
            self.combo_on.current(0)
        if saved_off in guid_to_name:
            self.combo_off.set(guid_to_name[saved_off])
        elif self.plan_names:
            self.combo_off.current(0)

    def save_and_close(self):
        config.set('telegram', 'api_id', self.api_id_entry.get())
        config.set('telegram', 'api_hash', self.api_hash_entry.get())
        config.set('telegram', 'channel_username', self.channel_entry.get())
        config.set('general', 'developer_mode', 'true' if self.dev_mode_var.get() else 'false')
        name_on = self.combo_on.get()
        name_off = self.combo_off.get()
        if name_on in self.power_plans: config.set('power', 'on_guid', self.power_plans[name_on])
        if name_off in self.power_plans: config.set('power', 'off_guid', self.power_plans[name_off])
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)
        AutoRun.set_state(self.autorun_var.get())
        self.win.destroy()
        self.on_close_callback()

    def cancel(self):
        if self.win.winfo_exists(): self.win.destroy()
        self.on_close_callback()


# --- TRAY & UI GLUE ---
def open_console_threadsafe(icon, item):
    if root: root.after(0, open_console_ui)


def open_console_ui():
    try:
        ConsoleWindow(root)
    except Exception as e:
        logging.error("Failed to create ConsoleWindow.", exc_info=e)


def open_settings_threadsafe(icon, item):
    if root: root.after(0, open_settings_ui)


def open_settings_ui():
    global settings_window
    try:
        if settings_window is not None:
            try:
                if settings_window.win.winfo_exists():
                    settings_window.win.deiconify()
                    settings_window.win.lift()
                    settings_window.win.focus_force()
                    return
            except:
                settings_window = None

        def on_settings_closed():
            global settings_window
            settings_window = None
            if tray_icon: tray_icon.menu = get_tray_menu()

        settings_window = SettingsWindow(root, on_settings_closed)
    except Exception as e:
        logging.error("Failed to create SettingsWindow.", exc_info=e)
        settings_window = None


def get_tray_menu():
    menu_items = [pystray.MenuItem('Settings', open_settings_threadsafe)]
    if config.getboolean('general', 'developer_mode'):
        menu_items.append(pystray.MenuItem('Console', open_console_threadsafe))
    menu_items.append(pystray.MenuItem('Exit', exit_app))
    return pystray.Menu(*menu_items)


def exit_app(icon, item):
    global app_running
    app_running = False
    if icon: icon.stop()
    if root: root.after(0, root.destroy)


# --- MAIN EXECUTION ---
def main():
    global root, tray_icon
    root = Tk()
    root.withdraw()
    tray_icon = pystray.Icon('SvitloBot', grey_image, "SvitloBot", get_tray_menu())
    telegram_thread = threading.Thread(target=run_telegram_thread, args=(tray_icon,), daemon=True)
    telegram_thread.start()
    pystray_thread = threading.Thread(target=tray_icon.run, daemon=True)
    pystray_thread.start()
    root.mainloop()


if __name__ == '__main__':
    main()