/**
 * Client-side frame analysis for the capture UI.
 *
 * **These are hints, not decisions.** The server owns the quality gates, and its
 * answer is the only one that counts. What this buys is latency: telling
 * someone their room is too dark takes 3 ms here and a full round trip plus an
 * ONNX inference there. A capture UI that can only say "too dark" *after*
 * submitting is a capture UI people give up on.
 *
 * Only the three gates that need no face model are computed here — exposure,
 * focus, and stability. Face size and head pose need a detector, so they come
 * back from the server after the first shot and drive the prompts from there.
 * Shipping a second face model to the browser to duplicate the gates would cost
 * megabytes and introduce a way for client and server to disagree.
 *
 * Everything runs on a downscaled copy. At 128x96 the whole analysis is well
 * under a millisecond, which is what makes it safe to run several times a
 * second on a phone.
 */

/** Working resolution for analysis. Small on purpose — see the module note. */
export const ANALYSIS_WIDTH = 128;
export const ANALYSIS_HEIGHT = 96;

export interface FrameQuality {
  /** Mean luma, 0–1. Usable range is roughly 0.25–0.85. */
  brightness: number;
  /** Normalised Laplacian variance, 0–1. Higher is sharper. */
  sharpness: number;
  /** 1 when the frame is still, falling as motion increases. */
  stability: number;
}

export interface QualityVerdict extends FrameQuality {
  ok: boolean;
  /** The single most useful thing to tell the user right now, or null. */
  hint: string | null;
}

/**
 * Calibrated against a downscaled webcam frame, not against the server's
 * thresholds. The server measures the *face crop* at full resolution, so the
 * two scales are not comparable and pretending they are would produce a HUD
 * that contradicts the result.
 */
const MIN_BRIGHTNESS = 0.22;
const MAX_BRIGHTNESS = 0.88;
const MIN_SHARPNESS = 0.18;
const MIN_STABILITY = 0.7;

/** Laplacian variance of a well-focused downscaled frame, empirically. */
const SHARPNESS_CEILING = 320;
/** Mean absolute inter-frame luma delta that reads as "clearly moving". */
const MOTION_CEILING = 14;

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value));

/**
 * BT.601 luma from RGBA bytes.
 *
 * The `!` assertions through this module are on typed-array reads whose indices
 * are bounded by the loop itself. `noUncheckedIndexedAccess` cannot see that,
 * and the alternative — a `?? 0` per read — would add a branch to an inner loop
 * that runs 12,288 times per sample.
 */
export function toLuma(pixels: Uint8ClampedArray, length: number): Float32Array {
  const luma = new Float32Array(length);
  for (let index = 0; index < length; index += 1) {
    const offset = index * 4;
    luma[index] =
      0.299 * pixels[offset]! + 0.587 * pixels[offset + 1]! + 0.114 * pixels[offset + 2]!;
  }
  return luma;
}

export function meanBrightness(luma: Float32Array): number {
  let total = 0;
  for (let index = 0; index < luma.length; index += 1) total += luma[index]!;
  return clamp01(total / luma.length / 255);
}

/**
 * Variance of the 4-neighbour Laplacian — the standard focus measure.
 *
 * Motion blur is the top cause of a rejected capture and it is invisible in a
 * small preview, which is exactly why it is measured rather than left to the
 * person holding the phone.
 */
export function laplacianVariance(luma: Float32Array, width: number, height: number): number {
  let sum = 0;
  let sumSquares = 0;
  let count = 0;

  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const index = y * width + x;
      const value =
        -4 * luma[index]! +
        luma[index - width]! +
        luma[index + width]! +
        luma[index - 1]! +
        luma[index + 1]!;
      sum += value;
      sumSquares += value * value;
      count += 1;
    }
  }

  if (count === 0) return 0;
  const mean = sum / count;
  return sumSquares / count - mean * mean;
}

/** Mean absolute luma difference between two frames of identical shape. */
export function motionBetween(current: Float32Array, previous: Float32Array): number {
  if (previous.length !== current.length) return 0;
  let total = 0;
  for (let index = 0; index < current.length; index += 1) {
    total += Math.abs(current[index]! - previous[index]!);
  }
  return total / current.length;
}

export function analyseLuma(
  luma: Float32Array,
  width: number,
  height: number,
  previous: Float32Array | null,
): FrameQuality {
  return {
    brightness: meanBrightness(luma),
    sharpness: clamp01(laplacianVariance(luma, width, height) / SHARPNESS_CEILING),
    stability: previous
      ? clamp01(1 - motionBetween(luma, previous) / MOTION_CEILING)
      : // No previous frame yet. Optimistic rather than pessimistic, so the
        // very first sample cannot flash a spurious "hold still" prompt.
        1,
  };
}

/**
 * Turn measurements into the one sentence worth showing.
 *
 * Ordered by what a person can fix fastest, not by severity. Someone in a dark
 * room cannot hold still their way to a usable frame, so lighting is raised
 * first even when motion is also failing.
 */
export function verdict(quality: FrameQuality): QualityVerdict {
  let hint: string | null = null;

  if (quality.brightness < MIN_BRIGHTNESS) {
    hint = "Too dark — find a brighter spot or face a window.";
  } else if (quality.brightness > MAX_BRIGHTNESS) {
    hint = "Too bright — move away from the light behind you.";
  } else if (quality.stability < MIN_STABILITY) {
    hint = "Hold still.";
  } else if (quality.sharpness < MIN_SHARPNESS) {
    hint = "Image looks blurred — clean the lens or move slightly back.";
  }

  return { ...quality, ok: hint === null, hint };
}

export const QUALITY_LIMITS = {
  brightness: { min: MIN_BRIGHTNESS, max: MAX_BRIGHTNESS },
  sharpness: { min: MIN_SHARPNESS },
  stability: { min: MIN_STABILITY },
} as const;
