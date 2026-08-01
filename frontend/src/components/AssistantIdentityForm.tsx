import React, { useRef, useEffect } from 'react';
import { HelpCircle } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';

interface AssistantIdentityFormProps {
  assistantName: string;
  setAssistantName: (val: string) => void;
  assistantRole: string;
  setAssistantRole: (val: string) => void;
  assistantResponsibility: string;
  setAssistantResponsibility: (val: string) => void;
  assistantFormality: string;
  setAssistantFormality: (val: string) => void;
  assistantTone: string;
  setAssistantTone: (val: string) => void;
  assistantLanguage: string;
  setAssistantLanguage: (val: string) => void;
}

// Helper components
const Field: React.FC<{ label: string; children: React.ReactNode; hint?: string }> = ({ label, children, hint }) => {
  const { isDark } = useTheme();
  return (
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
};

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>((props, ref) => {
  const { isDark } = useTheme();
  return (
    <input
      ref={ref}
      {...props}
      className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
        isDark
          ? 'border-gray-600 bg-gray-700 text-gray-200 placeholder:text-gray-400 focus:border-brand'
          : 'border-gray-300 bg-white text-gray-800 placeholder:text-gray-400 focus:border-brand'
      } ${props.className ?? ""}`}
    />
  );
});

const AssistantIdentityForm: React.FC<AssistantIdentityFormProps> = ({
  assistantName, setAssistantName,
  assistantRole, setAssistantRole,
  assistantResponsibility, setAssistantResponsibility,
  assistantFormality, setAssistantFormality,
  assistantTone, setAssistantTone,
  assistantLanguage, setAssistantLanguage
}) => {
  const { isDark } = useTheme();

  // Refs para inputs não controlados (mantém performance original)
  const nameRef = useRef<HTMLInputElement>(null);
  const roleRef = useRef<HTMLInputElement>(null);
  const responsibilityRef = useRef<HTMLInputElement>(null);

  // Inicializar os valores dos inputs
  useEffect(() => {
    if (nameRef.current) nameRef.current.value = assistantName;
    if (roleRef.current) roleRef.current.value = assistantRole;
    if (responsibilityRef.current) responsibilityRef.current.value = assistantResponsibility;
  }, [assistantName, assistantRole, assistantResponsibility]);

  // Atualizar estado apenas quando o input perde o foco
  const handleNameBlur = () => {
    if (nameRef.current) setAssistantName(nameRef.current.value);
  };

  const handleRoleBlur = () => {
    if (roleRef.current) setAssistantRole(roleRef.current.value);
  };

  const handleResponsibilityBlur = () => {
    if (responsibilityRef.current) setAssistantResponsibility(responsibilityRef.current.value);
  };

  return (
    <div className="space-y-4">
      {/* Nome do Agente - usando refs (funcionalidade original) */}
      <Field label="Nome do Agente" hint="Ex: Ana">
        <Input
          ref={nameRef}
          type="text"
          defaultValue={assistantName}
          onBlur={handleNameBlur}
          placeholder="Ex: Ana"
        />
      </Field>

      {/* Função/Cargo - usando refs (funcionalidade original) */}
      <Field label="Função/Cargo">
        <Input
          ref={roleRef}
          type="text"
          defaultValue={assistantRole}
          onBlur={handleRoleBlur}
          placeholder="Ex: Consultora de agendamento"
        />
      </Field>

      {/* Responsabilidade principal - usando refs (funcionalidade original) */}
      <Field label="Responsabilidade principal">
        <Input
          ref={responsibilityRef}
          type="text"
          defaultValue={assistantResponsibility}
          onBlur={handleResponsibilityBlur}
          placeholder="Ex: Auxiliar no agendamento de consultas"
        />
      </Field>

      {/* Selects permanecem controlados (funcionalidade original) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="Nível de formalidade">
          <select
            className={`w-full rounded-xl border px-3 py-2 text-sm focus:ring-2 focus:ring-brand ${
              isDark
                ? 'border-gray-600 bg-gray-700 text-gray-200 focus:border-brand'
                : 'border-gray-300 bg-white text-gray-800 focus:border-brand'
            }`}
            value={assistantFormality}
            onChange={e => setAssistantFormality(e.target.value)}
          >
            <option value="formal">Formal</option>
            <option value="informal">Informal</option>
            <option value="intermediário">Intermediário</option>
          </select>
        </Field>

        <Field label="Tom de voz">
          <select
            className={`w-full rounded-xl border px-3 py-2 text-sm focus:ring-2 focus:ring-brand ${
              isDark
                ? 'border-gray-600 bg-gray-700 text-gray-200 focus:border-brand'
                : 'border-gray-300 bg-white text-gray-800 focus:border-brand'
            }`}
            value={assistantTone}
            onChange={e => setAssistantTone(e.target.value)}
          >
            <option value="amigável">Amigável</option>
            <option value="profissional">Profissional</option>
            <option value="casual">Casual</option>
            <option value="empático">Empático</option>
            <option value="entusiástico">Entusiástico</option>
          </select>
        </Field>
      </div>

      <Field label="Idioma principal">
        <select
          className={`w-full rounded-xl border px-3 py-2 text-sm focus:ring-2 focus:ring-brand ${
            isDark
              ? 'border-gray-600 bg-gray-700 text-gray-200 focus:border-brand'
              : 'border-gray-300 bg-white text-gray-800 focus:border-brand'
          }`}
          value={assistantLanguage}
          onChange={e => setAssistantLanguage(e.target.value)}
        >
          <option value="pt-BR">Português (Brasil)</option>
          <option value="pt-PT">Português (Portugal)</option>
          <option value="en">Inglês</option>
          <option value="es">Espanhol</option>
        </select>
      </Field>

      {/* Dica com cores da empresa */}
      <div className={`rounded-2xl border p-4 ${
        isDark
          ? 'border-brand/30 bg-brand/10'
          : 'border-brand/20 bg-brand/5'
      }`}>
        <div className="flex gap-3">
          <HelpCircle className="w-5 h-5 text-brand flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="font-medium text-brand mb-1">Dica de personalidade</h4>
            <p className={`text-sm ${
              isDark ? 'text-brand/90' : 'text-brand/80'
            }`}>
              Defina uma personalidade que represente bem sua empresa. Uma personalidade amigável e empática geralmente funciona bem para o setor de serviços.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AssistantIdentityForm;