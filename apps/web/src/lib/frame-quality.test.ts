import { describe, expect, it } from "vitest";

import {
  ANALYSIS_HEIGHT,
  ANALYSIS_WIDTH,
  analyseLuma,
  laplacianVariance,
  meanBrightness,
  motionBetween,
  toLuma,
  verdict,
} from "./frame-quality";

const SIZE = ANALYSIS_WIDTH * ANALYSIS_HEIGHT;

function flat(value: number): Float32Array {
  return new Float32Array(SIZE).fill(value);
}

/** Alternating columns — high spatial frequency, i.e. a sharp image. */
function striped(low: number, high: number): Float32Array {
  const luma = new Float32Array(SIZE);
  for (let y = 0; y < ANALYSIS_HEIGHT; y += 1) {
    for (let x = 0; x < ANALYSIS_WIDTH; x += 1) {
      luma[y * ANALYSIS_WIDTH + x] = x % 2 === 0 ? low : high;
    }
  }
  return luma;
}

describe("toLuma", () => {
  it("weights green above red above blue, per BT.601", () => {
    // Three pure primaries at full intensity, in RGBA order. A naive average
    // would rank them equal, and the exposure meter would then be wrong on
    // anything that is not grey — a blue-lit room would read as bright as a
    // green-lit one.
    const pixels = new Uint8ClampedArray([
      255,
      0,
      0,
      255, // red
      0,
      255,
      0,
      255, // green
      0,
      0,
      255,
      255, // blue
    ]);
    const [red, green, blue] = toLuma(pixels, 3);

    expect(red).toBeCloseTo(0.299 * 255, 1);
    expect(green).toBeCloseTo(0.587 * 255, 1);
    expect(blue).toBeCloseTo(0.114 * 255, 1);
    expect(green).toBeGreaterThan(red!);
    expect(red).toBeGreaterThan(blue!);
  });
});

describe("meanBrightness", () => {
  it("normalises to 0–1", () => {
    expect(meanBrightness(flat(0))).toBe(0);
    expect(meanBrightness(flat(255))).toBe(1);
    expect(meanBrightness(flat(128))).toBeCloseTo(0.502, 2);
  });
});

describe("laplacianVariance", () => {
  it("is zero on a flat frame", () => {
    // A blank wall, or a lens cap. No detail means no focus signal.
    expect(laplacianVariance(flat(120), ANALYSIS_WIDTH, ANALYSIS_HEIGHT)).toBeCloseTo(0, 5);
  });

  it("rises with contrast at high spatial frequency", () => {
    const faint = laplacianVariance(striped(120, 130), ANALYSIS_WIDTH, ANALYSIS_HEIGHT);
    const strong = laplacianVariance(striped(40, 220), ANALYSIS_WIDTH, ANALYSIS_HEIGHT);

    expect(strong).toBeGreaterThan(faint);
    expect(faint).toBeGreaterThan(0);
  });
});

describe("motionBetween", () => {
  it("is zero for identical frames", () => {
    expect(motionBetween(flat(100), flat(100))).toBe(0);
  });

  it("grows with the difference", () => {
    expect(motionBetween(flat(100), flat(110))).toBeCloseTo(10, 5);
  });

  it("returns zero rather than throwing on a shape change", () => {
    // Happens for one frame when the user switches camera mid-capture.
    expect(motionBetween(new Float32Array(10), new Float32Array(20))).toBe(0);
  });
});

describe("analyseLuma", () => {
  it("treats the first frame as stable", () => {
    // Otherwise the very first sample would flash "hold still" at someone who
    // has not moved.
    const result = analyseLuma(flat(120), ANALYSIS_WIDTH, ANALYSIS_HEIGHT, null);
    expect(result.stability).toBe(1);
  });

  it("reports instability when the frame changes a lot", () => {
    const result = analyseLuma(flat(200), ANALYSIS_WIDTH, ANALYSIS_HEIGHT, flat(120));
    expect(result.stability).toBe(0);
  });
});

describe("verdict", () => {
  const good = { brightness: 0.5, sharpness: 0.6, stability: 1 };

  it("passes a well-exposed, sharp, still frame", () => {
    const result = verdict(good);
    expect(result.ok).toBe(true);
    expect(result.hint).toBeNull();
  });

  it.each([
    ["too dark", { ...good, brightness: 0.05 }, /dark/i],
    ["too bright", { ...good, brightness: 0.97 }, /bright/i],
    ["moving", { ...good, stability: 0.2 }, /still/i],
    ["blurred", { ...good, sharpness: 0.02 }, /blur/i],
  ])("explains %s in words a user can act on", (_label, quality, pattern) => {
    const result = verdict(quality);
    expect(result.ok).toBe(false);
    expect(result.hint).toMatch(pattern);
  });

  it("raises lighting before motion when both fail", () => {
    // Someone in a dark room cannot hold still their way to a usable frame.
    const result = verdict({ brightness: 0.05, sharpness: 0.6, stability: 0.1 });
    expect(result.hint).toMatch(/dark/i);
  });
});
