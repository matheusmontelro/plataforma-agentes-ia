import React, { useEffect, useMemo, useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { DailyFunnelItem } from '../../../../services/api';
import type { PipelineStage } from '../../../../services/crmApi';
import { MonoChartEmpty } from '../States/MonoStates';
import {
  MONO_MAX_VISIBLE_STAGES,
  monoChartPalette,
  monoSeriesColor,
  monoSeriesDash,
} from './MonoChartTheme';
import { MonoTooltip } from './MonoTooltip';

interface MonoChartProps {
  dailyFunnelData: DailyFunnelItem[];
  isDark: boolean;
  stages: PipelineStage[];
}

interface SeriesSpec {
  color: string;
  dash?: string;
  key: string;
  name: string;
}

const getDailyValue = (item: DailyFunnelItem, key: string) => {
  const value = item[key];
  return typeof value === 'number' ? value : 0;
};

const MonoChartBase: React.FC<MonoChartProps> = ({ dailyFunnelData, isDark, stages }) => {
  const palette = useMemo(() => monoChartPalette(isDark), [isDark]);
  const [isFirstRender, setIsFirstRender] = useState(true);

  useEffect(() => {
    const id = window.setTimeout(() => setIsFirstRender(false), 500);
    return () => window.clearTimeout(id);
  }, []);

  const { overflowStages, series } = useMemo<{ overflowStages: PipelineStage[]; series: SeriesSpec[] }>(() => {
    const visible = stages.slice(0, MONO_MAX_VISIBLE_STAGES);
    const overflow = stages.slice(MONO_MAX_VISIBLE_STAGES);
    const list: SeriesSpec[] = [{ color: palette.c0, key: 'leads', name: 'Leads' }];
    visible.forEach((stage, index) => {
      list.push({
        color: monoSeriesColor(palette, index + 1),
        dash: monoSeriesDash(index + 1),
        key: stage.name,
        name: stage.name,
      });
    });
    if (overflow.length > 0) {
      list.push({ color: palette.c6, key: '__outros__', name: 'Outros' });
    }
    return { overflowStages: overflow, series: list };
  }, [palette, stages]);

  const chartData = useMemo(() => {
    return dailyFunnelData.map((item) => {
      const [year, month, day] = item.date.split('-');
      const date = new Date(Number(year), Number(month) - 1, Number(day));
      const row: Record<string, number | string> = {
        displayDate: date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }),
        leads: item.leads,
      };
      series.forEach((spec) => {
        if (spec.key === 'leads' || spec.key === '__outros__') return;
        row[spec.key] = getDailyValue(item, spec.key);
      });
      if (overflowStages.length > 0) {
        row.__outros__ = overflowStages.reduce((sum, stage) => sum + getDailyValue(item, stage.name), 0);
      }
      return row;
    });
  }, [dailyFunnelData, overflowStages, series]);

  if (chartData.length === 0) return <MonoChartEmpty />;
  if (chartData.length === 1) return <MonoChartEmpty singlePoint />;

  return (
    <div className="mono-chart">
      <ResponsiveContainer height="100%" width="100%">
        <LineChart data={chartData} margin={{ bottom: 0, left: 0, right: 10, top: 8 }}>
          <CartesianGrid horizontal vertical={false} stroke={palette.grid} strokeDasharray="3 3" />
          <XAxis
            axisLine={false}
            dataKey="displayDate"
            tick={{ fill: palette.axis, fontSize: 12 }}
            tickLine={false}
          />
          <YAxis axisLine={false} tick={{ fill: palette.axis, fontSize: 12 }} tickLine={false} width={34} />
          <RechartsTooltip content={<MonoTooltip />} cursor={{ stroke: palette.grid, strokeWidth: 1 }} />
          {series.map((spec) => (
            <Line
              dataKey={spec.key}
              dot={false}
              isAnimationActive={isFirstRender}
              key={spec.key}
              name={spec.name}
              stroke={spec.color}
              strokeDasharray={spec.dash}
              strokeWidth={spec.key === 'leads' ? 2.25 : 2}
              type="monotone"
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export const MonoChart = React.memo(MonoChartBase, (prev, next) =>
  prev.isDark === next.isDark && prev.stages === next.stages && prev.dailyFunnelData === next.dailyFunnelData,
);
