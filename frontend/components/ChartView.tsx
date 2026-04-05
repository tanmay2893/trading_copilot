"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useImperativeHandle, forwardRef } from "react";
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
} from "lightweight-charts";
import { fetchChartData } from "@/lib/api";
import type { ChartData } from "@/lib/types";

export interface ChartViewHandle {
  takeScreenshot: () => string | null;
}

interface ChartViewProps {
  sessionId: string;
  onBack: () => void;
  dataVersion?: number;
}

const INDICATOR_COLORS = [
  "#6366f1", "#f59e0b", "#22c55e", "#ef4444", "#8b5cf6",
  "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#14b8a6",
];

const OVERLAY_KEYWORDS = [
  "sma", "ema", "wma", "vwap", "bollinger", "bb_upper", "bb_lower",
  "bb_mid", "keltner", "ichimoku", "senkou", "tenkan", "kijun",
  "upper_band", "lower_band", "middle_band", "moving_avg",
];

function isOverlayIndicator(name: string, values: { value: number }[], priceMin: number, priceMax: number): boolean {
  const lower = name.toLowerCase();
  if (OVERLAY_KEYWORDS.some((kw) => lower.includes(kw))) return true;

  if (values.length === 0) return false;
  const vals = values.map((v) => v.value).filter((v) => v != null);
  if (vals.length === 0) return false;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const priceRange = priceMax - priceMin;
  if (priceRange === 0) return true;
  return min > priceMin - priceRange && max < priceMax + priceRange;
}

function toNumericSeries(series: { time: string; value: unknown }[]): { time: string; value: number }[] {
  return series
    .map((p) => {
      const v = p.value;
      if (v == null) return null;
      if (typeof v === "number" && Number.isFinite(v)) return { time: p.time, value: v };
      if (typeof v === "boolean") return { time: p.time, value: v ? 1 : 0 };
      return null;
    })
    .filter((p): p is { time: string; value: number } => p != null);
}

function getIndicatorClassification(data: ChartData) {
  const prices = data.ohlcv
    .filter((b) => b.open != null && b.high != null && b.low != null && b.close != null)
    .map((b) => b.close as number);
  if (prices.length === 0) return { overlays: [] as [string, { time: string; value: number }[]][], separates: [] as [string, { time: string; value: number }[]][], hasVolume: false };
  const priceMin = Math.min(...prices);
  const priceMax = Math.max(...prices);
  const overlays: [string, { time: string; value: number }[]][] = [];
  const separates: [string, { time: string; value: number }[]][] = [];
  for (const [name, series] of Object.entries(data.indicators)) {
    if (series.length === 0) continue;
    const numericSeries = toNumericSeries(series);
    if (numericSeries.length === 0) continue;
    if (isOverlayIndicator(name, numericSeries, priceMin, priceMax)) {
      overlays.push([name, numericSeries]);
    } else {
      separates.push([name, numericSeries]);
    }
  }
  const hasVolume = data.ohlcv.some((b) => b.volume != null);
  return { overlays, separates, hasVolume };
}

function parseTime(raw: string): Time {
  const d = raw.replace(" ", "T");
  if (d.length === 10) return d as Time;
  const dt = new Date(d);
  return (Math.floor(dt.getTime() / 1000)) as Time;
}

export const ChartView = forwardRef<ChartViewHandle, ChartViewProps>(function ChartView({ sessionId, onBack, dataVersion }, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRefsRef = useRef<Map<string, ISeriesApi<"Line" | "Histogram", Time>>>(new Map());
  const visibilityRef = useRef<Record<string, boolean>>({});
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [indicatorVisibility, setIndicatorVisibility] = useState<Record<string, boolean>>({});

  useImperativeHandle(ref, () => ({
    takeScreenshot: () => {
      if (!chartRef.current) return null;
      try {
        const canvas = chartRef.current.takeScreenshot();
        return canvas.toDataURL("image/png");
      } catch {
        return null;
      }
    },
  }), []);

  useEffect(() => {
    setLoading(true);
    setError("");
    fetchChartData(sessionId)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [sessionId, dataVersion]);

  const buildChart = useCallback(() => {
    if (!containerRef.current || !data || data.ohlcv.length === 0) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#0a0a0f" },
        textColor: "#9494a8",
        fontFamily: "'Inter', sans-serif",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: "#1a1a2e" },
        horzLines: { color: "#1a1a2e" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#2a2a3e" },
      timeScale: {
        borderColor: "#2a2a3e",
        timeVisible: true,
        secondsVisible: false,
      },
    });
    chartRef.current = chart;

    const candlestickData: CandlestickData[] = data.ohlcv
      .filter((b) => b.open != null && b.high != null && b.low != null && b.close != null)
      .map((b) => ({
        time: parseTime(b.time),
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }));

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    candleSeries.setData(candlestickData);

    // Classify indicators and get current visibility for all overlays/volume
    const { overlays, separates, hasVolume } = getIndicatorClassification(data);
    seriesRefsRef.current.clear();
    const visibility = visibilityRef.current;

    // Volume histogram
    const volumeData: HistogramData[] = data.ohlcv
      .filter((b) => b.volume != null)
      .map((b) => ({
        time: parseTime(b.time),
        value: b.volume,
        color: b.close >= b.open ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)",
      }));

    if (volumeData.length > 0) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      volumeSeries.setData(volumeData);
      seriesRefsRef.current.set("Volume", volumeSeries as ISeriesApi<"Histogram", Time>);
      volumeSeries.applyOptions({ visible: visibility["Volume"] !== false });
    }

    overlays.forEach(([name, series], i) => {
      const color = INDICATOR_COLORS[i % INDICATOR_COLORS.length];
      const indicatorSeries = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        title: name,
        priceScaleId: "right",
      });
      const lineData: LineData[] = series.map((p) => ({
        time: parseTime(p.time),
        value: p.value,
      }));
      indicatorSeries.setData(lineData);
      seriesRefsRef.current.set(name, indicatorSeries as ISeriesApi<"Line", Time>);
      indicatorSeries.applyOptions({ visible: visibility[name] !== false });
    });

    separates.forEach(([name, series], i) => {
      const color = INDICATOR_COLORS[(overlays.length + i) % INDICATOR_COLORS.length];
      const scaleId = `indicator_${i}`;
      const indicatorSeries = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        title: name,
        priceScaleId: scaleId,
      });
      indicatorSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.8 + i * 0.05, bottom: 0 },
      });
      const lineData: LineData[] = series.map((p) => ({
        time: parseTime(p.time),
        value: p.value,
      }));
      indicatorSeries.setData(lineData);
      seriesRefsRef.current.set(name, indicatorSeries as ISeriesApi<"Line", Time>);
      indicatorSeries.applyOptions({ visible: visibility[name] !== false });
    });

    // Signal markers
    if (data.signals.length > 0) {
      const markers = data.signals
        .map((s) => ({
          time: parseTime(s.time),
          position: s.signal === "BUY" ? ("belowBar" as const) : ("aboveBar" as const),
          color: s.signal === "BUY" ? "#22c55e" : "#ef4444",
          shape: s.signal === "BUY" ? ("arrowUp" as const) : ("arrowDown" as const),
          text: s.signal,
        }))
        .sort((a, b) => (a.time as number) - (b.time as number));

      createSeriesMarkers(candleSeries, markers);
    }

    chart.timeScale().fitContent();

    return chart;
  }, [data]);

  const legendItems = useMemo(() => {
    if (!data) return [];
    const { overlays, separates, hasVolume } = getIndicatorClassification(data);
    const items: { name: string; color: string }[] = [];
    overlays.forEach(([name], i) => {
      items.push({ name, color: INDICATOR_COLORS[i % INDICATOR_COLORS.length] });
    });
    separates.forEach(([name], i) => {
      items.push({ name, color: INDICATOR_COLORS[(overlays.length + i) % INDICATOR_COLORS.length] });
    });
    if (hasVolume) items.push({ name: "Volume", color: "rgba(148, 163, 184, 0.9)" });
    return items;
  }, [data]);

  useEffect(() => {
    if (legendItems.length === 0) return;
    setIndicatorVisibility((prev) => {
      const next = { ...prev };
      legendItems.forEach(({ name }) => {
        if (!(name in next)) next[name] = true;
      });
      return next;
    });
  }, [legendItems]);

  useEffect(() => {
    visibilityRef.current = indicatorVisibility;
    for (const [name, visible] of Object.entries(indicatorVisibility)) {
      seriesRefsRef.current.get(name)?.applyOptions({ visible });
    }
  }, [indicatorVisibility]);

  useEffect(() => {
    const chart = buildChart();
    if (!chart || !containerRef.current) return;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        chart.applyOptions({ width, height });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRefsRef.current.clear();
    };
  }, [buildChart]);

  const buyCount = data?.signals.filter((s) => s.signal === "BUY").length ?? 0;
  const sellCount = data?.signals.filter((s) => s.signal === "SELL").length ?? 0;

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--bg-primary)]">
      {/* Header */}
      <header className="flex-shrink-0 border-b border-[var(--border)] px-6 py-3 flex items-center justify-between bg-[var(--bg-secondary)]">
        <div className="flex items-center gap-4">
          <button
            onClick={onBack}
            className="flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
            Back to chat
          </button>
          {data && (
            <div className="flex items-center gap-3 ml-4 pl-4 border-l border-[var(--border)]">
              <span className="text-base font-semibold text-[var(--text-primary)]">
                {data.ticker}
              </span>
              <span className="text-xs px-2 py-0.5 rounded bg-[var(--bg-tertiary)] text-[var(--text-muted)] font-mono">
                {data.interval}
              </span>
            </div>
          )}
        </div>
        {data && (
          <div className="flex items-center gap-4 text-xs">
            <span className="text-[var(--success)]">{buyCount} BUY</span>
            <span className="text-[var(--error)]">{sellCount} SELL</span>
            <span className="text-[var(--text-muted)]">{data.ohlcv.length} bars</span>
            {Object.keys(data.indicators).length > 0 && (
              <span className="text-[var(--text-muted)]">
                {Object.keys(data.indicators).length} indicator{Object.keys(data.indicators).length !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        )}
      </header>

      {/* Chart area */}
      <div className="flex-1 relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-[var(--bg-primary)]">
            <div className="flex items-center gap-3 text-[var(--text-muted)]">
              <svg className="w-5 h-5 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" strokeLinecap="round" />
              </svg>
              Loading chart data...
            </div>
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-[var(--bg-primary)]">
            <div className="text-center">
              <p className="text-[var(--error)] mb-2">{error}</p>
              <button
                onClick={onBack}
                className="text-sm text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors"
              >
                Go back and run a backtest
              </button>
            </div>
          </div>
        )}
        {!loading && !error && legendItems.length > 0 && (
          <div className="absolute top-3 left-3 z-10 flex flex-col gap-1 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)]/95 px-3 py-2 shadow-lg backdrop-blur-sm">
            <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-0.5">
              Indicators
            </span>
            {legendItems.map(({ name, color }) => {
              const isVisible = indicatorVisibility[name] !== false;
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => {
                    setIndicatorVisibility((prev) => ({ ...prev, [name]: !(prev[name] !== false) }));
                  }}
                  className="flex items-center gap-2 rounded px-2 py-1 text-left text-xs transition-colors hover:bg-[var(--bg-tertiary)]"
                >
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: color, opacity: isVisible ? 1 : 0.35 }}
                  />
                  <span className={isVisible ? "text-[var(--text-primary)]" : "text-[var(--text-muted)] line-through"}>
                    {name}
                  </span>
                </button>
              );
            })}
          </div>
        )}
        <div ref={containerRef} className="w-full h-full" />
      </div>
    </div>
  );
});
