"""Phase 0 spike — threshold calibration on a real pair set.

docs/08-ai-workflow.md §3 ships 0.38 as the "Balanced" default and says plainly
that it is a starting point to be measured, not a result. This measures it.

Method (docs/08 §4):
  1. Embed every usable LFW image once.
  2. Build genuine pairs (same identity) and impostor pairs (different identity).
  3. Sweep the threshold and record FAR and FRR at each step.
  4. Read the operating point off the curve at the FAR the product targets.

Accuracy is deliberately never reported. On a pair set it hides the asymmetry
that matters: 99% accuracy with a 1% false accept rate is unusable for
authentication, and the single number cannot say which error you bought.

Sessions are built directly rather than through `FaceAnalysis`, for the same
reason as bench_latency.py — it is the only way to control ONNX Runtime's
thread count. Here the goal is throughput, so it uses every core available.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import onnxruntime as ort

# Batch job: throughput, not latency. Use what the container was given.
THREADS = int(os.environ.get("ONNX_INTRA_OP_THREADS", str(os.cpu_count() or 4)))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from insightface.model_zoo.arcface_onnx import ArcFaceONNX  # noqa: E402
from insightface.model_zoo.scrfd import SCRFD  # noqa: E402
from insightface.utils import face_align  # noqa: E402
from sklearn.datasets import fetch_lfw_people  # noqa: E402
import cv2  # noqa: E402

MODEL_ROOT = Path.home() / ".insightface" / "models" / "buffalo_l"
OUT = Path("/out")

MIN_FACES_PER_PERSON = 2
# LFW is severely imbalanced — George W. Bush alone has 530 images, which would
# contribute ~140k genuine pairs and drown every other identity. Capping per
# identity keeps the genuine distribution representative of *people* rather
# than of one person.
MAX_IMAGES_PER_IDENTITY = 6
MAX_IMPOSTOR_PAIRS = 500_000
TARGET_FAR = 1e-4


def build_session(path: Path) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.intra_op_num_threads = THREADS
    options.inter_op_num_threads = 1
    # SCRFD's graph declares output shapes for its 640x640 baseline; running at
    # another size logs a warning per output per frame. Suppress the noise.
    options.log_severity_level = 3
    return ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )


def load_models() -> tuple[SCRFD, ArcFaceONNX]:
    detector = SCRFD(
        model_file=str(MODEL_ROOT / "det_10g.onnx"),
        session=build_session(MODEL_ROOT / "det_10g.onnx"),
    )
    # LFW frames are 250x250 with a centred face; 320 is ample.
    detector.prepare(ctx_id=-1, input_size=(320, 320))

    recognizer = ArcFaceONNX(
        model_file=str(MODEL_ROOT / "w600k_r50.onnx"),
        session=build_session(MODEL_ROOT / "w600k_r50.onnx"),
    )
    recognizer.prepare(ctx_id=-1)
    return detector, recognizer


def select_images() -> tuple[list[Path], np.ndarray, int]:
    """Return file paths, not decoded images.

    sklearn's array loader materialises every image into one float array — for
    LFW at full resolution that is roughly 7 GB, which thrashes or OOMs before
    a single embedding is computed. Only the download is reused; the images are
    then streamed from disk one at a time.
    """
    print(f"Locating LFW (downloads ~200 MB on first run, threads={THREADS})…")
    # Fetch with an aggressive slice/resize purely to trigger the download
    # cheaply; the returned arrays are discarded.
    fetch_lfw_people(min_faces_per_person=100, resize=0.4, funneled=True)

    home = Path(os.environ.get("SCIKIT_LEARN_DATA", str(Path.home() / "scikit_learn_data")))
    root = home / "lfw_home" / "lfw_funneled"
    if not root.is_dir():
        raise RuntimeError(f"LFW images not found under {root}")

    by_person = {
        person.name: sorted(person.glob("*.jpg"))
        for person in sorted(root.iterdir())
        if person.is_dir()
    }
    total_available = sum(len(v) for v in by_person.values())
    print(f"  {total_available} images / {len(by_person)} identities on disk")

    paths: list[Path] = []
    labels: list[int] = []
    for index, (_, files) in enumerate(sorted(by_person.items())):
        if len(files) < MIN_FACES_PER_PERSON:
            continue
        for file in files[:MAX_IMAGES_PER_IDENTITY]:
            paths.append(file)
            labels.append(index)

    print(
        f"  using {len(paths)} images / {len(set(labels))} identities "
        f"(>= {MIN_FACES_PER_PERSON} images, capped at {MAX_IMAGES_PER_IDENTITY})"
    )
    return paths, np.asarray(labels), total_available


def embed_all(
    detector: SCRFD, recognizer: ArcFaceONNX, paths: list[Path], labels: np.ndarray
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    embeddings: list[np.ndarray] = []
    kept: list[int] = []
    stats = {"considered": len(paths), "no_face": 0, "unreadable": 0, "embedded": 0}

    started = time.perf_counter()
    for index, (path, label) in enumerate(zip(paths, labels, strict=True)):
        # cv2 reads straight to BGR uint8, which is what the model expects.
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None:
            stats["unreadable"] += 1
            continue

        bboxes, keypoints = detector.detect(frame, max_num=0, metric="default")
        if bboxes.shape[0] == 0:
            stats["no_face"] += 1
            continue

        # Largest face — LFW frames occasionally catch a bystander.
        areas = (bboxes[:, 2] - bboxes[:, 0]) * (bboxes[:, 3] - bboxes[:, 1])
        best = int(np.argmax(areas))
        aligned = face_align.norm_crop(frame, landmark=keypoints[best], image_size=112)

        embedding = np.asarray(recognizer.get_feat(aligned), dtype=np.float32).ravel()
        embedding /= np.linalg.norm(embedding)
        embeddings.append(embedding)
        kept.append(int(label))
        stats["embedded"] += 1

        if (index + 1) % 500 == 0:
            elapsed = time.perf_counter() - started
            rate = (index + 1) / elapsed
            remaining = (len(paths) - index - 1) / rate
            print(f"  {index + 1}/{len(paths)}  {rate:.1f} img/s  eta {remaining:.0f}s")

    print(f"  embedded {stats['embedded']}, no face detected {stats['no_face']}")
    return np.vstack(embeddings), np.asarray(kept), stats


def build_pairs(embeddings: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Genuine and impostor cosine similarities.

    Embeddings are L2-normalised, so cosine similarity is a dot product.
    """
    by_identity: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        by_identity[int(label)].append(index)

    left_g: list[int] = []
    right_g: list[int] = []
    for indices in by_identity.values():
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                left_g.append(indices[i])
                right_g.append(indices[j])

    genuine = np.einsum("ij,ij->i", embeddings[left_g], embeddings[right_g])

    # Impostor pairs are sampled rather than exhaustive: bounded memory, and
    # still enough pairs to resolve a false-accept rate of 1e-4.
    rng = np.random.default_rng(20260801)
    total = len(labels)
    left = rng.integers(0, total, size=MAX_IMPOSTOR_PAIRS * 2)
    right = rng.integers(0, total, size=MAX_IMPOSTOR_PAIRS * 2)
    different = labels[left] != labels[right]
    left = left[different][:MAX_IMPOSTOR_PAIRS]
    right = right[different][:MAX_IMPOSTOR_PAIRS]
    impostor = np.einsum("ij,ij->i", embeddings[left], embeddings[right])

    print(f"  genuine  {len(genuine):,}")
    print(f"  impostor {len(impostor):,}  (FAR resolution ~{1 / len(impostor):.1e})")
    return genuine.astype(np.float64), impostor.astype(np.float64)


def sweep(genuine: np.ndarray, impostor: np.ndarray) -> list[dict[str, float]]:
    return [
        {
            "threshold": round(float(t), 4),
            "far": float((impostor >= t).mean()),
            "frr": float((genuine < t).mean()),
        }
        for t in np.arange(0.0, 1.0005, 0.005)
    ]


def operating_point(curve: list[dict[str, float]], target_far: float) -> dict[str, float]:
    """Lowest threshold whose FAR meets the target.

    Lowest, not nearest: being stricter than necessary buys no security and
    costs real users retries.
    """
    for point in curve:
        if point["far"] <= target_far:
            return point
    return curve[-1]


def plot(
    curve: list[dict[str, float]],
    genuine: np.ndarray,
    impostor: np.ndarray,
    chosen: dict[str, float],
) -> None:
    thresholds = [p["threshold"] for p in curve]
    fars = [max(p["far"], 1e-7) for p in curve]
    frrs = [max(p["frr"], 1e-7) for p in curve]

    figure, (left, right) = plt.subplots(1, 2, figsize=(13, 5))

    left.semilogy(thresholds, fars, color="#dc2626", label="FAR — impostor accepted")
    left.semilogy(thresholds, frrs, color="#2563eb", label="FRR — genuine rejected")
    left.axvline(chosen["threshold"], color="#111827", ls="--", lw=1,
                 label=f"chosen {chosen['threshold']:.3f}")
    left.axhline(TARGET_FAR, color="#9ca3af", ls=":", lw=1, label=f"target FAR {TARGET_FAR:.0e}")
    left.set_xlabel("cosine similarity threshold")
    left.set_ylabel("error rate (log scale)")
    left.set_title("FAR / FRR against threshold")
    left.set_ylim(1e-7, 1.2)
    left.set_xlim(0, 1)
    left.grid(alpha=0.3, which="both")
    left.legend(fontsize=8)

    right.hist(impostor, bins=200, density=True, alpha=0.65, color="#dc2626",
               label=f"impostor (n={len(impostor):,})")
    right.hist(genuine, bins=200, density=True, alpha=0.65, color="#2563eb",
               label=f"genuine (n={len(genuine):,})")
    right.axvline(chosen["threshold"], color="#111827", ls="--", lw=1)
    right.set_xlabel("cosine similarity")
    right.set_ylabel("density")
    right.set_title("Score distributions")
    right.grid(alpha=0.3)
    right.legend(fontsize=8)

    figure.suptitle(
        "Fvas Phase 0 — buffalo_l (w600k_r50) threshold calibration on LFW", fontsize=11
    )
    figure.tight_layout()
    figure.savefig(OUT / "far-frr-curve.png", dpi=140)
    print(f"  wrote {OUT / 'far-frr-curve.png'}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 74)
    print("Phase 0 spike — threshold calibration")
    print("=" * 74)

    detector, recognizer = load_models()
    paths, labels, available = select_images()
    embeddings, kept_labels, stats = embed_all(detector, recognizer, paths, labels)
    genuine, impostor = build_pairs(embeddings, kept_labels)

    curve = sweep(genuine, impostor)
    chosen = operating_point(curve, TARGET_FAR)

    presets = {
        name: min(curve, key=lambda p: abs(p["threshold"] - value))
        for name, value in (("lenient", 0.32), ("balanced", 0.38), ("strict", 0.45))
    }

    # Equal error rate — a single summary useful for comparing models, never
    # for setting a production threshold.
    eer = min(curve, key=lambda p: abs(p["far"] - p["frr"]))

    print("\n" + "=" * 74)
    print("Results")
    print("=" * 74)
    print(f"  genuine   mean {genuine.mean():.4f}  sd {genuine.std():.4f}  min {genuine.min():.4f}")
    print(f"  impostor  mean {impostor.mean():.4f}  sd {impostor.std():.4f}  max {impostor.max():.4f}")
    print(f"  separation between means: {genuine.mean() - impostor.mean():.4f}")
    print(f"\n  EER ~{eer['far']:.2e} at threshold {eer['threshold']:.3f}")
    print(f"\n  Operating point at FAR <= {TARGET_FAR:.0e}:")
    print(f"    threshold {chosen['threshold']:.3f}   FAR {chosen['far']:.2e}   "
          f"FRR {chosen['frr']:.2e}   TAR {1 - chosen['frr']:.4f}")
    print("\n  Shipped presets, measured:")
    for name, point in presets.items():
        print(f"    {name:<9} {point['threshold']:.3f}   FAR {point['far']:.2e}   "
              f"FRR {point['frr']:.2e}   TAR {1 - point['frr']:.4f}")

    plot(curve, genuine, impostor, chosen)

    (OUT / "calibration.json").write_text(
        json.dumps(
            {
                "dataset": "LFW (funneled, colour)",
                "model": "buffalo_l / w600k_r50",
                "images_available": available,
                "max_images_per_identity": MAX_IMAGES_PER_IDENTITY,
                "image_stats": stats,
                "pairs": {"genuine": int(len(genuine)), "impostor": int(len(impostor))},
                "distributions": {
                    "genuine": {
                        "mean": float(genuine.mean()), "std": float(genuine.std()),
                        "min": float(genuine.min()), "max": float(genuine.max()),
                    },
                    "impostor": {
                        "mean": float(impostor.mean()), "std": float(impostor.std()),
                        "min": float(impostor.min()), "max": float(impostor.max()),
                    },
                },
                "target_far": TARGET_FAR,
                "operating_point": chosen,
                "eer": eer,
                "presets_measured": presets,
                "curve": curve,
            },
            indent=2,
        )
    )
    print(f"  wrote {OUT / 'calibration.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
