import logging
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from telethon import TelegramClient, events

from config import config, state
from resources import red_image, green_image, grey_image, trouble_image
from utils import set_power_mode

app_running = True
client = None


def format_duration(start_time):
    if not start_time or start_time == datetime.min.replace(tzinfo=timezone.utc): return "N/A"
    diff = datetime.now(timezone.utc) - start_time
    total_seconds = int(diff.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m"


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


async def telegram_main(current_tray_icon):
    global client
    api_id = config.get('telegram', 'api_id')
    api_hash = config.get('telegram', 'api_hash')
    channel = config.get('telegram', 'channel_username')

    if any(s in str(v) for s in ('YOUR_API', 'YOUR_CHANNEL') for v in (api_id, api_hash, channel)) or not api_id:
        logging.warning("API details or channel are not configured. Please open Settings.")
        update_tray_icon(current_tray_icon)
        return

    session_path = Path(__file__).parent / 'energy_control_session'
    client = TelegramClient(str(session_path), api_id, api_hash, loop=asyncio.get_event_loop())

    @client.on(events.NewMessage(chats=channel))
    async def handler(event):
        await process_status(event.message, current_tray_icon)

    try:
        logging.info("Connecting to Telegram as %s...", api_id)
        await client.start()
        logging.info("Telethon client started. Listening on channel: %s", channel)
        async for message in client.iter_messages(channel, limit=10):
            if await process_status(message, current_tray_icon):
                logging.info("Initial status found.")
                break
        else:
            logging.warning("No initial status found in the last 10 messages.")

        update_tray_icon(current_tray_icon)

        while app_running:
            await asyncio.sleep(0.2)

    except Exception as e:
        logging.error("A critical error occurred in the Telegram thread.", exc_info=e)
    finally:
        if client and client.is_connected():
            logging.info("Disconnecting client...")
            await client.disconnect()
        logging.info("Telegram thread finished.")


def stop_bot():
    global app_running
    app_running = False