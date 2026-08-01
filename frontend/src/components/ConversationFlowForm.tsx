import React, { useRef, useEffect, useState } from 'react';
import { MessageSquare, Hash, PhoneCall, PlusCircle, Trash2, Send, HelpCircle, Settings } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';

interface FewShot {
  objectionType: string;
  userMessage: string;
  botResponse: string;
}

interface ConversationFlowFormProps {
  step0: string; setStep0: (val: string) => void;
  step1First: string; setStep1First: (val: string) => void;
  step1Second: string; setStep1Second: (val: string) => void;
  step2: string; setStep2: (val: string) => void;
  step3: string; setStep3: (val: string) => void;
  maxTokens: number; setMaxTokens: (val: number) => void;

  financialRedirectType: string; setFinancialRedirectType: (val: string) => void;
  financialRedirectNumber: string; setFinancialRedirectNumber: (val: string) => void;
  regularRedirectType: string; setRegularRedirectType: (val: string) => void;
  regularRedirectNumber: string; setRegularRedirectNumber: (val: string) => void;
  maintenanceRedirectType: string; setMaintenanceRedirectType: (val: string) => void;
  maintenanceRedirectNumber: string; setMaintenanceRedirectNumber: (val: string) => void;
  activeCustomersRedirectType: string; setActiveCustomersRedirectType: (val: string) => void;
  activeCustomersRedirectNumber: string; setActiveCustomersRedirectNumber: (val: string) => void;

  fewShots: FewShot[];
  setFewShots: (val: FewShot[]) => void;
}

const ExampleMessage: React.FC<{ text: string }> = ({ text }) => {
  const { isDark } = useTheme();
  return (
    <div className={`p-4 rounded-lg mt-2 mb-3 text-sm border ${
      isDark
        ? 'bg-gray-700/50 text-gray-300 border-gray-600'
        : 'bg-gray-50 text-gray-600 border-gray-200'
    }`}>
      <div className="flex items-center gap-2 font-medium mb-2 text-brand">
        <HelpCircle className="w-4 h-4" />
        <span>Exemplo de mensagem:</span>
      </div>
      {text}
    </div>
  );
};

/**
 * Converte configuração antiga (oldConfig) para o novo formato do ConversationFlowForm.
 * Removido qualquer referência a 'assessmentPrice'.
 */
const convertOldConfig = (oldConfig: any) => {
  return {
    step0: oldConfig.step0 || '',
    step1First: oldConfig.step1First || oldConfig.step1 || '',
    step1Second: oldConfig.step1Second || '',
    step2: oldConfig.step2 || '',
    step3: oldConfig.step3 || '',
    maxTokens: oldConfig.max_tokens || 300,

    financialRedirectType: oldConfig.financial_redirect?.type || 'fixo',
    financialRedirectNumber: oldConfig.financial_redirect?.number || '',
    regularRedirectType: oldConfig.regular_redirect?.type || 'fixo',
    regularRedirectNumber: oldConfig.regular_redirect?.number || '',
    maintenanceRedirectType: oldConfig.maintenance_redirect?.type || 'fixo',
    maintenanceRedirectNumber: oldConfig.maintenance_redirect?.number || '',
    activeCustomersRedirectType: oldConfig.active_customers_redirect?.type || 'fixo',
    activeCustomersRedirectNumber: oldConfig.active_customers_redirect?.number || '',

    fewShots: Array.isArray(oldConfig.few_shots) ? oldConfig.few_shots : []
  };
};

// Interface para os estados temporários dos fewshots
interface FewShotInputs {
  [key: string]: {
    objectionType: string;
    userMessage: string;
    botResponse: string;
  }
}

const ConversationFlowForm: React.FC<ConversationFlowFormProps> = ({
  step0, setStep0,
  step1First, setStep1First,
  step1Second, setStep1Second,
  step2, setStep2,
  step3, setStep3,
  maxTokens, setMaxTokens,

  financialRedirectType, setFinancialRedirectType,
  financialRedirectNumber, setFinancialRedirectNumber,
  regularRedirectType, setRegularRedirectType,
  regularRedirectNumber, setRegularRedirectNumber,
  maintenanceRedirectType, setMaintenanceRedirectType,
  maintenanceRedirectNumber, setMaintenanceRedirectNumber,
  activeCustomersRedirectType, setActiveCustomersRedirectType,
  activeCustomersRedirectNumber, setActiveCustomersRedirectNumber,

  fewShots, setFewShots
}) => {
  const { isDark } = useTheme();

  // Refs para inputs
  const step0Ref = useRef<HTMLTextAreaElement>(null);
  const step1FirstRef = useRef<HTMLTextAreaElement>(null);
  const step1SecondRef = useRef<HTMLTextAreaElement>(null);
  const step2Ref = useRef<HTMLTextAreaElement>(null);
  const step3Ref = useRef<HTMLTextAreaElement>(null);
  const maxTokensRef = useRef<HTMLInputElement>(null);

  const financialNumberRef = useRef<HTMLInputElement>(null);
  const regularNumberRef = useRef<HTMLInputElement>(null);
  const maintenanceNumberRef = useRef<HTMLInputElement>(null);
  const activeCustomersNumberRef = useRef<HTMLInputElement>(null);

  // Estado local para armazenar os valores dos campos de fewShots
  const [fewShotInputs, setFewShotInputs] = useState<FewShotInputs>({});

  // Inicializar valores dos inputs
  useEffect(() => {
    if (step0Ref.current) step0Ref.current.value = step0;
    if (step1FirstRef.current) step1FirstRef.current.value = step1First;
    if (step1SecondRef.current) step1SecondRef.current.value = step1Second;
    if (step2Ref.current) step2Ref.current.value = step2;
    if (step3Ref.current) step3Ref.current.value = step3;
    if (maxTokensRef.current) maxTokensRef.current.value = maxTokens.toString();

    if (financialNumberRef.current) financialNumberRef.current.value = financialRedirectNumber;
    if (regularNumberRef.current) regularNumberRef.current.value = regularRedirectNumber;
    if (maintenanceNumberRef.current) maintenanceNumberRef.current.value = maintenanceRedirectNumber;
    if (activeCustomersNumberRef.current) activeCustomersNumberRef.current.value = activeCustomersRedirectNumber;
  }, [step0, step1First, step1Second, step2, step3, maxTokens,
      financialRedirectNumber, regularRedirectNumber, maintenanceRedirectNumber, activeCustomersRedirectNumber]);

  // Inicializar o estado fewShotInputs com os valores dos fewShots
  useEffect(() => {
    const initialInputs: FewShotInputs = {};
    fewShots.forEach((fs, index) => {
      initialInputs[`fewshot-${index}`] = {
        objectionType: fs.objectionType,
        userMessage: fs.userMessage,
        botResponse: fs.botResponse
      };
    });
    setFewShotInputs(initialInputs);
  }, []);

  // Converter config existente para o novo formato ao montar o componente
  useEffect(() => {
    const storedConfig = {
      step0,
      step1First,
      step1Second,
      step2,
      step3,
      max_tokens: maxTokens,
      financial_redirect: { type: financialRedirectType, number: financialRedirectNumber },
      regular_redirect: { type: regularRedirectType, number: regularRedirectNumber },
      maintenance_redirect: { type: maintenanceRedirectType, number: maintenanceRedirectNumber },
      active_customers_redirect: { type: activeCustomersRedirectType, number: activeCustomersRedirectNumber },
      few_shots: fewShots
    };

    const convertedConfig = convertOldConfig(storedConfig);

    setStep0(convertedConfig.step0);
    setStep1First(convertedConfig.step1First);
    setStep1Second(convertedConfig.step1Second);
    setStep2(convertedConfig.step2);
    setStep3(convertedConfig.step3);
    setMaxTokens(convertedConfig.maxTokens);

    setFinancialRedirectType(convertedConfig.financialRedirectType);
    setFinancialRedirectNumber(convertedConfig.financialRedirectNumber);
    setRegularRedirectType(convertedConfig.regularRedirectType);
    setRegularRedirectNumber(convertedConfig.regularRedirectNumber);
    setMaintenanceRedirectType(convertedConfig.maintenanceRedirectType);
    setMaintenanceRedirectNumber(convertedConfig.maintenanceRedirectNumber);
    setActiveCustomersRedirectType(convertedConfig.activeCustomersRedirectType);
    setActiveCustomersRedirectNumber(convertedConfig.activeCustomersRedirectNumber);
    setFewShots(convertedConfig.fewShots);
  }, []);

  const handleAddFewShot = () => {
    // Salvar posição atual do scroll
    const currentScrollY = window.scrollY;

    const newIndex = fewShots.length;
    const newFewShot = { objectionType: "", userMessage: "", botResponse: "" };

    // Criar uma cópia do estado atual para evitar problemas de concorrência
    const updatedFewShots = [...fewShots, newFewShot];

    // Atualizar o estado local para incluir o novo item
    const newInputs = { ...fewShotInputs };
    newInputs[`fewshot-${newIndex}`] = {
      objectionType: "",
      userMessage: "",
      botResponse: ""
    };
    setFewShotInputs(newInputs);

    // Atualizar o estado global
    setFewShots(updatedFewShots);

    // Manter posição de scroll após a atualização
    requestAnimationFrame(() => {
      window.scrollTo(0, currentScrollY);
    });
  };

  const handleRemoveFewShot = (index: number) => {
    // Salvar posição atual do scroll
    const currentScrollY = window.scrollY;

    // Remover do estado local
    const newInputs = { ...fewShotInputs };
    delete newInputs[`fewshot-${index}`];

    // Reorganizar as chaves após a remoção
    const updatedInputs: FewShotInputs = {};
    const newFewShots = fewShots.filter((_, i) => i !== index);

    newFewShots.forEach((fs, i) => {
      updatedInputs[`fewshot-${i}`] = {
        objectionType: fs.objectionType,
        userMessage: fs.userMessage,
        botResponse: fs.botResponse
      };
    });

    setFewShotInputs(updatedInputs);
    setFewShots(newFewShots);

    // Manter posição de scroll após a atualização
    requestAnimationFrame(() => {
      window.scrollTo(0, currentScrollY);
    });
  };

  const updateFewShotField = (index: number, field: keyof FewShot, value: string) => {
    const key = `fewshot-${index}`;

    // Atualizar apenas se o valor realmente mudou, para evitar re-renderizações desnecessárias
    if (fewShots[index][field] !== value) {
      // Atualizar o estado local
      setFewShotInputs(prev => ({
        ...prev,
        [key]: {
          ...prev[key],
          [field]: value
        }
      }));

      // Atualizar o estado global
      const updatedFewShots = [...fewShots];
      updatedFewShots[index] = {
        ...updatedFewShots[index],
        [field]: value
      };

      setFewShots(updatedFewShots);
    }
  };

  // Helper components (seguindo padrão perfeito)
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

  const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>((props, ref) => (
    <textarea
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
      {/* Fluxo de conversa - seguindo padrão */}
      <Field label="Saudação inicial" hint="Primeira mensagem que o assistente envia">
        <Textarea
          ref={step0Ref}
          rows={3}
          placeholder="Ex: Olá! Sou a Ana, posso te ajudar a agendar sua avaliação?"
          defaultValue={step0}
          onBlur={() => step0Ref.current && setStep0(step0Ref.current.value)}
        />
      </Field>

      <Field label="Recepção amigável" hint="Apresentação da empresa e tratamentos">
        <Textarea
          ref={step1FirstRef}
          rows={3}
          placeholder="Ex: Prazer em conhecê-lo! Oferecemos implantes, clareamento, lentes..."
          defaultValue={step1First}
          onBlur={() => step1FirstRef.current && setStep1First(step1FirstRef.current.value)}
        />
      </Field>

      <Field label="Identificação do tratamento" hint="Pergunta sobre o interesse específico">
        <Textarea
          ref={step1SecondRef}
          rows={3}
          placeholder="Ex: Qual tratamento do seu interesse para melhorar seu sorriso?"
          defaultValue={step1Second}
          onBlur={() => step1SecondRef.current && setStep1Second(step1SecondRef.current.value)}
        />
      </Field>

      <Field label="Identificação do cliente" hint="Pergunta se é primeira vez ou cliente existente">
        <Textarea
          ref={step2Ref}
          rows={3}
          placeholder="Ex: É a sua primeira vez aqui na empresa?"
          defaultValue={step2}
          onBlur={() => step2Ref.current && setStep2(step2Ref.current.value)}
        />
      </Field>

      <Field label="Proposta de agendamento" hint="Apresentação do tratamento e convite para avaliação">
        <Textarea
          ref={step3Ref}
          rows={4}
          placeholder="Ex: Para definir o melhor plano, precisamos de uma avaliação. Posso agendar?"
          defaultValue={step3}
          onBlur={() => step3Ref.current && setStep3(step3Ref.current.value)}
        />
      </Field>

      <Field label="Máximo de tokens" hint="Limite de tokens por resposta (máximo: 300)">
        <Input
          ref={maxTokensRef}
          type="number"
          placeholder="150"
          defaultValue={maxTokens}
          onBlur={() => maxTokensRef.current && setMaxTokens(Number(maxTokensRef.current.value))}
          min="50"
          max="300"
        />
      </Field>

      {/* Redirecionamentos - seguindo padrão */}
      <div className={`border-t pt-4 ${
        isDark ? 'border-gray-600' : 'border-gray-200'
      }`}>
        <h3 className={`text-sm font-medium mb-4 ${
          isDark ? 'text-gray-300' : 'text-gray-700'
        }`}>Redirecionamentos</h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Questões financeiras">
            <div className="grid grid-cols-2 gap-2">
              <select
                className={`rounded-xl border px-3 py-2 text-sm focus:ring-2 focus:ring-brand ${
                  isDark
                    ? 'border-gray-600 bg-gray-700 text-gray-200 focus:border-brand'
                    : 'border-gray-300 bg-white text-gray-800 focus:border-brand'
                }`}
                value={financialRedirectType}
                onChange={e => setFinancialRedirectType(e.target.value)}
              >
                <option value="fixo">Fixo</option>
                <option value="celular">Celular</option>
              </select>
              <Input
                ref={financialNumberRef}
                type="text"
                placeholder="(00) 0000-0000"
                defaultValue={financialRedirectNumber}
                onBlur={() => financialNumberRef.current && setFinancialRedirectNumber(financialNumberRef.current.value)}
              />
            </div>
          </Field>

          <Field label="Agendamentos regulares">
            <div className="grid grid-cols-2 gap-2">
              <select
                className={`rounded-xl border px-3 py-2 text-sm focus:ring-2 focus:ring-brand ${
                  isDark
                    ? 'border-gray-600 bg-gray-700 text-gray-200 focus:border-brand'
                    : 'border-gray-300 bg-white text-gray-800 focus:border-brand'
                }`}
                value={regularRedirectType}
                onChange={e => setRegularRedirectType(e.target.value)}
              >
                <option value="fixo">Fixo</option>
                <option value="celular">Celular</option>
              </select>
              <Input
                ref={regularNumberRef}
                type="text"
                placeholder="(00) 0000-0000"
                defaultValue={regularRedirectNumber}
                onBlur={() => regularNumberRef.current && setRegularRedirectNumber(regularNumberRef.current.value)}
              />
            </div>
          </Field>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Manutenção">
            <div className="grid grid-cols-2 gap-2">
              <select
                className={`rounded-xl border px-3 py-2 text-sm focus:ring-2 focus:ring-brand ${
                  isDark
                    ? 'border-gray-600 bg-gray-700 text-gray-200 focus:border-brand'
                    : 'border-gray-300 bg-white text-gray-800 focus:border-brand'
                }`}
                value={maintenanceRedirectType}
                onChange={e => setMaintenanceRedirectType(e.target.value)}
              >
                <option value="fixo">Fixo</option>
                <option value="celular">Celular</option>
              </select>
              <Input
                ref={maintenanceNumberRef}
                type="text"
                placeholder="(00) 0000-0000"
                defaultValue={maintenanceRedirectNumber}
                onBlur={() => maintenanceNumberRef.current && setMaintenanceRedirectNumber(maintenanceNumberRef.current.value)}
              />
            </div>
          </Field>

          <Field label="Clientes ativos">
            <div className="grid grid-cols-2 gap-2">
              <select
                className={`rounded-xl border px-3 py-2 text-sm focus:ring-2 focus:ring-brand ${
                  isDark
                    ? 'border-gray-600 bg-gray-700 text-gray-200 focus:border-brand'
                    : 'border-gray-300 bg-white text-gray-800 focus:border-brand'
                }`}
                value={activeCustomersRedirectType}
                onChange={e => setActiveCustomersRedirectType(e.target.value)}
              >
                <option value="fixo">Fixo</option>
                <option value="celular">Celular</option>
              </select>
              <Input
                ref={activeCustomersNumberRef}
                type="text"
                placeholder="(00) 0000-0000"
                defaultValue={activeCustomersRedirectNumber}
                onBlur={() => activeCustomersNumberRef.current && setActiveCustomersRedirectNumber(activeCustomersNumberRef.current.value)}
              />
            </div>
          </Field>
        </div>
      </div>

      {/* Exemplos de objeções (Few-shots) */}
      <div className={`border-t pt-4 ${
        isDark ? 'border-gray-600' : 'border-gray-200'
      }`}>
        <div className="flex justify-between items-center mb-4">
          <h3 className={`text-sm font-medium ${
            isDark ? 'text-gray-300' : 'text-gray-700'
          }`}>Exemplos de Objeções</h3>
          <button
            className="px-3 py-1.5 bg-brand text-white rounded-xl text-xs hover:bg-brand/90 transition-colors"
            onClick={handleAddFewShot}
            type="button"
          >
            + Adicionar
          </button>
        </div>

        {fewShots.length === 0 ? (
          <div className={`rounded-2xl border p-6 text-center ${
            isDark
              ? 'border-gray-600 bg-gray-800/50'
              : 'border-gray-200 bg-gray-50'
          }`}>
            <p className={`text-sm ${
              isDark ? 'text-gray-400' : 'text-gray-500'
            }`}>Nenhum exemplo configurado</p>
          </div>
        ) : (
          <div className="space-y-3">
            {fewShots.map((fs, index) => {
              const key = `fewshot-${index}`;
              const inputs = fewShotInputs[key] || { objectionType: fs.objectionType, userMessage: fs.userMessage, botResponse: fs.botResponse };

              return (
                <div key={index} className={`p-4 rounded-xl border ${
                  isDark
                    ? 'border-gray-600 bg-gray-800/50'
                    : 'border-gray-200 bg-gray-50/50'
                }`}>
                  <div className="flex justify-between items-center mb-3">
                    <span className={`text-sm font-medium ${
                      isDark ? 'text-gray-300' : 'text-gray-700'
                    }`}>Exemplo #{index + 1}</span>
                    <button
                      className="text-red-500 hover:text-red-600 text-xs px-2 py-1 rounded hover:bg-red-50 transition-colors"
                      onClick={() => handleRemoveFewShot(index)}
                      type="button"
                    >
                      Remover
                    </button>
                  </div>

                  <div className="space-y-3">
                    <Field label="Tipo de objeção">
                      <Input
                        type="text"
                        placeholder="Ex: Preço, Medo, Tempo"
                        defaultValue={inputs.objectionType}
                        onBlur={(e) => updateFewShotField(index, 'objectionType', e.target.value)}
                      />
                    </Field>

                    <Field label="Pergunta do usuário">
                      <Textarea
                        rows={2}
                        placeholder="Ex: Achei muito caro o tratamento."
                        defaultValue={inputs.userMessage}
                        onBlur={(e) => updateFewShotField(index, 'userMessage', e.target.value)}
                      />
                    </Field>

                    <Field label="Resposta do assistente">
                      <Textarea
                        rows={3}
                        placeholder="Ex: Entendo sua preocupação com o investimento..."
                        defaultValue={inputs.botResponse}
                        onBlur={(e) => updateFewShotField(index, 'botResponse', e.target.value)}
                      />
                    </Field>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default ConversationFlowForm;