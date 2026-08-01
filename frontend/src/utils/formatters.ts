// src/utils/formatters.ts
/**
 * Formatadores para números, porcentagens, moeda e datas
 */

/**
 * Formata um número para exibição
 */
export const formatNumber = (value: number): string => {
    return new Intl.NumberFormat('pt-BR').format(value);
  };

  /**
   * Formata um valor monetário para exibição em Reais
   */
  export const formatCurrency = (value: number): string => {
    return new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: 'BRL',
      minimumFractionDigits: 2
    }).format(value);
  };

  /**
   * Formata uma porcentagem para exibição
   */
  export const formatPercentage = (value: number, digits: number = 1): string => {
    return `${value.toFixed(digits)}%`;
  };

  /**
   * Calcula a variação percentual entre dois valores
   */
  export const calculatePercentageChange = (current: number, previous: number): number => {
    if (previous === 0) return 0;
    return ((current / previous) - 1) * 100;
  };

  /**
   * Determina se uma variação é positiva ou negativa para fins de estilo
   */
  export const getDeltaType = (value: number): 'increase' | 'decrease' | 'unchanged' => {
    if (value > 0) return 'increase';
    if (value < 0) return 'decrease';
    return 'unchanged';
  };

  /**
   * Formata uma data para exibição (dia/mês/ano)
   */
  export const formatDate = (date: Date): string => {
    return new Intl.DateTimeFormat('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric'
    }).format(date);
  };

  /**
   * Formata um mês para exibição (nome do mês e ano)
   */
  export const formatMonth = (monthStr: string): string => {
    // monthStr no formato "YYYY-MM"
    const [year, month] = monthStr.split('-').map(part => parseInt(part));

    const date = new Date(year, month - 1, 1);
    return new Intl.DateTimeFormat('pt-BR', {
      month: 'long',
      year: 'numeric'
    }).format(date);
  };

  /**
   * Formata uma faixa de horas para exibição
   */
  export const formatTimeRange = (range: string): string => {
    // range no formato "8-10"
    const [start, end] = range.split('-');
    return `${start}h-${end}h`;
  };

  /**
   * Converte um número de dia da semana para o nome do dia
   */
  export const weekdayNumberToName = (day: number): string => {
    const weekdays = ['Domingo', 'Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado'];
    return weekdays[day] || '';
  };

  /**
   * Retorna uma cor com base no valor percentual (útil para heatmaps)
   */
  export const getColorBasedOnValue = (value: number, maxValue: number = 100): string => {
    const intensity = Math.min(Math.max((value / maxValue), 0), 1);

    // Retorna uma classe de cor do Tailwind para uso no Tremor
    if (intensity < 0.2) return 'blue-100';
    if (intensity < 0.4) return 'blue-300';
    if (intensity < 0.6) return 'blue-500';
    if (intensity < 0.8) return 'blue-700';
    return 'blue-900';
  };

  // src/utils/dateUtils.ts
  /**
   * Funções utilitárias para manipulação de datas
   */

  /**
   * Retorna o primeiro dia do mês atual
   */
  export const getFirstDayOfCurrentMonth = (): Date => {
    const today = new Date();
    return new Date(today.getFullYear(), today.getMonth(), 1);
  };

  /**
   * Retorna o primeiro dia do mês anterior
   */
  export const getFirstDayOfPreviousMonth = (): Date => {
    const today = new Date();
    return new Date(today.getFullYear(), today.getMonth() - 1, 1);
  };

  /**
   * Retorna o último dia do mês anterior
   */
  export const getLastDayOfPreviousMonth = (): Date => {
    const today = new Date();
    return new Date(today.getFullYear(), today.getMonth(), 0);
  };

  /**
   * Converte uma data para string no formato 'YYYY-MM-DD'
   */
  export const dateToISOString = (date: Date): string => {
    return date.toISOString().split('T')[0];
  };

  /**
   * Retorna a data de N dias atrás
   */
  export const getDateDaysAgo = (days: number): Date => {
    const date = new Date();
    date.setDate(date.getDate() - days);
    return date;
  };

  /**
   * Retorna um objeto com as datas para "últimos 7 dias"
   */
  export const getLast7DaysRange = () => {
    return {
      from: getDateDaysAgo(7),
      to: new Date()
    };
  };

  /**
   * Retorna um objeto com as datas para "últimos 30 dias"
   */
  export const getLast30DaysRange = () => {
    return {
      from: getDateDaysAgo(30),
      to: new Date()
    };
  };

  /**
   * Retorna um objeto com as datas para o mês atual
   */
  export const getCurrentMonthRange = () => {
    return {
      from: getFirstDayOfCurrentMonth(),
      to: new Date()
    };
  };

  /**
   * Retorna um objeto com as datas para o mês anterior
   */
  export const getPreviousMonthRange = () => {
    return {
      from: getFirstDayOfPreviousMonth(),
      to: getLastDayOfPreviousMonth()
    };
  };

  /**
   * Formata um intervalo de datas para exibição
   * Ex: "1-10 de Janeiro" ou "1 Jan - 10 Jan"
   */
  export const formatDateRange = (startDate: Date, endDate: Date): string => {
    // Se as datas estão no mesmo mês e ano
    if (startDate.getMonth() === endDate.getMonth() &&
        startDate.getFullYear() === endDate.getFullYear()) {

      const month = startDate.toLocaleDateString('pt-BR', { month: 'long' });
      return `${startDate.getDate()}-${endDate.getDate()} de ${month}`;
    }

    // Se as datas estão em meses diferentes
    const startMonth = startDate.toLocaleDateString('pt-BR', { month: 'short' });
    const endMonth = endDate.toLocaleDateString('pt-BR', { month: 'short' });

    return `${startDate.getDate()} ${startMonth} - ${endDate.getDate()} ${endMonth}`;
  };

  /**
   * Formata uma data para exibição em formato curto
   */
  export const formatShortDate = (date: Date): string => {
    return date.toLocaleDateString('pt-BR', { day: 'numeric', month: 'short' });
  };