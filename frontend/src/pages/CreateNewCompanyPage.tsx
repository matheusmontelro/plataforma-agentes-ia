import React, { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, Building2, Check, CheckCircle2, Copy, Loader2, Lock } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import { createNewCompanyAdmin } from '../services/api.ts';
import { customerBillingApi, type CustomerBillingDetail } from '../services/customerBillingApi.ts';

const WORKSPACE_OWNER_EMAIL_CONFLICT_MESSAGE = 'Use um e-mail diferente do seu para o cliente final.';

const normalizeEmail = (email: string) => email.trim().toLowerCase();

const NewCompanyAdminPage = () => {
  const { isDark } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const query = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const customerId = Number(query.get('customerId') || 0) || null;
  const customerName = query.get('customerName') || '';
  const returnTo = query.get('returnTo') || '/customers';
  const currentUserEmail = useMemo(() => normalizeEmail(localStorage.getItem('user_email') || ''), []);

  const [clientEmail, setClientEmail] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [companyCnpj, setCompanyCnpj] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [createdCompanyId, setCreatedCompanyId] = useState<number | null>(null);
  const [passwordSetupUrl, setPasswordSetupUrl] = useState('');
  const [passwordSetupUrlCopied, setPasswordSetupUrlCopied] = useState(false);
  const [passwordSetupCopyError, setPasswordSetupCopyError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [trialDays, setTrialDays] = useState('0');
  const [selectedCustomer, setSelectedCustomer] = useState<CustomerBillingDetail | null>(null);
  const [customerLoading, setCustomerLoading] = useState(Boolean(customerId));
  const [customerLoadError, setCustomerLoadError] = useState('');

  useEffect(() => {
    if (!customerId) {
      setCustomerLoading(false);
      setSelectedCustomer(null);
      setCustomerLoadError('');
      return;
    }

    let cancelled = false;
    setCustomerLoading(true);
    setCustomerLoadError('');

    customerBillingApi.getCustomer(customerId)
      .then((customer) => {
        if (cancelled) return;
        setSelectedCustomer(customer);
        setClientEmail((customer.email || '').trim());
        setCompanyName((current) => current || customer.nome || customerName);
        setCompanyCnpj((current) => current || formatDocument(customer.cpf_cnpj || ''));
      })
      .catch((err: any) => {
        if (!cancelled) {
          setCustomerLoadError(err.response?.data?.detail || err.message || 'Não foi possível carregar o cliente selecionado.');
        }
      })
      .finally(() => {
        if (!cancelled) setCustomerLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [customerId]);

  const formatDocument = (value: string) => {
    const digits = value.replace(/\D/g, '').substring(0, 14);
    if (digits.length <= 11) {
      return digits
        .replace(/^(\d{3})(\d)/, '$1.$2')
        .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
        .replace(/\.(\d{3})(\d)/, '.$1-$2')
        .substring(0, 14);
    }

    return digits
      .replace(/^(\d{2})(\d)/, '$1.$2')
      .replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
      .replace(/\.(\d{3})(\d)/, '.$1/$2')
      .replace(/(\d{4})(\d)/, '$1-$2')
      .substring(0, 18);
  };

  const validateEmail = (email: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

  const validateDocument = (document: string) => {
    const digits = document.replace(/\D/g, '');
    return digits.length === 11 || digits.length === 14;
  };

  const handleEmailChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setClientEmail(value);
    if (validateEmail(value)) setError('');
  };

  const handleCNPJChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setCompanyCnpj(formatDocument(e.target.value));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setCreatedCompanyId(null);
    setPasswordSetupUrl('');
    setPasswordSetupUrlCopied(false);
    setPasswordSetupCopyError('');

    if (customerId && customerLoading) {
      setError('Aguarde o carregamento dos dados do cliente.');
      return;
    }

    if (customerId && customerLoadError) {
      setError(customerLoadError);
      return;
    }

    if (customerId && !clientEmail.trim()) {
      setError('Edite o cliente e cadastre um e-mail antes de liberar o workspace.');
      return;
    }

    if (customerId && currentUserEmail && normalizeEmail(clientEmail) === currentUserEmail) {
      setError(WORKSPACE_OWNER_EMAIL_CONFLICT_MESSAGE);
      return;
    }

    if (!validateEmail(clientEmail)) {
      setError('Por favor, insira um email válido');
      return;
    }

    if (!validateDocument(companyCnpj)) {
      setError('Por favor, insira um CPF ou CNPJ válido');
      return;
    }

    setIsLoading(true);

    try {
      const cleanCNPJ = companyCnpj.replace(/\D/g, '');
      const data = await createNewCompanyAdmin(clientEmail, companyName, cleanCNPJ, customerId, Number(trialDays || 0));
      const trialMessage = data.trial_days
        ? ` Teste de ${data.trial_days} dias registrado${data.trial_ends_at ? ` ate ${new Date(data.trial_ends_at).toLocaleDateString('pt-BR')}` : ''}.`
        : '';
      const passwordSetupMessage = data.password_setup_email_sent
        ? ' E-mail para definição de senha enviado.'
        : data.client_created && data.password_setup_email_skipped
          ? data.password_setup_url
            ? ' O e-mail não foi enviado; use o link de definição de senha exibido abaixo.'
            : ' E-mail para definição de senha não enviado; verifique a configuração SMTP.'
          : '';
      setPasswordSetupUrl(
        !data.password_setup_email_sent && data.password_setup_url
          ? data.password_setup_url
          : ''
      );
      setSuccess(
        customerId
          ? `${data.message} Workspace vinculado ao cliente selecionado.${trialMessage}${passwordSetupMessage}`
          : data.message || 'Nova empresa criada com sucesso!'
      );
      setCreatedCompanyId(data.company_id);
      if (!customerId) setClientEmail('');
      setCompanyName('');
      setCompanyCnpj('');
      setTrialDays('0');
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Erro ao criar nova empresa!');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopyPasswordSetupUrl = async () => {
    if (!passwordSetupUrl) return;

    setPasswordSetupCopyError('');
    try {
      await navigator.clipboard.writeText(passwordSetupUrl);
      setPasswordSetupUrlCopied(true);
    } catch {
      setPasswordSetupUrlCopied(false);
      setPasswordSetupCopyError('Não foi possível copiar automaticamente. Selecione o link e copie manualmente.');
    }
  };

  const isCustomerWorkspace = Boolean(customerId);
  const customerEmailMissing = isCustomerWorkspace && !customerLoading && !clientEmail.trim();
  const ownerEmailConflict = isCustomerWorkspace && !customerLoading && Boolean(clientEmail.trim()) && Boolean(currentUserEmail) && normalizeEmail(clientEmail) === currentUserEmail;
  const formDisabled = isLoading || customerLoading || Boolean(customerLoadError) || customerEmailMissing || ownerEmailConflict;
  const customerDisplayName = selectedCustomer?.nome || customerName || (customerId ? `#${customerId}` : '');

  return (
    <main className={agentivePageClass(isDark, 'flex items-center justify-center px-4 py-8 sm:px-6')}>
      <div className="w-full max-w-lg">
        <button
          type="button"
          onClick={() => navigate(returnTo)}
          className={agentiveSecondaryButtonClass(isDark, 'mb-4')}
        >
          <ArrowLeft className="h-4 w-4" />
          Voltar
        </button>

        <section className={agentivePanelClass(isDark, 'p-5 sm:p-6')}>
          <div className="mb-6 flex items-start gap-3">
            <div className={isDark ? 'grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-white/10 text-white' : 'grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand text-white'}>
              <Building2 className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h1 className="text-xl font-semibold leading-tight">Criar nova empresa</h1>
              <p className={isDark ? 'mt-1 text-sm text-white/55' : 'mt-1 text-sm text-brand/55'}>
                Crie um workspace e libere o acesso do cliente final.
              </p>
            </div>
          </div>

          {customerId && (
            <div className={isDark ? 'mb-5 rounded-2xl border border-white/10 bg-white/[0.04] p-4 text-sm text-white/70' : 'mb-5 rounded-2xl border border-brand/10 bg-brand-canvas p-4 text-sm text-brand/70'}>
              Este workspace será associado ao cliente <strong>{customerLoading ? 'carregando...' : customerDisplayName}</strong> na gestão de clientes.
            </div>
          )}

          {customerLoadError && (
            <AgentiveAlert variant="error" className="mb-5">
              {customerLoadError}
            </AgentiveAlert>
          )}

          {customerId && customerEmailMissing && (
            <AgentiveAlert variant="warning" title="E-mail obrigatório" className="mb-5">
              Edite o perfil deste cliente e cadastre um e-mail antes de criar o workspace. Esse será o login do cliente final.
            </AgentiveAlert>
          )}

          {customerId && ownerEmailConflict && (
            <AgentiveAlert variant="warning" title="E-mail do cliente igual ao seu" className="mb-5">
              {WORKSPACE_OWNER_EMAIL_CONFLICT_MESSAGE} Edite o cadastro do cliente antes de criar o workspace.
            </AgentiveAlert>
          )}

          {error && (
            <AgentiveAlert variant="error" className="mb-5" onClose={() => setError('')}>
              {error}
            </AgentiveAlert>
          )}

          {success && (
            <AgentiveAlert variant="success" className="mb-5" onClose={() => setSuccess('')}>
              <div className="space-y-3">
                <p>{success}</p>
                {createdCompanyId && customerId && (
                  <button type="button" onClick={() => navigate(returnTo)} className={agentiveSecondaryButtonClass(isDark, 'px-2.5 py-1.5')}>
                    <CheckCircle2 className="h-4 w-4" />
                    Voltar ao cliente
                  </button>
                )}
              </div>
            </AgentiveAlert>
          )}

          {passwordSetupUrl && (
            <AgentiveAlert
              variant="warning"
              title="Envie o link de acesso ao cliente"
              className="mb-5"
              onClose={() => {
                setPasswordSetupUrl('');
                setPasswordSetupUrlCopied(false);
                setPasswordSetupCopyError('');
              }}
            >
              <div className="space-y-3">
                <p>
                  O SMTP não entregou o e-mail. Copie este link agora e envie ao cliente por um canal seguro; ele aparece somente nesta confirmação.
                </p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    type="text"
                    value={passwordSetupUrl}
                    readOnly
                    aria-label="Link temporário para definição de senha"
                    className={agentiveInputClass(isDark, 'min-w-0 flex-1 font-mono text-xs')}
                    onFocus={(event) => event.currentTarget.select()}
                  />
                  <button
                    type="button"
                    onClick={() => void handleCopyPasswordSetupUrl()}
                    className={agentiveSecondaryButtonClass(isDark, 'shrink-0')}
                  >
                    {passwordSetupUrlCopied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                    {passwordSetupUrlCopied ? 'Copiado' : 'Copiar link'}
                  </button>
                </div>
                {passwordSetupCopyError && (
                  <p className={isDark ? 'text-xs text-amber-100' : 'text-xs text-amber-800'}>
                    {passwordSetupCopyError}
                  </p>
                )}
              </div>
            </AgentiveAlert>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="block">
              <span className={agentiveLabelClass(isDark)}>E-mail do cliente</span>
              <div className="relative">
                <input
                  type="email"
                  required
                  value={clientEmail}
                  onChange={handleEmailChange}
                  onBlur={() => {
                    if (clientEmail && !validateEmail(clientEmail)) {
                      setError('Por favor, insira um email válido');
                    }
                  }}
                  className={agentiveInputClass(isDark, customerId ? 'pr-10' : '')}
                  placeholder="exemplo@dominio.com"
                  disabled={formDisabled || Boolean(customerId)}
                />
                {customerId && (
                  <Lock className={isDark ? 'pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/35' : 'pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-brand/35'} />
                )}
              </div>
              {customerId && (
                <p className={isDark ? 'mt-1.5 text-xs text-white/45' : 'mt-1.5 text-xs text-brand/45'}>
                  Este e-mail vem do cliente selecionado e será usado para criar ou reutilizar o login dele.
                </p>
              )}
            </label>

            <label className="block">
              <span className={agentiveLabelClass(isDark)}>Nome/Razão social da empresa</span>
              <input
                type="text"
                required
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                className={agentiveInputClass(isDark)}
                placeholder="Ex: Empresa Sorriso Saudável"
                disabled={formDisabled}
              />
            </label>

            <label className="block">
              <span className={agentiveLabelClass(isDark)}>CPF/CNPJ</span>
              <input
                type="text"
                required
                value={companyCnpj}
                onChange={handleCNPJChange}
                onBlur={() => {
                  if (companyCnpj && !validateDocument(companyCnpj)) {
                    setError('Por favor, insira um CPF ou CNPJ válido');
                  }
                }}
                className={agentiveInputClass(isDark)}
                placeholder="000.000.000-00 ou 12.345.678/0001-09"
                maxLength={18}
                disabled={formDisabled}
              />
            </label>

            {customerId && (
              <label className="block">
                <span className={agentiveLabelClass(isDark)}>Período de teste</span>
                <select
                  value={trialDays}
                  onChange={(e) => setTrialDays(e.target.value)}
                  className={agentiveInputClass(isDark)}
                  disabled={formDisabled}
                >
                  <option value="0">Sem teste</option>
                  <option value="3">3 dias</option>
                  <option value="7">7 dias</option>
                  <option value="14">14 dias</option>
                  <option value="30">30 dias</option>
                </select>
              </label>
            )}

            <button type="submit" disabled={formDisabled} className={agentivePrimaryButtonClass('h-11 w-full')}>
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Building2 className="h-4 w-4" />}
              Criar empresa
            </button>
          </form>
        </section>
      </div>
    </main>
  );
};

export default NewCompanyAdminPage;
