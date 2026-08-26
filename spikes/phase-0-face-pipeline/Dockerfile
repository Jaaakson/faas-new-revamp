# Phase 0 spike — throwaway image for measuring the face pipeline.
#
# Deliberately separate from apps/api: the spike answers "is this fast enough
# and accurate enough" before any of it is committed to the product image. It
# mirrors the production base (python:3.12-slim + CPU ONNX Runtime) so the
# numbers transfer.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# libgl1 + libglib2.0-0: OpenCV runtime.
# build-essential + cython: insightface compiles native extensions on install.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        build-essential \
        wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /spike

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Models and datasets land on mounted volumes so they survive a rebuild —
# together they are roughly 500 MB.
ENV INSIGHTFACE_HOME=/models \
    SCIKIT_LEARN_DATA=/data

CMD ["python", "bench_latency.py"]
