"""VideoAdapter — extracts audio transcript and key frames from video files."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Dict, List, Optional

from app.agents.schemas import EvidenceObject, ReviewFlag
from app.agents.extraction.adapters.base import IProcessEvidenceAdapter
from app.agents.extraction.adapters.audio import AudioAdapter, _fmt_ts

logger = logging.getLogger(__name__)


class VideoAdapter(IProcessEvidenceAdapter):
    """
    Processes video files.

    Pipeline:
      1. Extract audio track and transcribe via AudioAdapter (Azure Speech)
      2. Sample frames using opencv-python-headless respecting frame_extraction_policy
      3. Run OCR on sampled frames via Azure AI Vision
    """

    source_type = "video"

    def __init__(self) -> None:
        self._audio_adapter = AudioAdapter()
        self._vision_endpoint = os.environ.get("AZURE_VISION_ENDPOINT", "")
        self._vision_key = os.environ.get("AZURE_VISION_KEY", "")

    @property
    def _vision_configured(self) -> bool:
        return bool(self._vision_endpoint)

    async def normalize(
        self,
        input_file: Dict[str, Any],
        blob_url: Optional[str] = None,
    ) -> List[EvidenceObject]:
        evidence: List[EvidenceObject] = []

        video_path = input_file.get("local_path") or await self._download_video(blob_url)
        frame_policy = input_file.get("frame_extraction_policy", {})

        # 1. Audio track → transcription
        if input_file.get("audio_detected", False) or input_file.get("audio_declared", False):
            audio_input = {**input_file, "source_type": "audio", "local_path": video_path}
            audio_evidence = await self._audio_adapter.normalize(audio_input)
            evidence.extend(audio_evidence)
        else:
            logger.info("VideoAdapter: no audio detected/declared in video; skipping transcription")

        # 2. Frame extraction → OCR
        if video_path:
            frame_evidence = await self._extract_frames(video_path, frame_policy)
            evidence.extend(frame_evidence)
        else:
            logger.warning("VideoAdapter: no video path; skipping frame extraction")
            evidence.append(self._stub_frame_evidence(input_file))

        return evidence

    # ------------------------------------------------------------------
    # Frame extraction + OCR
    # ------------------------------------------------------------------

    async def _extract_frames(
        self,
        video_path: str,
        frame_policy: Dict[str, Any],
    ) -> List[EvidenceObject]:
        try:
            import cv2  # type: ignore[import]
        except ImportError:
            logger.error("opencv-python-headless not installed; skipping frame extraction")
            return [self._stub_frame_evidence({"file_name": video_path})]

        sample_interval = int(frame_policy.get("sample_interval_sec", 5))
        scene_threshold = float(frame_policy.get("scene_change_threshold", 0.68))
        ocr_enabled = bool(frame_policy.get("ocr_enabled", True))
        ocr_trigger = frame_policy.get("ocr_trigger", "scene_change_only")

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        evidence: List[EvidenceObject] = []
        prev_gray = None
        frame_idx = 0
        last_sampled_sec = -sample_interval

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            current_sec = frame_idx / fps
            frame_idx += 1

            # Scene-change detection using mean-absolute-difference
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            is_scene_change = False
            if prev_gray is not None:
                diff = cv2.absdiff(prev_gray, gray).mean() / 255.0
                is_scene_change = diff > (1 - scene_threshold)
            prev_gray = gray

            should_sample = (
                (current_sec - last_sampled_sec) >= sample_interval
                or (is_scene_change and ocr_trigger in ("scene_change_only", "always"))
            )
            if not should_sample:
                continue
            last_sampled_sec = current_sec

            anchor = f"{_fmt_ts(current_sec)}-{_fmt_ts(current_sec + sample_interval)}"
            ocr_text = None
            if ocr_enabled and (ocr_trigger == "always" or is_scene_change):
                ocr_text = await self._run_ocr_on_frame(frame)

            evidence.append(
                EvidenceObject(
                    source_type="video",
                    document_type="ocr_frame",
                    anchor=anchor,
                    confidence=0.7 if ocr_text else 0.5,
                    text_snippet=ocr_text,
                    metadata={
                        "frame_sec": current_sec,
                        "scene_change": is_scene_change,
                        "policy": frame_policy,
                    },
                )
            )

        cap.release()
        logger.info("VideoAdapter: extracted %d frames from %s", len(evidence), video_path)
        return evidence

    async def _run_ocr_on_frame(self, frame) -> Optional[str]:
        if not self._vision_configured:
            return None
        try:
            import cv2  # type: ignore[import]
            from azure.ai.vision.imageanalysis import ImageAnalysisClient  # type: ignore[import]
            from azure.ai.vision.imageanalysis.models import VisualFeatures  # type: ignore[import]
            from azure.core.credentials import AzureKeyCredential  # type: ignore[import]

            _, buf = cv2.imencode(".jpg", frame)
            image_data = buf.tobytes()

            client = ImageAnalysisClient(
                endpoint=self._vision_endpoint,
                credential=AzureKeyCredential(self._vision_key),
            )
            result = client.analyze(
                image_data=image_data,
                visual_features=[VisualFeatures.READ],
            )
            if result.read and result.read.blocks:
                lines = [
                    line.text
                    for block in result.read.blocks
                    for line in block.lines
                ]
                return " | ".join(lines)
        except Exception as exc:
            logger.warning("VideoAdapter: OCR failed: %s", exc)
        return None

    @staticmethod
    async def _download_video(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        import aiohttp  # type: ignore[import]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    f.write(await resp.read())
            return f.name

    @staticmethod
    def _stub_frame_evidence(input_file: Dict[str, Any]) -> EvidenceObject:
        return EvidenceObject(
            source_type="video",
            document_type="ocr_frame",
            anchor="00:00:00-00:00:10",
            confidence=0.3,
            text_snippet="[Frame extraction unavailable]",
            metadata={"stub": True, "file_name": input_file.get("file_name")},
        )

    # ------------------------------------------------------------------
    # IProcessEvidenceAdapter
    # ------------------------------------------------------------------

    def extract_facts(self, evidence: List[EvidenceObject]) -> List[EvidenceObject]:
        return [e for e in evidence if e.text_snippet or e.document_type == "ocr_frame"]

    def render_review_notes(self, evidence: List[EvidenceObject]) -> List[ReviewFlag]:
        flags: List[ReviewFlag] = []
        speech_evidence = [e for e in evidence if e.document_type == "audio"]
        frame_evidence = [e for e in evidence if e.document_type == "ocr_frame"]

        if not speech_evidence:
            flags.append(ReviewFlag(
                code="frame_first_evidence",
                severity="warning",
                message="Video audio is not available; sequence is derived from frame evidence only.",
                requires_user_action=False,
            ))
        stub_frames = [e for e in frame_evidence if e.metadata.get("stub")]
        if stub_frames:
            flags.append(ReviewFlag(
                code="frame_extraction_unavailable",
                severity="warning",
                message="Frame extraction was not performed; Azure Vision or video path is unavailable.",
                requires_user_action=False,
            ))
        return flags
