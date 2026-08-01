import React, { useRef, useEffect, useState } from 'react';
import { DollarSign, CreditCard, Tag, CheckCircle, AlertCircle, HelpCircle } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';

interface FinancialConfigFormProps {
  acceptsHealthInsurance: boolean;
  setAcceptsHealthInsurance: (val: boolean) => void;
  healthInsurancePlans: string;
  setHealthInsurancePlans: (val: string) => void;
  paymentMethods: string;
  setPaymentMethods: (val: string) => void;
  installmentConditions: string;
  setInstallmentConditions: (val: string) => void;
  evaluationPrice: string;
  setEvaluationPrice: (val: string) => void;
  treatmentPrices: string;
  setTreatmentPrices: (val: string) => void;
}

const FinancialConfigForm: React.FC<FinancialConfigFormProps> = ({
  acceptsHealthInsurance, setAcceptsHealthInsurance,
  healthInsurancePlans, setHealthInsurancePlans,
  paymentMethods, setPaymentMethods,
  installmentConditions, setInstallmentConditions,
  evaluationPrice, setEvaluationPrice,
  treatmentPrices, setTreatmentPrices
}) => {
  const { isDark } = useTheme();

  // Estado para controlar se avaliação é gratuita
  // Detectar se o valor atual indica gratuito
  const detectFreeEvaluation = (price: string) => {
    const priceLower = price.toLowerCase().trim();
    return (
      priceLower === 'gratuito' ||
      priceLower === 'gratuita' ||
      priceLower.includes('gratuito') ||
      priceLower.includes('gratuita') ||
      priceLower.includes('sem custo') ||
      priceLower.includes('cortesia') ||
      priceLower === '' ||
      price === ''
    );
  };

  const [isFreeEvaluation, setIsFreeEvaluation] = useState(
    detectFreeEvaluation(evaluationPrice)
  );

  // Refs para inputs
  const plansRef = useRef<HTMLInputElement>(null);
  const paymentsRef = useRef<HTMLInputElement>(null);
  const installmentsRef = useRef<HTMLInputElement>(null);
  const evalPriceRef = useRef<HTMLTextAreaElement>(null);
  const treatPricesRef = useRef<HTMLTextAreaElement>(null);

  // Inicializar valores nos inputs
  useEffect(() => {
    if (plansRef.current) plansRef.current.value = healthInsurancePlans;
    if (paymentsRef.current) paymentsRef.current.value = paymentMethods;
    if (installmentsRef.current) installmentsRef.current.value = installmentConditions;
    if (evalPriceRef.current) {
      evalPriceRef.current.value = isFreeEvaluation ? 'Gratuito' : evaluationPrice;
    }
    if (treatPricesRef.current) treatPricesRef.current.value = treatmentPrices;
  }, [healthInsurancePlans, paymentMethods, installmentConditions, evaluationPrice, treatmentPrices, isFreeEvaluation]);

  // Atualizar valor quando checkbox muda
  useEffect(() => {
    if (isFreeEvaluation) {
      setEvaluationPrice('Gratuito');
      if (evalPriceRef.current) {
        evalPriceRef.current.value = 'Gratuito';
      }
    }
  }, [isFreeEvaluation, setEvaluationPrice]);

  // Handler para convênios que preserva scroll
  const handleHealthInsuranceChange = (checked: boolean) => {
    // Salvar posição atual do scroll
    const currentScrollY = window.scrollY;

    setAcceptsHealthInsurance(checked);

    // Manter posição de scroll após a atualização
    requestAnimationFrame(() => {
      window.scrollTo(0, currentScrollY);
    });
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

  const Checkbox: React.FC<{ checked: boolean; onChange: (v: boolean) => void; label: string }> = ({ checked, onChange, label }) => (
    <label className="inline-flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-gray-300 text-brand focus:ring-brand"
      />
      <span className={isDark ? 'text-gray-300' : 'text-gray-700'}>{label}</span>
    </label>
  );

  return (
    <div className="space-y-4">
      {/* Convênios de serviços */}
      <Checkbox
        checked={acceptsHealthInsurance}
        onChange={handleHealthInsuranceChange}
        label="Aceita convênios de serviços"
      />

      {acceptsHealthInsurance && (
        <Field label="Convênios aceitos">
          <Input
            ref={plansRef}
            type="text"
            placeholder="Ex: Amil, SulAmérica, Bradesco"
            defaultValue={healthInsurancePlans}
            onBlur={() => plansRef.current && setHealthInsurancePlans(plansRef.current.value)}
          />
        </Field>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="Formas de pagamento">
          <Input
            ref={paymentsRef}
            type="text"
            placeholder="Ex: Dinheiro, Cartão, Pix"
            defaultValue={paymentMethods}
            onBlur={() => paymentsRef.current && setPaymentMethods(paymentsRef.current.value)}
          />
        </Field>

        <Field label="Condições de parcelamento">
          <Input
            ref={installmentsRef}
            type="text"
            placeholder="Ex: Até 10x sem juros"
            defaultValue={installmentConditions}
            onBlur={() => installmentsRef.current && setInstallmentConditions(installmentsRef.current.value)}
          />
        </Field>
      </div>

      <div className="space-y-3">
        <Checkbox
          checked={isFreeEvaluation}
          onChange={(checked) => {
            setIsFreeEvaluation(checked);
            if (!checked && evalPriceRef.current) {
              evalPriceRef.current.value = '';
              evalPriceRef.current.focus();
            }
          }}
          label="Avaliação gratuita"
        />

        <Field
          label="Preço da avaliação"
          hint={isFreeEvaluation ? "A avaliação está marcada como gratuita" : "Informe o valor cobrado pela avaliação"}
        >
          <Textarea
            ref={evalPriceRef}
            rows={3}
            placeholder={isFreeEvaluation ? "Gratuito" : "Ex: R$ 80,00 ou A partir de R$ 50,00"}
            defaultValue={isFreeEvaluation ? "Gratuito" : evaluationPrice}
            disabled={isFreeEvaluation}
            onBlur={() => {
              if (evalPriceRef.current && !isFreeEvaluation) {
                setEvaluationPrice(evalPriceRef.current.value);
              }
            }}
            className={isFreeEvaluation ? 'opacity-60 cursor-not-allowed' : ''}
          />
        </Field>
      </div>

      <Field label="Tabela de preços dos tratamentos" hint="Liste os principais tratamentos e preços">
        <Textarea
          ref={treatPricesRef}
          rows={5}
          placeholder="Ex: Implante: a partir de R$ 2.500,00&#10;Clareamento: a partir de R$ 800,00&#10;Lentes: a partir de R$ 1.200,00 por dente"
          defaultValue={treatmentPrices}
          onBlur={() => treatPricesRef.current && setTreatmentPrices(treatPricesRef.current.value)}
        />
      </Field>

      {/* Dica com cores da empresa (mesmo padrão dos outros componentes) */}
      <div className={`rounded-2xl border p-4 ${
        isDark
          ? 'border-brand/30 bg-brand/10'
          : 'border-brand/20 bg-brand/5'
      }`}>
        <div className="flex gap-3">
          <HelpCircle className="w-5 h-5 text-brand flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="font-medium text-brand mb-1">Dica sobre preços</h4>
            <p className={`text-sm ${
              isDark ? 'text-brand/90' : 'text-brand/80'
            }`}>
              Recomenda-se usar faixas de preço ou valores "a partir de", explicando que o valor final depende de uma avaliação presencial.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default FinancialConfigForm;