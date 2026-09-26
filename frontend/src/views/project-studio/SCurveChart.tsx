import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { Card } from '@/components/ui/Card'
import { formatINR, formatPct } from '@/lib/formatters'
import type { SCurveDataPoint } from '@/contracts/project'

interface SCurveChartProps {
  data: SCurveDataPoint[]
}

export function SCurveChart({ data }: SCurveChartProps) {
  return (
    <Card
      variant="section"
      title="Earned Value S-Curve & Trajectory"
      titleRight={<span className="text-fg-dimmed hidden sm:inline">Planned Baseline vs. Actual vs. ML Projection</span>}
      className="h-full flex flex-col"
    >
      <div className="flex-1 w-full p-2 min-h-[300px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 10, right: 30, left: 20, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#ccd1da" />
            <XAxis
              dataKey="quarter"
              stroke="#707987"
              fontSize={11}
              fontFamily="IBM Plex Mono"
              tickLine={false}
            />
            {/* Left Y Axis: Expenditure (₹ Cr) */}
            <YAxis
              yAxisId="left"
              width={85}
              stroke="#707987"
              fontSize={11}
              fontFamily="IBM Plex Mono"
              tickLine={false}
              tickFormatter={(val) => `₹${val}Cr`}
              label={{
                value: 'Cumulative Spend (₹ Cr)',
                angle: -90,
                position: 'insideLeft',
                offset: 10,
                fill: '#4d5563',
                fontSize: 10,
                fontFamily: 'IBM Plex Sans',
              }}
            />
            {/* Right Y Axis: Physical Progress % */}
            <YAxis
              yAxisId="right"
              orientation="right"
              stroke="#0b7249"
              fontSize={11}
              fontFamily="IBM Plex Mono"
              domain={[0, 100]}
              tickLine={false}
              tickFormatter={(val) => `${val}%`}
              label={{
                value: 'Physical Progress %',
                angle: 90,
                position: 'insideRight',
                offset: 10,
                fill: '#0b7249',
                fontSize: 10,
                fontFamily: 'IBM Plex Sans',
              }}
            />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload || !payload.length) return null

                return (
                  <div className="border border-border-default bg-surface-panel p-3 font-mono text-xs">
                    <div className="font-bold text-fg-base border-b border-border-subtle pb-1.5 mb-2">
                      {label} Telemetry
                    </div>
                    <div className="space-y-1.5">
                      {payload.map((item) => (
                        <div key={item.name} className="flex items-center justify-between gap-4">
                          <span style={{ color: item.color }} className="flex items-center gap-1.5">
                            <span
                              className="h-2 w-2 rounded-full inline-block"
                              style={{ backgroundColor: item.color }}
                            />
                            {item.name}:
                          </span>
                          <span className="font-semibold text-fg-base">
                            {item.name === 'Physical Progress'
                              ? formatPct(item.value as number)
                              : formatINR(item.value as number)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              }}
            />
            <Legend
              verticalAlign="top"
              height={36}
              wrapperStyle={{ fontSize: '11px', fontFamily: 'IBM Plex Sans' }}
            />

            {/* Baseline Planned Spend */}
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="plannedSpendCr"
              name="Planned Baseline"
              stroke="#707987"
              strokeWidth={2}
              strokeDasharray="4 4"
              dot={false}
            />

            {/* Actual Spend */}
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="actualSpendCr"
              name="Actual Spend"
              stroke="#1946b8"
              strokeWidth={2.5}
              dot={{ r: 4, fill: '#1946b8' }}
            />

            {/* Projected Spend */}
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="projectedSpendCr"
              name="ML Projected Trajectory"
              stroke="#ba1b2b"
              strokeWidth={2.5}
              strokeDasharray="5 3"
              dot={{ r: 4, fill: '#ba1b2b' }}
            />

            {/* Physical Progress % */}
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="physicalProgressPct"
              name="Physical Progress"
              stroke="#0b7249"
              strokeWidth={2}
              dot={{ r: 3, fill: '#0b7249' }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}
