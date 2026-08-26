# Phase 0 spike — face pipeline

Throwaway harness for the two measurements that can change the roadmap before
any of the pipeline is committed to the product:

1. **Latency** — is InsightFace fast enough on the deployment CPU to sit inside
   an 800 ms p95 verification budget?
2. **Threshold** — what is the cosine threshold at the false-accept rate the
   product targets, measured rather than guessed?

Results and the decisions they force: [`docs/14-phase-0-spike.md`](../../docs/14-phase-0-spike.md).

## Running it

```bash
docker build -t fvas-spike:phase0 .
docker volume create fvas-spike-models
docker volume create fvas-spike-data
mkdir -p out
```

Latency, at the production thread and CPU limits:

```bash
docker run --rm --cpus=2 \
  -v fvas-spike-models:/root/.insightface \
  -v "$(pwd)/out:/out" \
  -e ONNX_INTRA_OP_THREADS=2 \
  fvas-spike:phase0 python bench_latency.py
```

Threshold calibration (downloads ~200 MB of LFW on first run, then embeds every
image once — allow 10–20 minutes):

```bash
docker run --rm \
  -v fvas-spike-models:/root/.insightface \
  -v fvas-spike-data:/data \
  -v "$(pwd)/out:/out" \
  -e ONNX_INTRA_OP_THREADS=8 \
  fvas-spike:phase0 python calibrate_threshold.py
```

Outputs land in `out/`: `latency.json`, `calibration.json`, `far-frr-curve.png`.

## Why it is separate from `apps/api`

The spike exists to decide whether the planned approach works. Wiring it into
the product first would mean discovering a two-second inference time after the
console had been built around it — which is precisely the failure Phase 0 is
scheduled to prevent.

It pins its own dependencies and mirrors the production base image
(`python:3.12-slim`, CPU ONNX Runtime) so the numbers transfer.

Results land in the `fvas-spike-out` volume. Copy them to the host with:

```bash
docker run --rm -v fvas-spike-out:/out -v "$PWD/out:/host" alpine \
  sh -c "cp /out/* /host/"
```

## Notes for whoever runs this next

- **Git Bash on Windows mangles container paths.** `-v "$(pwd)/out:/out"`
  becomes `…/out;C -> \Program Files\Git\out` — the mount silently points
  somewhere useless and every output file is lost when the container exits.
  Prefix with `MSYS_NO_PATHCONV=1`, or use a named volume as above.
- `INSIGHTFACE_HOME` is **ignored** by insightface 0.7.3. The model root is
  `~/.insightface` regardless, so mount the cache there.
- **Set `intra_op_num_threads` explicitly.** ONNX Runtime defaults it to 0,
  meaning "every visible core", and a container sees the host's core count
  regardless of `--cpus`. The first run of this spike measured 5× too slow
  purely from that oversubscription. It is a *session* option — passing it via
  `provider_options` is accepted and silently ignored.
- The first run downloads ~600 MB of models and ~200 MB of LFW. Keep the
  volumes between runs.
