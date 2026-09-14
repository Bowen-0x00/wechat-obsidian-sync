#!/usr/bin/env python3
"""WeChat Obsidian 自动同步与部署脚本 (本地 -> 阿里云)."""

import os
import sys
import subprocess
import tempfile
import tarfile
from pathlib import Path

REMOTE_HOST = os.environ.get("ALIYUN_HOST", "aliyun")
REMOTE_DIR = os.environ.get("ALIYUN_DIR", "/root/wechat_obsidian")

INCLUDE_ITEMS = [
    "server",
    "deploy",
    "config.yaml",
    "requirements.txt"
]

EXCLUDE_PATTERNS = {
    "__pycache__",
    ".git",
    "data"  # 保护服务器上的 inbox.db 与图片缓存不被覆盖
}


def should_exclude(tarinfo: tarfile.TarInfo) -> bool:
    parts = Path(tarinfo.name).parts
    for p in parts:
        if p in EXCLUDE_PATTERNS or p.endswith(".pyc"):
            return True
    return False


def main():
    print("=" * 60)
    print(f"🚀 WeChat Obsidian 服务同步 -> 阿里云 ({REMOTE_HOST})")
    print("=" * 60)

    base_dir = Path(__file__).resolve().parent

    print(f"[*] 检查与远程主机 [{REMOTE_HOST}] 的连接...")
    test_cmd = ["ssh", "-o", "ConnectTimeout=5", REMOTE_HOST, "echo OK"]
    try:
        res = subprocess.run(test_cmd, capture_output=True, text=True, check=True)
        if "OK" not in res.stdout:
            raise RuntimeError("SSH 握手返回异常")
        print("    SSH 连接畅通！")
    except Exception as e:
        print(f"\n[错误] 无法连接到远程主机 {REMOTE_HOST}: {e}")
        sys.exit(1)

    print(f"[*] 确保远程目录存在: {REMOTE_DIR}")
    subprocess.run(["ssh", REMOTE_HOST, f"mkdir -p {REMOTE_DIR}"], check=True)

    print("[*] 正在打包服务端源码 (排除本地缓存与数据库)...")
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_tar_path = tmp.name

    try:
        with tarfile.open(tmp_tar_path, "w:gz") as tar:
            for item in INCLUDE_ITEMS:
                full_path = base_dir / item
                if full_path.exists():
                    tar.add(str(full_path), arcname=item, filter=lambda ti: None if should_exclude(ti) else ti)

        print(f"[*] 正在推送至 {REMOTE_HOST}:{REMOTE_DIR} ...")
        with open(tmp_tar_path, "rb") as f:
            proc = subprocess.Popen(
                ["ssh", REMOTE_HOST, f"tar -xzf - -C {REMOTE_DIR}"],
                stdin=f,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                print(f"[错误] 解压推送失败: {stderr.decode()}")
                sys.exit(1)

        print("    服务端代码同步完成！")

    finally:
        if os.path.exists(tmp_tar_path):
            try:
                os.remove(tmp_tar_path)
            except Exception:
                pass

    # 注册或重启服务
    print("[*] 配置并重启远程 wechat_obsidian 服务...")
    setup_cmd = (
        "cp /root/wechat_obsidian/deploy/wechat_obsidian.service /etc/systemd/system/ && "
        "systemctl daemon-reload && "
        "systemctl enable --now wechat_obsidian && "
        "systemctl restart wechat_obsidian"
    )
    subprocess.run(["ssh", REMOTE_HOST, setup_cmd], check=True)
    print("🎉 [成功] 阿里云上的 wechat_obsidian 服务已启动并载入最新代码！")

    print("=" * 60)
    print("✅ 一键同步完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
