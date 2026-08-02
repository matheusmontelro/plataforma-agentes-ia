import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  KeyRound,
  Loader2,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
  AgentivePageHeader,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import BrowserDateTime from '../components/BrowserDateTime.tsx';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  deleteAIProvider,
  FALLBACK_AI_MODELS,
  getAIProvider,
  type AIProviderConfig,
  updateAIProvider,
  validateAIProvider,
} from '../services/aiProviderApi.ts';
import { branding } from '../config/branding.ts';

type Feedback = {
  message: string;
  type: 'error' | 'success';
};

const EMPTY_PROVIDER: AIProviderConfig = {
  configured: false,
  last_error: null,
  last_validated_at: null,
  models: [],
  status: 'not_configured',
};

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

const getErrorMessage = (error: unknown, fallback: string) => {
  if (!error || typeof error !== 'object') return fallback;
  const candidate = error as {
    message?: string;
    response?: { data?: { detail?: string | { message?: string } } };
  };
  const detail = candidate.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message;
  return candidate.message || fallback;
};

const getStatusLabel = (provider: AIProviderConfig | null) => {
  if (!provider?.configured) return 'Não configurado';
  if (['valid', 'validated', 'active'].includes(provider.status)) return 'Validado';
  if (['invalid', 'error'].includes(provider.status)) return 'Atenção';
  return 'Configurado';
};

const AIProviderPage: React.FC = () => {
  const { isDark } = useTheme();
  const [provider, setProvider] = useState<AIProviderConfig | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [editingKey, setEditingKey] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false);

  const isConfigured = Boolean(provider?.configured);
  const isValidated = Boolean(
    provider?.configured && ['valid', 'validated', 'active'].includes(provider.status),
  );
  const modelOptions = useMemo(() => {
    const returnedModels = (provider?.models || [])
      .map((model) => String(model).trim())
      .filter(Boolean);
    if (returnedModels.length > 0) return Array.from(new Set(returnedModels));
    return isConfigured ? [] : [...FALLBACK_AI_MODELS];
  }, [isConfigured, provider?.models]);

  const loadProvider = useCallback(async () => {
    setLoading(true);
    setFeedback(null);
    try {
      const data = await getAIProvider();
      setProvider(data);
      setApiKey('');
      setEditingKey(false);
    } catch (error) {
      setFeedback({
        message: getErrorMessage(error, 'Não foi possível carregar o provedor de IA.'),
        type: 'error',
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProvider();
  }, [loadProvider]);

  const handleSave = async () => {
    const trimmedKey = apiKey.trim();
    if (!trimmedKey) {
      setFeedback({ message: 'Informe a chave de API da OpenAI.', type: 'error' });
      return;
    }

    setSaving(true);
    setFeedback(null);
    try {
      const data = await updateAIProvider({ api_key: trimmedKey });
      setProvider(data);
      setApiKey('');
      setEditingKey(false);
      setFeedback({
        message: 'Chave salva com segurança para esta empresa.',
        type: 'success',
      });
    } catch (error) {
      setFeedback({
        message: getErrorMessage(error, 'Não foi possível salvar a chave da OpenAI.'),
        type: 'error',
      });
    } finally {
      setSaving(false);
    }
  };

  const handleValidate = async () => {
    setValidating(true);
    setFeedback(null);
    try {
      const data = await validateAIProvider();
      setProvider(data);
      const validationSucceeded = ['valid', 'validated', 'active'].includes(data.status);
      setFeedback(validationSucceeded
        ? {
            message: 'Chave validada. O catálogo compatível foi atualizado.',
            type: 'success',
          }
        : {
            message: data.last_error || 'A chave não passou na validação da OpenAI.',
            type: 'error',
          });
    } catch (error) {
      setFeedback({
        message: getErrorMessage(error, 'Não foi possível validar a chave da OpenAI.'),
        type: 'error',
      });
    } finally {
      setValidating(false);
    }
  };

  const handleRemove = async () => {
    setRemoving(true);
    setFeedback(null);
    try {
      await deleteAIProvider();
      setProvider(EMPTY_PROVIDER);
      setApiKey('');
      setEditingKey(false);
      setShowRemoveConfirm(false);
      setFeedback({
        message: 'Chave removida desta empresa.',
        type: 'success',
      });
    } catch (error) {
      setFeedback({
        message: getErrorMessage(error, 'Não foi possível remover a chave da OpenAI.'),
        type: 'error',
      });
    } finally {
      setRemoving(false);
    }
  };

  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';

  if (loading && !provider) {
    return (
      <main className={agentivePageClass(isDark, 'p-4 sm:p-6')}>
        <div className="mx-auto w-full max-w-screen-xl">
          <div className={agentivePanelClass(isDark, 'flex items-center justify-center gap-3 p-8')}>
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm font-medium">Carregando provedor de IA</span>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className={agentivePageClass(isDark, 'p-4 sm:p-6')}>
      <div className="mx-auto flex w-full max-w-screen-xl flex-col gap-4">
        <AgentivePageHeader
          icon={KeyRound}
          title="Provedor de IA"
          description="Use a chave OpenAI da sua empresa para executar os agentes com credencial própria."
          badges={(
            <span className={agentivePillClass(isDark, isValidated)}>
              {getStatusLabel(provider)}
            </span>
          )}
          actions={(
            <button
              type="button"
              onClick={() => void loadProvider()}
              disabled={loading}
              className={agentiveSecondaryButtonClass(isDark)}
            >
              <RefreshCw className={cx('h-4 w-4', loading && 'animate-spin')} />
              Atualizar
            </button>
          )}
        />

        {feedback && (
          <AgentiveAlert
            variant={feedback.type}
            title={feedback.type === 'success' ? 'Atualização concluída' : 'Não foi possível concluir'}
            onClose={() => setFeedback(null)}
          >
            {feedback.message}
          </AgentiveAlert>
        )}

        {provider?.last_error && (
          <AgentiveAlert variant="warning" title="Última validação não concluída">
            {provider.last_error}
          </AgentiveAlert>
        )}

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <section className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
            <div className="mb-5 flex items-start gap-3">
              <div className={cx(
                'grid h-11 w-11 shrink-0 place-items-center rounded-xl',
                isDark ? 'bg-white/10 text-white' : 'bg-brand-canvas text-brand',
              )}>
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-base font-semibold">Chave da OpenAI</h2>
                <p className={cx('mt-1 text-sm leading-relaxed', mutedClass)}>
                  A chave é enviada somente ao backend, armazenada criptografada e nunca volta para esta tela.
                </p>
              </div>
            </div>

            <label className={agentiveLabelClass(isDark)} htmlFor="openai-api-key">
              Chave de API
            </label>

            {isConfigured && !editingKey ? (
              <div className={cx(
                'flex flex-col gap-3 rounded-xl border px-3 py-3 sm:flex-row sm:items-center sm:justify-between',
                isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas',
              )}>
                <div className="flex min-w-0 items-center gap-3">
                  <div className={cx(
                    'grid h-9 w-9 shrink-0 place-items-center rounded-xl',
                    isDark ? 'bg-white/10 text-white' : 'bg-white text-brand',
                  )}>
                    <LockKeyhole className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">Chave salva e protegida</p>
                    <p className={cx('mt-0.5 text-xs', mutedClass)}>
                      O valor não pode ser consultado. Substitua somente quando precisar rotacionar a chave.
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setEditingKey(true)}
                  className={agentiveSecondaryButtonClass(isDark, 'shrink-0')}
                >
                  Substituir chave
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  id="openai-api-key"
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={isConfigured ? 'Cole a nova chave OpenAI' : 'Cole a chave OpenAI desta empresa'}
                  className={agentiveInputClass(isDark)}
                  autoComplete="new-password"
                  spellCheck={false}
                  disabled={saving}
                />
                {isConfigured && (
                  <button
                    type="button"
                    onClick={() => {
                      setApiKey('');
                      setEditingKey(false);
                    }}
                    disabled={saving}
                    className={agentiveSecondaryButtonClass(isDark, 'shrink-0')}
                  >
                    <X className="h-4 w-4" />
                    Cancelar
                  </button>
                )}
              </div>
            )}

            <p className={cx('mt-3 text-xs leading-relaxed', mutedClass)}>
              Cada empresa usa sua própria credencial. {branding.appName} não utiliza uma chave compartilhada como fallback.
            </p>

            <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-between">
              {isConfigured && (
                <button
                  type="button"
                  onClick={() => setShowRemoveConfirm(true)}
                  disabled={saving || removing}
                  className={agentiveSecondaryButtonClass(isDark, 'text-red-600 hover:text-red-700')}
                >
                  <Trash2 className="h-4 w-4" />
                  Remover chave
                </button>
              )}

              {(!isConfigured || editingKey) && (
                <button
                  type="button"
                  onClick={() => void handleSave()}
                  disabled={saving || !apiKey.trim()}
                  className={agentivePrimaryButtonClass('sm:ml-auto')}
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  {saving ? 'Salvando' : 'Salvar chave'}
                </button>
              )}
            </div>
          </section>

          <aside className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
            <div className="flex items-center gap-2">
              <RefreshCw className="h-5 w-5" />
              <h2 className="text-base font-semibold">Validação e modelos</h2>
            </div>
            <p className={cx('mt-2 text-sm leading-relaxed', mutedClass)}>
              Confirme o acesso da chave e consulte os modelos liberados no projeto OpenAI.
            </p>

            <div className={cx(
              'mt-4 rounded-xl border p-3',
              isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas',
            )}>
              <p className={cx('text-xs font-medium', mutedClass)}>Última validação</p>
              <p className="mt-1 text-sm font-semibold">
                <BrowserDateTime value={provider?.last_validated_at} fallback="Ainda não validada" />
              </p>
            </div>

            <button
              type="button"
              onClick={() => void handleValidate()}
              disabled={validating || !isConfigured}
              className={agentivePrimaryButtonClass('mt-3 w-full')}
            >
              {validating ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
              {validating ? 'Validando' : 'Validar chave'}
            </button>

            <div className="mt-5">
              <p className={agentiveLabelClass(isDark, 'mb-2')}>
                {isConfigured ? 'Modelos disponíveis' : 'Modelos suportados'}
              </p>
              {modelOptions.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {modelOptions.map((model) => (
                    <span key={model} className={agentivePillClass(isDark)}>
                      {model}
                    </span>
                  ))}
                </div>
              ) : (
                <p className={cx('rounded-xl border border-dashed p-3 text-xs leading-relaxed', isDark ? 'border-white/10 text-white/50' : 'border-brand/10 text-brand/50')}>
                  Valide a chave para carregar o catálogo permitido para esta empresa.
                </p>
              )}
            </div>
          </aside>
        </div>
      </div>

      <AgentiveConfirmModal
        cancelText="Manter chave"
        confirmText="Remover"
        isLoading={removing}
        isOpen={showRemoveConfirm}
        message="Os agentes desta empresa deixarão de responder até uma nova chave válida ser configurada."
        onClose={() => {
          if (!removing) setShowRemoveConfirm(false);
        }}
        onConfirm={() => void handleRemove()}
        title="Remover chave OpenAI?"
        variant="danger"
      />
    </main>
  );
};

export default AIProviderPage;
