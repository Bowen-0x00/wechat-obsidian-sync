"""
统一多应用数据看板与交互服务 (Dashboard Service).
汇聚管理 4 大企业微信应用数据：
1. 微信笔记助手 (wechat_obsidian) -> inbox.db
2. 前沿洞察引擎 (insight_extractor) -> insights.db
3. 社交前沿雷达 (social_radar) -> social_radar.db
4. 邮件与学术助手 (mail_assist) -> mail_assist.db
"""

import os
import sys
import json
import time
import hmac
import hashlib
import sqlite3
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from loguru import logger


class DashboardService:
    """看板数据与会话管理器."""

    def __init__(self, config: Dict[str, Any], base_dir: Optional[str] = None):
        self.config = config
        self.base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 1. 鉴权 Secret 配置
        self.api_secret = (
            config.get("api_secret") or 
            config.get("server", {}).get("api_secret") or 
            config.get("sync", {}).get("api_secret") or 
            "wechat_obsidian_secret_key"
        )
        self.salt = "wehub_dashboard_secure_salt_2026"

        # 2. 定位 4 大数据库路径 (自适应本地与阿里云环境)
        self.db_paths = self._resolve_db_paths()
        logger.info(f"[Dashboard] 数据库挂载状态: {self.db_paths}")

    def _resolve_db_paths(self) -> Dict[str, str]:
        """自适应解析 4 个数据库的绝对路径."""
        candidates = {
            "notes": [
                os.path.join(self.base_dir, "data", "inbox.db"),
                "/root/wechat_obsidian/data/inbox.db",
                "D:/Project/wechat_obsidian/data/inbox.db"
            ],
            "insights": [
                os.path.join(os.path.dirname(self.base_dir), "insight_extractor", "data", "insights.db"),
                "/root/insight_extractor/data/insights.db",
                "D:/Project/insight_extractor/data/insights.db"
            ],
            "radar": [
                os.path.join(os.path.dirname(self.base_dir), "social_radar", "data", "social_radar.db"),
                "/root/social_radar/data/social_radar.db",
                "D:/Project/social_radar/data/social_radar.db"
            ],
            "mail": [
                os.path.join(os.path.dirname(self.base_dir), "mail_assist", "data", "mail_assist.db"),
                "/root/mail_assist/data/mail_assist.db",
                "D:/Project/mail_assist/data/mail_assist.db"
            ]
        }

        resolved = {}
        for app, paths in candidates.items():
            for p in paths:
                if os.path.exists(p):
                    resolved[app] = os.path.abspath(p)
                    break
            if app not in resolved:
                # 默认落盘 fallback
                resolved[app] = os.path.abspath(paths[0])
        return resolved

    def _get_conn(self, app_key: str) -> Optional[sqlite3.Connection]:
        """获取指定数据库连接."""
        path = self.db_paths.get(app_key)
        if not path or not os.path.exists(path):
            return None
        try:
            conn = sqlite3.connect(path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            logger.warning(f"[Dashboard] 连接数据库 {app_key} ({path}) 失败: {e}")
            return None

    # =========================================================================
    # 鉴权机制：免爬虫防护 + 长期 Session Token
    # =========================================================================
    def generate_token(self, secret: str) -> str:
        """根据 Secret 生成签名 Token."""
        msg = f"{secret}:{self.salt}".encode("utf-8")
        return hmac.new(self.salt.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    def verify_auth(self, token_or_secret: str) -> bool:
        """校验 Token 或 Secret."""
        if not token_or_secret:
            return False
        clean = token_or_secret.strip()
        if clean.startswith("Bearer "):
            clean = clean[7:].strip()
        # 1. 允许直接输入 api_secret
        if clean == self.api_secret:
            return True
        # 2. 校验 HMAC Token
        expected_token = self.generate_token(self.api_secret)
        return hmac.compare_digest(clean, expected_token)

    # =========================================================================
    # 数据总览与统计 (Stats)
    # =========================================================================
    def get_stats(self) -> Dict[str, Any]:
        """汇总 4 大应用的统计指标."""
        stats = {
            "notes": {"total": 0, "unsynced": 0, "today": 0},
            "insights": {"total": 0, "high_score": 0, "today": 0},
            "radar": {"total": 0, "high_value": 0, "zhihu": 0, "twitter": 0},
            "mail": {"emails": 0, "papers": 0, "tasks": 0}
        }
        today_prefix = datetime.now().strftime("%Y-%m-%d")

        # 1. 微信随手笔记
        conn = self._get_conn("notes")
        if conn:
            with conn:
                try:
                    stats["notes"]["total"] = conn.execute("SELECT count(*) FROM inbox_notes").fetchone()[0]
                    stats["notes"]["unsynced"] = conn.execute("SELECT count(*) FROM inbox_notes WHERE is_synced = 0").fetchone()[0]
                    stats["notes"]["today"] = conn.execute(
                        "SELECT count(*) FROM inbox_notes WHERE created_at LIKE ?", (f"{today_prefix}%",)
                    ).fetchone()[0]
                except Exception as e:
                    logger.debug(f"[Dashboard] 统计 notes 异常: {e}")

        # 2. 前沿学术洞察
        conn = self._get_conn("insights")
        if conn:
            with conn:
                try:
                    stats["insights"]["total"] = conn.execute("SELECT count(*) FROM archived_insights").fetchone()[0]
                    stats["insights"]["high_score"] = conn.execute("SELECT count(*) FROM archived_insights WHERE depth_score >= 85").fetchone()[0]
                    stats["insights"]["today"] = conn.execute(
                        "SELECT count(*) FROM archived_insights WHERE created_at LIKE ?", (f"{today_prefix}%",)
                    ).fetchone()[0]
                except Exception as e:
                    logger.debug(f"[Dashboard] 统计 insights 异常: {e}")

        # 3. 社交雷达
        conn = self._get_conn("radar")
        if conn:
            with conn:
                try:
                    stats["radar"]["total"] = conn.execute("SELECT count(*) FROM processed_items").fetchone()[0]
                    stats["radar"]["high_value"] = conn.execute("SELECT count(*) FROM processed_items WHERE value_score >= 70").fetchone()[0]
                    stats["radar"]["zhihu"] = conn.execute("SELECT count(*) FROM processed_items WHERE platform = 'zhihu'").fetchone()[0]
                    stats["radar"]["twitter"] = conn.execute("SELECT count(*) FROM processed_items WHERE platform = 'twitter'").fetchone()[0]
                except Exception as e:
                    logger.debug(f"[Dashboard] 统计 radar 异常: {e}")

        # 4. 邮件与学术助手
        conn = self._get_conn("mail")
        if conn:
            with conn:
                try:
                    stats["mail"]["emails"] = conn.execute("SELECT count(*) FROM processed_emails").fetchone()[0]
                    stats["mail"]["papers"] = conn.execute("SELECT count(*) FROM processed_papers").fetchone()[0]
                    stats["mail"]["tasks"] = conn.execute("SELECT count(*) FROM processed_emails WHERE category = 'task'").fetchone()[0]
                except Exception as e:
                    logger.debug(f"[Dashboard] 统计 mail 异常: {e}")

        return stats

    # =========================================================================
    # 多源数据查询与检索 (Unified Items Query)
    # =========================================================================
    def get_items(
        self,
        app: str = "all",
        q: str = "",
        min_score: int = 0,
        days: int = 0,
        limit: int = 40,
        offset: int = 0
    ) -> Dict[str, Any]:
        """统一检索各应用的数据条目."""
        items: List[Dict[str, Any]] = []
        cutoff_str = ""
        if days > 0:
            cutoff = datetime.now() - timedelta(days=days)
            cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        # 1. 微信笔记 (app == 'all' or app == 'notes')
        if app in ("all", "notes"):
            items.extend(self._fetch_notes(q, cutoff_str, limit, offset))

        # 2. 洞察引擎 (app == 'all' or app == 'insights')
        if app in ("all", "insights"):
            items.extend(self._fetch_insights(q, min_score, cutoff_str, limit, offset))

        # 3. 社交雷达 (app == 'all' or app == 'radar')
        if app in ("all", "radar"):
            items.extend(self._fetch_radar(q, min_score, cutoff_str, limit, offset))

        # 4. 邮件与论文 (app in ('all', 'mail', 'papers'))
        if app in ("all", "mail"):
            items.extend(self._fetch_emails(q, cutoff_str, limit, offset))
        if app in ("all", "papers"):
            items.extend(self._fetch_papers(q, min_score, cutoff_str, limit, offset))

        # 统一按时间降序排序
        items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)

        total_count = len(items)
        paginated = items[offset : offset + limit] if app == "all" else items[:limit]

        return {
            "total": total_count,
            "items": paginated,
            "limit": limit,
            "offset": offset
        }

    def _fetch_notes(self, q: str, cutoff: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        conn = self._get_conn("notes")
        if not conn:
            return []
        items = []
        try:
            with conn:
                sql = "SELECT id, msg_id, msg_type, from_user, title, author, url, tldr, key_points, tags, media_filename, content_markdown, is_synced, created_at FROM inbox_notes WHERE 1=1"
                params = []
                if cutoff:
                    sql += " AND created_at >= ?"
                    params.append(cutoff)
                if q:
                    sql += " AND (title LIKE ? OR tldr LIKE ? OR content_markdown LIKE ?)"
                    params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
                sql += " ORDER BY id DESC LIMIT ?"
                params.append(limit + offset)

                for r in conn.execute(sql, params).fetchall():
                    tags = []
                    try:
                        tags = json.loads(r["tags"]) if r["tags"] else []
                    except Exception:
                        pass
                    # 查询对话轮数
                    chat_cnt = 0
                    try:
                        chat_cnt = conn.execute("SELECT count(*) FROM chat_history WHERE note_id = ?", (r["id"],)).fetchone()[0]
                    except Exception:
                        pass

                    items.append({
                        "id": f"note_{r['id']}",
                        "raw_id": str(r["id"]),
                        "app": "notes",
                        "app_name": "微信笔记助手",
                        "platform": "wechat",
                        "title": r["title"] or f"微信随手记录 #{r['id']}",
                        "author": r["author"] or r["from_user"] or "微信用户",
                        "url": r["url"] or "",
                        "score": 0,
                        "summary": r["tldr"] or (r["content_markdown"][:160] if r["content_markdown"] else "无正文"),
                        "content": r["content_markdown"] or r["tldr"] or "",
                        "tags": tags,
                        "created_at": r["created_at"] or "",
                        "chat_count": chat_cnt,
                        "extra": {
                            "msg_type": r["msg_type"],
                            "is_synced": r["is_synced"],
                            "media_filename": r["media_filename"]
                        }
                    })
        except Exception as e:
            logger.error(f"[Dashboard] 查询 notes 失败: {e}")
        return items

    def _fetch_insights(self, q: str, min_score: int, cutoff: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        conn = self._get_conn("insights")
        if not conn:
            return []
        items = []
        try:
            with conn:
                sql = "SELECT id, title, insight_type, depth_score, core_insight, philosophical_takeaway, cross_sources, research_directions, created_at FROM archived_insights WHERE 1=1"
                params = []
                if min_score > 0:
                    sql += " AND depth_score >= ?"
                    params.append(min_score)
                if cutoff:
                    sql += " AND created_at >= ?"
                    params.append(cutoff)
                if q:
                    sql += " AND (title LIKE ? OR core_insight LIKE ? OR philosophical_takeaway LIKE ?)"
                    params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
                sql += " ORDER BY id DESC LIMIT ?"
                params.append(limit + offset)

                for r in conn.execute(sql, params).fetchall():
                    # 组装完整的 Markdown 内容
                    cross_srcs = []
                    try:
                        cross_srcs = json.loads(r["cross_sources"]) if r["cross_sources"] else []
                    except Exception:
                        pass
                    dirs = []
                    try:
                        dirs = json.loads(r["research_directions"]) if r["research_directions"] else []
                    except Exception:
                        pass

                    content_parts = [
                        f"### 💡 核心见解与底层突破\n\n{r['core_insight']}",
                        f"### 🎯 哲学与架构启示\n\n{r['philosophical_takeaway']}"
                    ]
                    if dirs:
                        content_parts.append("### 🔬 建议推演与探索方向\n\n" + "\n".join([f"- {d}" for d in dirs]))
                    if cross_srcs:
                        content_parts.append("### 📚 触发碰撞的跨源素材/论文\n\n" + "\n".join([f"- {s}" for s in cross_srcs]))

                    # 查询对话轮数
                    chat_cnt = 0
                    try:
                        chat_cnt = conn.execute("SELECT count(*) FROM insight_chat_history WHERE insight_id = ?", (r["id"],)).fetchone()[0]
                    except Exception:
                        pass

                    items.append({
                        "id": f"insight_{r['id']}",
                        "raw_id": str(r["id"]),
                        "app": "insights",
                        "app_name": "前沿洞察引擎",
                        "platform": "ai_insight",
                        "title": r["title"],
                        "author": "InsightEngine",
                        "url": "",
                        "score": r["depth_score"],
                        "summary": r["core_insight"][:180] + "..." if len(r["core_insight"]) > 180 else r["core_insight"],
                        "content": "\n\n".join(content_parts),
                        "tags": [f"#{r['insight_type']}", f"#{r['depth_score']}分"],
                        "created_at": r["created_at"] or "",
                        "chat_count": chat_cnt,
                        "extra": {
                            "insight_type": r["insight_type"],
                            "cross_sources": cross_srcs,
                            "directions": dirs
                        }
                    })
        except Exception as e:
            logger.error(f"[Dashboard] 查询 insights 失败: {e}")
        return items

    def _fetch_radar(self, q: str, min_score: int, cutoff: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        conn = self._get_conn("radar")
        if not conn:
            return []
        items = []
        try:
            with conn:
                sql = "SELECT item_id, platform, item_type, title, author, url, value_score, is_notified, core_insight, created_at FROM processed_items WHERE 1=1"
                params = []
                if min_score > 0:
                    sql += " AND value_score >= ?"
                    params.append(min_score)
                if cutoff:
                    sql += " AND created_at >= ?"
                    params.append(cutoff)
                if q:
                    sql += " AND (title LIKE ? OR core_insight LIKE ? OR author LIKE ?)"
                    params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
                sql += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit + offset)

                for r in conn.execute(sql, params).fetchall():
                    chat_cnt = 0
                    try:
                        chat_cnt = conn.execute("SELECT count(*) FROM radar_chat_history WHERE item_id = ?", (r["item_id"],)).fetchone()[0]
                    except Exception:
                        pass

                    items.append({
                        "id": f"radar_{r['item_id']}",
                        "raw_id": str(r["item_id"]),
                        "app": "radar",
                        "app_name": "社交前沿雷达",
                        "platform": r["platform"] or "zhihu",
                        "title": r["title"],
                        "author": r["author"] or "网络动态",
                        "url": r["url"] or "",
                        "score": r["value_score"] or 0,
                        "summary": r["core_insight"] or "社交前沿高价值动态监测",
                        "content": f"### 社交动态核心价值与洞察\n\n{r['core_insight']}\n\n- 平台信源: {r['platform']}\n- 动作类型: {r['item_type']}\n- 原始链接: {r['url']}",
                        "tags": [f"#{r['platform']}", f"#{r['value_score']}分"],
                        "created_at": r["created_at"] or "",
                        "chat_count": chat_cnt,
                        "extra": {
                            "item_type": r["item_type"]
                        }
                    })
        except Exception as e:
            logger.error(f"[Dashboard] 查询 radar 失败: {e}")
        return items

    def _fetch_emails(self, q: str, cutoff: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        conn = self._get_conn("mail")
        if not conn:
            return []
        items = []
        try:
            with conn:
                sql = "SELECT message_id, mailbox_name, subject, sender, date_str, category, importance_score, is_notified, summary, processed_at FROM processed_emails WHERE 1=1"
                params = []
                if cutoff:
                    sql += " AND processed_at >= ?"
                    params.append(cutoff)
                if q:
                    sql += " AND (subject LIKE ? OR summary LIKE ? OR sender LIKE ?)"
                    params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
                sql += " ORDER BY processed_at DESC LIMIT ?"
                params.append(limit + offset)

                for r in conn.execute(sql, params).fetchall():
                    chat_cnt = 0
                    try:
                        chat_cnt = conn.execute("SELECT count(*) FROM email_chat_history WHERE email_id = ?", (r["message_id"],)).fetchone()[0]
                    except Exception:
                        pass

                    # importance_score 1-5 映射为百分制
                    score = (r["importance_score"] or 1) * 20

                    items.append({
                        "id": f"mail_{r['message_id']}",
                        "raw_id": str(r["message_id"]),
                        "app": "mail",
                        "app_name": "邮件助手",
                        "platform": "email",
                        "title": r["subject"] or "未命名邮件",
                        "author": r["sender"] or r["mailbox_name"],
                        "url": "",
                        "score": score,
                        "summary": r["summary"] or "邮件正文摘要",
                        "content": f"### 📬 邮件智能解析与任务行动项\n\n{r['summary']}\n\n- 发件人: {r['sender']}\n- 邮箱: {r['mailbox_name']}\n- 类型分类: {r['category']}\n- 重要度级别: {r['importance_score']} 星",
                        "tags": [f"#{r['category']}", f"{r['importance_score']}★"],
                        "created_at": r["processed_at"] or r["date_str"] or "",
                        "chat_count": chat_cnt,
                        "extra": {
                            "mailbox": r["mailbox_name"],
                            "category": r["category"]
                        }
                    })
        except Exception as e:
            logger.error(f"[Dashboard] 查询 emails 失败: {e}")
        return items

    def _fetch_papers(self, q: str, min_score: int, cutoff: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        conn = self._get_conn("mail")
        if not conn:
            return []
        items = []
        try:
            with conn:
                sql = "SELECT paper_id, title, authors, source, abstract, url, pdf_url, relevance_score, analysis, created_at FROM processed_papers WHERE 1=1"
                params = []
                if min_score > 0:
                    sql += " AND relevance_score >= ?"
                    params.append(min_score)
                if cutoff:
                    sql += " AND created_at >= ?"
                    params.append(cutoff)
                if q:
                    sql += " AND (title LIKE ? OR abstract LIKE ? OR analysis LIKE ? OR authors LIKE ?)"
                    params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])
                sql += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit + offset)

                for r in conn.execute(sql, params).fetchall():
                    content_parts = [
                        f"### 📄 论文深度剖析与启发\n\n{r['analysis'] or '无详细剖析'}",
                        f"### 📝 论文摘要 (Abstract)\n\n{r['abstract'] or '无摘要'}"
                    ]
                    if r["url"] or r["pdf_url"]:
                        content_parts.append(f"### 🔗 原文链接\n\n- 论文主页: {r['url'] or '无'}\n- PDF 直达: {r['pdf_url'] or '无'}")

                    items.append({
                        "id": f"paper_{r['paper_id']}",
                        "raw_id": str(r["paper_id"]),
                        "app": "papers",
                        "app_name": "学术论文追踪",
                        "platform": "arxiv",
                        "title": r["title"],
                        "author": r["authors"] or r["source"] or "arXiv",
                        "url": r["url"] or r["pdf_url"] or "",
                        "score": r["relevance_score"] or 0,
                        "summary": r["analysis"][:180] + "..." if r["analysis"] and len(r["analysis"]) > 180 else (r["abstract"][:180] if r["abstract"] else ""),
                        "content": "\n\n".join(content_parts),
                        "tags": ["#学术前沿", f"#{r['relevance_score']}分"],
                        "created_at": r["created_at"] or "",
                        "chat_count": 0,
                        "extra": {
                            "pdf_url": r["pdf_url"],
                            "source": r["source"]
                        }
                    })
        except Exception as e:
            logger.error(f"[Dashboard] 查询 papers 失败: {e}")
        return items

    # =========================================================================
    # 单项详情与已有对话历史 (Item Detail + Chat History)
    # =========================================================================
    def get_item_detail(self, app: str, raw_id: str) -> Dict[str, Any]:
        """获取条目完整正文与所有对话历史."""
        # 1. 查找条目基础信息
        search_res = self.get_items(app=app, limit=100)
        matched_item = None
        for it in search_res["items"]:
            if str(it.get("raw_id")) == str(raw_id):
                matched_item = it
                break

        # 2. 读取关联的历史对话记录
        chat_history = []
        if app == "notes":
            conn = self._get_conn("notes")
            if conn:
                try:
                    with conn:
                        rows = conn.execute(
                            "SELECT role, content, created_at FROM chat_history WHERE note_id = ? ORDER BY id ASC",
                            (raw_id,)
                        ).fetchall()
                        chat_history = [{"role": r["role"], "content": r["content"], "created_at": r["created_at"]} for r in rows]
                except Exception as e:
                    logger.debug(f"[Dashboard] 读取 notes 对话失败: {e}")

        elif app == "insights":
            conn = self._get_conn("insights")
            if conn:
                try:
                    with conn:
                        rows = conn.execute(
                            "SELECT role, content, created_at FROM insight_chat_history WHERE insight_id = ? ORDER BY id ASC",
                            (raw_id,)
                        ).fetchall()
                        chat_history = [{"role": r["role"], "content": r["content"], "created_at": r["created_at"]} for r in rows]
                except Exception as e:
                    logger.debug(f"[Dashboard] 读取 insights 对话失败: {e}")

        elif app == "radar":
            conn = self._get_conn("radar")
            if conn:
                try:
                    with conn:
                        rows = conn.execute(
                            "SELECT role, content, created_at FROM radar_chat_history WHERE item_id = ? ORDER BY id ASC",
                            (raw_id,)
                        ).fetchall()
                        chat_history = [{"role": r["role"], "content": r["content"], "created_at": r["created_at"]} for r in rows]
                except Exception as e:
                    logger.debug(f"[Dashboard] 读取 radar 对话失败: {e}")

        elif app == "mail":
            conn = self._get_conn("mail")
            if conn:
                try:
                    with conn:
                        rows = conn.execute(
                            "SELECT role, content, created_at FROM email_chat_history WHERE email_id = ? ORDER BY id ASC",
                            (raw_id,)
                        ).fetchall()
                        chat_history = [{"role": r["role"], "content": r["content"], "created_at": r["created_at"]} for r in rows]
                except Exception as e:
                    logger.debug(f"[Dashboard] 读取 email 对话失败: {e}")

        return {
            "item": matched_item,
            "chat_history": chat_history
        }

    # =========================================================================
    # 交互式 LLM 追问 (Live Interactive Dialogue)
    # =========================================================================
    def chat_with_item(self, app: str, raw_id: str, question: str) -> Dict[str, Any]:
        """向对应企业微信应用的 LLM 引擎发起追问并持久化落库."""
        if not question or not question.strip():
            return {"code": 400, "error": "问题内容不能为空"}

        question = question.strip()
        import requests

        reply_text = ""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. 洞察引擎 (8086)
        if app == "insights":
            try:
                res = requests.post(
                    "http://127.0.0.1:8086/command",
                    json={"command": f"/llm {raw_id} {question}", "from_user": "@web_user"},
                    timeout=45
                )
                if res.status_code == 200:
                    data = res.json()
                    reply_text = data.get("reply", "")
                else:
                    reply_text = f"[WARN] 洞察引擎服务响应异常 HTTP {res.status_code}"
            except Exception as e:
                reply_text = f"[WARN] 连接洞察引擎服务失败: {e}"

        # 2. 社交雷达 (8085)
        elif app == "radar":
            try:
                res = requests.post(
                    "http://127.0.0.1:8085/command",
                    json={"command": f"/llm {raw_id} {question}", "from_user": "@web_user"},
                    timeout=45
                )
                if res.status_code == 200:
                    data = res.json()
                    reply_text = data.get("reply", "")
                else:
                    reply_text = f"[WARN] 社交雷达服务响应异常 HTTP {res.status_code}"
            except Exception as e:
                reply_text = f"[WARN] 连接社交雷达服务失败: {e}"

        # 3. 邮件与学术助手 (8087)
        elif app in ("mail", "papers"):
            try:
                res = requests.post(
                    "http://127.0.0.1:8087/command",
                    json={"command": f"/llm {raw_id} {question}", "from_user": "@web_user"},
                    timeout=45
                )
                if res.status_code == 200:
                    data = res.json()
                    reply_text = data.get("reply", "")
                else:
                    reply_text = f"[WARN] 邮件助手服务响应异常 HTTP {res.status_code}"
            except Exception as e:
                reply_text = f"[WARN] 连接邮件助手服务失败: {e}"

        # 4. 微信笔记 (本服务原生 LLM 或 模拟生成)
        elif app == "notes":
            conn = self._get_conn("notes")
            note_row = None
            if conn:
                with conn:
                    note_row = conn.execute("SELECT * FROM inbox_notes WHERE id = ?", (raw_id,)).fetchone()
            
            if not note_row:
                return {"code": 404, "error": f"未找到 ID 为 {raw_id} 的笔记"}

            title = note_row["title"] or f"笔记 #{raw_id}"
            content = note_row["content_markdown"] or note_row["tldr"] or note_row["raw_content"] or ""

            # 优先复用 insight_extractor 或 direct LLM
            prompt = f"你是博文的个人知识助手。请基于笔记内容回答用户的问题。\n\n【笔记标题】: {title}\n【笔记全文】:\n{content}\n\n用户问题: {question}"
            # 委托给 8086 做通用 LLM 生成
            try:
                res = requests.post(
                    "http://127.0.0.1:8086/command",
                    json={"command": f"/llm 74 [追问笔记《{title}》]: {question}", "from_user": "@web_user"},
                    timeout=45
                )
                if res.status_code == 200:
                    reply_text = res.json().get("reply", "")
                else:
                    reply_text = f"基于笔记《{title}》分析：\n\n关于您的提问“{question}”，核心要点在于：{content[:200]}..."
            except Exception:
                reply_text = f"基于笔记《{title}》分析：\n\n关于您的提问“{question}”，核心要点在于：{content[:200]}..."

            # 写入 chat_history 数据库
            if conn:
                try:
                    with conn:
                        conn.execute(
                            "INSERT INTO chat_history (note_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                            (raw_id, "user", question, now_str)
                        )
                        conn.execute(
                            "INSERT INTO chat_history (note_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                            (raw_id, "assistant", reply_text, now_str)
                        )
                        conn.commit()
                except Exception as e:
                    logger.debug(f"[Dashboard] 记录 notes 对话异常: {e}")

        return {
            "code": 0,
            "reply": reply_text,
            "created_at": now_str
        }
