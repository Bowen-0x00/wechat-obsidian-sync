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
                is_synced INTEGER DEFAULT 0,  -- 0: 待同步, 1: 已同步落盘
                synced_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
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
        media_filename: str = ""
    ) -> int:
        """新增一条笔记到收件箱."""
        kp_json = json.dumps(key_points or [], ensure_ascii=False)
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT OR IGNORE INTO inbox_notes 
            (msg_id, msg_type, from_user, create_time, raw_content, title, author, url, tldr, key_points, tags, media_filename, is_synced)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
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
                media_filename
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
            SELECT id, msg_id, msg_type, from_user, create_time, raw_content, title, author, url, tldr, key_points, tags, media_filename, created_at
            FROM inbox_notes
            WHERE is_synced = 0
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
                    "created_at": r["created_at"]
                })
            return notes

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
