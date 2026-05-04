import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import librosa
from config import SAMPLE_RATE, N_MFCC


class AudioFeatureExtractor:

    def __init__(self, sr: int = SAMPLE_RATE, n_mfcc: int = N_MFCC):
        self.sr = sr
        self.n_mfcc = n_mfcc

    # ── Audio loading ─────────────────────────────────────────
    def load(self, path: str) -> np.ndarray:
        """Load audio: resample → mono → trim silence → normalize."""
        y, _ = librosa.load(path, sr=self.sr, mono=True)
        if y.size == 0:
            raise ValueError(f"Audio rỗng hoặc không đọc được: {path}")

        y, _ = librosa.effects.trim(y, top_db=20)
        if y.size == 0:
            raise ValueError(f"Audio chỉ chứa silence sau trim: {path}")

        peak = np.max(np.abs(y))
        if peak > 0:
            y = y / peak

        return y

    # ── Core feature computation (shared) ─────────────────────
    def _compute_features(self, y: np.ndarray):
        feats: list[float] = []

        # MFCC (mean + std)
        mfcc = librosa.feature.mfcc(y=y, sr=self.sr, n_mfcc=self.n_mfcc)
        feats.extend(np.mean(mfcc, axis=1).tolist())
        feats.extend(np.std(mfcc, axis=1).tolist())

        # Chroma
        chroma = librosa.feature.chroma_stft(y=y, sr=self.sr)
        feats.extend(np.mean(chroma, axis=1).tolist())

        # Spectral Centroid
        cen = librosa.feature.spectral_centroid(y=y, sr=self.sr)
        feats.append(float(np.mean(cen)))
        feats.append(float(np.std(cen)))

        # Spectral Rolloff
        roll = librosa.feature.spectral_rolloff(y=y, sr=self.sr, roll_percent=0.85)
        feats.append(float(np.mean(roll)))

        # Spectral Flux (FIXED)
        S = np.abs(librosa.stft(y))
        feats.append(float(np.mean(np.abs(np.diff(S, axis=1)) ** 2)))

        # ZCR
        zcr = librosa.feature.zero_crossing_rate(y)
        feats.append(float(np.mean(zcr)))

        # RMS Energy
        rms = librosa.feature.rms(y=y)
        feats.append(float(np.mean(rms)))

        # HNR
        y_h, _ = librosa.effects.hpss(y)
        total = float(np.sum(y ** 2)) + 1e-9
        feats.append(float(np.sum(y_h ** 2)) / total)

        # Onset Strength
        onset = librosa.onset.onset_strength(y=y, sr=self.sr)
        feats.append(float(np.mean(onset)))

        return feats, mfcc, cen, zcr, rms, onset

    # ── Feature scaling ───────────────────────────────────────
    # Fix #10: Chuẩn hóa per-feature để các feature có scale khác nhau
    # không bị dominate bởi feature có magnitude lớn (VD: MFCC vs ZCR)
    # Sử dụng thống kê ước lượng cho từng nhóm feature.
    _FEATURE_RANGES = {
        # (start_idx, end_idx, approx_mean, approx_std)
        "mfcc_mean":  (0, 40, 0.0, 80.0),
        "mfcc_std":   (40, 80, 25.0, 20.0),
        "chroma":     (80, 92, 0.35, 0.15),
        "centroid":   (92, 94, 2000.0, 1500.0),
        "rolloff":    (94, 95, 4000.0, 2000.0),
        "flux":       (95, 96, 0.3, 0.5),
        "zcr":        (96, 97, 0.08, 0.06),
        "rms":        (97, 98, 0.15, 0.1),
        "hnr":        (98, 99, 0.7, 0.2),
        "onset":      (99, 100, 2.0, 2.0),
    }

    def scale_features(self, vec: np.ndarray) -> np.ndarray:
        """Per-feature z-score normalization using estimated statistics."""
        scaled = vec.copy()
        for name, (start, end, mean, std) in self._FEATURE_RANGES.items():
            if std > 0:
                scaled[start:end] = (scaled[start:end] - mean) / std
        return scaled

    # ── Normalize ─────────────────────────────────────────────
    def l2_normalize(self, vec: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(vec)
        return vec / n if n > 0 else vec

    def estimate_pitch(self, y: np.ndarray) -> dict:
        """
        Estimate dominant pitch from monophonic-like audio.
        Returns note + octave + coarse range for reporting.
        """
        try:
            f0 = librosa.yin(
                y,
                fmin=librosa.note_to_hz("C1"),
                fmax=librosa.note_to_hz("C8"),
                sr=self.sr,
            )
            f0 = np.array(f0, dtype=np.float32)
            f0 = f0[np.isfinite(f0)]
            f0 = f0[f0 > 0]
            if f0.size == 0:
                return {
                    "dominant_f0_hz": 0.0,
                    "dominant_note": "unknown",
                    "pitch_range": "unknown",
                }

            dom = float(np.median(f0))
            note = librosa.hz_to_note(dom, octave=True, cents=False)

            if dom < 196.0:
                pr = "low"
            elif dom < 523.25:
                pr = "mid"
            else:
                pr = "high"

            return {
                "dominant_f0_hz": round(dom, 2),
                "dominant_note": note,
                "pitch_range": pr,
            }
        except Exception:
            return {
                "dominant_f0_hz": 0.0,
                "dominant_note": "unknown",
                "pitch_range": "unknown",
            }

    # ── Vector only (for FAISS) ───────────────────────────────
    def extract_vector(self, path: str) -> np.ndarray:
        y = self.load(path)
        feats, *_ = self._compute_features(y)

        vec = np.array(feats, dtype=np.float32)
        vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)

        # Fix #10: per-feature scaling trước L2 normalize
        vec = self.scale_features(vec)

        # ⭐ CRITICAL: normalize for cosine similarity
        vec = self.l2_normalize(vec)

        return vec

    # ── Full metadata (for MongoDB) ───────────────────────────
    def extract_all(self, path: str) -> dict:
        y = self.load(path)
        dur = len(y) / self.sr

        feats, mfcc, cen, zcr, rms, onset = self._compute_features(y)
        pitch = self.estimate_pitch(y)

        vec = np.array(feats, dtype=np.float32)
        vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)

        # Fix #10: per-feature scaling trước L2 normalize
        vec = self.scale_features(vec)

        # ⭐ CRITICAL: normalize
        vec = self.l2_normalize(vec)

        return {
            "feature_vector": vec.tolist(),
            "mfcc_mean": np.mean(mfcc, axis=1).tolist(),
            "spectral_centroid": float(np.mean(cen)),
            "zcr": float(np.mean(zcr)),
            "rms": float(np.mean(rms)),
            "onset_strength": float(np.mean(onset)),
            "dominant_f0_hz": pitch["dominant_f0_hz"],
            "dominant_note": pitch["dominant_note"],
            "pitch_range": pitch["pitch_range"],
            "duration": round(dur, 3),
            "sample_rate": self.sr,
        }