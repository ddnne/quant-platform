import { describe, expect, it } from "vitest";

import {
  personalVolPerformance,
  type PersonalVolDailyPoint,
} from "./personal_vol_metrics";

function points(returns: number[]): PersonalVolDailyPoint[] {
  let equity = 1;
  return returns.map((netReturn, index) => {
    equity *= 1 + netReturn;
    const date = new Date(Date.UTC(2024, 0, 2 + index * 2))
      .toISOString()
      .slice(0, 10);
    return { date, net_return: netReturn, equity };
  });
}

describe("personal vol comprehensive performance", () => {
  it("computes the common return, risk, hit, drawdown and tail metrics", () => {
    const metrics = personalVolPerformance(
      points([0.02, -0.01, 0.015, -0.03, 0.01, 0.005]),
      true,
    );

    expect(metrics.net_total_return).not.toBeNull();
    expect(metrics.cagr).not.toBeNull();
    expect(metrics.annualized_volatility).toBeGreaterThan(0);
    expect(metrics.annualized_sharpe).not.toBeNull();
    expect(metrics.annualized_sortino).not.toBeNull();
    expect(metrics.schema_version).toBe("personal-performance/v1");
    expect(metrics.total_return_net).toBe(metrics.net_total_return);
    expect(metrics.max_drawdown).toBeGreaterThan(0);
    expect(metrics.max_drawdown_duration_sessions).toBeGreaterThan(0);
    expect(metrics.daily_hit_rate).toBe(4 / 6);
    expect(metrics.positive_day_rate).toBe(4 / 6);
    expect(metrics.positive_active_day_rate).toBe(4 / 6);
    expect(metrics.calmar_ratio).toBe(metrics.calmar);
    expect(metrics.best_day).toBe(0.02);
    expect(metrics.worst_day).toBe(-0.03);
    expect(metrics.historical_var_95_loss).toBeGreaterThan(0);
    expect(metrics.historical_cvar_95_loss).toBeGreaterThan(0);
    expect(metrics.series_contiguity).toBe("contiguous_window");
  });

  it("never calls a non-contiguous stitch CAGR", () => {
    const metrics = personalVolPerformance(points([0.01, -0.005, 0.02]), false);

    expect(metrics.series_contiguity).toBe(
      "non_contiguous_six_window_stitch",
    );
    expect(metrics.cagr_applicable).toBe(false);
    expect(metrics.cagr).toBeNull();
    expect(metrics.calmar).toBeNull();
    expect(metrics.net_total_return).not.toBeNull();
  });
});
