import logging
from pathlib import Path
try:
    from PIL import Image
except ImportError:
    pass # Обработается в main

ICONS_DIR = Path(__file__).parent / 'icons'

def load_icon(filename, fallback_color):
    icon_path = ICONS_DIR / filename
    try:
        img = Image.open(icon_path).convert("RGBA")
        return img
    except FileNotFoundError:
        logging.warning(f"Icon file missing: {filename}. Using fallback color box.")
        return Image.new('RGBA', (16, 16), fallback_color)
    except NameError:
        return None

# Будут инициализированы при импорте, если PIL доступен
red_image = load_icon('thunder_red.png', 'red')
green_image = load_icon('thunder_green.png', 'green')
grey_image = load_icon('thunder_grey.png', 'grey')
trouble_image = load_icon('troubleshooting.png', 'yellow')