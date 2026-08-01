import React, { useRef, useState } from 'react';
import { CheckCircle2, Download, FileText, Upload, X } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  agentiveIconButtonClass,
  agentivePanelClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';
import api from '../services/api.ts';

interface ImportResult {
  success: boolean;
  total_processed: number;
  contacts_created: number;
  contacts_updated: number;
  customers_created: number;
  errors: string[];
}

interface ContactsImportProps {
  onImportComplete?: (result: ImportResult) => void;
  onClose?: () => void;
}

const ContactsImport: React.FC<ContactsImportProps> = ({ onImportComplete, onClose }) => {
  const { isDark } = useTheme();
  const [isUploading, setIsUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const allowedTypes = [
      'text/csv',
      'application/vnd.ms-excel',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    ];

    if (!allowedTypes.includes(file.type) && !file.name.match(/\.(csv|xls|xlsx)$/i)) {
      setError('Formato de arquivo não suportado. Use CSV, XLS ou XLSX.');
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      setError('Arquivo muito grande. Máximo de 10MB.');
      return;
    }

    await uploadFile(file);
  };

  const uploadFile = async (file: File) => {
    try {
      setIsUploading(true);
      setError(null);
      setUploadResult(null);

      const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
      if (!companyId) {
        setError('ID da empresa não encontrado');
        return;
      }

      const formData = new FormData();
      formData.append('file', file);
      formData.append('company_id', companyId);

      const response = await api.post<ImportResult>('/webhook/contacts/import', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      setUploadResult(response.data);
      onImportComplete?.(response.data);

      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao importar arquivo');
      console.error('Erro no upload:', err);
    } finally {
      setIsUploading(false);
    }
  };

  const downloadTemplate = () => {
    const csvContent = 'nome,telefone,email,tipo,observacoes,tags\nJoão Silva,5500000000003,joao@email.com,cliente,Cliente existente da empresa,"VIP,Retorno"\nMaria Santos,5500000000005,maria@email.com,contato,Lead potencial,Instagram\nPedro Costa,5500000000006,pedro@email.com,contato,Novo contato,Indicação';
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', 'template_contatos.csv');
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <section className={agentivePanelClass(isDark, 'overflow-hidden')}>
      <div className="p-4 sm:p-5">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className={`mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${isDark ? 'text-white/40' : 'text-brand/45'}`}>
              Importação
            </div>
            <h2 className="text-lg font-semibold">Importar contatos</h2>
            <p className={`mt-1 max-w-2xl text-sm ${mutedClass}`}>
              Envie uma planilha CSV, XLS ou XLSX para criar ou atualizar contatos em lote.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button type="button" onClick={downloadTemplate} className={agentiveSecondaryButtonClass(isDark)}>
              <Download className="h-4 w-4" />
              Template
            </button>
            {onClose && (
              <button type="button" onClick={onClose} className={agentiveIconButtonClass(isDark)} aria-label="Fechar importação">
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        <div
          className={`rounded-2xl border border-dashed p-6 text-center transition-colors sm:p-8 ${
            isDark
              ? 'border-white/15 bg-white/[0.04] hover:border-white/30'
              : 'border-brand/15 bg-brand-canvas hover:border-brand/30'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xls,.xlsx"
            onChange={handleFileSelect}
            className="hidden"
            disabled={isUploading}
          />

          <div className="mx-auto flex max-w-md flex-col items-center">
            <span className={`mb-4 grid h-14 w-14 place-items-center rounded-2xl ${isDark ? 'bg-white/10 text-white/70' : 'bg-white text-brand'}`}>
              <Upload className="h-7 w-7" />
            </span>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading}
              className={agentivePrimaryButtonClass('min-h-10 px-4')}
            >
              <FileText className="h-4 w-4" />
              {isUploading ? 'Importando...' : 'Selecionar arquivo'}
            </button>
            <p className={`mt-2 text-sm ${mutedClass}`}>
              Formatos aceitos: CSV, XLS e XLSX. Tamanho máximo: 10MB.
            </p>
          </div>
        </div>

        {error && (
          <div className="mt-4">
            <AgentiveAlert title="Falha na importação" variant="error">
              {error}
            </AgentiveAlert>
          </div>
        )}

        {uploadResult && (
          <div className={`mt-4 rounded-2xl border p-4 ${isDark ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}>
            <div className="mb-3 flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5" />
              <h3 className="font-semibold">Importação concluída</h3>
            </div>
            <div className="grid gap-2 sm:grid-cols-4">
              <div className="rounded-xl bg-white/70 p-3 text-brand">
                <p className="text-xl font-semibold">{uploadResult.total_processed}</p>
                <p className="text-xs text-brand/55">processados</p>
              </div>
              <div className="rounded-xl bg-white/70 p-3 text-brand">
                <p className="text-xl font-semibold">{uploadResult.contacts_created}</p>
                <p className="text-xs text-brand/55">criados</p>
              </div>
              <div className="rounded-xl bg-white/70 p-3 text-brand">
                <p className="text-xl font-semibold">{uploadResult.contacts_updated}</p>
                <p className="text-xs text-brand/55">atualizados</p>
              </div>
              <div className="rounded-xl bg-white/70 p-3 text-brand">
                <p className="text-xl font-semibold">{uploadResult.customers_created}</p>
                <p className="text-xs text-brand/55">clientes</p>
              </div>
            </div>
            {uploadResult.errors.length > 0 && (
              <div className={`mt-3 rounded-xl border p-3 text-sm ${isDark ? 'border-white/10 bg-white/10 text-white/75' : 'border-emerald-200 bg-white text-brand/70'}`}>
                <p className="font-semibold">Erros encontrados</p>
                <ul className="mt-2 list-inside list-disc space-y-1 text-xs">
                  {uploadResult.errors.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div className={`mt-4 rounded-2xl border p-4 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
          <div className="mb-3 flex items-center gap-2">
            <span className={`grid h-8 w-8 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white/70' : 'bg-white text-brand'}`}>
              <FileText className="h-4 w-4" />
            </span>
            <p className="text-sm font-semibold">Formato esperado</p>
          </div>
          <div className={`grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3 ${mutedClass}`}>
            <p><strong>nome:</strong> nome completo do contato</p>
            <p><strong>telefone:</strong> telefone com DDD</p>
            <p><strong>email:</strong> opcional</p>
            <p><strong>tipo:</strong> contato ou cliente</p>
            <p><strong>observações:</strong> opcional</p>
            <p><strong>tags:</strong> separadas por vírgula</p>
          </div>
        </div>
      </div>
    </section>
  );
};

export default ContactsImport;
