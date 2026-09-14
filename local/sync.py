"""本地 Obsidian 笔记同步客户端 (从云端拉取 -> 落盘写入 -> 回复确认)."""

import os
import sys
import time
import yaml
import argparse
import requests
from typing import List, Dict, Any
from loguru import logger

from writer import ObsidianWriter


class LocalSyncAgent:
    """本地同步引擎."""

    def __init__(self, config_path: str = "config.yaml"):
        if not os.path.exists(config_path):
            if os.path.exists("config.example.yaml"):
                config_path = "config.example.yaml"
            else:
                raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

        sync_cfg = self.cfg.get("sync", {})
        self.server_url = sync_cfg.get("server_url", "http://your-server-domain.com").rstrip("/")
        self.api_secret = sync_cfg.get("api_secret", "YOUR_CUSTOM_SYNC_SECRET_TOKEN")

        obs_cfg = self.cfg.get("obsidian", {})
        self.writer = ObsidianWriter(
            vault_path=obs_cfg.get("vault_path", "D:/Obsidian/workspace"),
            archive_mode=obs_cfg.get("archive_mode", "daily"),
            daily_folder=obs_cfg.get("daily_folder", "10-Journal&Planning/13-note"),
            inbox_file=obs_cfg.get("inbox_file", "00-Inbox/Inbox.md"),
            attachment_folder=obs_cfg.get("attachment_folder", "10-Journal&Planning/13-note/images"),
            server_base_url=self.server_url,
            api_secret=self.api_secret
        )

    def sync_once(self) -> int:
        """执行单次同步：拉取未同步笔记 -> 写入本地 Vault -> 提交确认."""
        sync_api = f"{self.server_url}/api/sync"
        ack_api = f"{self.server_url}/api/sync/ack"

        try:
            # 1. 从云端拉取未同步数据
            resp = requests.get(
                sync_api,
                params={"secret": self.api_secret, "limit": 50},
                timeout=15
            )
            if resp.status_code == 401:
                logger.error("[Sync] 同步认证失败！请检查 config.yaml 中的 api_secret 是否与云端一致")
                return 0
            if resp.status_code != 200:
                logger.warning(f"[Sync] 请求同步接口失败 HTTP {resp.status_code}")
                return 0

            data = resp.json()
            notes: List[Dict[str, Any]] = data.get("notes", [])
            if not notes:
                logger.debug("[Sync] 没有待同步的新笔记")
                return 0

            logger.info(f"[Sync] 发现 {len(notes)} 条新笔记，开始写入本地 Obsidian Vault...")

            # 2. 依次写入本地 Vault
            synced_ids = []
            for note in notes:
                success = self.writer.append_note(note)
                if success:
                    synced_ids.append(note["id"])

            # 3. 提交已同步确认，更新云端状态
            if synced_ids:
                ack_resp = requests.post(
                    ack_api,
                    params={"secret": self.api_secret},
                    json={"ids": synced_ids},
                    timeout=15
                )
                if ack_resp.status_code == 200:
                    logger.success(f"[Sync] 成功同步并确认 {len(synced_ids)} 条笔记入库！")
                else:
                    logger.warning(f"[Sync] 提交确认异常 HTTP {ack_resp.status_code}")

            return len(synced_ids)

        except requests.exceptions.ConnectionError:
            logger.warning("[Sync] 无法连接到云端服务器，将在下次重试")
            return 0
        except Exception as e:
            logger.error(f"[Sync] 同步过程中发生未预期异常: {e}")
            return 0

    def run_loop(self, interval_seconds: int = 60):
        """后台轮询常驻同步."""
        logger.info(f"[Sync] 启动本地后台自动同步守护进程 (轮询间隔: {interval_seconds} 秒)...")
        logger.info(f"目标 Obsidian 知识库: {self.writer.vault_path}")
        while True:
            try:
                self.sync_once()
            except Exception as e:
                logger.error(f"[Sync] 轮询异常: {e}")
            time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="WeChat to Obsidian 本地同步客户端")
    parser.add_argument("--once", action="store_true", help="单次同步后退出")
    parser.add_argument("--interval", type=int, default=60, help="轮询间隔 (秒，默认 60)")
    args = parser.parse_args()

    # 切换当前工作路径至项目根目录
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    agent = LocalSyncAgent("../config.yaml")

    if args.once:
        synced = agent.sync_once()
        print(f"单次同步完成，已同步 {synced} 条笔记")
    else:
        agent.run_loop(interval_seconds=args.interval)


if __name__ == "__main__":
    main()
