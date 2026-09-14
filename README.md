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
  - **公众号长文 / 网页链接**：自动智能抓取正文，剔除噪音广告，调用大模型（DeepSeek / OpenAI / Claude 等）生成 **100 字核心速读（TLDR）**、核心要点提炼，并自动打上符合知识库体系的标准 Obsidian 标签（如 `#计算机体系结构`、`#AI芯片` 等）。
  - **灵感闪念随手记**：阅读简短文字，自动识别语义打上 1~2 个分类标签（如 `#想法`、`#待办`）。
- 📝 **Obsidian 本地文件安全落盘**：
  - 完美适配主流 Obsidian 归档规范：支持**按日归档**（如 `Daily/YYYY-MM-DD/同步助手_YYYY-MM-DD.md`）或**单文件归档**（如 `Inbox.md`）。
  - 内置 `FileLock` 文件互斥锁机制，确保多任务并发写入时绝对不发生数据竞争与损坏。
  - 图片多媒体资源自动从云端下载并保存至本地附件文件夹（如 `attachments/`），生成标准 Obsidian 内部双链 `![[...|缩略图]]`。
- 🔌 **双重本地同步支持**：
  - **原生 Obsidian 插件**：直接安装在 Obsidian 内，支持左侧边栏一键点击同步、快捷键同步、后台自动定时静默轮询同步及可视化设置面板。
  - **独立 Python 同步脚本**：无需打开 Obsidian 客户端，亦可在本地后台静默守护同步。

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
  base_url: "https://api.deepseek.com/v1" # 兼容 OpenAI 格式 API
  api_key: "YOUR_LLM_API_KEY"
  model: "deepseek-chat"

sync:
  api_secret: "YOUR_CUSTOM_SYNC_SECRET"   # 自定义客户端拉取密钥
  port: 8088                              # 服务监听端口
```

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
