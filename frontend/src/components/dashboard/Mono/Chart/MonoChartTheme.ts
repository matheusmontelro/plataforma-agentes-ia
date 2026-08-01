// Mono — tema do recharts passado como LITERAIS JS (recharts SVG não lê var() de forma confiável).

export interface MonoPalette {
  axis: string;
  c0: string;
  c1: string;
  c2: string;
  c3: string;
  c4: string;
  c5: string;
  c6: string;
  grid: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
}

export const monoChartPalette = (isDark: boolean): MonoPalette =>
  isDark
    ? {
        c0: '#f7f7f7',
        c1: 'rgba(247,247,247,0.55)',
        c2: 'rgba(247,247,247,0.30)',
        c3: '#2dd4bf',
        c4: 'rgba(247,247,247,0.20)',
        c5: 'rgba(247,247,247,0.14)',
        c6: '#9ca3af',
        grid: 'rgba(255,255,255,0.07)',
        axis: 'rgba(247,247,247,0.55)',
        tooltipBg: '#08091f',
        tooltipBorder: 'rgba(255,255,255,0.14)',
        tooltipText: '#f7f7f7',
      }
    : {
        c0: '#020323',
        c1: 'rgba(2,3,35,0.55)',
        c2: 'rgba(2,3,35,0.30)',
        c3: '#0f766e',
        c4: 'rgba(2,3,35,0.18)',
        c5: 'rgba(2,3,35,0.12)',
        c6: '#6b7280',
        grid: 'rgba(2,3,35,0.06)',
        axis: 'rgba(2,3,35,0.55)',
        tooltipBg: '#ffffff',
        tooltipBorder: 'rgba(2,3,35,0.12)',
        tooltipText: '#020323',
      };

const COLOR_BY_INDEX: Record<number, keyof MonoPalette> = {
  1: 'c1',
  2: 'c2',
  3: 'c3',
  4: 'c4',
  5: 'c5',
  6: 'c6',
};

/** Padrão de dash por índice (1-based) da série de estágio — garante distinção em daltônico. */
const DASH_BY_INDEX: Record<number, string> = {
  2: '4 3',
  4: '2 3',
  5: '7 4',
};

export const monoSeriesColor = (palette: MonoPalette, index: number) => {
  const key = COLOR_BY_INDEX[index] || 'c6';
  return palette[key];
};

export const monoSeriesDash = (index: number) => DASH_BY_INDEX[index];

/** Limite de séries individuais antes de agregar em 'Outros' (c6). Leads = c0 fora desta contagem. */
export const MONO_MAX_VISIBLE_STAGES = 5;
