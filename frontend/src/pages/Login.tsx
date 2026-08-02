import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  Eye,
  EyeOff,
  Loader2,
  LockKeyhole,
  Mail,
  ShieldCheck,
} from 'lucide-react';
import { login } from '../services/api.ts';
import { branding } from '../config/branding.ts';

const inputClass = [
  'w-full rounded-xl border border-brand/10 bg-white px-3.5 py-3 text-sm text-brand outline-none transition',
  'placeholder:text-brand/35 focus:border-brand/30 focus:ring-4 focus:ring-brand/10',
  'disabled:cursor-not-allowed disabled:bg-brand-canvas disabled:text-brand/55',
].join(' ');

const labelClass = 'text-xs font-semibold text-brand/70';

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const savedError = localStorage.getItem('auth_error_message');
    if (savedError) {
      setError(savedError);
      localStorage.removeItem('auth_error_message');
    }
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const {
        companyId,
        clientId,
        userType,
        userId,
        userTeam,
        team,
        sidebarPermissions,
        contactPermissions,
      } = await login(email, password);

      if (userType) localStorage.setItem('user_type', userType);
      if (userId) localStorage.setItem('user_id', userId.toString());
      if (clientId) localStorage.setItem('client_id', clientId.toString());
      if (companyId) {
        const id = companyId.toString();
        localStorage.setItem('company_id', id);
        localStorage.setItem('clinic_id', id);
      }
      if (userTeam) {
        localStorage.setItem('user_team', userTeam);
      } else {
        localStorage.removeItem('user_team');
      }
      if (team) {
        localStorage.setItem('user_team_data', JSON.stringify(team));
      } else {
        localStorage.removeItem('user_team_data');
      }
      localStorage.setItem('sidebar_permissions', JSON.stringify(sidebarPermissions || []));
      if (contactPermissions) {
        localStorage.setItem('contact_permissions', JSON.stringify(contactPermissions));
      } else {
        localStorage.removeItem('contact_permissions');
      }

      localStorage.setItem('user_email', email);

      if (userType === 'user' && clientId) {
        localStorage.setItem('master_client_id', clientId.toString());
      }

      navigate('/dashboard');
    } catch (err: any) {
      console.error('Erro completo:', err);
      setError(err.message || 'Falha ao fazer login');

      localStorage.removeItem('user_type');
      localStorage.removeItem('user_team');
      localStorage.removeItem('user_team_data');
      localStorage.removeItem('sidebar_permissions');
      localStorage.removeItem('contact_permissions');
      localStorage.removeItem('user_id');
      localStorage.removeItem('client_id');
      localStorage.removeItem('master_client_id');
      localStorage.removeItem('company_id');
      localStorage.removeItem('clinic_id');
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
              <p className="text-xs text-white/50">Área de acesso</p>
            </div>
          </div>

          <div className="max-w-md">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white/75">
              <ShieldCheck className="h-3.5 w-3.5" />
              Plataforma segura
            </div>
            <h1 className="text-3xl font-semibold leading-tight tracking-normal sm:text-4xl">
              Entre no seu workspace.
            </h1>
            <p className="mt-3 max-w-sm text-sm leading-6 text-white/60">
              Acesse a operação para acompanhar atendimentos, automações, agentes e resultados em um só lugar.
            </p>
          </div>
        </div>
      </section>

      <section className="flex min-h-[calc(100vh-220px)] items-center justify-center px-4 py-8 sm:px-6 lg:min-h-screen lg:px-10">
        <div className="w-full max-w-[560px]">
          <div className="rounded-2xl border border-brand/10 bg-white p-5 shadow-[0_24px_80px_rgba(2,3,35,0.08)] sm:p-7">
            <div className="mb-6">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand/35">
                Login
              </p>
              <h2 className="mt-2 text-2xl font-semibold tracking-normal text-brand">
                Acesse sua conta
              </h2>
              <p className="mt-2 text-sm leading-6 text-brand/55">
                Entre com as credenciais vinculadas à sua empresa.
              </p>
            </div>

            {error && (
              <div className="mb-5 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <form className="space-y-5" onSubmit={handleSubmit}>
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
                    onChange={(event) => setEmail(event.target.value)}
                    disabled={isLoading}
                    className={`${inputClass} pl-10`}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <label htmlFor="password" className={labelClass}>
                    Senha
                  </label>
                  <Link
                    to="/reset-password"
                    className="text-xs font-semibold text-brand/60 underline-offset-4 transition hover:text-brand hover:underline"
                  >
                    Esqueci minha senha
                  </Link>
                </div>
                <div className="relative">
                  <LockKeyhole className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-brand/35" />
                  <input
                    id="password"
                    name="password"
                    type={showPassword ? 'text' : 'password'}
                    required
                    autoComplete="current-password"
                    placeholder="Digite sua senha"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
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

              <button
                type="submit"
                disabled={isLoading}
                className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 text-sm font-semibold text-white transition hover:bg-brand/90 disabled:cursor-wait disabled:opacity-75"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Entrando...
                  </>
                ) : (
                  <>
                    Entrar
                    <ArrowRight className="h-4 w-4" />
                  </>
                )}
              </button>
            </form>

          </div>

          <div className="mt-5 text-center text-[11px] text-brand/40">
            © {new Date().getFullYear()} {branding.appName}. Todos os direitos reservados.
          </div>
        </div>
      </section>
    </main>
  );
};

export default Login;
