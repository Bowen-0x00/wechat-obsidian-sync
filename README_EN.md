# WeChat to Obsidian Sync (Private & AI-Powered)

[English Documentation](README_EN.md) | [中文文档](README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Obsidian: Plugin](https://img.shields.io/badge/Obsidian-Plugin-purple.svg)](https://obsidian.md/)
[![LLM: AI_Summary](https://img.shields.io/badge/LLM-AI--Powered-green.svg)](https://platform.openai.com/)

**WeChat Obsidian Sync** is a 100% self-hosted, private, secure, and free note synchronization system connecting WeChat to Obsidian.
Say goodbye to costly commercial subscription fees and privacy exposure risks! You can send quick thought memos, forward articles or web links, and share images directly from your **personal WeChat** mobile app. The cloud server automatically leverages Large Language Models (LLMs) to generate **100-word TLDR summaries and auto-tags**, seamlessly appending everything to your local **Obsidian Vault**.

> 📖 **Step-by-Step SOP Guide**: See [WeChat Customer Service & Obsidian SOP Guide (docs/SOP_WECHAT_KF_SETUP.md)](docs/SOP_WECHAT_KF_SETUP.md) for detailed walk-throughs on enabling WeChat Customer Service, direct article forwarding with official badges, port 8088 Nginx reverse proxying, and native Obsidian plugin setup.

---

## ✨ Key Features

- 💬 **Direct One-Click Forwarding in Personal WeChat**:
  - Powered by Enterprise WeChat's official "WeChat Customer Service" or "Self-Built App" dual engine.
  - Sits permanently in your primary WeChat chat list with an official enterprise badge. Forward any article directly via "Send to friend" without complex copying.
- 🧠 **LLM-Powered Content Enrichment**:
  - **Articles & Web Links**: Automatically scrapes full web page / WeChat official account content, strips noise, and queries LLMs (DeepSeek, OpenAI, Claude, etc.) to produce a **100-word TLDR summary**, key takeaways, and relevant Obsidian `#tags` (e.g., `#ComputerArchitecture`, `#LLM`, `#Chiplet`).
  - **Quick Thoughts**: Automatically classifies memos and appends 1~2 relevant tags (e.g., `#ideas`, `#todo`).
- 📝 **Safe Local Obsidian Writing**:
  - Matches standard Obsidian vault conventions: supports **Daily Notes** (e.g., `Daily/YYYY-MM-DD/WeChat_YYYY-MM-DD.md`) or a single **Inbox file** (e.g., `Inbox.md`).
  - Built-in `FileLock` mutex ensures zero race conditions or file corruption during concurrent operations.
  - Image media is automatically downloaded and saved to your local attachments directory (e.g., `attachments/`), generating standard Obsidian wikilinks `![[...|thumbnail]]`.
- 🔌 **Dual Sync Clients**:
  - **Native Obsidian Plugin**: Installs directly in Obsidian with a left-ribbon sync button, command palette shortcuts, automated background polling timer, and settings tab.
  - **Standalone Python Daemon**: Syncs notes silently in the background on your PC without requiring the Obsidian client to be open.

---

## 🏗️ Architecture

```
[ Personal WeChat Mobile App ]  (Thoughts / Forwarded Articles / Photos)
       │
       ▼ (Encrypted XML Webhook)
[ Cloud Server (Linux / VPS) ] (24/7 Background Daemon)
  ├── 1. WeCom XML Decryption (Token + EncodingAESKey)
  ├── 2. Web Article Crawler (WeChat / Zhihu / General Web pages)
  ├── 3. LLM Enrichment (100-word TLDR + Auto-Tagging)
  ├── 4. Instant Confirmation Reply ("✅ Synced to Obsidian")
  └── 5. SQLite Pending Queue (inbox.db)
       ▲
       │  HTTP REST API (Token Authentication)
       │
[ Local Obsidian Vault (PC / Mac) ]
  ├── Option A: Native Obsidian Plugin (Ribbon Sync / Auto Interval)
  └── Option B: Standalone Python Daemon (Thread-Safe File Append)
       │
       ├── Appends to: Daily/YYYY-MM-DD/Sync_YYYY-MM-DD.md
       └── Downloads images to: attachments/
```

---

## 🚀 Getting Started

### Part 1: Server Deployment (Cloud Server / VPS)

#### 1. Clone & Configure
```bash
git clone https://github.com/Bowen-0x00/wechat-obsidian-sync.git
cd wechat-obsidian-sync

cp config.example.yaml config.yaml
```

Edit `config.yaml` with your credentials:
```yaml
wechat:
  corp_id: "YOUR_CORP_ID"
  agent_id: 1000003
  secret: "YOUR_SECRET"
  token: "YOUR_TOKEN"
  encoding_aes_key: "YOUR_ENCODING_AES_KEY"
  open_kfid: "YOUR_OPEN_KFID"             # If using WeChat Customer Service

llm:
  enable: true
  base_url: "https://api.deepseek.com/v1"
  api_key: "YOUR_LLM_API_KEY"
  model: "deepseek-chat"

sync:
  api_secret: "YOUR_CUSTOM_SYNC_SECRET"
  port: 8088
```

#### 2. Install & Start
```bash
pip install -r requirements.txt

# Run the server
python -m server.server
```

*(Optional: Use the provided `deploy/wechat_obsidian.service` for systemd daemon management).*

#### 3. Set Callback URL in Enterprise WeChat
In your Enterprise WeChat admin console, configure the callback:
- **URL**: `http://your-server-domain.com/wechat` (reverse proxied via Nginx/OpenResty to port 8088).
- **Token** and **EncodingAESKey** must match your `config.yaml`.

---

### Part 2: Local Obsidian Vault Setup

#### Option A: Native Obsidian Plugin (Recommended)
1. Copy the `obsidian_plugin/` folder into your Obsidian vault:
   `.obsidian/plugins/wechat-obsidian/`
2. Open Obsidian, go to **Settings $\rightarrow$ Community Plugins**, and enable **WeChat Obsidian Helper**.
3. In the plugin settings tab:
   - **Server URL**: Your cloud server URL (e.g., `http://your-server-domain.com`).
   - **API Secret**: The `api_secret` defined in `config.yaml`.
   - **Archive Mode**: `daily` or `inbox`.
4. Click the chat icon on the left ribbon (or run `Ctrl+P` $\rightarrow$ "Sync Now") to fetch notes!

#### Option B: Standalone Local Python Script
Sync notes directly without launching Obsidian:
```bash
cd local
python sync.py --once       # Sync once
python sync.py --interval 60 # Poll every 60 seconds
```

---

## 📂 Repository Structure

```
wechat-obsidian-sync/
├── config.example.yaml          # Unified configuration template
├── requirements.txt             # Python dependencies
├── server/                      # Cloud webhook and processing server
│   ├── server.py                # Server entrypoint and sync API
│   ├── wxcrypt.py               # WeCom encryption & decryption
│   ├── parser.py                # XML message parser
│   ├── crawler.py               # Webpage and article scraper
│   ├── llm_enhancer.py          # LLM TLDR and tag generator
│   ├── storage.py               # SQLite inbox storage
│   └── wechat_client.py         # WeCom & Customer Service client
├── obsidian_plugin/             # Native Obsidian community plugin
│   ├── manifest.json            # Plugin manifest
│   ├── main.js                  # Plugin source
│   └── styles.css               # Styling
├── local/                       # Local Python sync client
│   ├── writer.py                # Thread-safe file writer & image downloader
│   └── sync.py                  # Local polling daemon
├── deploy/
│   └── wechat_obsidian.service  # Linux Systemd unit file
└── LICENSE                      # MIT License
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
