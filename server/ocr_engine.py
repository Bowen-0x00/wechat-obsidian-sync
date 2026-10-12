"""本地轻量级 OCR 引擎模块 (基于 RapidOCR ONNX，含低内存保护与长图分块防卡死机制)."""

import gc
import io
import os
from typing import List, Optional
import requests
from loguru import logger

# 全局单例
_ocr_instance = None
_ocr_init_failed = False


def has_sufficient_memory(min_available_mb: int = 450) -> bool:
    """检测 Linux 服务器当前可用物理内存是否充足，防止小内存云主机 OOM 卡死."""
    if os.path.exists("/proc/meminfo"):
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        avail_kb = int(line.split()[1])
                        avail_mb = avail_kb // 1024
                        if avail_mb < min_available_mb:
                            logger.warning(f"[OCR] 服务器可用内存仅剩 {avail_mb}MB (< {min_available_mb}MB)，触发防卡死保护，跳过本地 ONNX 推理")
                            return False
                        return True
        except Exception:
            pass
    return True


def get_ocr_engine():
    """获取或延迟初始化 RapidOCR 单例 (强制单线程与小尺寸检测框，限制 CPU 与内存占用)."""
    global _ocr_instance, _ocr_init_failed
    if not has_sufficient_memory(450):
        return None
    if _ocr_instance is not None:
        return _ocr_instance
    if _ocr_init_failed:
        return None

    try:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_instance = RapidOCR(
            intra_op_num_threads=1,
            inter_op_num_threads=1,
            det_limit_side_len=640
        )
        logger.info("[OCR] RapidOCR 本地轻量引擎初始化成功 (单线程防卡死模式)")
        return _ocr_instance
    except Exception as e:
        _ocr_init_failed = True
        logger.warning(f"[OCR] RapidOCR 初始化失败或未安装 (将跳过本地 OCR): {e}")
        return None


def download_image_bytes(url: str, timeout: int = 12) -> Optional[bytes]:
    """安全下载外部图片 (自动规避微信防盗链，限制最大读取体积 8MB)."""
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
        if r.status_code == 200 and 100 < len(r.content) <= 8 * 1024 * 1024:
            return r.content
        else:
            logger.warning(f"[OCR] 下载图片失败或体积超限 (HTTP {r.status_code}, size={len(r.content)}): {url[:80]}")
            return None
    except Exception as e:
        logger.error(f"[OCR] 下载图片网络异常: {e} URL: {url[:80]}")
        return None


def _prepare_safe_image_slices(image_bytes: bytes, max_width: int = 960, slice_height: int = 1200, max_slices: int = 2) -> List[bytes]:
    """
    将大图或超长微信长图缩放并切分为安全的轻量切片，彻底杜绝超长图直接送入 ONNX 导致内存暴涨卡死.
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")

        # 1. 限制宽度不超过 max_width (如 960px)
        if img.width > max_width:
            scale = max_width / img.width
            new_h = max(1, int(img.height * scale))
            img = img.resize((max_width, new_h), Image.Resampling.BILINEAR)

        # 2. 若高度在安全范围内，直接输出单张 JPEG
        if img.height <= slice_height:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            return [buf.getvalue()]

        # 3. 若为微信超长条漫/长图，仅截取前 max_slices 段进行识别
        slices = []
        for idx in range(max_slices):
            top = idx * slice_height
            if top >= img.height:
                break
            bottom = min(img.height, top + slice_height)
            if bottom - top < 60:
                break
            crop_img = img.crop((0, top, img.width, bottom))
            buf = io.BytesIO()
            crop_img.save(buf, format="JPEG", quality=80)
            slices.append(buf.getvalue())
        return slices
    except Exception as e:
        logger.warning(f"[OCR] 图片安全切片预处理失败: {e}")
        return [image_bytes]


class OCREngine:
    """本地 OCR 识别管理器."""

    @classmethod
    def extract_text_from_bytes(cls, image_bytes: bytes, min_score: float = 0.45) -> str:
        """从图片字节流中安全提取文本 (自动切分超长图并回收内存)."""
        if not image_bytes:
            return ""
        engine = get_ocr_engine()
        if not engine:
            return ""

        try:
            slices = _prepare_safe_image_slices(image_bytes)
            lines = []
            for s_bytes in slices:
                if not has_sufficient_memory(400):
                    break
                results, _ = engine(s_bytes)
                if not results:
                    continue
                for item in results:
                    if len(item) >= 2:
                        text = str(item[1]).strip()
                        score = float(item[2]) if len(item) > 2 else 1.0
                        if text and score >= min_score:
                            lines.append(text)
            gc.collect()
            return "\n".join(lines).strip()
        except Exception as e:
            logger.error(f"[OCR] 识别图片异常: {e}")
            return ""

    @classmethod
    def extract_text_from_images(cls, image_urls: List[str], max_images: int = 3) -> str:
        """批量下载并提取多张图片中的文字 (默认最多处理前 3 张关键图片，防止高负载阻塞)."""
        if not image_urls:
            return ""
        if not has_sufficient_memory(450):
            return ""

        target_urls = image_urls[:max_images]
        logger.info(f"[OCR] 开始处理前 {len(target_urls)} 张推文内嵌图片...")

        extracted_sections = []
        for idx, url in enumerate(target_urls, 1):
            if not has_sufficient_memory(400):
                break
            img_data = download_image_bytes(url)
            if not img_data:
                continue

            txt = cls.extract_text_from_bytes(img_data)
            if txt:
                extracted_sections.append(f"【图 {idx} 识别文字】\n{txt}")

        full_ocr = "\n\n".join(extracted_sections).strip()
        logger.info(f"[OCR] 识别完成，成功提取文字长度: {len(full_ocr)}")
        return full_ocr
