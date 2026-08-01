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
   * Formata uma data para exibição no formato local (dia/mês/ano)
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
  export const formatMonth = (date: Date): string => {
    return new Intl.DateTimeFormat('pt-BR', {
      month: 'long',
      year: 'numeric'
    }).format(date);
  };

  /**
   * Retorna o nome do mês a partir do número (0-11)
   */
  export const getMonthName = (monthNumber: number): string => {
    const date = new Date();
    date.setMonth(monthNumber);
    return new Intl.DateTimeFormat('pt-BR', { month: 'long' }).format(date);
  };

  /**
   * Verifica se duas datas são do mesmo dia
   */
  export const isSameDay = (date1: Date, date2: Date): boolean => {
    return (
      date1.getFullYear() === date2.getFullYear() &&
      date1.getMonth() === date2.getMonth() &&
      date1.getDate() === date2.getDate()
    );
  };

  /**
   * Adiciona dias a uma data
   */
  export const addDays = (date: Date, days: number): Date => {
    const result = new Date(date);
    result.setDate(result.getDate() + days);
    return result;
  };

  /**
   * Adiciona meses a uma data
   */
  export const addMonths = (date: Date, months: number): Date => {
    const result = new Date(date);
    result.setMonth(result.getMonth() + months);
    return result;
  };