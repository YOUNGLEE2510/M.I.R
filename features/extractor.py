import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import numpy as np
import librosa
from config import SAMPLE_RATE, N_MFCC, BASE_DIR, FEATURE_WEIGHTS


class AudioFeatureExtractor:

    # ── Cached weight vector (built once from config) ─────
    _weight_vec: np.ndarray | None = None

    @classmethod
    def _get_weight_vec(cls) -> np.ndarray:
        if cls._weight_vec is None:
            w = np.ones(100, dtype=np.float32)
            w[0:40]  = FEATURE_WEIGHTS['mfcc_mean']
            w[40:80] = FEATURE_WEIGHTS['mfcc_std']
            w[80:92] = FEATURE_WEIGHTS['chroma']
            w[92:94] = FEATURE_WEIGHTS['centroid']
            w[94]    = FEATURE_WEIGHTS['rolloff']
            w[95]    = FEATURE_WEIGHTS['flux']
            w[96]    = FEATURE_WEIGHTS['zcr']
            w[97]    = FEATURE_WEIGHTS['rms']
            w[98]    = FEATURE_WEIGHTS['hnr']
            w[99]    = FEATURE_WEIGHTS['onset']
            cls._weight_vec = w
        return cls._weight_vec

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

        # ── Compute STFT once and reuse across features ──
        S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))

        # MFCC (mean + std)
        mfcc = librosa.feature.mfcc(y=y, sr=self.sr, n_mfcc=self.n_mfcc)
        feats.extend(np.mean(mfcc, axis=1).tolist())
        feats.extend(np.std(mfcc, axis=1).tolist())

        # Chroma (reuse STFT)
        chroma = librosa.feature.chroma_stft(S=S, sr=self.sr)
        feats.extend(np.mean(chroma, axis=1).tolist())

        # Spectral Centroid (reuse STFT)
        cen = librosa.feature.spectral_centroid(S=S, sr=self.sr)
        feats.append(float(np.mean(cen)))
        feats.append(float(np.std(cen)))

        # Spectral Rolloff (reuse STFT)
        roll = librosa.feature.spectral_rolloff(S=S, sr=self.sr, roll_percent=0.85)
        feats.append(float(np.mean(roll)))

        # Spectral Flux (reuse STFT)
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

    # ── Feature scaling (dynamic Z-score) ────────────────────
    # Stats are learned from real data via refit_scaler() and persisted
    # to faiss_index/feature_stats.json.  Fall back to safe defaults on
    # cold start (no data yet) so the system stays functional.

    # Path where learned stats are stored
    _STATS_PATH: str = os.path.join(BASE_DIR, "faiss_index", "feature_stats.json")

    # Safe fallback defaults (same as the old hardcoded values)
    _FALLBACK_RANGES: dict = {
        # name: (start_idx, end_idx, approx_mean, approx_std)
        "mfcc_mean": (0,   40,  0.0,    80.0),
        "mfcc_std":  (40,  80,  25.0,   20.0),
        "chroma":    (80,  92,  0.35,   0.15),
        "centroid":  (92,  94,  2000.0, 1500.0),
        "rolloff":   (94,  95,  4000.0, 2000.0),
        "flux":      (95,  96,  0.3,    0.5),
        "zcr":       (96,  97,  0.08,   0.06),
        "rms":       (97,  98,  0.15,   0.1),
        "hnr":       (98,  99,  0.7,    0.2),
        "onset":     (99,  100, 2.0,    2.0),
    }

    # Loaded at class level; shared across all instances
    _scaler_mean: np.ndarray | None = None
    _scaler_std:  np.ndarray | None = None

    @classmethod
    def _load_scaler(cls) -> None:
        """Load per-feature mean/std from JSON (if available)."""
        if cls._scaler_mean is not None:
            return  # already loaded
        if os.path.exists(cls._STATS_PATH):
            try:
                with open(cls._STATS_PATH, "r") as f:
                    data = json.load(f)
                cls._scaler_mean = np.array(data["mean"], dtype=np.float32)
                cls._scaler_std  = np.array(data["std"],  dtype=np.float32)
                print(f"[Scaler] Loaded stats from {cls._STATS_PATH} "
                      f"(n={data.get('n_samples', '?')})")
                return
            except Exception as e:
                print(f"[Scaler] Warning: could not load stats file – {e}")
        # Fall back to hardcoded defaults
        print("[Scaler] Using fallback hardcoded statistics (run refit_scaler() to learn from data)")

    @classmethod
    def refit_scaler(cls, vectors: list[np.ndarray]) -> None:
        """Compute and persist per-feature mean/std using Welford's algorithm.

        Args:
            vectors: list of raw (unscaled, un-normalised) feature vectors,
                     each shape (FEATURE_DIM,).
        """
        if not vectors:
            print("[Scaler] No vectors provided – skipping refit.")
            return

        # Welford online algorithm (numerically stable)
        n = 0
        mean = np.zeros(len(vectors[0]), dtype=np.float64)
        M2   = np.zeros_like(mean)

        for v in vectors:
            n += 1
            delta  = v.astype(np.float64) - mean
            mean  += delta / n
            delta2 = v.astype(np.float64) - mean
            M2    += delta * delta2

        std = np.sqrt(M2 / max(n - 1, 1)).astype(np.float32)
        std = np.where(std < 1e-6, 1.0, std)  # avoid division by zero

        cls._scaler_mean = mean.astype(np.float32)
        cls._scaler_std  = std

        os.makedirs(os.path.dirname(cls._STATS_PATH), exist_ok=True)
        with open(cls._STATS_PATH, "w") as f:
            json.dump({
                "n_samples": n,
                "mean": cls._scaler_mean.tolist(),
                "std":  cls._scaler_std.tolist(),
            }, f)
        print(f"[Scaler] Refit done: {n} samples -> saved to {cls._STATS_PATH}")

    def scale_features(self, vec: np.ndarray) -> np.ndarray:
        """Per-feature z-score normalisation.

        Uses learned statistics from refit_scaler() when available;
        falls back to hardcoded group-level defaults otherwise.
        """
        self._load_scaler()  # no-op if already loaded

        if self._scaler_mean is not None and len(self._scaler_mean) == len(vec):
            # Learned per-element stats
            return ((vec - self._scaler_mean) / self._scaler_std).astype(np.float32)

        # Fallback: group-level hardcoded stats
        scaled = vec.copy()
        for _name, (start, end, mean, std) in self._FALLBACK_RANGES.items():
            if std > 0:
                scaled[start:end] = (scaled[start:end] - mean) / std
        return scaled

    # ── Normalize ─────────────────────────────────────────────
    def l2_normalize(self, vec: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(vec)
        return vec / n if n > 0 else vec

    def apply_weights(self, vec: np.ndarray) -> np.ndarray:
        return vec * self._get_weight_vec()

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

        # Apply optimized weights before L2 normalization
        vec = self.apply_weights(vec)

        # ⭐ CRITICAL: normalize for cosine similarity
        vec = self.l2_normalize(vec)

        return vec

    # ── Raw vector + metadata (for 2-pass batch refit) ────────
    def extract_raw(self, path: str) -> tuple[np.ndarray, dict]:
        """Return the RAW (unscaled) feature vector and audio metadata.

        Used by batch_extract to collect raw vectors for scaler fitting
        before applying scale + L2-normalize and storing in MongoDB.
        Do NOT call scale_features() here – caller is responsible.
        """
        y = self.load(path)
        dur = len(y) / self.sr
        feats, mfcc, cen, zcr, rms, onset = self._compute_features(y)
        pitch = self.estimate_pitch(y)

        vec = np.array(feats, dtype=np.float32)
        vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)

        meta = {
            "mfcc_mean":         np.mean(mfcc, axis=1).tolist(),
            "spectral_centroid": float(np.mean(cen)),
            "zcr":               float(np.mean(zcr)),
            "rms":               float(np.mean(rms)),
            "onset_strength":    float(np.mean(onset)),
            "dominant_f0_hz":    pitch["dominant_f0_hz"],
            "dominant_note":     pitch["dominant_note"],
            "pitch_range":       pitch["pitch_range"],
            "duration":          round(dur, 3),
            "sample_rate":       self.sr,
        }
        return vec, meta

    # ── Full metadata (for MongoDB / single-file ingest) ──────
    def extract_all(self, path: str) -> dict:
        """Extract features, scale, L2-normalize and return full metadata dict.

        Uses whatever scaler stats are currently loaded (learned or fallback).
        For bulk ingestion prefer the 2-pass approach in batch_extract.py.
        """
        raw_vec, meta = self.extract_raw(path)
        vec = self.scale_features(raw_vec)
        vec = self.apply_weights(vec)
        vec = self.l2_normalize(vec)
        return {**meta, "feature_vector": vec.tolist()}