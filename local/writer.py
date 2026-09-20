"""Obsidian 本地文件落盘写入引擎 (线程安全追加 + 附件自动下载)."""

import os
import re
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional
from filelock import FileLock
from loguru import logger


class ObsidianWriter:
    """负责将云端同步的笔记以标准 Markdown 追加写入指定 Obsidian Vault 目录."""

    def __init__(
        self,
        vault_path: str = "./vault",
        archive_mode: str = "daily",
        daily_folder: str = "Daily",
        inbox_file: str = "Inbox.md",
        attachment_folder: str = "attachments",
        server_base_url: str = "http://your-server-domain.com",
        api_secret: str = ""
    ):
        self.vault_path = os.path.abspath(vault_path)
        self.archive_mode = archive_mode
        self.daily_folder = daily_folder
        self.inbox_file = inbox_file
        self.attachment_folder = attachment_folder
        self.server_base_url = server_base_url.rstrip("/")
        self.api_secret = api_secret

        # 锁文件路径 (避免多线程或多实例并发写入同一文件冲突)
        self.lock_file = os.path.join(self.vault_path, ".obsidian_wechat_sync.lock")

    def get_target_file_path(self, timestamp: int) -> str:
        """根据归档规则计算目标 Markdown 文件的绝对路径."""
        dt = datetime.fromtimestamp(timestamp) if timestamp else datetime.now()
        date_str = dt.strftime("%Y-%m-%d")

        if self.archive_mode == "daily":
            # 模式 1: 按日归档，如 10-Journal&Planning/13-note/2026-09-14/同步助手_2026-09-14.md
            folder_dir = os.path.join(self.vault_path, self.daily_folder, date_str)
            os.makedirs(folder_dir, exist_ok=True)
            return os.path.join(folder_dir, f"同步助手_{date_str}.md")
        else:
            # 模式 2: 单文件集中归档，如 00-Inbox/Inbox.md
            target_path = os.path.join(self.vault_path, self.inbox_file)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            return target_path

    def download_image_to_vault(self, media_filename_or_url: str) -> Optional[str]:
        """下载图片（云端附件或文章外链图片）到 Vault 附件目录，返回 Obsidian 引用路径."""
        if not media_filename_or_url:
            return None

        images_dir = os.path.join(self.vault_path, self.attachment_folder)
        os.makedirs(images_dir, exist_ok=True)

        # 判断是云端本地文件名还是外部图片链接
        if media_filename_or_url.startswith(("http://", "https://")):
            import hashlib
            # 生成稳定的本地文件名，并尽量保留扩展名
            url_hash = hashlib.md5(media_filename_or_url.encode("utf-8")).hexdigest()[:12]
            ext = ".png"
            if ".jpg" in media_filename_or_url or "wx_fmt=jpeg" in media_filename_or_url:
                ext = ".jpg"
            elif ".gif" in media_filename_or_url or "wx_fmt=gif" in media_filename_or_url:
                ext = ".gif"
            elif ".webp" in media_filename_or_url or "wx_fmt=webp" in media_filename_or_url:
                ext = ".webp"
            filename = f"art_img_{url_hash}{ext}"
            img_url = media_filename_or_url
        else:
            filename = media_filename_or_url
            img_url = f"{self.server_base_url}/api/image/{filename}"

        local_dest = os.path.join(images_dir, filename)
        if not os.path.exists(local_dest):
            try:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
                        "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.48"
                    ),
                    "Referer": "https://mp.weixin.qq.com/"
                }
                r = requests.get(img_url, headers=headers, timeout=15)
                if r.status_code == 200:
                    with open(local_dest, "wb") as f:
                        f.write(r.content)
                    logger.info(f"[Writer] 附件/内嵌图片下载成功: {filename}")
                else:
                    logger.warning(f"[Writer] 图片下载失败 (HTTP {r.status_code}): {img_url}")
                    return None
            except Exception as e:
                logger.error(f"[Writer] 下载附件异常: {e}")
                return None

        vault_rel_path = f"{self.attachment_folder}/{filename}".replace("\\", "/")
        return f"![[{vault_rel_path}]]"
    def format_note_markdown(self, note: Dict[str, Any]) -> str:
        """将笔记字典格式化为规范的 Markdown 片段."""
        create_time = note.get("create_time") or int(datetime.now().timestamp())
        dt = datetime.fromtimestamp(create_time)
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        msg_type = note.get("msg_type", "text")
        title = note.get("title", "")
        author = note.get("author", "")
        url = note.get("url", "")
        raw_content = note.get("raw_content", "")
        tldr = note.get("tldr", "")
        key_points = note.get("key_points", [])
        tags = note.get("tags", [])
        media_filename = note.get("media_filename", "")
        content_markdown = note.get("content_markdown", "")
        image_urls = note.get("image_urls", [])
        tags_str = " ".join(tags) if tags else ""

        blocks = []
        blocks.append("\n---")

        # 1. 链接/文章类型
        if msg_type == "link" or url:
            heading = f"#### {title or '网页收藏'}"
            blocks.append(heading)
            blocks.append(f"## 📅 {time_str}")
            if url:
                blocks.append(f"[{title}]({url})")
            if author:
                blocks.append(f"**作者**: {author}")

            # AI 核心速读
            if tldr:
                blocks.append(f"> [!abstract] 💡 AI 核心速读 (100字)\n> {tldr}")
            
            if key_points:
                kp_lines = "\n".join([f"> - {p}" for p in key_points])
                blocks.append(f"> [!tip] 📌 核心要点\n{kp_lines}")

            if tags_str:
                blocks.append(f"\n{tags_str}")

            if media_filename:
                img_link = self.download_image_to_vault(media_filename)
                if img_link:
                    blocks.append(f"\n{img_link}")

            # 渲染文章完整正文与图片
            if content_markdown:
                # 将文章中的外链图片下载到本地并替换为 Obsidian 内部引用 ![[...]]
                processed_md = content_markdown
                img_pattern = re.compile(r'!\[(.*?)\]\((https?://[^\s\)]+)\)')
                found_imgs = img_pattern.findall(processed_md)
                for alt, img_src in found_imgs:
                    local_obsidian_img = self.download_image_to_vault(img_src)
                    if local_obsidian_img:
                        processed_md = processed_md.replace(f"![{alt}]({img_src})", local_obsidian_img)

                blocks.append(f"\n### 📖 正文内容\n\n{processed_md}")
            elif raw_content and raw_content != url:
                blocks.append(f"\n> {raw_content.strip()}")
        # 2. 图片类型
        elif msg_type == "image":
            blocks.append("#### 🖼️ 图片备忘")
            blocks.append(f"## 📅 {time_str}")
            if media_filename:
                img_link = self.download_image_to_vault(media_filename)
                if img_link:
                    blocks.append(img_link)
            if tags_str:
                blocks.append(tags_str)

        # 3. 纯文本闪念/待办
        else:
            blocks.append(f"## 📅 {time_str}")
            blocks.append(raw_content.strip())
            if tags_str:
                blocks.append(f"\n{tags_str}")

        # 隐形标记，避免重复合并
        msg_id = note.get("msg_id", "")
        if msg_id:
            blocks.append(f"<!--wx:{msg_id}-->")

        return "\n".join(blocks) + "\n"

    def append_note(self, note: Dict[str, Any]) -> bool:
        """线程安全地将笔记追加写入目标文件."""
        target_file = self.get_target_file_path(note.get("create_time", 0))
        md_snippet = self.format_note_markdown(note)

        # 使用文件互斥锁，确保多进程/多线程写入时不产生数据竞争破坏
        lock = FileLock(self.lock_file, timeout=10)
        try:
            with lock:
                # 检查文件中是否已存在该 msg_id，严防重复写入
                msg_id = note.get("msg_id", "")
                if os.path.exists(target_file) and msg_id:
                    with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                        if f"<!--wx:{msg_id}-->" in f.read():
                            logger.debug(f"[Writer] 笔记已存在于目标文件中，跳过: {msg_id}")
                            return True

                # 若文件尚不存在，写入初始 FrontMatter 标头
                if not os.path.exists(target_file) or os.path.getsize(target_file) == 0:
                    with open(target_file, "w", encoding="utf-8") as f:
                        f.write("---\ntags: [微信随手记]\n---\n")

                with open(target_file, "a", encoding="utf-8") as f:
                    f.write(md_snippet)

                logger.info(f"[Writer] 成功落盘写入: {os.path.basename(target_file)}")
                return True
        except Exception as e:
            logger.error(f"[Writer] 写入文件失败 ({target_file}): {e}")
            return False
