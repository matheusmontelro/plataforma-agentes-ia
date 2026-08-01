import api from './api.ts';

export interface MediaSource {
    id: number;
    company_id: number;
    name: string;
    active: boolean;
}

export interface CreateMediaSourceData {
    name: string;
    active?: boolean;
}

export interface UpdateMediaSourceData {
    name?: string;
    active?: boolean;
}

export const getMediaSources = async (): Promise<MediaSource[]> => {
    const response = await api.get('/media-sources/');
    return response.data;
};

export const createMediaSource = async (data: CreateMediaSourceData): Promise<MediaSource> => {
    const response = await api.post('/media-sources/', data);
    return response.data;
};

export const updateMediaSource = async (id: number, data: UpdateMediaSourceData): Promise<MediaSource> => {
    const response = await api.put(`/media-sources/${id}`, data);
    return response.data;
};

export const deleteMediaSource = async (id: number): Promise<void> => {
    await api.delete(`/media-sources/${id}`);
};
