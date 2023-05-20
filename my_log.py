from aiogram.types import Message
import asyncio
import os
import datetime


async def log(message: Message, reply_from_bot: str = '') -> None:
    log_file_path = os.path.join(os.getcwd(), 'log.txt')
    async with asyncio.Lock():
        with open(log_file_path, 'a') as log_file:
            time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
            #log_file.write(f"[{time_now}] [{message.chat.type}] chat [{message.chat.id}], [{message.chat.username}]: {message.text}\n")
            
            
#            log_file.write(f"[{time_now}] [{message.chat.type}] {('user' if message.chat.type == 'private' else 'chat')} \
#[{message.chat.id}], [{message.chat.username or message.chat.first_name or message.chat.title or ''}]: {message.text or message.caption}\n")

            log_file.write(f"[{time_now}] [{message.chat.type}] [{('user' if message.chat.type == 'private' else 'chat')} \
{message.chat.username or message.chat.first_name or message.chat.title or ''}] [{message.from_user.first_name or message.from_user.username or ''}]: \
{message.text or message.caption}\n")


            if reply_from_bot:
                log_file.write(f"[{time_now}] Bot replied: {reply_from_bot}\n")
            log_file.write('\n\n')
