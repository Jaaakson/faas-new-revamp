"use client";

import * as React from "react";

/**
 * Camera access, with the failure modes treated as first-class states.
 *
 * Every one of these happens in the field, and each needs a different recovery:
 *
 * * `denied` — the user said no, or said no once before and the browser is
 *   remembering it. Re-calling `getUserMedia` will not re-prompt, so the only
 *   honest response is to explain how to reverse it in browser settings. This
 *   is the case a naive implementation gets wrong by retrying forever.
 * * `unavailable` — no camera, or the OS gave it to another app.
 * * `insecure` — `getUserMedia` is undefined outside a secure context. On plain
 *   HTTP over a LAN address this is the actual cause, and "camera not found"
 *   would send someone hunting for a hardware fault.
 *
 * The stream is stopped on unmount. A leaked `MediaStream` keeps the camera
 * light on after navigation, which people reasonably read as spyware.
 */

export type CameraStatus =
  "idle" | "requesting" | "ready" | "denied" | "unavailable" | "insecure" | "error";

export interface CameraDevice {
  deviceId: string;
  label: string;
}

interface UseCameraResult {
  status: CameraStatus;
  stream: MediaStream | null;
  error: string | null;
  devices: CameraDevice[];
  deviceId: string | null;
  start: (deviceId?: string) => Promise<void>;
  stop: () => void;
  selectDevice: (deviceId: string) => Promise<void>;
}

const CONSTRAINTS: MediaTrackConstraints = {
  // 1280x720 requested, not demanded. `ideal` degrades on a device that cannot
  // manage it; `exact` would fail outright, and a 640x480 capture is still far
  // above the 112 px inter-ocular minimum.
  width: { ideal: 1280 },
  height: { ideal: 720 },
  facingMode: "user",
};

export function useCamera(): UseCameraResult {
  const [status, setStatus] = React.useState<CameraStatus>("idle");
  const [stream, setStream] = React.useState<MediaStream | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [devices, setDevices] = React.useState<CameraDevice[]>([]);
  const [deviceId, setDeviceId] = React.useState<string | null>(null);

  // Mirrors `stream` for the unmount cleanup, which must not re-run every time
  // the stream changes or it would tear down the stream it just started.
  const streamRef = React.useRef<MediaStream | null>(null);

  const stop = React.useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setStream(null);
    setStatus("idle");
  }, []);

  const start = React.useCallback(async (requestedDeviceId?: string) => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      // Almost always a non-secure origin rather than missing hardware.
      setStatus(window.isSecureContext === false ? "insecure" : "unavailable");
      return;
    }

    setStatus("requesting");
    setError(null);

    try {
      streamRef.current?.getTracks().forEach((track) => track.stop());

      const media = await navigator.mediaDevices.getUserMedia({
        video: requestedDeviceId
          ? { ...CONSTRAINTS, deviceId: { exact: requestedDeviceId } }
          : CONSTRAINTS,
        audio: false,
      });

      streamRef.current = media;
      setStream(media);
      setStatus("ready");
      setDeviceId(media.getVideoTracks()[0]?.getSettings().deviceId ?? null);

      // Labels are blank until permission is granted, so enumerate *after*
      // the prompt or the picker would show "Camera 1", "Camera 2".
      const all = await navigator.mediaDevices.enumerateDevices();
      setDevices(
        all
          .filter((device) => device.kind === "videoinput")
          .map((device, index) => ({
            deviceId: device.deviceId,
            label: device.label || `Camera ${index + 1}`,
          })),
      );
    } catch (cause) {
      const name = cause instanceof DOMException ? cause.name : "";
      if (name === "NotAllowedError" || name === "SecurityError") {
        setStatus("denied");
      } else if (name === "NotFoundError" || name === "OverconstrainedError") {
        setStatus("unavailable");
      } else if (name === "NotReadableError") {
        setStatus("error");
        setError("Another application is using the camera.");
      } else {
        setStatus("error");
        setError(cause instanceof Error ? cause.message : "The camera could not be started.");
      }
    }
  }, []);

  const selectDevice = React.useCallback(
    async (nextDeviceId: string) => {
      setDeviceId(nextDeviceId);
      await start(nextDeviceId);
    },
    [start],
  );

  React.useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  return { status, stream, error, devices, deviceId, start, stop, selectDevice };
}
