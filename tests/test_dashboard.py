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
