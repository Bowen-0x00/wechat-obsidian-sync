"""WeChat to Obsidian 云端核心服务 (消息接收解密 + AI 增强 + 同步 REST API)."""

import os
import re
import json
import yaml
import time
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, List, Dict, Any
from loguru import logger

try:
    from .wxcrypt import WXBizMsgCrypt
    from .parser import MessageParser, WeChatMessage
    from .crawler import ArticleCrawler
    from .llm_enhancer import LLMEnhancer
    from .storage import InboxStorage
    from .wechat_client import WeComClient
except ImportError:
    from wxcrypt import WXBizMsgCrypt
    from parser import MessageParser, WeChatMessage
    from crawler import ArticleCrawler
    from llm_enhancer import LLMEnhancer
    from storage import InboxStorage
    from wechat_client import WeComClient


class WeChatObsidianServer:
    """服务端业务协调器."""

    def __init__(self, config_path: str = "config.yaml"):
        if not os.path.exists(config_path):
            if os.path.exists("config.example.yaml"):
                config_path = "config.example.yaml"
            else:
                raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

        wc = self.cfg["wechat"]
        self.corp_id = wc["corp_id"]
        self.agent_id = wc["agent_id"]
        self.secret = wc["secret"]
        self.token = wc["token"]
        self.encoding_aes_key = wc["encoding_aes_key"]
        self.open_kfid = wc.get("open_kfid", "")
        self.crypt = WXBizMsgCrypt(self.token, self.encoding_aes_key, self.corp_id)
        
        # 统一多应用回调转发路由表 (邮件通知 1000002, 社交雷达 1000004, 洞察引擎 1000005)
        self.gateway_routes = [
            {
                "name": "邮件通知 (1000002)",
                "port": 8087,
                "crypt": WXBizMsgCrypt("dPSAGVIQMAJmoNgon62TYDi", "0hauE4dK6GN4hPUBA5M15LvoGZyMkV9PcabQPH8gtR8", self.corp_id)
            },
            {
                "name": "社交雷达 (1000004)",
                "port": 8085,
                "crypt": WXBizMsgCrypt("JyyBkfqOUshWB6nHbUdW4UiqRibSaB", "5oSnf2sWi9JeySMrwAK7HanS9rV8tJzEbec5zQHYLCC", self.corp_id)
            },
            {
                "name": "洞察引擎 (1000005)",
                "port": 8086,
                "crypt": WXBizMsgCrypt("Bfj3VGVeKysV5Q9koJg6TUs9MFwj", "IVxJFR8Ae4jhJmwmcmA0AJm8O2mIgEsYTqoSUGBeShX", self.corp_id)
            }
        ]
        lc = self.cfg.get("llm", {})
        self.llm = LLMEnhancer(
            base_url=lc.get("base_url", ""),
            api_key=lc.get("api_key", ""),
            model=lc.get("model", "deepseek-chat"),
            temperature=float(lc.get("temperature", 0.3)),
            enable=bool(lc.get("enable", True)),
            proxy=lc.get("proxy")
        )

        # 加载知乎配置 (优先当前配置，若无则自动回退查找同台机器上的 social_radar 配置)
        zc = self.cfg.get("zhihu", {})
        zhihu_cookie = zc.get("cookie", "")
        if not zhihu_cookie:
            candidate_paths = [
                os.path.join(os.path.dirname(__file__), "../../social_radar/config/config.yaml"),
                os.path.join(os.path.dirname(__file__), "../social_radar/config/config.yaml"),
                "/root/social_radar/config/config.yaml"
            ]
            for cp in candidate_paths:
                if os.path.exists(cp):
                    try:
                        with open(cp, "r", encoding="utf-8") as f:
                            sr_cfg = yaml.safe_load(f) or {}
                            cand = sr_cfg.get("zhihu", {}).get("cookie", "")
                            if cand:
                                zhihu_cookie = cand
                                logger.info(f"[Server] 成功从 social_radar 复用知乎凭据 (长度: {len(zhihu_cookie)})")
                                break
                    except Exception as e:
                        logger.warning(f"[Server] 尝试复用 social_radar 配置异常: {e}")

        crawler_proxy = lc.get("proxy")
        self.crawler = ArticleCrawler(timeout=15, zhihu_cookie=zhihu_cookie, proxy=crawler_proxy)
        self.storage = InboxStorage(db_path="data/inbox.db")
        self.wecom_client = WeComClient(
            corp_id=self.corp_id,
            agent_id=self.agent_id,
            secret=self.secret,
            cache_dir="data/images"
        )

        sc = self.cfg.get("sync", {})
        self.api_secret = sc.get("api_secret", "obsidian_sync_token_secure_8888")
        self.port = int(sc.get("port", 80))

        # 异步线程池处理耗时的网络爬虫与大模型请求，避免阻塞微信回调
        self.executor = ThreadPoolExecutor(max_workers=8)
    def _submit_background(self, func, *args):
        """提交后台任务，并确保线程内异常不会被 Future 静默吞掉."""
        future = self.executor.submit(func, *args)
        future.add_done_callback(self._log_background_failure)
        return future

    @staticmethod
    def _log_background_failure(future):
        try:
            future.result()
        except Exception:
            logger.exception("[Server] 后台消息处理失败")


    def handle_incoming_xml(self, msg_signature: str, timestamp: str, nonce: str, raw_xml: str):
        """同步解密后提交后台异步处理，立即返回 success 避免微信超时重试."""
        try:
            decrypted_xml = self.crypt.decrypt_msg(msg_signature, timestamp, nonce, raw_xml)
            msg = MessageParser.parse_xml(decrypted_xml)
            if msg:
                self._submit_background(self._process_message_async, msg)
        except Exception as e:
            logger.error(f"[Server] 消息解密/解析失败: {e}")

    def _process_message_async(self, msg: WeChatMessage):
        """后台执行正文抓取、LLM 摘要打标与入库."""
        # 1. 微信客服消息事件处理
        if msg.msg_type == "event" and msg.event == "kf_msg_or_event":
            logger.info("[Server] 收到微信客服新消息事件通知，开始拉取客服会话...")
            self._process_kf_event_async(msg)
            return

        if self.storage.is_msg_processed(msg.msg_id):
            logger.debug(f"[Server] 消息已处理过，跳过: {msg.msg_id}")
            return
        logger.info(f"[Server] 开始异步处理新微信消息 ({msg.msg_type}): {msg.title or msg.content[:30]}")

        # 检查是否为控制指令 (/help, /status, /llm)
        cmd_text = msg.content.strip().lower() if msg.msg_type == "text" else ""
        if cmd_text in ("/help", "／help", "help", "帮助", "/h"):
            self._handle_help_command(msg)
            return
        elif cmd_text in ("/status", "／status", "status", "状态", "/s"):
            self._handle_status_command(msg)
            return
        elif cmd_text.startswith(("/cookie", "／cookie", "cookie", "更新cookie", "知乎cookie")):
            self._handle_cookie_command(msg)
            return
        elif cmd_text.startswith(("/llm", "／llm")):
            self._handle_llm_chat_command(msg)
            return
        title = msg.title
        author = ""
        url = msg.url
        raw_content = msg.content
        tldr = ""
        key_points = []
        tags = []
        media_filename = ""
        content_markdown = ""
        image_urls = []

        # 1. 链接/文章类型 (或正文包含 URL)
        if msg.msg_type == "link" or msg.url or (msg.msg_type == "text" and msg.embedded_urls):
            target_url = msg.url or (msg.embedded_urls[0] if msg.embedded_urls else "")
            logger.info(f"[Server] 抓取网页正文: {target_url}")

            user_note_text = ""
            if msg.msg_type == "text" and msg.content:
                user_note_text = re.sub(r'https?://[^\s<>"\'\(\)]+', '', msg.content).strip()

            title_hint = msg.title or (user_note_text[:40] if user_note_text else "")
            article = self.crawler.crawl(target_url, title_hint=title_hint)
            title = article.title or msg.title or (user_note_text[:40] if user_note_text else "网页收藏")
            if title.startswith(("http://", "https://")) and (msg.title or user_note_text):
                title = msg.title or user_note_text[:40]
            author = article.author
            url = article.url or target_url
            image_urls = article.images

            # 内容与摘要回退保障机制
            if article.content_markdown and len(article.content_markdown.strip()) > 30:
                content_markdown = article.content_markdown
                content_text = article.content_text
                if user_note_text:
                    content_markdown = f"> [!note] 随附笔记\n> {user_note_text}\n\n" + content_markdown
            else:
                # 抓取正文受阻（如反爬拦截），使用卡片摘要或用户附言作为正文
                fallback_content = msg.content if msg.msg_type == "link" else user_note_text
                fallback_content = fallback_content.strip()
                content_text = fallback_content or title
                if fallback_content:
                    content_markdown = f"> [!quote] 摘要内容\n> {fallback_content}\n\n> 🔗 原文链接: [{title}]({url})\n"
                else:
                    content_markdown = f"> [!info] 收藏链接\n> 🔗 [{title}]({url})\n> *(正文触发站点反爬防护，已自动记录链接与标题)*\n"

            # 调用大模型生成 100 字速读和标签
            ai_res = self.llm.summarize_article(title, content_text, url)
            tldr = ai_res.get("tldr", "")
            key_points = ai_res.get("key_points", [])
            tags = ai_res.get("tags", ["#文章收藏"])
        # 2. 纯文本闪念
        elif msg.msg_type == "text":
            title = "闪念随笔"
            tags = self.llm.tag_thought(raw_content)

        # 3. 图片消息
        elif msg.msg_type == "image":
            title = "图片备忘"
            tags = ["#图片"]
            # 下载微信媒体资源
            if msg.media_id:
                media_filename = self.wecom_client.download_media(msg.media_id, prefix="wx_img") or ""

        # 入库存储
        note_id = self.storage.add_note(
            msg_id=msg.msg_id,
            msg_type=msg.msg_type,
            from_user=msg.from_user,
            create_time=msg.create_time,
            raw_content=raw_content,
            title=title,
            author=author,
            url=url,
            tldr=tldr,
            key_points=key_points,
            tags=tags,
            media_filename=media_filename,
            content_markdown=content_markdown,
            image_urls=image_urls
        )
        # 发送微信确认
        confirm_text = f"✅ 已成功收录至 Obsidian (ID: {note_id})\n"
        if title and title != "闪念随笔":
            confirm_text += f"📄 《{title}》\n"
        if tldr:
            confirm_text += f"💡 核心速读: {tldr}\n"
        if tags:
            confirm_text += f"🏷️ 标签: {' '.join(tags)}"

        self.wecom_client.send_confirmation(msg.from_user, confirm_text.strip())

    def _process_kf_event_async(self, event_msg: WeChatMessage):
        """从微信客服 API 拉取消息并处理入库."""
        kfid = event_msg.open_kfid or self.open_kfid
        data = self.wecom_client.sync_kf_messages(token=event_msg.event_token, open_kfid=kfid)
        msg_list = data.get("msg_list", [])
        logger.info(f"[Server] 微信客服拉取到 {len(msg_list)} 条消息")

        for m in msg_list:
            # origin == 4 表示客服自己发出的消息，跳过防死循环
            if m.get("origin") == 4:
                continue

            msg_id = m.get("msgid", "")
            if not msg_id or self.storage.is_msg_processed(msg_id):
                continue

            msg_type = m.get("msgtype", "text")
            send_time = m.get("send_time", int(time.time()))
            from_user = m.get("external_userid", "")

            title = ""
            author = ""
            url = ""
            raw_content = ""
            tldr = ""
            key_points = []
            tags = []
            content_markdown = ""
            image_urls = []
            media_filename = ""

            # 文本类型
            if msg_type == "text":
                raw_content = m.get("text", {}).get("content", "")
                cmd_raw = raw_content.strip().lower()
                if cmd_raw in ("/help", "／help", "help", "帮助", "/h"):
                    kf_cmd_msg = WeChatMessage(msg_id=msg_id, msg_type="text", from_user=from_user, create_time=send_time, content=raw_content)
                    self._handle_help_command(kf_cmd_msg, is_kf=True, kfid=kfid)
                    continue
                elif cmd_raw in ("/status", "／status", "status", "状态", "/s"):
                    kf_cmd_msg = WeChatMessage(msg_id=msg_id, msg_type="text", from_user=from_user, create_time=send_time, content=raw_content)
                    self._handle_status_command(kf_cmd_msg, is_kf=True, kfid=kfid)
                    continue
                elif cmd_raw.startswith(("/cookie", "／cookie", "cookie", "更新cookie", "知乎cookie")):
                    kf_cmd_msg = WeChatMessage(msg_id=msg_id, msg_type="text", from_user=from_user, create_time=send_time, content=raw_content)
                    self._handle_cookie_command(kf_cmd_msg, is_kf=True, kfid=kfid)
                    continue
                elif cmd_raw.startswith(("/llm", "／llm")):
                    kf_cmd_msg = WeChatMessage(msg_id=msg_id, msg_type="text", from_user=from_user, create_time=send_time, content=raw_content)
                    self._handle_llm_chat_command(kf_cmd_msg, is_kf=True, kfid=kfid)
                    continue
                # 检查是否包含网页 URL
                import html
                content_clean = html.unescape(raw_content)
                urls = MessageParser.URL_PATTERN.findall(content_clean)
                if urls:
                    url = urls[0]
                    user_note_text = re.sub(r'https?://[^\s<>"\'\(\)]+', '', content_clean).strip()
                    title_hint = user_note_text[:40] if user_note_text else ""
                    article = self.crawler.crawl(url, title_hint=title_hint)
                    title = article.title or (user_note_text[:40] if user_note_text else "网页收藏")
                    if title.startswith(("http://", "https://")) and user_note_text:
                        title = user_note_text[:40]
                    author = article.author
                    url = article.url or url
                    image_urls = article.images

                    if article.content_markdown and len(article.content_markdown.strip()) > 30:
                        content_markdown = article.content_markdown
                        content_text = article.content_text
                        if user_note_text:
                            content_markdown = f"> [!note] 随附笔记\n> {user_note_text}\n\n" + content_markdown
                    else:
                        content_text = user_note_text or title
                        if user_note_text:
                            content_markdown = f"> [!quote] 随笔记录\n> {user_note_text}\n\n> 🔗 原文链接: [{title}]({url})\n"
                        else:
                            content_markdown = f"> [!info] 收藏链接\n> 🔗 [{title}]({url})\n> *(正文触发站点反爬防护，已自动记录链接与标题)*\n"

                    ai_res = self.llm.summarize_article(title, content_text, url)
                    tldr = ai_res.get("tldr", "")
                    key_points = ai_res.get("key_points", [])
                    tags = ai_res.get("tags", ["#文章收藏"])
                else:
                    title = "闪念随笔"
                    tags = self.llm.tag_thought(raw_content)

            # 链接 / 公众号文章转发类型
            elif msg_type == "link":
                link_data = m.get("link", {})
                title = link_data.get("title", "")
                url = link_data.get("url", "")
                raw_content = link_data.get("desc", "")
                article = self.crawler.crawl(url, title_hint=title)
                title = article.title or title or "微信文章收藏"
                author = article.author
                url = article.url or url
                image_urls = article.images

                if article.content_markdown and len(article.content_markdown.strip()) > 30:
                    content_markdown = article.content_markdown
                    content_text = article.content_text
                else:
                    content_text = raw_content or title
                    if raw_content:
                        content_markdown = f"> [!quote] 微信转发摘要\n> {raw_content}\n\n> 🔗 原文链接: [{title}]({url})\n"
                    else:
                        content_markdown = f"> [!info] 收藏链接\n> 🔗 [{title}]({url})\n> *(正文触发站点反爬防护，已自动记录链接与标题)*\n"

                ai_res = self.llm.summarize_article(title, content_text, url)
                tldr = ai_res.get("tldr", "")
                key_points = ai_res.get("key_points", [])
                tags = ai_res.get("tags", ["#文章收藏"])
            elif msg_type == "image":
                title = "图片备忘"
                tags = ["#图片"]
                media_id = m.get("image", {}).get("media_id", "")
                if media_id:
                    media_filename = self.wecom_client.download_media(media_id, prefix="kf_img") or ""

            # 入库
            note_id = self.storage.add_note(
                msg_id=msg_id,
                msg_type=msg_type,
                from_user=from_user,
                create_time=send_time,
                raw_content=raw_content,
                title=title,
                author=author,
                url=url,
                tldr=tldr,
                key_points=key_points,
                tags=tags,
                media_filename=media_filename,
                content_markdown=content_markdown,
                image_urls=image_urls
            )

            # 客服会话内回复确认
            confirm_text = f"✅ 已成功收录至 Obsidian (ID: {note_id})\n"
            if title and title != "闪念随笔":
                confirm_text += f"📄 《{title}》\n"
            if tldr:
                confirm_text += f"💡 核心速读: {tldr}\n"
            if tags:
                confirm_text += f"🏷️ 标签: {' '.join(tags)}"

            self.wecom_client.send_kf_reply(from_user, kfid, confirm_text.strip())
    def _handle_llm_chat_command(self, msg: WeChatMessage, is_kf: bool = False, kfid: str = ""):
        """处理 /llm 交互追问命令."""
        text = msg.content.strip()
        # 去除前缀 /llm 或 ／llm
        if text.startswith(("/llm", "／llm")):
            text = text[4:].strip()

        # 解析命令参数: [/llm] [target] <question>
        parts = text.split(maxsplit=1)
        if not parts:
            help_text = (
                "💡 【/llm 笔记追问指南】\n"
                "• /llm <问题> (默认追问最近一篇笔记)\n"
                "• /llm last <问题> (追问最近一篇笔记)\n"
                "• /llm <ID> <问题> (追问指定 ID 笔记，如 /llm 17 ...)\n"
                "• /llm <时间> <问题> (如 /llm 20260920 或 /llm 202609202157 ...)\n"
                "• /llm history (查看上一篇笔记的概况与历史)"
            )
            self._reply_user(msg.from_user, help_text, is_kf, kfid)
            return

        first_token = parts[0].strip().lower()
        if first_token in ("last", "latest") or first_token.isdigit() or (len(first_token) >= 8 and first_token.isalnum()):
            target = first_token
            question = parts[1].strip() if len(parts) > 1 else ""
        else:
            # 用户直接输入了问题，如: /llm 核心观点是什么？
            target = "last"
            question = text

        note = self.storage.get_note_by_target(target, from_user=msg.from_user)
        if not note:
            reply_text = f"❌ 未找到对应的笔记或文章 (查询目标: '{target}')。\n请确认笔记 ID 是否正确，或发送 /llm 查看帮助。"
            self._reply_user(msg.from_user, reply_text, is_kf, kfid)
            return

        note_id = note["id"]
        note_title = note["title"] or "未命名笔记"

        # 如果用户只输入了 /llm id 或 /llm history 而没有问题，返回基本概况
        if not question or question.lower() == "history":
            history = self.storage.get_chat_history(note_id, limit=6)
            info_text = f"📄 当前选中笔记 [ID: {note_id}]: 《{note_title}》\n"
            if note["author"]:
                info_text += f"👤 作者: {note['author']}\n"
            if note["tldr"]:
                info_text += f"💡 核心速读: {note['tldr']}\n"
            info_text += f"\n💬 已有追问历史: {len(history)} 条消息。\n您可以发送：/llm {note_id} 您的具体问题"
            self._reply_user(msg.from_user, info_text, is_kf, kfid)
            return

        logger.info(f"[LLM Chat] 用户 {msg.from_user} 追问笔记 [ID: {note_id}] 《{note_title}》: {question}")
        
        # 获取对话历史并生成回复
        history = self.storage.get_chat_history(note_id, limit=6)
        answer = self.llm.chat_with_note(note, question, history)

        # 固化本轮问答到数据库
        self.storage.add_chat_message(note_id, msg.from_user, "user", question)
        self.storage.add_chat_message(note_id, msg.from_user, "assistant", answer)

        # 组装微信端回复（兼顾 2048 字节限制）
        reply_msg = (
            f"🤖 【AI 深度追问】[ID: {note_id}]\n"
            f"📄 《{note_title}》\n"
            f"❓ 问: {question}\n\n"
            f"💡 答:\n{answer}"
        )
        self._reply_user(msg.from_user, reply_msg.strip(), is_kf, kfid)

    def _handle_cookie_command(self, msg: WeChatMessage, is_kf: bool = False, kfid: str = ""):
        """处理 /cookie 更新知乎凭据指令."""
        text = msg.content.strip()
        parts = re.split(r'\s+', text, maxsplit=1)
        if len(parts) < 2 or len(parts[1].strip()) < 15:
            help_msg = (
                "🍪 **知乎 Cookie 更新指南**\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "• 用法：发送 `/cookie <您的完整Cookie>`\n"
                "• 作用：使笔记助手具备直接解析知乎问答全文、专栏文章与高清原图的权限\n"
                "• 获取方式：电脑浏览器访问 zhihu.com 登录后，F12 网络面板中复制任意请求的 `Cookie:` 标头内容即可。"
            )
            self._reply_user(msg.from_user, help_msg, is_kf, kfid)
            return

        new_cookie = parts[1].strip()
        self.crawler.set_zhihu_cookie(new_cookie)

        # 写入本地 config.yaml
        try:
            config_path = "config.yaml"
            cfg_obj = {}
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg_obj = yaml.safe_load(f) or {}
            if "zhihu" not in cfg_obj:
                cfg_obj["zhihu"] = {}
            cfg_obj["zhihu"]["cookie"] = new_cookie
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg_obj, f, allow_unicode=True)
            logger.info("[Server] 本地 config.yaml 知乎 Cookie 更新成功")
        except Exception as e:
            logger.error(f"[Server] 更新本地 config.yaml 异常: {e}")

        # 同步写入 social_radar 的 config.yaml (如果存在)
        for sr_path in ["/root/social_radar/config/config.yaml", "../social_radar/config/config.yaml"]:
            if os.path.exists(sr_path):
                try:
                    with open(sr_path, "r", encoding="utf-8") as f:
                        sr_obj = yaml.safe_load(f) or {}
                    if "zhihu" in sr_obj:
                        sr_obj["zhihu"]["cookie"] = new_cookie
                        with open(sr_path, "w", encoding="utf-8") as f:
                            yaml.dump(sr_obj, f, allow_unicode=True)
                        logger.info(f"[Server] 同步热更新 {sr_path} 知乎 Cookie 成功！")
                except Exception as e:
                    logger.warning(f"[Server] 同步更新 {sr_path} 异常: {e}")

        reply_msg = (
            "✅ **知乎 Cookie 更新成功！**\n\n"
            f"已热加载凭据（长度: {len(new_cookie)}），后续粘贴知乎链接将自动尝试拉取问答与专栏全文并排版。"
        )
        self._reply_user(msg.from_user, reply_msg, is_kf, kfid)
    def process_clipped_content(
        self,
        raw_text: str,
        custom_title: str = "",
        extra_tags: Optional[List[str]] = None,
        from_user: str = "quick_share"
    ) -> Dict[str, Any]:
        """处理手机快捷指令/系统分享直传的内容，完成爬取、LLM分析与入库."""
        import html
        raw_clean = html.unescape(raw_text.strip())
        urls = MessageParser.URL_PATTERN.findall(raw_clean)

        now_ts = int(time.time())
        msg_id = f"clip_{now_ts}_{int(time.time() * 1000) % 10000}"

        title = custom_title
        author = ""
        url = ""
        tldr = ""
        key_points = []
        tags = list(extra_tags or [])
        content_markdown = ""
        image_urls = []
        media_filename = ""
        raw_content = raw_clean

        if urls:
            msg_type = "link"
            url = urls[0]
            user_note_text = re.sub(r'https?://[^\s<>"\'\(\)]+', '', raw_clean).strip()
            title_hint = custom_title or (user_note_text[:40] if user_note_text else "")

            logger.info(f"[Clip API] 提取到链接，开始抓取: {url}")
            article = self.crawler.crawl(url, title_hint=title_hint)
            title = custom_title or article.title or (user_note_text[:40] if user_note_text else "网页剪藏")
            if title.startswith(("http://", "https://")) and (custom_title or user_note_text):
                title = custom_title or user_note_text[:40]
            author = article.author
            url = article.url or url
            image_urls = article.images

            if article.content_markdown and len(article.content_markdown.strip()) > 30:
                content_markdown = article.content_markdown
                content_text = article.content_text
                if user_note_text:
                    content_markdown = f"> [!note] 随附笔记\n> {user_note_text}\n\n" + content_markdown
            else:
                content_text = user_note_text or title
                if user_note_text:
                    content_markdown = f"> [!quote] 剪藏摘要\n> {user_note_text}\n\n> 🔗 原文链接: [{title}]({url})\n"
                else:
                    content_markdown = f"> [!info] 剪藏链接\n> 🔗 [{title}]({url})\n> *(正文触发站点反爬防护，已自动记录链接与标题)*\n"

            ai_res = self.llm.summarize_article(title, content_text, url)
            tldr = ai_res.get("tldr", "")
            key_points = ai_res.get("key_points", [])
            for t in ai_res.get("tags", ["#剪藏"]):
                if t not in tags:
                    tags.append(t)
        else:
            msg_type = "text"
            title = custom_title or "闪念随笔"
            thought_tags = self.llm.tag_thought(raw_clean)
            for t in thought_tags:
                if t not in tags:
                    tags.append(t)

        note_id = self.storage.add_note(
            msg_id=msg_id,
            msg_type=msg_type,
            from_user=from_user,
            create_time=now_ts,
            raw_content=raw_content,
            title=title,
            author=author,
            url=url,
            tldr=tldr,
            key_points=key_points,
            tags=tags,
            media_filename=media_filename,
            content_markdown=content_markdown,
            image_urls=image_urls
        )

        logger.info(f"[Clip API] 快捷剪藏入库成功 [ID: {note_id}]: 《{title}》")

        # 异步通过微信客服/应用给用户发一条推送提醒 (可选)
        def _notify():
            try:
                notify_text = f"📱 **手机一键剪藏成功** (ID: {note_id})\n"
                if title and title != "闪念随笔":
                    notify_text += f"📄 《{title}》\n"
                if tldr:
                    notify_text += f"💡 核心速读: {tldr}\n"
                if tags:
                    notify_text += f"🏷️ 标签: {' '.join(tags)}"
                self.wecom_client.send_confirmation("@all", notify_text.strip())
            except Exception as e:
                logger.debug(f"[Clip API] 发送微信通知跳过: {e}")

        self._submit_background(_notify)

        return {
            "note_id": note_id,
            "title": title,
            "tldr": tldr,
            "tags": tags
        }


    def _reply_user(self, to_user: str, text: str, is_kf: bool = False, kfid: str = ""):
        """统一发送微信/客服回复."""
        if is_kf and kfid:
            self.wecom_client.send_kf_reply(to_user, kfid, text)
        else:
            self.wecom_client.send_confirmation(to_user, text)
    def _handle_help_command(self, msg: WeChatMessage, is_kf: bool = False, kfid: str = ""):
        """返回笔记助手的完整使用手册."""
        help_text = (
            "📖 **Obsidian 笔记助手交互手册**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔹 **核心剪藏功能**:\n"
            "• 直接发送微信文章链接: 自动抓取标题、作者、正文排版并下载图片\n"
            "• 发送普通文本/闪念: 自动归档并打上精炼标签\n"
            "• 发送图片: 自动保存原图并关联至 Obsidian 附件\n\n"
            "🔹 **AI 深度追问与多轮对话**:\n"
            "• `/llm <问题>`: 对最新收录的一篇笔记/文章发起深度追问\n"
            "• `/llm last <问题>`: 追问最近一篇笔记\n"
            "• `/llm <ID> <问题>`: 追问指定 ID 笔记 (如 `/llm 17 ...`)\n"
            "• `/llm <时间> <问题>`: 按日期追问 (如 `/llm 20260920 ...`)\n"
            "• `/llm history`: 查看当前选中笔记的概况与已有追问历史\n\n"
            "🔹 **系统状态**:\n"
            "• `/cookie <Cookie内容>`: 更新知乎抓取凭据，开启知乎全文与问答解析\n"
            "• `/status` 或 `状态`: 检查笔记收件箱状态、已入库数量与同步情况"
        )
        self._reply_user(msg.from_user, help_text, is_kf, kfid)

    def _handle_status_command(self, msg: WeChatMessage, is_kf: bool = False, kfid: str = ""):
        """返回笔记收件箱与服务运行状态看板."""
        with self.storage._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*), SUM(CASE WHEN is_synced=0 THEN 1 ELSE 0 END), SUM(CASE WHEN is_synced=1 THEN 1 ELSE 0 END) FROM inbox_notes")
            total, unsynced, synced = cur.fetchone()
            total = total or 0
            unsynced = unsynced or 0
            synced = synced or 0

            cur.execute("SELECT id, title, created_at FROM inbox_notes ORDER BY id DESC LIMIT 1")
            latest = cur.fetchone()

        latest_info = f"《{latest['title']}》 (ID: {latest['id']}, {latest['created_at']})" if latest else "暂无记录"

        llm_cfg = self.cfg.get("llm", {})
        llm_model = llm_cfg.get("model", "deepseek-chat")
        llm_enable = "🟢 启用" if self.llm.enable else "🔴 停用"

        status_text = (
            "📊 **Obsidian 笔记助手系统状态**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🟢 **服务状态**: 守护运行中 (端口: {self.port})\n"
            f"🤖 **大模型引擎**: `{llm_model}` ({llm_enable})\n"
            f"🍪 **知乎全文解析**: {'🟢 已就绪' if self.crawler.zhihu_cookie else '⚪ 未配置凭据 (降级模式)'}\n\n"
            "📚 **收件箱数据库统计**:\n"
            f"• 累计收录笔记: **{total}** 条\n"
            f"• 待同步落盘: **{unsynced}** 条\n"
            f"• 已同步至本地: **{synced}** 条\n\n"
            f"📄 **最近收录笔记**: {latest_info}\n\n"
            "💡 发送 `/help` 查看操作指南；发送 `/llm <问题>` 即可继续追问最近一篇笔记！"
        )
        self._reply_user(msg.from_user, status_text, is_kf, kfid)
class RequestHandler(BaseHTTPRequestHandler):
    server_instance: WeChatObsidianServer = None

    def _check_auth(self, query_params) -> bool:
        """校验客户端同步请求密钥."""
        secret_param = query_params.get("secret", [""])[0]
        auth_header = self.headers.get("Authorization", "").replace("Bearer ", "").strip()
        expected = self.server_instance.api_secret
        return secret_param == expected or auth_header == expected

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        # 1. 微信接口握手验证 (GET /wechat 或 GET /)
        if parsed.path in ("/wechat", "/obsidian", "/"):
            msg_signature = params.get("msg_signature", [""])[0]
            timestamp = params.get("timestamp", [""])[0]
            nonce = params.get("nonce", [""])[0]
            echostr = params.get("echostr", [""])[0]

            if msg_signature and timestamp and nonce and echostr:
                # 尝试当前 Obsidian 助手
                if self.server_instance.crypt.verify_signature(timestamp, nonce, echostr, msg_signature):
                    try:
                        msg, _ = self.server_instance.crypt.decrypt(echostr)
                        logger.info(f"[Server] 成功响应 Obsidian 助手握手验证")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(msg.encode("utf-8"))
                        return
                    except Exception as e:
                        logger.error(f"[Server] 解密失败: {e}")
                for route in self.server_instance.gateway_routes:
                    if route["crypt"].verify_signature(timestamp, nonce, echostr, msg_signature):
                        try:
                            msg, _ = route["crypt"].decrypt(echostr)
                            logger.info(f"[Gateway] 成功响应 [{route['name']}] 握手验证")
                            self.send_response(200)
                            self.send_header("Content-Type", "text/plain; charset=utf-8")
                            self.end_headers()
                            self.wfile.write(msg.encode("utf-8"))
                            return
                        except Exception:
                            pass
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Invalid signature")
                return

        # 2. Obsidian 插件拉取待同步笔记: GET /api/sync
        if parsed.path == "/api/sync":
            if not self._check_auth(params):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"code": 401, "msg": "Unauthorized"}).encode())
                return

            limit = int(params.get("limit", [50])[0])
            since_id_raw = params.get("since_id", [None])[0]
            since_id = int(since_id_raw) if since_id_raw and since_id_raw.isdigit() else None
            include_synced = params.get("all", ["0"])[0] in ("1", "true", "yes")

            notes = self.server_instance.storage.get_unsynced_notes(
                limit=limit,
                since_id=since_id,
                include_synced=include_synced
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"code": 0, "count": len(notes), "notes": notes}, ensure_ascii=False).encode())
            return

        # 3. 提供图片下载: GET /api/image/<filename>
        if parsed.path.startswith("/api/image/"):
            filename = os.path.basename(parsed.path)
            filepath = os.path.join("data/images", filename)
            if os.path.exists(filepath):
                self.send_response(200)
                mime_type, _ = mimetypes.guess_type(filepath)
                self.send_header("Content-Type", mime_type or "application/octet-stream")
                self.end_headers()
                with open(filepath, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        # 默认返回服务运行状态
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"WeChat Obsidian Sync Server is active.")

    def _forward_command(self, target_url: str, app_name: str, msg):
        """异步将交互指令投递至后端服务并记录返回."""
        if not msg or not msg.content:
            return
        def _post():
            try:
                import requests
                logger.info(f"[Gateway] 转发微信指令至 [{app_name}] -> {target_url}: {msg.content}")
                res = requests.post(target_url, json={"command": msg.content, "from_user": msg.from_user}, timeout=10)
                logger.info(f"[Gateway] [{app_name}] 指令响应状态: {res.status_code}")
            except Exception as e:
                logger.error(f"[Gateway] 转发至 [{app_name}] 异常: {e}")
        self.server_instance.executor.submit(_post)

    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len).decode("utf-8", errors="replace")

        # 1. 微信消息推送回调: POST /wechat 或 POST /
        if parsed.path in ("/wechat", "/obsidian", "/"):
            msg_signature = params.get("msg_signature", [""])[0]
            timestamp = params.get("timestamp", [""])[0]
            nonce = params.get("nonce", [""])[0]

            # 立即回复微信 success
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"success")

            logger.info(f"[Gateway] 收到微信 POST 回调: 报文长度 {len(post_body)} 字节")

            # 候选密钥集合 (优先匹配多应用网关路由，再匹配 Obsidian 笔记助手)
            crypt_candidates = self.server_instance.gateway_routes + [
                {"name": "Obsidian 笔记助手 (1000003)", "port": None, "crypt": self.server_instance.crypt}
            ]

            decrypted_xml = None
            matched_cand = None
            for cand in crypt_candidates:
                try:
                    decrypted_xml = cand["crypt"].decrypt_msg(msg_signature, timestamp, nonce, post_body)
                    matched_cand = cand
                    logger.info(f"[Gateway] 成功使用 [{cand['name']}] 密钥解密微信消息！")
                    break
                except Exception:
                    continue

            if not decrypted_xml:
                logger.error(f"[Gateway] 所有已知应用密钥均无法解密该消息！请检查微信后台 Token 与 EncodingAESKey。body 摘要: {post_body[:100]}...")
                return

            # 解析解密后的 XML 报文
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(decrypted_xml)
                agent_id = (root.findtext("AgentID") or "").strip()
            except Exception:
                agent_id = ""

            msg = MessageParser.parse_xml(decrypted_xml)
            logger.info(f"[Gateway] 报文解析成功: AgentID={agent_id or '未显式标注'}, MsgType={msg.msg_type if msg else 'None'}, Content={msg.content if msg else ''}")

            # 路由分发决策
            if agent_id == "1000002" or (matched_cand and matched_cand.get("port") == 8087):
                self._forward_command("http://127.0.0.1:8087/command", "邮件通知助手", msg)
            elif agent_id == "1000004" or (matched_cand and matched_cand.get("port") == 8085):
                self._forward_command("http://127.0.0.1:8085/command", "社交雷达", msg)
            elif agent_id == "1000005" or (matched_cand and matched_cand.get("port") == 8086):
                self._forward_command("http://127.0.0.1:8086/command", "洞察引擎", msg)
            else:
                # 提交给 Obsidian 笔记助手异步入库处理
                if msg:
                    logger.info(f"[Gateway] 投递给 Obsidian 笔记助手处理: {msg.content[:30]}")
                    self.server_instance._submit_background(self.server_instance._process_message_async, msg)
            return

        # 2. Obsidian 插件确认同步完成: POST /api/sync/ack
        if parsed.path == "/api/sync/ack":
            if not self._check_auth(params):
                self.send_response(401)
                self.end_headers()
                return

            try:
                data = json.loads(post_body)
                ids = data.get("ids", [])
                self.server_instance.storage.mark_as_synced(ids)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"code": 0, "msg": "Ack success", "synced_count": len(ids)}).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"code": 400, "error": str(e)}).encode())
            return

        # 3. 手机快捷指令 / 系统分享直传剪藏: POST /api/clip 或 POST /api/push
        if parsed.path in ("/api/clip", "/api/push"):
            if not self._check_auth(params):
                self.send_response(401)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"code": 401, "msg": "Unauthorized: API secret invalid"}).encode())
                return

            try:
                raw_text = ""
                custom_title = ""
                extra_tags = []
                from_user = "system_share"

                content_type = self.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    try:
                        data = json.loads(post_body)
                        raw_text = (data.get("content") or data.get("text") or data.get("url") or "").strip()
                        custom_title = (data.get("title") or "").strip()
                        extra_tags = data.get("tags") or []
                        from_user = data.get("from_user") or from_user
                    except Exception:
                        raw_text = post_body.strip()
                else:
                    raw_text = post_body.strip()

                if not raw_text:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"code": 400, "msg": "Empty content"}).encode())
                    return

                res = self.server_instance.process_clipped_content(
                    raw_text=raw_text,
                    custom_title=custom_title,
                    extra_tags=extra_tags,
                    from_user=from_user
                )

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "code": 0,
                    "msg": "Success",
                    "note_id": res["note_id"],
                    "title": res["title"],
                    "tldr": res["tldr"],
                    "tags": res["tags"]
                }, ensure_ascii=False).encode())
                return
            except Exception as e:
                logger.error(f"[Clip API] 剪藏处理失败: {e}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"code": 500, "error": str(e)}).encode())
                return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # 简化日志输出
        logger.debug(f"[HTTP] {self.address_string()} - {format % args}")


def run_server():
    server = WeChatObsidianServer("config.yaml")
    RequestHandler.server_instance = server
    httpd = HTTPServer(("0.0.0.0", server.port), RequestHandler)
    logger.info(f"==================================================")
    logger.info(f"微信回调 URL: /wechat")
    logger.info(f"同步 API 接口: /api/sync")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("服务优雅退出")


if __name__ == "__main__":
    run_server()
