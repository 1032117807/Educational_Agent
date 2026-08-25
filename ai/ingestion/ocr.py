from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import base64
import json
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai.exceptions import DocumentParseError

@dataclass(frozen=True, slots=True)
class OCRResult:
    text: str
    average_confidence: float
    line_count: int

class OCRServiceProtocol(Protocol):
    def recognize(self, image: str | Path | Any) -> OCRResult:
        """识别图片或图像数组。"""


class PaddleOCRService:
    """PaddleOCR 3.x 的延迟加载适配器。"""

    def __init__(
        self,
        *,
        language: str = "ch",
        device: str = "cpu",
        min_confidence: float = 0.5,
        detection_model_name: str = "PP-OCRv5_mobile_det",
        detection_model_dir: Path | None = None,
        recognition_model_name: str = "PP-OCRv5_mobile_rec",
        recognition_model_dir: Path | None = None,
        use_doc_orientation: bool = False,
        use_textline_orientation: bool = False,
        enable_mkldnn: bool = False,
    ) -> None:
        self.language = language
        self.device = device
        self.min_confidence = min_confidence
        self.detection_model_name = detection_model_name
        self.detection_model_dir = self._resolve_model_dir(
            detection_model_dir,
            "文本检测",
        )
        self.recognition_model_name = recognition_model_name
        self.recognition_model_dir = self._resolve_model_dir(
            recognition_model_dir,
            "文本识别",
        )
        self.use_doc_orientation = use_doc_orientation
        self.use_textline_orientation = use_textline_orientation
        self.enable_mkldnn = enable_mkldnn

    @staticmethod
    def _resolve_model_dir(
        path: Path | None,
        label: str,
    ) -> str | None:
        if path is None:
            return None

        resolved = path.expanduser().resolve()
        if not resolved.is_dir():
            raise DocumentParseError(
                f"{label} OCR 模型目录不存在：{resolved}"
            )

        return str(resolved)


    @cached_property
    def pipeline(self) -> Any:
        """第一次真正执行 OCR 时才加载模型。"""

        try:
            # Keep PaddleOCR optional so the desktop release does not bundle
            # Paddle's large training/runtime stack. Remote OCR and native PDF
            # text extraction remain available without this dependency.
            PaddleOCR = import_module("paddleocr").PaddleOCR
        except ImportError as exc:
            raise DocumentParseError(
                "OCR 组件未安装。请安装 paddlepaddle 和 paddleocr。"
            ) from exc

        try:
            arguments: dict[str, object] = {
                "device": self.device,
                "text_detection_model_name": self.detection_model_name,
                "text_detection_model_dir": self.detection_model_dir,
                "text_recognition_model_name": self.recognition_model_name,
                "text_recognition_model_dir": self.recognition_model_dir,
                "use_doc_orientation_classify": self.use_doc_orientation,
                "use_doc_unwarping": False,
                "use_textline_orientation": self.use_textline_orientation,
                "enable_mkldnn": self.enable_mkldnn,
            }

            if (
                self.detection_model_dir is None
                and self.recognition_model_dir is None
            ):
                arguments["lang"] = self.language

            return PaddleOCR(**arguments)
        except Exception as exc:
            raise DocumentParseError(
                f"PaddleOCR 模型初始化失败：{exc}"
            ) from exc


    def recognize(self, image:str|Path|Any) -> OCRResult:
        source = str(image) if isinstance(image, Path) else image

        try:
            predictions = self.pipeline.predict(
                input=source,
                text_rec_score_thresh=self.min_confidence,
            )
        except Exception as exc:
            raise DocumentParseError(f"OCR 识别失败：{exc}") from exc

        lines: list[str] = []
        scores: list[float] = []

        for prediction in predictions:
            payload = prediction.json

            # PaddleOCR Result.json 通常将实际结果放在 res 中。
            if isinstance(payload, dict) and isinstance(payload.get("res"), dict):
                payload = payload["res"]

            if not isinstance(payload, dict):
                continue

            recognize_texts = payload.get("rec_texts") or []
            recognized_scores = payload.get("rec_scores") or []

            for index, raw_text in enumerate(recognize_texts):
                text = str(raw_text).strip()
                if not text:
                    continue

                score = (
                    float(recognized_scores[index])
                    if index < len(recognized_scores)
                    else 0.0
                )

                if score < self.min_confidence:
                    continue

                lines.append(text)
                scores.append(score)

        average_confidence = (
            sum(scores) / len(scores)
            if scores
            else 0.0
        )

        return OCRResult(
            text="\n".join(lines),
            average_confidence=average_confidence,
            line_count=len(lines),
        )


class OpenAICompatibleVisionOCRService:
    """OCR through a vision model exposed via OpenAI-compatible chat API."""

    def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def recognize(self, image: str | Path | Any) -> OCRResult:
        encoded = self._to_data_url(image)
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "Perform OCR. Return only the visible text in the image, preserving paragraphs. Do not explain."},
                {"type": "image_url", "image_url": {"url": encoded}},
            ]}],
        }
        url = self.base_url if self.base_url.endswith("/chat/completions") else f"{self.base_url}/chat/completions"
        request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise DocumentParseError(f"OCR API returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise DocumentParseError(f"OCR API unavailable: {exc.reason}") from exc
        try:
            content = decoded["choices"][0]["message"]["content"]
            text = content if isinstance(content, str) else str(content)
        except (KeyError, IndexError, TypeError) as exc:
            raise DocumentParseError("OCR API returned an invalid response") from exc
        return OCRResult(text=text.strip(), average_confidence=1.0, line_count=len([line for line in text.splitlines() if line.strip()]))

    @staticmethod
    def _to_data_url(image: str | Path | Any) -> str:
        if isinstance(image, (str, Path)):
            path = Path(image)
            data = path.read_bytes()
            mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        else:
            try:
                height, width, channels = image.shape
                import fitz
                pixmap = fitz.Pixmap(fitz.csRGB, width, height, image.tobytes(), False)
                data = pixmap.tobytes("png")
                mime = "image/png"
            except Exception as exc:
                raise DocumentParseError("Unable to encode image for OCR API") from exc
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


class FallbackOCRService:
    """Try remote OCR first; local CPU OCR remains available as a fallback."""

    def __init__(self, primary: OCRServiceProtocol, fallback: OCRServiceProtocol) -> None:
        self.primary = primary
        self.fallback = fallback

    def recognize(self, image: str | Path | Any) -> OCRResult:
        try:
            return self.primary.recognize(image)
        except Exception:
            return self.fallback.recognize(image)
