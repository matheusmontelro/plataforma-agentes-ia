// src/components/dashboard/MonthYearSelector.tsx

import React, { useState, useEffect, useRef } from 'react';
import { Calendar, ChevronLeft, ChevronRight, Calendar as CalendarIcon } from 'lucide-react';

interface MonthYearSelectorProps {
  value: string; // formato YYYY-MM
  onChange: (value: string) => void;
  className?: string;
  error?: boolean;
}

const MonthYearSelector: React.FC<MonthYearSelectorProps> = ({
  value,
  onChange,
  className = '',
  error = false
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Parse o valor inicial para obter ano e mês
  useEffect(() => {
    if (value) {
      const [yearStr, monthStr] = value.split('-');
      if (yearStr && !isNaN(parseInt(yearStr))) {
        setYear(parseInt(yearStr));
      }
    }
  }, [value]);

  // Fechar o dropdown ao clicar fora
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // Formatar a data para exibição
  const formatDisplayDate = (dateStr: string): string => {
    if (!dateStr) return '';

    const months = [
      'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
      'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'
    ];

    const [yearStr, monthStr] = dateStr.split('-');
    const monthIndex = parseInt(monthStr) - 1;

    return `${months[monthIndex]} de ${yearStr}`;
  };

  // Navegar para o ano anterior
  const prevYear = () => {
    setYear(year - 1);
  };

  // Navegar para o próximo ano
  const nextYear = () => {
    setYear(year + 1);
  };

  // Selecionar um mês
  const selectMonth = (month: number) => {
    // Mês deve ser uma string de dois dígitos (01-12)
    const monthStr = String(month).padStart(2, '0');
    const newValue = `${year}-${monthStr}`;
    onChange(newValue);
    setIsOpen(false);
  };

  // Verificar se um mês está selecionado
  const isMonthSelected = (month: number): boolean => {
    if (!value) return false;

    const [yearStr, monthStr] = value.split('-');
    return parseInt(yearStr) === year && parseInt(monthStr) === month;
  };

  // Obter o mês atual
  const getCurrentMonth = (): number => {
    const today = new Date();
    return today.getMonth() + 1; // JavaScript meses são 0-indexed
  };

  // Verificar se é o mês atual
  const isCurrentMonth = (month: number): boolean => {
    const today = new Date();
    return today.getFullYear() === year && (today.getMonth() + 1) === month;
  };

  // Array com os meses
  const months = [
    { value: 1, label: 'Jan' },
    { value: 2, label: 'Fev' },
    { value: 3, label: 'Mar' },
    { value: 4, label: 'Abr' },
    { value: 5, label: 'Mai' },
    { value: 6, label: 'Jun' },
    { value: 7, label: 'Jul' },
    { value: 8, label: 'Ago' },
    { value: 9, label: 'Set' },
    { value: 10, label: 'Out' },
    { value: 11, label: 'Nov' },
    { value: 12, label: 'Dez' }
  ];

  return (
    <div ref={dropdownRef} className={`relative ${className}`}>
      {/* Campo de exibição */}
      <div
        className={`flex items-center justify-between px-3 py-2 border ${error ? 'border-rose-300' : 'border-slate-300'} rounded-md shadow-sm cursor-pointer bg-white hover:border-slate-400 transition-colors`}
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex items-center">
          <CalendarIcon className="w-5 h-5 mr-2 text-slate-500" />
          <span className="text-slate-700">{formatDisplayDate(value) || 'Selecionar mês/ano'}</span>
        </div>
        <ChevronRight className={`w-5 h-5 text-slate-500 transition-transform ${isOpen ? 'transform rotate-90' : ''}`} />
      </div>

      {/* Dropdown */}
      {isOpen && (
        <div className="fixed z-50 mt-1 w-64 bg-white border border-slate-200 rounded-lg shadow-lg" style={{
          top: dropdownRef.current ? dropdownRef.current.getBoundingClientRect().bottom + 4 : 0,
          left: dropdownRef.current ? dropdownRef.current.getBoundingClientRect().left : 0
        }}>
          {/* Header - Seletor de ano */}
          <div className="flex items-center justify-between p-3 border-b border-slate-200">
            <button
              onClick={prevYear}
              className="p-1 rounded-full hover:bg-slate-100 text-slate-600"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>
            <span className="font-medium text-slate-800">{year}</span>
            <button
              onClick={nextYear}
              className="p-1 rounded-full hover:bg-slate-100 text-slate-600"
            >
              <ChevronRight className="w-5 h-5" />
            </button>
          </div>

          {/* Grid de meses */}
          <div className="grid grid-cols-4 gap-1 p-2">
            {months.map((month) => (
              <button
                key={month.value}
                onClick={() => selectMonth(month.value)}
                className={`
                  p-2 text-sm rounded-md transition-colors
                  ${isMonthSelected(month.value)
                    ? 'bg-indigo-600 text-white'
                    : isCurrentMonth(month.value)
                      ? 'bg-indigo-50 text-indigo-700'
                      : 'hover:bg-slate-100 text-slate-700'}
                `}
              >
                {month.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default MonthYearSelector;