# WeChat to Obsidian 智能笔记同步助手 (WeChat Obsidian Sync)

[中文文档](README.md) | [English Documentation](README_EN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Obsidian: Plugin](https://img.shields.io/badge/Obsidian-Plugin-purple.svg)](https://obsidian.md/)
[![LLM: AI_Summary](https://img.shields.io/badge/LLM-AI--Powered-green.svg)](https://platform.openai.com/)

**WeChat Obsidian Sync** 是一个 100% 私有化部署、安全且完全免费的微信至 Obsidian 智能笔记同步系统。
告别商业同步插件高昂的年费与隐私泄露隐患！你可以直接在**个人手机微信**中给专属助手发送文字闪念、转发公众号文章长链接或发送图片，云端自动利用大模型（LLM）提取 **100 字核心速读（TLDR）并自动打上 Obsidian 标签**，全自动无缝追加同步到你本地的 **Obsidian 知识库** 中。

> 📖 **全流程开通与避坑指南**：详见 [微信客服与 Obsidian 随手记全流程 SOP (docs/SOP_WECHAT_KF_SETUP.md)](docs/SOP_WECHAT_KF_SETUP.md)，涵盖如何利用微信客服实现公众号文章一键转发、橙色认证标常驻微信主聊天、OpenResty 8088 端口反代与本地插件落盘。

---

## ✨ 核心特性

- 💬 **像好友一样在微信主聊天列表一键转发**：
  - 基于企业微信官方「微信客服」或「自建应用」双引擎驱动。
  - 支持直接在微信主聊天列表中常驻（带有专属企业认证标识），在任何公众号文章或网页中点击“发送给朋友”即可一键转发收录。
- 🧠 **大模型智能增强 (LLM-Powered)**：
  - **公众号长文 / 网页链接**：自动抓取正文、清理噪音，通过本机 Antigravity 网关直接请求模型，生成 **100 字核心速读（TLDR）**、核心要点和 Obsidian 标签。
  - **灵感闪念随手记**：阅读简短文字，自动识别语义打上 1~2 个分类标签（如 `#想法`、`#待办`）。
- 📝 **Obsidian 本地文件安全落盘**：
  - 完美适配主流 Obsidian 归档规范：支持**按日归档**（如 `Daily/YYYY-MM-DD/同步助手_YYYY-MM-DD.md`）或**单文件归档**（如 `Inbox.md`）。
  - 内置 `FileLock` 文件互斥锁机制，确保多任务并发写入时绝对不发生数据竞争与损坏。
  - 图片多媒体资源自动从云端下载并保存至本地附件文件夹（如 `attachments/`），生成标准 Obsidian 内部双链 `![[...|缩略图]]`。
- 🔌 **双重本地同步支持**：
  - **原生 Obsidian 插件**：直接安装在 Obsidian 内，支持左侧边栏一键点击同步、快捷键同步、后台自动定时静默轮询同步及可视化设置面板。
  - **独立 Python 同步脚本**：无需打开 Obsidian 客户端，亦可在本地后台静默守护同步。
- 🚀 **全平台系统级原生剪藏 (直传云端，无需中转微信)**：
  - 提供开放的 `POST /api/clip` 接口。
  - 在安卓（HTTP Shortcuts / MacroDroid）或苹果（iOS 快捷指令）中，在知乎、B站、小红书、浏览器点击“系统分享” $\rightarrow$ 选择“剪藏到 Obsidian”，1 秒直达云端并由大模型自动提炼，彻底摆脱外部 App 无法分享给客服或特定联系人的限制！
  - 自动识别并解析知乎问答全文、专栏文章及短想法，微信发送 `/cookie <Cookie>` 可随时免登热更。

### 💬 交互指令大全 (直接在微信对话框发送)

| 指令 | 别名 | 功能说明 | 示例 |
| :--- | :--- | :--- | :--- |
| **`/status`** | `状态` | **实时探测**大模型连通性与知乎 Cookie 有效性看板 | 发送 `/status` |
| **`/llm model`** | `模型` | 查看大模型当前主模型与常用候选列表 | 发送 `/llm model` |
| **`/llm model <模型名>`** | - | **热切换并持久化大模型** (支持连通性预检) | 发送 `/llm model gemini-3.8-flash` |
| **`/llm <问题>`** | - | 对最新一篇笔记展开多轮 AI 深度追问 | 发送 `/llm 核心架构创新是什么？` |
| **`/cookie <Cookie>`** | - | **免登录服务器，直接在微信热更新知乎 Cookie** | 发送 `/cookie _xsrf=...` |
| **`/help`** | `帮助` | 查看完整使用说明与指令列表 | 发送 `/help` |

---
## 🏗️ 系统架构图

```
[ 手机个人微信 ]  (随手发送文字闪念 / 转发文章 / 发送图片)
       │
       ▼ (微信加密 XML Webhook)
[ 云端服务端 (Linux / VPS) ] (7×24小时在线值守)
  ├── 1. 微信密文解密 (Token + EncodingAESKey)
  ├── 2. 网页正文智能抓取 (微信公众号 / 知乎 / 博客正文清洗)
  ├── 3. LLM 智能增强 (大模型提炼 100 字核心速读 + 自动打标签)
  ├── 4. 自动向用户微信回复确认卡片 ("✅ 已收录至 Obsidian")
  └── 5. 暂存入 SQLite 待同步队列 (inbox.db)
       ▲
       │  HTTP REST API 安全拉取 (Token 密钥认证)
       │
[ 本地 Obsidian 知识库 (PC / Mac) ]
  ├── 途径 A: 原生 Obsidian 插件 (边栏一键同步 / 自动定时同步)
  └── 途径 B: 本地 Python 守护进程 (线程安全文件追加)
       │
       ├── 自动落盘写入: Daily/YYYY-MM-DD/同步助手_YYYY-MM-DD.md
       └── 附件图片保存至: attachments/

[ 安卓/iOS 系统原生分享面板 ] (知乎/B站/小红书/Chrome 一键分享)
       │
       ▼ HTTP POST (Token 认证: /api/clip)
[ 云端服务端 (Linux / VPS) ] ──> 爬取清洗 + AI速读打标 ──> 写入待同步数据库
```

---

## 🚀 快速上手指南

### 第一部分：服务端部署 (云服务器 / VPS)

#### 1. 克隆代码与准备配置
```bash
git clone https://github.com/Bowen-0x00/wechat-obsidian-sync.git
cd wechat-obsidian-sync

# 复制配置文件模板
cp config.example.yaml config.yaml
```

编辑 `config.yaml` 填入您的凭据：
```yaml
wechat:
  corp_id: "YOUR_CORP_ID"
  agent_id: 1000003
  secret: "YOUR_SECRET"
  token: "YOUR_TOKEN"
  encoding_aes_key: "YOUR_ENCODING_AES_KEY"
  open_kfid: "YOUR_OPEN_KFID"             # 微信客服账号 ID (若使用微信客服)

llm:
  enable: true
  base_url: "http://127.0.0.1:18890/v1"
  api_key: ""                            # 由 LLM_GATEWAY_KEY 环境变量提供本机网关密钥
  model: "default"                        # 跟随网页设置；网关实际默认模型初始为 gemini-3.8-flash

sync:
  api_secret: "YOUR_CUSTOM_SYNC_SECRET"   # 自定义客户端拉取密钥
  port: 8088                              # 服务监听端口
```

#### 可切换模型通道与研究 agent

四个业务服务共用 `llm_gateway/`，实时请求与研究 agent 分流不随上游切换而改变。当前恢复使用原 OpenAI-compatible API；Antigravity OAuth 实现及私有凭据保留，修复地区/代理问题后可切回：

- `/v1/chat/completions`：微信笔记、图片理解、雷达、普通邮件及其追问直接请求模型，不启动 agent。
- `/agent/v1/chat/completions`：洞察提炼、洞察追问、论文评估和论文追问使用 `thinkingLevel: high`，按需检索历史资料。
- 数据访问工具为 `search_history`、`read_history`、`read_chat_history`，以只读 SQLite 连接访问固定数据库；限制结果长度、调用次数和总执行时间，不提供 shell、文件写入或任意 SQL。结构化分析通过不写库的 `submit_analysis` 提交最终对象，避免长回答破坏 JSON；历史追问取最近消息并按时间正序送入上下文。
- OpenAI-compatible 研究 Agent 的工具回合使用 `stream: false` 获取完整函数名、ID 与参数，再按原 Agent 协议执行；不会猜测、拼接或重命名上游损坏的流式调用。仍使用 high 推理和相同只读工具，Antigravity 原生协议不变。模型错误、取消和截断优先于“没有提交分析”报错，并显示实际模型及上游主机。
- 默认模型为 `gemini-3.8-flash`；`/llm model` 从当前上游模型目录读取候选，不自动切换后端或模型。Google 的授权、目录和推理可用性需分别验证。

实时直调有 45 秒总截止时间，研究 agent 有 240 秒总截止时间；更换 API 不会取消这些上限。网关自身达到截止时间时返回 HTTP `504` / `gateway_timeout`，错误中注明实际模型与上游主机；调用客户端取消或断开则与上游错误区分。`default` 只是跟随网页全局模型的选择器，不是实际模型名。单次超时不代表 Key 失效、配置未保存或切回 Google；网关不会因此自动重试或切换通道。

网页右上角 **「模型设置」** 可管理共享通道、API Base URL、API Key 与全局默认模型，无需登录服务器。手机端为同位置的滑杆图标。

1. 选择 OpenAI 兼容 API 或已在服务器导入的 Antigravity 账号。
2. 填写公网 HTTPS API 根地址（通常以 `/v1` 结尾）。API Key 留空保留已有值，更换 API 地址必须输入对应的新 Key；旧 Key 不会回传至浏览器或发往新地址。
3. 使用「读取模型列表」选择模型，「测试连接」发送简短请求但不修改配置。研究 agent 所用 OpenAI-compatible 上游还需正确支持非流式工具调用，普通直调保持原请求方式。
4. 「保存并生效」会先验证模型请求，通过后原子写入 `data/llm-upstream.env`（`0600`）并热更新。失败保留当前配置；多窗口冲突会要求重新加载。正在执行的请求继续使用原快照。

如果启动时上游不可用或 Key 已失效，配置接口仍保持可用，模型请求会明确返回不可用；可直接在此面板修正配置并恢复，无需先 SSH 修改文件。

业务配置 `llm.model: default` 表示跟随网页全局默认，本次部署的四个应用均已启用。通过微信 `/llm model <具体模型ID>` 独立指定的应用可覆盖全局默认；发送 `/llm model default` 恢复跟随。实时直调与论文、Insight 的 high agent 分流不变。

配置 API 与原工作台共用 Bearer 鉴权：`GET /api/dashboard/model-settings`，以及 `POST /api/dashboard/model-settings/models`、`/test`、`/save`。读取仅返回 `api_key_configured` 标志；提交字段为 `revision`、`backend`、`base_url`、`default_model` 和可选新 `api_key`。禁止用 URL 查询参数授权配置接口，公网访问工作台应使用 HTTPS。


网关单独读取权限为 `0600` 的 `data/llm-upstream.env`，四个 Python 业务服务不读取上游密钥：

```dotenv
LLM_BACKEND=openai-compatible
LLM_UPSTREAM_BASE_URL=https://code28.ccwu.cc/v1
LLM_UPSTREAM_API_KEY=<原 API 密钥，仅保存在服务器私有文件中>
LLM_DEFAULT_MODEL=gemini-3.8-flash
```

该模式不加载 Google 凭据、不调用 Google 模型目录，默认绕过 Google 专用代理。若上游 API 本身需要代理，可单独设置 `LLM_UPSTREAM_PROXY`。推荐在网页切回 Antigravity，保存前会验证原生推理；API 地址与密钥会保留，Antigravity 模式不会使用它们。手工修改此文件时需 `systemctl restart wehub_llm`，网页保存则无需重启。

部署前需要 Bun ≥1.4.4，systemd 模板使用 `/opt/wehub-llm/bin/bun`。以下为保留的 Antigravity 初始化步骤；仅该模式需要可服务账号的 Google 出口代理（当前专用本机入口 `127.0.0.1:18891`）：

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

账号文件仅通过 stdin 导入；OAuth 库和本机密钥均位于忽略提交的 `data/`，权限应为 `0600`，不要把 refresh token 填入业务 `api_key`。各服务通过 `EnvironmentFile` 加载同一 `LLM_GATEWAY_KEY`；前台运行 Python 服务时也需先加载此环境变量。该网关是单一所有者的本机服务，不是多租户或公网 API；不要对外暴露端口或凭据。


#### 2. 安装依赖并启动
```bash
pip install -r requirements.txt

# 运行服务 (可通过 systemd 或 nohup 守护运行)
python -m server.server
```

*(可选：项目目录中包含 `deploy/wechat_obsidian.service`，可直接复制到 `/etc/systemd/system/` 作为系统服务常驻)*

#### 3. 配置微信回调 URL
在企业微信后台（或微信客服）的“设置 API 接收”中填写：
- **URL**: `http://your-server-domain.com/wechat` (可通过 Nginx/OpenResty 反代到 8088 端口)
- **Token** 与 **EncodingAESKey** 保持与 `config.yaml` 一致，点击保存通过握手。

---

### 第二部分：本地 Obsidian 接收端配置

#### 方案 A：使用原生 Obsidian 插件（推荐）
1. 将项目中的 `obsidian_plugin/` 文件夹复制到你的 Obsidian 知识库目录：
   `.obsidian/plugins/wechat-obsidian/`
2. 打开 Obsidian，进入 **设置 $\rightarrow$ 第三方插件**，启用 **“WeChat 笔记助手”**。
3. 进入该插件设置面板：
   - **同步服务器 URL**：填入您的服务器地址（如 `http://your-server-domain.com`）。
   - **同步安全密钥**：填入与 `config.yaml` 中相同的 `sync.api_secret`。
   - **归档模式**：按日归档 (`daily`) 或单文件归档 (`inbox`)。
4. **点击左侧边栏的消息图标**（或按 `Ctrl+P` 运行“立即同步微信笔记”），即可一键拉取并落盘！

#### 方案 B：使用本地 Python 自动同步脚本
在不需要启动 Obsidian 时，也可以直接运行本地脚本自动追加写入本地硬盘：
```bash
cd local
python sync.py --once       # 单次同步
python sync.py --interval 60 # 60秒轮询常驻同步
```

---

## 📂 项目文件结构

```
wechat-obsidian-sync/
├── config.example.yaml          # 云端与本地统一配置模板
├── requirements.txt             # Python 依赖库清单
├── server/                      # 云端接收与处理核心服务
│   ├── server.py                # Webhook 接收、REST API、主业务编排
│   ├── wxcrypt.py               # 微信消息加解密 (AES-256-CBC, PKCS#7)
│   ├── parser.py                # 微信 XML 消息解析器
│   ├── crawler.py               # 微信公众号与网页正文抓取
│   ├── llm_enhancer.py          # 大模型 100 字速读与智能打标引擎
│   ├── storage.py               # SQLite 收件箱待同步队列管理器
│   └── wechat_client.py         # 企业微信与微信客服消息收发与多媒体下载
├── obsidian_plugin/             # 原生 Obsidian 插件 (TypeScript/JS)
│   ├── manifest.json            # 插件清单文件
│   ├── main.js                  # 插件核心逻辑 (边栏按钮、设置面板、文件追加)
│   └── styles.css               # 插件样式
├── local/                       # 本地独立 Python 同步工具
│   ├── writer.py                # 线程安全文件追加写入器与图片下载器
│   └── sync.py                  # 本地定时同步守护程序
├── deploy/
│   └── wechat_obsidian.service  # Linux Systemd 服务模板
├── sync_to_aliyun.py            # 本地代码一键同步至云端服务器工具
├── sync_to_aliyun.bat           # Windows 一键同步批处理
├── sync_local.bat               # Windows 本地一键拉取笔记批处理
└── LICENSE                      # MIT 开源许可证
```

---

## 📄 开源许可证

本项目采用 [MIT License](LICENSE) 许可证。
