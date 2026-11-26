"""多应用业务参数与研究画像配置管理器 (供 Web GUI 统一读取、校验、热更新与重启)."""

import copy
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

import httpx
import requests
import yaml
from loguru import logger
from openai import OpenAI


_QUIET_OFF = {"off", "none", "false", "0", "关闭"}
_CONTROL_OR_QUOTE = re.compile(r'[\s"\'\\\x00-\x1f]')


class AppSettingsManager:
    """统一管理 4 个企业微信应用的运行时配置、共享知乎 Cookie 与 3 份研究画像."""

    def __init__(
        self,
        base_dir: Optional[str] = None,
        paths: Optional[Dict[str, str]] = None,
        allow_restart: bool = True,
    ):
        self.base_dir = os.path.abspath(
            base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.allow_restart = allow_restart
        self.paths = self._resolve_paths(paths or {})

    def _resolve_paths(self, overrides: Dict[str, str]) -> Dict[str, str]:
        parent = os.path.dirname(self.base_dir)
        candidates = {
            "insight_config": [
                os.path.join(parent, "insight_extractor", "config", "config.yaml"),
                "/root/insight_extractor/config/config.yaml",
                "D:/Project/insight_extractor/config/config.yaml",
            ],
            "insight_philosophy": [
                os.path.join(parent, "insight_extractor", "config", "architecture_philosophy.yaml"),
                "/root/insight_extractor/config/architecture_philosophy.yaml",
                "D:/Project/insight_extractor/config/architecture_philosophy.yaml",
            ],
            "mail_config": [
                os.path.join(parent, "mail_assist", "config", "config.yaml"),
                "/root/mail_assist/config/config.yaml",
                "D:/Project/mail_assist/config/config.yaml",
            ],
            "mail_profile": [
                os.path.join(parent, "mail_assist", "config", "user_profile.yaml"),
                "/root/mail_assist/config/user_profile.yaml",
                "D:/Project/mail_assist/config/user_profile.yaml",
            ],
            "radar_config": [
                os.path.join(parent, "social_radar", "config", "config.yaml"),
                "/root/social_radar/config/config.yaml",
                "D:/Project/social_radar/config/config.yaml",
            ],
            "radar_profile": [
                os.path.join(parent, "social_radar", "config", "user_profile.yaml"),
                "/root/social_radar/config/user_profile.yaml",
                "D:/Project/social_radar/config/user_profile.yaml",
            ],
            "obsidian_config": [
                os.path.join(self.base_dir, "config.yaml"),
                "/root/wechat_obsidian/config.yaml",
                "D:/Project/wechat_obsidian/config.yaml",
            ],
        }
        resolved: Dict[str, str] = {}
        for key, cand_list in candidates.items():
            if key in overrides:
                resolved[key] = overrides[key]
                continue
            chosen = cand_list[0]
            for cand in cand_list:
                if os.path.exists(cand):
                    chosen = cand
                    break
            resolved[key] = chosen
        return resolved

    def _exists(self, key: str) -> bool:
        path = self.paths.get(key, "")
        return bool(path and os.path.exists(path))

    def _read_yaml(self, key: str) -> Dict[str, Any]:
        path = self.paths.get(key, "")
        if not path or not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}

    def _read_text(self, key: str) -> str:
        path = self.paths.get(key, "")
        if not path or not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _atomic_write_text(self, path: str, content: str, private: bool = False) -> None:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=parent,
                prefix=".tmp_cfg_",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_path = tmp.name
                tmp.write(content)
            if private and os.name != "nt":
                os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, path)
            tmp_path = None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _atomic_write_yaml(self, path: str, data: Dict[str, Any], private: bool = False) -> None:
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        self._atomic_write_text(path, text, private=private)

    @staticmethod
    def _validate_quiet_hours(val: Any) -> str:
        if not isinstance(val, str):
            raise ValueError("免打扰时段格式无效，请使用 HH:MM-HH:MM 或 off")
        clean = val.strip()
        if clean.lower() in _QUIET_OFF:
            return "off"
        match = re.match(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$", clean)
        if not match:
            raise ValueError("免打扰时段格式无效，请使用 HH:MM-HH:MM 或 off")
        sh, sm, eh, em = map(int, match.groups())
        if not (0 <= sh <= 23 and 0 <= eh <= 23 and 0 <= sm <= 59 and 0 <= em <= 59):
            raise ValueError("免打扰时段小时/分钟超出合法范围")
        return f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"

    @staticmethod
    def _validate_int(val: Any, name: str, lo: int, hi: int) -> int:
        if isinstance(val, bool):
            raise ValueError(f"{name} 必须是整数")
        try:
            num = int(val)
        except (TypeError, ValueError):
            raise ValueError(f"{name} 必须是整数")
        if not (lo <= num <= hi):
            raise ValueError(f"{name} 必须在 {lo} 到 {hi} 之间")
        return num

    @staticmethod
    def _validate_float(val: Any, name: str, lo: float, hi: float) -> float:
        if isinstance(val, bool):
            raise ValueError(f"{name} 必须是数字")
        try:
            num = float(val)
        except (TypeError, ValueError):
            raise ValueError(f"{name} 必须是数字")
        if not (lo <= num <= hi):
            raise ValueError(f"{name} 必须在 {lo} 到 {hi} 之间")
        return round(num, 3)

    @staticmethod
    def _validate_model_name(val: Any) -> str:
        if not isinstance(val, str):
            raise ValueError("模型名称必须是字符串")
        model = val.strip()
        if not model or len(model) > 200 or _CONTROL_OR_QUOTE.search(model):
            raise ValueError("模型名称无效，不能包含空白、引号或控制字符")
        return model

    @staticmethod
    def _validate_str_list(val: Any, name: str, max_items: int = 200) -> List[str]:
        if not isinstance(val, list):
            raise ValueError(f"{name} 必须是字符串列表")
        items: List[str] = []
        for entry in val:
            if not isinstance(entry, str):
                raise ValueError(f"{name} 中包含非文本项")
            trimmed = entry.strip()
            if not trimmed:
                continue
            if len(trimmed) > 500:
                raise ValueError(f"{name} 单条长度不能超过 500 字符")
            items.append(trimmed)
        if len(items) > max_items:
            raise ValueError(f"{name} 条目数不能超过 {max_items}")
        return items

    @staticmethod
    def _validate_short_str(val: Any, name: str, max_len: int = 120) -> str:
        if not isinstance(val, str):
            raise ValueError(f"{name} 必须是文本")
        clean = val.strip()
        if len(clean) > max_len or any(c in clean for c in ("\r", "\n", "\x00")):
            raise ValueError(f"{name} 长度或格式无效")
        return clean

    def _restart_services(self, services: List[str]) -> tuple[List[str], List[str]]:
        restarted: List[str] = []
        errors: List[str] = []
        if not services or not self.allow_restart or os.name == "nt":
            return restarted, errors
        if not shutil.which("systemctl"):
            return restarted, errors
        for svc in sorted(set(services)):
            try:
                active = subprocess.run(
                    ["systemctl", "is-active", "--quiet", svc],
                    capture_output=True,
                    timeout=5,
                )
                if active.returncode != 0:
                    continue
                res = subprocess.run(
                    ["systemctl", "restart", svc],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if res.returncode == 0:
                    restarted.append(svc)
                else:
                    errors.append(f"{svc}: {res.stderr.strip() or res.returncode}")
            except Exception as exc:
                errors.append(f"{svc}: {exc}")
        return restarted, errors

    def get_all(self) -> Dict[str, Any]:
        """读取所有应用参数、知乎状态与 3 份研究画像（绝不返回任何密钥或 Cookie 明文）."""
        ins_cfg = self._read_yaml("insight_config")
        mail_cfg = self._read_yaml("mail_config")
        radar_cfg = self._read_yaml("radar_config")
        obs_cfg = self._read_yaml("obsidian_config")

        ins_eng = ins_cfg.get("engine") or {}
        ins_llm = ins_cfg.get("llm") or {}
        ins_active = ins_llm.get("active_provider", "antigravity")
        ins_provider = (ins_llm.get("providers") or {}).get(ins_active) or {}

        mail_app = mail_cfg.get("app") or {}
        mail_llm = mail_cfg.get("llm") or {}

        radar_app = radar_cfg.get("radar") or {}
        radar_zh = radar_cfg.get("zhihu") or {}
        radar_llm = radar_cfg.get("llm") or {}

        obs_llm = obs_cfg.get("llm") or {}
        obs_book = obs_cfg.get("obsidian") or {}
        obs_zh = obs_cfg.get("zhihu") or {}

        saved_cookie = str(obs_zh.get("cookie") or radar_zh.get("cookie") or "").strip()

        mail_prof = self._read_yaml("mail_profile")
        mail_sum_pref = mail_prof.get("summary_preferences") or {}
        radar_prof = self._read_yaml("radar_profile")
        radar_pref = radar_prof.get("preferences") or {}
        philosophy_text = self._read_text("insight_philosophy")

        return {
            "apps": {
                "insight": {
                    "available": self._exists("insight_config"),
                    "quiet_hours": str(ins_eng.get("quiet_hours", "23:00-09:00")),
                    "lookback_hours": int(ins_eng.get("lookback_hours", 72)),
                    "run_interval_hours": int(ins_eng.get("run_interval_hours", 6)),
                    "min_insight_score": int(ins_eng.get("min_insight_score", 80)),
                    "auto_notify_threshold": bool(ins_eng.get("auto_notify_threshold", True)),
                    "llm_model": str(ins_provider.get("model", "default")),
                },
                "mail": {
                    "available": self._exists("mail_config"),
                    "quiet_hours": str(mail_app.get("quiet_hours", "23:00-09:00")),
                    "poll_interval": int(mail_app.get("poll_interval", 180)),
                    "since_days": int(mail_app.get("since_days", 7)),
                    "max_fetch_emails_per_round": int(mail_app.get("max_fetch_emails_per_round", 10)),
                    "scholar_score_threshold": int(mail_app.get("scholar_score_threshold", 65)),
                    "task_importance_threshold": int(mail_app.get("task_importance_threshold", 3)),
                    "llm_model": str(mail_llm.get("model", "default")),
                },
                "radar": {
                    "available": self._exists("radar_config"),
                    "quiet_hours": str(radar_app.get("quiet_hours", "23:00-09:00")),
                    "base_interval_minutes": int(radar_app.get("base_interval_minutes", 20)),
                    "max_days_back": int(radar_app.get("max_days_back", 7)),
                    "min_value_score": int(radar_app.get("min_value_score", 70)),
                    "zhihu_enabled": bool(radar_zh.get("enabled", True)),
                    "zhihu_user_token": str(radar_zh.get("user_token", "")),
                    "zhihu_check_moments": bool(radar_zh.get("check_moments", True)),
                    "zhihu_check_questions": bool(radar_zh.get("check_questions", True)),
                    "zhihu_max_questions_per_round": int(radar_zh.get("max_questions_per_round", 8)),
                    "llm_model": str(radar_llm.get("model", "default")),
                },
                "obsidian": {
                    "available": self._exists("obsidian_config"),
                    "llm_enable": bool(obs_llm.get("enable", True)),
                    "llm_temperature": float(obs_llm.get("temperature", 0.2)),
                    "llm_model": str(obs_llm.get("model", "default")),
                    "archive_mode": str(obs_book.get("archive_mode", "daily")),
                    "daily_folder": str(obs_book.get("daily_folder", "10-Journal&Planning/13-note")),
                    "inbox_file": str(obs_book.get("inbox_file", "00-Inbox/Inbox.md")),
                    "format_template": str(obs_book.get("format_template", "bullet")),
                },
                "zhihu": {
                    "cookie_configured": bool(saved_cookie),
                    "cookie_length": len(saved_cookie),
                },
            },
            "profiles": {
                "mail": {
                    "available": self._exists("mail_profile"),
                    "research_topics": list(mail_prof.get("research_topics") or []),
                    "keywords": list(mail_prof.get("keywords") or []),
                    "exclude_topics": list(mail_prof.get("exclude_topics") or []),
                    "language": str(mail_sum_pref.get("language", "zh")),
                    "focus_aspects": list(mail_sum_pref.get("focus_aspects") or []),
                },
                "radar": {
                    "available": self._exists("radar_profile"),
                    "target_topics": list(radar_prof.get("target_topics") or []),
                    "keywords": list(radar_prof.get("keywords") or []),
                    "exclude_patterns": list(radar_prof.get("exclude_patterns") or []),
                    "reward_in_depth_insights": bool(radar_pref.get("reward_in_depth_insights", True)),
                    "reward_architectural_tradeoffs": bool(radar_pref.get("reward_architectural_tradeoffs", True)),
                },
                "insight_philosophy": {
                    "available": self._exists("insight_philosophy"),
                    "yaml_text": philosophy_text,
                },
            },
        }

    def save_apps(self, payload: Dict[str, Any], server_instance: Any = None) -> Dict[str, Any]:
        """校验并持久化保存 4 个应用的业务参数与共享知乎 Cookie，按需热更新并重启变更服务."""
        if not isinstance(payload, dict):
            raise ValueError("配置请求必须是 JSON 对象")

        changed_services: List[str] = []

        if "insight" in payload and self._exists("insight_config"):
            sec = payload["insight"]
            if not isinstance(sec, dict):
                raise ValueError("insight 配置无效")
            before = self._read_yaml("insight_config")
            after = copy.deepcopy(before)
            eng = after.setdefault("engine", {})
            if "quiet_hours" in sec:
                eng["quiet_hours"] = self._validate_quiet_hours(sec["quiet_hours"])
            if "lookback_hours" in sec:
                eng["lookback_hours"] = self._validate_int(sec["lookback_hours"], "Insight 回溯小时", 24, 720)
            if "run_interval_hours" in sec:
                eng["run_interval_hours"] = self._validate_int(sec["run_interval_hours"], "Insight 思考周期", 1, 168)
            if "min_insight_score" in sec:
                eng["min_insight_score"] = self._validate_int(sec["min_insight_score"], "Insight 推送阈值", 50, 100)
            if "auto_notify_threshold" in sec:
                eng["auto_notify_threshold"] = bool(sec["auto_notify_threshold"])
            if "llm_model" in sec:
                llm_sec = after.setdefault("llm", {})
                active_p = llm_sec.get("active_provider", "antigravity")
                providers = llm_sec.setdefault("providers", {})
                providers.setdefault(active_p, {})["model"] = self._validate_model_name(sec["llm_model"])
            if after != before:
                self._atomic_write_yaml(self.paths["insight_config"], after, private=True)
                changed_services.append("insight_extractor")

        if "mail" in payload and self._exists("mail_config"):
            sec = payload["mail"]
            if not isinstance(sec, dict):
                raise ValueError("mail 配置无效")
            before = self._read_yaml("mail_config")
            after = copy.deepcopy(before)
            app = after.setdefault("app", {})
            if "quiet_hours" in sec:
                app["quiet_hours"] = self._validate_quiet_hours(sec["quiet_hours"])
            if "poll_interval" in sec:
                app["poll_interval"] = self._validate_int(sec["poll_interval"], "邮件轮询周期", 30, 86400)
            if "since_days" in sec:
                app["since_days"] = self._validate_int(sec["since_days"], "邮件回溯天数", 1, 90)
            if "max_fetch_emails_per_round" in sec:
                app["max_fetch_emails_per_round"] = self._validate_int(sec["max_fetch_emails_per_round"], "单轮最大邮件数", 1, 50)
            if "scholar_score_threshold" in sec:
                app["scholar_score_threshold"] = self._validate_int(sec["scholar_score_threshold"], "论文推送阈值", 0, 100)
            if "task_importance_threshold" in sec:
                app["task_importance_threshold"] = self._validate_int(sec["task_importance_threshold"], "事务重要度阈值", 1, 5)
            if "llm_model" in sec:
                after.setdefault("llm", {})["model"] = self._validate_model_name(sec["llm_model"])
            if after != before:
                self._atomic_write_yaml(self.paths["mail_config"], after, private=True)
                changed_services.append("mail_assist")

        radar_before = self._read_yaml("radar_config") if self._exists("radar_config") else {}
        radar_after = copy.deepcopy(radar_before)
        radar_changed = False

        if "radar" in payload and self._exists("radar_config"):
            sec = payload["radar"]
            if not isinstance(sec, dict):
                raise ValueError("radar 配置无效")
            r_sec = radar_after.setdefault("radar", {})
            z_sec = radar_after.setdefault("zhihu", {})
            if "quiet_hours" in sec:
                r_sec["quiet_hours"] = self._validate_quiet_hours(sec["quiet_hours"])
            if "base_interval_minutes" in sec:
                r_sec["base_interval_minutes"] = self._validate_int(sec["base_interval_minutes"], "雷达轮询周期", 5, 1440)
            if "max_days_back" in sec:
                r_sec["max_days_back"] = self._validate_int(sec["max_days_back"], "雷达回溯天数", 1, 90)
            if "min_value_score" in sec:
                r_sec["min_value_score"] = self._validate_int(sec["min_value_score"], "雷达价值阈值", 0, 100)
            if "zhihu_enabled" in sec:
                z_sec["enabled"] = bool(sec["zhihu_enabled"])
            if "zhihu_user_token" in sec:
                z_sec["user_token"] = self._validate_short_str(sec["zhihu_user_token"], "知乎 user_token", 100)
            if "zhihu_check_moments" in sec:
                z_sec["check_moments"] = bool(sec["zhihu_check_moments"])
            if "zhihu_check_questions" in sec:
                z_sec["check_questions"] = bool(sec["zhihu_check_questions"])
            if "zhihu_max_questions_per_round" in sec:
                z_sec["max_questions_per_round"] = self._validate_int(sec["zhihu_max_questions_per_round"], "单轮检查问题数", 1, 50)
            if "llm_model" in sec:
                radar_after.setdefault("llm", {})["model"] = self._validate_model_name(sec["llm_model"])
            if radar_after != radar_before:
                radar_changed = True

        obs_before = self._read_yaml("obsidian_config") if self._exists("obsidian_config") else {}
        obs_after = copy.deepcopy(obs_before)
        obs_changed = False

        if "obsidian" in payload and self._exists("obsidian_config"):
            sec = payload["obsidian"]
            if not isinstance(sec, dict):
                raise ValueError("obsidian 配置无效")
            llm_sec = obs_after.setdefault("llm", {})
            book_sec = obs_after.setdefault("obsidian", {})
            if "llm_enable" in sec:
                llm_sec["enable"] = bool(sec["llm_enable"])
            if "llm_temperature" in sec:
                llm_sec["temperature"] = self._validate_float(sec["llm_temperature"], "笔记摘要温度", 0.0, 2.0)
            if "llm_model" in sec:
                llm_sec["model"] = self._validate_model_name(sec["llm_model"])
            if "archive_mode" in sec:
                mode = str(sec["archive_mode"]).strip()
                if mode not in ("daily", "inbox"):
                    raise ValueError("Obsidian 归档模式仅支持 daily 或 inbox")
                book_sec["archive_mode"] = mode
            if "daily_folder" in sec:
                folder = self._validate_short_str(sec["daily_folder"], "每日笔记目录", 160)
                if not folder:
                    raise ValueError("每日笔记目录不能为空")
                book_sec["daily_folder"] = folder
            if "inbox_file" in sec:
                inbox = self._validate_short_str(sec["inbox_file"], "单文件收件箱路径", 160)
                if not inbox:
                    raise ValueError("单文件收件箱路径不能为空")
                book_sec["inbox_file"] = inbox
            if "format_template" in sec:
                fmt = str(sec["format_template"]).strip()
                if fmt not in ("bullet", "callout", "plain"):
                    raise ValueError("笔记排版模板仅支持 bullet、callout 或 plain")
                book_sec["format_template"] = fmt
            if obs_after != obs_before:
                obs_changed = True

        new_cookie: Optional[str] = None
        if "zhihu" in payload and isinstance(payload["zhihu"], dict):
            raw_cookie = payload["zhihu"].get("cookie")
            if isinstance(raw_cookie, str) and raw_cookie.strip():
                cookie = raw_cookie.strip()
                if any(c in cookie for c in ("\r", "\n", "\x00")) or len(cookie) < 30 or "z_c0" not in cookie:
                    raise ValueError("知乎 Cookie 格式无效（需包含 z_c0 且不能换行）")
                new_cookie = cookie
                if self._exists("obsidian_config"):
                    obs_after.setdefault("zhihu", {})["cookie"] = cookie
                    if obs_after != obs_before:
                        obs_changed = True
                if self._exists("radar_config"):
                    radar_after.setdefault("zhihu", {})["cookie"] = cookie
                    if radar_after != radar_before:
                        radar_changed = True

        if radar_changed:
            self._atomic_write_yaml(self.paths["radar_config"], radar_after, private=True)
            changed_services.append("social_radar")

        if obs_changed:
            self._atomic_write_yaml(self.paths["obsidian_config"], obs_after, private=True)
            if server_instance is not None:
                self._hot_reload_obsidian(server_instance, obs_after, new_cookie)

        restarted, restart_errors = self._restart_services(changed_services)
        return {
            "code": 0,
            "restarted": restarted,
            "restart_errors": restart_errors,
            **self.get_all(),
        }

    def _hot_reload_obsidian(self, server_instance: Any, obs_cfg: Dict[str, Any], new_cookie: Optional[str]) -> None:
        server_instance.cfg = obs_cfg
        if new_cookie and hasattr(server_instance, "crawler") and server_instance.crawler:
            server_instance.crawler.set_zhihu_cookie(new_cookie)
        llm_cfg = obs_cfg.get("llm") or {}
        llm_obj = getattr(server_instance, "llm", None)
        if llm_obj is not None:
            llm_obj.model = str(llm_cfg.get("model", llm_obj.model))
            llm_obj.temperature = float(llm_cfg.get("temperature", llm_obj.temperature))
            want_enable = bool(llm_cfg.get("enable", True))
            llm_obj.enable = want_enable and bool(llm_obj.api_key) and llm_obj.api_key != "YOUR_LLM_API_KEY"
            if llm_obj.enable and llm_obj.client is None and llm_obj.api_key:
                llm_obj.client = OpenAI(
                    base_url=llm_obj.base_url,
                    api_key=llm_obj.api_key,
                    max_retries=0,
                    http_client=httpx.Client(timeout=50.0, proxy=llm_cfg.get("proxy"), trust_env=False),
                )
        logger.info("[AppSettings] wechat_obsidian 配置已热更新生效")

    def save_profiles(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """校验并保存 MailAssist / SocialRadar 画像与 Insight 体系结构研究心法."""
        if not isinstance(payload, dict):
            raise ValueError("画像配置必须是 JSON 对象")

        changed_services: List[str] = []

        if "mail" in payload and self._exists("mail_profile"):
            sec = payload["mail"]
            if not isinstance(sec, dict):
                raise ValueError("mail 画像格式无效")
            before = self._read_yaml("mail_profile")
            after = copy.deepcopy(before)
            if "research_topics" in sec:
                after["research_topics"] = self._validate_str_list(sec["research_topics"], "研究方向")
            if "keywords" in sec:
                after["keywords"] = self._validate_str_list(sec["keywords"], "学术关键词", max_items=300)
            if "exclude_topics" in sec:
                after["exclude_topics"] = self._validate_str_list(sec["exclude_topics"], "排除方向")
            sp = after.setdefault("summary_preferences", {})
            if "language" in sec:
                lang = str(sec["language"]).strip()
                if lang not in ("zh", "en"):
                    raise ValueError("论文速读语言仅支持 zh 或 en")
                sp["language"] = lang
            if "focus_aspects" in sec:
                sp["focus_aspects"] = self._validate_str_list(sec["focus_aspects"], "导读关注维度")
            if after != before:
                self._atomic_write_yaml(self.paths["mail_profile"], after)
                changed_services.append("mail_assist")

        if "radar" in payload and self._exists("radar_profile"):
            sec = payload["radar"]
            if not isinstance(sec, dict):
                raise ValueError("radar 画像格式无效")
            before = self._read_yaml("radar_profile")
            after = copy.deepcopy(before)
            if "target_topics" in sec:
                after["target_topics"] = self._validate_str_list(sec["target_topics"], "雷达关注领域")
            if "keywords" in sec:
                after["keywords"] = self._validate_str_list(sec["keywords"], "雷达关键词", max_items=300)
            if "exclude_patterns" in sec:
                after["exclude_patterns"] = self._validate_str_list(sec["exclude_patterns"], "雷达降噪规则")
            pref = after.setdefault("preferences", {})
            if "reward_in_depth_insights" in sec:
                pref["reward_in_depth_insights"] = bool(sec["reward_in_depth_insights"])
            if "reward_architectural_tradeoffs" in sec:
                pref["reward_architectural_tradeoffs"] = bool(sec["reward_architectural_tradeoffs"])
            if after != before:
                self._atomic_write_yaml(self.paths["radar_profile"], after)
                changed_services.append("social_radar")

        if "insight_philosophy" in payload and self._exists("insight_philosophy"):
            sec = payload["insight_philosophy"]
            if not isinstance(sec, dict) or not isinstance(sec.get("yaml_text"), str):
                raise ValueError("研究心法 yaml_text 必须是字符串")
            yaml_text = sec["yaml_text"].strip()
            if not yaml_text or len(yaml_text) > 32000:
                raise ValueError("研究心法内容不能为空且不能超过 32000 字符")
            try:
                parsed = yaml.safe_load(yaml_text)
            except yaml.YAMLError as exc:
                raise ValueError(f"研究心法 YAML 语法错误: {exc}")
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError("研究心法 YAML 根节点必须是非空映射")
            before_text = self._read_text("insight_philosophy")
            normalized = yaml_text + "\n"
            if normalized != before_text:
                self._atomic_write_text(self.paths["insight_philosophy"], normalized)
                changed_services.append("insight_extractor")

        restarted, restart_errors = self._restart_services(changed_services)
        return {
            "code": 0,
            "restarted": restarted,
            "restart_errors": restart_errors,
            **self.get_all(),
        }

    def run_action(self, payload: Dict[str, Any], server_instance: Any = None) -> Dict[str, Any]:
        """执行白名单内的测试或立即触发操作."""
        if not isinstance(payload, dict):
            raise ValueError("操作请求必须是 JSON 对象")
        action = str(payload.get("action") or "").strip()

        if action == "test_zhihu_cookie":
            cand = str(payload.get("cookie") or "").strip()
            if cand:
                if any(c in cand for c in ("\r", "\n", "\x00")) or len(cand) < 30 or "z_c0" not in cand:
                    raise ValueError("知乎 Cookie 格式无效（需包含 z_c0 且不能换行）")
                cookie = cand
            else:
                obs_zh = self._read_yaml("obsidian_config").get("zhihu") or {}
                radar_zh = self._read_yaml("radar_config").get("zhihu") or {}
                cookie = str(obs_zh.get("cookie") or radar_zh.get("cookie") or "").strip()
            if not cookie:
                return {"code": 0, "ok": False, "status_code": 0, "account": "", "message": "尚未配置知乎 Cookie"}
            headers = {
                "accept": "*/*",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "cookie": cookie,
            }
            with requests.Session() as session:
                session.trust_env = False
                resp = session.get("https://www.zhihu.com/api/v4/me?include=is_realname", headers=headers, timeout=8)
            if resp.status_code == 200:
                account = (resp.json() or {}).get("name") or "已登录账号"
                return {"code": 0, "ok": True, "status_code": 200, "account": account, "message": f"Cookie 有效（账号：{account}）"}
            return {"code": 0, "ok": False, "status_code": resp.status_code, "account": "", "message": f"知乎返回 HTTP {resp.status_code}，可能已过期或触发验证"}

        triggers = {
            "trigger_insight": ("http://127.0.0.1:8086/command", "/insight", "洞察引擎"),
            "trigger_mail_check": ("http://127.0.0.1:8087/command", "/check", "邮件助手"),
            "trigger_radar_check": ("http://127.0.0.1:8085/command", "/check", "社交雷达"),
        }
        if action not in triggers:
            raise ValueError(f"不支持的操作: {action}")

        url, cmd, label = triggers[action]
        with requests.Session() as session:
            session.trust_env = False
            resp = session.post(url, json={"command": cmd, "from_user": "web"}, timeout=15)
        data = resp.json() if resp.headers.get("Content-Type", "").startswith("application/json") else {}
        reply = data.get("reply") or f"已向 {label} 发送 {cmd}"
        return {"code": 0, "ok": resp.status_code == 200, "message": str(reply)[:300]}
