"use client";

import * as React from "react";
import { AlertTriangle, Camera, CameraOff, Check, Lock, RefreshCw, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useCamera } from "@/hooks/use-camera";
import {
  ANALYSIS_HEIGHT,
  ANALYSIS_WIDTH,
  QUALITY_LIMITS,
  type QualityVerdict,
  analyseLuma,
  toLuma,
  verdict,
} from "@/lib/frame-quality";
import { cn } from "@/lib/utils";

/** How often the preview is analysed. ~7 Hz — responsive without being busy. */
const SAMPLE_INTERVAL_MS = 140;
/** Consecutive good samples before auto-capture fires. ~700 ms of steady framing. */
const SAMPLES_TO_ARM = 5;

interface CameraCaptureProps {
  /** Shown above the frame: what this particular shot is for. */
  prompt: string;
  /** Receives a JPEG data URL. */
  onCapture: (dataUrl: string) => void;
  /** Auto-capture once quality holds. Manual capture always stays available. */
  autoCapture?: boolean;
  disabled?: boolean;
  /** Guidance from the server's last attempt — outranks any local hint. */
  serverHint?: string | null;
}

export function CameraCapture({
  prompt,
  onCapture,
  autoCapture = true,
  disabled = false,
  serverHint = null,
}: CameraCaptureProps) {
  const camera = useCamera();
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const analysisRef = React.useRef<HTMLCanvasElement>(null);
  const previousLumaRef = React.useRef<Float32Array | null>(null);
  const goodSamplesRef = React.useRef(0);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const [quality, setQuality] = React.useState<QualityVerdict | null>(null);
  const [armed, setArmed] = React.useState(0);
  const [flash, setFlash] = React.useState(false);

  // Held in a ref so the sampling loop never restarts when the parent
  // re-renders. Restarting it would reset the arming counter and make
  // auto-capture unreachable on a page that updates while you frame the shot.
  const onCaptureRef = React.useRef(onCapture);
  React.useEffect(() => {
    onCaptureRef.current = onCapture;
  }, [onCapture]);

  React.useEffect(() => {
    void camera.start();
    // Mount only: `start` is stable, and re-running it would restart the stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    const video = videoRef.current;
    if (video && camera.stream) {
      video.srcObject = camera.stream;
    }
  }, [camera.stream]);

  const grabFrame = React.useCallback((): string | null => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return null;

    // Full resolution for the capture itself — the analysis downscale exists to
    // keep the HUD cheap, and sending it to the server would throw away exactly
    // the detail the 112 px inter-ocular gate is measuring.
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    if (!context) return null;

    // Un-mirror. The preview is flipped so it behaves like a mirror, which is
    // what people expect; sending the flipped frame would be sending a
    // different face than the one that will later authenticate.
    context.translate(canvas.width, 0);
    context.scale(-1, 1);
    context.drawImage(video, 0, 0);

    return canvas.toDataURL("image/jpeg", 0.92);
  }, []);

  const capture = React.useCallback(() => {
    const dataUrl = grabFrame();
    if (!dataUrl) return;
    setFlash(true);
    setTimeout(() => setFlash(false), 160);
    goodSamplesRef.current = 0;
    setArmed(0);
    onCaptureRef.current(dataUrl);
  }, [grabFrame]);

  const captureRef = React.useRef(capture);
  React.useEffect(() => {
    captureRef.current = capture;
  }, [capture]);

  // The sampling loop. Deliberately depends only on the camera status and the
  // two switches that change its behaviour.
  React.useEffect(() => {
    if (camera.status !== "ready" || disabled) return;

    const timer = window.setInterval(() => {
      const video = videoRef.current;
      const canvas = analysisRef.current;
      if (!video || !canvas || !video.videoWidth) return;

      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) return;

      context.drawImage(video, 0, 0, ANALYSIS_WIDTH, ANALYSIS_HEIGHT);
      const { data } = context.getImageData(0, 0, ANALYSIS_WIDTH, ANALYSIS_HEIGHT);
      const luma = toLuma(data, ANALYSIS_WIDTH * ANALYSIS_HEIGHT);

      const next = verdict(
        analyseLuma(luma, ANALYSIS_WIDTH, ANALYSIS_HEIGHT, previousLumaRef.current),
      );
      previousLumaRef.current = luma;
      setQuality(next);

      goodSamplesRef.current = next.ok ? goodSamplesRef.current + 1 : 0;
      setArmed(goodSamplesRef.current);

      if (autoCapture && goodSamplesRef.current >= SAMPLES_TO_ARM) {
        captureRef.current();
      }
    }, SAMPLE_INTERVAL_MS);

    return () => window.clearInterval(timer);
  }, [camera.status, autoCapture, disabled]);

  const handleUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") onCaptureRef.current(reader.result);
    };
    reader.readAsDataURL(file);
    event.target.value = "";
  };

  const progress = Math.min(1, armed / SAMPLES_TO_ARM);

  if (camera.status !== "ready" && camera.status !== "requesting") {
    return (
      <CameraFallback
        status={camera.status}
        error={camera.error}
        onRetry={() => void camera.start()}
        onUpload={() => fileInputRef.current?.click()}
        fileInput={
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            onChange={handleUpload}
          />
        }
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium">{prompt}</p>
        {camera.devices.length > 1 ? (
          <select
            value={camera.deviceId ?? ""}
            onChange={(event) => void camera.selectDevice(event.target.value)}
            className="border-input bg-background h-7 rounded-md border px-2 text-xs"
            aria-label="Camera"
          >
            {camera.devices.map((device) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      <div className="bg-muted relative aspect-[4/3] overflow-hidden rounded-xl border">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          // Mirrored preview only. `grabFrame` un-mirrors before sending.
          className="size-full -scale-x-100 object-cover"
        />
        <canvas
          ref={analysisRef}
          width={ANALYSIS_WIDTH}
          height={ANALYSIS_HEIGHT}
          className="hidden"
          aria-hidden
        />

        <FaceGuideOverlay ok={quality?.ok ?? false} progress={progress} />

        {flash ? <div className="absolute inset-0 animate-pulse bg-white/70" aria-hidden /> : null}

        <div className="absolute inset-x-0 bottom-0 p-3">
          <div
            className={cn(
              "rounded-lg px-3 py-2 text-center text-xs font-medium backdrop-blur-sm transition-colors",
              serverHint
                ? "bg-destructive/85 text-white"
                : quality?.ok
                  ? "bg-emerald-600/85 text-white"
                  : "bg-slate-900/80 text-white",
            )}
            // Announced, not just shown: someone relying on a screen reader
            // gets the same coaching as someone watching the ring.
            role="status"
            aria-live="polite"
          >
            {serverHint ?? quality?.hint ?? "Hold steady…"}
          </div>
        </div>
      </div>

      <FaceQualityHUD quality={quality} />

      <div className="flex items-center gap-2">
        <Button onClick={capture} disabled={disabled} className="flex-1">
          <Camera className="size-4" aria-hidden />
          Capture
        </Button>
        <Button variant="outline" onClick={() => fileInputRef.current?.click()} disabled={disabled}>
          <Upload className="size-4" aria-hidden />
          Upload
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="sr-only"
          onChange={handleUpload}
        />
      </div>
    </div>
  );
}

/**
 * The oval guide and the arming ring.
 *
 * Purely decorative to assistive technology — every state it conveys is already
 * in the live region above, so announcing it again would double every message.
 */
export function FaceGuideOverlay({ ok, progress }: { ok: boolean; progress: number }) {
  const radius = 46;
  const circumference = 2 * Math.PI * radius;

  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className="pointer-events-none absolute inset-0 size-full"
      aria-hidden
    >
      <defs>
        <mask id="face-guide-mask">
          <rect width="100" height="100" fill="white" />
          <ellipse cx="50" cy="46" rx="26" ry="34" fill="black" />
        </mask>
      </defs>

      {/* Everything outside the oval is dimmed, which frames the subject
          without hiding what the camera actually sees. */}
      <rect width="100" height="100" fill="rgb(2 6 23 / 0.45)" mask="url(#face-guide-mask)" />

      <ellipse
        cx="50"
        cy="46"
        rx="26"
        ry="34"
        fill="none"
        strokeWidth="0.6"
        strokeDasharray="3 2"
        className={cn(
          "transition-[stroke] duration-300",
          ok ? "stroke-emerald-400" : "stroke-white/60",
        )}
        vectorEffect="non-scaling-stroke"
      />

      {/* Arming progress. Rendered only while filling, so a steady frame does
          not sit under a permanently full ring. */}
      {progress > 0 ? (
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          strokeWidth="1.2"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - progress)}
          transform="rotate(-90 50 50)"
          className="stroke-emerald-400 transition-[stroke-dashoffset] duration-150"
          vectorEffect="non-scaling-stroke"
        />
      ) : null}
    </svg>
  );
}

/**
 * Three meters for the three things measurable without a face model.
 *
 * Labelled with what to do, not with the metric name: "Lighting" is actionable,
 * "mean luma 0.19" is not.
 */
export function FaceQualityHUD({ quality }: { quality: QualityVerdict | null }) {
  const meters = [
    {
      label: "Lighting",
      value: quality?.brightness ?? 0,
      ok:
        !!quality &&
        quality.brightness >= QUALITY_LIMITS.brightness.min &&
        quality.brightness <= QUALITY_LIMITS.brightness.max,
    },
    {
      label: "Focus",
      value: quality?.sharpness ?? 0,
      ok: !!quality && quality.sharpness >= QUALITY_LIMITS.sharpness.min,
    },
    {
      label: "Steadiness",
      value: quality?.stability ?? 0,
      ok: !!quality && quality.stability >= QUALITY_LIMITS.stability.min,
    },
  ];

  return (
    <div className="grid grid-cols-3 gap-2">
      {meters.map((meter) => (
        <div key={meter.label} className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground text-[11px]">{meter.label}</span>
            {meter.ok ? (
              <Check className="size-3 text-emerald-500" aria-hidden />
            ) : (
              <AlertTriangle className="size-3 text-amber-500" aria-hidden />
            )}
          </div>
          <div
            className="bg-muted h-1.5 overflow-hidden rounded-full"
            role="meter"
            aria-label={meter.label}
            aria-valuenow={Math.round(meter.value * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className={cn(
                "h-full rounded-full transition-[width,background-color] duration-200",
                meter.ok ? "bg-emerald-500" : "bg-amber-500",
              )}
              style={{ width: `${Math.round(meter.value * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * The camera-unavailable path, with a recovery route for each cause.
 *
 * Upload is offered in every one of them. A blocked camera must never be the
 * end of the road — the same enrollment is reachable with a photo file, and the
 * server cannot tell the difference.
 */
function CameraFallback({
  status,
  error,
  onRetry,
  onUpload,
  fileInput,
}: {
  status: string;
  error: string | null;
  onRetry: () => void;
  onUpload: () => void;
  fileInput: React.ReactNode;
}) {
  const content = {
    denied: {
      icon: Lock,
      title: "Camera access is blocked",
      body:
        "Your browser is remembering an earlier refusal, so asking again will not prompt you. " +
        "Open the padlock or camera icon in the address bar, allow access for this site, then reload.",
      retry: "Reload after allowing",
    },
    unavailable: {
      icon: CameraOff,
      title: "No camera found",
      body: "No video input is available. It may be in use by another application, or disconnected.",
      retry: "Look again",
    },
    insecure: {
      icon: Lock,
      title: "Camera needs a secure connection",
      body:
        "Browsers only expose the camera over HTTPS or on localhost. Open the console over " +
        "https, or use localhost rather than a LAN address.",
      retry: "Try again",
    },
    error: {
      icon: AlertTriangle,
      title: "The camera could not be started",
      body: error ?? "Something went wrong while opening the camera.",
      retry: "Try again",
    },
    idle: {
      icon: Camera,
      title: "Camera not started",
      body: "Allow camera access to capture a face, or upload a photo instead.",
      retry: "Start camera",
    },
  }[status] ?? {
    icon: Camera,
    title: "Camera not started",
    body: "Allow camera access to capture a face, or upload a photo instead.",
    retry: "Start camera",
  };

  const Icon = content.icon;

  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-10 text-center">
      <div className="bg-muted flex size-10 items-center justify-center rounded-full">
        <Icon className="text-muted-foreground size-5" aria-hidden />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">{content.title}</p>
        <p className="text-muted-foreground mx-auto max-w-sm text-xs leading-relaxed">
          {content.body}
        </p>
      </div>
      <div className="flex gap-2 pt-1">
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-3.5" aria-hidden />
          {content.retry}
        </Button>
        <Button size="sm" onClick={onUpload}>
          <Upload className="size-3.5" aria-hidden />
          Upload a photo
        </Button>
      </div>
      {fileInput}
    </div>
  );
}
