import { describe, expect, it } from "vitest";

import { comparison, plans, recommendPlan } from "./pricing";

describe("plans", () => {
  it("exposes exactly one featured plan", () => {
    // Two "most popular" badges is a design bug that only shows up visually.
    expect(plans.filter((plan) => plan.featured)).toHaveLength(1);
  });

  it("orders metered tiers by ascending volume", () => {
    const metered = plans
      .filter((plan) => plan.verifications !== null)
      .map((plan) => plan.verifications!);
    expect([...metered].sort((a, b) => a - b)).toEqual(metered);
  });

  it("lowers the overage rate as the plan grows", () => {
    // A larger plan charging more per unit would be indefensible to a buyer.
    const rates = plans.filter((p) => p.overage !== null).map((p) => p.overage!);
    expect([...rates].sort((a, b) => b - a)).toEqual(rates);
  });

  it("gives every comparison row a value for every plan", () => {
    for (const group of comparison) {
      for (const row of group.rows) {
        expect(row.values, `${group.group} → ${row.label}`).toHaveLength(plans.length);
      }
    }
  });
});

describe("recommendPlan", () => {
  it("recommends Free at low volume with no overage", () => {
    const result = recommendPlan(500);
    expect(result.plan.id).toBe("free");
    expect(result.monthlyCost).toBe(0);
    expect(result.overageUnits).toBe(0);
  });

  it("recommends the smallest plan that fits", () => {
    expect(recommendPlan(1_000).plan.id).toBe("free");
    expect(recommendPlan(1_001).plan.id).toBe("startup");
    expect(recommendPlan(25_000).plan.id).toBe("startup");
    expect(recommendPlan(25_001).plan.id).toBe("growth");
  });

  it("adds overage past the largest metered tier", () => {
    const result = recommendPlan(200_000);

    expect(result.plan.id).toBe("growth");
    expect(result.overageUnits).toBe(50_000);
    expect(result.overageCost).toBeCloseTo(100, 5); // 50,000 × $0.002
    expect(result.monthlyCost).toBeCloseTo(299, 5); // $199 + $100
  });

  it("hands off to Enterprise past a million", () => {
    // Beyond this a negotiated contract genuinely beats metered overage, and
    // quoting a metered price would mislead the buyer.
    const result = recommendPlan(1_500_000);
    expect(result.plan.id).toBe("enterprise");
    expect(result.monthlyCost).toBeNull();
  });

  it("never quotes a cost per verification worse than the overage rate", () => {
    for (const volume of [2_000, 30_000, 100_000, 400_000]) {
      const result = recommendPlan(volume);
      if (result.monthlyCost === null) continue;

      const perVerification = result.monthlyCost / volume;
      expect(perVerification, `at ${volume}`).toBeLessThan(0.05);
    }
  });

  it("is monotonic — more volume never costs less", () => {
    let previous = -1;
    for (const volume of [100, 1_000, 5_000, 25_000, 50_000, 150_000, 500_000]) {
      const { monthlyCost } = recommendPlan(volume);
      if (monthlyCost === null) break;
      expect(monthlyCost, `at ${volume}`).toBeGreaterThanOrEqual(previous);
      previous = monthlyCost;
    }
  });
});
