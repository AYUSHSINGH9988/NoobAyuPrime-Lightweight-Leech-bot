import os
import time
import asyncio
import aiohttp
import yt_dlp
import aria2p
import subprocess
import shutil
import re
import urllib.parse
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# ==================== CONFIGURATION ====================
API_ID = int(os.environ.get("API_ID", 33675350))
API_HASH = os.environ.get("API_HASH", "2f97c845b067a750c9f36fec497acf97")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8787057992:AAGVOgykB3Lj13dBT0gy15TammjtI633S7A")
RCLONE_PATH = os.environ.get("RCLONE_PATH", "remote:")

# --- Dump Channel Logic ---
DUMP_CHANNEL = -1004455954813
try:
    d = str(os.environ.get("DUMP_CHANNEL", "0")).strip()
    if d != "0":
        if d.startswith("-100"): DUMP_CHANNEL = int(d)
        elif d.startswith("-"): DUMP_CHANNEL = int(f"-100{d[1:]}")
        else: DUMP_CHANNEL = int(f"-100{d}")
except: DUMP_CHANNEL = 0

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Globals ---
aria2 = None
user_queues = {}   
is_processing = {} 
progress_status = {}

def humanbytes(size):
    if not size: return "0B"
    dic = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    n = 0
    while size > 1024: size /= 1024; n += 1
    return f"{round(size, 2)} {dic[n]}B"

def time_formatter(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def clean_filename(name):
    name = urllib.parse.unquote_plus(name)
    return name.replace("<", "").replace(">", "").replace(":", "")

async def progress_bar(current, total, message, start, action, name):
    now = time.time()
    last = progress_status.get(message.id, 0)
    if (now - last < 3) and (current != total): return
    progress_status[message.id] = now
    pct = current * 100 / total if total else 0
    speed = current / (now - start) if now > start else 0
    eta = round((total - current) / speed) if speed > 0 else 0
    filled = int(pct // 10)
    bar = '☁️' * filled + '◌' * (10 - filled)
    text = f"""☁️ <b>Powered by Ayuprime</b>

📂 <b>File:</b> {clean_filename(name)}
<b>{action}</b>

{bar} <code>{round(pct, 1)}%</code>

💾 <b>Size:</b> <code>{humanbytes(current)} / {humanbytes(total)}</code>
🚀 <b>Speed:</b> <code>{humanbytes(speed)}/s</code>
⏳ <b>ETA:</b> <code>{time_formatter(eta)}</code>"""
    try: await message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✖️ Cancel", callback_data=f"cancel_{message.id}")]]))
    except: pass

# BUG FIX 1: await proc.wait() added
async def take_ss(video):
    thumb = f"{video}.jpg"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-ss", "00:00:01", "-i", video,
            "-vframes", "1", "-q:v", "2", thumb, "-y"
        )
        await proc.wait()
        if os.path.exists(thumb): return thumb
    except: pass
    return None

async def rclone_upload(message, path):
    name = clean_filename(os.path.basename(path))
    if not os.path.exists("rclone.conf"):
        return await message.edit_text("❌ <b>Error:</b> <code>rclone.conf</code> not found!")
    await message.edit_text(f"🚀 <b>Rclone Upload Started...</b>\nTarget: <code>{RCLONE_PATH}</code>")
    cmd = ["rclone", "copy", path, RCLONE_PATH, "--config", "rclone.conf", "-P"]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    last_edit = 0
    while True:
        line = await proc.stdout.readline()
        if not line: break
        decoded = line.decode().strip()
        if "Transferred" in decoded and "%" in decoded:
            now = time.time()
            if now - last_edit > 4:
                match = re.search(r"(\d+)%", decoded)
                pct = match.group(1) if match else "0"
                filled = int(int(pct) // 10)
                bar = '☁️' * filled + '◌' * (10 - filled)
                text = f"""🚀 <b>Rclone Uploading...</b>
📂 <b>File:</b> {name}

{bar} <code>{pct}%</code>
⚡ <b>Status:</b> {decoded.split(',')[1].strip() if ',' in decoded else 'Uploading'}"""
                try:
                    await message.edit_text(text)
                    last_edit = now
                except: pass
    await proc.wait()
    if proc.returncode == 0:
        await message.edit_text(f"✅ <b>Uploaded to Cloud!</b>\n📂 {name}")
    else:
        err = await proc.stderr.read()
        await message.edit_text(f"❌ <b>Rclone Failed!</b>\n<code>{err.decode()[:300]}</code>")

async def telegram_upload(client, message, path):
    name = clean_filename(os.path.basename(path))
    thumb = await take_ss(path)
    # BUG FIX 2: </code> tag added
    caption = f"☁️ <b>File:</b> {name}\n📦 <b>Size:</b> <code>{humanbytes(os.path.getsize(path))}</code>"
    if DUMP_CHANNEL != 0:
        try:
            sent = await client.send_document(
                chat_id=DUMP_CHANNEL, document=path, thumb=thumb, caption=caption,
                progress=progress_bar, progress_args=(message, time.time(), "☁️ Uploading to Dump...", name)
            )
            link = f"https://t.me/c/{str(DUMP_CHANNEL)[4:]}/{sent.id}"
            await message.edit_text(f"✅ <b>Done!</b>\n<a href='{link}'>View in Channel</a>", disable_web_page_preview=True)
            if thumb: os.remove(thumb)
            return
        except Exception as e:
            await message.edit_text(f"❌ <b>Dump Upload Failed!</b>\nError: <code>{e}</code>\n\n<i>Falling back to Private Chat...</i>")
            await asyncio.sleep(2)
    try:
        await client.send_document(
            chat_id=message.chat.id, document=path, thumb=thumb, caption=caption,
            progress=progress_bar, progress_args=(message, time.time(), "☁️ Uploading...", name)
        )
        await message.delete()
    except Exception as e:
        await message.edit_text(f"❌ <b>Upload Failed!</b>\n<code>{e}</code>")
    if thumb and os.path.exists(thumb): os.remove(thumb)

async def process_task(client, message, link, mode, target):
    try:
        msg = await message.reply_text(f"⏳ <b>Initializing...</b>")
        path = None
        if "pixeldrain.com" in link and "/u/" in link:
            link = link.replace("/u/", "/api/file/")
        if "magnet" in link or link.endswith(".torrent"):
            if not aria2: return await msg.edit_text("❌ Aria2 Daemon Not Running!")
            try:
                if "magnet" in link: 
                    download = aria2.add_magnet(link)
                else:
                    async with aiohttp.ClientSession() as s:
                        async with s.get(link) as r:
                            with open("task.torrent", "wb") as f: f.write(await r.read())
                    download = aria2.add_torrent("task.torrent")
            except Exception as e:
                return await msg.edit_text(f"❌ Aria2 Error: {e}")
            gid = download.gid
            while True:
                try:
                    curr_dl = aria2.get_download(gid)
                    if curr_dl.status == "complete":
                        path = curr_dl.files[0].path
                        break
                    elif curr_dl.status == "error":
                        return await msg.edit_text("❌ Torrent Error")
                    elif curr_dl.status == "removed":
                        return await msg.edit_text("❌ Task Cancelled")
                    await progress_bar(
                        int(curr_dl.completed_length), int(curr_dl.total_length),
                        msg, time.time(), "⬇️ Downloading Torrent...", curr_dl.name
                    )
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"Monitor Error: {e}")
                    await asyncio.sleep(2)
        else:
            opts = {'outtmpl': '%(title)s.%(ext)s', 'quiet': True}
            try:
                with yt_dlp.YoutubeDL(opts) as y:
                    info = y.extract_info(link, download=True)
                    path = y.prepare_filename(info)
            except Exception as e:
                return await msg.edit_text(f"❌ Download Error: {e}")
        if path:
            new_name = clean_filename(os.path.basename(path))
            new_path = os.path.join(os.path.dirname(path), new_name)
            os.rename(path, new_path)
            path = new_path
            if target == "rclone": await rclone_upload(msg, path)
            else: await telegram_upload(client, msg, path)
            if os.path.exists(path): os.remove(path)
    except Exception as e:
        await message.reply_text(f"❌ Critical Error: {e}")

async def queue_manager(client, user_id):
    is_processing[user_id] = True
    while user_id in user_queues and user_queues[user_id]:
        task = user_queues[user_id].pop(0)
        link, mode, target, m = task
        await process_task(client, m, link, mode, target)
    del is_processing[user_id]
    await client.send_message(user_id, "✅ <b>All Queue Tasks Finished!</b>")

@app.on_message(filters.command("start"))
async def start(c, m):
    await m.reply_text(f"👋 <b>Bot Ready!</b>\nDump ID: <code>{DUMP_CHANNEL}</code>")

@app.on_message(filters.command(["leech", "rclone", "queue", "queue_rc"]))
async def add_task(c, m):
    if len(m.command) < 2: return await m.reply_text("❌ Give me a link!")
    link = m.command[1]
    cmd = m.command[0]
    target = "rclone" if "rclone" in cmd or "rc" in cmd else "telegram"
    if "queue" in cmd:
        if m.from_user.id not in user_queues: user_queues[m.from_user.id] = []
        user_queues[m.from_user.id].append((link, "auto", target, m))
        await m.reply_text(f"✅ Added to Queue ({len(user_queues[m.from_user.id])})")
        if not is_processing.get(m.from_user.id):
            asyncio.create_task(queue_manager(c, m.from_user.id))
    else:
        asyncio.create_task(process_task(c, m, link, "auto", target))

@app.on_callback_query(filters.regex(r"cancel_"))
async def cancel(c, cb):
    await cb.message.delete()

async def main():
    global aria2
    print("🤖 Bot Starting...")
    if shutil.which("aria2c"):
        try:
            print("🚀 Starting Aria2c Daemon...")
            subprocess.Popen(["aria2c", "--enable-rpc", "--rpc-listen-port=6800", "--daemon", "--allow-overwrite=true"])
            await asyncio.sleep(3)
            aria2 = aria2p.API(aria2p.Client(host="http://localhost", port=6800, secret=""))
            print("✅ Aria2 Connected Successfully!")
        except Exception as e:
            print(f"❌ Aria2 Connection Failed: {e}")
    else:
        print("❌ Aria2c Binary Not Found!")
    await app.start()
    runner = web.AppRunner(web.Application())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await asyncio.Event().wait()

# BUG FIX 3: asyncio.run() use kiya
if __name__ == "__main__":
    asyncio.run(main())
