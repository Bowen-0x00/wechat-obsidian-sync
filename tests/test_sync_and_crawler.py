"""针对增量同步与知乎解析/防爬降级的单元测试."""

import os
import sys
import tempfile
import pytest

# 添加 server 目录到 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server")))

from storage import InboxStorage
from crawler import ArticleCrawler, CrawledArticle


def test_incremental_sync_storage():
    """测试 Storage 的增量同步、标记已同步与全量拉取逻辑."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_inbox.db")
        storage = InboxStorage(db_path=db_path)

        # 1. 初始应为空
        assert len(storage.get_unsynced_notes()) == 0

        # 2. 插入 3 条笔记
        id1 = storage.add_note(msg_id="m1", msg_type="text", from_user="u1", create_time=1000, raw_content="笔记1")
        id2 = storage.add_note(msg_id="m2", msg_type="text", from_user="u1", create_time=1001, raw_content="笔记2")
        id3 = storage.add_note(msg_id="m3", msg_type="text", from_user="u1", create_time=1002, raw_content="笔记3")

        # 3. get_unsynced_notes 应返回全部 3 条 (因为均未同步)
        unsynced = storage.get_unsynced_notes()
        assert len(unsynced) == 3
        assert [n["id"] for n in unsynced] == [id1, id2, id3]

        # 4. 客户端同步并 ACK 确认前 2 条
        storage.mark_as_synced([id1, id2])

        # 5. 关键验证：后续只拉取未同步的笔记 (仅第 3 条，绝不能每次全量重复同步)
        unsynced_after = storage.get_unsynced_notes()
        assert len(unsynced_after) == 1
        assert unsynced_after[0]["id"] == id3

        # 6. 支持 include_synced=True 全量重拉
        all_notes = storage.get_unsynced_notes(include_synced=True)
        assert len(all_notes) == 3

        # 7. 支持 since_id 游标过滤
        cursor_notes = storage.get_unsynced_notes(since_id=id2, include_synced=True)
        assert len(cursor_notes) == 1
        assert cursor_notes[0]["id"] == id3

        # 8. 确认第 3 条
        storage.mark_as_synced([id3])
        assert len(storage.get_unsynced_notes()) == 0


def test_anti_spider_detection():
    """测试反爬标语拦截，确保不会将知乎等站点的 403 占位语误当作正文."""
    crawler = ArticleCrawler()

    # 模拟知乎反爬 403 页面 HTML
    anti_spider_html = """
    <!DOCTYPE html><html><head><title>知乎 - 有问题，就会有答案</title></head>
    <body>
        <div style="color:#535861;">知乎，让每一次点击都充满意义 —— 欢迎来到知乎，发现问题背后的世界。</div>
    </body></html>
    """
    article = crawler._parse_html(anti_spider_html, "https://zhuanlan.zhihu.com/p/123456", "测试专栏标题")
    assert article.summary_hint == "[反爬拦截]"
    assert article.content_text == ""
    assert article.content_markdown == ""
    assert article.title == "测试专栏标题"


def test_zhihu_redirect_cleaning():
    """测试知乎短链与重定向 target 提取."""
    crawler = ArticleCrawler()

    # link.zhihu.com 重定向
    dirty_url = "https://link.zhihu.com/?target=https%3A%2F%2Fzhuanlan.zhihu.com%2Fp%2F677041838"
    article = crawler.crawl(dirty_url, title_hint="知乎专栏")
    # 不管最终有无凭据，URL 都应被自动净化为真实 target
    assert "link.zhihu.com" not in article.url
    assert "zhuanlan.zhihu.com/p/677041838" in article.url


def test_crawler_cookie_update():
    """测试 Crawler 的知乎 Cookie 动态更新与携带."""
    crawler = ArticleCrawler()
    assert crawler.zhihu_cookie == ""
    crawler.set_zhihu_cookie("test_cookie_12345")
    assert crawler.zhihu_cookie == "test_cookie_12345"


def test_storage_reset_synced_status():
    """测试 Storage 同步状态重置功能."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_inbox.db")
        storage = InboxStorage(db_path=db_path)

        id1 = storage.add_note(msg_id="m1", msg_type="text", from_user="u1", create_time=1000, raw_content="笔记1")
        storage.mark_as_synced([id1])
        assert len(storage.get_unsynced_notes()) == 0

        storage.reset_synced_status()
        assert len(storage.get_unsynced_notes()) == 1


def test_process_clipped_content_text_and_link():
    """测试手机一键剪藏接口的入库与解析逻辑."""
    from server import WeChatObsidianServer

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_clip.db")
        server = WeChatObsidianServer.__new__(WeChatObsidianServer)
        server.storage = InboxStorage(db_path=db_path)
        server.crawler = ArticleCrawler()
        # mock llm & wecom
        class DummyLLM:
            enable = False
            def summarize_article(self, title, text, url):
                return {"tldr": f"速读: {title}", "key_points": ["要点1"], "tags": ["#剪藏"]}
            def tag_thought(self, text):
                return ["#闪念"]
        class DummyWeCom:
            def send_confirmation(self, *args, **kwargs):
                pass
        server.llm = DummyLLM()
        server.wecom_client = DummyWeCom()
        server.executor = None
        server._submit_background = lambda fn, *args: None

        # 1. 测试纯文字剪藏
        res1 = server.process_clipped_content(raw_text="今天学习了存算一体架构与CXL", custom_title="学习备忘")
        assert res1["note_id"] > 0
        assert res1["title"] == "学习备忘"
        assert "#闪念" in res1["tags"]

        # 2. 测试带知乎链接的剪藏 (带随笔附注)
        res2 = server.process_clipped_content(raw_text="这篇文章讲AI芯片很透彻 https://zhuanlan.zhihu.com/p/677041838")
        assert res2["note_id"] > 0
        assert "这篇文章讲AI芯片很透彻" in res2["title"]

        # 3. 验证数据库中这两条笔记均待同步 (is_synced = 0)
        unsynced = server.storage.get_unsynced_notes()
        assert len(unsynced) == 2


def test_http_clip_api_endpoint():
    """测试 HTTP 层级的 /api/clip 接口 (鉴权、请求解析与响应格式)."""
    import threading
    import requests
    from http.server import HTTPServer
    from server import WeChatObsidianServer, RequestHandler

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_http_clip.db")
        server = WeChatObsidianServer.__new__(WeChatObsidianServer)
        server.storage = InboxStorage(db_path=db_path)
        server.crawler = ArticleCrawler()
        server.api_secret = "test_secret_123"
        server.port = 18999
        class DummyLLM:
            enable = False
            def summarize_article(self, title, text, url):
                return {"tldr": "速读测试", "key_points": [], "tags": ["#测试"]}
            def tag_thought(self, text):
                return ["#测试"]
        class DummyWeCom:
            def send_confirmation(self, *args, **kwargs):
                pass
        server.llm = DummyLLM()
        server.wecom_client = DummyWeCom()
        server.executor = None
        server._submit_background = lambda fn, *args: None

        RequestHandler.server_instance = server
        httpd = HTTPServer(("127.0.0.1", 18999), RequestHandler)
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()

        try:
            # 1. 鉴权失败测试
            r_fail = requests.post("http://127.0.0.1:18999/api/clip", json={"content": "测试"}, timeout=5)
            assert r_fail.status_code == 401

            # 2. 正常 JSON 剪藏
            r_ok = requests.post(
                "http://127.0.0.1:18999/api/clip?secret=test_secret_123",
                json={"content": "这是从安卓剪藏的内容", "title": "自定义标题"},
                timeout=5
            )
            assert r_ok.status_code == 200
            data = r_ok.json()
            assert data["code"] == 0
            assert data["title"] == "自定义标题"
            assert data["note_id"] > 0

            # 3. 正常纯文本 POST 剪藏 (兼容各种简单快捷方式)
            r_text = requests.post(
                "http://127.0.0.1:18999/api/clip?secret=test_secret_123",
                data="纯文本闪念备忘".encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"},
                timeout=5
            )
            assert r_text.status_code == 200
            data_text = r_text.json()
            assert data_text["code"] == 0
            assert data_text["note_id"] > 0
        finally:
            httpd.shutdown()
