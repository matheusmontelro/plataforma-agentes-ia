import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'react-toastify';
import {
    CalendarDays,
    Check,
    Clock3,
    Edit2,
    Globe2,
    Link2,
    Loader2,
    Plus,
    RefreshCw,
    Search,
    ShieldCheck,
    Unlink,
    X,
} from 'lucide-react';
import { calendarApi, Agenda, AgendaCreate, Schedule } from '../services/calendar_api.ts';
import {
    createGoogleCalendarForAgenda,
    getGoogleCalendarIntegration,
    GoogleCalendarIntegration,
    GoogleCalendarOption,
    linkGoogleCalendarToAgenda,
    listGoogleCalendars,
    unlinkGoogleCalendarFromAgenda,
} from '../services/api';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
    AgentiveAlert,
    AgentiveConfirmModal,
    AgentiveEmptyState,
    agentiveIconButtonClass,
    agentiveInputClass,
    agentivePanelClass,
    agentivePillClass,
    agentivePrimaryButtonClass,
    agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';

const DAY_LABELS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];

type EditableAgenda = Partial<AgendaCreate> & { id?: number };
type ScheduleTimeField =
    | 'morning_start'
    | 'morning_end'
    | 'afternoon_start'
    | 'afternoon_end'
    | 'night_start'
    | 'night_end';

const formatMargin = (minutes?: number | null) => {
    const value = minutes ?? 180;
    if (value === 0) return 'Sem margem';
    if (value < 60) return `${value} min`;
    if (value === 60) return '1 hora';
    if (value % 1440 === 0) return `${value / 1440} dia`;
    if (value % 60 === 0) return `${value / 60} horas`;
    return `${value} min`;
};

const countScheduleDays = (agenda: Agenda) =>
    (agenda.schedules || []).filter((schedule) =>
        Boolean(
            schedule.morning_start
            || schedule.morning_end
            || schedule.afternoon_start
            || schedule.afternoon_end
            || schedule.night_start
            || schedule.night_end
        )
    ).length;

export const CalendarConfig: React.FC = () => {
    const { isDark } = useTheme();
    const [agendas, setAgendas] = useState<Agenda[]>([]);
    const [integration, setIntegration] = useState<GoogleCalendarIntegration | null>(null);
    const [googleCalendars, setGoogleCalendars] = useState<GoogleCalendarOption[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadingGoogle, setLoadingGoogle] = useState(false);
    const [saving, setSaving] = useState(false);
    const [editing, setEditing] = useState(false);
    const [searchTerm, setSearchTerm] = useState('');
    const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive'>('all');
    const [linkAgenda, setLinkAgenda] = useState<Agenda | null>(null);
    const [selectedGoogleCalendarId, setSelectedGoogleCalendarId] = useState('');
    const [isCreatingGoogleCalendar, setIsCreatingGoogleCalendar] = useState(false);
    const [newGoogleCalendarName, setNewGoogleCalendarName] = useState('');
    const [agendaToUnlink, setAgendaToUnlink] = useState<Agenda | null>(null);
    const [currentAgenda, setCurrentAgenda] = useState<EditableAgenda>({
        name: '',
        slot_duration: 30,
        active: true,
        timezone: 'America/Sao_Paulo',
        safety_margin_minutes: 180,
        schedules: [],
    });

    const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
    const tableBorderClass = isDark ? 'border-white/10' : 'border-brand/10';
    const tableHeadClass = isDark ? 'bg-white/[0.04] text-white/45' : 'bg-brand-canvas text-brand/45';

    const isGoogleConnected = Boolean(integration?.google_oauth_connected);
    const linkAgendaHasGoogleLink = Boolean(linkAgenda?.google_calendar_id);
    const linkedGoogleCalendarLabel = linkAgenda?.google_calendar_summary || linkAgenda?.google_calendar_id || '';

    const filteredAgendas = useMemo(() => {
        const normalized = searchTerm.trim().toLowerCase();

        return agendas.filter((agenda) => {
            const matchesSearch = !normalized
                || agenda.name.toLowerCase().includes(normalized)
                || (agenda.google_calendar_summary || '').toLowerCase().includes(normalized);
            const matchesStatus =
                statusFilter === 'all'
                || (statusFilter === 'active' && agenda.active)
                || (statusFilter === 'inactive' && !agenda.active);

            return matchesSearch && matchesStatus;
        });
    }, [agendas, searchTerm, statusFilter]);

    const loadAgendas = useCallback(async () => {
        const data = await calendarApi.listAgendas();
        setAgendas(data);
    }, []);

    const loadGoogle = useCallback(async () => {
        setLoadingGoogle(true);
        try {
            const data = await getGoogleCalendarIntegration();
            setIntegration(data);
            if (data.google_oauth_connected) {
                const items = await listGoogleCalendars();
                setGoogleCalendars(items);
            } else {
                setGoogleCalendars([]);
            }
        } catch (error: any) {
            setGoogleCalendars([]);
            toast.error(error.message || 'Erro ao carregar Google Agenda.');
        } finally {
            setLoadingGoogle(false);
        }
    }, []);

    const loadAll = useCallback(async () => {
        setLoading(true);
        try {
            await Promise.all([loadAgendas(), loadGoogle()]);
        } catch (error) {
            toast.error('Erro ao carregar agendas.');
        } finally {
            setLoading(false);
        }
    }, [loadAgendas, loadGoogle]);

    useEffect(() => {
        loadAll();
    }, [loadAll]);

    const resetForm = () => {
        setCurrentAgenda({
            name: '',
            slot_duration: 30,
            active: true,
            timezone: 'America/Sao_Paulo',
            safety_margin_minutes: 180,
            schedules: [],
        });
    };

    const handleEdit = (agenda: Agenda) => {
        setCurrentAgenda({
            ...agenda,
            schedules: agenda.schedules || [],
        });
        setEditing(true);
    };

    const handleNew = () => {
        resetForm();
        setEditing(true);
    };

    const handleSave = async () => {
        if (!currentAgenda.name || !currentAgenda.slot_duration) {
            toast.error('Preencha os campos obrigatórios.');
            return;
        }

        setSaving(true);
        try {
            const payload = {
                ...currentAgenda,
                schedules: currentAgenda.schedules || [],
            } as AgendaCreate;

            if (currentAgenda.id) {
                await calendarApi.updateAgenda(currentAgenda.id, payload);
                toast.success('Agenda atualizada com sucesso.');
            } else {
                await calendarApi.createAgenda(payload);
                toast.success('Agenda criada com sucesso.');
            }

            setEditing(false);
            resetForm();
            await loadAgendas();
        } catch (error) {
            toast.error('Erro ao salvar agenda.');
        } finally {
            setSaving(false);
        }
    };

    const openLinkModal = (agenda: Agenda) => {
        setLinkAgenda(agenda);
        setSelectedGoogleCalendarId(agenda.google_calendar_id ? '' : googleCalendars[0]?.id || '');
        setIsCreatingGoogleCalendar(false);
        setNewGoogleCalendarName('');
    };

    const closeLinkModal = () => {
        setLinkAgenda(null);
        setIsCreatingGoogleCalendar(false);
        setNewGoogleCalendarName('');
    };

    const handleLinkExisting = async () => {
        if (linkAgenda?.google_calendar_id) {
            toast.error('Desvincule a agenda Google atual antes de vincular outra.');
            return;
        }

        if (!linkAgenda || !selectedGoogleCalendarId) {
            toast.error('Selecione uma agenda Google.');
            return;
        }

        setSaving(true);
        try {
            await linkGoogleCalendarToAgenda(linkAgenda.id, selectedGoogleCalendarId);
            toast.success('Agenda vinculada ao Google Agenda.');
            closeLinkModal();
            await Promise.all([loadAgendas(), loadGoogle()]);
        } catch (error: any) {
            toast.error(error.message || 'Erro ao vincular agenda Google.');
        } finally {
            setSaving(false);
        }
    };

    const handleCreateAndLink = async () => {
        if (linkAgenda?.google_calendar_id) {
            toast.error('Desvincule a agenda Google atual antes de criar outro vínculo.');
            return;
        }

        if (!linkAgenda || !newGoogleCalendarName.trim()) {
            toast.error('Informe um nome para a nova agenda Google.');
            return;
        }

        setSaving(true);
        try {
            await createGoogleCalendarForAgenda(linkAgenda.id, newGoogleCalendarName.trim());
            toast.success('Agenda Google criada e vinculada.');
            closeLinkModal();
            await Promise.all([loadAgendas(), loadGoogle()]);
        } catch (error: any) {
            toast.error(error.message || 'Erro ao criar agenda Google.');
        } finally {
            setSaving(false);
        }
    };

    const handleUnlink = async () => {
        if (!agendaToUnlink) return;

        setSaving(true);
        try {
            await unlinkGoogleCalendarFromAgenda(agendaToUnlink.id);
            toast.success('Agenda Google desvinculada.');
            setAgendaToUnlink(null);
            await loadAgendas();
        } catch (error: any) {
            toast.error(error.message || 'Erro ao desvincular agenda Google.');
        } finally {
            setSaving(false);
        }
    };

    const handleScheduleChange = (dayIndex: number, field: ScheduleTimeField, value: string) => {
        const schedules = [...(currentAgenda.schedules || [])];
        let daySchedule = schedules.find(s => s.day_of_week === dayIndex);

        if (!daySchedule) {
            daySchedule = { day_of_week: dayIndex };
            schedules.push(daySchedule);
        }

        daySchedule[field] = value === '' ? null : value;
        setCurrentAgenda({ ...currentAgenda, schedules });
    };

    const getScheduleValue = (dayIndex: number, field: ScheduleTimeField) => {
        const sched = currentAgenda.schedules?.find(s => s.day_of_week === dayIndex);
        return sched ? (sched[field] as string) || '' : '';
    };

    if (loading) {
        return (
            <div className={agentivePanelClass(isDark, 'p-8')}>
                <div className="flex items-center justify-center gap-3">
                    <Loader2 className="h-5 w-5 animate-spin" />
                    <span className="text-sm font-medium">Carregando agendas</span>
                </div>
            </div>
        );
    }

    if (editing) {
        return (
            <div className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
                <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                        <div className={`mb-1 text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>
                            {currentAgenda.id ? 'Editar' : 'Criar'}
                        </div>
                        <h2 className="text-xl font-semibold">{currentAgenda.id ? 'Editar agenda' : 'Nova agenda'}</h2>
                        <p className={`mt-1 text-sm ${mutedClass}`}>Ajuste regras de disponibilidade, duração e fuso desta agenda local.</p>
                    </div>
                    <label className={`inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-semibold ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
                        <input
                            type="checkbox"
                            className="h-4 w-4 rounded border-brand/20 text-brand focus:ring-brand/20"
                            checked={currentAgenda.active}
                            onChange={e => setCurrentAgenda({ ...currentAgenda, active: e.target.checked })}
                        />
                        Agenda ativa
                    </label>
                </div>

                <div className="mb-6 grid gap-4 lg:grid-cols-2">
                    <div>
                        <label className={`mb-1.5 block text-sm font-medium ${isDark ? 'text-white/75' : 'text-brand/70'}`}>Nome da agenda</label>
                        <input
                            type="text"
                            className={agentiveInputClass(isDark)}
                            value={currentAgenda.name || ''}
                            onChange={e => setCurrentAgenda({ ...currentAgenda, name: e.target.value })}
                        />
                    </div>
                    <div>
                        <label className={`mb-1.5 block text-sm font-medium ${isDark ? 'text-white/75' : 'text-brand/70'}`}>Duração do slot</label>
                        <select
                            className={agentiveInputClass(isDark)}
                            value={currentAgenda.slot_duration}
                            onChange={e => setCurrentAgenda({ ...currentAgenda, slot_duration: parseInt(e.target.value, 10) })}
                        >
                            <option value={15}>15 minutos</option>
                            <option value={30}>30 minutos</option>
                            <option value={45}>45 minutos</option>
                            <option value={60}>60 minutos</option>
                        </select>
                    </div>

                    <div>
                        <label className={`mb-1.5 block text-sm font-medium ${isDark ? 'text-white/75' : 'text-brand/70'}`}>Fuso horário</label>
                        <select
                            className={agentiveInputClass(isDark)}
                            value={currentAgenda.timezone || 'America/Sao_Paulo'}
                            onChange={e => setCurrentAgenda({ ...currentAgenda, timezone: e.target.value })}
                        >
                            <option value="America/Sao_Paulo">Brasília (BRT) - America/Sao_Paulo</option>
                            <option value="America/Manaus">Manaus (AMT) - America/Manaus</option>
                            <option value="America/Belem">Belém (BRT) - America/Belem</option>
                            <option value="America/Fortaleza">Fortaleza (BRT) - America/Fortaleza</option>
                            <option value="America/Recife">Recife (BRT) - America/Recife</option>
                            <option value="America/Cuiaba">Cuiabá (AMT) - America/Cuiaba</option>
                            <option value="America/Porto_Velho">Porto Velho (AMT) - America/Porto_Velho</option>
                            <option value="America/Boa_Vista">Boa Vista (AMT) - America/Boa_Vista</option>
                            <option value="America/Maceio">Maceió (BRT) - America/Maceio</option>
                            <option value="America/Bahia">Salvador (BRT) - America/Bahia</option>
                            <option value="America/Rio_Branco">Rio Branco (ACT) - America/Rio_Branco</option>
                            <option value="America/Noronha">Fernando de Noronha (FNT) - America/Noronha</option>
                        </select>
                    </div>

                    <div>
                        <label className={`mb-1.5 block text-sm font-medium ${isDark ? 'text-white/75' : 'text-brand/70'}`}>Margem de segurança</label>
                        <select
                            className={agentiveInputClass(isDark)}
                            value={currentAgenda.safety_margin_minutes ?? 180}
                            onChange={e => setCurrentAgenda({ ...currentAgenda, safety_margin_minutes: parseInt(e.target.value, 10) })}
                        >
                            <option value={0}>Sem margem (imediato)</option>
                            <option value={30}>30 minutos</option>
                            <option value={60}>1 hora</option>
                            <option value={120}>2 horas</option>
                            <option value={180}>3 horas</option>
                            <option value={240}>4 horas</option>
                            <option value={1440}>24 horas</option>
                        </select>
                    </div>
                </div>

                <div className={`overflow-hidden rounded-2xl border ${tableBorderClass}`}>
                    <div className={`flex items-center gap-2 border-b px-4 py-3 ${tableBorderClass} ${isDark ? 'bg-white/[0.04]' : 'bg-brand-canvas'}`}>
                        <ShieldCheck className={`h-4 w-4 ${isDark ? 'text-white/55' : 'text-brand/55'}`} />
                        <span className="text-sm font-semibold">Janelas de atendimento</span>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="min-w-[760px] w-full divide-y divide-brand/10 text-sm">
                            <thead className={tableHeadClass}>
                                <tr className="text-left text-[10px] font-bold uppercase tracking-[0.16em]">
                                    <th className="px-3 py-2">Dia</th>
                                    <th className="px-3 py-2 text-center" colSpan={2}>Manhã</th>
                                    <th className="px-3 py-2 text-center" colSpan={2}>Tarde</th>
                                    <th className="px-3 py-2 text-center" colSpan={2}>Noite</th>
                                </tr>
                                <tr className="text-center text-[10px] font-medium">
                                    <th />
                                    <th className="pb-2">Início</th>
                                    <th className="pb-2">Fim</th>
                                    <th className="pb-2">Início</th>
                                    <th className="pb-2">Fim</th>
                                    <th className="pb-2">Início</th>
                                    <th className="pb-2">Fim</th>
                                </tr>
                            </thead>
                            <tbody className={`divide-y ${isDark ? 'divide-white/10' : 'divide-brand/10'}`}>
                                {DAY_LABELS.map((day, index) => (
                                    <tr key={day} className={isDark ? 'hover:bg-white/[0.04]' : 'hover:bg-brand-canvas/70'}>
                                        <td className="whitespace-nowrap px-3 py-2 font-semibold">{day}</td>
                                        {(['morning_start', 'morning_end', 'afternoon_start', 'afternoon_end', 'night_start', 'night_end'] as ScheduleTimeField[]).map((field) => (
                                            <td key={field} className="px-1 py-1">
                                                <input
                                                    type="time"
                                                    className={agentiveInputClass(isDark, 'min-w-[92px] px-2 py-1.5 text-xs')}
                                                    value={getScheduleValue(index, field)}
                                                    onChange={e => handleScheduleChange(index, field, e.target.value)}
                                                />
                                            </td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>

                <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                    <button
                        type="button"
                        onClick={() => {
                            setEditing(false);
                            resetForm();
                        }}
                        disabled={saving}
                        className={agentiveSecondaryButtonClass(isDark)}
                    >
                        Cancelar
                    </button>
                    <button type="button" onClick={handleSave} disabled={saving} className={agentivePrimaryButtonClass('px-4')}>
                        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                        {currentAgenda.id ? 'Atualizar agenda' : 'Salvar agenda'}
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className={agentivePanelClass(isDark, 'min-w-0 overflow-hidden')}>
            <div className={`border-b p-4 sm:p-5 ${tableBorderClass}`}>
                <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
                    <div>
                        <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>Gerenciamento</p>
                        <h2 className="mt-1 text-lg font-semibold">Agendas locais</h2>
                        <p className={`mt-1 text-sm ${mutedClass}`}>
                            {filteredAgendas.length} de {agendas.length} agendas exibidas.
                        </p>
                    </div>

                    <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                        <button
                            type="button"
                            onClick={loadAll}
                            disabled={loading || loadingGoogle}
                            className={agentiveSecondaryButtonClass(isDark)}
                        >
                            {loadingGoogle ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                            Atualizar
                        </button>
                        <div className="relative min-w-0 lg:w-72">
                            <Search className={`pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${isDark ? 'text-white/35' : 'text-brand/35'}`} />
                            <input
                                type="search"
                                value={searchTerm}
                                onChange={(event) => setSearchTerm(event.target.value)}
                                placeholder="Buscar agenda"
                                className={agentiveInputClass(isDark, 'pl-9')}
                            />
                        </div>
                        <div className={`flex items-center gap-1 rounded-2xl border p-1 ${isDark ? 'border-white/10 bg-black/15' : 'border-brand/10 bg-brand-canvas'}`}>
                            {[
                                { id: 'all' as const, label: 'Todas' },
                                { id: 'active' as const, label: 'Ativas' },
                                { id: 'inactive' as const, label: 'Inativas' },
                            ].map((option) => (
                                <button
                                    key={option.id}
                                    type="button"
                                    onClick={() => setStatusFilter(option.id)}
                                    className={agentivePillClass(isDark, statusFilter === option.id, 'border-transparent')}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                        <button type="button" onClick={handleNew} className={agentivePrimaryButtonClass('min-h-10 px-4')}>
                            <Plus className="h-4 w-4" />
                            Nova agenda
                        </button>
                    </div>
                </div>
            </div>

            {!isGoogleConnected && (
                <div className="px-4 pt-4 sm:px-5">
                    <AgentiveAlert variant="info" title="Google Agenda não conectado">
                        Conecte o Google na aba Integrações para vincular agendas locais a calendários Google.
                    </AgentiveAlert>
                </div>
            )}

            <div className="p-3 sm:p-4">
                {agendas.length === 0 ? (
                    <AgentiveEmptyState
                        icon={CalendarDays}
                        title="Nenhuma agenda configurada"
                        description="Crie uma agenda local para definir horários, duração e vínculo com Google Agenda."
                        action={(
                            <button type="button" onClick={handleNew} className={agentivePrimaryButtonClass('px-4')}>
                                <Plus className="h-4 w-4" />
                                Criar agenda
                            </button>
                        )}
                    />
                ) : filteredAgendas.length === 0 ? (
                    <AgentiveEmptyState
                        icon={Search}
                        title="Nenhuma agenda encontrada"
                        description="Ajuste a busca ou o filtro de status para encontrar outra agenda."
                    />
                ) : (
                    <div className={`overflow-hidden rounded-2xl border ${tableBorderClass}`}>
                        <div className="overflow-x-auto">
                            <table className="min-w-[960px] w-full border-collapse text-sm">
                                <thead className={tableHeadClass}>
                                    <tr className="text-left text-[10px] font-bold uppercase tracking-[0.16em]">
                                        <th className="px-4 py-3">Agenda</th>
                                        <th className="px-4 py-3">Status</th>
                                        <th className="px-4 py-3">Duração</th>
                                        <th className="px-4 py-3">Fuso</th>
                                        <th className="px-4 py-3">Margem</th>
                                        <th className="px-4 py-3">Google Agenda</th>
                                        <th className="px-4 py-3 text-right">Ações</th>
                                    </tr>
                                </thead>
                                <tbody className={`divide-y ${isDark ? 'divide-white/10' : 'divide-brand/10'}`}>
                                    {filteredAgendas.map((agenda) => {
                                        const hasGoogleLink = Boolean(agenda.google_calendar_id);
                                        return (
                                            <tr key={agenda.id} className={isDark ? 'hover:bg-white/[0.06]' : 'hover:bg-brand-canvas'}>
                                                <td className="px-4 py-3">
                                                    <div className="flex min-w-0 items-center gap-3">
                                                        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${agenda.active ? 'bg-emerald-500/10 text-emerald-600' : isDark ? 'bg-white/10 text-white/70' : 'bg-brand-canvas text-brand/70'}`}>
                                                            <CalendarDays className="h-4 w-4" />
                                                        </span>
                                                        <div className="min-w-0">
                                                            <p className="truncate font-semibold">{agenda.name}</p>
                                                            <p className={`mt-0.5 text-xs ${isDark ? 'text-white/45' : 'text-brand/45'}`}>
                                                                {countScheduleDays(agenda)} dias com janelas
                                                            </p>
                                                        </div>
                                                    </div>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <span className={agentivePillClass(isDark, agenda.active)}>
                                                        {agenda.active ? 'Ativa' : 'Inativa'}
                                                    </span>
                                                </td>
                                                <td className={`px-4 py-3 font-medium ${mutedClass}`}>
                                                    <span className="inline-flex items-center gap-2">
                                                        <Clock3 className="h-4 w-4 opacity-60" />
                                                        {agenda.slot_duration} min
                                                    </span>
                                                </td>
                                                <td className={`px-4 py-3 ${mutedClass}`}>
                                                    <span className="inline-flex items-center gap-2">
                                                        <Globe2 className="h-4 w-4 opacity-60" />
                                                        {agenda.timezone || 'America/Sao_Paulo'}
                                                    </span>
                                                </td>
                                                <td className={`px-4 py-3 ${mutedClass}`}>{formatMargin(agenda.safety_margin_minutes)}</td>
                                                <td className="px-4 py-3">
                                                    {hasGoogleLink ? (
                                                        <span className={`block max-w-[260px] truncate text-sm font-medium ${isDark ? 'text-white/85' : 'text-brand'}`} title={agenda.google_calendar_summary || agenda.google_calendar_id || undefined}>
                                                            {agenda.google_calendar_summary || agenda.google_calendar_id}
                                                        </span>
                                                    ) : (
                                                        <span className={agentivePillClass(isDark)}>
                                                            Sem vínculo
                                                        </span>
                                                    )}
                                                </td>
                                                <td className="px-4 py-3">
                                                    <div className="flex items-center justify-end gap-2">
                                                        <button type="button" onClick={() => handleEdit(agenda)} className={agentiveIconButtonClass(isDark, 'primary')} title="Editar agenda">
                                                            <Edit2 className="h-4 w-4" />
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={() => openLinkModal(agenda)}
                                                            disabled={!isGoogleConnected && !hasGoogleLink}
                                                            className={agentiveIconButtonClass(isDark, hasGoogleLink ? 'warning' : 'success')}
                                                            title={hasGoogleLink ? 'Ver vínculo Google' : 'Vincular Google Agenda'}
                                                        >
                                                            <Link2 className="h-4 w-4" />
                                                        </button>
                                                        {hasGoogleLink && (
                                                            <button type="button" onClick={() => setAgendaToUnlink(agenda)} className={agentiveIconButtonClass(isDark, 'danger')} title="Desvincular Google Agenda">
                                                                <Unlink className="h-4 w-4" />
                                                            </button>
                                                        )}
                                                    </div>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            </div>

            {linkAgenda && (
                <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
                    <div className="fixed inset-0 bg-brand/55 backdrop-blur-sm" onClick={saving ? undefined : closeLinkModal} />
                    <div className={`relative z-[10000] w-full max-w-xl overflow-hidden rounded-2xl border p-5 shadow-[0_24px_70px_rgba(2,3,35,0.28)] ${isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'}`}>
                        <div className="flex items-start justify-between gap-4">
                            <div className="flex items-start gap-3">
                                <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                                    <Link2 className="h-5 w-5" />
                                </span>
                                <div>
                                    <h3 className="text-base font-semibold leading-tight">Vincular Google Agenda</h3>
                                    <p className={`mt-1.5 text-sm leading-relaxed ${mutedClass}`}>
                                        {linkAgenda.name}
                                    </p>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={closeLinkModal}
                                disabled={saving}
                                className={agentiveIconButtonClass(isDark)}
                                aria-label="Fechar modal"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        <div className="mt-5">
                            {linkAgendaHasGoogleLink ? (
                                <div className={`rounded-2xl border p-4 ${isDark ? 'border-amber-400/20 bg-amber-400/10' : 'border-amber-200 bg-amber-50'}`}>
                                    <p className={`text-sm font-semibold ${isDark ? 'text-amber-100' : 'text-amber-900'}`}>Esta agenda já tem um vínculo Google</p>
                                    <p className={`mt-2 text-sm leading-relaxed ${isDark ? 'text-amber-100/75' : 'text-amber-900/70'}`}>
                                        Para trocar por outra agenda Google, desvincule o vínculo atual e depois vincule novamente usando uma agenda disponível na integração.
                                    </p>
                                    <div className={`mt-4 rounded-xl border px-3 py-2 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-amber-200/70 bg-white/70'}`}>
                                        <p className={`text-[10px] font-bold uppercase tracking-[0.16em] ${isDark ? 'text-white/35' : 'text-brand/35'}`}>Vínculo atual</p>
                                        <p className="mt-1 truncate text-sm font-semibold" title={linkedGoogleCalendarLabel || undefined}>
                                            {linkedGoogleCalendarLabel}
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => {
                                            if (!linkAgenda) return;
                                            const agenda = linkAgenda;
                                            closeLinkModal();
                                            setAgendaToUnlink(agenda);
                                        }}
                                        disabled={saving}
                                        className={agentiveSecondaryButtonClass(isDark, 'mt-4')}
                                    >
                                        <Unlink className="h-4 w-4" />
                                        Desvincular vínculo atual
                                    </button>
                                </div>
                            ) : (
                                <div className="space-y-5">
                                    <div>
                                        <label className={`mb-1.5 block text-sm font-medium ${isDark ? 'text-white/75' : 'text-brand/70'}`}>Agenda Google existente</label>
                                        <select
                                            value={selectedGoogleCalendarId}
                                            onChange={event => setSelectedGoogleCalendarId(event.target.value)}
                                            disabled={saving || loadingGoogle || googleCalendars.length === 0}
                                            className={agentiveInputClass(isDark)}
                                        >
                                            <option value="">{loadingGoogle ? 'Carregando agendas...' : 'Selecione uma agenda Google'}</option>
                                            {googleCalendars.map((calendar) => (
                                                <option key={calendar.id} value={calendar.id}>
                                                    {calendar.summary || calendar.id}{calendar.primary ? ' (principal)' : ''}
                                                </option>
                                            ))}
                                        </select>
                                        <p className={`mt-1.5 text-xs ${mutedClass}`}>
                                            A lista mostra apenas agendas disponíveis na conta Google conectada em Integrações.
                                        </p>
                                        <button type="button" onClick={handleLinkExisting} disabled={saving || !selectedGoogleCalendarId} className={agentiveSecondaryButtonClass(isDark, 'mt-3')}>
                                            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
                                            Vincular existente
                                        </button>
                                    </div>

                                    <div className={`rounded-2xl border p-4 ${isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-brand-canvas'}`}>
                                        {!isCreatingGoogleCalendar ? (
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    setIsCreatingGoogleCalendar(true);
                                                    setNewGoogleCalendarName('');
                                                }}
                                                disabled={saving}
                                                className={agentiveSecondaryButtonClass(isDark)}
                                            >
                                                <Plus className="h-4 w-4" />
                                                Criar nova agenda Google
                                            </button>
                                        ) : (
                                            <div>
                                                <div className="mb-3 flex items-start justify-between gap-3">
                                                    <label className={`block text-sm font-medium ${isDark ? 'text-white/75' : 'text-brand/70'}`}>Nome da nova agenda Google</label>
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            setIsCreatingGoogleCalendar(false);
                                                            setNewGoogleCalendarName('');
                                                        }}
                                                        disabled={saving}
                                                        className={`text-xs font-semibold transition-colors ${isDark ? 'text-white/50 hover:text-white' : 'text-brand/50 hover:text-brand'}`}
                                                    >
                                                        Cancelar
                                                    </button>
                                                </div>
                                                <input
                                                    autoFocus
                                                    value={newGoogleCalendarName}
                                                    onChange={event => setNewGoogleCalendarName(event.target.value)}
                                                    disabled={saving}
                                                    placeholder="Digite o nome da agenda"
                                                    className={agentiveInputClass(isDark)}
                                                />
                                                <button type="button" onClick={handleCreateAndLink} disabled={saving || !newGoogleCalendarName.trim()} className={agentivePrimaryButtonClass('mt-3 px-4')}>
                                                    {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                                                    Criar e vincular
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            <AgentiveConfirmModal
                cancelText="Manter vínculo"
                confirmText="Desvincular"
                isLoading={saving}
                isOpen={Boolean(agendaToUnlink)}
                message={(
                    <>
                        A agenda local <strong>{agendaToUnlink?.name}</strong> deixará de criar novos eventos nesse Google Agenda. Eventos já existentes no Google não serão apagados.
                    </>
                )}
                onClose={() => setAgendaToUnlink(null)}
                onConfirm={handleUnlink}
                title="Desvincular Google Agenda?"
                variant="warning"
            />
        </div>
    );
};
