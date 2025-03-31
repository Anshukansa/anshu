import logging
from telegram import Bot
from telegram.error import TelegramError
import asyncio
from config import TELEGRAM_TOKEN

bot = Bot(token=TELEGRAM_TOKEN)

async def send_message(message, chat_id):
    """
    Send a message to a chat and return the message object.
    
    Args:
        message (str): Message text to send
        chat_id (int): Telegram chat ID
        
    Returns:
        telegram.Message or None: The sent message object if successful, None otherwise
    """
    for attempt in range(3):  # Retry up to 3 times
        try:
            sent_msg = await bot.send_message(chat_id=chat_id, text=message)
            logging.info(f"Message sent to {chat_id}: {message[:50]}...")
            return sent_msg  # Return the message object
        except TelegramError as e:
            logging.error(f"Failed to send message to {chat_id}: {e}")
            if attempt < 2:
                await asyncio.sleep(2 ** (attempt + 1))  # Exponential backoff
            else:
                logging.error(f"Failed after 3 attempts: {chat_id}")
    return None  # Return None if all attempts failed

async def send_messages_sequentially(messages):
    """Send messages sequentially to avoid overloading Telegram."""
    for message, chat_id in messages:
        for attempt in range(3):  # Retry up to 3 times
            try:
                await bot.send_message(chat_id=chat_id, text=message)
                logging.info(f"Message sent to {chat_id}: {message[:50]}...")
                break
            except TelegramError as e:
                logging.error(f"Failed to send message to {chat_id}: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** (attempt + 1))  # Exponential backoff
                else:
                    logging.error(f"Failed after 3 attempts: {chat_id}")

async def edit_message(chat_id, message_id, new_text):
    """
    Edit a previously sent message with new text.
    
    Args:
        chat_id (int): Telegram chat ID
        message_id (int): ID of the message to edit
        new_text (str): New text for the message
        
    Returns:
        bool: True if the edit was successful, False otherwise
    """
    for attempt in range(3):  # Retry up to 3 times
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=new_text)
            logging.info(f"Message edited for chat_id={chat_id}, message_id={message_id}")
            return True
        except TelegramError as e:
            logging.error(f"Failed to edit message for chat_id={chat_id}, message_id={message_id}: {e}")
            if attempt < 2:
                await asyncio.sleep(2 ** (attempt + 1))  # Exponential backoff
            else:
                logging.error(f"Failed after 3 attempts: chat_id={chat_id}, message_id={message_id}")
    return False
