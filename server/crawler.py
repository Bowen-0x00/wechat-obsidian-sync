"""网页与公众号文章正文抓取与清洗模块."""

import re
import requests
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from bs4 import BeautifulSoup, NavigableString, Tag
from loguru import logger


@dataclass
class CrawledArticle:
    title: str
    author: str
    content_text: str               # 纯文本 (用于 LLM 分析)
    content_markdown: str = ""      # 转换后的完整 Markdown (含排版与图片)
    url: str = ""
    summary_hint: str = ""
    images: List[str] = field(default_factory=list) # 文章包含的图片链接


class ArticleCrawler:
    """文章与网页正文抓取器."""

    def __init__(self, timeout: int = 15, zhihu_cookie: str = "", proxy: Optional[str] = None):
        self.timeout = timeout
        self.zhihu_cookie = (zhihu_cookie or "").strip()
        self.proxy = proxy
        self.session = requests.Session()
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        # 微信公众号请求头候选组：使用带 WindowsWechat 客户端指纹和 Referer 的请求头，能有效避开云端机房 IP 触发的验证码拦截
        self.wechat_headers_candidates = [
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
                    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x6309092b) XWEB/11275"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://mp.weixin.qq.com/",
            },
            {
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.48(0x18003028) NetType/WIFI Language/zh_CN"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh-Hans;q=0.9",
                "Referer": "https://mp.weixin.qq.com/",
            }
        ]
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        })
    def set_zhihu_cookie(self, cookie: str):
        """动态更新知乎 Cookie."""
        self.zhihu_cookie = (cookie or "").strip()
        logger.info(f"[Crawler] 知乎 Cookie 已热更新 (长度: {len(self.zhihu_cookie)})")

    def set_proxy(self, proxy: Optional[str]):
        """动态配置网络代理."""
        self.proxy = proxy
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        else:
            self.session.proxies = {}

    def crawl(self, url: str, title_hint: str = "") -> CrawledArticle:
        """根据 URL 抓取网页标题、作者与纯文本正文以及完整 Markdown."""
        clean_url = url.strip()
        # 清洗可能存在的 HTML 转义符号 (例如链接中 &amp; 变成 &)
        import html
        from urllib.parse import urlparse, parse_qs, unquote
        clean_url = html.unescape(clean_url)
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url

        # 解析知乎重定向链接 (如 https://link.zhihu.com/?target=...)
        if "link.zhihu.com" in clean_url:
            try:
                parsed = urlparse(clean_url)
                qs = parse_qs(parsed.query)
                if "target" in qs:
                    clean_url = unquote(qs["target"][0])
            except Exception:
                pass

        # 处理知乎短链接 (如 https://v.zhihu.com/xxx)
        if "v.zhihu.com" in clean_url:
            try:
                resp = self.session.head(clean_url, allow_redirects=True, timeout=self.timeout)
                clean_url = resp.url
            except Exception:
                pass

        # 优先分流知乎平台专属解析引擎
        if "zhihu.com" in clean_url:
            return self._crawl_zhihu(clean_url, title_hint)

        try:
            if "mp.weixin.qq.com" in clean_url:
                resp = None
                for headers in self.wechat_headers_candidates:
                    resp = self.session.get(clean_url, headers=headers, timeout=self.timeout)
                    # 如果未被重定向到验证码页面，且成功包含正文或标题节点，立即解析
                    if "wappoc_appmsgcaptcha" not in resp.url and ("activity-name" in resp.text or "js_content" in resp.text):
                        resp.encoding = "utf-8"
                        return self._parse_html(resp.text, clean_url, title_hint)
                # 兜底解析
                if resp is not None:
                    resp.encoding = "utf-8"
                    return self._parse_html(resp.text, clean_url, title_hint)
                return self._parse_html("", clean_url, title_hint)
            else:
                resp = self.session.get(clean_url, headers=self.session.headers, timeout=self.timeout)
                if resp.encoding in (None, "ISO-8859-1"):
                    resp.encoding = "utf-8"
                else:
                    resp.encoding = resp.encoding or "utf-8"
                return self._parse_html(resp.text, clean_url, title_hint)
        except Exception as e:
            logger.warning(f"[Crawler] 抓取网页失败 ({clean_url}): {e}")
            return CrawledArticle(
                title=title_hint or clean_url,
                author="",
                content_text="",
                content_markdown="",
                url=clean_url,
                summary_hint="",
                images=[]
            )
    def _html_to_markdown(self, elem) -> tuple[str, List[str]]:
        """把 HTML 节点转换为清晰易读的 Markdown，提取内嵌图片链接."""
        if not elem:
            return "", []

        output = []
        images = []

        def walk(node):
            if isinstance(node, NavigableString):
                text = str(node)
                if text:
                    output.append(text)
                return

            if not isinstance(node, Tag):
                return

            if node.name in ["script", "style", "svg"]:
                return

            # 图片解析
            if node.name == "img":
                src = node.get("data-src") or node.get("src") or ""
                src = src.strip()
                if src and not src.startswith("data:image"):
                    images.append(src)
                    alt = (node.get("alt") or "图片").strip()
                    output.append(f"\n\n![{alt}]({src})\n\n")
                return

            # 标题
            if node.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                level = int(node.name[1])
                output.append(f"\n\n{'#' * level} ")
                for child in node.children:
                    walk(child)
                output.append("\n\n")
                return

            # 段落与容器
            if node.name in ["p", "section"]:
                output.append("\n\n")
                for child in node.children:
                    walk(child)
                return

            if node.name == "br":
                output.append("\n")
                return

            if node.name in ["strong", "b"]:
                output.append("**")
                for child in node.children:
                    walk(child)
                output.append("**")
                return

            if node.name in ["em", "i"]:
                output.append("*")
                for child in node.children:
                    walk(child)
                output.append("*")
                return

            if node.name in ["blockquote"]:
                output.append("\n\n> ")
                for child in node.children:
                    walk(child)
                output.append("\n\n")
                return

            if node.name == "a":
                href = node.get("href", "").strip()
                link_text = []
                for child in node.children:
                    if isinstance(child, NavigableString):
                        link_text.append(str(child))
                    elif isinstance(child, Tag):
                        link_text.append(child.get_text(strip=True))
                t = "".join(link_text).strip()
                if href and t:
                    output.append(f"[{t}]({href})")
                elif t:
                    output.append(t)
                return

            for child in node.children:
                walk(child)

        walk(elem)
        raw_md = "".join(output)
        clean_md = re.sub(r'\n{3,}', '\n\n', raw_md).strip()
        return clean_md, images
    def _crawl_zhihu(self, url: str, title_hint: str = "") -> CrawledArticle:
        """知乎平台定制解析器 (支持问答、专栏文章与短想法，兼顾 Cookie API 与防爬兜底)."""
        logger.info(f"[Crawler] 开始解析知乎链接: {url}")

        # 1. 识别 URL 结构类型
        ans_match = re.search(r'zhihu\.com/question/(\d+)/answer/(\d+)', url)
        q_match = re.search(r'zhihu\.com/question/(\d+)', url)
        art_match = re.search(r'zhuanlan\.zhihu\.com/p/(\d+)', url)

        zhihu_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "x-requested-with": "fetch",
        }
        if self.zhihu_cookie:
            zhihu_headers["cookie"] = self.zhihu_cookie

        # 2. 问答单条回答解析 (带 Cookie 时优先 API)
        if ans_match:
            qid, aid = ans_match.group(1), ans_match.group(2)
            zhihu_headers["referer"] = f"https://www.zhihu.com/question/{qid}/answer/{aid}"
            api_url = f"https://www.zhihu.com/api/v4/answers/{aid}?include=content,excerpt,author,question,voteup_count"
            try:
                resp = self.session.get(api_url, headers=zhihu_headers, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    q_title = data.get("question", {}).get("title", "")
                    title = q_title or title_hint or f"知乎问答 (Q:{qid})"
                    author = data.get("author", {}).get("name", "知乎答主")
                    raw_html = data.get("content", "")
                    excerpt = data.get("excerpt", "")
                    soup = BeautifulSoup(raw_html, "html.parser")
                    content_markdown, images = self._html_to_markdown(soup)
                    content_text = soup.get_text(separator="\n", strip=True) or excerpt
                    logger.info(f"[Crawler] 知乎回答 API 成功提取: 《{title[:30]}》 作者: {author}")
                    return CrawledArticle(
                        title=title,
                        author=author,
                        content_text=content_text[:8000],
                        content_markdown=content_markdown,
                        url=url,
                        images=images
                    )
            except Exception as e:
                logger.warning(f"[Crawler] 知乎回答 API 异常: {e}")

        # 3. 专栏文章解析
        elif art_match:
            pid = art_match.group(1)
            zhihu_headers["referer"] = f"https://zhuanlan.zhihu.com/p/{pid}"
            api_url = f"https://www.zhihu.com/api/v4/articles/{pid}?include=content,excerpt,author,title"
            try:
                resp = self.session.get(api_url, headers=zhihu_headers, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    title = data.get("title") or title_hint or f"知乎专栏 (P:{pid})"
                    author = data.get("author", {}).get("name", "知乎作者")
                    raw_html = data.get("content", "")
                    soup = BeautifulSoup(raw_html, "html.parser")
                    content_markdown, images = self._html_to_markdown(soup)
                    content_text = soup.get_text(separator="\n", strip=True) or data.get("excerpt", "")
                    logger.info(f"[Crawler] 知乎专栏 API 成功提取: 《{title[:30]}》 作者: {author}")
                    return CrawledArticle(
                        title=title,
                        author=author,
                        content_text=content_text[:8000],
                        content_markdown=content_markdown,
                        url=url,
                        images=images
                    )
            except Exception as e:
                logger.warning(f"[Crawler] 知乎专栏 API 异常: {e}")

        # 4. 纯问题主页解析
        elif q_match:
            qid = q_match.group(1)
            zhihu_headers["referer"] = f"https://www.zhihu.com/question/{qid}"
            api_url = f"https://www.zhihu.com/api/v4/questions/{qid}?include=detail,excerpt,author,title"
            try:
                resp = self.session.get(api_url, headers=zhihu_headers, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    title = data.get("title") or title_hint or f"知乎问题 (Q:{qid})"
                    author = data.get("author", {}).get("name", "")
                    detail_html = data.get("detail", "")
                    soup = BeautifulSoup(detail_html, "html.parser")
                    content_markdown, images = self._html_to_markdown(soup)
                    content_text = soup.get_text(separator="\n", strip=True) or data.get("excerpt", "")
                    return CrawledArticle(
                        title=title,
                        author=author,
                        content_text=content_text[:8000],
                        content_markdown=content_markdown,
                        url=url,
                        images=images
                    )
            except Exception as e:
                logger.warning(f"[Crawler] 知乎问题 API 异常: {e}")

        # 5. 常规网页抓取尝试 (若未被反爬 WAF 拦截)
        try:
            web_headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
            if self.zhihu_cookie:
                web_headers["cookie"] = self.zhihu_cookie
            resp = self.session.get(url, headers=web_headers, timeout=self.timeout)
            if resp.status_code == 200:
                parsed = self._parse_html(resp.text, url, title_hint)
                if parsed.content_text and not parsed.summary_hint:
                    return parsed
        except Exception as e:
            logger.debug(f"[Crawler] 知乎网页直接抓取受阻: {e}")

        # 6. 反爬保护兜底：严禁返回知乎 anti-spider 占位标语！
        logger.warning(f"[Crawler] 知乎链接触发反爬拦截或 Cookie 需更新 ({url})，进入安全降级模式")
        return CrawledArticle(
            title=title_hint or url,
            author="",
            content_text="",
            content_markdown="",
            url=url,
            summary_hint="[知乎反爬限制]"
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
            if not title:
                # 尝试从 js 中提取 msg_title
                title_match = re.search(r'var\s+msg_title\s*=\s*[\'"]([^\'"]+)[\'"]', html)
                if title_match:
                    title = title_match.group(1).strip()

            author = ""
            a_tag = soup.find(id="js_name") or soup.find(class_="rich_media_meta_text")
            if a_tag:
                author = a_tag.get_text(strip=True)
            if not author:
                author_match = re.search(r'var\s+nickname\s*=\s*[\'"]([^\'"]+)[\'"]', html)
                if author_match:
                    author = author_match.group(1).strip()

            content_div = soup.find(id="js_content")
            if content_div:
                # 纯文本抽取
                for s in content_div(["script", "style", "svg"]):
                    s.decompose()
                content_text = content_div.get_text(separator="\n", strip=True)
                content_markdown, images = self._html_to_markdown(content_div)
            else:
                content_text = ""
                content_markdown = ""
                images = []

            return CrawledArticle(
                title=title or title_hint or "微信公众号文章",
                author=author,
                content_text=content_text[:8000],  # 截取前 8000 字供大模型精读
                content_markdown=content_markdown,
                url=url,
                images=images
            )

        # 2. 通用网页解析
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside"]):
            tag.decompose()

        title = ""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
        elif soup.title and soup.title.string:
            title = soup.title.string.strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text(strip=True)

        title = title or title_hint or url

        author = ""
        meta_author = soup.find("meta", attrs={"name": "author"}) or soup.find("meta", property="article:author")
        if meta_author and meta_author.get("content"):
            author = meta_author["content"].strip()

        main_elem = soup.find("article") or soup.find("main") or soup.find("body")
        if main_elem:
            content_text = main_elem.get_text(separator="\n", strip=True)
            content_text = re.sub(r'\n{3,}', '\n\n', content_text)
        # 检测知乎或其它网站反爬占位页，避免误将反爬标语当作文章正文
        anti_spider_signals = [
            "知乎，让每一次点击都充满意义",
            "你似乎来到了没有知识存在的荒原",
            "wappoc_appmsgcaptcha",
            "请您登录后查看更多专业优质内容",
            "403 Forbidden",
            "Access Denied",
            "Attention Required! | Cloudflare",
            "robot or human"
        ]
        if any(signal in content_text for signal in anti_spider_signals) or any(signal in title for signal in anti_spider_signals):
            logger.warning(f"[Crawler] 检测到目标站点反爬提示标语，舍弃占位文本: {url}")
            return CrawledArticle(
                title=title_hint or url,
                author="",
                content_text="",
                content_markdown="",
                url=url,
                summary_hint="[反爬拦截]"
            )

            content_markdown, images = self._html_to_markdown(main_elem)
        else:
            content_text = ""
            content_markdown = ""
            images = []

        return CrawledArticle(
            title=title,
            author=author,
            content_text=content_text[:8000],
            content_markdown=content_markdown,
            url=url,
            images=images
        )
