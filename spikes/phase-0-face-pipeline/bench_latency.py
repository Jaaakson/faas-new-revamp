"""Phase 0 spike — per-stage latency of the face pipeline.

Answers the one question that can invalidate the roadmap: is InsightFace fast
enough on the deployment CPU to sit inside an 800 ms p95 verification budget?

Measures each stage separately, because a single end-to-end number tells you
nothing about what to fix if it is too slow:

    decode → detect → align → embed → match

## Thread control

The sessions are built here rather than through `FaceAnalysis`, because thread
count is the dominant lever on CPU inference and `FaceAnalysis` gives no way to
set it. ONNX Runtime defaults `intra_op_num_threads` to 0, meaning "use every
core it can see" — and a container sees the host's core count regardless of its
`--cpus` quota. The first run of this spike did exactly that: 8 ORT threads
against a 2-CPU quota, which thrashed and produced numbers 5-10x worse than the
hardware is capable of.

`provider_options` is not where this setting lives; it is a session option, and
passing it to the CPU provider is silently ignored. Production will build its
sessions the same way this file does.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from insightface.model_zoo.arcface_onnx import ArcFaceONNX
from insightface.model_zoo.scrfd import SCRFD
from insightface.utils import face_align

MODEL_ROOT = Path.home() / ".insightface" / "models" / "buffalo_l"
DET_MODEL = MODEL_ROOT / "det_10g.onnx"
REC_MODEL = MODEL_ROOT / "w600k_r50.onnx"

WARMUP = 5
ITERATIONS = 30

# Thread counts to compare. 2 is the production default
# (docs/05-architecture.md §7); the others show how the workload scales.
THREAD_COUNTS = [int(t) for t in os.environ.get("THREAD_SWEEP", "1,2,4").split(",")]

# Input sizes a real integration would send. docs/08 §6 claims downscaling
# before detection is "the largest single win" — tested here.
INPUT_SIZES = [(640, 480), (1280, 720)]

# Detector working resolution, independent of input size.
DET_SIZES = [320, 640]


@dataclass
class StageStats:
    stage: str
    mean_ms: float
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float

    @classmethod
    def of(cls, stage: str, samples_ms: list[float]) -> StageStats:
        ordered = sorted(samples_ms)
        return cls(
            stage=stage,
            mean_ms=round(statistics.fmean(ordered), 2),
            p50_ms=round(ordered[len(ordered) // 2], 2),
            p95_ms=round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2),
            min_ms=round(ordered[0], 2),
            max_ms=round(ordered[-1], 2),
        )


def environment() -> dict[str, object]:
    """A latency figure without the hardware and build that produced it is not
    reproducible."""
    cpu_model = "unknown"
    flags: list[str] = []
    try:
        text = Path("/proc/cpuinfo").read_text()
        for line in text.splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
        flags = [f for f in ("avx512f", "avx2", "avx", "fma") if f" {f}" in text]
    except OSError:
        pass

    quota = "unlimited"
    try:
        raw = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if raw[0] != "max":
            quota = f"{int(raw[0]) / int(raw[1]):.2f} cpu"
    except (OSError, ValueError, IndexError):
        pass

    return {
        "cpu": cpu_model,
        "cpu_flags": flags,
        "cpu_count_visible": os.cpu_count(),
        "cgroup_cpu_quota": quota,
        "onnxruntime": ort.__version__,
        "python": sys.version.split()[0],
    }


def build_session(path: Path, threads: int) -> ort.InferenceSession:
    options = ort.SessionOptions()
    # The setting that actually matters. 0 would mean "all visible cores",
    # which inside a CPU-quota'd container means oversubscription.
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )


def load_models(threads: int, det_size: int) -> tuple[SCRFD, ArcFaceONNX, float]:
    started = time.perf_counter()
    detector = SCRFD(model_file=str(DET_MODEL), session=build_session(DET_MODEL, threads))
    detector.prepare(ctx_id=-1, input_size=(det_size, det_size))

    recognizer = ArcFaceONNX(
        model_file=str(REC_MODEL), session=build_session(REC_MODEL, threads)
    )
    recognizer.prepare(ctx_id=-1)
    return detector, recognizer, time.perf_counter() - started


def sample_image() -> np.ndarray:
    from insightface.data import get_image

    image = get_image("t1")
    if image is None:
        raise RuntimeError("insightface sample image unavailable")
    return image


def encode_jpeg(image: np.ndarray, quality: int = 90) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("failed to encode sample image")
    return buffer.tobytes()


def bench(
    detector: SCRFD, recognizer: ArcFaceONNX, jpeg: bytes, label: str
) -> dict[str, object] | None:
    decode_ms: list[float] = []
    detect_ms: list[float] = []
    align_ms: list[float] = []
    embed_ms: list[float] = []
    total_ms: list[float] = []
    embedding: np.ndarray | None = None

    for iteration in range(WARMUP + ITERATIONS):
        record = iteration >= WARMUP
        started = time.perf_counter()

        t0 = time.perf_counter()
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        t1 = time.perf_counter()

        bboxes, keypoints = detector.detect(image, max_num=0, metric="default")
        t2 = time.perf_counter()

        if bboxes.shape[0] == 0:
            print(f"  SKIP {label}: no face detected")
            return None

        areas = (bboxes[:, 2] - bboxes[:, 0]) * (bboxes[:, 3] - bboxes[:, 1])
        best = int(np.argmax(areas))
        aligned = face_align.norm_crop(image, landmark=keypoints[best], image_size=112)
        t3 = time.perf_counter()

        embedding = recognizer.get_feat(aligned)
        t4 = time.perf_counter()

        if record:
            decode_ms.append((t1 - t0) * 1000)
            detect_ms.append((t2 - t1) * 1000)
            align_ms.append((t3 - t2) * 1000)
            embed_ms.append((t4 - t3) * 1000)
            total_ms.append((time.perf_counter() - started) * 1000)

    # Matching is a dot product against a handful of templates. Measured over
    # many more iterations because it is orders of magnitude cheaper and would
    # otherwise vanish into timer noise.
    templates = np.random.default_rng(0).normal(size=(5, 512)).astype(np.float32)
    templates /= np.linalg.norm(templates, axis=1, keepdims=True)
    probe = np.asarray(embedding, dtype=np.float32).ravel()
    probe /= np.linalg.norm(probe)

    match_ms: list[float] = []
    for _ in range(2000):
        t0 = time.perf_counter()
        _ = float((templates @ probe).max())
        match_ms.append((time.perf_counter() - t0) * 1000)

    stages = [
        StageStats.of("decode", decode_ms),
        StageStats.of("detect", detect_ms),
        StageStats.of("align", align_ms),
        StageStats.of("embed", embed_ms),
        StageStats.of("match", match_ms),
        StageStats.of("TOTAL", total_ms),
    ]
    return {"label": label, "stages": [asdict(s) for s in stages]}


def print_table(result: dict[str, object]) -> None:
    print(f"\n  {result['label']}")
    print(f"  {'stage':<10} {'mean':>10} {'p50':>10} {'p95':>10}")
    print(f"  {'-' * 10} {'-' * 10} {'-' * 10} {'-' * 10}")
    for stage in result["stages"]:  # type: ignore[index]
        print(
            f"  {stage['stage']:<10} {stage['mean_ms']:>9.2f}ms "
            f"{stage['p50_ms']:>9.2f}ms {stage['p95_ms']:>9.2f}ms"
        )


def main() -> int:
    env = environment()
    print("=" * 74)
    print("Phase 0 spike — face pipeline latency")
    print("=" * 74)
    for key, value in env.items():
        print(f"  {key:<20} {value}")
    print(f"  {'warmup/iterations':<20} {WARMUP}/{ITERATIONS}")

    if not DET_MODEL.exists() or not REC_MODEL.exists():
        print(f"\nModels missing under {MODEL_ROOT}. Run the download step first.")
        return 1

    base = sample_image()
    print(f"  {'sample image':<20} {base.shape[1]}x{base.shape[0]}")

    results: list[dict[str, object]] = []

    for threads in THREAD_COUNTS:
        for det_size in DET_SIZES:
            detector, recognizer, load_seconds = load_models(threads, det_size)
            print(f"\n{'=' * 74}")
            print(f"threads={threads}  det_size={det_size}  (model load {load_seconds:.2f}s)")
            print("=" * 74)

            for width, height in INPUT_SIZES:
                resized = cv2.resize(base, (width, height), interpolation=cv2.INTER_AREA)
                jpeg = encode_jpeg(resized)
                label = f"{width}x{height} in, det={det_size}, threads={threads}"
                result = bench(detector, recognizer, jpeg, label)
                if result is None:
                    continue
                result |= {
                    "threads": threads,
                    "det_size": det_size,
                    "input": f"{width}x{height}",
                    "jpeg_bytes": len(jpeg),
                    "model_load_seconds": round(load_seconds, 2),
                }
                results.append(result)
                print_table(result)

    Path("/out").mkdir(parents=True, exist_ok=True)
    Path("/out/latency.json").write_text(
        json.dumps(
            {"environment": env, "warmup": WARMUP, "iterations": ITERATIONS, "results": results},
            indent=2,
        )
    )

    print(f"\n{'=' * 74}\nVerdict — Phase 0 gate: p95 under 500 ms\n{'=' * 74}")
    for result in results:
        total = next(s for s in result["stages"] if s["stage"] == "TOTAL")  # type: ignore[index]
        mark = "PASS" if total["p95_ms"] < 500 else "FAIL"
        print(f"  {mark}  {result['label']:<44} p95 {total['p95_ms']:>8.2f}ms")

    best = min(
        results,
        key=lambda r: next(s for s in r["stages"] if s["stage"] == "TOTAL")["p95_ms"],  # type: ignore[index]
    )
    best_p95 = next(s for s in best["stages"] if s["stage"] == "TOTAL")["p95_ms"]  # type: ignore[index]
    print(f"\n  Best configuration: {best['label']}  →  p95 {best_p95:.2f}ms")
    print("\nWrote /out/latency.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
