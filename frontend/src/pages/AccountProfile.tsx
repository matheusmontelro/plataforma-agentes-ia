import React, { useEffect, useMemo, useRef, useState } from 'react';
import { BadgeCheck, Camera, Check, IdCard, Loader2, MapPin, Save, Search, UserRound } from 'lucide-react';
import {
  AccountBillingProfile,
  getAccountProfile,
  updateAccountProfile,
  uploadAccountProfilePhoto,
} from '../services/api.ts';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';

const emptyProfile: AccountBillingProfile = {
  full_name: '',
  email: '',
  cellphone: '',
  document: '',
  postal_code: '',
  street: '',
  number: '',
  neighborhood: '',
  complement: '',
  state: '',
  profile_picture_url: '',
};

type ProfileField = keyof AccountBillingProfile;
type FieldErrors = Partial<Record<ProfileField, string>>;
type CepStatus = 'idle' | 'loading' | 'found' | 'not_found' | 'error';

interface ViaCepResponse {
  bairro?: string;
  erro?: boolean;
  localidade?: string;
  logradouro?: string;
  uf?: string;
}

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
    return digits.replace(/^(\d{2})(\d)/, '($1) $2').replace(/(\d{4})(\d)/, '$1-$2').slice(0, 14);
  }
  return digits.replace(/^(\d{2})(\d)/, '($1) $2').replace(/(\d{5})(\d)/, '$1-$2').slice(0, 15);
};

const formatPostalCode = (value: string) => onlyDigits(value).slice(0, 8).replace(/^(\d{5})(\d)/, '$1-$2');

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

const getProfileErrors = (profile: AccountBillingProfile): FieldErrors => {
  const errors: FieldErrors = {};
  if (!profile.full_name.trim()) errors.full_name = 'Informe o nome completo.';
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(profile.email.trim())) errors.email = 'Informe um email válido.';

  const phoneDigits = onlyDigits(profile.cellphone);
  if (!phoneDigits) errors.cellphone = 'Informe o celular.';
  else if (phoneDigits.length < 10 || phoneDigits.length > 11) errors.cellphone = 'Use DDD + número.';

  const documentDigits = onlyDigits(profile.document);
  if (!documentDigits) errors.document = 'Informe CPF ou CNPJ.';
  else if (![11, 14].includes(documentDigits.length)) errors.document = 'CPF precisa de 11 dígitos; CNPJ, 14.';
  else if (documentDigits.length === 11 && !isValidCPF(documentDigits)) errors.document = 'CPF inválido.';
  else if (documentDigits.length === 14 && !isValidCNPJ(documentDigits)) errors.document = 'CNPJ inválido.';

  const postalDigits = onlyDigits(profile.postal_code);
  if (postalDigits && postalDigits.length !== 8) errors.postal_code = 'CEP deve ter 8 dígitos.';
  if (profile.state && !/^[A-Za-z]{2}$/.test(profile.state)) errors.state = 'UF deve ter 2 letras.';
  return errors;
};

const getErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
};

const formatLoadedProfile = (profile: AccountBillingProfile): AccountBillingProfile => ({
  ...emptyProfile,
  ...profile,
  cellphone: formatPhone(profile.cellphone || ''),
  document: formatDocument(profile.document || ''),
  postal_code: formatPostalCode(profile.postal_code || ''),
});

interface FieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: string;
  hint?: string;
  isDark: boolean;
  label: string;
}

const Field: React.FC<FieldProps> = ({ error, hint, isDark, label, className = '', ...props }) => (
  <label className="block">
    <span className={agentiveLabelClass(isDark)}>{label}</span>
    <input
      {...props}
      aria-invalid={Boolean(error)}
      className={agentiveInputClass(
        isDark,
        `${error ? 'border-red-500/70 focus:border-red-500 focus:ring-red-500/20' : ''} ${className}`
      )}
    />
    {(error || hint) && (
      <span className={`mt-1.5 block text-xs ${error ? 'text-red-500' : isDark ? 'text-white/45' : 'text-brand/45'}`}>
        {error || hint}
      </span>
    )}
  </label>
);

const AccountProfile: React.FC = () => {
  const { isDark } = useTheme();
  const photoInputRef = useRef<HTMLInputElement | null>(null);
  const [profile, setProfile] = useState<AccountBillingProfile>(emptyProfile);
  const [profileComplete, setProfileComplete] = useState(false);
  const [touchedFields, setTouchedFields] = useState<Set<ProfileField>>(new Set());
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [cepStatus, setCepStatus] = useState<CepStatus>('idle');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isUploadingPhoto, setIsUploadingPhoto] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    void loadProfile();
  }, []);

  const fieldErrors = useMemo(() => getProfileErrors(profile), [profile]);
  const hasBlockingErrors = Object.values(fieldErrors).some(Boolean);

  const completedCoreFields = useMemo(() => {
    const coreFields: ProfileField[] = ['full_name', 'email', 'cellphone', 'document'];
    return coreFields.filter((field) => Boolean(profile[field]?.trim()) && !fieldErrors[field]).length;
  }, [fieldErrors, profile]);

  const postalDigits = onlyDigits(profile.postal_code);

  useEffect(() => {
    if (postalDigits.length !== 8) {
      setCepStatus('idle');
      return;
    }

    const controller = new AbortController();
    setCepStatus('loading');

    window
      .fetch(`https://viacep.com.br/ws/${postalDigits}/json/`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('CEP indisponível');
        return response.json() as Promise<ViaCepResponse>;
      })
      .then((data) => {
        if (data.erro) {
          setCepStatus('not_found');
          return;
        }
        setProfile((current) => {
          if (onlyDigits(current.postal_code) !== postalDigits) return current;
          return {
            ...current,
            street: data.logradouro || current.street,
            neighborhood: data.bairro || current.neighborhood,
            state: (data.uf || current.state).toUpperCase().slice(0, 2),
          };
        });
        setCepStatus('found');
      })
      .catch((lookupError) => {
        if ((lookupError as Error).name !== 'AbortError') setCepStatus('error');
      });

    return () => controller.abort();
  }, [postalDigits]);

  async function loadProfile() {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getAccountProfile();
      setProfile(formatLoadedProfile(response.billing_profile));
      setProfileComplete(response.profile_complete);
    } catch (loadError) {
      setError(getErrorMessage(loadError, 'Não foi possível carregar o perfil da conta.'));
    } finally {
      setIsLoading(false);
    }
  }

  const markTouched = (field: ProfileField) => {
    setTouchedFields((current) => {
      const next = new Set(current);
      next.add(field);
      return next;
    });
  };

  const updateField = (field: ProfileField, value: string) => {
    markTouched(field);
    setProfile((prev) => ({ ...prev, [field]: value }));
    setSuccessMessage(null);
  };

  const visibleError = (field: ProfileField) => {
    if (submitAttempted || touchedFields.has(field)) return fieldErrors[field];
    return undefined;
  };

  const handlePhotoChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      setError('Envie uma imagem JPG, PNG ou WebP.');
      return;
    }
    if (file.size > 4 * 1024 * 1024) {
      setError('A foto deve ter até 4MB.');
      return;
    }

    setIsUploadingPhoto(true);
    setError(null);
    try {
      const response = await uploadAccountProfilePhoto(file);
      setProfile(formatLoadedProfile(response.billing_profile));
      setProfileComplete(response.profile_complete);
      setSuccessMessage('Foto atualizada com sucesso.');
    } catch (photoError) {
      setError(getErrorMessage(photoError, 'Não foi possível atualizar a foto.'));
    } finally {
      setIsUploadingPhoto(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitAttempted(true);
    if (hasBlockingErrors) {
      setError('Revise os campos destacados antes de salvar.');
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      const response = await updateAccountProfile({
        full_name: profile.full_name.trim(),
        cellphone: onlyDigits(profile.cellphone),
        document: onlyDigits(profile.document),
        postal_code: onlyDigits(profile.postal_code),
        street: profile.street,
        number: profile.number,
        neighborhood: profile.neighborhood,
        complement: profile.complement,
        state: profile.state.trim().toUpperCase(),
        profile_picture_url: profile.profile_picture_url,
      });
      setProfile(formatLoadedProfile(response.billing_profile));
      setProfileComplete(response.profile_complete);
      setSuccessMessage('Perfil atualizado com sucesso.');
    } catch (saveError) {
      setError(getErrorMessage(saveError, 'Não foi possível atualizar o perfil da conta.'));
    } finally {
      setIsSaving(false);
    }
  };

  const cepHint = useMemo(() => {
    if (cepStatus === 'loading') return 'Buscando endereço...';
    if (cepStatus === 'found') return 'Endereço encontrado.';
    if (cepStatus === 'not_found') return 'CEP não encontrado.';
    if (cepStatus === 'error') return 'Não foi possível buscar o CEP agora.';
    return 'Digite o CEP para preencher rua, bairro e UF.';
  }, [cepStatus]);

  const summaryItems = useMemo(
    () => [
      { label: 'Nome', value: profile.full_name, valid: !fieldErrors.full_name },
      { label: 'Email', value: profile.email, valid: !fieldErrors.email },
      { label: 'Celular', value: profile.cellphone, valid: !fieldErrors.cellphone },
      { label: 'Documento', value: profile.document, valid: !fieldErrors.document },
    ],
    [fieldErrors, profile]
  );

  const initials = profile.full_name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase() || 'AG';

  if (isLoading) {
    return (
      <div className={`flex min-h-screen items-center justify-center ${isDark ? 'bg-brand text-white' : 'bg-brand-canvas text-brand'}`}>
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-10 w-10 animate-spin" />
          <p className={`text-sm font-medium ${isDark ? 'text-white/60' : 'text-brand/60'}`}>Carregando perfil...</p>
        </div>
      </div>
    );
  }

  return (
    <div className={agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10')}>
      <div className="mx-auto max-w-screen-xl space-y-5">
        <header className={agentivePanelClass(isDark, 'p-5')}>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="flex min-w-0 items-center gap-4">
              <div className={`relative grid h-16 w-16 shrink-0 place-items-center overflow-hidden rounded-2xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                {profile.profile_picture_url ? (
                  <img src={profile.profile_picture_url} alt="Foto do perfil" className="h-full w-full object-cover" />
                ) : (
                  <span className="text-lg font-semibold">{initials}</span>
                )}
              </div>
              <div className="min-w-0">
                <p className={`text-[10px] font-semibold uppercase tracking-[0.14em] ${isDark ? 'text-white/40' : 'text-brand/40'}`}>
                  Conta master
                </p>
                <h1 className="mt-1 truncate text-2xl font-semibold tracking-tight sm:text-3xl">Perfil da conta</h1>
                <div className="mt-2 flex flex-wrap gap-2">
                  <span className={agentivePillClass(isDark, profileComplete)}>
                    {profileComplete ? 'Dados completos' : 'Dados pendentes'}
                  </span>
                  <span className={agentivePillClass(isDark)}>{completedCoreFields}/4 dados principais</span>
                </div>
              </div>
            </div>

            <button
              type="submit"
              form="account-profile-form"
              disabled={isSaving || isUploadingPhoto}
              className={agentivePrimaryButtonClass('w-full sm:w-auto')}
            >
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Salvar perfil
            </button>
          </div>
        </header>

        {error && (
          <AgentiveAlert variant="error" title="Não foi possível concluir" onClose={() => setError(null)}>
            {error}
          </AgentiveAlert>
        )}

        {successMessage && (
          <AgentiveAlert variant="success" title="Atualização concluída" onClose={() => setSuccessMessage(null)}>
            {successMessage}
          </AgentiveAlert>
        )}

        <form id="account-profile-form" onSubmit={handleSubmit} className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <section className={agentivePanelClass(isDark, 'p-5')}>
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">Dados do titular</h2>
                <p className={`text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>Identificação principal da conta e dados de contato.</p>
              </div>
              <IdCard className={`h-5 w-5 ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                isDark={isDark}
                label="Nome completo"
                value={profile.full_name}
                onChange={(event) => updateField('full_name', event.target.value)}
                error={visibleError('full_name')}
                required
                disabled={isSaving}
              />
              <Field
                isDark={isDark}
                label="Email da conta"
                type="email"
                value={profile.email}
                hint="Este e-mail identifica a conta e não pode ser alterado depois da criação."
                required
                disabled
              />
              <Field
                isDark={isDark}
                label="Celular"
                value={profile.cellphone}
                onChange={(event) => updateField('cellphone', formatPhone(event.target.value))}
                error={visibleError('cellphone')}
                inputMode="numeric"
                placeholder="(11) 98888-8888"
                required
                disabled={isSaving}
              />
              <Field
                isDark={isDark}
                label="CPF ou CNPJ"
                value={profile.document}
                onChange={(event) => updateField('document', formatDocument(event.target.value))}
                error={visibleError('document')}
                inputMode="numeric"
                placeholder="123.456.789-09 ou 12.345.678/0001-95"
                required
                disabled={isSaving}
              />
            </div>
          </section>

          <section className={agentivePanelClass(isDark, 'p-5')}>
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">Foto do perfil</h2>
                <p className={`text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>Imagem exibida para identificar a conta.</p>
              </div>
              <Camera className={`h-5 w-5 ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
            </div>

            <div className="flex flex-col items-center text-center">
              <div className={`grid h-28 w-28 place-items-center overflow-hidden rounded-3xl border ${isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-brand-canvas'}`}>
                {profile.profile_picture_url ? (
                  <img src={profile.profile_picture_url} alt="Foto do perfil" className="h-full w-full object-cover" />
                ) : (
                  <UserRound className={`h-10 w-10 ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
                )}
              </div>
              <input
                ref={photoInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                onChange={handlePhotoChange}
              />
              <button
                type="button"
                onClick={() => photoInputRef.current?.click()}
                disabled={isUploadingPhoto || isSaving}
                className={agentiveSecondaryButtonClass(isDark, 'mt-4 w-full')}
              >
                {isUploadingPhoto ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />}
                {profile.profile_picture_url ? 'Alterar foto' : 'Adicionar foto'}
              </button>
            </div>
          </section>

          <section className={agentivePanelClass(isDark, 'p-5 lg:col-span-2')}>
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">Endereço</h2>
                <p className={`text-sm ${isDark ? 'text-white/55' : 'text-brand/55'}`}>Dados opcionais para completar o perfil e a identificação fiscal.</p>
              </div>
              {cepStatus === 'loading' ? (
                <Loader2 className={`h-5 w-5 animate-spin ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
              ) : (
                <MapPin className={`h-5 w-5 ${isDark ? 'text-white/45' : 'text-brand/45'}`} />
              )}
            </div>

            <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)_140px_minmax(0,1fr)_90px]">
              <Field
                isDark={isDark}
                label="CEP"
                value={profile.postal_code}
                onChange={(event) => updateField('postal_code', formatPostalCode(event.target.value))}
                error={visibleError('postal_code')}
                hint={cepHint}
                inputMode="numeric"
                disabled={isSaving}
              />
              <Field
                isDark={isDark}
                label="Rua"
                value={profile.street}
                onChange={(event) => updateField('street', event.target.value)}
                disabled={isSaving}
              />
              <Field
                isDark={isDark}
                label="Número"
                value={profile.number}
                onChange={(event) => updateField('number', event.target.value)}
                disabled={isSaving}
              />
              <Field
                isDark={isDark}
                label="Bairro"
                value={profile.neighborhood}
                onChange={(event) => updateField('neighborhood', event.target.value)}
                disabled={isSaving}
              />
              <Field
                isDark={isDark}
                label="UF"
                value={profile.state}
                onChange={(event) => updateField('state', event.target.value.toUpperCase().slice(0, 2))}
                error={visibleError('state')}
                maxLength={2}
                disabled={isSaving}
              />
              <div className="lg:col-span-5">
                <Field
                  isDark={isDark}
                  label="Complemento"
                  value={profile.complement}
                  onChange={(event) => updateField('complement', event.target.value)}
                  disabled={isSaving}
                />
              </div>
            </div>
          </section>

          <section className={agentivePanelClass(isDark, 'p-5 lg:col-span-2')}>
            <div className="grid gap-3 sm:grid-cols-4">
              {summaryItems.map(({ label, value, valid }) => (
                <div key={label} className={`rounded-2xl border px-4 py-3 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
                  <div className="flex items-center justify-between gap-3">
                    <span className={`text-sm font-medium ${isDark ? 'text-white/55' : 'text-brand/55'}`}>{label}</span>
                    {valid && value ? <Check className="h-4 w-4 text-emerald-500" /> : <span className={`h-2 w-2 rounded-full ${isDark ? 'bg-white/20' : 'bg-brand/20'}`} />}
                  </div>
                  <p className="mt-2 truncate text-sm font-semibold">{value || 'Pendente'}</p>
                </div>
              ))}
            </div>
            <div className={`mt-4 flex items-start gap-2 rounded-2xl border p-3 text-xs ${profileComplete ? isDark ? 'border-emerald-300/20 bg-emerald-300/10 text-emerald-100' : 'border-emerald-500/20 bg-emerald-50 text-emerald-800' : isDark ? 'border-amber-300/20 bg-amber-300/10 text-amber-100' : 'border-amber-500/20 bg-amber-50 text-amber-800'}`}>
              {profileComplete ? <BadgeCheck className="mt-0.5 h-4 w-4 shrink-0" /> : <Search className="mt-0.5 h-4 w-4 shrink-0" />}
              <span>{profileComplete ? 'A conta já tem os dados principais completos.' : 'Complete nome, email, celular e CPF/CNPJ para manter o perfil organizado.'}</span>
            </div>
          </section>
        </form>
      </div>
    </div>
  );
};

export default AccountProfile;
