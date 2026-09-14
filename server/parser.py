"""企业微信接收消息解析器."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional, List
from loguru import logger


@dataclass
class WeChatMessage:
    """结构化微信消息."""
    msg_id: str
    msg_type: str                   # 'text', 'link', 'image', 'file', 'voice'
    from_user: str
    create_time: int
    content: str = ""               # 文本正文
    title: str = ""                 # 链接标题或文件名
    description: str = ""           # 链接描述
    url: str = ""                   # 网页链接
    pic_url: str = ""               # 图片或图文封面链接
    media_id: str = ""              # 多媒体素材 ID
    event: str = ""                 # 事件名，如 kf_msg_or_event
    event_token: str = ""           # 客服拉取凭据 Token
    open_kfid: str = ""             # 客服 ID
    embedded_urls: List[str] = field(default_factory=list)

class MessageParser:
    """微信 XML 消息解析器."""

    URL_PATTERN = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+', re.IGNORECASE)

    @classmethod
    def parse_xml(cls, xml_text: str) -> Optional[WeChatMessage]:
        """将解密后的 XML 字符串解析为 WeChatMessage."""
        try:
            root = ET.fromstring(xml_text)
            
            def get_text(tag: str, default: str = "") -> str:
                elem = root.find(tag)
                return (elem.text or "").strip() if elem is not None else default

            msg_id = get_text("MsgId")
            msg_type = get_text("MsgType").lower()
            from_user = get_text("FromUserName")
            create_time = int(get_text("CreateTime", "0"))

            # 若 MsgId 为空（某些事件推送），用时间+用户生成临时 ID
            if not msg_id:
                msg_id = f"msg_{from_user}_{create_time}"

            content = get_text("Content")
            title = get_text("Title")
            description = get_text("Description")
            url = get_text("Url")
            pic_url = get_text("PicUrl")
            media_id = get_text("MediaId")
            event = get_text("Event")
            event_token = get_text("Token")
            open_kfid = get_text("OpenKfId")
            # 文本消息特殊处理：如果用户发送的纯文本是一串链接（如直接粘贴公众号链接）
            embedded_urls = []
            if msg_type == "text" and content:
                urls = cls.URL_PATTERN.findall(content)
                if urls:
                    embedded_urls = urls
                    # 如果文本几乎全是一条链接，自动升格具备 link 属性
                    if not url and len(urls) == 1 and (len(content) - len(urls[0])) < 10:
                        url = urls[0]
                        logger.info(f"[Parser] 纯文本自动识别为网页长链接: {url}")

            msg = WeChatMessage(
                msg_id=msg_id,
                msg_type=msg_type,
                from_user=from_user,
                create_time=create_time,
                content=content,
                title=title,
                description=description,
                url=url,
                pic_url=pic_url,
                media_id=media_id,
                event=event,
                event_token=event_token,
                open_kfid=open_kfid,
                embedded_urls=embedded_urls
            )

            logger.info(f"[Parser] 解析微信消息成功: 类型={msg_type}, ID={msg_id}")
            return msg

        except Exception as e:
            logger.error(f"[Parser] 解析 XML 失败: {e}\nXML: {xml_text}")
            return None
