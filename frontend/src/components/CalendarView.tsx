
import React, { useState, useEffect } from 'react';
import { Agenda, calendarApi, Schedule } from '../services/calendar_api.ts';
import api from '../services/api.ts';
import { toast } from 'react-toastify';
import { startOfWeek, addDays, format, endOfDay, startOfDay } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import { formatInTimeZone } from 'date-fns-tz';
import { CalendarDays, ChevronLeft, ChevronRight, Clock3, Lock } from 'lucide-react';
import AppointmentBookingModal from './AppointmentBookingModal.tsx';

interface Agendamento {
    id: number;
    agenda_id: number;
    consulta_data: string; // ISO string
    nome: string;
    phone: string;
    midia?: string;
    interesse?: string;
    status: string;
}

interface CalendarViewProps { }

const DEFAULT_TIMEZONE = 'America/Sao_Paulo';
const DATE_TIME_KEY_FORMAT = 'yyyy-MM-dd HH:mm';
const DATE_KEY_FORMAT = 'yyyy-MM-dd';
const SCHEDULE_PERIODS: Array<[keyof Schedule, keyof Schedule]> = [
    ['morning_start', 'morning_end'],
    ['afternoon_start', 'afternoon_end'],
    ['night_start', 'night_end'],
];

type TimeWindow = {
    start: number;
    end: number;
};

const formatNowInTimezone = (timezone?: string) => {
    try {
        return formatInTimeZone(new Date(), timezone || DEFAULT_TIMEZONE, DATE_TIME_KEY_FORMAT);
    } catch {
        return format(new Date(), DATE_TIME_KEY_FORMAT);
    }
};

const formatTodayInTimezone = (timezone?: string) => {
    try {
        return formatInTimeZone(new Date(), timezone || DEFAULT_TIMEZONE, DATE_KEY_FORMAT);
    } catch {
        return format(new Date(), DATE_KEY_FORMAT);
    }
};

const formatIsoInTimezone = (value: string, timezone: string | undefined, pattern: string) => {
    const date = new Date(value);

    if (Number.isNaN(date.getTime())) return '';

    try {
        return formatInTimeZone(date, timezone || DEFAULT_TIMEZONE, pattern);
    } catch {
        return format(date, pattern);
    }
};

const formatPeriodLabel = (date: Date, viewMode: 'week' | 'day') => {
    if (viewMode === 'day') {
        return format(date, "EEEE, dd 'de' MMMM 'de' yyyy", { locale: ptBR });
    }

    const start = startOfWeek(date, { weekStartsOn: 0 });
    const end = addDays(start, 6);

    if (format(start, 'yyyy-MM') === format(end, 'yyyy-MM')) {
        return `${format(start, 'dd', { locale: ptBR })} - ${format(end, "dd 'de' MMMM 'de' yyyy", { locale: ptBR })}`;
    }

    return `${format(start, "dd 'de' MMM", { locale: ptBR })} - ${format(end, "dd 'de' MMM 'de' yyyy", { locale: ptBR })}`;
};

const getAgendaDayIndex = (date: Date) => (date.getDay() + 6) % 7;

const parseTimeToMinutes = (value?: string | null) => {
    if (!value) return null;

    const [hours, minutes] = value.split(':').map(Number);

    if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return null;

    return hours * 60 + minutes;
};

const minutesToTimeLabel = (minutes: number) => {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;

    return `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}`;
};

const getScheduleWindows = (schedule?: Schedule): TimeWindow[] => {
    if (!schedule) return [];

    return SCHEDULE_PERIODS
        .map(([startField, endField]) => {
            const start = parseTimeToMinutes(schedule[startField] as string | null | undefined);
            const end = parseTimeToMinutes(schedule[endField] as string | null | undefined);

            if (start === null || end === null || end <= start) return null;

            return { start, end };
        })
        .filter((window): window is TimeWindow => Boolean(window));
};

const slotFitsWindow = (slotMinutes: number, duration: number, windows: TimeWindow[]) => (
    windows.some(window => slotMinutes >= window.start && slotMinutes + duration <= window.end)
);

export const CalendarView: React.FC<CalendarViewProps> = () => {
    const [agendas, setAgendas] = useState<Agenda[]>([]);
    const [selectedAgendaId, setSelectedAgendaId] = useState<number | null>(null);
    const [selectedAgenda, setSelectedAgenda] = useState<Agenda | null>(null);
    const [currentDate, setCurrentDate] = useState(new Date());
    const [viewMode, setViewMode] = useState<'week' | 'day'>('week');
    const [agendamentos, setAgendamentos] = useState<Agendamento[]>([]);

    // Modal states
    const [showModal, setShowModal] = useState(false);
    const [selectedSlot, setSelectedSlot] = useState<Date | null>(null);

    useEffect(() => {
        loadAgendas();
    }, []);

    useEffect(() => {
        if (selectedAgendaId) {
            const agenda = agendas.find(a => a.id === selectedAgendaId);
            setSelectedAgenda(agenda || null);
            fetchAgendamentos();
        }
    }, [selectedAgendaId, currentDate, viewMode]);

    const loadAgendas = async () => {
        try {
            const data = await calendarApi.listAgendas();
            setAgendas(data);
            if (data.length > 0 && !selectedAgendaId) {
                setSelectedAgendaId(data[0].id);
            }
        } catch (error) {
            toast.error("Erro ao carregar agendas");
        }
    };

    const fetchAgendamentos = async () => {
        const clientId = getUserId();
        const companyId = getCompanyId();

        if (!selectedAgendaId || !clientId || !companyId) {
            console.warn("[CalendarView] Missing params (agenda, client or company), skipping fetch.", { selectedAgendaId, clientId, companyId });
            return;
        }

        // Calculate start/end dates for the view
        let startDate = startOfDay(currentDate);
        let endDate = endOfDay(currentDate);

        if (viewMode === 'week') {
            startDate = startOfWeek(currentDate, { weekStartsOn: 0 }); // Sunday start or Monday? Brazil usually Monday(1) or Sunday(0)
            endDate = endOfDay(addDays(startDate, 6));
        }

        console.log(`[CalendarView] Fetching appointments for Agenda: ${selectedAgendaId} `, {
            startDate: startDate.toISOString(),
            endDate: endDate.toISOString(),
            viewMode
        });

        // Just fetching broad range for now. The API should support range filtering.
        // Assuming update done in backend: ?agenda_id=X&start_date=Y&end_date=Z
        try {
            const url = `/api/agenda/clients/${clientId}/companies/${companyId}/agendamentos`;
            console.log(`[CalendarView] Requesting URL: ${url}`);

            // Using direct axios call or we need to add to calendar_api/agendamento_api
            const response = await api.get(url, {
                params: {
                    agenda_id: selectedAgendaId,
                    start_date: startDate.toISOString(),
                    end_date: endDate.toISOString()
                }
            });
            console.log("[CalendarView] Appointments Response:", response.data);
            setAgendamentos(response.data);
        } catch (error) {
            console.error("[CalendarView] Failed to fetch appointments", error);
        }
    };

    // Helpers to get client/company ID - these should ideally come from context
    const getUserId = () => {
        // Try getting the explicit client_id stored during login
        const storedClientId = localStorage.getItem('client_id');
        if (storedClientId) return parseInt(storedClientId);

        const user = JSON.parse(localStorage.getItem('user') || '{}');
        // Fallback to user.client_id, then user.id
        return user.client_id || user.id;
    };
    const getCompanyId = () => {
        // First check explicitly selected company
        const storedId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
        if (storedId) return parseInt(storedId);

        // Fallback to user object
        const user = JSON.parse(localStorage.getItem('user') || '{}');
        return user.company_id || null;
    };

    const handleSlotClick = (date: Date) => {
        if (selectedAgenda) {
            const slotKey = format(date, DATE_TIME_KEY_FORMAT);
            const nowKey = formatNowInTimezone(selectedAgenda.timezone);

            if (slotKey <= nowKey) {
                toast.info("Este horário já passou e não pode receber novos agendamentos.");
                return;
            }
        }

        setSelectedSlot(date);
        setShowModal(true);
    };

    const navigatePeriod = (direction: -1 | 1) => {
        const step = viewMode === 'week' ? 7 : 1;
        setCurrentDate(previousDate => addDays(previousDate, step * direction));
    };

    const goToToday = () => {
        setCurrentDate(new Date());
    };

    const periodLabel = formatPeriodLabel(currentDate, viewMode);
    const periodUnit = viewMode === 'week' ? 'semana' : 'dia';

    // --- RENDER HELPERS ---

    const renderTimeSlots = () => {
        if (!selectedAgenda) return null;

        const duration = selectedAgenda.slot_duration || 30;
        const days = viewMode === 'week' ?
            Array.from({ length: 7 }, (_, i) => addDays(startOfWeek(currentDate, { weekStartsOn: 0 }), i)) :
            [currentDate];
        const nowDateTimeKey = formatNowInTimezone(selectedAgenda.timezone);
        const todayDateKey = formatTodayInTimezone(selectedAgenda.timezone);
        const windowsByDayKey = new Map<string, TimeWindow[]>();
        const visibleSlotMinutes = new Set<number>();

        days.forEach(day => {
            const dayKey = format(day, DATE_KEY_FORMAT);
            const dayIndex = getAgendaDayIndex(day);
            const daySchedule = selectedAgenda.schedules?.find(schedule => schedule.day_of_week === dayIndex);
            const windows = getScheduleWindows(daySchedule);

            windowsByDayKey.set(dayKey, windows);

            windows.forEach(window => {
                for (let slotMinutes = window.start; slotMinutes + duration <= window.end; slotMinutes += duration) {
                    visibleSlotMinutes.add(slotMinutes);
                }
            });
        });

        agendamentos.forEach(appointment => {
            if (!appointment.consulta_data) return;

            const appointmentDateKey = formatIsoInTimezone(
                appointment.consulta_data,
                selectedAgenda.timezone,
                DATE_KEY_FORMAT,
            );
            const isVisibleDay = days.some(day => format(day, DATE_KEY_FORMAT) === appointmentDateKey);

            if (!isVisibleDay) return;

            const appointmentMinutes = parseTimeToMinutes(
                formatIsoInTimezone(appointment.consulta_data, selectedAgenda.timezone, 'HH:mm'),
            );

            if (appointmentMinutes !== null) {
                visibleSlotMinutes.add(appointmentMinutes);
            }
        });

        const timeLabels = Array.from(visibleSlotMinutes)
            .sort((a, b) => a - b)
            .map(minutesToTimeLabel);

        if (timeLabels.length === 0) {
            return (
                <div className="flex min-h-[360px] w-full items-center justify-center rounded-2xl border border-dashed border-brand/15 bg-white p-8 text-center shadow-[0_22px_55px_rgba(2,3,35,0.08)]">
                    <div className="max-w-md">
                        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-canvas text-brand/45">
                            <Clock3 className="h-6 w-6" />
                        </div>
                        <h3 className="text-base font-semibold text-brand">Nenhuma janela de atendimento neste período</h3>
                        <p className="mt-2 text-sm text-brand/55">
                            Configure horários para esta agenda ou navegue para uma semana/dia com atendimento.
                        </p>
                    </div>
                </div>
            );
        }

        return (
            <div className="flex h-[620px] w-full flex-col overflow-auto rounded-2xl border border-brand/10 bg-white shadow-[0_22px_55px_rgba(2,3,35,0.08)]">
                {/* Header */}
                <div className="sticky top-0 z-10 flex border-b border-brand/10 bg-white">
                    <div className="w-16 flex-shrink-0 border-r border-brand/10 bg-brand-canvas"></div>
                    {days.map(day => {
                        const dayKey = format(day, DATE_KEY_FORMAT);
                        const isPastDay = dayKey < todayDateKey;
                        const isToday = dayKey === todayDateKey;
                        const hasConfiguredWindows = (windowsByDayKey.get(dayKey)?.length || 0) > 0;

                        return (
                            <div
                                key={day.toString()}
                                className={`min-w-[132px] flex-1 border-r border-brand/10 px-3 py-3 text-center text-xs font-semibold uppercase tracking-[0.04em] ${
                                    isPastDay ? 'bg-brand-canvas text-brand/35' : 'text-brand/70'
                                }`}
                            >
                                <div>{format(day, 'EEE dd/MM', { locale: ptBR })}</div>
                                {isToday && (
                                    <span className="mt-1 inline-flex rounded-full bg-brand px-2 py-0.5 text-[10px] font-semibold text-white">
                                        Hoje
                                    </span>
                                )}
                                {isPastDay && (
                                    <span className="mt-1 inline-flex rounded-full border border-brand/10 bg-white px-2 py-0.5 text-[10px] font-semibold text-brand/35">
                                        Bloqueado
                                    </span>
                                )}
                                {!isPastDay && !hasConfiguredWindows && (
                                    <span className="mt-1 inline-flex rounded-full border border-brand/10 bg-brand-canvas px-2 py-0.5 text-[10px] font-semibold text-brand/35">
                                        Sem agenda
                                    </span>
                                )}
                            </div>
                        );
                    })}
                </div>

                {/* Body */}
                <div className="flex-1 relative">
                    {timeLabels.map((time) => (
                        <div key={time} className="flex min-h-[54px] border-b border-brand/10">
                            <div className="w-16 flex-shrink-0 border-r border-brand/10 bg-brand-canvas pr-2 pt-2 text-right text-xs font-medium text-brand/40">
                                {time}
                            </div>
                            {days.map(day => {
                                // Construct full date for this slot
                                const [hours, minutes] = time.split(':').map(Number);
                                const slotDate = new Date(day);
                                slotDate.setHours(hours, minutes, 0, 0);
                                const slotDateTimeKey = format(slotDate, DATE_TIME_KEY_FORMAT);
                                const slotMinutes = hours * 60 + minutes;
                                const dayKey = format(day, DATE_KEY_FORMAT);
                                const isConfiguredSlot = slotFitsWindow(slotMinutes, duration, windowsByDayKey.get(dayKey) || []);
                                const isPastSlot = slotDateTimeKey <= nowDateTimeKey;

                                // Find appointments in this slot
                                const appointment = agendamentos.find(a => {
                                    if (!a.consulta_data) return false;

                                    const apptString = formatIsoInTimezone(
                                        a.consulta_data,
                                        selectedAgenda.timezone,
                                        DATE_TIME_KEY_FORMAT,
                                    );
                                    return apptString === slotDateTimeKey;
                                });
                                const canCreateAppointment = !appointment && !isPastSlot && isConfiguredSlot;

                                return (
                                    <div
                                        key={day.toISOString() + time}
                                        aria-disabled={!canCreateAppointment}
                                        title={
                                            appointment
                                                ? undefined
                                                : isPastSlot
                                                    ? 'Horário passado'
                                                    : !isConfiguredSlot
                                                        ? 'Fora da janela de atendimento'
                                                        : undefined
                                        }
                                        className={`relative min-w-[132px] flex-1 border-r border-brand/10 transition-colors ${
                                            appointment
                                                ? 'cursor-default'
                                                : isPastSlot
                                                    ? 'cursor-not-allowed bg-[repeating-linear-gradient(135deg,rgba(2,3,35,0.035)_0,rgba(2,3,35,0.035)_8px,transparent_8px,transparent_16px)]'
                                                    : !isConfiguredSlot
                                                        ? 'cursor-not-allowed bg-brand-canvas/35'
                                                        : 'cursor-pointer hover:bg-brand-canvas'
                                        }`}
                                        onClick={canCreateAppointment ? () => handleSlotClick(slotDate) : undefined}
                                    >
                                        {appointment && (
                                            <div className="absolute inset-1 overflow-hidden rounded-xl border border-brand/10 bg-brand text-xs text-white shadow-sm">
                                                <div className="h-full border-l-4 border-white/40 p-2">
                                                    <div className="truncate font-semibold">{appointment.nome}</div>
                                                    <div className="truncate text-white/65">{appointment.phone}</div>
                                                </div>
                                            </div>
                                        )}
                                        {isPastSlot && !appointment && (
                                            <div className="absolute right-2 top-2 inline-flex h-5 w-5 items-center justify-center rounded-full border border-brand/10 bg-white/80 text-brand/25">
                                                <Lock className="h-3 w-3" />
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    ))}
                </div>
            </div>
        );
    };

    return (
        <div className="w-full space-y-4 text-brand">
            {/* Toolbar */}
            <div className="w-full rounded-2xl border border-brand/10 bg-white p-4 shadow-[0_22px_55px_rgba(2,3,35,0.08)]">
                <div className="grid gap-3 xl:grid-cols-[minmax(220px,280px)_minmax(0,1fr)_auto] xl:items-center">
                    <select
                        className="min-h-[42px] w-full rounded-xl border border-brand/10 bg-white px-3 py-2 text-sm font-semibold text-brand outline-none transition-all focus:border-brand/30 focus:ring-2 focus:ring-brand/10"
                        value={selectedAgendaId || ''}
                        onChange={(e) => setSelectedAgendaId(parseInt(e.target.value))}
                    >
                        {agendas.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </select>

                    <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] gap-1 rounded-xl border border-brand/10 bg-brand-canvas p-1 sm:grid-cols-[auto_minmax(180px,1fr)_auto_auto]">
                        <button
                            type="button"
                            aria-label={`${periodUnit} anterior`}
                            onClick={() => navigatePeriod(-1)}
                            className="inline-flex min-h-[38px] items-center justify-center gap-2 rounded-lg px-3 text-sm font-semibold text-brand/60 transition-colors hover:bg-white hover:text-brand"
                        >
                            <ChevronLeft className="h-4 w-4" />
                            <span className="hidden lg:inline">{periodUnit === 'semana' ? 'Semana anterior' : 'Dia anterior'}</span>
                        </button>
                        <div className="min-w-0 rounded-lg bg-white px-3 py-2 text-center">
                            <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-brand/35">
                                Período
                            </div>
                            <div className="truncate text-sm font-semibold capitalize text-brand">
                                {periodLabel}
                            </div>
                        </div>
                        <button
                            type="button"
                            onClick={goToToday}
                            className="hidden min-h-[38px] items-center justify-center rounded-lg px-3 text-sm font-semibold text-brand/60 transition-colors hover:bg-white hover:text-brand sm:inline-flex"
                        >
                            Hoje
                        </button>
                        <button
                            type="button"
                            aria-label={`Próximo ${periodUnit}`}
                            onClick={() => navigatePeriod(1)}
                            className="inline-flex min-h-[38px] items-center justify-center gap-2 rounded-lg px-3 text-sm font-semibold text-brand/60 transition-colors hover:bg-white hover:text-brand"
                        >
                            <span className="hidden lg:inline">{periodUnit === 'semana' ? 'Próxima semana' : 'Próximo dia'}</span>
                            <ChevronRight className="h-4 w-4" />
                        </button>
                    </div>

                <div className="flex w-full rounded-xl border border-brand/10 bg-brand-canvas p-1 xl:w-auto">
                    <button
                        type="button"
                        onClick={() => setViewMode('week')}
                        className={`inline-flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors xl:flex-none ${viewMode === 'week' ? 'bg-brand text-white shadow-sm' : 'text-brand/60 hover:bg-white hover:text-brand'}`}
                    >
                        <CalendarDays className="h-4 w-4" />
                        Semana
                    </button>
                    <button
                        type="button"
                        onClick={() => setViewMode('day')}
                        className={`inline-flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors xl:flex-none ${viewMode === 'day' ? 'bg-brand text-white shadow-sm' : 'text-brand/60 hover:bg-white hover:text-brand'}`}
                    >
                        <Clock3 className="h-4 w-4" />
                        Dia
                    </button>
                </div>
                </div>
            </div>

            {/* Timezone Info */}
            {selectedAgenda?.timezone && (
                <div className="inline-flex items-center gap-2 rounded-full border border-brand/10 bg-white px-3 py-1.5 text-xs font-medium text-brand/55">
                    <Clock3 className="h-3.5 w-3.5" />
                    Fuso horário: {selectedAgenda.timezone}
                </div>
            )}

            {/* Grid */}
            {renderTimeSlots()}

            <AppointmentBookingModal
                agendas={agendas}
                defaultAgendaId={selectedAgendaId}
                defaultDate={selectedSlot}
                isOpen={showModal && Boolean(selectedSlot)}
                onClose={() => {
                    setShowModal(false);
                    setSelectedSlot(null);
                }}
                onCreated={async () => {
                    toast.success("Agendamento criado!");
                    await fetchAgendamentos();
                }}
            />
        </div>
    );
};
