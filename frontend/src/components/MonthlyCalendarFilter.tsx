// src/components/MonthlyCalendarFilter.tsx
import React, { useState, useRef, useEffect } from 'react';
import { ChevronDown, Calendar, Check } from 'lucide-react';
import MonthYearSelector from './MonthYearSelector.tsx';

export type MonthlyFilterType = 'thisMonth' | 'lastMonth' | 'last3Months' | 'last6Months' | 'year' | 'custom';

interface MonthlyCalendarFilterProps {
  onFilterSelect: (filterType: MonthlyFilterType, startDate?: string, endDate?: string) => void;
  currentFilter: MonthlyFilterType;
  startDate?: string; // formato YYYY-MM-DD
  endDate?: string;   // formato YYYY-MM-DD
  className?: string;
  isLoading?: boolean;
}

const MonthlyCalendarFilter: React.FC<MonthlyCalendarFilterProps> = ({
  onFilterSelect,
  currentFilter,
  startDate,
  endDate,
  className = '',
  isLoading = false
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [isCustomOpen, setIsCustomOpen] = useState(false);
  const [customStartMonth, setCustomStartMonth] = useState(startDate?.substring(0, 7) || ''); // YYYY-MM
  const [customEndMonth, setCustomEndMonth] = useState(endDate?.substring(0, 7) || ''); // YYYY-MM
  const [selectedOption, setSelectedOption] = useState<MonthlyFilterType>(currentFilter);

  const dropdownRef = useRef<HTMLDivElement>(null);

  // Atualiza a opção selecionada quando o filtro atual muda externamente
  useEffect(() => {
    setSelectedOption(currentFilter);
  }, [currentFilter]);

  // Efeito para fechar o dropdown ao clicar fora
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setIsCustomOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // Obtém o texto para o filtro selecionado
  const getFilterText = (): string => {
    switch (currentFilter) {
      case 'thisMonth':
        return 'Mês atual';
      case 'lastMonth':
        return 'Mês anterior';
      case 'last3Months':
        return 'Últimos 3 meses';
      case 'last6Months':
        return 'Últimos 6 meses';
      case 'year':
        return 'Este ano';
      case 'custom':
        const startText = formatMonthYearForDisplay(customStartMonth);
        const endText = formatMonthYearForDisplay(customEndMonth);
        return `${startText} - ${endText}`;
      default:
        return 'Selecionar período';
    }
  };

  // Formata data YYYY-MM para exibição como MM/YYYY ou Nome do mês
  const formatMonthYearForDisplay = (monthStr: string): string => {
    if (!monthStr) return '';

    const [year, month] = monthStr.split('-');
    const monthIndex = parseInt(month) - 1;
    const months = [
      'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
      'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'
    ];

    return `${months[monthIndex]}/${year}`;
  };

  // Manipulador para selecionar um filtro
  const handleOptionSelect = (filter: MonthlyFilterType) => {
    if (filter === 'custom') {
      setIsCustomOpen(true);
      return;
    }

    setSelectedOption(filter);
  };

  // Manipulador para aplicar o filtro selecionado
  const handleApplyFilter = () => {
    if (selectedOption === 'custom') {
      // Já está sendo tratado pelo applyCustomFilter
      return;
    }

    // Chama a função do componente pai para atualizar os dados
    onFilterSelect(selectedOption);
    setIsOpen(false);
  };

  // Atualiza mês início
  const handleStartMonthChange = (value: string) => {
    setCustomStartMonth(value);
  };

  // Atualiza mês fim
  const handleEndMonthChange = (value: string) => {
    setCustomEndMonth(value);
  };

  // Aplicar filtro customizado
  const applyCustomFilter = () => {
    if (customStartMonth && customEndMonth) {
      // Converter YYYY-MM para YYYY-MM-DD (primeiro e último dia do mês)
      const startDate = `${customStartMonth}-01`;

      // Para o último dia do mês, calcular o primeiro dia do próximo mês e subtrair 1
      const [endYear, endMonth] = customEndMonth.split('-').map(Number);
      const lastDay = new Date(endYear, endMonth, 0).getDate(); // 0 para último dia do mês anterior
      const endDate = `${customEndMonth}-${lastDay}`;

      // Chama a função do componente pai para atualizar os dados
      onFilterSelect('custom', startDate, endDate);
      setIsCustomOpen(false);
      setIsOpen(false);
    }
  };

  return (
    <div ref={dropdownRef} className={`relative ${className}`}>
      {/* Botão de filtro */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between w-full px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
        aria-haspopup="true"
        aria-expanded={isOpen}
        disabled={isLoading}
      >
        <div className="flex items-center">
          <Calendar className={`w-4 h-4 mr-2 ${isLoading ? 'text-gray-400' : 'text-gray-500'}`} />
          <span>{getFilterText()}</span>
        </div>
        {isLoading ? (
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-500"></div>
        ) : (
          <ChevronDown className="w-4 h-4 ml-2 text-gray-500" />
        )}
      </button>

      {/* Dropdown principal */}
      {isOpen && !isCustomOpen && (
        <div className="absolute z-40 w-64 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg">
          <div className="py-1 border-b border-gray-200">
            <div className="px-3 py-2 text-xs font-semibold text-gray-500 uppercase">
              Selecionar período
            </div>
          </div>
          <div className="py-1">
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                selectedOption === 'thisMonth' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleOptionSelect('thisMonth')}
            >
              {selectedOption === 'thisMonth' && <Check className="w-4 h-4 mr-2 text-blue-600" />}
              <span className={selectedOption === 'thisMonth' ? 'ml-6' : ''}>Mês atual</span>
            </button>
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                selectedOption === 'lastMonth' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleOptionSelect('lastMonth')}
            >
              {selectedOption === 'lastMonth' && <Check className="w-4 h-4 mr-2 text-blue-600" />}
              <span className={selectedOption === 'lastMonth' ? 'ml-6' : ''}>Mês anterior</span>
            </button>
          </div>
          <div className="py-1 border-t border-gray-200">
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                selectedOption === 'last3Months' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleOptionSelect('last3Months')}
            >
              {selectedOption === 'last3Months' && <Check className="w-4 h-4 mr-2 text-blue-600" />}
              <span className={selectedOption === 'last3Months' ? 'ml-6' : ''}>Últimos 3 meses</span>
            </button>
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                selectedOption === 'last6Months' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleOptionSelect('last6Months')}
            >
              {selectedOption === 'last6Months' && <Check className="w-4 h-4 mr-2 text-blue-600" />}
              <span className={selectedOption === 'last6Months' ? 'ml-6' : ''}>Últimos 6 meses</span>
            </button>
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                selectedOption === 'year' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleOptionSelect('year')}
            >
              {selectedOption === 'year' && <Check className="w-4 h-4 mr-2 text-blue-600" />}
              <span className={selectedOption === 'year' ? 'ml-6' : ''}>Este ano</span>
            </button>
          </div>
          <div className="py-1 border-t border-gray-200">
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                selectedOption === 'custom' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleOptionSelect('custom')}
            >
              {selectedOption === 'custom' && <Check className="w-4 h-4 mr-2 text-blue-600" />}
              <span className={selectedOption === 'custom' ? 'ml-6' : ''}>Período personalizado</span>
            </button>
          </div>

          {/* Botão de aplicar */}
          <div className="p-3 border-t border-gray-200">
            <button
              className="w-full flex items-center justify-center px-3 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 transition duration-150 ease-in-out"
              onClick={handleApplyFilter}
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                  Carregando...
                </>
              ) : 'Aplicar Filtro'}
            </button>
          </div>
        </div>
      )}

      {/* Filtro customizado - USANDO MonthYearSelector */}
      {isOpen && isCustomOpen && (
        <div className="absolute z-40 w-80 mt-1 p-4 bg-white border border-gray-200 rounded-lg shadow-lg">
          <h3 className="text-sm font-medium text-gray-700 mb-3">Selecione o período personalizado</h3>

          <div className="mb-3">
            <label className="block text-xs font-medium text-gray-500 mb-1">
              Mês Inicial
            </label>
            <MonthYearSelector
              value={customStartMonth}
              onChange={handleStartMonthChange}
              className="w-full"
            />
          </div>

          <div className="mb-4">
            <label className="block text-xs font-medium text-gray-500 mb-1">
              Mês Final
            </label>
            <MonthYearSelector
              value={customEndMonth}
              onChange={handleEndMonthChange}
              className="w-full"
            />
          </div>

          <div className="flex justify-end space-x-2 mt-4">
            <button
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50 text-gray-700"
              onClick={() => setIsCustomOpen(false)}
            >
              Cancelar
            </button>
            <button
              className="px-3 py-1.5 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 flex items-center"
              onClick={applyCustomFilter}
              disabled={!customStartMonth || !customEndMonth || isLoading}
            >
              {isLoading ? (
                <>
                  <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white mr-2"></div>
                  Carregando...
                </>
              ) : 'Aplicar'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default MonthlyCalendarFilter;