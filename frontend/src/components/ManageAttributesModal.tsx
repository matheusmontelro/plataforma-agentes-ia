import React, { useEffect, useState } from 'react';
import {
  Check,
  Edit2,
  FileText,
  Loader2,
  Plus,
  Save,
  Settings,
  Trash2,
  X,
} from 'lucide-react';
import { crmApi, LeadCustomField } from '../services/crmApi';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
} from './AgentiveUI.tsx';
import {
  CrmModernEmptyState,
  crmModernBadgeClass,
  crmModernIconButtonClass,
  crmModernInputClass,
  crmModernLabelClass,
  crmModernPrimaryButtonClass,
  crmModernSecondaryButtonClass,
} from './crm/CRMModern/CRMModernUI.tsx';
import './ManageAttributesModal.css';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

interface ManageAttributesModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAttributesChanged: () => void;
}

const FIELD_TYPES = [
  { value: 'text', label: 'Texto' },
  { value: 'number', label: 'Número' },
  { value: 'date', label: 'Data' },
  { value: 'select', label: 'Seleção' },
  { value: 'textarea', label: 'Texto longo' },
];

export default function ManageAttributesModal({ isOpen, onClose, onAttributesChanged }: ManageAttributesModalProps) {
  const { isDark } = useTheme();
  const [fields, setFields] = useState<LeadCustomField[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<LeadCustomField | null>(null);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [newField, setNewField] = useState<Partial<LeadCustomField>>({
    field_name: '',
    field_key: '',
    field_type: 'text',
    is_active: true,
    display_order: 0,
  });
  const [editForm, setEditForm] = useState<Partial<LeadCustomField>>({});

  const mutedTextClass = 'crm-modern-muted';

  const fetchFields = async () => {
    setIsLoading(true);
    setFeedback(null);
    try {
      const data = await crmApi.getCustomFields();
      setFields(data.sort((a, b) => a.display_order - b.display_order));
    } catch (error) {
      console.error('Erro ao carregar atributos personalizados:', error);
      setFeedback({ type: 'error', message: 'Não foi possível carregar os campos.' });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) fetchFields();
  }, [isOpen]);

  const resetCreateForm = () => {
    setIsCreating(false);
    setNewField({
      field_name: '',
      field_key: '',
      field_type: 'text',
      is_active: true,
      display_order: 0,
    });
  };

  const handleCreate = async () => {
    if (!newField.field_name) return;

    try {
      const fieldData = { ...newField };
      if (!fieldData.field_key) {
        fieldData.field_key = fieldData.field_name
          .toLowerCase()
          .replace(/[^a-z0-9]/g, '_')
          .replace(/_+/g, '_')
          .replace(/^_|_$/g, '');
      }

      if (!fieldData.display_order) {
        fieldData.display_order = fields.length + 1;
      }

      await crmApi.createCustomField(fieldData);
      await fetchFields();
      resetCreateForm();
      setFeedback({ type: 'success', message: 'Campo criado.' });
      onAttributesChanged();
    } catch (error) {
      console.error('Erro ao criar atributo:', error);
      setFeedback({ type: 'error', message: 'Erro ao criar campo.' });
    }
  };

  const startEditing = (field: LeadCustomField) => {
    setEditingId(field.id);
    setEditForm({ ...field });
    setFeedback(null);
  };

  const handleUpdate = async () => {
    if (!editingId) return;

    try {
      await crmApi.updateCustomField(editingId, editForm);
      await fetchFields();
      setEditingId(null);
      setFeedback({ type: 'success', message: 'Campo atualizado.' });
      onAttributesChanged();
    } catch (error) {
      console.error('Erro ao atualizar atributo:', error);
      setFeedback({ type: 'error', message: 'Erro ao atualizar campo.' });
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;

    try {
      await crmApi.deleteCustomField(deleteTarget.id);
      await fetchFields();
      setDeleteTarget(null);
      setFeedback({ type: 'success', message: 'Campo removido.' });
      onAttributesChanged();
    } catch (error) {
      console.error('Erro ao remover atributo:', error);
      setFeedback({ type: 'error', message: 'Erro ao remover campo.' });
    }
  };

  if (!isOpen) return null;

  return (
    <div className={cx('crm-work-modal fixed inset-0 z-[90] flex items-center justify-center p-4', isDark && 'crm-work-modal--dark')}>
      <div className="crm-modern-modal-root absolute inset-0" onClick={onClose} />

      <section className="crm-modern-modal crm-attributes-modal relative z-[91] flex max-h-[92vh] w-full flex-col overflow-hidden">
        <header className="crm-modern-modal__header flex items-start justify-between gap-4">
          <div className="crm-attributes-modal__heading">
            <span className="crm-attributes-modal__heading-icon" aria-hidden="true">
              <Settings className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p className="crm-attributes-modal__eyebrow">Configuração do CRM</p>
              <h2 className="text-base font-semibold leading-tight">Campos personalizados</h2>
              <p className={cx('mt-1 text-xs leading-relaxed', mutedTextClass)}>
                Organize as informações extras exibidas nos perfis dos leads.
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} className={crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon')} aria-label="Fechar campos personalizados" title="Fechar">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="crm-modern-modal__body min-h-0 flex-1 overflow-y-auto custom-scrollbar">
          <div className="crm-attributes-modal__body">
            {feedback && (
              <AgentiveAlert className="crm-modern-alert" title={feedback.type === 'success' ? 'Atualizado' : 'Erro'} variant={feedback.type} onClose={() => setFeedback(null)}>
                {feedback.message}
              </AgentiveAlert>
            )}

            <div className="crm-attributes-toolbar">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold">Campos cadastrados</h3>
                  <span className={crmModernBadgeClass(isDark, false, 'tabular-nums')}>{fields.length}</span>
                </div>
                <p className={cx('mt-1 text-xs', mutedTextClass)}>Esses campos ficam disponíveis em todos os perfis do CRM.</p>
              </div>
              {!isCreating && (
                <button type="button" onClick={() => setIsCreating(true)} className={crmModernPrimaryButtonClass('shrink-0')}>
                  <Plus className="h-4 w-4" />
                  Novo campo
                </button>
              )}
            </div>

            {isCreating && (
              <section className="crm-attributes-composer" aria-label="Novo campo personalizado">
                <div className="crm-attributes-composer__header">
                  <div>
                    <h3 className="text-sm font-semibold">Novo campo</h3>
                    <p className={cx('mt-1 text-xs', mutedTextClass)}>Defina um nome legível e o formato do valor.</p>
                  </div>
                  <button type="button" onClick={resetCreateForm} className={crmModernIconButtonClass(isDark, 'neutral', 'crm-action-icon')} aria-label="Fechar criação de campo" title="Fechar">
                    <X className="h-4 w-4" />
                  </button>
                </div>

                <div className="crm-attributes-composer__body">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                      <label className={crmModernLabelClass(isDark)}>Nome</label>
                      <input
                        type="text"
                        placeholder="Ex: Especialidade"
                        className={crmModernInputClass(isDark, 'p-3')}
                        value={newField.field_name}
                        onChange={(event) => setNewField({ ...newField, field_name: event.target.value })}
                      />
                    </div>
                    <div>
                      <label className={crmModernLabelClass(isDark)}>Tipo</label>
                      <select
                        className={crmModernInputClass(isDark, 'p-3')}
                        value={newField.field_type}
                        onChange={(event) => setNewField({ ...newField, field_type: event.target.value })}
                      >
                        {FIELD_TYPES.map(type => (
                          <option key={type.value} value={type.value}>{type.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div>
                    <label className={crmModernLabelClass(isDark)}>Chave opcional</label>
                    <input
                      type="text"
                      placeholder="especialidade"
                      className={crmModernInputClass(isDark, 'p-3 font-mono')}
                      value={newField.field_key}
                      onChange={(event) => setNewField({ ...newField, field_key: event.target.value })}
                    />
                    <p className={cx('mt-1.5 text-[10px]', mutedTextClass)}>Se ficar vazia, a chave será criada automaticamente.</p>
                  </div>
                </div>

                <div className="crm-attributes-composer__footer">
                  <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                    <button type="button" onClick={resetCreateForm} className={crmModernSecondaryButtonClass(isDark)}>
                      Cancelar
                    </button>
                    <button type="button" onClick={handleCreate} disabled={!newField.field_name} className={crmModernPrimaryButtonClass()}>
                      <Check className="h-4 w-4" />
                      Salvar campo
                    </button>
                  </div>
                </div>
              </section>
            )}

            <section className="crm-attributes-section" aria-label="Lista de campos personalizados">
              {isLoading ? (
                <div className="flex min-h-40 flex-col items-center justify-center gap-3 text-center">
                  <Loader2 className="h-5 w-5 animate-spin text-[var(--crm-modern-ink-muted)]" />
                  <p className={cx('text-sm', mutedTextClass)}>Carregando campos...</p>
                </div>
              ) : fields.length === 0 ? (
                <CrmModernEmptyState
                  icon={Settings}
                  title="Nenhum campo definido"
                  description="Crie o primeiro campo para personalizar os perfis dos leads."
                  action={!isCreating ? (
                    <button type="button" onClick={() => setIsCreating(true)} className={crmModernPrimaryButtonClass()}>
                      <Plus className="h-4 w-4" />
                      Novo campo
                    </button>
                  ) : undefined}
                />
              ) : (
                <div className="crm-attributes-list">
                  {fields.map(field => (
                    <article key={field.id} className="crm-attributes-item">
                      {editingId === field.id ? (
                        <div className="space-y-4">
                          <div className="grid gap-4 sm:grid-cols-2">
                            <div>
                              <label className={crmModernLabelClass(isDark, 'text-xs')}>Nome</label>
                              <input
                                type="text"
                                className={crmModernInputClass(isDark)}
                                value={editForm.field_name}
                                onChange={(event) => setEditForm({ ...editForm, field_name: event.target.value })}
                              />
                            </div>
                            <div>
                              <label className={crmModernLabelClass(isDark, 'text-xs')}>Tipo</label>
                              <select
                                className={crmModernInputClass(isDark)}
                                value={editForm.field_type}
                                onChange={(event) => setEditForm({ ...editForm, field_type: event.target.value })}
                              >
                                {FIELD_TYPES.map(type => (
                                  <option key={type.value} value={type.value}>{type.label}</option>
                                ))}
                              </select>
                            </div>
                          </div>

                          <div className="crm-attributes-item__footer">
                            <p className={cx('font-mono text-xs', mutedTextClass)}>Chave: {field.field_key}</p>
                            <div className="flex flex-wrap items-center gap-2">
                              <button type="button" onClick={() => setEditingId(null)} className={crmModernSecondaryButtonClass(isDark, 'px-2.5 py-1.5 text-xs')}>
                                Cancelar
                              </button>
                              <button type="button" onClick={handleUpdate} className={crmModernPrimaryButtonClass('px-2.5 py-1.5 text-xs')}>
                                <Save className="h-3.5 w-3.5" />
                                Salvar
                              </button>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start justify-between gap-3">
                          <div className="crm-attributes-item__identity">
                            <span className="crm-attributes-item__icon" aria-hidden="true">
                              <FileText className="h-4 w-4" />
                            </span>
                            <div className="min-w-0">
                              <h4 className="truncate text-sm font-semibold">{field.field_name}</h4>
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <span className={crmModernBadgeClass(isDark, false, 'font-mono')}>
                                  {field.field_key}
                                </span>
                                <span className={crmModernBadgeClass(isDark)}>
                                  {field.field_type}
                                </span>
                              </div>
                            </div>
                          </div>

                          <div className="crm-attributes-item__actions">
                            <button type="button" onClick={() => startEditing(field)} className={crmModernIconButtonClass(isDark, 'primary', 'crm-action-icon')} aria-label={`Editar ${field.field_name}`} title="Editar campo">
                              <Edit2 className="h-4 w-4" />
                            </button>
                            <button type="button" onClick={() => setDeleteTarget(field)} className={crmModernIconButtonClass(isDark, 'danger', 'crm-action-icon')} aria-label={`Remover ${field.field_name}`} title="Remover campo">
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>
          </div>
        </div>
      </section>

      <AgentiveConfirmModal
        appearance="modern"
        cancelText="Cancelar"
        confirmText="Remover campo"
        isOpen={Boolean(deleteTarget)}
        message="Remover este campo também pode ocultar valores já preenchidos nos perfis de leads."
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title={`Remover ${deleteTarget?.field_name || 'campo'}?`}
        variant="danger"
      />
    </div>
  );
}
