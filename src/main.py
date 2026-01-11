import threading
import asyncio
import sys
import logging
from tkinter import Tk

try:
    import pystray
except ImportError as e:
    print(f"Error: {e}. Please run pip install -r requirements.txt")
    sys.exit(1)

# Импорты из наших модулей
from logger import setup_logging
from config import config
from resources import grey_image
from bot import telegram_main, stop_bot, update_tray_icon
from ui import open_settings_ui, open_console_ui

# Setup Logging
setup_logging()

root = None
tray_icon = None
loop = None


def run_telegram_thread(icon):
    global loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(telegram_main(icon))
    finally:
        loop.close()


def exit_app(icon, item):
    logging.info("Exit requested. Shutting down...")
    stop_bot()  # Останавливает цикл в bot.py

    if icon: icon.stop()
    if root: root.after(0, root.destroy)


# --- Tray Callbacks Wrappers ---
def open_settings_threadsafe(icon, item):
    if root:
        # Передаем функцию обновления трея (чтобы обновить меню при закрытии)
        update_cb = lambda: setattr(tray_icon, 'menu', get_tray_menu())
        root.after(0, lambda: open_settings_ui(root, tray_icon, update_cb))


def open_console_threadsafe(icon, item):
    if root: root.after(0, lambda: open_console_ui(root))


def get_tray_menu():
    menu_items = [pystray.MenuItem('Settings', open_settings_threadsafe)]
    if config.getboolean('general', 'developer_mode'):
        menu_items.append(pystray.MenuItem('Console', open_console_threadsafe))
    menu_items.append(pystray.MenuItem('Exit', exit_app))
    return pystray.Menu(*menu_items)


def main():
    global root, tray_icon
    root = Tk()
    root.withdraw()

    tray_icon = pystray.Icon('SvitloBot', grey_image, "SvitloBot", get_tray_menu())

    # Запуск Telegram в отдельном потоке
    telegram_thread = threading.Thread(target=run_telegram_thread, args=(tray_icon,), daemon=True)
    telegram_thread.start()

    # Запуск иконки в трее (блокирующий вызов для трея, но в отдельном потоке pystray сам разберется, если запустить так)
    # Pystray run блокирует поток. Поэтому запускаем его в отдельном потоке, а Tkinter в основном.
    pystray_thread = threading.Thread(target=tray_icon.run, daemon=True)
    pystray_thread.start()

    logging.info("Application startup complete. Running UI main loop.")
    root.mainloop()
    logging.info("Application shutting down.")


if __name__ == '__main__':
    main()