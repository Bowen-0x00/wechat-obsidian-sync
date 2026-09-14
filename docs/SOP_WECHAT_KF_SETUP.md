# 微信客服与 Obsidian 随手记全流程配置指南 (SOP)

本文档详细记录了如何利用企业微信官方的**「微信客服」**功能，打造一个在个人微信主聊天列表中常驻、带有**橙色认证标**、且支持在任意公众号文章中**“发送给朋友一键转发”**的 Obsidian 私有化随手记助手。

---

## 目录
1. [为什么必须使用「微信客服」而非普通自建应用](#1-为什么必须使用微信客服而非普通自建应用)
2. [微信客服开通与托管绑定全流程](#2-微信客服开通与托管绑定全流程)
   - [第一步：开通微信客服功能](#第一步开通微信客服功能)
   - [第二步：创建客服账号与形象设置](#第二步创建客服账号与形象设置)
   - [第三步：托管至自建应用 (共享凭据秘诀)](#第三步托管至自建应用-共享凭据秘诀)
3. [微信主聊天列表常驻与一键转发测试](#3-微信主聊天列表常驻与一键转发测试)
4. [云服务器回调验证与 OpenResty 反向代理](#4-云服务器回调验证与-openresty-反向代理)
5. [Obsidian 本地插件安装与自动化落盘](#5-obsidian-本地插件安装与自动化落盘)
6. [云端守护服务 Systemd 与运维命令](#6-云端守护服务-systemd-与运维命令)

---

## 1. 为什么必须使用「微信客服」而非普通自建应用

微信生态在底层架构上存在严格的安全与流控限制：

| 对比维度 | 普通企业自建应用 | 微信客服（商业版同款底层） |
| :--- | :--- | :--- |
| **微信内入口** | 深深折叠在“企业微信”插件二级文件夹内 | **独立常驻**在个人微信主聊天列表顶层 |
| **专属标识** | 无专属标识 | 名字后缀带有尊贵的**橙黄色 `@企业名称`** 官方认证标 |
| **公众号长文一键转发** | ❌ **底层完全禁止**（转发列表搜不到） | ✅ **完全原生支持**（像发给好友一样点“发送给朋友”） |
| **图片与文字闪念** | 仅支持在折叠对话框中复制发送 | 直接在微信主聊天框中发送文字、表情、图片、截图 |
| **API 接口支持** | 支持事件回调 | 支持事件回调 + 微信官方客服消息同步 API |

因此，要获得与市面上商业付费插件 100% 相同的使用体验，开通并配置「微信客服」是唯一且最佳的途径。

---

## 2. 微信客服开通与托管绑定全流程

### 第一步：开通微信客服功能
1. 浏览器登录 [企业微信管理后台](https://work.weixin.qq.com/)。
2. 导航栏进入 **应用管理**。
3. 在应用列表中找到 **“微信客服”**（若显示未开启，点击开启）。

### 第二步：创建客服账号与形象设置
1. 在微信客服页面，找到 **“客服账号 (Customer Service Account)”**。
2. 点击 **“添加客服账号 (Create Account)”**：
   - **名称**：填写 `Obsidian` 或 `笔记助手`。
   - **头像**：上传 Obsidian 紫色宝石 Logo 图标。
   - **接待人员**：勾选选择你自己。

### 第三步：托管至自建应用 (共享凭据秘诀)
这一步是免去重复申请 API 权限的最优雅做法：
1. 页面往下拉，找到 **“API 接入 / 权限管理 (Manage chat messages via API)”**。
2. 选择 **“自建应用托管 / In-house development”**。
3. 选择你前面创建的自建应用（如 `笔记助手`，AgentId `1000003`），将其关联给刚建的 `Obsidian` 客服账号。
4. **效果**：微信客服将**直接复用该自建应用的所有配置**（相同的 `CorpID`、`Secret`、`Token`、`EncodingAESKey` 与接收消息的服务器 URL），无需任何多余开发授权！
5. 在页面上方记录生成的客服链接：
   `https://work.weixin.qq.com/kfid/kfcxxxxxx`

---

## 3. 微信主聊天列表常驻与一键转发测试

1. 在后台客服账号详情页中，点击 **“在微信中接入”** $\rightarrow$ **“生成二维码 (Generate QR Code)”**。
   *(或者直接在手机微信中访问链接 `https://work.weixin.qq.com/kfid/kfcxxxxxx`)*
2. 使用你的**个人手机微信扫码**。
3. 手机微信会立即弹出一个独立的会话窗口：
   * 名字显示为：**`Obsidian @你的企业名`**（带有橙黄色小标）。
4. 在会话中随便发送一条文字（如“你好”）。
5. **常驻完成**：该联系人现已永久留在你的微信主聊天列表中。你可以长按它选择 **“置顶聊天”**。
6. **一键转发测试**：打开微信中任意一篇公众号长文，点击右上角 `...` $\rightarrow$ **“发送给朋友”**，在搜索栏或最近聊天中点击 `Obsidian @你的企业名` 即可一秒发送！

---

## 4. 云服务器回调验证与 OpenResty 反向代理

### 4.1 消息数据链路与回调
当用户向客服发送内容时：
1. 微信服务器向你的公网回调地址发送事件通知：
   `POST http://your-domain.com/wechat`
2. 服务端在 5 秒内解密并响应 `success`。
3. 服务端后台异步调用 `https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg` 拉取该条图文/网页长链接。
4. 正文爬虫清洗网页，大语言模型（LLM）提取 100 字核心速读并打上 `#标签`，存入云端数据库，并通过客服接口自动在会话内回复你确认卡片。

### 4.2 OpenResty / Nginx 端口配置最佳实践
为了避免云服务器上 80/443 端口与现有网站冲突，建议服务端监听内网独立端口（如 `8088`），通过 Nginx/OpenResty 进行反向代理：

在域名（如 `your-domain.com`）的 Nginx `server { ... }` 配置块中追加：
```nginx
# 微信消息与事件回调接口
location /wechat {
    proxy_pass http://127.0.0.1:8088;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Obsidian 本地拉取与图片下载 API
location /api/ {
    proxy_pass http://127.0.0.1:8088;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```
重载配置：`nginx -s reload`。

---

## 5. Obsidian 本地插件安装与自动化落盘

本项目自带完全符合 Obsidian 官方标准的社区插件（位于项目 `obsidian_plugin/` 目录）：

### 5.1 插件安装
1. 将 `obsidian_plugin/` 目录下的三个文件复制到你的笔记库插件文件夹：
   `你的知识库/.obsidian/plugins/wechat-obsidian/`
   - `manifest.json`
   - `main.js`
   - `styles.css`
2. 在 Obsidian 设置中，进入 **第三方插件**，在“已安装插件”列表中找到并开启 **WeChat 笔记助手**。

### 5.2 插件功能与体验
- **左侧工具栏图标**：左侧边栏会出现一个气泡图标，点击即可随时拉取最新未同步的微信笔记。
- **自动后台同步**：只要 Obsidian 保持打开，默认每 60 秒静默拉取一次，落盘后屏幕右下角会弹出轻通知。
- **文件落盘格式**：
  自动追加至 `10-Journal&Planning/13-note/{日期}/同步助手_{日期}.md`，图片保存在 `images/`，支持 AI 100 字速读 Callout 排版。
- **防数据冲突锁**：内置文件互斥锁与隐形 ID，多端多设备同步绝不产生数据竞争与重复片段。

---

## 6. 云端守护服务 Systemd 与运维命令

在 Linux 云服务器上，通过 Systemd 保持 7×24 小时后台运行：

```bash
# 启动云端服务并设置开机自启
systemctl daemon-reload
systemctl enable --now wechat_obsidian

# 实时查看微信消息接收与 AI 提炼日志
journalctl -u wechat_obsidian -f

# 重启服务
systemctl restart wechat_obsidian
```

本地代码若有调整，可在本地双击运行 `sync_to_aliyun.bat`，3 秒内完成增量上传与服务热重启。
