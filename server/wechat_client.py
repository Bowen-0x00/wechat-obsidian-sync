"""企业微信 API 客户端模块 (媒体资源下载与异步回复确认)."""

import os
import time
import requests
from typing import Optional
from loguru import logger


class WeComClient:
    """企业微信 API 交互客户端."""

    def __init__(self, corp_id: str, agent_id: int, secret: str, cache_dir: str = "data/images"):
        self.corp_id = corp_id.strip()
        self.agent_id = int(agent_id)
        self.secret = secret.strip()
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def get_access_token(self, force_refresh: bool = False) -> str:
        """获取企业微信 access_token."""
        now = time.time()
        if not force_refresh and self._token and now < self._token_expires_at:
            return self._token

        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        params = {"corpid": self.corp_id, "corpsecret": self.secret}

        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if data.get("errcode") != 0:
                raise RuntimeError(f"获取 Token 失败: {data.get('errmsg')}")

            self._token = data["access_token"]
            self._token_expires_at = now + data.get("expires_in", 7200) - 300
            return self._token
        except Exception as e:
            logger.error(f"[WeComClient] 获取 access_token 失败: {e}")
            raise

    def download_media(self, media_id: str, prefix: str = "img") -> Optional[str]:
        """通过 media_id 从微信官方服务器下载图片/文件."""
        if not media_id:
            return None

        try:
            token = self.get_access_token()
            url = f"https://qyapi.weixin.qq.com/cgi-bin/media/get?access_token={token}&media_id={media_id}"
            resp = requests.get(url, timeout=20, stream=True)

            if resp.status_code == 200:
                # 判断文件扩展名
                content_type = resp.headers.get("Content-Type", "")
                ext = ".jpg"
                if "png" in content_type:
                    ext = ".png"
                elif "gif" in content_type:
                    ext = ".gif"
                elif "webp" in content_type:
                    ext = ".webp"

                filename = f"{prefix}_{int(time.time())}{ext}"
                filepath = os.path.join(self.cache_dir, filename)

                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=32768):
                        f.write(chunk)

                logger.info(f"[WeComClient] 成功下载媒体图片: {filename} ({os.path.getsize(filepath)} 字节)")
                return filename
            else:
                logger.warning(f"[WeComClient] 下载媒体失败 HTTP {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"[WeComClient] 下载媒体资源异常: {e}")
            return None

    def send_confirmation(self, to_user: str, text: str) -> bool:
        """向用户发送一条收录确认消息 (应用消息通道)."""
        if not to_user:
            return False

        try:
            token = self.get_access_token()
            url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
            payload = {
                "touser": to_user,
                "msgtype": "text",
                "agentid": self.agent_id,
                "text": {"content": text},
                "safe": 0
            }
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("errcode") == 0:
                logger.debug(f"[WeComClient] 已向用户发送确认回复 -> {to_user}")
                return True
            else:
                logger.warning(f"[WeComClient] 发送确认回复失败: {data}")
                return False
        except Exception as e:
            logger.warning(f"[WeComClient] 发送微信回复异常: {e}")
            return False

    def sync_kf_messages(self, cursor: str = "", token: str = "", open_kfid: str = "", limit: int = 100) -> dict:
        """从微信客服拉取新消息列表."""
        access_token = self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token={access_token}"
        body = {
            "cursor": cursor,
            "token": token,
            "limit": limit,
            "voice_format": 0
        }
        if open_kfid:
            body["open_kfid"] = open_kfid

        try:
            resp = requests.post(url, json=body, timeout=15)
            data = resp.json()
            if data.get("errcode") == 0:
                return data
            else:
                logger.error(f"[WeComClient] 拉取微信客服消息失败: {data}")
                return {}
        except Exception as e:
            logger.error(f"[WeComClient] 拉取微信客服消息网络异常: {e}")
            return {}

    def send_kf_reply(self, touser: str, open_kfid: str, content: str) -> bool:
        """向微信客服会话中的用户发送文本回复."""
        if not touser or not open_kfid:
            return False

        try:
            access_token = self.get_access_token()
            url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg?access_token={access_token}"
            body = {
                "touser": touser,
                "open_kfid": open_kfid,
                "msgtype": "text",
                "text": {
                    "content": content
                }
            }
            resp = requests.post(url, json=body, timeout=10)
            data = resp.json()
            if data.get("errcode") == 0:
                logger.info(f"[WeComClient] 成功发送微信客服确认回复 -> {touser}")
                return True
            else:
                logger.warning(f"[WeComClient] 发送微信客服回复失败: {data}")
                return False
        except Exception as e:
            logger.error(f"[WeComClient] 发送微信客服回复异常: {e}")
            return False
