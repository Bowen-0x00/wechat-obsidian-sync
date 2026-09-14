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
        self.client: Optional[OpenAI] = None

        if self.enable:
            http_client = httpx.Client(timeout=40.0, proxy=proxy) if proxy else httpx.Client(timeout=40.0)
            self.client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                http_client=http_client
            )
            logger.info(f"[LLM] 已初始化大模型引擎 (模型: {model}, 代理: {proxy or '直连'})")
        else:
            logger.warning("[LLM] 大模型引擎已停用或未配置 API Key")
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

        user_prompt = f"""文章标题: {title}
文章链接: {url}

文章正文截取:
{text[:4000]}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                response_format={"type": "json_object"}
            )
            raw = response.choices[0].message.content or "{}"
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
                "tldr": text[:150] + "...",
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            raw = response.choices[0].message.content or "{}"
            data = self._parse_json(raw)
            tags = [t if t.startswith("#") else f"#{t}" for t in data.get("tags", [])]
            return tags[:2] or ["#随想"]
        except Exception as e:
            logger.error(f"[LLM] 闪念打标签异常: {e}")
            return ["#随想"]

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
