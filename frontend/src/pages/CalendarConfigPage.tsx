import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { Calendar as CalendarIcon, Clock, Link2 } from 'lucide-react';
import { CalendarConfig } from '../components/CalendarConfig.tsx';
import { CalendarView } from '../components/CalendarView.tsx';
import AgendaIntegration from './AgendaIntegration.tsx';
import { useTheme } from '../contexts/ThemeContext.tsx';

type AgendaTab = 'calendar' | 'hours' | 'integrations';

const tabs: Array<{
    id: AgendaTab;
    label: string;
    description: string;
    icon: React.ComponentType<{ className?: string }>;
}> = [
    { id: 'calendar', label: 'Calendário', description: 'Dia e semana', icon: CalendarIcon },
    { id: 'hours', label: 'Agendas e horários', description: 'Disponibilidade', icon: Clock },
    { id: 'integrations', label: 'Integrações', description: 'Google e conectores', icon: Link2 },
];

const normalizeTab = (tab: string | null): AgendaTab => {
    if (tab === 'hours' || tab === 'integrations') return tab;
    return 'calendar';
};

const CalendarConfigPage: React.FC = () => {
    const { isDark } = useTheme();
    const [searchParams, setSearchParams] = useSearchParams();
    const activeTab = normalizeTab(searchParams.get('tab'));

    const setActiveTab = (tab: AgendaTab) => {
        const nextParams = new URLSearchParams(searchParams);

        if (tab === 'calendar') {
            nextParams.delete('tab');
        } else {
            nextParams.set('tab', tab);
        }

        setSearchParams(nextParams, { replace: true });
    };

    const pageClass = isDark ? 'bg-brand text-white' : 'bg-brand-canvas text-brand';
    const panelClass = isDark
        ? 'border-white/10 bg-white/[0.06] shadow-[0_22px_55px_rgba(0,0,0,0.22)]'
        : 'border-brand/10 bg-white shadow-[0_22px_55px_rgba(2,3,35,0.08)]';
    const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';

    return (
        <div className={`flex min-h-screen w-full justify-center px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10 2xl:px-12 ${pageClass}`}>
            <div className="w-full max-w-screen-2xl space-y-5">
                <div className={`rounded-2xl border p-4 sm:p-5 ${panelClass}`}>
                    <div className="grid gap-4 xl:grid-cols-[minmax(260px,1fr)_auto] xl:items-end">
                        <div>
                            <div className={`mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] ${mutedClass}`}>
                                Operacional
                            </div>
                            <h1 className="text-2xl font-semibold sm:text-3xl">Agenda</h1>
                            <p className={`mt-1 max-w-2xl text-sm ${mutedClass}`}>
                                Calendário, horários por agenda, fuso e integrações.
                            </p>
                        </div>

                        <div className={`grid w-full grid-cols-3 gap-1 rounded-2xl border p-1.5 xl:w-[520px] ${isDark ? 'border-white/10 bg-black/15' : 'border-brand/10 bg-brand-canvas'}`}>
                            {tabs.map((tab) => {
                                const Icon = tab.icon;
                                const isActive = activeTab === tab.id;

                                return (
                                    <button
                                        key={tab.id}
                                        type="button"
                                        onClick={() => setActiveTab(tab.id)}
                                        className={`group flex min-w-0 items-center gap-2 rounded-xl border px-2 py-2 text-left transition-all duration-200 sm:px-3 ${
                                            isActive
                                                ? isDark
                                                    ? 'border-white bg-white text-brand shadow-[0_10px_24px_rgba(255,255,255,0.08)]'
                                                    : 'border-brand bg-brand text-white shadow-[0_10px_24px_rgba(2,3,35,0.12)]'
                                                : isDark
                                                    ? 'border-transparent text-white/55 hover:border-white/10 hover:bg-white/[0.06] hover:text-white'
                                                    : 'border-transparent text-brand/55 hover:border-brand/10 hover:bg-white hover:text-brand'
                                        }`}
                                    >
                                        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors ${
                                            isActive
                                                ? isDark
                                                    ? 'bg-brand text-white'
                                                    : 'bg-white text-brand'
                                                : isDark
                                                    ? 'bg-white/10 text-white/55 group-hover:text-white'
                                                    : 'bg-white text-brand/50 group-hover:text-brand'
                                        }`}>
                                            <Icon className="h-4 w-4" />
                                        </span>
                                        <span className="min-w-0">
                                            <span className="block truncate text-xs font-semibold sm:text-sm">{tab.label}</span>
                                            <span className={`hidden truncate text-[10px] leading-tight sm:block ${
                                                isActive
                                                    ? isDark ? 'text-brand/55' : 'text-white/60'
                                                    : isDark ? 'text-white/35' : 'text-brand/35'
                                            }`}>
                                                {tab.description}
                                            </span>
                                        </span>
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                </div>

                <div className="min-w-0">
                    {activeTab === 'calendar' && <CalendarView />}
                    {activeTab === 'hours' && <CalendarConfig />}
                    {activeTab === 'integrations' && <AgendaIntegration embedded />}
                </div>
            </div>
        </div>
    );
};

export default CalendarConfigPage;
