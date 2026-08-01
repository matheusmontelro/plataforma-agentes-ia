import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Building2,
  CheckCircle2,
  Loader2,
  LockKeyhole,
  Mail,
  Phone,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import { checkRegistrationEligibility, registerUser } from '../services/api.ts';
import { branding } from '../config/branding.ts';

type RegisterStep = 'email' | 'details';

const STUDENT_ONLY_MESSAGE = 'Cadastro liberado apenas para alunos.';

const onlyDigits = (value: string) => value.replace(/\D/g, '');

const formatDocument = (value: string) => {
  const digits = onlyDigits(value).slice(0, 14);

  if (digits.length <= 11) {
    return digits
      .replace(/^(\d{3})(\d)/, '$1.$2')
      .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
      .replace(/\.(\d{3})(\d)/, '.$1-$2')
      .slice(0, 14);
  }

  return digits
    .replace(/^(\d{2})(\d)/, '$1.$2')
    .replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
    .replace(/\.(\d{3})(\d)/, '.$1/$2')
    .replace(/(\d{4})(\d)/, '$1-$2')
    .slice(0, 18);
};

const formatPhone = (value: string) => {
  const digits = onlyDigits(value).slice(0, 11);
  if (digits.length <= 10) {
    return digits
      .replace(/^(\d{2})(\d)/, '($1) $2')
      .replace(/(\d{4})(\d)/, '$1-$2')
      .slice(0, 14);
  }

  return digits
    .replace(/^(\d{2})(\d)/, '($1) $2')
    .replace(/(\d{5})(\d)/, '$1-$2')
    .slice(0, 15);
};

const hasRepeatedDigits = (digits: string) => digits.length > 0 && digits === digits[0].repeat(digits.length);

const isValidCPF = (value: string) => {
  const digits = onlyDigits(value);
  if (digits.length !== 11 || hasRepeatedDigits(digits)) return false;
  const numbers = digits.split('').map(Number);
  const firstSum = numbers.slice(0, 9).reduce((sum, number, index) => sum + number * (10 - index), 0);
  const firstDigit = firstSum % 11 < 2 ? 0 : 11 - (firstSum % 11);
  const secondSum = numbers.slice(0, 10).reduce((sum, number, index) => sum + number * (11 - index), 0);
  const secondDigit = secondSum % 11 < 2 ? 0 : 11 - (secondSum % 11);
  return numbers[9] === firstDigit && numbers[10] === secondDigit;
};

const isValidCNPJ = (value: string) => {
  const digits = onlyDigits(value);
  if (digits.length !== 14 || hasRepeatedDigits(digits)) return false;
  const numbers = digits.split('').map(Number);
  const firstWeights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
  const secondWeights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
  const firstSum = firstWeights.reduce((sum, weight, index) => sum + numbers[index] * weight, 0);
  const firstDigit = firstSum % 11 < 2 ? 0 : 11 - (firstSum % 11);
  const secondSum = secondWeights.reduce((sum, weight, index) => sum + numbers[index] * weight, 0);
  const secondDigit = secondSum % 11 < 2 ? 0 : 11 - (secondSum % 11);
  return numbers[12] === firstDigit && numbers[13] === secondDigit;
};

const validateEmail = (email: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());

const validateDocument = (document: string) => {
  const numbers = onlyDigits(document);
  if (numbers.length === 11) return isValidCPF(numbers);
  if (numbers.length === 14) return isValidCNPJ(numbers);
  return false;
};

const validatePhone = (phone: string) => {
  const numbers = onlyDigits(phone);
  return numbers.length >= 10 && numbers.length <= 11;
};

const normalizeEligibilityMessage = (message: string) => {
  const normalized = message.toLowerCase();
  if (normalized.includes('compradores') || normalized.includes('produto principal')) {
    return STUDENT_ONLY_MESSAGE;
  }
  return message;
};

const inputClass = [
  'w-full rounded-xl border border-brand/10 bg-white px-3.5 py-3 text-sm text-brand outline-none transition',
  'placeholder:text-brand/35 focus:border-brand/30 focus:ring-4 focus:ring-brand/10',
  'disabled:cursor-not-allowed disabled:bg-brand-canvas disabled:text-brand/55',
].join(' ');

const labelClass = 'text-xs font-semibold text-brand/70';

const Register = () => {
  const [step, setStep] = useState<RegisterStep>('email');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [responsibleName, setResponsibleName] = useState('');
  const [responsiblePhone, setResponsiblePhone] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [documentNumber, setDocumentNumber] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [isCheckingEmail, setIsCheckingEmail] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();

  const emailIsValid = validateEmail(email);

  const phoneError = useMemo(() => {
    if (!responsiblePhone) return '';
    return validatePhone(responsiblePhone) ? '' : 'Informe DDD + número.';
  }, [responsiblePhone]);

  const documentError = useMemo(() => {
    if (!documentNumber) return '';
    const numbers = onlyDigits(documentNumber);
    if (![11, 14].includes(numbers.length)) return 'CPF precisa de 11 dígitos; CNPJ, 14.';
    if (numbers.length === 11 && !isValidCPF(numbers)) return 'CPF inválido.';
    if (numbers.length === 14 && !isValidCNPJ(numbers)) return 'CNPJ inválido.';
    return '';
  }, [documentNumber]);

  const resetMessages = () => {
    setError('');
    setSuccess('');
  };

  const handleEmailChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setEmail(event.target.value);
    if (error || success) resetMessages();
  };

  const handleDocumentChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setDocumentNumber(formatDocument(event.target.value));
  };

  const handlePhoneChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setResponsiblePhone(formatPhone(event.target.value));
  };

  async function handleEmailSubmit(event: React.FormEvent) {
    event.preventDefault();
    resetMessages();

    if (!emailIsValid) {
      setError('Informe um email válido para continuar.');
      return;
    }

    setIsCheckingEmail(true);
    try {
      await checkRegistrationEligibility(email.trim().toLowerCase());
      setEmail(email.trim().toLowerCase());
      setStep('details');
      setSuccess('Email confirmado. Complete os dados da conta.');
    } catch (err) {
      const message = err instanceof Error ? err.message : STUDENT_ONLY_MESSAGE;
      setError(normalizeEligibilityMessage(message));
    } finally {
      setIsCheckingEmail(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    resetMessages();

    if (step !== 'details') {
      setError('Confirme seu email antes de continuar.');
      return;
    }

    if (!emailIsValid) {
      setError('Informe um email válido para continuar.');
      setStep('email');
      return;
    }

    if (!password.trim()) {
      setError('Crie uma senha para acessar sua conta.');
      return;
    }

    if (!responsibleName.trim()) {
      setError('Informe o nome completo do responsável.');
      return;
    }

    if (!validatePhone(responsiblePhone)) {
      setError('Informe um celular válido.');
      return;
    }

    if (!companyName.trim()) {
      setError('Informe a razão social da empresa.');
      return;
    }

    if (!validateDocument(documentNumber)) {
      setError('Informe um CPF ou CNPJ válido.');
      return;
    }

    setIsLoading(true);

    try {
      const cleanDocument = onlyDigits(documentNumber);
      const cleanPhone = onlyDigits(responsiblePhone);
      const message = await registerUser(
        email.trim().toLowerCase(),
        password,
        companyName.trim(),
        cleanDocument,
        responsibleName.trim(),
        cleanPhone,
      );
      setSuccess(message || 'Registro realizado com sucesso!');
      setTimeout(() => navigate('/'), 1600);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Erro ao registrar usuário.';
      setError(normalizeEligibilityMessage(message));
    } finally {
      setIsLoading(false);
    }
  }

  const goBackToEmail = () => {
    resetMessages();
    setStep('email');
  };

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
              <p className="text-xs text-white/50">Cadastro de aluno</p>
            </div>
          </div>

          <div className="max-w-md">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white/75">
              <ShieldCheck className="h-3.5 w-3.5" />
              Acesso reservado
            </div>
            <h1 className="text-3xl font-semibold leading-tight tracking-normal sm:text-4xl">
              Ative sua conta na plataforma.
            </h1>
            <p className="mt-3 max-w-sm text-sm leading-6 text-white/60">
              Confirme o email usado na matrícula para liberar o formulário de criação da conta master.
            </p>
          </div>
        </div>
      </section>

      <section className="flex min-h-[calc(100vh-220px)] items-center justify-center px-4 py-8 sm:px-6 lg:min-h-screen lg:px-10">
        <div className="w-full max-w-[560px]">
          <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl border border-brand/10 bg-white p-2 shadow-[0_18px_60px_rgba(2,3,35,0.06)]">
            <div className={`flex min-w-0 flex-1 items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold transition ${step === 'email' ? 'bg-brand text-white' : 'bg-brand-canvas text-brand/55'}`}>
              <Mail className="h-4 w-4 shrink-0" />
              <span className="truncate">Validar email</span>
            </div>
            <div className={`flex min-w-0 flex-1 items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold transition ${step === 'details' ? 'bg-brand text-white' : 'bg-brand-canvas text-brand/55'}`}>
              <UserRound className="h-4 w-4 shrink-0" />
              <span className="truncate">Dados da conta</span>
            </div>
          </div>

          <div className="rounded-2xl border border-brand/10 bg-white p-5 shadow-[0_24px_80px_rgba(2,3,35,0.08)] sm:p-7">
            <div className="mb-6 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand/35">
                  {step === 'email' ? 'Etapa 1 de 2' : 'Etapa 2 de 2'}
                </p>
                <h2 className="mt-2 text-2xl font-semibold tracking-normal text-brand">
                  {step === 'email' ? 'Confirme seu email' : 'Complete seu cadastro'}
                </h2>
                <p className="mt-2 text-sm leading-6 text-brand/55">
                  {step === 'email'
                    ? 'Use o mesmo email liberado para acessar a plataforma.'
                    : 'Esses dados ficam vinculados à conta master da empresa.'}
                </p>
              </div>
              {step === 'details' && (
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600">
                  <CheckCircle2 className="h-5 w-5" />
                </span>
              )}
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

            {step === 'email' ? (
              <form onSubmit={handleEmailSubmit} className="space-y-5">
                <div className="space-y-2">
                  <label htmlFor="register-email" className={labelClass}>
                    Email
                  </label>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-brand/35" />
                    <input
                      id="register-email"
                      name="email"
                      type="email"
                      required
                      autoComplete="email"
                      value={email}
                      onChange={handleEmailChange}
                      className={`${inputClass} pl-10`}
                      placeholder="seu@email.com"
                      disabled={isCheckingEmail}
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={isCheckingEmail}
                  className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 text-sm font-semibold text-white transition hover:bg-brand/90 disabled:cursor-wait disabled:opacity-75"
                >
                  {isCheckingEmail ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Validando...
                    </>
                  ) : (
                    <>
                      Avançar
                      <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </button>
              </form>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="rounded-xl border border-brand/10 bg-brand-canvas px-3.5 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-brand/35">Email validado</p>
                      <p className="mt-1 truncate text-sm font-semibold text-brand">{email}</p>
                    </div>
                    <button
                      type="button"
                      onClick={goBackToEmail}
                      disabled={isLoading}
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-brand/10 bg-white px-2.5 py-1.5 text-xs font-semibold text-brand/65 transition hover:bg-brand hover:text-white disabled:opacity-50"
                    >
                      <ArrowLeft className="h-3.5 w-3.5" />
                      Trocar
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <label htmlFor="register-password" className={labelClass}>
                    Senha
                  </label>
                  <div className="relative">
                    <LockKeyhole className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-brand/35" />
                    <input
                      id="register-password"
                      type="password"
                      required
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      className={`${inputClass} pl-10`}
                      placeholder="Crie uma senha"
                      disabled={isLoading}
                    />
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <label htmlFor="register-name" className={labelClass}>
                      Responsável
                    </label>
                    <div className="relative">
                      <UserRound className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-brand/35" />
                      <input
                        id="register-name"
                        type="text"
                        required
                        value={responsibleName}
                        onChange={(event) => setResponsibleName(event.target.value)}
                        className={`${inputClass} pl-10`}
                        placeholder="Nome completo"
                        disabled={isLoading}
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label htmlFor="register-phone" className={labelClass}>
                      Celular
                    </label>
                    <div className="relative">
                      <Phone className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-brand/35" />
                      <input
                        id="register-phone"
                        type="tel"
                        required
                        value={responsiblePhone}
                        onChange={handlePhoneChange}
                        className={`${inputClass} pl-10`}
                        placeholder="(11) 98888-8888"
                        disabled={isLoading}
                      />
                    </div>
                    {phoneError && <p className="text-xs font-medium text-red-600">{phoneError}</p>}
                  </div>
                </div>

                <div className="space-y-2">
                  <label htmlFor="register-company" className={labelClass}>
                    Razão social
                  </label>
                  <div className="relative">
                    <Building2 className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-brand/35" />
                    <input
                      id="register-company"
                      type="text"
                      required
                      value={companyName}
                      onChange={(event) => setCompanyName(event.target.value)}
                      className={`${inputClass} pl-10`}
                      placeholder="Nome da empresa"
                      disabled={isLoading}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <label htmlFor="register-document" className={labelClass}>
                    CPF ou CNPJ
                  </label>
                  <div className="relative">
                    <BadgeCheck className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-brand/35" />
                    <input
                      id="register-document"
                      type="text"
                      required
                      value={documentNumber}
                      onChange={handleDocumentChange}
                      className={`${inputClass} pl-10`}
                      placeholder="CPF ou CNPJ"
                      maxLength={18}
                      disabled={isLoading}
                    />
                  </div>
                  {documentError && <p className="text-xs font-medium text-red-600">{documentError}</p>}
                </div>

                <button
                  type="submit"
                  disabled={isLoading}
                  className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 text-sm font-semibold text-white transition hover:bg-brand/90 disabled:cursor-wait disabled:opacity-75"
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Criando conta...
                    </>
                  ) : (
                    <>
                      Criar conta
                      <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </button>
              </form>
            )}

            <div className="mt-6 text-center text-sm">
              <span className="text-brand/45">Já tem acesso? </span>
              <a href="/" className="font-semibold text-brand underline-offset-4 hover:underline">
                Fazer login
              </a>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
};

export default Register;
