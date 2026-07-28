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
    ) -> None:
        self.language = language
        self.device = device
        self.min_confidence = min_confidence


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
            return PaddleOCR(
                lang=self.language,
                device=self.device,
                use_doc_orientation_classify=True,
                use_doc_unwarping=False,
                use_textline_orientation=True,
            )
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

            for index, raw_text in enumerate(recognized_texts):
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