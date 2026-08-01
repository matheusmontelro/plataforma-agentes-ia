import React, { useEffect, useState } from 'react';
import { ArrowRight, Plug } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentivePageHeader,
  agentivePageClass,
  agentivePanelClass,
  agentivePillClass,
  agentivePrimaryButtonClass,
} from '../components/AgentiveUI.tsx';
import TelegramIcon from '../components/icons/TelegramIcon.tsx';
import {
  getTelegramIntegration,
  type TelegramIntegration,
} from '../services/api.ts';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

const IntegrationsHub: React.FC = () => {
  const { isDark } = useTheme();
  const [telegram, setTelegram] = useState<TelegramIntegration | null>(null);

  useEffect(() => {
    getTelegramIntegration()
      .then(setTelegram)
      .catch(() => setTelegram(null));
  }, []);

  const isConnected = Boolean(telegram?.configured);

  return (
    <main className={agentivePageClass(isDark, 'p-4 sm:p-6')}>
      <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-4">
        <AgentivePageHeader
          icon={Plug}
          title="Integrações"
          description="Conecte apps externos usados nos canais e automações desta empresa."
        />

        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <Link to="/integrations/telegram" className="block focus:outline-none focus:ring-2 focus:ring-brand/30">
            <div className={agentivePanelClass(isDark, 'group flex h-full flex-col justify-between p-4 transition hover:-translate-y-0.5 hover:shadow-[0_18px_45px_rgba(2,3,35,0.12)]')}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <div className={cx('grid h-12 w-12 shrink-0 place-items-center rounded-2xl', isDark ? 'bg-white text-brand' : 'bg-sky-50 text-sky-600')}>
                    <TelegramIcon className="h-9 w-9" />
                  </div>
                  <div className="min-w-0">
                    <div className={cx('text-[10px] font-bold uppercase tracking-[0.16em]', isDark ? 'text-white/40' : 'text-brand/40')}>
                      Mensageria
                    </div>
                    <h2 className="mt-1 truncate text-base font-semibold">Telegram</h2>
                    <p className={cx('mt-1 text-sm leading-snug', isDark ? 'text-white/55' : 'text-brand/55')}>
                      Bot e chat padrão para nodes Msg Telegram no Flow Builder.
                    </p>
                  </div>
                </div>
                <span className={agentivePillClass(isDark, isConnected, 'shrink-0')}>
                  {isConnected ? 'Conectado' : 'Configurar'}
                </span>
              </div>

              <div className="mt-5 flex justify-end">
                <span className={agentivePrimaryButtonClass('px-3 py-2')}>
                  Abrir
                  <ArrowRight className="h-4 w-4" />
                </span>
              </div>
            </div>
          </Link>
        </section>
      </div>
    </main>
  );
};

export default IntegrationsHub;
