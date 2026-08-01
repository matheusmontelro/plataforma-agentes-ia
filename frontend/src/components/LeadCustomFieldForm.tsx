import React, { useState, useEffect } from 'react';
import {
  AlertCircle,
  Calendar,
  Check,
  FileText,
  Hash,
  List,
  Mail,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
  Type,
  type LucideIcon,
} from 'lucide-react';
import { CustomFieldType, LeadCustomField, LeadCustomFieldCreate, LeadCustomFieldUpdate, CustomFieldValidationRules } from '../services/api.ts';
import {
  agentiveIconButtonClass,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePanelClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';

interface LeadCustomFieldFormProps {
  field?: LeadCustomField | null;
  isPreviewMode?: boolean;
  onSave: (fieldData: LeadCustomFieldCreate | LeadCustomFieldUpdate) => void;
  onCancel: () => void;
  isDark: boolean;
}

interface FieldTypeOption {
  description: string;
  icon: LucideIcon;
  label: string;
  value: CustomFieldType;
}

const cx = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const createEmptyField = (): LeadCustomFieldCreate => ({
  field_name: '',
  field_key: '',
  field_type: 'text',
  is_required: false,
  default_value: null,
  validation_rules: {},
  display_order: 0,
  is_active: true,
});

const fieldTypes: FieldTypeOption[] = [
  { value: 'text', label: 'Texto', description: 'Resposta curta, como CPF ou protocolo', icon: Type },
  { value: 'textarea', label: 'Texto longo', description: 'Observações, histórico ou contexto amplo', icon: FileText },
  { value: 'email', label: 'E-mail', description: 'Endereços com formato de e-mail', icon: Mail },
  { value: 'number', label: 'Número', description: 'Valores numéricos com limites opcionais', icon: Hash },
  { value: 'date', label: 'Data', description: 'Datas importantes do relacionamento', icon: Calendar },
  { value: 'select', label: 'Seleção', description: 'Lista fechada para padronizar respostas', icon: List },
];

const getTypeLabel = (fieldType: CustomFieldType) => {
  return fieldTypes.find(type => type.value === fieldType)?.label || fieldType;
};

const LeadCustomFieldForm: React.FC<LeadCustomFieldFormProps> = ({
  field,
  isPreviewMode = false,
  onSave,
  onCancel,
  isDark
}) => {
  const [formData, setFormData] = useState<LeadCustomFieldCreate>(createEmptyField);
  const [selectOptions, setSelectOptions] = useState<string[]>([]);
  const [newOption, setNewOption] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (field) {
      setFormData({
        field_name: field.field_name,
        field_key: field.field_key,
        field_type: field.field_type,
        is_required: field.is_required,
        default_value: field.default_value,
        validation_rules: field.validation_rules || {},
        display_order: field.display_order,
        is_active: field.is_active
      });
      setSelectOptions(field.field_type === 'select' && Array.isArray(field.default_value) ? field.default_value : []);
    } else {
      setFormData(createEmptyField());
      setSelectOptions([]);
    }

    setNewOption('');
    setErrors({});
  }, [field]);

  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {};
    const minValue = formData.validation_rules?.min_value;
    const maxValue = formData.validation_rules?.max_value;

    if (!formData.field_name.trim()) {
      newErrors.field_name = 'Nome do campo é obrigatório';
    } else if (formData.field_name.trim().length < 2) {
      newErrors.field_name = 'Nome deve ter pelo menos 2 caracteres';
    }

    if (!formData.field_type) {
      newErrors.field_type = 'Tipo do campo é obrigatório';
    }

    if (formData.field_type === 'select' && selectOptions.length === 0) {
      newErrors.select_options = 'Adicione pelo menos uma opção para o campo de seleção';
    }

    if (minValue !== undefined && maxValue !== undefined && minValue > maxValue) {
      newErrors.validation_rules = 'Valor mínimo não pode ser maior que o máximo';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (!validateForm()) return;

    setIsSubmitting(true);

    try {
      const submitData: LeadCustomFieldCreate | LeadCustomFieldUpdate = {
        ...formData,
        field_name: formData.field_name.trim(),
        default_value: formData.field_type === 'select' ? selectOptions : formData.default_value
      };

      await onSave(submitData);
    } catch (error) {
      console.error('Erro ao salvar campo:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAddOption = () => {
    const option = newOption.trim();
    if (!option || selectOptions.includes(option)) return;

    setSelectOptions([...selectOptions, option]);
    setNewOption('');
    setErrors(prev => ({ ...prev, select_options: '' }));
  };

  const handleRemoveOption = (index: number) => {
    setSelectOptions(selectOptions.filter((_, optionIndex) => optionIndex !== index));
  };

  const handleInputChange = (fieldName: keyof LeadCustomFieldCreate, value: any) => {
    setFormData(prev => ({
      ...prev,
      [fieldName]: value
    }));

    if (errors[fieldName]) {
      setErrors(prev => ({
        ...prev,
        [fieldName]: ''
      }));
    }
  };

  const handleTypeChange = (fieldType: CustomFieldType) => {
    handleInputChange('field_type', fieldType);
    setErrors(prev => ({ ...prev, field_type: '', select_options: '' }));

    if (fieldType !== 'select') {
      setSelectOptions([]);
    }
  };

  const handleValidationRuleChange = (rule: keyof CustomFieldValidationRules, value: any) => {
    setFormData(prev => ({
      ...prev,
      validation_rules: {
        ...prev.validation_rules,
        [rule]: value
      }
    }));
    setErrors(prev => ({ ...prev, validation_rules: '' }));
  };

  if (isPreviewMode && field) {
    return (
      <div className={agentivePanelClass(isDark, 'p-6 shadow-flat')}>
        <div className="mb-4">
          <h3 className="text-lg font-semibold">{field.field_name}</h3>
          <p className={`text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>
            Tipo: {getTypeLabel(field.field_type)}
          </p>
        </div>
        <label className={agentiveLabelClass(isDark)}>
          {field.field_name} {field.is_required && <span className="text-red-500">*</span>}
        </label>
        <div className={`rounded-xl border px-3 py-2 text-sm ${isDark ? 'border-white/10 bg-white/[0.04] text-white/45' : 'border-brand/10 bg-brand-canvas text-brand/45'}`}>
          Prévia do campo {getTypeLabel(field.field_type).toLowerCase()}
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
        <div>
          <label className={agentiveLabelClass(isDark)}>
            Nome do campo <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            value={formData.field_name}
            onChange={(event) => handleInputChange('field_name', event.target.value)}
            placeholder="Ex: CPF, Preferência, Convênio"
            className={agentiveInputClass(isDark, `min-h-11 ${errors.field_name ? 'border-red-500 focus:border-red-500 focus:ring-red-500/20' : ''}`)}
            disabled={isSubmitting}
            autoFocus
          />
          {errors.field_name && (
            <p className="mt-1.5 flex items-center gap-1 text-sm text-red-500">
              <AlertCircle className="h-3.5 w-3.5" />
              {errors.field_name}
            </p>
          )}
        </div>

        <div className={cx('rounded-2xl border p-3', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
          <p className={cx('text-[11px] font-semibold uppercase tracking-[0.1em]', isDark ? 'text-white/45' : 'text-brand/45')}>
            Chave técnica
          </p>
          <p className={cx('mt-2 break-all font-mono text-xs', isDark ? 'text-white/70' : 'text-brand/70')}>
            {field?.field_key || 'Gerada ao salvar'}
          </p>
        </div>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between gap-3">
          <label className={agentiveLabelClass(isDark, 'mb-0')}>
            Tipo do campo <span className="text-red-500">*</span>
          </label>
          <span className={cx('text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
            {getTypeLabel(formData.field_type)}
          </span>
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          {fieldTypes.map(type => {
            const Icon = type.icon;
            const selected = formData.field_type === type.value;

            return (
              <button
                key={type.value}
                type="button"
                onClick={() => handleTypeChange(type.value)}
                disabled={isSubmitting}
                aria-pressed={selected}
                className={cx(
                  'flex min-h-[88px] items-start gap-3 rounded-2xl border p-3 text-left transition-all disabled:opacity-50',
                  selected
                    ? isDark ? 'border-white bg-white text-brand shadow-flat' : 'border-brand bg-brand text-white shadow-flat'
                    : isDark ? 'border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white' : 'border-brand/10 bg-white text-brand/70 hover:bg-brand-canvas hover:text-brand'
                )}
              >
                <span className={cx(
                  'grid h-9 w-9 shrink-0 place-items-center rounded-xl',
                  selected
                    ? isDark ? 'bg-brand text-white' : 'bg-white text-brand'
                    : isDark ? 'bg-white/10 text-white/60' : 'bg-brand-canvas text-brand/55'
                )}>
                  <Icon className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold">{type.label}</span>
                  <span className={cx('mt-1 block text-xs leading-relaxed', selected ? (isDark ? 'text-brand/60' : 'text-white/65') : (isDark ? 'text-white/45' : 'text-brand/45'))}>
                    {type.description}
                  </span>
                </span>
                {selected && <Check className="ml-auto h-4 w-4 shrink-0" />}
              </button>
            );
          })}
        </div>

        {errors.field_type && (
          <p className="mt-1.5 flex items-center gap-1 text-sm text-red-500">
            <AlertCircle className="h-3.5 w-3.5" />
            {errors.field_type}
          </p>
        )}
      </section>

      {formData.field_type === 'select' && (
        <section className={cx('rounded-2xl border p-4', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
          <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <label className={agentiveLabelClass(isDark, 'mb-0')}>
                Opções de seleção <span className="text-red-500">*</span>
              </label>
              <p className={cx('mt-1 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
                Use opções curtas para manter o CRM fácil de filtrar.
              </p>
            </div>
            <span className={cx('text-xs font-semibold', isDark ? 'text-white/55' : 'text-brand/55')}>
              {selectOptions.length} opção{selectOptions.length === 1 ? '' : 'ões'}
            </span>
          </div>

          <div className="space-y-2">
            {selectOptions.map((option, index) => (
              <div key={`${option}-${index}`} className="flex items-center gap-2">
                <span className={cx('min-w-0 flex-1 truncate rounded-xl border px-3 py-2 text-sm', isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand')}>
                  {option}
                </span>
                <button
                  type="button"
                  onClick={() => handleRemoveOption(index)}
                  className={agentiveIconButtonClass(isDark, 'danger')}
                  aria-label={`Remover opção ${option}`}
                  title={`Remover ${option}`}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}

            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                type="text"
                value={newOption}
                onChange={(event) => setNewOption(event.target.value)}
                placeholder="Adicionar opção"
                className={agentiveInputClass(isDark, 'min-h-11 flex-1')}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    handleAddOption();
                  }
                }}
                disabled={isSubmitting}
              />
              <button
                type="button"
                onClick={handleAddOption}
                disabled={!newOption.trim() || isSubmitting}
                className={agentivePrimaryButtonClass('min-h-11 px-4')}
              >
                <Plus className="h-4 w-4" />
                Adicionar
              </button>
            </div>
          </div>

          {errors.select_options && (
            <p className="mt-2 flex items-center gap-1 text-sm text-red-500">
              <AlertCircle className="h-3.5 w-3.5" />
              {errors.select_options}
            </p>
          )}
        </section>
      )}

      <section className="grid gap-3 sm:grid-cols-2">
        <label className={cx('flex cursor-pointer items-start gap-3 rounded-2xl border p-4 transition-colors', isDark ? 'border-white/10 bg-white/[0.04] hover:bg-white/10' : 'border-brand/10 bg-white hover:bg-brand-canvas')}>
          <input
            type="checkbox"
            checked={Boolean(formData.is_required)}
            onChange={(event) => handleInputChange('is_required', event.target.checked)}
            className="mt-1 h-4 w-4 rounded border-brand/20 text-brand focus:ring-brand/20"
            disabled={isSubmitting}
          />
          <span className="min-w-0">
            <span className="flex items-center gap-2 text-sm font-semibold">
              <AlertCircle className="h-4 w-4" />
              Campo obrigatório
            </span>
            <span className={cx('mt-1 block text-xs leading-relaxed', isDark ? 'text-white/45' : 'text-brand/45')}>
              O lead precisa informar esse dado quando o campo aparecer no cadastro.
            </span>
          </span>
        </label>

        <label className={cx('flex cursor-pointer items-start gap-3 rounded-2xl border p-4 transition-colors', isDark ? 'border-white/10 bg-white/[0.04] hover:bg-white/10' : 'border-brand/10 bg-white hover:bg-brand-canvas')}>
          <input
            type="checkbox"
            checked={Boolean(formData.is_active)}
            onChange={(event) => handleInputChange('is_active', event.target.checked)}
            className="mt-1 h-4 w-4 rounded border-brand/20 text-brand focus:ring-brand/20"
            disabled={isSubmitting}
          />
          <span className="min-w-0">
            <span className="flex items-center gap-2 text-sm font-semibold">
              <ShieldCheck className="h-4 w-4" />
              Campo ativo
            </span>
            <span className={cx('mt-1 block text-xs leading-relaxed', isDark ? 'text-white/45' : 'text-brand/45')}>
              Campos inativos ficam preservados, mas deixam de aparecer para novos usos.
            </span>
          </span>
        </label>
      </section>

      {formData.field_type === 'number' && (
        <section className={cx('rounded-2xl border p-4', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
          <div className="mb-3">
            <h4 className="text-sm font-semibold">Validação numérica</h4>
            <p className={cx('mt-1 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
              Defina limites apenas quando o dado tiver uma faixa aceita.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className={agentiveLabelClass(isDark, 'text-xs')}>
                Valor mínimo
              </label>
              <input
                type="number"
                value={formData.validation_rules?.min_value ?? ''}
                onChange={(event) => handleValidationRuleChange('min_value', event.target.value ? parseFloat(event.target.value) : undefined)}
                className={agentiveInputClass(isDark)}
                disabled={isSubmitting}
              />
            </div>

            <div>
              <label className={agentiveLabelClass(isDark, 'text-xs')}>
                Valor máximo
              </label>
              <input
                type="number"
                value={formData.validation_rules?.max_value ?? ''}
                onChange={(event) => handleValidationRuleChange('max_value', event.target.value ? parseFloat(event.target.value) : undefined)}
                className={agentiveInputClass(isDark)}
                disabled={isSubmitting}
              />
            </div>
          </div>

          {errors.validation_rules && (
            <p className="mt-2 flex items-center gap-1 text-sm text-red-500">
              <AlertCircle className="h-3.5 w-3.5" />
              {errors.validation_rules}
            </p>
          )}
        </section>
      )}

      {errors.validation_rules && formData.field_type !== 'number' && (
        <p className="flex items-center gap-1 text-sm text-red-500">
          <AlertCircle className="h-3.5 w-3.5" />
          {errors.validation_rules}
        </p>
      )}

      <div className={cx('flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:justify-end', isDark ? 'border-white/10' : 'border-brand/10')}>
        <button
          type="button"
          onClick={onCancel}
          disabled={isSubmitting}
          className={agentiveSecondaryButtonClass(isDark, 'min-h-10')}
        >
          Cancelar
        </button>

        <button
          type="submit"
          disabled={isSubmitting}
          className={agentivePrimaryButtonClass('min-h-10')}
        >
          {isSubmitting ? (
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          {field ? 'Salvar alterações' : 'Criar campo'}
        </button>
      </div>
    </form>
  );
};

export default LeadCustomFieldForm;
