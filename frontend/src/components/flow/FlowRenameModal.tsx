import React, { useEffect, useState } from 'react';
import { Edit2, Loader2, Save, X } from 'lucide-react';
import {
  agentiveIconButtonClass,
  agentiveInputClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../AgentiveUI.tsx';

interface FlowRenameModalProps {
  initialName: string;
  isDark: boolean;
  isOpen: boolean;
  isSaving?: boolean;
  onClose: () => void;
  onSubmit: (name: string) => Promise<void> | void;
}

const FlowRenameModal: React.FC<FlowRenameModalProps> = ({
  initialName,
  isDark,
  isOpen,
  isSaving = false,
  onClose,
  onSubmit,
}) => {
  const [name, setName] = useState(initialName);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    setName(initialName || '');
    setError('');
  }, [initialName, isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError('Informe um nome para o fluxo.');
      return;
    }

    await onSubmit(trimmedName);
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
      <div className="fixed inset-0 bg-brand/55 backdrop-blur-sm" onClick={isSaving ? undefined : onClose} />
      <form
        onSubmit={handleSubmit}
        className={`relative z-[10000] w-full max-w-lg overflow-hidden rounded-2xl border p-5 shadow-[0_24px_70px_rgba(2,3,35,0.28)] ${
          isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'
        }`}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
              <Edit2 className="h-5 w-5" />
            </span>
            <div>
              <h3 className="text-base font-semibold leading-tight">Editar nome do fluxo</h3>
              <p className={`mt-1.5 text-sm leading-relaxed ${isDark ? 'text-white/60' : 'text-brand/60'}`}>
                O nome ajuda a identificar a automação na lista e no editor.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className={agentiveIconButtonClass(isDark)}
            aria-label="Fechar modal"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-5">
          <label className={`mb-1.5 block text-sm font-medium ${isDark ? 'text-white/75' : 'text-brand/70'}`}>
            Nome da automação
          </label>
          <input
            autoFocus
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              if (error) setError('');
            }}
            placeholder="Ex: Qualificar leads do WhatsApp"
            className={agentiveInputClass(isDark, error ? 'border-red-500 focus:border-red-500 focus:ring-red-500/20' : '')}
          />
          {error && <p className="mt-2 text-xs font-medium text-red-500">{error}</p>}
        </div>

        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className={agentiveSecondaryButtonClass(isDark)}
          >
            Cancelar
          </button>
          <button type="submit" disabled={isSaving} className={agentivePrimaryButtonClass('px-4')}>
            {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {isSaving ? 'Salvando' : 'Salvar nome'}
          </button>
        </div>
      </form>
    </div>
  );
};

export default FlowRenameModal;
