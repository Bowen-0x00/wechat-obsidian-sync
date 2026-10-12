"""本地轻量级 OCR 引擎模块 (基于 RapidOCR ONNX)."""

import io
from typing import List, Optional
import requests
from loguru import logger

# 全局单例
_ocr_instance = None
_ocr_init_failed = False


def get_ocr_engine():
    """获取或延迟初始化 RapidOCR 单例."""
    global _ocr_instance, _ocr_init_failed
    if _ocr_instance is not None:
        return _ocr_instance
    if _ocr_init_failed:
        return None

    try:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_instance = RapidOCR()
        logger.info("[OCR] RapidOCR 本地引擎初始化成功")
        return _ocr_instance
    except Exception as e:
        _ocr_init_failed = True
        logger.warning(f"[OCR] RapidOCR 初始化失败或未安装 (将跳过本地 OCR): {e}")
        return None


def download_image_bytes(url: str, timeout: int = 15) -> Optional[bytes]:
    """安全下载外部图片 (自动规避微信防盗链)."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
        }
        if "mmbiz.qpic.cn" in url or "weixin.qq.com" in url or "mp.weixin" in url:
            headers["Referer"] = "https://mp.weixin.qq.com/"
        elif "zhimg.com" in url or "zhihu.com" in url:
            headers["Referer"] = "https://www.zhihu.com/"

        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 100:
            return r.content
        else:
            logger.warning(f"[OCR] 下载图片失败 HTTP {r.status_code}: {url[:80]}")
            return None
    except Exception as e:
        logger.error(f"[OCR] 下载图片网络异常: {e} URL: {url[:80]}")
        return None


class OCREngine:
    """本地 OCR 识别管理器."""

    @classmethod
    def extract_text_from_bytes(cls, image_bytes: bytes, min_score: float = 0.45) -> str:
        """从图片字节流中提取文本."""
        if not image_bytes:
            return ""
        engine = get_ocr_engine()
        if not engine:
            return ""

        try:
            results, elapse = engine(image_bytes)
            if not results:
                return ""

            lines = []
            for item in results:
                # RapidOCR 返回格式: [[dt_boxes], text, score]
                if len(item) >= 2:
                    text = str(item[1]).strip()
                    score = float(item[2]) if len(item) > 2 else 1.0
                    if text and score >= min_score:
                        lines.append(text)

            return "\n".join(lines).strip()
        except Exception as e:
            logger.error(f"[OCR] 识别图片异常: {e}")
            return ""

    @classmethod
    def extract_text_from_images(cls, image_urls: List[str], max_images: int = 6) -> str:
        """批量下载并提取多张图片中的文字 (适用于纯图推文或图文混排)."""
        if not image_urls:
            return ""

        target_urls = image_urls[:max_images]
        logger.info(f"[OCR] 开始处理 {len(target_urls)} 张推文内嵌图片...")

        extracted_sections = []
        for idx, url in enumerate(target_urls, 1):
            img_data = download_image_bytes(url)
            if not img_data:
                continue

            txt = cls.extract_text_from_bytes(img_data)
            if txt:
                extracted_sections.append(f"【图 {idx} 识别文字】\n{txt}")

        full_ocr = "\n\n".join(extracted_sections).strip()
        logger.info(f"[OCR] 识别完成，成功提取文字长度: {len(full_ocr)}")
        return full_ocr
