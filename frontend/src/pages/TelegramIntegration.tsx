import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, CheckCircle2, ExternalLink, Loader2, LockKeyhole, RefreshCw, Send, Trash2, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { toast } from 'react-toastify';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentivePageHeader,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import ConfirmDeleteModal from '../components/ConfirmDeleteModal.tsx';
import TelegramIcon from '../components/icons/TelegramIcon.tsx';
import {
  deleteTelegramIntegration,
  getTelegramIntegration,
  testTelegramIntegration,
  type TelegramIntegration as TelegramIntegrationData,
  updateTelegramIntegration,
} from '../services/api.ts';
import { branding } from '../config/branding.ts';

const BOTFATHER_URL = 'https://t.me/BotFather';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

const TelegramIntegration: React.FC = () => {
  const { isDark } = useTheme();
  const [integration, setIntegration] = useState<TelegramIntegrationData | null>(null);
  const [botToken, setBotToken] = useState('');
  const [defaultChatId, setDefaultChatId] = useState('');
  const [defaultChatTitle, setDefaultChatTitle] = useState('');
  const [testMessage, setTestMessage] = useState(`Teste de integração Telegram - ${branding.appName}`);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [editingToken, setEditingToken] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const isConnected = Boolean(integration?.configured);
  const statusLabel = useMemo(() => {
    if (!integration?.configured) return 'Não conectado';
    if (integration.status === 'error') return 'Atenção';
    return 'Conectado';
  }, [integration]);

  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';

  const loadIntegration = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getTelegramIntegration();
      setIntegration(data);
      setDefaultChatId(data.default_chat_id || '');
      setDefaultChatTitle(data.default_chat_title || '');
      setBotToken('');
      setEditingToken(false);
    } catch (error: any) {
      toast.error(error.message || 'Erro ao carregar integração Telegram.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadIntegration();
  }, [loadIntegration]);

  const handleSave = async () => {
    const trimmedToken = botToken.trim();
    const requiresToken = !isConnected || editingToken;

    if (requiresToken && !trimmedToken) {
      toast.error(isConnected ? 'Informe o novo token do bot Telegram.' : 'Informe o token do bot Telegram.');
      return;
    }

    setSaving(true);
    try {
      const data = await updateTelegramIntegration({
        bot_token: requiresToken ? trimmedToken : undefined,
        default_chat_id: defaultChatId.trim(),
        default_chat_title: defaultChatTitle.trim(),
      });
      setIntegration(data);
      setBotToken('');
      setEditingToken(false);
      toast.success('Telegram conectado para esta empresa.');
    } catch (error: any) {
      toast.error(error.message || 'Erro ao salvar integração Telegram.');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    const chatId = defaultChatId.trim() || integration?.default_chat_id || '';
    if (!chatId) {
      toast.error('Informe o chat ID padrão para testar.');
      return;
    }

    setTesting(true);
    try {
      await testTelegramIntegration({
        chat_id: chatId,
        message: testMessage.trim() || `Teste de integração Telegram - ${branding.appName}`,
      });
      toast.success('Mensagem de teste enviada.');
      await loadIntegration();
    } catch (error: any) {
      toast.error(error.message || 'Erro ao testar Telegram.');
    } finally {
      setTesting(false);
    }
  };

  const handleDelete = async () => {
    setSaving(true);
    try {
      await deleteTelegramIntegration();
      setIntegration(null);
      setBotToken('');
      setEditingToken(false);
      setDefaultChatId('');
      setDefaultChatTitle('');
      setShowDeleteConfirm(false);
      toast.success('Telegram removido desta empresa.');
      await loadIntegration();
    } catch (error: any) {
      toast.error(error.message || 'Erro ao remover integração Telegram.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <main className={agentivePageClass(isDark, 'p-4 sm:p-6')}>
        <div className="mx-auto w-full max-w-screen-xl">
          <div className={agentivePanelClass(isDark, 'flex items-center justify-center gap-3 p-8')}>
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm font-medium">Carregando Telegram</span>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className={agentivePageClass(isDark, 'p-4 sm:p-6')}>
      <div className="mx-auto flex w-full max-w-screen-xl flex-col gap-4">
        <AgentivePageHeader
          icon={Send}
          title="Telegram"
          description="Bot e chat padrão usados pelos nodes Msg Telegram nos fluxos desta empresa."
          badges={<span className={agentivePillClass(isDark, isConnected)}>{statusLabel}</span>}
          actions={
            <>
              <Link to="/integrations" className={agentiveSecondaryButtonClass(isDark)}>
                <ArrowLeft className="h-4 w-4" />
                Integrações
              </Link>
              <a href={BOTFATHER_URL} target="_blank" rel="noreferrer" className={agentiveSecondaryButtonClass(isDark)}>
                <ExternalLink className="h-4 w-4" />
                BotFather
              </a>
            </>
          }
        />

        {integration?.last_error && (
          <AgentiveAlert variant="warning" title="Última falha do Telegram">
            {integration.last_error}
          </AgentiveAlert>
        )}

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <section className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
            <div className="mb-5 flex items-start gap-3">
              <div className={cx('grid h-11 w-11 shrink-0 place-items-center rounded-xl', isDark ? 'bg-white text-brand' : 'bg-sky-50 text-sky-600')}>
                <TelegramIcon className="h-8 w-8" />
              </div>
              <div>
                <h2 className="text-base font-semibold">Configuração do bot</h2>
                <p className={cx('mt-1 text-sm leading-relaxed', mutedClass)}>
                  O token é validado no Telegram e armazenado criptografado.
                </p>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="md:col-span-2">
                <label className={agentiveLabelClass(isDark)} htmlFor="telegram-token">
                  Token do bot
                </label>
                {isConnected && !editingToken ? (
                  <div className={cx('flex flex-col gap-3 rounded-xl border px-3 py-3 sm:flex-row sm:items-center sm:justify-between', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas')}>
                    <div className="flex min-w-0 items-center gap-3">
                      <div className={cx('grid h-9 w-9 shrink-0 place-items-center rounded-xl', isDark ? 'bg-white/10 text-white' : 'bg-white text-brand')}>
                        <LockKeyhole className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold">Token salvo e protegido</p>
                        <p className={cx('mt-0.5 text-xs', mutedClass)}>
                          O valor fica criptografado no banco. Edite apenas se quiser trocar o bot.
                        </p>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setEditingToken(true)}
                      className={agentiveSecondaryButtonClass(isDark, 'shrink-0')}
                    >
                      Editar token
                    </button>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <input
                      id="telegram-token"
                      type="password"
                      value={botToken}
                      onChange={(event) => setBotToken(event.target.value)}
                      placeholder={isConnected ? 'Cole o novo token do BotFather' : 'Cole o token gerado no BotFather'}
                      className={agentiveInputClass(isDark)}
                      autoComplete="off"
                    />
                    {isConnected && (
                      <button
                        type="button"
                        onClick={() => {
                          setBotToken('');
                          setEditingToken(false);
                        }}
                        className={agentiveSecondaryButtonClass(isDark, 'shrink-0')}
                      >
                        <X className="h-4 w-4" />
                        Cancelar
                      </button>
                    )}
                  </div>
                )}
              </div>

              <div>
                <label className={agentiveLabelClass(isDark)} htmlFor="telegram-chat-id">
                  Chat ID padrão
                </label>
                <input
                  id="telegram-chat-id"
                  type="text"
                  value={defaultChatId}
                  onChange={(event) => setDefaultChatId(event.target.value)}
                  placeholder="-1001234567890 ou @canal"
                  className={agentiveInputClass(isDark)}
                />
              </div>

              <div>
                <label className={agentiveLabelClass(isDark)} htmlFor="telegram-chat-title">
                  Nome interno do chat
                </label>
                <input
                  id="telegram-chat-title"
                  type="text"
                  value={defaultChatTitle}
                  onChange={(event) => setDefaultChatTitle(event.target.value)}
                  placeholder="Ex: Alertas comerciais"
                  className={agentiveInputClass(isDark)}
                />
              </div>
            </div>

            <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-between">
              {isConnected && (
                <button
                  type="button"
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={saving}
                  className={agentiveSecondaryButtonClass(isDark, 'text-red-600 hover:text-red-700')}
                >
                  <Trash2 className="h-4 w-4" />
                  Remover Telegram
                </button>
              )}

              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className={agentivePrimaryButtonClass('sm:ml-auto')}
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                {saving ? 'Salvando' : 'Salvar configuração'}
              </button>
            </div>
          </section>

          <aside className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
            <div className="mb-4 flex items-center gap-2">
              <Send className="h-5 w-5" />
              <h2 className="text-base font-semibold">Teste rápido</h2>
            </div>
            <p className={cx('text-sm leading-relaxed', mutedClass)}>
              Usa o token salvo e o chat ID informado nesta tela.
            </p>

            <label className={agentiveLabelClass(isDark, 'mt-4')} htmlFor="telegram-test-message">
              Mensagem
            </label>
            <textarea
              id="telegram-test-message"
              value={testMessage}
              onChange={(event) => setTestMessage(event.target.value)}
              className={agentiveInputClass(isDark, 'min-h-28 resize-y')}
            />

            <button
              type="button"
              onClick={handleTest}
              disabled={testing || !isConnected}
              className={agentivePrimaryButtonClass('mt-4 w-full')}
            >
              {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              {testing ? 'Enviando' : 'Enviar teste'}
            </button>
          </aside>
        </div>
      </div>

      <ConfirmDeleteModal
        isOpen={showDeleteConfirm}
        onClose={() => setShowDeleteConfirm(false)}
        onConfirm={handleDelete}
        isLoading={saving}
        title="Remover Telegram?"
        message="Os nodes Msg Telegram desta empresa deixarão de enviar mensagens até uma nova configuração ser salva."
        confirmText="Remover"
        cancelText="Manter"
      />
    </main>
  );
};

export default TelegramIntegration;
