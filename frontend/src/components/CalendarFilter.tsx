// src/components/CalendarFilter.tsx
import React, { useState, useRef, useEffect } from 'react';
import { format, isValid, parse, isBefore, isAfter, startOfDay, endOfDay, addDays } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import { Calendar, ChevronUp, ChevronDown, Calendar as CalendarIcon, X } from 'lucide-react';

// Tipos
export interface DateRange {
  startDate: Date | null;
  endDate: Date | null;
}

// Interface para os dias no calendário
interface CalendarDay {
  date: Date;
  isCurrentMonth: boolean;
  isSelected: boolean;
  isToday: boolean;
}

export interface CalendarFilterProps {
  // Função chamada quando o filtro é alterado
  onFilterChange: (dateRange: DateRange) => void;
  // Valores iniciais (opcional)
  initialDateRange?: DateRange;
  // Formato de exibição da data
  dateFormat?: string;
  // Rótulos personalizáveis
  labels?: {
    startDate?: string;
    endDate?: string;
    apply?: string;
    clear?: string;
    placeholder?: string;
    monthLabel?: string;
    today?: string;
  };
  // Classe adicional para o container
  className?: string;
  // Se verdadeiro, permite selecionar apenas uma data em vez de um intervalo
  singleDate?: boolean;
}

// Dias da semana
const WEEKDAYS = ['D', 'S', 'T', 'Q', 'Q', 'S', 'S'];

// Componente principal de Filtro de Calendário
const CalendarFilter: React.FC<CalendarFilterProps> = ({
  onFilterChange,
  initialDateRange,
  dateFormat = 'dd/MM/yyyy',
  labels = {
    startDate: 'Data inicial',
    endDate: 'Data final',
    apply: 'Aplicar',
    clear: 'Limpar',
    placeholder: 'dd/mm/aaaa',
    monthLabel: 'de',
    today: 'Hoje'
  },
  className = '',
  singleDate = false
}) => {
  // Estados
  const [isOpen, setIsOpen] = useState(false);
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [selectedRange, setSelectedRange] = useState<DateRange>(
    initialDateRange || { startDate: null, endDate: null }
  );
  const [inputValue, setInputValue] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Refs
  const calendarRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Efeito para fechar o calendário ao clicar fora dele
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (calendarRef.current && !calendarRef.current.contains(event.target as Node) &&
          inputRef.current && !inputRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // Efeito para atualizar o input quando o range é alterado
  useEffect(() => {
    updateInputValue();
  }, [selectedRange]);

  // Atualiza o valor do input com base no range selecionado
  const updateInputValue = () => {
    if (singleDate && selectedRange.startDate) {
      setInputValue(format(selectedRange.startDate, dateFormat));
    } else if (selectedRange.startDate && selectedRange.endDate) {
      setInputValue(
        `${format(selectedRange.startDate, dateFormat)} - ${format(selectedRange.endDate, dateFormat)}`
      );
    } else if (selectedRange.startDate) {
      setInputValue(format(selectedRange.startDate, dateFormat));
    } else {
      setInputValue('');
    }
  };

  // Gera os dias do mês atual para renderização
  const generateDaysForMonth = (): CalendarDay[] => {
    const year = currentMonth.getFullYear();
    const month = currentMonth.getMonth();

    // Primeiro dia do mês
    const firstDay = new Date(year, month, 1);
    // Último dia do mês
    const lastDay = new Date(year, month + 1, 0);

    // Dia da semana do primeiro dia (0 = Domingo, 1 = Segunda, etc.)
    const firstDayOfWeek = firstDay.getDay();

    const daysArray: CalendarDay[] = [];

    // Dias do mês anterior para completar a primeira semana
    for (let i = 0; i < firstDayOfWeek; i++) {
      const prevMonthDay = new Date(year, month, -firstDayOfWeek + i + 1);
      daysArray.push({
        date: prevMonthDay,
        isCurrentMonth: false,
        isSelected: isDateInRange(prevMonthDay),
        isToday: isToday(prevMonthDay)
      });
    }

    // Dias do mês atual
    for (let i = 1; i <= lastDay.getDate(); i++) {
      const currentDay = new Date(year, month, i);
      daysArray.push({
        date: currentDay,
        isCurrentMonth: true,
        isSelected: isDateInRange(currentDay),
        isToday: isToday(currentDay)
      });
    }

    // Dias do próximo mês para completar a última semana
    const remainingDays = 42 - daysArray.length; // 6 semanas x 7 dias = 42
    for (let i = 1; i <= remainingDays; i++) {
      const nextMonthDay = new Date(year, month + 1, i);
      daysArray.push({
        date: nextMonthDay,
        isCurrentMonth: false,
        isSelected: isDateInRange(nextMonthDay),
        isToday: isToday(nextMonthDay)
      });
    }

    return daysArray;
  };

  // Verifica se a data está no intervalo selecionado
  const isDateInRange = (date: Date): boolean => {
    if (!selectedRange.startDate) return false;

    try {
      const start = selectedRange.startDate;
      // Se não houver data final, considera o final do mesmo dia da data inicial
      const end = selectedRange.endDate || endOfDay(start);

      // Normalizar as datas para o início e fim do dia
      const startOfDayTime = startOfDay(start).getTime();
      const endOfDayTime = endOfDay(end).getTime();
      const dateTime = date.getTime();

      return dateTime >= startOfDayTime && dateTime <= endOfDayTime;
    } catch {
      return false;
    }
  };

  // Verifica se a data é hoje
  const isToday = (date: Date) => {
    const today = new Date();
    return (
      date.getDate() === today.getDate() &&
      date.getMonth() === today.getMonth() &&
      date.getFullYear() === today.getFullYear()
    );
  };

  // Manipuladores de eventos para navegação no calendário
  const goToPrevMonth = () => {
    setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1));
  };

  const goToNextMonth = () => {
    setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1));
  };

  // Manipulador de clique em um dia do calendário
  const handleDateClick = (date: Date) => {
    if (singleDate) {
      // Em modo de data única, define tanto a data inicial quanto a final
      // para garantir que o intervalo esteja sempre completo
      const newRange = {
        startDate: startOfDay(date),
        endDate: endOfDay(date)  // Usando endOfDay para incluir todo o dia
      };
      setSelectedRange(newRange);
      return;
    }

    if (!selectedRange.startDate || (selectedRange.startDate && selectedRange.endDate)) {
      // Se não tiver data inicial ou já tiver um intervalo completo, começa um novo
      setSelectedRange({ startDate: startOfDay(date), endDate: null });
    } else {
      // Se já tiver data inicial, mas não final
      const start = selectedRange.startDate;

      if (isBefore(date, start)) {
        // Se a data clicada for anterior à data inicial, inverte
        setSelectedRange({ startDate: startOfDay(date), endDate: endOfDay(start) });
      } else {
        // Se for posterior, completa o intervalo
        setSelectedRange({ ...selectedRange, endDate: endOfDay(date) });
      }
    }
  };

  // Aplica o filtro
  const applyFilter = () => {
    // Se não houver data inicial selecionada, não faz nada
    if (!selectedRange.startDate) {
      return;
    }

    // Para o modo de data única, garantimos que startDate e endDate sejam definidos
    if (singleDate && selectedRange.startDate && !selectedRange.endDate) {
      // Define endDate como o final do mesmo dia que startDate
      const completeRange = {
        startDate: selectedRange.startDate,
        endDate: endOfDay(selectedRange.startDate)
      };
      setSelectedRange(completeRange);
      setError(null);
      onFilterChange(completeRange);
      setIsOpen(false);
      return;
    }

    // Para o modo de intervalo, precisamos ter startDate e endDate
    if (!singleDate && (!selectedRange.startDate || !selectedRange.endDate)) {
      setError('Selecione uma data inicial e final');
      return;
    }

    if (selectedRange.startDate && selectedRange.endDate &&
        isAfter(selectedRange.startDate, selectedRange.endDate)) {
      setError('Data inicial não pode ser maior que a data final');
      return;
    }

    setError(null);
    onFilterChange(selectedRange);
    setIsOpen(false);
  };

  // Limpa o filtro
  const clearFilter = () => {
    const emptyRange = { startDate: null, endDate: null };
    setSelectedRange(emptyRange);
    setError(null);
    onFilterChange(emptyRange);
  };

  // Define hoje como a data selecionada
  const selectToday = () => {
    const today = new Date();
    if (singleDate) {
      setSelectedRange({ startDate: startOfDay(today), endDate: null });
    } else {
      setSelectedRange({ startDate: startOfDay(today), endDate: endOfDay(today) });
    }
    setCurrentMonth(today);
  };

  // Renderização dos dias da semana
  const renderWeekdays = () => {
    return (
      <div className="grid grid-cols-7 gap-1 mb-1">
        {WEEKDAYS.map((day, index) => (
          <div
            key={index}
            className="h-8 flex items-center justify-center text-xs font-medium text-gray-500"
          >
            {day}
          </div>
        ))}
      </div>
    );
  };

  // Renderização dos dias do mês
  const renderDays = () => {
    const daysArray = generateDaysForMonth();

    return (
      <div className="grid grid-cols-7 gap-1">
        {daysArray.map((day, index) => (
          <button
            key={index}
            type="button"
            onClick={() => handleDateClick(day.date)}
            className={`h-8 w-8 flex items-center justify-center text-sm rounded-full
              ${!day.isCurrentMonth ? 'text-gray-400' : 'text-gray-700'}
              ${day.isToday ? 'border border-blue-500' : ''}
              ${day.isSelected ? 'bg-blue-500 text-white hover:bg-blue-600' : 'hover:bg-gray-100'}
              focus:outline-none focus:ring-2 focus:ring-offset-0 focus:ring-blue-500`}
            aria-label={format(day.date, 'PPP', { locale: ptBR })}
          >
            {day.date.getDate()}
          </button>
        ))}
      </div>
    );
  };

  return (
    <div className={`relative ${className}`}>
      {/* Input de data */}
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          className={`w-full px-10 py-2 border rounded-lg text-sm focus:ring-2 focus:outline-none focus:ring-blue-500
            ${error ? 'border-red-500' : 'border-gray-300'}`}
          placeholder={labels.placeholder}
          value={inputValue}
          onClick={() => setIsOpen(!isOpen)}
          readOnly
          aria-label="Selecionar data"
          aria-expanded={isOpen}
        />
        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
          <CalendarIcon className="h-5 w-5 text-gray-400" />
        </div>
        {inputValue && (
          <button
            type="button"
            className="absolute inset-y-0 right-0 pr-3 flex items-center"
            onClick={(e) => {
              e.stopPropagation();
              clearFilter();
            }}
            aria-label="Limpar seleção"
          >
            <X className="h-4 w-4 text-gray-400 hover:text-gray-600" />
          </button>
        )}
      </div>

      {/* Mensagem de erro */}
      {error && <p className="mt-1 text-xs text-red-500">{error}</p>}

      {/* Popover do calendário */}
      {isOpen && (
        <div
          ref={calendarRef}
          className="absolute z-10 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg p-4 w-72"
          role="dialog"
          aria-label="Calendário"
        >
          {/* Cabeçalho do calendário */}
          <div className="flex items-center justify-between mb-4">
            <div className="text-sm font-medium">
              {format(currentMonth, 'MMMM', { locale: ptBR })} {labels.monthLabel} {currentMonth.getFullYear()}
            </div>
            <div className="flex space-x-1">
              <button
                type="button"
                onClick={goToPrevMonth}
                className="p-1 rounded-md hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                aria-label="Mês anterior"
              >
                <ChevronUp className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={goToNextMonth}
                className="p-1 rounded-md hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                aria-label="Próximo mês"
              >
                <ChevronDown className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Corpo do calendário */}
          <div className="mb-4">
            {renderWeekdays()}
            {renderDays()}
          </div>

          {/* Rodapé do calendário */}
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={clearFilter}
              className="text-xs text-blue-600 hover:text-blue-800 focus:outline-none focus:underline"
              aria-label="Limpar seleção"
            >
              {labels.clear}
            </button>

            <div className="flex space-x-2">
              <button
                type="button"
                onClick={selectToday}
                className="text-xs px-2 py-1 bg-gray-100 rounded hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                aria-label="Selecionar hoje"
              >
                {labels.today}
              </button>
              <button
                type="button"
                onClick={applyFilter}
                className="text-xs px-2 py-1 bg-blue-500 text-white rounded hover:bg-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
                aria-label="Aplicar filtro"
              >
                {labels.apply}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CalendarFilter;