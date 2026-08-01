import React, { useRef, useEffect } from 'react';
import { Calendar, Clock, Check, X, HelpCircle } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';

interface DayConfig {
  open: boolean;
  morningEnabled: boolean;
  morningStart: string;
  morningEnd: string;
  afternoonEnabled: boolean;
  afternoonStart: string;
  afternoonEnd: string;
}

const defaultDay: DayConfig = {
  open: false,
  morningEnabled: false,
  morningStart: '',
  morningEnd: '',
  afternoonEnabled: false,
  afternoonStart: '',
  afternoonEnd: ''
};

// Função para converter dados antigos para o novo formato
const convertOldConfig = (oldConfig: any): DayConfig => {
  // Se já estiver no novo formato, retorna como está
  if ('morningEnabled' in oldConfig && 'afternoonEnabled' in oldConfig) {
    return oldConfig as DayConfig;
  }

  // Caso contrário, converte do formato antigo
  return {
    open: false, // Começamos com false e vamos habilitar baseado nos períodos
    morningEnabled: false,
    morningStart: '',
    morningEnd: '',
    afternoonEnabled: false,
    afternoonStart: '',
    afternoonEnd: ''
  };
};

interface SchedulingConfigFormProps {
  monday: DayConfig; setMonday: (val: DayConfig) => void;
  tuesday: DayConfig; setTuesday: (val: DayConfig) => void;
  wednesday: DayConfig; setWednesday: (val: DayConfig) => void;
  thursday: DayConfig; setThursday: (val: DayConfig) => void;
  friday: DayConfig; setFriday: (val: DayConfig) => void;
  saturday: DayConfig; setSaturday: (val: DayConfig) => void;
  sunday: DayConfig; setSunday: (val: DayConfig) => void;

  consultationDuration: number;
  setConsultationDuration: (val: number) => void;
  numberOfSuggestions: number;
  setNumberOfSuggestions: (val: number) => void;
}

interface DayRowProps {
  label: string;
  dayConfig: DayConfig;
  setDayConfig: (val: DayConfig) => void;
}

// Removendo a interface TimeInputRefs pois usaremos inferência de tipo

const DayRow: React.FC<DayRowProps> = ({ label, dayConfig, setDayConfig }) => {
  const { isDark } = useTheme();

  // Criar refs para os inputs de tempo
  const morningStartRef = useRef<HTMLInputElement>(null);
  const morningEndRef = useRef<HTMLInputElement>(null);
  const afternoonStartRef = useRef<HTMLInputElement>(null);
  const afternoonEndRef = useRef<HTMLInputElement>(null);

  // Usando refs diretamente para evitar problemas de tipagem

  // Sincronizar refs com props quando as props mudarem
  useEffect(() => {
    if (morningStartRef.current) {
      morningStartRef.current.value = dayConfig.morningStart;
    }
    if (morningEndRef.current) {
      morningEndRef.current.value = dayConfig.morningEnd;
    }
    if (afternoonStartRef.current) {
      afternoonStartRef.current.value = dayConfig.afternoonStart;
    }
    if (afternoonEndRef.current) {
      afternoonEndRef.current.value = dayConfig.afternoonEnd;
    }
  }, [dayConfig]);

  const handlePeriodToggle = (period: 'morning' | 'afternoon') => {
    // Salvar posição atual do scroll
    const currentScrollY = window.scrollY;

    if (period === 'morning') {
      const newState = !dayConfig.morningEnabled;
      const newConfig = {
        ...dayConfig,
        morningEnabled: newState,
        morningStart: newState ? '08:00' : '',
        morningEnd: newState ? '12:00' : '',
      };
      newConfig.open = newConfig.morningEnabled || newConfig.afternoonEnabled;
      setDayConfig(newConfig);
    } else {
      const newState = !dayConfig.afternoonEnabled;
      const newConfig = {
        ...dayConfig,
        afternoonEnabled: newState,
        afternoonStart: newState ? '14:00' : '',
        afternoonEnd: newState ? '18:00' : '',
      };
      newConfig.open = newConfig.morningEnabled || newConfig.afternoonEnabled;
      setDayConfig(newConfig);
    }

    // Manter posição de scroll após a atualização
    requestAnimationFrame(() => {
      window.scrollTo(0, currentScrollY);
    });
  };

  const handleTimeBlur = (period: 'morning' | 'afternoon', timeType: 'start' | 'end') => {
    const newConfig = { ...dayConfig };

    if (period === 'morning') {
      if (timeType === 'start' && morningStartRef.current) {
        newConfig.morningStart = morningStartRef.current.value;
      } else if (timeType === 'end' && morningEndRef.current) {
        newConfig.morningEnd = morningEndRef.current.value;
      }
    } else {
      if (timeType === 'start' && afternoonStartRef.current) {
        newConfig.afternoonStart = afternoonStartRef.current.value;
      } else if (timeType === 'end' && afternoonEndRef.current) {
        newConfig.afternoonEnd = afternoonEndRef.current.value;
      }
    }

    newConfig.open = newConfig.morningEnabled || newConfig.afternoonEnabled;
    setDayConfig(newConfig);
  };

  return (
    <div className={`p-4 rounded-xl border mb-3 ${
      isDark
        ? 'bg-gray-800/30 border-gray-600'
        : 'bg-gray-50/30 border-gray-200'
    }`}>
      <div className="flex items-center justify-between mb-4">
        <span className={`font-medium ${
          isDark ? 'text-gray-200' : 'text-gray-800'
        }`}>{label}</span>
        <div className={`w-2 h-2 rounded-full ${
          (dayConfig.morningEnabled || dayConfig.afternoonEnabled) ? 'bg-brand' : 'bg-gray-400'
        }`}></div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Manhã */}
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={dayConfig.morningEnabled}
              onChange={() => handlePeriodToggle('morning')}
              className="h-4 w-4 rounded border-gray-300 text-brand focus:ring-brand"
            />
            <span className={isDark ? 'text-gray-300' : 'text-gray-700'}>Atende de manhã</span>
          </label>

          {dayConfig.morningEnabled && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={`block text-sm mb-1 ${
                  isDark ? 'text-gray-300' : 'text-gray-700'
                }`}>Início</label>
                <input
                  ref={morningStartRef}
                  type="time"
                  className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
                    isDark
                      ? 'border-gray-600 bg-gray-700 text-gray-200 focus:border-brand'
                      : 'border-gray-300 bg-white text-gray-800 focus:border-brand'
                  }`}
                  defaultValue={dayConfig.morningStart}
                  onBlur={() => handleTimeBlur('morning', 'start')}
                />
              </div>
              <div>
                <label className={`block text-sm mb-1 ${
                  isDark ? 'text-gray-300' : 'text-gray-700'
                }`}>Fim</label>
                <input
                  ref={morningEndRef}
                  type="time"
                  className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
                    isDark
                      ? 'border-gray-600 bg-gray-700 text-gray-200 focus:border-brand'
                      : 'border-gray-300 bg-white text-gray-800 focus:border-brand'
                  }`}
                  defaultValue={dayConfig.morningEnd}
                  onBlur={() => handleTimeBlur('morning', 'end')}
                />
              </div>
            </div>
          )}
        </div>

        {/* Tarde */}
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={dayConfig.afternoonEnabled}
              onChange={() => handlePeriodToggle('afternoon')}
              className="h-4 w-4 rounded border-gray-300 text-brand focus:ring-brand"
            />
            <span className={isDark ? 'text-gray-300' : 'text-gray-700'}>Atende à tarde</span>
          </label>

          {dayConfig.afternoonEnabled && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={`block text-sm mb-1 ${
                  isDark ? 'text-gray-300' : 'text-gray-700'
                }`}>Início</label>
                <input
                  ref={afternoonStartRef}
                  type="time"
                  className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
                    isDark
                      ? 'border-gray-600 bg-gray-700 text-gray-200 focus:border-brand'
                      : 'border-gray-300 bg-white text-gray-800 focus:border-brand'
                  }`}
                  defaultValue={dayConfig.afternoonStart}
                  onBlur={() => handleTimeBlur('afternoon', 'start')}
                />
              </div>
              <div>
                <label className={`block text-sm mb-1 ${
                  isDark ? 'text-gray-300' : 'text-gray-700'
                }`}>Fim</label>
                <input
                  ref={afternoonEndRef}
                  type="time"
                  className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
                    isDark
                      ? 'border-gray-600 bg-gray-700 text-gray-200 focus:border-brand'
                      : 'border-gray-300 bg-white text-gray-800 focus:border-brand'
                  }`}
                  defaultValue={dayConfig.afternoonEnd}
                  onBlur={() => handleTimeBlur('afternoon', 'end')}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const SchedulingConfigForm: React.FC<SchedulingConfigFormProps> = ({
  monday, setMonday,
  tuesday, setTuesday,
  wednesday, setWednesday,
  thursday, setThursday,
  friday, setFriday,
  saturday, setSaturday,
  sunday, setSunday,
  consultationDuration, setConsultationDuration,
  numberOfSuggestions, setNumberOfSuggestions
}) => {
  const { isDark } = useTheme();

  // Refs para campos de configuração
  const consultationDurationRef = useRef<HTMLInputElement>(null);
  const numberOfSuggestionsRef = useRef<HTMLInputElement>(null);

  // Sincronizar refs com props quando as props mudarem
  useEffect(() => {
    if (consultationDurationRef.current) {
      consultationDurationRef.current.value = consultationDuration.toString();
    }
    if (numberOfSuggestionsRef.current) {
      numberOfSuggestionsRef.current.value = numberOfSuggestions.toString();
    }
  }, [consultationDuration, numberOfSuggestions]);

  // Converter as configurações existentes para o novo formato ao montar o componente
  useEffect(() => {
    setMonday(convertOldConfig(monday));
    setTuesday(convertOldConfig(tuesday));
    setWednesday(convertOldConfig(wednesday));
    setThursday(convertOldConfig(thursday));
    setFriday(convertOldConfig(friday));
    setSaturday(convertOldConfig(saturday));
    setSunday(convertOldConfig(sunday));
  }, []); // Executar apenas na montagem do componente

  // Manipuladores para atualizar estados quando o input perde o foco
  const handleConsultationDurationBlur = () => {
    if (consultationDurationRef.current) {
      const value = Number(consultationDurationRef.current.value);
      if (!isNaN(value) && value > 0) {
        setConsultationDuration(value);
      }
    }
  };

  const handleNumberOfSuggestionsBlur = () => {
    if (numberOfSuggestionsRef.current) {
      const value = Number(numberOfSuggestionsRef.current.value);
      if (!isNaN(value) && value > 0 && value <= 5) {
        setNumberOfSuggestions(value);
      }
    }
  };

  // Helper components (seguindo padrão)
  const Field: React.FC<{ label: string; children: React.ReactNode; hint?: string }> = ({ label, children, hint }) => (
    <label className="block text-sm">
      <span className={`mb-1 block ${
        isDark ? 'text-gray-300' : 'text-gray-700'
      }`}>{label}</span>
      {children}
      {hint && <span className={`mt-1 block text-[11px] ${
        isDark ? 'text-gray-400' : 'text-gray-500'
      }`}>{hint}</span>}
    </label>
  );

  const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>((props, ref) => (
    <input
      ref={ref}
      {...props}
      className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
        isDark
          ? 'border-gray-600 bg-gray-700 text-gray-200 placeholder:text-gray-400 focus:border-brand'
          : 'border-gray-300 bg-white text-gray-800 placeholder:text-gray-400 focus:border-brand'
      } ${props.className ?? ""}`}
    />
  ));

  return (
    <div className="space-y-4">
      {/* Dias da semana */}
      <div className="space-y-3">
        <DayRow label="Segunda" dayConfig={monday} setDayConfig={setMonday}/>
        <DayRow label="Terça" dayConfig={tuesday} setDayConfig={setTuesday}/>
        <DayRow label="Quarta" dayConfig={wednesday} setDayConfig={setWednesday}/>
        <DayRow label="Quinta" dayConfig={thursday} setDayConfig={setThursday}/>
        <DayRow label="Sexta" dayConfig={friday} setDayConfig={setFriday}/>
        <DayRow label="Sábado" dayConfig={saturday} setDayConfig={setSaturday}/>
        <DayRow label="Domingo" dayConfig={sunday} setDayConfig={setSunday}/>
      </div>

      {/* Separação visual clara */}
      <div className={`border-t pt-4 ${
        isDark ? 'border-gray-600' : 'border-gray-200'
      }`}>
        <h3 className={`text-sm font-medium mb-4 ${
          isDark ? 'text-gray-300' : 'text-gray-700'
        }`}>Configurações Gerais</h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Duração das consultas" hint="Tempo médio em minutos">
            <Input
              ref={consultationDurationRef}
              type="number"
              defaultValue={consultationDuration}
              onBlur={handleConsultationDurationBlur}
              min="1"
              placeholder="30"
            />
          </Field>

          <Field label="Sugestões de horário" hint="Quantas opções oferecer (1-5)">
            <Input
              ref={numberOfSuggestionsRef}
              type="number"
              defaultValue={numberOfSuggestions}
              onBlur={handleNumberOfSuggestionsBlur}
              min="1"
              max="5"
              placeholder="3"
            />
          </Field>
        </div>
      </div>
    </div>
  );
};

export default SchedulingConfigForm;