import React, { useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  LockKeyhole,
  Mail,
  ShieldCheck,
} from 'lucide-react';
import { confirmPasswordReset, requestPasswordReset } from '../services/api.ts';
import { branding } from '../config/branding.ts';

const inputClass = [
  'w-full rounded-xl border border-brand/10 bg-white px-3.5 py-3 text-sm text-brand outline-none transition',
  'placeholder:text-brand/35 focus:border-brand/30 focus:ring-4 focus:ring-brand/10',
  'disabled:cursor-not-allowed disabled:bg-brand-canvas disabled:text-brand/55',
].join(' ');

const labelClass = 'text-xs font-semibold text-brand/70';

const validateEmail = (email: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());

const ResetPassword = () => {
  const location = useLocation();
  const token = useMemo(() => new URLSearchParams(location.search).get('token') || '', [location.search]);
  const isConfirmMode = Boolean(token);

  const [email, setEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const resetMessages = () => {
    setError('');
    setSuccess('');
  };

  async function handleRequestSubmit(event: React.FormEvent) {
    event.preventDefault();
    resetMessages();

    const normalizedEmail = email.trim().toLowerCase();
    if (!validateEmail(normalizedEmail)) {
      setError('Informe um email válido.');
      return;
    }

    setIsLoading(true);
    try {
      const message = await requestPasswordReset(normalizedEmail);
      setEmail(normalizedEmail);
      setSuccess(message);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível solicitar a redefinição agora.');
    } finally {
      setIsLoading(false);
    }
  }

  async function handleConfirmSubmit(event: React.FormEvent) {
    event.preventDefault();
    resetMessages();

    if (newPassword.length < 6) {
      setError('A senha deve ter pelo menos 6 caracteres.');
      return;
    }

    if (newPassword !== confirmPassword) {
      setError('Senhas não conferem.');
      return;
    }

    setIsLoading(true);
    try {
      const message = await confirmPasswordReset(token, newPassword, confirmPassword);
      setSuccess(message);
      setNewPassword('');
      setConfirmPassword('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível redefinir a senha agora.');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-brand-canvas text-brand lg:grid lg:grid-cols-[minmax(360px,0.9fr)_minmax(0,1.1fr)]">
      <section className="relative flex min-h-[220px] overflow-hidden bg-brand px-5 py-6 text-white sm:px-8 lg:min-h-screen lg:items-end lg:px-10 lg:py-10">
        <div
          className="absolute inset-0 opacity-70"
          style={{
            backgroundImage: 'radial-gradient(circle at 18% 18%, rgba(111, 90, 255, 0.55), transparent 34%), radial-gradient(circle at 82% 72%, rgba(36, 190, 191, 0.3), transparent 38%)',
          }}
        />
        <div className="absolute inset-0 bg-brand/75" />
        <div
          className="absolute inset-0 opacity-45"
          style={{
            backgroundImage: 'linear-gradient(rgba(255,255,255,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.08) 1px, transparent 1px)',
            backgroundSize: '44px 44px',
          }}
        />

        <div className="relative z-10 flex h-full w-full flex-col justify-between gap-8">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-white">
              <img src={branding.assets.icon} alt={branding.appName} className="h-full w-full object-cover" />
            </span>
            <div>
              <p className="text-sm font-semibold leading-tight">{branding.appName}</p>
              <p className="text-xs text-white/50">Recuperação de acesso</p>
            </div>
          </div>

          <div className="max-w-md">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white/75">
              <ShieldCheck className="h-3.5 w-3.5" />
              Link seguro
            </div>
            <h1 className="text-3xl font-semibold leading-tight tracking-normal sm:text-4xl">
              Recupere seu acesso.
            </h1>
            <p className="mt-3 max-w-sm text-sm leading-6 text-white/60">
              Solicite um link por email ou cadastre uma nova senha para voltar ao workspace.
            </p>
          </div>
        </div>
      </section>

      <section className="flex min-h-[calc(100vh-220px)] items-center justify-center px-4 py-8 sm:px-6 lg:min-h-screen lg:px-10">
        <div className="w-full max-w-[560px]">
          <div className="rounded-2xl border border-brand/10 bg-white p-5 shadow-[0_24px_80px_rgba(2,3,35,0.08)] sm:p-7">
            <div className="mb-6">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand/35">
                {isConfirmMode ? 'Nova senha' : 'Redefinir senha'}
              </p>
              <h2 className="mt-2 text-2xl font-semibold tracking-normal text-brand">
                {isConfirmMode ? 'Crie uma nova senha' : 'Receba o link de recuperação'}
              </h2>
              <p className="mt-2 text-sm leading-6 text-brand/55">
                {isConfirmMode
                  ? 'Use uma senha segura para acessar sua conta novamente.'
                  : 'Informe o email da conta para receber as instruções.'}
              </p>
            </div>

            {error && (
              <div className="mb-5 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {success && (
              <div className="mb-5 flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-3 text-sm text-emerald-700">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{success}</span>
              </div>
            )}

            {!isConfirmMode ? (
              <form className="space-y-5" onSubmit={handleRequestSubmit}>
                <div className="space-y-2">
                  <label htmlFor="email" className={labelClass}>
                    Email
                  </label>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-brand/35" />
                    <input
                      id="email"
                      name="email"
                      type="email"
                      required
                      autoComplete="email"
                      placeholder="seu@email.com"
                      value={email}
                      onChange={(event) => {
                        setEmail(event.target.value);
                        if (error || success) resetMessages();
                      }}
                      disabled={isLoading}
                      className={`${inputClass} pl-10`}
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={isLoading}
                  className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 text-sm font-semibold text-white transition hover:bg-brand/90 disabled:cursor-wait disabled:opacity-75"
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Enviando...
                    </>
                  ) : (
                    <>
                      Enviar link
                      <KeyRound className="h-4 w-4" />
                    </>
                  )}
                </button>
              </form>
            ) : (
              <form className="space-y-5" onSubmit={handleConfirmSubmit}>
                <div className="space-y-2">
                  <label htmlFor="new-password" className={labelClass}>
                    Nova senha
                  </label>
                  <div className="relative">
                    <LockKeyhole className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-brand/35" />
                    <input
                      id="new-password"
                      name="new-password"
                      type={showPassword ? 'text' : 'password'}
                      required
                      autoComplete="new-password"
                      placeholder="Digite a nova senha"
                      value={newPassword}
                      onChange={(event) => {
                        setNewPassword(event.target.value);
                        if (error || success) resetMessages();
                      }}
                      disabled={isLoading}
                      className={`${inputClass} pl-10 pr-12`}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((current) => !current)}
                      aria-label={showPassword ? 'Ocultar senha' : 'Mostrar senha'}
                      title={showPassword ? 'Ocultar senha' : 'Mostrar senha'}
                      disabled={isLoading}
                      className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-brand/45 transition hover:bg-brand-canvas hover:text-brand disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <label htmlFor="confirm-password" className={labelClass}>
                    Confirmar senha
                  </label>
                  <div className="relative">
                    <LockKeyhole className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-brand/35" />
                    <input
                      id="confirm-password"
                      name="confirm-password"
                      type={showConfirmPassword ? 'text' : 'password'}
                      required
                      autoComplete="new-password"
                      placeholder="Repita a nova senha"
                      value={confirmPassword}
                      onChange={(event) => {
                        setConfirmPassword(event.target.value);
                        if (error || success) resetMessages();
                      }}
                      disabled={isLoading}
                      className={`${inputClass} pl-10 pr-12`}
                    />
                    <button
                      type="button"
                      onClick={() => setShowConfirmPassword((current) => !current)}
                      aria-label={showConfirmPassword ? 'Ocultar senha' : 'Mostrar senha'}
                      title={showConfirmPassword ? 'Ocultar senha' : 'Mostrar senha'}
                      disabled={isLoading}
                      className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-brand/45 transition hover:bg-brand-canvas hover:text-brand disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {showConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={isLoading || Boolean(success)}
                  className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 text-sm font-semibold text-white transition hover:bg-brand/90 disabled:cursor-wait disabled:opacity-75"
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Salvando...
                    </>
                  ) : (
                    <>
                      Salvar nova senha
                      <CheckCircle2 className="h-4 w-4" />
                    </>
                  )}
                </button>
              </form>
            )}

            <div className="mt-6 text-center text-sm">
              <Link to="/login" className="inline-flex items-center gap-2 font-semibold text-brand underline-offset-4 hover:underline">
                <ArrowLeft className="h-4 w-4" />
                Voltar para login
              </Link>
            </div>
          </div>

          <div className="mt-5 text-center text-[11px] text-brand/40">
            © {new Date().getFullYear()} {branding.appName}. Todos os direitos reservados.
          </div>
        </div>
      </section>
    </main>
  );
};

export default ResetPassword;
