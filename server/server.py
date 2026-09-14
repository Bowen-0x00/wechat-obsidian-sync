"""WeChat to Obsidian 云端核心服务 (消息接收解密 + AI 增强 + 同步 REST API)."""

import os
import json
import yaml
import time
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from loguru import logger

from .wxcrypt import WXBizMsgCrypt
from .parser import MessageParser, WeChatMessage
from .crawler import ArticleCrawler
from .llm_enhancer import LLMEnhancer
from .storage import InboxStorage
from .wechat_client import WeComClient


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
        
        compat_token = wc.get("compat_token")
        compat_key = wc.get("compat_aes_key")
        self.compat_crypt = WXBizMsgCrypt(compat_token, compat_key, self.corp_id) if (compat_token and compat_key) else None

        lc = self.cfg.get("llm", {})
        self.llm = LLMEnhancer(
            base_url=lc.get("base_url", ""),
            api_key=lc.get("api_key", ""),
            model=lc.get("model", "deepseek-chat"),
            temperature=float(lc.get("temperature", 0.3)),
            enable=bool(lc.get("enable", True)),
            proxy=lc.get("proxy")
        )

        self.crawler = ArticleCrawler()
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

    def handle_incoming_xml(self, msg_signature: str, timestamp: str, nonce: str, raw_xml: str):
        """同步解密后提交后台异步处理，立即返回 success 避免微信超时重试."""
        try:
            decrypted_xml = self.crypt.decrypt_msg(msg_signature, timestamp, nonce, raw_xml)
            msg = MessageParser.parse_xml(decrypted_xml)
            if msg:
                # 提交异步处理
                self.executor.submit(self._process_message_async, msg)
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

        title = msg.title
        author = ""
        url = msg.url
        raw_content = msg.content
        tldr = ""
        key_points = []
        tags = []
        media_filename = ""

        # 1. 链接/文章类型 (或正文就是一条 URL)
        if msg.msg_type == "link" or (msg.msg_type == "text" and msg.url):
            target_url = msg.url
            logger.info(f"[Server] 抓取网页正文: {target_url}")
            article = self.crawler.crawl(target_url, title_hint=msg.title)
            title = article.title or msg.title or "网页收藏"
            author = article.author
            url = article.url

            # 调用大模型生成 100 字速读和标签
            ai_res = self.llm.summarize_article(title, article.content_text, url)
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
            media_filename=media_filename
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
            media_filename = ""

            # 文本类型
            if msg_type == "text":
                raw_content = m.get("text", {}).get("content", "")
                # 检查是否是粘贴的网页 URL
                urls = MessageParser.URL_PATTERN.findall(raw_content)
                if urls and len(urls) == 1 and (len(raw_content) - len(urls[0])) < 15:
                    url = urls[0]
                    article = self.crawler.crawl(url)
                    title = article.title or "网页收藏"
                    author = article.author
                    ai_res = self.llm.summarize_article(title, article.content_text, url)
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
                ai_res = self.llm.summarize_article(title, article.content_text, url)
                tldr = ai_res.get("tldr", "")
                key_points = ai_res.get("key_points", [])
                tags = ai_res.get("tags", ["#文章收藏"])

            # 图片类型
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
                media_filename=media_filename
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

                # 兼容旧应用配置
                if self.server_instance.compat_crypt and self.server_instance.compat_crypt.verify_signature(timestamp, nonce, echostr, msg_signature):
                    try:
                        msg, _ = self.server_instance.compat_crypt.decrypt(echostr)
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
            notes = self.server_instance.storage.get_unsynced_notes(limit=limit)
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

            # 检查是否是邮件助手 (1000002) 的微信指令消息
            if self.server_instance.compat_crypt and self.server_instance.compat_crypt.verify_signature(timestamp, nonce, post_body, msg_signature):
                try:
                    decrypted_xml = self.server_instance.compat_crypt.decrypt_msg(msg_signature, timestamp, nonce, post_body)
                    msg = MessageParser.parse_xml(decrypted_xml)
                    if msg and msg.content:
                        logger.info(f"[Server] 转发邮件助手微信交互指令 -> http://127.0.0.1:8087/command: {msg.content}")
                        import requests
                        requests.post("http://127.0.0.1:8087/command", json={"command": msg.content, "from_user": msg.from_user}, timeout=3)
                except Exception as e:
                    logger.warning(f"[Server] 转发邮件助手指令异常: {e}")
                return

            # 提交后台解密与处理 (Obsidian 笔记助手)
            self.server_instance.handle_incoming_xml(msg_signature, timestamp, nonce, post_body)
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
