import api from './api.ts';

export interface Schedule {
    id?: number;
    agenda_id?: number;
    day_of_week: number;
    morning_start?: string | null; // HH:MM:SS
    morning_end?: string | null;
    afternoon_start?: string | null;
    afternoon_end?: string | null;
    night_start?: string | null;
    night_end?: string | null;
}

export interface Agenda {
    id: number;
    company_id: number;
    name: string;
    slot_duration: number;
    active: boolean;
    timezone?: string; // Added timezone
    safety_margin_minutes?: number; // Added safety margin
    google_calendar_id?: string | null;
    google_calendar_summary?: string | null;
    google_calendar_time_zone?: string | null;
    created_at: string;
    schedules: Schedule[];
}

export interface AgendaCreate {
    name: string;
    slot_duration: number;
    active: boolean;
    timezone?: string; // Added timezone
    safety_margin_minutes?: number; // Added safety margin
    schedules: Schedule[];
}

export interface AgendaUpdate {
    name: string;
    slot_duration: number;
    active: boolean;
    timezone?: string;
    safety_margin_minutes?: number;
    schedules?: Schedule[];
}

export interface Slot {
    start_time: string;
    end_time: string;
}

export const calendarApi = {
    createAgenda: async (data: AgendaCreate): Promise<Agenda> => {
        const response = await api.post<Agenda>('/api/calendar/', data);
        return response.data;
    },

    listAgendas: async (): Promise<Agenda[]> => {
        const response = await api.get<Agenda[]>('/api/calendar/');
        return response.data;
    },

    getAgenda: async (id: number): Promise<Agenda> => {
        const response = await api.get<Agenda>(`/api/calendar/${id}`);
        return response.data;
    },

    updateAgenda: async (id: number, data: AgendaUpdate): Promise<Agenda> => {
        const response = await api.put<Agenda>(`/api/calendar/${id}`, data);
        return response.data;
    },

    getSlots: async (agendaId: number, startDate: string, endDate: string): Promise<Slot[]> => {
        const response = await api.get<Slot[]>(`/api/calendar/${agendaId}/slots`, {
            params: { start_date: startDate, end_date: endDate }
        });
        return response.data;
    }
};
