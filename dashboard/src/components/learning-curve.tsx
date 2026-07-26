import { formatDuration } from "@/lib/format";
import { bestReplayImprovement } from "@/lib/snapshot";
import type { LearningPoint } from "@/lib/types";

const WIDTH = 760;
const HEIGHT = 238;
const LEFT = 54;
const RIGHT = 22;
const TOP = 24;
const BOTTOM = 46;

export function LearningCurve({ points }: { points: LearningPoint[] }) {
  const maximum = Math.max(...points.map((point) => point.diagnosisMs), 1);
  const chartWidth = WIDTH - LEFT - RIGHT;
  const chartHeight = HEIGHT - TOP - BOTTOM;
  const position = (point: LearningPoint, index: number) => {
    const x =
      points.length === 1
        ? LEFT + chartWidth / 2
        : LEFT + (index / (points.length - 1)) * chartWidth;
    const y = TOP + chartHeight - (point.diagnosisMs / maximum) * chartHeight;
    return { x, y };
  };
  const path = points
    .map((point, index) => {
      const { x, y } = position(point, index);
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");
  const bestImprovement = bestReplayImprovement(points);

  return (
    <section className="panel learning-panel" aria-labelledby="learning-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">EPISODIC MEMORY / MEASURED</p>
          <h2 id="learning-title">The second diagnosis knows where to look.</h2>
        </div>
        <div className="learning-callout">
          <span>BEST VERIFIED REPLAY</span>
          <strong>{bestImprovement === null ? "N/A" : `${bestImprovement.toFixed(1)}% faster`}</strong>
        </div>
      </div>

      {points.length > 0 ? (
        <>
          <div className="chart-wrap">
            <svg
              className="learning-chart"
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              role="img"
              aria-label="Diagnosis time across measured completed runs"
            >
              {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
                const y = TOP + chartHeight - ratio * chartHeight;
                return (
                  <g key={ratio}>
                    <line x1={LEFT} x2={WIDTH - RIGHT} y1={y} y2={y} className="chart-grid" />
                    <text x={LEFT - 10} y={y + 4} textAnchor="end" className="chart-label">
                      {formatDuration(Math.round(maximum * ratio))}
                    </text>
                  </g>
                );
              })}
              <path d={path} className="chart-path" />
              {points.map((point, index) => {
                const { x, y } = position(point, index);
                const assisted = point.precedentCount > 0;
                return (
                  <g key={point.runId}>
                    <line x1={x} x2={x} y1={y} y2={HEIGHT - BOTTOM} className="chart-stem" />
                    <circle
                      cx={x}
                      cy={y}
                      r={assisted ? 7 : 6}
                      className={assisted ? "chart-point assisted" : "chart-point cold"}
                    >
                      <title>
                        {point.runId}: {formatDuration(point.diagnosisMs)},{" "}
                        {assisted ? `${point.precedentCount} precedent(s)` : "novel incident"}
                      </title>
                    </circle>
                    <text x={x} y={HEIGHT - 19} textAnchor="middle" className="chart-run-label">
                      {index + 1}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
          <div className="chart-legend">
            <span>
              <i className="legend-dot cold" /> Novel incident
            </span>
            <span>
              <i className="legend-dot assisted" /> Precedent cited
            </span>
            <span className="chart-note">
              Measured end-to-end observations. Timeout chaos runs excluded.
            </span>
          </div>
        </>
      ) : (
        <p className="empty-state">No completed measured runs are available yet.</p>
      )}
    </section>
  );
}
