"""网页与公众号文章正文抓取与清洗模块."""

import re
import requests
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class CrawledArticle:
    title: str
    author: str
    content_text: str
    url: str
    summary_hint: str = ""


class ArticleCrawler:
    """文章与网页正文抓取器."""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        })

    def crawl(self, url: str, title_hint: str = "") -> CrawledArticle:
        """根据 URL 抓取网页标题、作者与纯文本正文."""
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url

        try:
            resp = self.session.get(clean_url, timeout=self.timeout)
            resp.encoding = resp.apparent_encoding or "utf-8"
            html = resp.text
            return self._parse_html(html, clean_url, title_hint)
        except Exception as e:
            logger.warning(f"[Crawler] 抓取网页失败 ({clean_url}): {e}")
            return CrawledArticle(
                title=title_hint or clean_url,
                author="",
                content_text="",
                url=clean_url,
                summary_hint=""
            )

    def _parse_html(self, html: str, url: str, title_hint: str) -> CrawledArticle:
        """解析 HTML 并提取核心信息."""
        soup = BeautifulSoup(html, "html.parser")

        # 1. 针对微信公众号文章专门解析
        if "mp.weixin.qq.com" in url:
            title = ""
            t_tag = soup.find(id="activity-name")
            if t_tag:
                title = t_tag.get_text(strip=True)
            if not title:
                og_title = soup.find("meta", property="og:title")
                if og_title:
                    title = og_title.get("content", "").strip()

            author = ""
            a_tag = soup.find(id="js_name") or soup.find(class_="rich_media_meta_text")
            if a_tag:
                author = a_tag.get_text(strip=True)

            content_div = soup.find(id="js_content")
            if content_div:
                for s in content_div(["script", "style", "svg"]):
                    s.decompose()
                content_text = content_div.get_text(separator="\n", strip=True)
            else:
                content_text = ""

            return CrawledArticle(
                title=title or title_hint or "微信公众号文章",
                author=author,
                content_text=content_text[:8000],  # 截取前 8000 字供大模型精读
                url=url
            )

        # 2. 通用网页解析
        # 移除噪音标签
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside"]):
            tag.decompose()

        # 提取标题
        title = ""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
        elif soup.title and soup.title.string:
            title = soup.title.string.strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text(strip=True)

        title = title or title_hint or url

        # 提取作者
        author = ""
        meta_author = soup.find("meta", attrs={"name": "author"}) or soup.find("meta", property="article:author")
        if meta_author and meta_author.get("content"):
            author = meta_author["content"].strip()

        # 提取正文 (优先寻找 article / main，否则直接提取全部文本)
        main_elem = soup.find("article") or soup.find("main") or soup.find("body")
        if main_elem:
            content_text = main_elem.get_text(separator="\n", strip=True)
            # 清理多余空行
            content_text = re.sub(r'\n{3,}', '\n\n', content_text)
        else:
            content_text = ""

        return CrawledArticle(
            title=title,
            author=author,
            content_text=content_text[:8000],
            url=url
        )
