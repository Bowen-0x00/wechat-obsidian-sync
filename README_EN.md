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
  - **Articles & Web Links**: Scrapes and cleans article text, then calls the model directly through the local Antigravity gateway for TLDR summaries, key points, and Obsidian tags.
  - **Quick Thoughts**: Automatically classifies memos and appends 1~2 relevant tags (e.g., `#ideas`, `#todo`).
- 📝 **Safe Local Obsidian Writing**:
  - Matches standard Obsidian vault conventions: supports **Daily Notes** (e.g., `Daily/YYYY-MM-DD/WeChat_YYYY-MM-DD.md`) or a single **Inbox file** (e.g., `Inbox.md`).
  - Built-in `FileLock` mutex ensures zero race conditions or file corruption during concurrent operations.
  - Image media is automatically downloaded and saved to your local attachments directory (e.g., `attachments/`), generating standard Obsidian wikilinks `![[...|thumbnail]]`.
- 🔌 **Dual Sync Clients**:
  - **Native Obsidian Plugin**: Installs directly in Obsidian with a left-ribbon sync button, command palette shortcuts, automated background polling timer, and settings tab.
  - **Standalone Python Daemon**: Syncs notes silently in the background on your PC without requiring the Obsidian client to be open.
- 🚀 **System-Wide Native Share Sheet Support (Direct to Cloud, No WeChat Middleman)**:
  - Provides an open `POST /api/clip` endpoint.
  - Share directly from Zhihu, Bilibili, Chrome, or any mobile browser via system share sheet (HTTP Shortcuts / iOS Shortcuts) $\rightarrow$ "Clip to Obsidian" without WeChat's SDK restrictions.
  - Automatically scrapes full Zhihu Q&A / articles; live `/cookie <Cookie>` hot-update supported.

### 💬 Interactive Commands (Send directly in WeChat)

| Command | Alias | Description | Example |
| :--- | :--- | :--- | :--- |
| **`/status`** | `状态` | **Real-time live probe** of LLM connectivity & Zhihu Cookie health | `/status` |
| **`/llm model`** | `模型` | View active LLM model and recommended candidates | `/llm model` |
| **`/llm model <Name>`**| - | **Hot-switch active model** with pre-flight connection test | `/llm model gemini-3.8-flash` |
| **`/llm <question>`** | - | Multi-turn conversational follow-up on the latest note | `/llm What is the key innovation?` |
| **`/cookie <Cookie>`** | - | **Hot-update Zhihu cookie** directly from WeChat chat | `/cookie _xsrf=...` |
| **`/help`** | `帮助` | Display interactive command manual | `/help` |

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
  base_url: "http://127.0.0.1:18890/v1"
  api_key: ""                            # Local bearer key comes from LLM_GATEWAY_KEY
  model: "default"                       # Follow the web setting; the initial gateway default is gemini-3.8-flash

sync:
  api_secret: "YOUR_CUSTOM_SYNC_SECRET"
  port: 8088
```

#### Switchable upstreams and research agents

All four services share `llm_gateway/`; direct inference versus research-agent routing stays unchanged when switching upstreams. Production currently uses the previous OpenAI-compatible API. Antigravity OAuth support and private credentials remain available for a later switch:

- `/v1/chat/completions`: direct inference for notes, vision, social radar, ordinary email, and their follow-ups.
- `/agent/v1/chat/completions`: `thinkingLevel: high` for insight generation/follow-ups and paper evaluation/follow-ups.
- Data access is limited to `search_history`, `read_history`, and `read_chat_history`. Fixed SQLite databases are opened read-only, with bounded result sizes, tool calls, and execution deadlines. No shell, arbitrary SQL, or write tools. Structured analyses finish through the non-persisting `submit_analysis` tool, avoiding invalid JSON in long answers. Follow-ups use the latest history messages in chronological order.
- OpenAI-compatible research-agent tool turns use `stream: false` to obtain complete function names, IDs, and arguments before executing the same agent protocol. Broken streamed calls are never guessed, merged, or renamed. High reasoning and read-only tools remain enabled; native Antigravity transport is unchanged. Provider errors, cancellation, and truncation take precedence over missing-submission errors and identify the resolved model/upstream.
- Default: `gemini-3.8-flash`. Model choices come from the active upstream roster; neither backend nor model is switched automatically. Google authorization, discovery, and inference availability must be verified separately.

Direct inference has a 45-second total deadline; research agents have 240 seconds. Changing the API does not remove these limits. A gateway-owned deadline returns HTTP `504` / `gateway_timeout` with the resolved model and upstream host, separately from client cancellation and upstream failures. `default` is a selector for the web-configured global model, not a model ID. A single timeout does not prove an invalid key, an unsaved configuration, or a switch back to Google; it does not trigger automatic retries or backend changes.

Use **Model settings** in the upper-right navigation (the sliders icon on phones) to edit the shared backend, API Base URL, API Key, and default model without SSH.

1. Select an OpenAI-compatible API or the Antigravity account already imported on the server.
2. Enter a public HTTPS base URL, usually ending in `/v1`. A blank key retains the stored credential. Changing endpoints requires a new key; existing keys are never returned to the browser or forwarded to the new endpoint.
3. **Load models** retrieves the provider roster. **Test connection** sends a short model request without changing configuration. OpenAI-compatible research providers must correctly support non-streaming tool calls; ordinary direct inference keeps its existing transport.
4. **Save and apply** preflights the model, atomically persists `data/llm-upstream.env` with mode `0600`, then hot-swaps the runtime snapshot. Failures leave the active configuration untouched; stale concurrent edits require a reload. In-flight requests retain their previous snapshot.

If the upstream is unavailable or its key expires at startup, management remains available while inference explicitly reports unavailable. Correct the configuration in this panel to recover without first editing files over SSH.

Business configuration `llm.model: default` follows the shared setting; all four deployed services use this alias. An explicit `/llm model <ID>` command overrides it for that application; `/llm model default` restores following. Direct-inference versus high research-agent routing is unchanged.

The existing dashboard Bearer authentication protects `GET /api/dashboard/model-settings` and `POST /api/dashboard/model-settings/models`, `/test`, `/save`. Reads expose only `api_key_configured`; candidate writes use `revision`, `backend`, `base_url`, `default_model`, and an optional new `api_key`. Query-string authentication is not accepted for these endpoints. Use HTTPS for public dashboard access.


Only the gateway reads `data/llm-upstream.env` (mode `0600`); the Python business services never receive the upstream key:

```dotenv
LLM_BACKEND=openai-compatible
LLM_UPSTREAM_BASE_URL=https://code28.ccwu.cc/v1
LLM_UPSTREAM_API_KEY=<previous API key, stored only in the private server file>
LLM_DEFAULT_MODEL=gemini-3.8-flash
```

This mode does not load Google credentials or query Google's model roster, and bypasses the dedicated Google proxy by default. Set `LLM_UPSTREAM_PROXY` only if the upstream API itself requires a proxy. Prefer switching back to Antigravity in the web settings: save preflights native inference and retains the unused API URL/key. Manual changes to the environment file require `systemctl restart wehub_llm`; web saves do not.

Install Bun ≥1.4.4 at `/opt/wehub-llm/bin/bun` for the systemd template. The following retained Antigravity initialization steps require a Google-capable egress proxy only for that mode (currently a dedicated loopback listener at `127.0.0.1:18891`):

```bash
export PATH=/opt/wehub-llm/bin:$PATH
mkdir -p /root/wechat_obsidian/data
cd /root/wechat_obsidian/llm_gateway
bun install --frozen-lockfile
export PI_PROXY=http://127.0.0.1:18891 HTTPS_PROXY=http://127.0.0.1:18891 HTTP_PROXY=http://127.0.0.1:18891
export LLM_AUTH_DB=/root/wechat_obsidian/data/llm-auth.db
bun import-account.ts < /secure/antigravity_accounts.json
umask 077
printf 'LLM_GATEWAY_KEY=%s\n' "$(openssl rand -hex 32)" > ../data/llm-gateway.env
cp ../deploy/wehub_llm.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wehub_llm
```

Import the account through stdin only. Keep the OAuth database and gateway environment file in ignored `data/` with mode `0600`; a refresh token is not a business-service API key. Each systemd unit loads the same `LLM_GATEWAY_KEY` via `EnvironmentFile`; foreground Python processes need that variable too. This is a loopback-only, single-owner service, not a public or multi-tenant API.


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
