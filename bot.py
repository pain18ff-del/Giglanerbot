import asyncio
import os
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    InlineQueryResultAudio,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


async def search_itunes(query: str):
    url = "https://itunes.apple.com/search"
    params = {"term": query, "media": "music", "limit": 10}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params) as r:
            data = await r.json()
            return data.get("results", [])


def log_query(user, text):
    name = f"@{user.username}" if user.username else user.first_name
    with open("queries.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {user.id} | {name} | {text}\n")


@dp.message()
async def on_message(message: types.Message):
    await message.answer(
        "Саломчик! “Музыка қидирамиз)”\n\n"
        "Любой чатда ёз😎\n"
        "<code>@giglanerbot Imagine Dragons Believer</code>"
    )


@dp.inline_query()
async def inline_music(query: types.InlineQuery):
    text = query.query.strip()

    if not text:
        await query.answer(
            results=[InlineQueryResultArticle(
                id="hint",
                title="Музыка номи нма?",
                description="Масалан: Imagine Dragons Believer",
                input_message_content=InputTextMessageContent(
                    message_text="Музыка номи нма?"
                ),
            )],
            cache_time=1,
        )
        return

    log_query(query.from_user, text)
    tracks = await search_itunes(text)
    results = []

    for t in tracks:
        preview = t.get("previewUrl")
        if not preview:
            continue
        results.append(InlineQueryResultAudio(
            id=str(t.get("trackId")),
            audio_url=preview,
            title=f'{t.get("trackName")} — {t.get("artistName")}',
            performer=t.get("artistName", ""),
            audio_duration=t.get("trackTimeMillis", 0) // 1000,
        ))

    if not results:
        results.append(InlineQueryResultArticle(
            id="nf",
            title="Нихуя топилмади🗿💔(",
            description="Бошка ном билан уриниб кўр",
            input_message_content=InputTextMessageContent(
                message_text="Нихуя топилмади🗿💔("
            ),
        ))

    await query.answer(results=results[:10], cache_time=5)


async def main():
    print("Бот ишлаяпти")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
