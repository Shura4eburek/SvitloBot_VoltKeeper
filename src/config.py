import configparser
import sys
from pathlib import Path
from datetime import datetime, timezone

APP_NAME = "SvitloBot"
CONFIG_FILE = Path(__file__).parent / 'config.ini'


class State:
    def __init__(self):
        self.last_status = None
        self.last_change_time = datetime.min.replace(tzinfo=timezone.utc)
        self.last_break_time = datetime.min.replace(tzinfo=timezone.utc)
        self.last_msg_text = ""


# Глобальный объект состояния
state = State()


def load_config():
    conf = configparser.ConfigParser()
    if not CONFIG_FILE.exists():
        conf['telegram'] = {'api_id': '', 'api_hash': '', 'channel_username': ''}
        conf['general'] = {'developer_mode': 'false'}
        conf['power'] = {'on_guid': '', 'off_guid': ''}
        save_config(conf)

    conf.read(CONFIG_FILE, encoding='utf-8')

    # Миграция/Валидация секций
    changed = False
    if 'power' not in conf:
        conf.add_section('power')
        changed = True
    if 'general' not in conf:
        conf.add_section('general')
        conf.set('general', 'developer_mode', 'false')
        changed = True

    if changed:
        save_config(conf)

    return conf


def save_config(conf):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        conf.write(f)


# Глобальный объект конфига
config = load_config()