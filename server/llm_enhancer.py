"""大语言模型增强引擎 (生成 100 字核心速读与智能打标签)."""

import re
import json
import httpx
from typing import Dict, Any, List, Optional
from openai import OpenAI
from loguru import logger


class LLMEnhancer:
    """基于大模型的文章深度摘要与闪念打标签引擎."""

    def __init__(self, base_url: str, api_key: str, model: str = "deepseek-chat", temperature: float = 0.3, enable: bool = True, proxy: Optional[str] = None):
        self.enable = enable and bool(api_key) and api_key != "YOUR_LLM_API_KEY"
        self.model = model
        self.temperature = temperature
        self.base_url = base_url
        self.api_key = api_key
        self.proxy = proxy
        self.client: Optional[OpenAI] = None
        self.direct_client: Optional[OpenAI] = None

        if self.enable:
            http_client = httpx.Client(timeout=30.0, proxy=proxy) if proxy else httpx.Client(timeout=30.0)
            self.client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                http_client=http_client
            )
            if proxy:
                self.direct_client = OpenAI(
                    base_url=base_url,
                    api_key=api_key,
                    http_client=httpx.Client(timeout=30.0)
                )
            else:
                self.direct_client = self.client
            logger.info(f"[LLM] 已初始化大模型引擎 (首选模型: {model}, 代理: {proxy or '直连'})")
        else:
            logger.warning("[LLM] 大模型引擎已停用或未配置 API Key")

    def _call_chat_completions(self, messages: List[Dict[str, str]], response_format: Optional[Dict[str, str]] = None) -> str:
        """调用大模型，具备自动多候选模型故障转移与代理连接故障自愈能力."""
        candidate_models = [self.model, "gemini-3.1-pro-preview", "gemini-3.6-flash", "gemini-3.8-flash", "deepseek-chat"]
        seen = set()
        ordered_models = []
        for m in candidate_models:
            if m and m not in seen:
                seen.add(m)
                ordered_models.append(m)

        clients = [self.client]
        if self.direct_client and self.direct_client is not self.client:
            clients.append(self.direct_client)

        last_error = None
        for cli in clients:
            for m in ordered_models:
                try:
                    kwargs = {
                        "model": m,
                        "messages": messages,
                        "temperature": self.temperature,
                    }
                    if response_format:
                        kwargs["response_format"] = response_format
                    resp = cli.chat.completions.create(**kwargs)
                    content = resp.choices[0].message.content or ""
                    if content.strip():
                        if m != self.model:
                            logger.info(f"[LLM] 模型 [{self.model}] 不可用，已自动故障转移至候选模型 [{m}]")
                        return content
                except Exception as e:
                    last_error = e
                    logger.debug(f"[LLM] 候选模型 [{m}] 调用失败: {e}")
                    continue

        raise last_error or RuntimeError("所有大模型通道均不可用")

    def summarize_article(self, title: str, text: str, url: str) -> Dict[str, Any]:
        """对长文章提取 100 字核心摘要与 1~3 个 Obsidian 标签."""
        if not self.enable or not text:
            # 基础兜底
            return {
                "tldr": text[:150].strip() + ("..." if len(text) > 150 else ""),
                "key_points": [],
                "tags": ["#网页收藏"]
            }

        system_prompt = """你是一位高水平的个人知识管理专家（PKM）与科研阅读助手。
请阅读用户转发的文章正文，生成精炼的速读摘要，并提取 1~3 个符合知识库归档的标准 Obsidian 标签。

要求：
1. tldr: 严格控制在 80~120 字内，直击文章最核心观点或技术贡献，拒绝废话套话。
2. key_points: 提炼 2~3 个关键要点（每个要点 1 句话）。
3. tags: 1~3 个以 # 开头的分类标签（优先对齐计算机体系结构、AI硬件、编译、系统等领域，如 #计算机体系结构 #KVCache #AI编译器）。

请直接输出标准 JSON 格式：
{
  "tldr": "100字核心摘要",
  "key_points": ["核心要点1", "核心要点2"],
  "tags": ["#标签1", "#标签2"]
}"""
        clean_text = (text or "").strip()
        if len(clean_text) < 30 or clean_text in (title, url, "-"):
            user_prompt = f"""文章标题: {title}
文章链接: {url}

说明: 当前未能直接抓取到文章全文，请仅根据标题和链接主题，为用户提炼关于该主题的背景简介与核心价值（100字），并打上标准领域分类标签。"""
        else:
            user_prompt = f"""文章标题: {title}
文章链接: {url}

文章正文截取:
{clean_text[:4000]}"""

        try:
            raw = self._call_chat_completions(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"}
            )
            data = self._parse_json(raw)
            tags = [t if t.startswith("#") else f"#{t}" for t in data.get("tags", [])]
            return {
                "tldr": data.get("tldr", ""),
                "key_points": data.get("key_points", []),
                "tags": tags or ["#文章收藏"]
            }
        except Exception as e:
            logger.error(f"[LLM] 文章摘要生成异常: {e}")
            return {
                "tldr": f"《{title}》相关文章收藏与收录",
                "key_points": [],
                "tags": ["#文章收藏"]
            }

    def tag_thought(self, text: str) -> List[str]:
        """为纯文本闪念、随想或待办生成 1~2 个 Obsidian 标签."""
        if not self.enable or not text:
            return ["#随想"]

        system_prompt = """你是一个个人笔记打标签助手。请阅读用户的简短闪念、随笔或待办记录，自动生成 1~2 个最精准贴切的 Obsidian 标签。
要求：
- 标签以 # 开头（如 #想法 #待办 #体系结构 #读书笔记 #灵感 等）。
- 请直接输出标准 JSON：{"tags": ["#标签1", "#标签2"]}"""

        user_prompt = f"随手记内容:\n{text[:500]}"

        try:
            raw = self._call_chat_completions(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"}
            )
            data = self._parse_json(raw)
            tags = [t if t.startswith("#") else f"#{t}" for t in data.get("tags", [])]
            return tags[:2] or ["#随想"]
        except Exception as e:
            logger.error(f"[LLM] 闪念打标签异常: {e}")
            return ["#随想"]
    def chat_with_note(
        self,
        note: Dict[str, Any],
        question: str,
        history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """基于特定笔记的完整上下文与追问历史进行智能解答."""
        if not self.enable:
            return "⚠️ LLM 增强引擎未启用，请在 config.yaml 中配置 api_key。"

        title = note.get("title") or "未命名笔记"
        author = note.get("author") or ""
        url = note.get("url") or ""
        tldr = note.get("tldr") or ""
        key_points = note.get("key_points") or []
        content = note.get("content_markdown") or note.get("raw_content") or ""

        # 组装文章上下文
        context_parts = [
            f"【文章/笔记标题】: {title}",
        ]
        if author:
            context_parts.append(f"【作者/来源】: {author}")
        if url:
            context_parts.append(f"【原始链接】: {url}")
        if tldr:
            context_parts.append(f"【前期核心速读】: {tldr}")
        if key_points:
            context_parts.append(f"【前期要点】: " + "；".join(key_points))
        if content:
            # 控制在 6000 字符以内，留足 token 给对话
            context_parts.append(f"【正文参考】:\n{content[:6000]}")

        doc_context = "\n".join(context_parts)

        system_prompt = f"""你是一位深度的个人知识助理与学术/技术阅读助手。
请基于以下用户收录的笔记/文章内容，回答用户的追问。

--- 笔记上下文 ---
{doc_context}
--- 结束 ---

回答要求：
1. 严格依据上述笔记内容与事实作答；如笔记中未提及，请明确说明。
2. 语言条理清晰，层次分明，逻辑严密，适合企业微信或手机端阅读。
3. 尽量控制在 500 字以内，避免冗长废话，突出要点。"""

        messages = [{"role": "system", "content": system_prompt}]

        # 拼接最近历史追问
        if history:
            for item in history[-6:]:  # 最多保留最近 3 轮追问
                r = item.get("role", "user")
                c = item.get("content", "")
                if r in ("user", "assistant") and c:
                    messages.append({"role": r, "content": c})

        messages.append({"role": "user", "content": question})

        try:
            ans = self._call_chat_completions(messages=messages)
            return ans.strip() or "未能获取回答，请重试。"
        except Exception as e:
            logger.error(f"[LLM] 对话追问异常: {e}")
            return f"⚠️ 追问回答生成失败: {e}"

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """容错解析 JSON 字符串."""
        text = text.strip()
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if m:
            text = m.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m2 = re.search(r'\{[\s\S]*\}', text)
            if m2:
                try:
                    return json.loads(m2.group(0))
                except Exception:
                    pass
            return {}
