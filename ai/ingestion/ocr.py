from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol

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
            from paddleocr import PaddleOCR
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
