import os
import sys
import json
import pytest

# 添加 server 目录到 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server")))

from dashboard_service import DashboardService


@pytest.fixture
def mock_config(tmp_path):
    return {
        "api_secret": "test_token_secret_8888",
        "sync": {"api_secret": "test_token_secret_8888"}
    }


def test_dashboard_service_auth(mock_config):
    srv = DashboardService(mock_config)
    
    # 1. 验证原始秘钥
    assert srv.verify_auth("test_token_secret_8888") is True
    assert srv.verify_auth("wrong_secret") is False

    # 2. 验证生成 Token 与 Bearer Token
    token = srv.generate_token("test_token_secret_8888")
    assert len(token) == 64  # SHA256 hex string
    assert srv.verify_auth(token) is True
    assert srv.verify_auth(f"Bearer {token}") is True
    assert srv.verify_auth("Bearer invalid_token") is False


def test_dashboard_service_stats_and_items(mock_config):
    srv = DashboardService(mock_config)
    
    stats = srv.get_stats()
    assert "notes" in stats
    assert "insights" in stats
    assert "radar" in stats
    assert "mail" in stats

    items_resp = srv.get_items(limit=10)
    assert "items" in items_resp
    assert "total" in items_resp
    assert isinstance(items_resp["items"], list)


def test_dashboard_service_filters(mock_config):
    srv = DashboardService(mock_config)

    # 过滤不存在的关键词
    empty_res = srv.get_items(q="RANDOM_KEYWORD_NOT_EXIST_XYZ12345")
    assert len(empty_res["items"]) == 0

    # 限制返回数量
    lim_res = srv.get_items(limit=3)
    assert len(lim_res["items"]) <= 3


def test_web_index_html_exists():
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "index.html")
    assert os.path.exists(html_path)
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "WeHub" in content
    assert "id=\"authModal\"" in content
    assert "id=\"drawerOverlay\"" in content
    assert "id=\"editModal\"" in content
    assert "id=\"editItemBtn\"" in content
    assert "id=\"deleteItemBtn\"" in content


def test_dashboard_edit_delete_and_timezone(tmp_path, mock_config):
    """测试笔记时区本地化修正以及看板的编辑与删除能力."""
    import sqlite3
    from storage import InboxStorage

    db_dir = tmp_path / "data"
    db_dir.mkdir()
    db_path = str(db_dir / "inbox.db")

    # 1. 创建一条模拟历史 UTC 时间戳的记录 (1791791051 对应北京时间 2026-10-12 15:44:11，UTC 为 07:44:50)
    storage = InboxStorage(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
        INSERT INTO inbox_notes (msg_id, msg_type, from_user, create_time, title, tldr, content_markdown, tags, created_at)
        VALUES ('utc_msg_1', 'link', 'u1', 1791791051, '旧标题', '旧摘要', '旧正文', '["#旧标签"]', '2026-10-12 07:44:50')
        """)
        conn.commit()

    # 重新初始化触发 UTC -> UTC+8 自动修正
    storage = InboxStorage(db_path=db_path)
    note = storage.get_note_by_target("last")
    assert note["created_at"] == "2026-10-12 15:44:50"

    # 2. 验证 DashboardService 的 update_item 与 delete_item
    srv = DashboardService(mock_config, base_dir=str(tmp_path))
    srv.db_paths["notes"] = db_path

    nid = str(note["id"])
    up_res = srv.update_item("notes", nid, {
        "title": "新修改标题",
        "author": "新作者",
        "url": "https://example.com/new",
        "summary": "更新后的速读",
        "content": "更新后的完整 Markdown 正文",
        "tags": "#AI芯片 #体系结构"
    })
    assert up_res["code"] == 0

    items = srv.get_items(app="notes")["items"]
    assert len(items) == 1
    assert items[0]["title"] == "新修改标题"
    assert items[0]["summary"] == "更新后的速读"
    assert items[0]["content"] == "更新后的完整 Markdown 正文"
    assert "#AI芯片" in items[0]["tags"]

    del_res = srv.delete_item("notes", nid)
    assert del_res["code"] == 0
    assert len(srv.get_items(app="notes")["items"]) == 0
