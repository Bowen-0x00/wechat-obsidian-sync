"""SQLite 待同步笔记暂存与队列管理模块."""

import os
import json
import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime
from loguru import logger


class InboxStorage:
    """云端笔记收件箱数据库管理器."""

    def __init__(self, db_path: str = "data/inbox.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化表结构."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS inbox_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id TEXT UNIQUE,
                msg_type TEXT NOT NULL,       -- 'text', 'link', 'image', 'file'
                from_user TEXT,
                create_time INTEGER,          -- 微信时间戳
                raw_content TEXT,             -- 原始正文
                title TEXT,                   -- 标题 / 文章名 / 文件名
                author TEXT,                  -- 作者
                url TEXT,                     -- 网页链接
                tldr TEXT,                    -- AI 生成的 100 字速读
                key_points TEXT,              -- AI 核心要点 (JSON 字符串)
                tags TEXT,                    -- 标签列表 (JSON 字符串)
                media_filename TEXT,          -- 图片或文件本地文件名
                content_markdown TEXT,        -- 文章转换后的 Markdown 正文
                image_urls TEXT,              -- 文章包含的所有图片链接 (JSON 字符串)
                is_synced INTEGER DEFAULT 0,  -- 0: 待同步, 1: 已同步落盘
                synced_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS note_chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER NOT NULL,
                from_user TEXT,
                role TEXT NOT NULL,           -- 'user', 'assistant'
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (note_id) REFERENCES inbox_notes(id)
            )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_note_id ON note_chat_history(note_id)")
            # 自动迁移旧数据库，添加 content_markdown 和 image_urls 字段
            try:
                cursor.execute("ALTER TABLE inbox_notes ADD COLUMN content_markdown TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE inbox_notes ADD COLUMN image_urls TEXT")
            except sqlite3.OperationalError:
                pass
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inbox_synced ON inbox_notes(is_synced)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inbox_msg_id ON inbox_notes(msg_id)")
            conn.commit()
            logger.debug(f"[Storage] 笔记收件箱数据库就绪: {self.db_path}")

    def is_msg_processed(self, msg_id: str) -> bool:
        """检查消息是否已处理记录过."""
        if not msg_id:
            return False
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM inbox_notes WHERE msg_id = ?", (msg_id,))
            return cur.fetchone() is not None

    def add_note(
        self,
        msg_id: str,
        msg_type: str,
        from_user: str,
        create_time: int,
        raw_content: str = "",
        title: str = "",
        author: str = "",
        url: str = "",
        tldr: str = "",
        key_points: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        media_filename: str = "",
        content_markdown: str = "",
        image_urls: Optional[List[str]] = None
    ) -> int:
        """新增一条笔记到收件箱."""
        kp_json = json.dumps(key_points or [], ensure_ascii=False)
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        img_json = json.dumps(image_urls or [], ensure_ascii=False)
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT OR IGNORE INTO inbox_notes 
            (msg_id, msg_type, from_user, create_time, raw_content, title, author, url, tldr, key_points, tags, media_filename, content_markdown, image_urls, is_synced)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                msg_id,
                msg_type,
                from_user,
                create_time,
                raw_content,
                title,
                author,
                url,
                tldr,
                kp_json,
                tags_json,
                media_filename,
                content_markdown,
                img_json
            ))
            conn.commit()
            last_id = cur.lastrowid
            logger.info(f"[Storage] 笔记入库成功 [ID {last_id}]: {title or raw_content[:25]}")
            return last_id

    def get_unsynced_notes(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取尚未同步到本地 Obsidian 的笔记列表."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
            SELECT id, msg_id, msg_type, from_user, create_time, raw_content, title, author, url, tldr, key_points, tags, media_filename, content_markdown, image_urls, created_at
            FROM inbox_notes
            ORDER BY id ASC
            LIMIT ?
            """, (limit,))
            rows = cur.fetchall()

            notes = []
            for r in rows:
                notes.append({
                    "id": r["id"],
                    "msg_id": r["msg_id"],
                    "msg_type": r["msg_type"],
                    "from_user": r["from_user"],
                    "create_time": r["create_time"],
                    "raw_content": r["raw_content"] or "",
                    "title": r["title"] or "",
                    "author": r["author"] or "",
                    "url": r["url"] or "",
                    "tldr": r["tldr"] or "",
                    "key_points": json.loads(r["key_points"] or "[]"),
                    "tags": json.loads(r["tags"] or "[]"),
                    "media_filename": r["media_filename"] or "",
                    "content_markdown": r["content_markdown"] or "",
                    "image_urls": json.loads(r["image_urls"] or "[]"),
                    "created_at": r["created_at"]
                })
            return notes

    def get_note_by_target(self, target: str, from_user: str = "") -> Optional[Dict[str, Any]]:
        """
        根据标识查找特定笔记:
        1. 'last' 或空 -> 用户最近一篇笔记（若未指定用户则取全局最新一篇）
        2. 数字 -> 直接按 note_id 查找
        3. 8位/12位时间字符串（如 20260920, 202609202157）-> 匹配对应时间段创建的笔记
        """
        target = target.strip().lower()
        with self._get_connection() as conn:
            cur = conn.cursor()
            row = None

            # 1. last
            if target in ("last", "", "latest"):
                if from_user:
                    cur.execute("""
                    SELECT * FROM inbox_notes 
                    WHERE from_user = ? 
                    ORDER BY id DESC LIMIT 1
                    """, (from_user,))
                    row = cur.fetchone()
                if not row:
                    cur.execute("SELECT * FROM inbox_notes ORDER BY id DESC LIMIT 1")
                    row = cur.fetchone()

            # 2. 纯数字 ID
            elif target.isdigit() and len(target) < 8:
                cur.execute("SELECT * FROM inbox_notes WHERE id = ?", (int(target),))
                row = cur.fetchone()

            # 3. 日期或时间戳匹配 (如 20260920 或 202609202157 或 2026-09-20)
            else:
                clean_dt = target.replace("-", "").replace(":", "").replace(" ", "").replace("_", "")
                if len(clean_dt) == 8: # YYYYMMDD
                    date_pattern = f"{clean_dt[:4]}-{clean_dt[4:6]}-{clean_dt[6:8]}%"
                    cur.execute("""
                    SELECT * FROM inbox_notes 
                    WHERE created_at LIKE ? 
                    ORDER BY id DESC LIMIT 1
                    """, (date_pattern,))
                    row = cur.fetchone()
                elif len(clean_dt) >= 12: # YYYYMMDDHHMM
                    date_pattern = f"{clean_dt[:4]}-{clean_dt[4:6]}-{clean_dt[6:8]} {clean_dt[8:10]}:{clean_dt[10:12]}%"
                    cur.execute("""
                    SELECT * FROM inbox_notes 
                    WHERE created_at LIKE ? 
                    ORDER BY id DESC LIMIT 1
                    """, (date_pattern,))
                    row = cur.fetchone()
                else:
                    # 模糊标题匹配
                    cur.execute("""
                    SELECT * FROM inbox_notes 
                    WHERE title LIKE ? OR raw_content LIKE ? 
                    ORDER BY id DESC LIMIT 1
                    """, (f"%{target}%", f"%{target}%"))
                    row = cur.fetchone()

            if not row:
                return None

            return {
                "id": row["id"],
                "msg_id": row["msg_id"],
                "msg_type": row["msg_type"],
                "from_user": row["from_user"],
                "create_time": row["create_time"],
                "raw_content": row["raw_content"] or "",
                "title": row["title"] or "",
                "author": row["author"] or "",
                "url": row["url"] or "",
                "tldr": row["tldr"] or "",
                "key_points": json.loads(row["key_points"] or "[]"),
                "tags": json.loads(row["tags"] or "[]"),
                "media_filename": row["media_filename"] or "",
                "content_markdown": row["content_markdown"] or "",
                "image_urls": json.loads(row["image_urls"] or "[]"),
                "created_at": row["created_at"]
            }

    def add_chat_message(self, note_id: int, from_user: str, role: str, content: str):
        """记录追问对话历史."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO note_chat_history (note_id, from_user, role, content)
            VALUES (?, ?, ?, ?)
            """, (note_id, from_user, role, content))
            conn.commit()

    def get_chat_history(self, note_id: int, limit: int = 10) -> List[Dict[str, str]]:
        """获取指定笔记的追问历史."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
            SELECT role, content FROM note_chat_history
            WHERE note_id = ?
            ORDER BY id ASC
            LIMIT ?
            """, (note_id, limit))
            rows = cur.fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in rows]

    def mark_as_synced(self, note_ids: List[int]):
        """将指定的笔记标记为已同步."""
        if not note_ids:
            return
        with self._get_connection() as conn:
            cur = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            placeholders = ",".join(["?"] * len(note_ids))
            cur.execute(f"""
            UPDATE inbox_notes
            SET is_synced = 1, synced_at = ?
            WHERE id IN ({placeholders})
            """, [now] + note_ids)
            conn.commit()
            logger.info(f"[Storage] 成功标记 {len(note_ids)} 篇笔记为已同步")
