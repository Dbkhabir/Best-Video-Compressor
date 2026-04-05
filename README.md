# 🎬 Video Compressor Bot

A powerful Telegram bot that compresses videos using FFmpeg with MTProto support for large files (2GB+). Built with Pyrogram.

🤖 **Bot:** [@BestVideoCompressorBot](https://t.me/BestVideoCompressorBot)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🎞 **Video Compression** | Compress MP4, MKV, AVI, MOV, WebM and more |
| 🎛 **Quality Presets** | 🟢 Low (fast) · 🟡 Medium (balanced) · 🔴 High (best) |
| 📐 **Resolution Options** | 1080p · 720p · 480p · 360p · Original |
| 📦 **Large File Support** | Up to 2GB+ via Pyrogram MTProto |
| 📊 **Live Progress** | Real-time download, compression & upload progress bars |
| ⚡ **Smart Queue** | Per-user task queue (3 max), unlimited for admins |
| 👤 **User Profiles** | Track compression stats & history |
| ⚙️ **Admin Panel** | Full inline settings panel via `/settings` |
| 📢 **Force Subscribe** | Optional channel subscription requirement |
| 📋 **Log Channel** | Sends original videos to log channel after compression |
| 📅 **Daily Limits** | Configurable per-day compression limits |
| 📣 **Broadcast** | Send messages to all users |
| 🚫 **Ban System** | Ban/unban users from using the bot |
| 🧹 **Auto Cleanup** | Hourly temp file cleanup |

---

## 🚀 Deployment (Railway)

### 1️⃣ Fork or upload this repository to GitHub

### 2️⃣ Create a new project on [Railway](https://railway.app)
Connect your GitHub repo, or deploy from the Dockerfile.

### 3️⃣ Set Environment Variables

| Variable | Required | Description |
|----------|:--------:|-------------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token from [@BotFather](https://t.me/BotFather) |
| `API_ID` | ✅ | Telegram API ID from [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | ✅ | Telegram API Hash from [my.telegram.org](https://my.telegram.org) |
| `ADMIN_IDS` | ✅ | Comma-separated admin Telegram user IDs |
| `BOT_USERNAME` | ⬜ | Bot username (default: `BestVideoCompressorBot`) |
| `BOT_VERSION` | ⬜ | Version string (default: `1.0.0`) |
| `MAX_QUEUE_PER_USER` | ⬜ | Max queued tasks per user (default: `3`) |
| `COOLDOWN_SECONDS` | ⬜ | Seconds between tasks (default: `5`) |

### 4️⃣ Deploy
Railway will automatically detect the `Dockerfile` and build the project. That's it! 🎉

---

## 📁 Project Structure

```
📦 video-compressor-bot
├── 🚀 main.py               → Entry point, signal handling, cleanup worker
├── ⚙️ config.py              → Environment variables & bot configuration
├── 🗄️ database.py            → SQLite database (users, history, settings)
├── 📂 handlers/
│   ├── 👤 user_handlers.py   → /start, /help, /info, /profile, /history
│   ├── 🔐 admin_handlers.py  → /settings, /stats, /ban, /unban, /broadcast
│   └── 🎬 video_handler.py   → Video processing, queue, compression pipeline
├── 📂 utils/
│   ├── 🔧 helpers.py         → Utilities, progress bar, throttled editor
│   └── 🎥 compressor.py      → FFmpeg compression, thumbnail extraction
├── 🐳 Dockerfile             → Docker build for Railway
├── 📄 Procfile               → Railway process definition
├── 📋 requirements.txt       → Python dependencies
└── 📄 nixpacks.toml          → Nixpacks config (FFmpeg)
```

---

## 🤖 Bot Commands

### 👤 User Commands

| Command | Description |
|---------|-------------|
| `/start` | 🏠 Main menu |
| `/help` | 📚 How to use the bot |
| `/info` | 🖥 Bot & server info |
| `/profile` | 👤 Your compression stats |
| `/history` | 🗂 Past compressions |
| `/cancel` | 🛑 Stop current task |

### 🔐 Admin Commands

| Command | Description |
|---------|-------------|
| `/settings` | ⚙️ Admin settings panel (inline buttons) |
| `/stats` | 📊 Full dashboard with stats |
| `/ban <user_id>` | 🚫 Ban a user |
| `/unban <user_id>` | ✅ Unban a user |
| `/userinfo <user_id>` | 👤 View user details |
| `/broadcast <message>` | 📢 Send message to all users |

---

## 🎯 How It Works

```
📤 User sends video
    ↓
🎛 Select quality (Low / Medium / High)
    ↓
📐 Select resolution (1080p / 720p / 480p / 360p / Original)
    ↓
📥 Bot downloads video via MTProto
    ↓
⚙️ FFmpeg compresses the video
    ↓
📤 Bot uploads compressed video
    ↓
✅ Done! Original video sent to log channel
```

---

## 🛠 Tech Stack

| Technology | Purpose |
|-----------|---------|
| 🐍 **Python 3.11** | Core language |
| 📡 **Pyrogram 2.0** | MTProto Telegram client |
| 🎥 **FFmpeg** | Video compression engine |
| 🗄️ **SQLite (WAL)** | Local database |
| 💻 **psutil** | System monitoring |
| 🐳 **Docker** | Containerized deployment |

---

## 📝 License

This project is for personal use.

---

> 🎬 **Video Compressor Bot** — Compress. Save. Share. ⚡
