// src/components/CalendarFilter/CalendarFilterDropdown.tsx
import React, { useState, useRef, useEffect } from 'react';
import { ChevronDown, Calendar as CalendarIcon } from 'lucide-react';
import { PresetFilterType } from '../hooks/useCalendarFilter.ts';

interface CalendarFilterDropdownProps {
  // Função chamada quando o filtro é alterado
  onFilterSelect: (filterType: PresetFilterType) => void;
  // Tipo de filtro selecionado
  currentFilter: PresetFilterType;
  // Rótulos personalizáveis
  labels?: {
    today?: string;
    tomorrow?: string;
    yesterday?: string;
    thisWeek?: string;
    lastWeek?: string;
    thisMonth?: string;
    lastMonth?: string;
    custom?: string;
    all?: string;
    filterByDate?: string;
  };
  // Classe adicional para o container
  className?: string;
}

const CalendarFilterDropdown: React.FC<CalendarFilterDropdownProps> = ({
  onFilterSelect,
  currentFilter,
  labels = {
    today: 'Hoje',
    yesterday: 'Ontem',
    thisWeek: 'Esta semana',
    lastWeek: 'Semana passada',
    thisMonth: 'Este mês',
    lastMonth: 'Mês passado',
    custom: 'Personalizado',
    all: 'Todas as datas',
    filterByDate: 'Filtrar por data'
  },
  className = ''
}) => {
  // Estados
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Efeito para fechar o dropdown ao clicar fora
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

  // Obtém o texto do filtro selecionado
  const getFilterText = (filter: PresetFilterType): string => {
    switch (filter) {
      case 'today':
        return labels.today || 'Hoje';
      case 'yesterday':
        return labels.yesterday || 'Ontem';
      case 'thisWeek':
        return labels.thisWeek || 'Esta semana';
      case 'lastWeek':
        return labels.lastWeek || 'Semana passada';
      case 'thisMonth':
        return labels.thisMonth || 'Este mês';
      case 'lastMonth':
        return labels.lastMonth || 'Mês passado';
      case 'custom':
        return labels.custom || 'Personalizado';
      case 'all':
      default:
        return labels.all || 'Todas as datas';
    }
  };

  // Manipulador para selecionar um filtro
  const handleFilterSelect = (filter: PresetFilterType) => {
    onFilterSelect(filter);
    setIsOpen(false);
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
      >
        <div className="flex items-center">
          <CalendarIcon className="w-4 h-4 mr-2 text-gray-500" />
          <span>{getFilterText(currentFilter)}</span>
        </div>
        <ChevronDown className="w-4 h-4 ml-2 text-gray-500" />
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute z-10 w-56 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg">
          <div className="py-1 border-b border-gray-200">
            <div className="px-3 py-2 text-xs font-semibold text-gray-500 uppercase">
              {labels.filterByDate}
            </div>
          </div>
          <div className="py-1">
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                currentFilter === 'all' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleFilterSelect('all')}
            >
              {labels.all}
            </button>
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                currentFilter === 'today' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleFilterSelect('today')}
            >
              {labels.today}
            </button>
            {/* Nova opção para Amanhã */}
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                currentFilter === 'tomorrow' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleFilterSelect('tomorrow')}
            >
              {labels.tomorrow || 'Amanhã'}
            </button>
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                currentFilter === 'yesterday' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleFilterSelect('yesterday')}
            >
              {labels.yesterday}
            </button>
          </div>
          <div className="py-1 border-t border-gray-200">
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                currentFilter === 'thisWeek' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleFilterSelect('thisWeek')}
            >
              {labels.thisWeek}
            </button>
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                currentFilter === 'lastWeek' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleFilterSelect('lastWeek')}
            >
              {labels.lastWeek}
            </button>
          </div>
          <div className="py-1 border-t border-gray-200">
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                currentFilter === 'thisMonth' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleFilterSelect('thisMonth')}
            >
              {labels.thisMonth}
            </button>
            <button
              className={`flex items-center w-full px-4 py-2 text-sm text-left ${
                currentFilter === 'lastMonth' ? 'bg-gray-100 text-blue-600' : 'text-gray-700 hover:bg-gray-50'
              }`}
              onClick={() => handleFilterSelect('lastMonth')}
            >
              {labels.lastMonth}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default CalendarFilterDropdown;