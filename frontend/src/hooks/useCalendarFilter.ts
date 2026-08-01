// src/hooks/useCalendarFilter.ts
import { useState, useCallback } from 'react';
import { startOfDay, endOfDay, subDays, startOfWeek, endOfWeek, startOfMonth, endOfMonth } from 'date-fns';
import { DateRange } from '../components/CalendarFilter.tsx';

// Tipos predefinidos de intervalos
export type PresetFilterType =
  | 'today'
  | 'tomorrow'
  | 'yesterday'
  | 'thisWeek'
  | 'lastWeek'
  | 'thisMonth'
  | 'lastMonth'
  | 'custom'
  | 'all';

// Interface para o hook
interface UseCalendarFilterProps {
  onFilterChange?: (dateRange: DateRange) => void;
  initialDateRange?: DateRange;
}

// Hook personalizado para gerenciar filtros de calendário
const useCalendarFilter = ({ onFilterChange, initialDateRange }: UseCalendarFilterProps = {}) => {
  // Estado para o intervalo de datas atual
  const [dateRange, setDateRange] = useState<DateRange>(
    initialDateRange || { startDate: null, endDate: null }
  );

  // Estado para o tipo de filtro predefinido
  const [filterType, setFilterType] = useState<PresetFilterType>('all');

  // Função para aplicar um filtro predefinido
  const applyPresetFilter = useCallback((type: PresetFilterType) => {
    const today = new Date();
    let newRange: DateRange = { startDate: null, endDate: null };

    switch(type) {
      case 'today':
        newRange = {
          startDate: startOfDay(today),
          endDate: endOfDay(today)
        };
        break;
      case 'yesterday':
        const yesterday = subDays(today, 1);
        newRange = {
          startDate: startOfDay(yesterday),
          endDate: endOfDay(yesterday)
        };
        break;
      case 'thisWeek':
        newRange = {
          startDate: startOfWeek(today, { weekStartsOn: 0 }), // Domingo
          endDate: endOfWeek(today, { weekStartsOn: 0 }) // Sábado
        };
        break;
      case 'lastWeek':
        const lastWeekDay = subDays(today, 7);
        newRange = {
          startDate: startOfWeek(lastWeekDay, { weekStartsOn: 0 }),
          endDate: endOfWeek(lastWeekDay, { weekStartsOn: 0 })
        };
        break;
      case 'thisMonth':
        newRange = {
          startDate: startOfMonth(today),
          endDate: endOfMonth(today)
        };
        break;
      case 'lastMonth':
        const lastMonth = subDays(startOfMonth(today), 1);
        newRange = {
          startDate: startOfMonth(lastMonth),
          endDate: endOfMonth(lastMonth)
        };
        break;
      case 'all':
      default:
        // Sem filtro de data
        newRange = { startDate: null, endDate: null };
        break;
    }

    setDateRange(newRange);
    setFilterType(type);

    if (onFilterChange) {
      onFilterChange(newRange);
    }

    return newRange;
  }, [onFilterChange]);

  // Função para aplicar um filtro personalizado
  const applyCustomFilter = useCallback((customRange: DateRange) => {
    setDateRange(customRange);
    setFilterType('custom');

    if (onFilterChange) {
      onFilterChange(customRange);
    }

    return customRange;
  }, [onFilterChange]);

  // Função para limpar o filtro
  const clearFilter = useCallback(() => {
    const emptyRange = { startDate: null, endDate: null };
    setDateRange(emptyRange);
    setFilterType('all');

    if (onFilterChange) {
      onFilterChange(emptyRange);
    }

    return emptyRange;
  }, [onFilterChange]);

  // Retornando as funções e estados necessários
  return {
    dateRange,
    filterType,
    applyPresetFilter,
    applyCustomFilter,
    clearFilter
  };
};

export default useCalendarFilter;