import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests
import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server")))
from server import RequestHandler
from dashboard_service import DashboardService
from app_settings import AppSettingsManager


@pytest.fixture
def settings_http(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_KEY", "internal-test-credential")
    dashboard = DashboardService({"sync": {"api_secret": "settings-owner-secret"}})
    class Handler(RequestHandler):
        server_instance = SimpleNamespace(dashboard=dashboard, api_secret="settings-owner-secret")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_model_settings_reject_query_auth_and_cross_origin_mutation(settings_http):
    response = requests.get(settings_http + "/api/dashboard/model-settings?secret=settings-owner-secret", timeout=3)
    assert response.status_code == 401
    response = requests.post(
        settings_http + "/api/dashboard/model-settings/save",
        headers={"Authorization": "Bearer settings-owner-secret", "Origin": "https://untrusted.example"},
        json={"api_key": "must-not-be-forwarded"}, timeout=3,
    )
    assert response.status_code == 403
    assert "must-not-be-forwarded" not in response.text


def test_model_settings_reject_non_json_and_oversized_input(settings_http):
    headers = {"Authorization": "Bearer settings-owner-secret"}
    response = requests.post(settings_http + "/api/dashboard/model-settings/save", headers=headers, data="api_key=secret", timeout=3)
    assert response.status_code == 400
    response = requests.post(settings_http + "/api/dashboard/model-settings/save", headers=headers, json={"api_key": "x" * 17000}, timeout=3)
    assert response.status_code == 400
    assert "x" * 100 not in response.text
    assert response.headers["Cache-Control"] == "no-store"


@pytest.fixture
def app_settings_http(tmp_path):
    paths = {
        "insight_config": str(tmp_path / "insight.yaml"),
        "insight_philosophy": str(tmp_path / "philosophy.yaml"),
        "mail_config": str(tmp_path / "mail.yaml"),
        "mail_profile": str(tmp_path / "mail_profile.yaml"),
        "radar_config": str(tmp_path / "radar.yaml"),
        "radar_profile": str(tmp_path / "radar_profile.yaml"),
        "obsidian_config": str(tmp_path / "obsidian.yaml"),
    }
    with open(paths["insight_config"], "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "wechat": {"corp_secret": "SECRET_INSIGHT"},
            "llm": {"active_provider": "antigravity", "providers": {"antigravity": {"model": "default"}}},
            "engine": {"quiet_hours": "23:00-09:00", "lookback_hours": 72, "min_insight_score": 80, "run_interval_hours": 6},
        }, f)
    with open(paths["mail_config"], "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "notify": {"corp_secret": "SECRET_MAIL"},
            "mailboxes": [{"name": "Gmail", "password": "SECRET_GMAIL_PASSWORD"}],
            "llm": {"model": "default"},
            "app": {"quiet_hours": "23:00-09:00", "poll_interval": 180, "since_days": 7, "scholar_score_threshold": 65, "task_importance_threshold": 3},
        }, f)
    with open(paths["radar_config"], "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "wechat": {"corp_secret": "SECRET_RADAR"},
            "zhihu": {"enabled": True, "user_token": "Bowen", "cookie": "z_c0=SECRET_ZHIHU_COOKIE_VALUE_LONG_ENOUGH"},
            "llm": {"model": "default"},
            "radar": {"quiet_hours": "23:00-09:00", "base_interval_minutes": 20, "max_days_back": 7, "min_value_score": 70},
        }, f)
    with open(paths["obsidian_config"], "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "wechat": {"secret": "SECRET_OBS", "encoding_aes_key": "SECRET_AES"},
            "sync": {"api_secret": "settings-owner-secret"},
            "llm": {"enable": True, "model": "default", "temperature": 0.2},
            "obsidian": {"archive_mode": "daily", "daily_folder": "10-Journal", "inbox_file": "00-Inbox/Inbox.md", "format_template": "bullet"},
            "zhihu": {"cookie": "z_c0=SECRET_ZHIHU_COOKIE_VALUE_LONG_ENOUGH"},
        }, f)
    with open(paths["mail_profile"], "w", encoding="utf-8") as f:
        yaml.safe_dump({"research_topics": ["PIM"], "keywords": ["CXL"], "exclude_topics": [], "summary_preferences": {"language": "zh", "focus_aspects": ["PPA"]}}, f)
    with open(paths["radar_profile"], "w", encoding="utf-8") as f:
        yaml.safe_dump({"target_topics": ["CXL"], "keywords": ["PIM"], "exclude_patterns": [], "preferences": {"reward_in_depth_insights": True, "reward_architectural_tradeoffs": True}}, f)
    with open(paths["insight_philosophy"], "w", encoding="utf-8") as f:
        f.write("essence_vs_vehicle:\n  core_maxim: test\n")

    dashboard = DashboardService({"sync": {"api_secret": "settings-owner-secret"}})
    manager = AppSettingsManager(paths=paths, allow_restart=False)
    hot_state = {"cookie": None}
    crawler = SimpleNamespace(set_zhihu_cookie=lambda c: hot_state.__setitem__("cookie", c))
    llm = SimpleNamespace(model="default", temperature=0.2, enable=True, api_key="k", client=object(), base_url="http://127.0.0.1:18890/v1")

    class Handler(RequestHandler):
        server_instance = SimpleNamespace(
            dashboard=dashboard,
            app_settings=manager,
            api_secret="settings-owner-secret",
            cfg={},
            crawler=crawler,
            llm=llm,
        )

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", paths, hot_state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_app_settings_auth_origin_and_secret_redaction(app_settings_http):
    base_url, _, _ = app_settings_http
    r = requests.get(base_url + "/api/dashboard/app-settings?secret=settings-owner-secret", timeout=3)
    assert r.status_code == 401
    r = requests.post(
        base_url + "/api/dashboard/app-settings/apps",
        headers={"Authorization": "Bearer settings-owner-secret", "Origin": "https://untrusted.example"},
        json={"insight": {"min_insight_score": 85}},
        timeout=3,
    )
    assert r.status_code == 403

    r = requests.get(base_url + "/api/dashboard/app-settings", headers={"Authorization": "Bearer settings-owner-secret"}, timeout=3)
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    body = r.json()
    assert body["code"] == 0
    assert body["apps"]["zhihu"]["cookie_configured"] is True
    for secret in ("SECRET_INSIGHT", "SECRET_MAIL", "SECRET_GMAIL_PASSWORD", "SECRET_RADAR", "SECRET_OBS", "SECRET_ZHIHU_COOKIE"):
        assert secret not in r.text


def test_app_settings_validate_and_persist_apps_and_profiles(app_settings_http):
    base_url, paths, hot_state = app_settings_http
    headers = {"Authorization": "Bearer settings-owner-secret"}

    bad_quiet = requests.post(base_url + "/api/dashboard/app-settings/apps", headers=headers, json={"insight": {"quiet_hours": "99:99-00:00"}}, timeout=3)
    assert bad_quiet.status_code == 400

    bad_cookie = requests.post(base_url + "/api/dashboard/app-settings/apps", headers=headers, json={"zhihu": {"cookie": "short"}}, timeout=3)
    assert bad_cookie.status_code == 400

    ok_apps = requests.post(
        base_url + "/api/dashboard/app-settings/apps",
        headers=headers,
        json={
            "insight": {"min_insight_score": 88, "lookback_hours": 96},
            "mail": {"scholar_score_threshold": 75},
            "obsidian": {"format_template": "callout", "llm_temperature": 0.4},
            "zhihu": {"cookie": "d_c0=abc; z_c0=UPDATED_VALID_ZHIHU_COOKIE_STRING_12345"},
        },
        timeout=3,
    )
    assert ok_apps.status_code == 200
    assert ok_apps.json()["apps"]["insight"]["min_insight_score"] == 88
    assert hot_state["cookie"] == "d_c0=abc; z_c0=UPDATED_VALID_ZHIHU_COOKIE_STRING_12345"

    with open(paths["mail_config"], "r", encoding="utf-8") as f:
        mail_saved = yaml.safe_load(f)
    assert mail_saved["mailboxes"][0]["password"] == "SECRET_GMAIL_PASSWORD"
    assert mail_saved["app"]["scholar_score_threshold"] == 75

    bad_yaml = requests.post(base_url + "/api/dashboard/app-settings/profiles", headers=headers, json={"insight_philosophy": {"yaml_text": "bad: [unclosed"}}, timeout=3)
    assert bad_yaml.status_code == 400

    ok_prof = requests.post(
        base_url + "/api/dashboard/app-settings/profiles",
        headers=headers,
        json={
            "mail": {"research_topics": ["Near-Memory"], "keywords": ["HBM4", "CXL"], "exclude_topics": ["Crypto"], "language": "en", "focus_aspects": ["Area"]},
            "radar": {"target_topics": ["Chiplet"], "keywords": ["UCIe"], "exclude_patterns": ["Gossip"], "reward_in_depth_insights": False, "reward_architectural_tradeoffs": True},
            "insight_philosophy": {"yaml_text": "essence_vs_vehicle:\n  core_maxim: updated\n"},
        },
        timeout=3,
    )
    assert ok_prof.status_code == 200
    assert ok_prof.json()["profiles"]["mail"]["language"] == "en"
    assert ok_prof.json()["profiles"]["radar"]["keywords"] == ["UCIe"]
