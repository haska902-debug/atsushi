"""顔検出・照合（OpenCV YuNet + SFace）。

参照写真に写っている人物の顔特徴量を登録し、各写真に同じ人物が
写っているかどうかをコサイン類似度で判定する。
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MODEL_FILES = {
    "detector": (
        "face_detection_yunet_2023mar.onnx",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
        "models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
    "recognizer": (
        "face_recognition_sface_2021dec.onnx",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
        "models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ),
}

DEFAULT_MODEL_DIR = Path.home() / ".cache" / "photo_organizer" / "models"

# SFace のコサイン類似度の推奨しきい値（これ以上なら同一人物）
DEFAULT_THRESHOLD = 0.363

# 検出処理を速くするため、長辺をこのサイズまで縮小してから顔を探す
DETECT_MAX_SIDE = 1280


def ensure_models(model_dir: Path = DEFAULT_MODEL_DIR) -> dict[str, Path]:
    """モデルファイルが無ければダウンロードしてパスを返す。"""
    model_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, (filename, url) in MODEL_FILES.items():
        path = model_dir / filename
        if not path.exists() or path.stat().st_size < 10_000:
            print(f"顔認識モデルをダウンロード中: {filename}")
            tmp = path.with_suffix(".part")
            urllib.request.urlretrieve(url, tmp)
            tmp.replace(path)
        paths[key] = path
    return paths


def pil_to_bgr(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)


class FaceMatcher:
    def __init__(
        self,
        model_dir: Path = DEFAULT_MODEL_DIR,
        threshold: float = DEFAULT_THRESHOLD,
        min_face_score: float = 0.7,
    ):
        paths = ensure_models(model_dir)
        self.detector = cv2.FaceDetectorYN.create(
            str(paths["detector"]), "", (320, 320), min_face_score
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(paths["recognizer"]), "")
        self.threshold = threshold
        self.references: list[np.ndarray] = []

    def face_features(self, image: Image.Image) -> list[tuple[np.ndarray, float]]:
        """画像内の各顔について (特徴量, 顔の面積) のリストを返す。"""
        img = pil_to_bgr(image)
        h, w = img.shape[:2]
        scale = min(1.0, DETECT_MAX_SIDE / max(h, w))
        if scale < 1.0:
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            h, w = img.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(img)
        if faces is None:
            return []
        results = []
        for face in faces:
            aligned = self.recognizer.alignCrop(img, face)
            feature = self.recognizer.feature(aligned)
            results.append((feature.copy(), float(face[2] * face[3])))
        return results

    def add_reference(self, image: Image.Image) -> bool:
        """参照写真の中で一番大きな顔をその人物として登録する。"""
        faces = self.face_features(image)
        if not faces:
            return False
        feature, _ = max(faces, key=lambda f: f[1])
        self.references.append(feature)
        return True

    def similarity(self, image: Image.Image) -> float | None:
        """写真内の顔と参照人物との最大類似度。顔が無ければ None。"""
        if not self.references:
            raise RuntimeError("参照写真が登録されていません")
        faces = self.face_features(image)
        if not faces:
            return None
        return max(
            self.recognizer.match(ref, feature, cv2.FaceRecognizerSF_FR_COSINE)
            for feature, _ in faces
            for ref in self.references
        )

    def is_match(self, score: float | None) -> bool:
        return score is not None and score >= self.threshold
