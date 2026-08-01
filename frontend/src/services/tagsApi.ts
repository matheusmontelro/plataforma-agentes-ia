/**
 * Tags API Service
 * CRUD operations for tag categories, tags, and contact-tag associations
 */
import api from './api.ts';

// ==================== Types ====================

export interface TagCategory {
    id: number;
    company_id: number;
    name: string;
    color: string;
    display_order: number;
}

export interface Tag {
    id: number;
    company_id: number;
    name: string;
    color: string;
    category_id: number | null;
    category_name: string | null;
}

export interface CreateTagCategoryRequest {
    company_id: number;
    name: string;
    color?: string;
    display_order?: number;
}

export interface UpdateTagCategoryRequest {
    name?: string;
    color?: string;
    display_order?: number;
}

export interface CreateTagRequest {
    company_id: number;
    name: string;
    color?: string;
    category_id?: number;
}

export interface UpdateTagRequest {
    name?: string;
    color?: string;
    category_id?: number | null;
}

// ==================== Category API ====================

export const getTagCategories = async (companyId: number): Promise<TagCategory[]> => {
    const response = await api.get<TagCategory[]>(`/webhook/tag-categories?company_id=${companyId}`);
    return response.data;
};

export const createTagCategory = async (data: CreateTagCategoryRequest): Promise<TagCategory> => {
    const response = await api.post<TagCategory>('/webhook/tag-categories', data);
    return response.data;
};

export const updateTagCategory = async (categoryId: number, data: UpdateTagCategoryRequest): Promise<TagCategory> => {
    const response = await api.put<TagCategory>(`/webhook/tag-categories/${categoryId}`, data);
    return response.data;
};

export const deleteTagCategory = async (categoryId: number): Promise<void> => {
    await api.delete(`/webhook/tag-categories/${categoryId}`);
};

// ==================== Tags API ====================

export const getTags = async (companyId: number, categoryId?: number): Promise<Tag[]> => {
    let url = `/webhook/tags?company_id=${companyId}`;
    if (categoryId) {
        url += `&category_id=${categoryId}`;
    }
    const response = await api.get<Tag[]>(url);
    return response.data;
};

export const createTag = async (data: CreateTagRequest): Promise<Tag> => {
    const response = await api.post<Tag>('/webhook/tags', data);
    return response.data;
};

export const updateTag = async (tagId: number, data: UpdateTagRequest): Promise<Tag> => {
    const response = await api.put<Tag>(`/webhook/tags/${tagId}`, data);
    return response.data;
};

export const deleteTag = async (tagId: number): Promise<void> => {
    await api.delete(`/webhook/tags/${tagId}`);
};

// ==================== Contact Tags API ====================

export const getContactTags = async (contactId: number): Promise<Tag[]> => {
    const response = await api.get<Tag[]>(`/webhook/contacts/${contactId}/tags`);
    return response.data;
};

export const updateContactTags = async (contactId: number, tagIds: number[]): Promise<void> => {
    await api.post(`/webhook/contacts/${contactId}/tags`, { tag_ids: tagIds });
};

export const removeTagFromContact = async (contactId: number, tagId: number): Promise<void> => {
    await api.delete(`/webhook/contacts/${contactId}/tags/${tagId}`);
};
