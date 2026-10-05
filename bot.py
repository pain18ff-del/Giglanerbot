import asyncio
import os
import re
import aiohttp
import aiosqlite
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    InlineQueryResultAudio,
    InlineQueryResultArticle,
    InputTextMessageContent,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

yt_cache = {}
DB = "bot.db"
PAGE_SIZE = 10


async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_seen TIMESTAMP,
                banned INTEGER DEFAULT 0
            )
        """)
        await db.commit()


async def save_user(user):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, first_name, last_seen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_seen=excluded.last_seen
        """, (user.id, user.username, user.first_name, datetime.now()))
        await db.commit()


async def get_all_users():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT user_id FROM users WHERE banned=0") as c:
            return [row[0] for row in await c.fetchall()]


async def get_users_count():
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            return (await c.fetchone())[0]


def log_query(user, text, source=""):
    name = f"@{user.username}" if user.username else user.first_name
    with open("queries.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {user.id} | {name} | [{source}] {text}\n")


async def search_itunes(query: str):
    url = "https://itunes.apple.com/search"
    params = {"term": query, "media": "music", "limit": 10}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params) as r:
            data = await r.json()
            return data.get("results", [])


async def search_youtube(query: str, limit: int = 30):
    args = [
        "yt-dlp",
        f"ytsearch{limit}:{query}",
        "--dump-json",
        "--flat-playlist",
        "--no-warnings",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        return []

    results = []
    for line in stdout.decode("utf-8", errors="ignore").splitlines():
        try:
            import json
            data = json.loads(line)
            results.append({
                "id": data.get("id"),
                "title": data.get("title", "Unknown"),
                "url": f"https://youtu.be/{data.get('id')}",
                "duration": data.get("duration"),
            })
        except:
            continue
    return results


async def search_youtube_one(query: str):
    results = await search_youtube(query, limit=1)
    return results[0] if results else None


def format_duration(sec):
    if not sec:
        return ""
    m = sec // 60
    s = sec % 60
    return f"{m}:{s:02d}"


def clean_tmp():
    os.makedirs("/tmp/yt", exist_ok=True)
    for f in os.listdir("/tmp/yt"):
        try:
            os.remove(f"/tmp/yt/{f}")
        except:
            pass


async def download_file(url, mode, prefix_uid=""):
    os.makedirs("/tmp/yt", exist_ok=True)
    tag = f"{mode}_{prefix_uid}"
    out_tpl = f"/tmp/yt/{tag}_%(title)s.%(ext)s"

    if mode == "audio":
        args = ["yt-dlp", "-x", "--audio-format", "mp3",
                "--audio-quality", "192K", "--max-filesize", "45M",
                "-o", out_tpl, url]
    else:
        args = ["yt-dlp", "-f", "mp4", "--max-filesize", "45M",
                "-o", out_tpl, url]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        return None

    files = [
        f for f in os.listdir("/tmp/yt")
        if f.startswith(tag) and f.endswith((".mp3", ".m4a", ".mp4", ".mkv", ".webm"))
    ]
    if not files:
        return None
    files.sort(key=lambda x: os.path.getmtime(f"/tmp/yt/{x}"), reverse=True)
    return f"/tmp/yt/{files[0]}"


async def send_audio_video(message, url, uid_tag=""):
    clean_tmp()
    audio_path = await download_file(url, "audio", uid_tag)
    video_path = await download_file(url, "video", uid_tag)

    if not audio_path and not video_path:
        return False

    if audio_path:
        try:
            name = os.path.basename(audio_path)
            display = name.split("_", 2)[-1] if "_" in name else name
            await message.reply_audio(
                FSInputFile(audio_path, filename=display),
                title=display.rsplit(".", 1)[0],
                caption="@giglanerbot",
            )
        except Exception as e:
            print(f"Audio error: {e}")

    if video_path:
        try:
            name = os.path.basename(video_path)
            display = name.split("_", 2)[-1] if "_" in name else name
            await message.reply_video(
                FSInputFile(video_path, filename=display),
                caption="@giglanerbot",
            )
        except Exception as e:
            print(f"Video error: {e}")

    clean_tmp()
    return True


def build_page_kb(uid):
    data = yt_cache.get(uid)
    if not data:
        return None
    tracks = data["tracks"]
    page = data["page"]
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_tracks = tracks[start:end]

    buttons = []
    for i, t in enumerate(page_tracks):
        real_idx = start + i
        dur = format_duration(t.get("duration"))
        label = t["title"][:55]
        if dur:
            label += f"  [{dur}]"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"yt_{real_idx}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_prev"))
    if end < len(tracks):
        nav.append(InlineKeyboardButton(text="➕ Ещё", callback_data="nav_next"))
    if nav:
        buttons.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def page_text(uid):
    data = yt_cache.get(uid)
    if not data:
        return "🎵 Танланг:"
    total = len(data["tracks"])
    page = data["page"]
    start = page * PAGE_SIZE + 1
    end = min((page + 1) * PAGE_SIZE, total)
    return f"🎵 Танланг: ({start}-{end} из {total})"


@dp.message(lambda m: m.new_chat_members is not None)
async def on_group_add(message: types.Message):
    if not message.new_chat_members:
        return
    me = await bot.get_me()
    for member in message.new_chat_members:
        if member.id == me.id:
            await message.answer("Салом қанжиқчалар”")
            break


@dp.message(Command("start"))
async def on_start(message: types.Message):
    await save_user(message.from_user)
    await message.answer(
        "Саломчик! “Музыка қидирамиз)”\n\n"
        "<b>1.</b> Музыка номи\n\n"
        "<b>2.</b> Ссылка ташла (YouTube, Instagram, TikTok)\n\n"
        "<b>3.</b> Тайла тайла голосовой ташла музыкасини топибераман 🎤"
    )


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    count = await get_users_count()
    await message.answer(f"👥 Фойдаланувчилар: <b>{count}</b>")


@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace("/broadcast", "", 1).strip()
    if not text:
        await message.answer("<code>/broadcast Матнингни ёз</code>")
        return
    users = await get_all_users()
    await message.answer(f"📢 {len(users)} та фойдаланувчига юбориляпти...")
    ok = 0
    fail = 0
    for uid in users:
        try:
            await bot.send_message(uid, text)
            ok += 1
            await asyncio.sleep(0.05)
        except:
            fail += 1
    await message.answer(f"✅ Тайёр!\nЮборилди: {ok}\nХатолик: {fail}")


URL_PATTERN = re.compile(
    r"https?://(www\.)?(youtube\.com|youtu\.be|instagram\.com|tiktok\.com)/\S+"
)


@dp.message(lambda m: m.text and URL_PATTERN.search(m.text))
async def handle_link(message: types.Message):
    await save_user(message.from_user)
    url = URL_PATTERN.search(message.text).group(0)
    log_query(message.from_user, url, "link")

    msg = await message.reply("⏳ Юкланяпти...")
    ok = await send_audio_video(message, url, str(message.from_user.id))

    if not ok:
        await msg.edit_text("Қӯтоқ ҳам топилмади(😢")
    else:
        try:
            await msg.delete()
        except:
            pass


@dp.message(lambda m: m.text and m.text.lower().startswith("найти"))
async def cmd_naiti(message: types.Message):
    await save_user(message.from_user)
    query = message.text[5:].strip()

    if not query:
        await message.reply("Нима қидирамиз? Масалан: <code>найти Believer</code>")
        return

    log_query(message.from_user, query, "найти")
    msg = await message.reply("🔍 Қидиряпти...")

    track = await search_youtube_one(query)
    if not track:
        await msg.edit_text("Нихуя топилмади🗿💔(")
        return

    await msg.edit_text(f"⏳ Юкланяпти: {track['title'][:50]}...")
    ok = await send_audio_video(message, track["url"], str(message.from_user.id))

    if not ok:
        await msg.edit_text("Қӯтоқ ҳам топилмади(😢")
    else:
        try:
            await msg.delete()
        except:
            pass


@dp.callback_query(lambda c: c.data in ("nav_next", "nav_prev"))
async def on_nav(call: CallbackQuery):
    uid = call.from_user.id
    data = yt_cache.get(uid)
    if not data:
        await call.answer("Сессия истекла, напиши заново", show_alert=True)
        return
    if call.data == "nav_next":
        data["page"] += 1
    else:
        data["page"] = max(0, data["page"] - 1)
    kb = build_page_kb(uid)
    text = page_text(uid)
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except:
        pass
    await call.answer()


@dp.callback_query(lambda c: c.data.startswith("yt_"))
async def on_track_choice(call: CallbackQuery):
    uid = call.from_user.id
    idx = int(call.data.replace("yt_", ""))
    data = yt_cache.get(uid)
    if not data or idx >= len(data["tracks"]):
        await call.answer("Трек потерялся, напиши заново", show_alert=True)
        return
    track = data["tracks"][idx]
    await call.message.edit_text(f"⏳ Юкланяпти: {track['title'][:50]}...")
    ok = await send_audio_video(call.message, track["url"], str(uid))
    if not ok:
        await call.message.edit_text("Қӯтоқ ҳам топилмади(😢")
    else:
        try:
            await call.message.delete()
        except:
            pass
    yt_cache.pop(uid, None)


@dp.message(lambda m: m.text and not m.text.startswith("/") and m.chat.type == "private")
async def handle_text_search(message: types.Message):
    await save_user(message.from_user)
    text = message.text.strip()
    if len(text) < 2 or URL_PATTERN.search(text):
        return
    if text.lower().startswith("найти"):
        return

    log_query(message.from_user, text, "text")
    msg = await message.reply("🔍 Қидиряпти...")
    tracks = await search_youtube(text, limit=30)
    if not tracks:
        await msg.edit_text("Нихуя топилмади🗿💔(")
        return
    uid = message.from_user.id
    yt_cache[uid] = {"tracks": tracks, "page": 0, "query": text}
    kb = build_page_kb(uid)
    await msg.edit_text(page_text(uid), reply_markup=kb)


@dp.inline_query()
async def inline_music(query: types.InlineQuery):
    text = query.query.strip()
    if not text:
        await query.answer(
            results=[InlineQueryResultArticle(
                id="hint",
                title="Мусиқа номи нма?",
                description="Масалан: Imagine Dragons Believer",
                input_message_content=InputTextMessageContent(
                    message_text="Мусиқа номи нма?"
                ),
            )],
            cache_time=1,
        )
        return
    log_query(query.from_user, text, "inline")
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
            description="Бошқа ном билан уриниб кўр",
            input_message_content=InputTextMessageContent(
                message_text="Нихуя топилмади🗿💔("
            ),
        ))
    await query.answer(results=results[:10], cache_time=5)


async def main():
    await init_db()
    print("Бот ишлаяпти")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
