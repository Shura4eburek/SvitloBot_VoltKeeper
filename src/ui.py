import logging
import webbrowser
from tkinter import Toplevel, Label, Entry, Button, Checkbutton, BooleanVar, scrolledtext, Frame, END
from tkinter import ttk

try:
    from PIL import ImageTk
except ImportError:
    pass

from config import config, save_config
from utils import AutoRun, get_system_power_plans, apply_dark_title_bar
from resources import load_icon
from logger import get_log_stream

# Глобальные ссылки на окна, чтобы не открывать дубликаты
console_window_ref = None
settings_window_ref = None


class ConsoleWindow:
    def __init__(self, master):
        global console_window_ref
        if console_window_ref:
            console_window_ref.lift()
            return

        self.win = Toplevel(master)
        self.win.title("Console Log")
        self.win.geometry("600x400")
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)

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
        self.text_area.insert(END, get_log_stream().getvalue())
        self.text_area.see(END)

        self.handler = self.LogHandler(self.text_area)
        logging.getLogger().addHandler(self.handler)
        console_window_ref = self.win

    def on_close(self):
        global console_window_ref
        logging.getLogger().removeHandler(self.handler)
        self.win.destroy()
        console_window_ref = None

    class LogHandler(logging.Handler):
        def __init__(self, text_widget):
            super().__init__()
            self.text_widget = text_widget

        def emit(self, record):
            self.text_widget.insert(END, self.format(record) + '\n')
            self.text_widget.see(END)


class SettingsWindow:
    def __init__(self, master, on_close_callback):
        self.master = master
        self.on_close_callback = on_close_callback
        self.win = Toplevel(master)
        self.win.title("Settings")

        try:
            icon_img = load_icon("settings.png", "white")
            self.icon = ImageTk.PhotoImage(icon_img)
            self.win.iconphoto(False, self.icon)
        except Exception:
            pass

        # Styles & Colors
        bg_color, fg_color = "#1e1e1e", "#ffffff"
        entry_bg, entry_border = "#2d2d2d", "#3f3f3f"
        accent_color, header_color = "#0078d7", "#3a9ad9"

        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure("Dark.TCombobox", fieldbackground=entry_bg, background=bg_color, foreground=fg_color,
                             darkcolor=bg_color, lightcolor=bg_color, selectbackground=accent_color,
                             selectforeground=fg_color, bordercolor=entry_border, arrowcolor=fg_color)
        self.style.map("Dark.TCombobox", fieldbackground=[('readonly', entry_bg)],
                       selectbackground=[('readonly', entry_bg)], selectforeground=[('readonly', fg_color)])
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

        # --- Helpers ---
        def create_header(row, text, top_pad=0):
            Label(self.win, text=text, bg=bg_color, fg=header_color, font=("Segoe UI", 11, "bold")).grid(
                row=row, column=0, columnspan=2, pady=(top_pad, 5))

        def create_separator(row):
            Frame(self.win, bg=entry_border, height=1).grid(row=row, column=0, columnspan=2, sticky="ew", padx=pad_x,
                                                            pady=(15, 5))

        def create_entry(row, label_text):
            Label(self.win, text=label_text, bg=bg_color, fg=fg_color, font=("Segoe UI", 9)).grid(row=row, column=0,
                                                                                                  padx=(pad_x, 5),
                                                                                                  pady=pad_y,
                                                                                                  sticky="w")
            e = Entry(self.win, bg=entry_bg, fg=fg_color, insertbackground="white", relief="flat",
                      highlightbackground=entry_border, highlightcolor=accent_color, highlightthickness=1,
                      font=("Segoe UI", 10), width=35)
            e.grid(row=row, column=1, padx=(5, pad_x), pady=pad_y, sticky="we")
            return e

        # --- UI Build ---
        create_header(0, "Telegram API", top_pad=15)
        self.api_id_entry = create_entry(1, "API ID:")
        self.api_hash_entry = create_entry(2, "API Hash:")

        btn_get = Button(self.win, text="🌐 Get API Credentials",
                         command=lambda: webbrowser.open("https://my.telegram.org/apps"),
                         bg=bg_color, fg="#3a9ad9", bd=0, cursor="hand2", font=("Segoe UI", 9, "underline"),
                         activebackground=bg_color, activeforeground=accent_color)
        btn_get.grid(row=3, column=1, sticky="w", padx=pad_x, pady=(0, 5))

        create_separator(4)
        create_header(5, "Monitoring & Control")
        self.channel_entry = create_entry(6, "TG Channel:")

        Label(self.win, text="Power (Light ON):", bg=bg_color, fg=fg_color, font=("Segoe UI", 9)).grid(row=7, column=0,
                                                                                                       padx=(pad_x, 5),
                                                                                                       pady=pad_y,
                                                                                                       sticky="w")
        self.combo_on = ttk.Combobox(self.win, values=self.plan_names, state="readonly", font=("Segoe UI", 9), width=33,
                                     style="Dark.TCombobox")
        self.combo_on.grid(row=7, column=1, padx=(5, pad_x), pady=pad_y, sticky="we")

        Label(self.win, text="Power (Light OFF):", bg=bg_color, fg=fg_color, font=("Segoe UI", 9)).grid(row=8, column=0,
                                                                                                        padx=(pad_x, 5),
                                                                                                        pady=pad_y,
                                                                                                        sticky="w")
        self.combo_off = ttk.Combobox(self.win, values=self.plan_names, state="readonly", font=("Segoe UI", 9),
                                      width=33, style="Dark.TCombobox")
        self.combo_off.grid(row=8, column=1, padx=(5, pad_x), pady=pad_y, sticky="we")

        create_separator(9)
        create_header(10, "System Settings")

        self.autorun_var = BooleanVar()
        self.dev_mode_var = BooleanVar()
        cb_style = {'bg': bg_color, 'fg': fg_color, 'selectcolor': '#333333', 'activebackground': bg_color,
                    'activeforeground': fg_color, 'font': ("Segoe UI", 9)}
        Checkbutton(self.win, text="Start with Windows", variable=self.autorun_var, **cb_style).grid(row=11, column=0,
                                                                                                     columnspan=2,
                                                                                                     padx=pad_x,
                                                                                                     pady=(5, 0),
                                                                                                     sticky="w")
        Checkbutton(self.win, text="Developer Mode (Show Console)", variable=self.dev_mode_var, **cb_style).grid(row=12,
                                                                                                                 column=0,
                                                                                                                 columnspan=2,
                                                                                                                 padx=pad_x,
                                                                                                                 pady=(
                                                                                                                     2,
                                                                                                                     5),
                                                                                                                 sticky="w")

        btn_frame = Frame(self.win, bg=bg_color)
        btn_frame.grid(row=13, column=0, columnspan=2, pady=(20, 20))
        Button(btn_frame, text="Save", command=self.save_and_close, bg=accent_color, fg="white", bd=0, width=12,
               height=1, font=("Segoe UI", 9, "bold")).pack(side="left", padx=10)
        Button(btn_frame, text="Cancel", command=self.cancel, bg="#444444", fg="white", bd=0, width=12, height=1,
               font=("Segoe UI", 9)).pack(side="left", padx=10)

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

        save_config(config)
        AutoRun.set_state(self.autorun_var.get())

        self.win.destroy()
        self.on_close_callback()

    def cancel(self):
        if self.win.winfo_exists(): self.win.destroy()
        self.on_close_callback()


def open_console_ui(root):
    try:
        ConsoleWindow(root)
    except Exception as e:
        logging.error("Failed to create ConsoleWindow.", exc_info=e)


def open_settings_ui(root, tray_icon, update_tray_cb):
    global settings_window_ref
    try:
        if settings_window_ref and settings_window_ref.win.winfo_exists():
            settings_window_ref.win.deiconify()
            settings_window_ref.win.lift()
            settings_window_ref.win.focus_force()
            return

        def on_closed():
            global settings_window_ref
            settings_window_ref = None
            if update_tray_cb: update_tray_cb()

        settings_window_ref = SettingsWindow(root, on_closed)
    except Exception as e:
        logging.error("Failed to create SettingsWindow.", exc_info=e)
        settings_window_ref = None