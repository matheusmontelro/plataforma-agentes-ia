import React from 'react';
import { Alert, Button, Spinner, ThemeProvider } from 'flowbite-react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { monoFlowbiteClearTheme, monoFlowbiteProps, monoFlowbiteTheme } from '../flowbiteTheme';

interface FullPageProps {
  isDark: boolean;
}

export const MonoLoading: React.FC<FullPageProps> = ({ isDark }) => (
  <ThemeProvider
    clearTheme={monoFlowbiteClearTheme}
    props={monoFlowbiteProps}
    root
    theme={monoFlowbiteTheme}
  >
    <div className={`mono-dashboard ${isDark ? 'mono-dashboard--dark' : ''}`}>
      <div className="mono-loading-page">
        <div className="mono-loading-box">
          <Spinner aria-label="Carregando métricas" color="mono" size="lg" />
          <p>Carregando métricas...</p>
        </div>
      </div>
    </div>
  </ThemeProvider>
);

interface ErrorPageProps extends FullPageProps {
  error: string;
  onRefresh: () => void;
}

export const MonoError: React.FC<ErrorPageProps> = ({ error, isDark, onRefresh }) => (
  <ThemeProvider
    clearTheme={monoFlowbiteClearTheme}
    props={monoFlowbiteProps}
    root
    theme={monoFlowbiteTheme}
  >
    <div className={`mono-dashboard ${isDark ? 'mono-dashboard--dark' : ''}`}>
      <div className="mono-error-page">
        <div className="mono-error-box">
          <h1 className="mono-title">Erro ao carregar dados</h1>
          <Alert className="mono-error-alert" color="failure" icon={AlertCircle}>
            <span>{error}</span>
          </Alert>
          <Button className="mono-btn mono-btn--primary" color="monoPrimary" onClick={onRefresh} size="mono" type="button">
            <RefreshCw />
            Tentar novamente
          </Button>
        </div>
      </div>
    </div>
  </ThemeProvider>
);

interface EmptyProps {
  children: React.ReactNode;
}

export const MonoEmpty: React.FC<EmptyProps> = ({ children }) => (
  <div className="mono-empty">{children}</div>
);

interface SkeletonProps {
  height?: number | string;
  width?: number | string;
  radius?: number | string;
  style?: React.CSSProperties;
}

export const MonoSkeleton: React.FC<SkeletonProps> = ({ height = 16, radius, style, width = '100%' }) => (
  <div
    aria-hidden="true"
    className="mono-skeleton"
    style={{ height, width, borderRadius: radius, ...style }}
  />
);

/** Estado vazio de chart: 0 datapoints -> placeholder; 1 datapoint -> aviso de ponto isolado. */
export const MonoChartEmpty: React.FC<{ singlePoint?: boolean }> = ({ singlePoint }) => (
  <div className="mono-empty">
    {singlePoint
      ? 'Apenas 1 ponto de dado no período — ajuste o intervalo para ver a linha.'
      : 'Sem dados no período selecionado.'}
  </div>
);
