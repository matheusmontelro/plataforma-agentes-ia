import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  CustomFieldType,
  LeadCustomField,
  LeadCustomFieldCreate,
  LeadCustomFieldUpdate,
  listarLeadCustomFields,
  criarLeadCustomField,
  atualizarLeadCustomField,
  deletarLeadCustomField
} from '../services/api';
import LeadCustomFieldForm from '../components/LeadCustomFieldForm.tsx';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  ClipboardCheck,
  Database,
  Edit2,
  FileText,
  Hash,
  KeyRound,
  Layers,
  List,
  Loader2,
  Mail,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  ToggleRight,
  Trash2,
  X,
  type LucideIcon,
} from 'lucide-react';
import ConfirmDeleteModal from '../components/ConfirmDeleteModal.tsx';
import {
  AgentiveAlert,
  AgentiveEmptyState,
  agentiveIconButtonClass,
  agentiveInputClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';

type FieldStatusFilter = 'all' | 'active' | 'inactive' | 'required';
type FieldTypeFilter = CustomFieldType | 'all';

interface FieldTypeMeta {
  description: string;
  icon: LucideIcon;
  label: string;
  tone: string;
  toneDark: string;
}

interface MetricTileProps {
  helper: string;
  icon: LucideIcon;
  isDark: boolean;
  label: string;
  value: React.ReactNode;
}

const cx = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const FIELD_TYPE_META: Record<CustomFieldType, FieldTypeMeta> = {
  text: {
    description: 'Texto curto para dados simples',
    icon: FileText,
    label: 'Texto',
    tone: 'bg-sky-50 text-sky-700 ring-sky-100',
    toneDark: 'bg-sky-400/10 text-sky-200 ring-sky-300/15',
  },
  textarea: {
    description: 'Observações e textos longos',
    icon: FileText,
    label: 'Texto longo',
    tone: 'bg-indigo-50 text-indigo-700 ring-indigo-100',
    toneDark: 'bg-indigo-400/10 text-indigo-200 ring-indigo-300/15',
  },
  email: {
    description: 'Endereços de e-mail',
    icon: Mail,
    label: 'E-mail',
    tone: 'bg-emerald-50 text-emerald-700 ring-emerald-100',
    toneDark: 'bg-emerald-400/10 text-emerald-200 ring-emerald-300/15',
  },
  number: {
    description: 'Valores e quantidades',
    icon: Hash,
    label: 'Número',
    tone: 'bg-violet-50 text-violet-700 ring-violet-100',
    toneDark: 'bg-violet-400/10 text-violet-200 ring-violet-300/15',
  },
  date: {
    description: 'Datas importantes do lead',
    icon: Calendar,
    label: 'Data',
    tone: 'bg-amber-50 text-amber-700 ring-amber-100',
    toneDark: 'bg-amber-400/10 text-amber-200 ring-amber-300/15',
  },
  select: {
    description: 'Lista de opções padronizadas',
    icon: List,
    label: 'Seleção',
    tone: 'bg-rose-50 text-rose-700 ring-rose-100',
    toneDark: 'bg-rose-400/10 text-rose-200 ring-rose-300/15',
  },
};

const FIELD_TYPE_OPTIONS = Object.keys(FIELD_TYPE_META) as CustomFieldType[];

const STATUS_FILTERS: Array<{ id: FieldStatusFilter; label: string }> = [
  { id: 'all', label: 'Todos' },
  { id: 'active', label: 'Ativos' },
  { id: 'inactive', label: 'Inativos' },
  { id: 'required', label: 'Obrigatórios' },
];

const getFieldTypeMeta = (fieldType: string) => {
  return FIELD_TYPE_META[fieldType as CustomFieldType] || FIELD_TYPE_META.text;
};

const getFieldTypeLabel = (fieldType: string) => getFieldTypeMeta(fieldType).label;

const getSelectOptionsCount = (field: LeadCustomField) => {
  return field.field_type === 'select' && Array.isArray(field.default_value) ? field.default_value.length : 0;
};

const getValidationRules = (field: LeadCustomField) => {
  const rules: string[] = [];
  const validation = field.validation_rules || {};

  if (field.is_required) rules.push('Obrigatório');
  if (field.field_type === 'select') rules.push(`${getSelectOptionsCount(field)} opções`);
  if (validation.min_length) rules.push(`mín. ${validation.min_length} caracteres`);
  if (validation.max_length) rules.push(`máx. ${validation.max_length} caracteres`);
  if (validation.min_value !== undefined) rules.push(`mín. ${validation.min_value}`);
  if (validation.max_value !== undefined) rules.push(`máx. ${validation.max_value}`);
  if (validation.pattern) rules.push('formato validado');

  return rules;
};

const MetricTile: React.FC<MetricTileProps> = ({ helper, icon: Icon, isDark, label, value }) => (
  <div className={agentivePanelClass(isDark, 'p-4 shadow-flat')}>
    <div className="mb-3 flex items-center justify-between gap-3">
      <span className={cx('text-sm font-medium', isDark ? 'text-white/55' : 'text-brand/55')}>{label}</span>
      <span className={cx('grid h-9 w-9 place-items-center rounded-xl', isDark ? 'bg-white/10 text-white/70' : 'bg-brand-canvas text-brand/65')}>
        <Icon className="h-4 w-4" />
      </span>
    </div>
    <div className="text-2xl font-semibold leading-none">{value}</div>
    <div className={cx('mt-1 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>{helper}</div>
  </div>
);

const LeadCustomFieldsConfig: React.FC = () => {
  const { isDark } = useTheme();

  const [customFields, setCustomFields] = useState<LeadCustomField[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingField, setEditingField] = useState<LeadCustomField | null>(null);
  const [actionLoading, setActionLoading] = useState<{ [key: string]: boolean }>({});
  const [fieldToDelete, setFieldToDelete] = useState<LeadCustomField | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [typeFilter, setTypeFilter] = useState<FieldTypeFilter>('all');
  const [statusFilter, setStatusFilter] = useState<FieldStatusFilter>('all');
  const [selectedFieldId, setSelectedFieldId] = useState<number | null>(null);

  const storedClientId = Number(localStorage.getItem('client_id'));
  const storedCompanyId = Number(localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  const clientId = Number.isInteger(storedClientId) && storedClientId > 0 ? storedClientId : null;
  const companyId = Number.isInteger(storedCompanyId) && storedCompanyId > 0 ? storedCompanyId : null;
  const apiKey = '';

  const sortedFields = useMemo(() => {
    return [...customFields].sort((a, b) => a.display_order - b.display_order);
  }, [customFields]);

  const filteredFields = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();

    return sortedFields.filter(field => {
      const meta = getFieldTypeMeta(field.field_type);
      const matchesSearch = !query || [
        field.field_name,
        field.field_key,
        meta.label,
        meta.description,
      ].some(value => value.toLowerCase().includes(query));
      const matchesType = typeFilter === 'all' || field.field_type === typeFilter;
      const matchesStatus =
        statusFilter === 'all' ||
        (statusFilter === 'active' && field.is_active) ||
        (statusFilter === 'inactive' && !field.is_active) ||
        (statusFilter === 'required' && field.is_required);

      return matchesSearch && matchesType && matchesStatus;
    });
  }, [searchTerm, sortedFields, statusFilter, typeFilter]);

  const fieldsCount = sortedFields.length;
  const activeFieldsCount = sortedFields.filter(field => field.is_active).length;
  const requiredFieldsCount = sortedFields.filter(field => field.is_required).length;
  const typeCount = new Set(sortedFields.map(field => field.field_type)).size;
  const activeFilterCount = (searchTerm.trim() ? 1 : 0) + (typeFilter !== 'all' ? 1 : 0) + (statusFilter !== 'all' ? 1 : 0);

  const selectedField = useMemo(() => {
    if (filteredFields.length === 0) return null;
    return filteredFields.find(field => field.id === selectedFieldId) || filteredFields[0];
  }, [filteredFields, selectedFieldId]);

  const loadCustomFields = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);

      if (!clientId || !companyId) {
        throw new Error('Selecione uma empresa válida antes de carregar campos customizados.');
      }

      const fields = await listarLeadCustomFields(clientId, companyId, true, apiKey);
      setCustomFields(fields);
    } catch (err: any) {
      console.error('Erro ao carregar campos customizados:', err);
      setError(err.message || 'Erro ao carregar campos customizados');
    } finally {
      setIsLoading(false);
    }
  }, [clientId, companyId]);

  useEffect(() => {
    loadCustomFields();
  }, [loadCustomFields]);

  const handleCreateField = () => {
    setEditingField(null);
    setIsFormOpen(true);
  };

  const handleEditField = (field: LeadCustomField) => {
    setEditingField(field);
    setIsFormOpen(true);
  };

  const handleSaveField = async (fieldData: LeadCustomFieldCreate | LeadCustomFieldUpdate) => {
    if (!clientId || !companyId) {
      setError('Selecione uma empresa válida antes de salvar campos customizados.');
      return;
    }

    try {
      setError(null);

      const loadingKey = editingField ? `edit-${editingField.id}` : 'create';
      setActionLoading(prev => ({ ...prev, [loadingKey]: true }));

      if (editingField) {
        const updatedField = await atualizarLeadCustomField(
          clientId,
          companyId,
          editingField.id,
          fieldData,
          apiKey
        );

        setCustomFields(prev =>
          prev.map(field =>
            field.id === editingField.id ? updatedField : field
          )
        );
        setSelectedFieldId(updatedField.id);
        setSuccessMessage('Campo atualizado com sucesso.');
      } else {
        const newField = await criarLeadCustomField(
          clientId,
          companyId,
          fieldData as LeadCustomFieldCreate,
          apiKey
        );

        setCustomFields(prev => [...prev, newField].sort((a, b) => a.display_order - b.display_order));
        setSelectedFieldId(newField.id);
        setSuccessMessage('Campo criado com sucesso.');
      }

      setIsFormOpen(false);
      setEditingField(null);
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: any) {
      console.error('Erro ao salvar campo:', err);
      setError(err.message || 'Erro ao salvar campo');
    } finally {
      const loadingKey = editingField ? `edit-${editingField?.id}` : 'create';
      setActionLoading(prev => ({ ...prev, [loadingKey]: false }));
    }
  };

  const handleDeleteField = async (field: LeadCustomField) => {
    setFieldToDelete(field);
  };

  const confirmDeleteField = async () => {
    if (!fieldToDelete) return;
    if (!clientId || !companyId) {
      setError('Selecione uma empresa válida antes de excluir campos customizados.');
      return;
    }

    try {
      setError(null);
      setActionLoading(prev => ({ ...prev, [`delete-${fieldToDelete.id}`]: true }));

      await deletarLeadCustomField(clientId, companyId, fieldToDelete.id, apiKey);

      setCustomFields(prev =>
        prev.filter(field => field.id !== fieldToDelete.id)
      );
      setSelectedFieldId(current => current === fieldToDelete.id ? null : current);
      setFieldToDelete(null);
      setSuccessMessage('Campo excluído com sucesso.');
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: any) {
      console.error('Erro ao excluir campo:', err);
      setError(err.message || 'Erro ao excluir campo');
    } finally {
      setActionLoading(prev => fieldToDelete ? ({ ...prev, [`delete-${fieldToDelete.id}`]: false }) : prev);
    }
  };

  const resetFilters = () => {
    setSearchTerm('');
    setTypeFilter('all');
    setStatusFilter('all');
  };

  const renderFieldIcon = (field: LeadCustomField, selected = false) => {
    const meta = getFieldTypeMeta(field.field_type);
    const Icon = meta.icon;

    return (
      <span className={cx(
        'grid h-10 w-10 shrink-0 place-items-center rounded-xl ring-1',
        selected
          ? isDark ? 'bg-white text-brand ring-white' : 'bg-brand text-white ring-brand'
          : isDark ? meta.toneDark : meta.tone
      )}>
        <Icon className="h-4 w-4" />
      </span>
    );
  };

  const renderStatusPills = (field: LeadCustomField) => (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className={cx(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold',
        field.is_active
          ? isDark ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-200' : 'border-emerald-200 bg-emerald-50 text-emerald-700'
          : isDark ? 'border-white/10 bg-white/[0.04] text-white/45' : 'border-brand/10 bg-brand-canvas text-brand/45'
      )}>
        <ToggleRight className="h-3 w-3" />
        {field.is_active ? 'Ativo' : 'Inativo'}
      </span>
      {field.is_required && (
        <span className={cx(
          'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold',
          isDark ? 'border-amber-400/20 bg-amber-400/10 text-amber-200' : 'border-amber-200 bg-amber-50 text-amber-700'
        )}>
          <AlertCircle className="h-3 w-3" />
          Obrigatório
        </span>
      )}
    </div>
  );

  const renderFieldActions = (field: LeadCustomField) => (
    <div className="flex items-center justify-end gap-1">
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          handleEditField(field);
        }}
        className={agentiveIconButtonClass(isDark, 'primary', 'min-h-10 min-w-10')}
        aria-label={`Editar campo ${field.field_name}`}
        title={`Editar ${field.field_name}`}
      >
        <Edit2 className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          handleDeleteField(field);
        }}
        disabled={actionLoading[`delete-${field.id}`]}
        className={agentiveIconButtonClass(isDark, 'danger', `min-h-10 min-w-10 ${actionLoading[`delete-${field.id}`] ? 'cursor-not-allowed opacity-50' : ''}`)}
        aria-label={`Excluir campo ${field.field_name}`}
        title={`Excluir ${field.field_name}`}
      >
        {actionLoading[`delete-${field.id}`] ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Trash2 className="h-4 w-4" />
        )}
      </button>
    </div>
  );

  return (
    <div className={agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10 2xl:px-12')}>
      <div className="mx-auto w-full max-w-screen-2xl space-y-4">
        <section className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
          <div className="grid gap-4 xl:grid-cols-[minmax(260px,1fr)_auto] xl:items-end">
            <div className="min-w-0">
              <div className={cx('mb-2 text-[10px] font-semibold uppercase tracking-[0.14em]', isDark ? 'text-white/40' : 'text-brand/45')}>
                Configurações
              </div>
              <div className="flex items-center gap-3">
                <span className={cx('grid h-11 w-11 shrink-0 place-items-center rounded-xl', isDark ? 'bg-white/10 text-white' : 'bg-brand text-white')}>
                  <ClipboardCheck className="h-5 w-5" />
                </span>
                <div className="min-w-0">
                  <h1 className="truncate text-2xl font-semibold leading-tight sm:text-3xl">Campos personalizados</h1>
                  <p className={cx('mt-1 max-w-3xl text-sm', isDark ? 'text-white/55' : 'text-brand/55')}>
                    Estruture os dados extras que alimentam CRM, automações e atendimento sem perder padronização.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 xl:justify-end">
              <button
                type="button"
                onClick={loadCustomFields}
                disabled={isLoading}
                className={agentiveSecondaryButtonClass(isDark, 'min-h-10')}
              >
                <RefreshCw className={cx('h-4 w-4', isLoading && 'animate-spin')} />
                Atualizar
              </button>
              <button
                type="button"
                onClick={handleCreateField}
                className={agentivePrimaryButtonClass('min-h-10')}
              >
                <Plus className="h-4 w-4" />
                Novo campo
              </button>
            </div>
          </div>
        </section>

        {error && (
          <AgentiveAlert variant="error" title="Não foi possível concluir a ação" onClose={() => setError(null)}>
            {error}
          </AgentiveAlert>
        )}

        {successMessage && (
          <AgentiveAlert variant="success" title="Operação concluída" onClose={() => setSuccessMessage(null)}>
            {successMessage}
          </AgentiveAlert>
        )}

        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricTile
            helper="atributos cadastrados"
            icon={Database}
            isDark={isDark}
            label="Total"
            value={fieldsCount.toLocaleString('pt-BR')}
          />
          <MetricTile
            helper="disponíveis nos cadastros"
            icon={CheckCircle2}
            isDark={isDark}
            label="Ativos"
            value={activeFieldsCount.toLocaleString('pt-BR')}
          />
          <MetricTile
            helper="exigidos no preenchimento"
            icon={AlertCircle}
            isDark={isDark}
            label="Obrigatórios"
            value={requiredFieldsCount.toLocaleString('pt-BR')}
          />
          <MetricTile
            helper="formatos diferentes em uso"
            icon={Layers}
            isDark={isDark}
            label="Tipos em uso"
            value={typeCount.toLocaleString('pt-BR')}
          />
        </section>

        <section className={agentivePanelClass(isDark, 'p-3')}>
          <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
            <div className="flex min-w-0 flex-col gap-2 lg:flex-row lg:items-center">
              <div className={cx('flex min-h-11 w-full items-center gap-2', agentiveInputClass(isDark))}>
                <Search className={cx('h-4 w-4 shrink-0', isDark ? 'text-white/40' : 'text-brand/40')} />
                <input
                  type="text"
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                  placeholder="Buscar por nome, chave ou tipo"
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-inherit"
                />
                {searchTerm && (
                  <button
                    type="button"
                    onClick={() => setSearchTerm('')}
                    className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-7 min-w-7 p-1')}
                    aria-label="Limpar busca"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:w-[440px]">
                <label className={cx('flex min-h-11 items-center gap-2 rounded-xl border px-3', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-white')}>
                  <SlidersHorizontal className={cx('h-4 w-4 shrink-0', isDark ? 'text-white/45' : 'text-brand/45')} />
                  <span className={cx('text-[11px] font-semibold uppercase tracking-[0.08em]', isDark ? 'text-white/45' : 'text-brand/45')}>Tipo</span>
                  <select
                    value={typeFilter}
                    onChange={(event) => setTypeFilter(event.target.value as FieldTypeFilter)}
                    className={cx('min-w-0 flex-1 bg-transparent text-sm font-semibold outline-none', isDark ? 'text-white' : 'text-brand')}
                    aria-label="Filtrar por tipo"
                  >
                    <option value="all">Todos</option>
                    {FIELD_TYPE_OPTIONS.map(type => (
                      <option key={type} value={type}>{FIELD_TYPE_META[type].label}</option>
                    ))}
                  </select>
                </label>

                <label className={cx('flex min-h-11 items-center gap-2 rounded-xl border px-3', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-white')}>
                  <ToggleRight className={cx('h-4 w-4 shrink-0', isDark ? 'text-white/45' : 'text-brand/45')} />
                  <span className={cx('text-[11px] font-semibold uppercase tracking-[0.08em]', isDark ? 'text-white/45' : 'text-brand/45')}>Status</span>
                  <select
                    value={statusFilter}
                    onChange={(event) => setStatusFilter(event.target.value as FieldStatusFilter)}
                    className={cx('min-w-0 flex-1 bg-transparent text-sm font-semibold outline-none', isDark ? 'text-white' : 'text-brand')}
                    aria-label="Filtrar por status"
                  >
                    {STATUS_FILTERS.map(status => (
                      <option key={status.id} value={status.id}>{status.label}</option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 xl:justify-end">
              <span className={agentivePillClass(isDark, false, 'min-h-10 rounded-xl px-3')}>
                {filteredFields.length.toLocaleString('pt-BR')} visíveis
              </span>
              {activeFilterCount > 0 && (
                <button
                  type="button"
                  onClick={resetFilters}
                  className={agentiveSecondaryButtonClass(isDark, 'min-h-10')}
                >
                  <X className="h-4 w-4" />
                  Limpar filtros
                </button>
              )}
            </div>
          </div>
        </section>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <section className={agentivePanelClass(isDark, 'overflow-hidden')}>
            <div className={cx('flex flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between', isDark ? 'border-white/10' : 'border-brand/10')}>
              <div>
                <p className={cx('text-xs font-semibold uppercase tracking-[0.12em]', isDark ? 'text-white/40' : 'text-brand/40')}>
                  Biblioteca de dados
                </p>
                <h2 className="mt-0.5 text-base font-semibold">Atributos do lead</h2>
              </div>
              <div className="flex flex-wrap gap-2">
                {typeFilter !== 'all' && (
                  <span className={agentivePillClass(isDark)}>
                    tipo:{getFieldTypeLabel(typeFilter)}
                  </span>
                )}
                {statusFilter !== 'all' && (
                  <span className={agentivePillClass(isDark)}>
                    status:{STATUS_FILTERS.find(status => status.id === statusFilter)?.label}
                  </span>
                )}
              </div>
            </div>

            {isLoading ? (
              <div className="flex min-h-[340px] flex-col items-center justify-center gap-3 p-8 text-center" role="status" aria-live="polite">
                <Loader2 className={cx('h-8 w-8 animate-spin', isDark ? 'text-white/60' : 'text-brand/60')} />
                <div>
                  <p className="text-sm font-semibold">Carregando campos</p>
                  <p className={cx('mt-1 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>Sincronizando atributos da empresa.</p>
                </div>
              </div>
            ) : sortedFields.length === 0 ? (
              <div className="p-4">
                <AgentiveEmptyState
                  icon={ClipboardCheck}
                  title="Nenhum campo personalizado"
                  description="Crie o primeiro atributo para padronizar informações usadas no CRM e nas automações."
                  action={(
                    <button
                      type="button"
                      onClick={handleCreateField}
                      className={agentivePrimaryButtonClass()}
                    >
                      <Plus className="h-4 w-4" />
                      Criar campo
                    </button>
                  )}
                />
              </div>
            ) : filteredFields.length === 0 ? (
              <div className="p-4">
                <AgentiveEmptyState
                  icon={Search}
                  title="Nenhum campo corresponde aos filtros"
                  description="Ajuste a busca, tipo ou status para encontrar o atributo desejado."
                  action={(
                    <button
                      type="button"
                      onClick={resetFilters}
                      className={agentiveSecondaryButtonClass(isDark)}
                    >
                      <X className="h-4 w-4" />
                      Limpar filtros
                    </button>
                  )}
                />
              </div>
            ) : (
              <>
                <div className="hidden overflow-x-auto lg:block">
                  <table className="min-w-full text-sm" role="table" aria-label="Lista de campos personalizados">
                    <thead className={cx('border-b text-left text-[11px] font-semibold uppercase tracking-[0.1em]', isDark ? 'border-white/10 text-white/40' : 'border-brand/10 text-brand/40')}>
                      <tr>
                        <th className="min-w-[280px] px-4 py-3" scope="col">Campo</th>
                        <th className="min-w-[160px] px-4 py-3" scope="col">Tipo</th>
                        <th className="min-w-[220px] px-4 py-3" scope="col">Regras</th>
                        <th className="min-w-[160px] px-4 py-3" scope="col">Status</th>
                        <th className="w-28 px-4 py-3 text-right" scope="col">Ações</th>
                      </tr>
                    </thead>
                    <tbody className={cx('divide-y', isDark ? 'divide-white/10' : 'divide-brand/10')}>
                      {filteredFields.map(field => {
                        const meta = getFieldTypeMeta(field.field_type);
                        const TypeIcon = meta.icon;
                        const rules = getValidationRules(field);
                        const isSelected = selectedField?.id === field.id;

                        return (
                          <tr
                            key={field.id}
                            className={cx(
                              'group cursor-pointer transition-colors',
                              isSelected
                                ? isDark ? 'bg-white/[0.08]' : 'bg-brand-canvas'
                                : isDark ? 'hover:bg-white/[0.04]' : 'hover:bg-brand-canvas/70'
                            )}
                            onClick={() => setSelectedFieldId(field.id)}
                          >
                            <td className="px-4 py-3">
                              <div className="flex min-w-0 items-center gap-3">
                                {renderFieldIcon(field, isSelected)}
                                <div className="min-w-0">
                                  <p className="truncate font-semibold">{field.field_name}</p>
                                  <p className={cx('mt-1 flex items-center gap-1 truncate font-mono text-[11px]', isDark ? 'text-white/40' : 'text-brand/40')}>
                                    <KeyRound className="h-3 w-3 shrink-0" />
                                    {field.field_key}
                                  </p>
                                </div>
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <span className={cx('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1', isDark ? meta.toneDark : meta.tone)}>
                                <TypeIcon className="h-3.5 w-3.5" />
                                {meta.label}
                              </span>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex max-w-[260px] flex-wrap gap-1.5">
                                {rules.length > 0 ? rules.slice(0, 3).map(rule => (
                                  <span key={rule} className={agentivePillClass(isDark, false, 'px-2 py-0.5 text-[11px]')}>
                                    {rule}
                                  </span>
                                )) : (
                                  <span className={cx('text-xs', isDark ? 'text-white/40' : 'text-brand/40')}>Sem regra extra</span>
                                )}
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              {renderStatusPills(field)}
                            </td>
                            <td className="px-4 py-3">
                              {renderFieldActions(field)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <div className="space-y-3 p-3 lg:hidden">
                  {filteredFields.map(field => {
                    const meta = getFieldTypeMeta(field.field_type);
                    const TypeIcon = meta.icon;
                    const rules = getValidationRules(field);
                    const isSelected = selectedField?.id === field.id;

                    return (
                      <article
                        key={field.id}
                        className={cx(
                          'rounded-2xl border p-3 transition-colors',
                          isSelected
                            ? isDark ? 'border-white/20 bg-white/[0.08]' : 'border-brand/15 bg-brand-canvas'
                            : isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-white'
                        )}
                        onClick={() => setSelectedFieldId(field.id)}
                      >
                        <div className="flex items-start gap-3">
                          {renderFieldIcon(field, isSelected)}
                          <div className="min-w-0 flex-1">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <h3 className="truncate text-sm font-semibold">{field.field_name}</h3>
                                <p className={cx('mt-1 flex items-center gap-1 truncate font-mono text-[11px]', isDark ? 'text-white/40' : 'text-brand/40')}>
                                  <KeyRound className="h-3 w-3 shrink-0" />
                                  {field.field_key}
                                </p>
                              </div>
                              {renderFieldActions(field)}
                            </div>

                            <div className="mt-3 flex flex-wrap gap-2">
                              <span className={cx('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1', isDark ? meta.toneDark : meta.tone)}>
                                <TypeIcon className="h-3.5 w-3.5" />
                                {meta.label}
                              </span>
                              {renderStatusPills(field)}
                            </div>

                            {rules.length > 0 && (
                              <div className="mt-3 flex flex-wrap gap-1.5">
                                {rules.slice(0, 3).map(rule => (
                                  <span key={rule} className={agentivePillClass(isDark, false, 'px-2 py-0.5 text-[11px]')}>
                                    {rule}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </>
            )}
          </section>

          <aside className={agentivePanelClass(isDark, 'h-fit overflow-hidden xl:sticky xl:top-4')}>
            <div className={cx('border-b p-4', isDark ? 'border-white/10' : 'border-brand/10')}>
              <p className={cx('text-xs font-semibold uppercase tracking-[0.12em]', isDark ? 'text-white/40' : 'text-brand/40')}>
                Prévia
              </p>
              <h2 className="mt-0.5 text-base font-semibold">Como o CRM vai receber</h2>
            </div>

            {selectedField ? (
              <div className="space-y-4 p-4">
                <div className={cx('rounded-2xl border p-4', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
                  <div className="flex items-start gap-3">
                    {renderFieldIcon(selectedField, true)}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold">{selectedField.field_name}</p>
                      <p className={cx('mt-1 text-xs', isDark ? 'text-white/50' : 'text-brand/50')}>
                        {getFieldTypeMeta(selectedField.field_type).description}
                      </p>
                    </div>
                  </div>

                  <div className="mt-4 space-y-2">
                    <label className={cx('block text-[11px] font-semibold uppercase tracking-[0.1em]', isDark ? 'text-white/40' : 'text-brand/40')}>
                      Exemplo no cadastro
                    </label>
                    <div className={cx('rounded-xl border px-3 py-2.5 text-sm', isDark ? 'border-white/10 bg-brand text-white/45' : 'border-brand/10 bg-white text-brand/45')}>
                      {selectedField.field_type === 'select'
                        ? `${getSelectOptionsCount(selectedField)} opção${getSelectOptionsCount(selectedField) === 1 ? '' : 'ões'} configurada${getSelectOptionsCount(selectedField) === 1 ? '' : 's'}`
                        : `Preencher ${getFieldTypeMeta(selectedField.field_type).label.toLowerCase()}`}
                    </div>
                  </div>
                </div>

                <div className="space-y-2">
                  <p className={cx('text-xs font-semibold uppercase tracking-[0.12em]', isDark ? 'text-white/40' : 'text-brand/40')}>
                    Regras aplicadas
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {getValidationRules(selectedField).length > 0 ? getValidationRules(selectedField).map(rule => (
                      <span key={rule} className={agentivePillClass(isDark)}>
                        {rule}
                      </span>
                    )) : (
                      <span className={cx('text-sm', isDark ? 'text-white/45' : 'text-brand/45')}>Sem regra extra.</span>
                    )}
                  </div>
                </div>

                <div className={cx('rounded-2xl border p-4 text-sm', isDark ? 'border-white/10 bg-white/[0.04] text-white/65' : 'border-brand/10 bg-white text-brand/65')}>
                  <div className="mb-2 flex items-center gap-2 font-semibold">
                    <KeyRound className="h-4 w-4" />
                    Chave técnica
                  </div>
                  <code className={cx('break-all rounded-lg px-2 py-1 text-xs', isDark ? 'bg-white/10 text-white/75' : 'bg-brand-canvas text-brand/70')}>
                    {selectedField.field_key}
                  </code>
                </div>
              </div>
            ) : (
              <div className="p-4">
                <AgentiveEmptyState
                  icon={ClipboardCheck}
                  title="Selecione um campo"
                  description="A prévia mostra tipo, chave e regras do atributo escolhido."
                />
              </div>
            )}
          </aside>
        </div>

        {isFormOpen && (
          <div
            className="fixed inset-0 z-[9999] flex items-center justify-center p-4 sm:p-6"
            role="dialog"
            aria-modal="true"
            aria-labelledby="custom-field-modal-title"
            aria-describedby="custom-field-modal-description"
          >
            <button
              type="button"
              className="fixed inset-0 cursor-default bg-brand/60 backdrop-blur-sm"
              onClick={() => {
                setIsFormOpen(false);
                setEditingField(null);
              }}
              aria-label="Fechar modal"
            />
            <div className={agentivePanelClass(isDark, 'relative z-[10000] flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden shadow-[0_24px_70px_rgba(2,3,35,0.28)]')}>
              <div className={cx('flex items-start justify-between gap-4 border-b p-5', isDark ? 'border-white/10' : 'border-brand/10')}>
                <div className="flex min-w-0 items-start gap-3">
                  <span className={cx('grid h-11 w-11 shrink-0 place-items-center rounded-xl', isDark ? 'bg-white/10 text-white' : 'bg-brand text-white')}>
                    <ClipboardCheck className="h-5 w-5" />
                  </span>
                  <div className="min-w-0">
                    <h3
                      id="custom-field-modal-title"
                      className="text-lg font-semibold leading-tight"
                    >
                      {editingField ? 'Editar campo personalizado' : 'Novo campo personalizado'}
                    </h3>
                    <p
                      id="custom-field-modal-description"
                      className={cx('mt-1 text-sm', isDark ? 'text-white/55' : 'text-brand/55')}
                    >
                      Defina o formato, obrigatoriedade e regras do dado que será salvo no lead.
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setIsFormOpen(false);
                    setEditingField(null);
                  }}
                  className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-10 min-w-10')}
                  aria-label="Fechar modal"
                  title="Fechar"
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
              <div className="min-h-0 overflow-y-auto p-5" role="form" aria-label="Formulário de campo personalizado">
                <LeadCustomFieldForm
                  field={editingField}
                  onSave={handleSaveField}
                  onCancel={() => {
                    setIsFormOpen(false);
                    setEditingField(null);
                  }}
                  isDark={isDark}
                />
              </div>
            </div>
          </div>
        )}

        <ConfirmDeleteModal
          isOpen={Boolean(fieldToDelete)}
          onClose={() => setFieldToDelete(null)}
          onConfirm={confirmDeleteField}
          isLoading={fieldToDelete ? actionLoading[`delete-${fieldToDelete.id}`] : false}
          title="Excluir campo personalizado?"
          message="Os novos cadastros deixam de usar este campo. Dados já salvos podem ficar indisponíveis nas telas que dependem dele."
          confirmText="Excluir campo"
        >
          <span className={isDark ? 'text-white/80' : 'text-brand/70'}>
            Campo selecionado: <strong>{fieldToDelete?.field_name}</strong>
          </span>
        </ConfirmDeleteModal>
      </div>
    </div>
  );
};

export default LeadCustomFieldsConfig;
