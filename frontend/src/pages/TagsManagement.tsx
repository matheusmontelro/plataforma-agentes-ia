import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
    Check,
    Edit2,
    Folder,
    Hash,
    Layers,
    Loader2,
    Palette,
    Plus,
    Search,
    Tag as TagIcon,
    Tags,
    Trash2,
    X,
} from 'lucide-react';
import {
    getTagCategories,
    getTags,
    createTagCategory,
    updateTagCategory,
    deleteTagCategory,
    createTag,
    updateTag,
    deleteTag,
    TagCategory,
    Tag,
} from '../services/tagsApi.ts';
import ConfirmDeleteModal from '../components/ConfirmDeleteModal.tsx';
import {
    AgentiveAlert,
    AgentiveEmptyState,
    agentiveIconButtonClass,
    agentiveInputClass,
    agentivePageClass,
    agentivePrimaryButtonClass,
    agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import styles from './TagsManagement.module.css';

const PRESET_COLORS = [
    '#020323',
    '#10B981',
    '#F59E0B',
    '#EF4444',
    '#8B5CF6',
    '#EC4899',
    '#6B7280',
    '#0EA5E9',
];

type CategoryFilter = 'all' | 'uncategorized' | number;
type TagCreateTarget = number | 'uncategorized' | null;

const cx = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const ColorSwatches: React.FC<{
    disabled?: boolean;
    onChange: (color: string) => void;
    selectedColor: string;
    size?: 'sm' | 'md';
}> = ({ disabled = false, onChange, selectedColor, size = 'md' }) => {
    const sizeClass = size === 'sm' ? 'h-5 w-5' : 'h-7 w-7';

    return (
        <div className={styles.swatches}>
            {PRESET_COLORS.map(color => {
                const isSelected = selectedColor === color;

                return (
                    <button
                        aria-label={`Selecionar cor ${color}`}
                        className={cx(
                            styles.swatch,
                            sizeClass,
                            isSelected && styles.swatchSelected
                        )}
                        disabled={disabled}
                        key={color}
                        onClick={() => onChange(color)}
                        style={{ backgroundColor: color }}
                        type="button"
                    />
                );
            })}
        </div>
    );
};

const KpiCard: React.FC<{
    detail: string;
    label: string;
    value: React.ReactNode;
}> = ({ detail, label, value }) => (
    <article className={styles.kpiCard}>
        <div className={styles.kpiCopy}>
            <span className={styles.kpiLabel}>{label}</span>
            <strong className={styles.kpiValue}>{value}</strong>
            <span className={styles.kpiDetail}>{detail}</span>
        </div>
    </article>
);

const TagsManagement: React.FC = () => {
    const { isDark } = useTheme();
    const [categories, setCategories] = useState<TagCategory[]>([]);
    const [tags, setTags] = useState<Tag[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [selectedFilter, setSelectedFilter] = useState<CategoryFilter>('all');
    const [searchTerm, setSearchTerm] = useState('');

    const [editingCategory, setEditingCategory] = useState<TagCategory | null>(null);
    const [editingTag, setEditingTag] = useState<Tag | null>(null);

    const [showNewCategory, setShowNewCategory] = useState(false);
    const [showNewTag, setShowNewTag] = useState<TagCreateTarget>(null);
    const [newCategoryName, setNewCategoryName] = useState('');
    const [newCategoryColor, setNewCategoryColor] = useState(PRESET_COLORS[6]);
    const [newTagName, setNewTagName] = useState('');
    const [newTagColor, setNewTagColor] = useState(PRESET_COLORS[0]);

    const [actionLoading, setActionLoading] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState<{ type: 'category' | 'tag'; id: number; name: string } | null>(null);

    const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0');

    const fetchData = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            const [categoriesData, tagsData] = await Promise.all([
                getTagCategories(companyId),
                getTags(companyId),
            ]);
            setCategories(categoriesData || []);
            setTags(Array.isArray(tagsData) ? tagsData : []);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Erro ao carregar tags');
        } finally {
            setLoading(false);
        }
    }, [companyId]);

    useEffect(() => {
        if (!companyId) {
            setLoading(false);
            setError('Empresa ativa não encontrada. Selecione uma empresa para gerenciar tags.');
            return;
        }

        fetchData();
    }, [companyId, fetchData]);

    useEffect(() => {
        if (typeof selectedFilter === 'number' && !categories.some(category => category.id === selectedFilter)) {
            setSelectedFilter('all');
        }
    }, [categories, selectedFilter]);

    const safeTags = Array.isArray(tags) ? tags : [];

    const tagCountByCategory = useMemo(() => {
        const counts = new Map<number | null, number>();
        safeTags.forEach(tag => {
            counts.set(tag.category_id, (counts.get(tag.category_id) || 0) + 1);
        });
        return counts;
    }, [safeTags]);

    const uncategorizedTags = useMemo(() => safeTags.filter(tag => tag.category_id === null), [safeTags]);
    const selectedCategory = typeof selectedFilter === 'number'
        ? categories.find(category => category.id === selectedFilter)
        : null;

    const selectedTags = useMemo(() => {
        if (selectedFilter === 'all') return safeTags;
        if (selectedFilter === 'uncategorized') return uncategorizedTags;
        return safeTags.filter(tag => tag.category_id === selectedFilter);
    }, [safeTags, selectedFilter, uncategorizedTags]);

    const filteredTags = useMemo(() => {
        const query = searchTerm.trim().toLowerCase();
        if (!query) return selectedTags;

        return selectedTags.filter(tag => {
            const categoryName = tag.category_name || categories.find(category => category.id === tag.category_id)?.name || 'sem categoria';
            return tag.name.toLowerCase().includes(query) || categoryName.toLowerCase().includes(query);
        });
    }, [categories, searchTerm, selectedTags]);

    const selectedTitle = selectedFilter === 'all'
        ? 'Todas as tags'
        : selectedFilter === 'uncategorized'
            ? 'Sem categoria'
            : selectedCategory?.name || 'Categoria';

    const selectedDescription = selectedFilter === 'all'
        ? 'Visão completa dos segmentos usados em contatos, filtros e campanhas.'
        : selectedFilter === 'uncategorized'
            ? 'Tags soltas que ainda não estão agrupadas em uma categoria.'
            : 'Tags agrupadas nesta categoria operacional.';

    const getCategoryCount = (categoryId: number | null) => tagCountByCategory.get(categoryId) || 0;

    const getTagCategoryName = (tag: Tag) => {
        if (tag.category_name) return tag.category_name;
        if (tag.category_id === null) return 'Sem categoria';
        return categories.find(category => category.id === tag.category_id)?.name || 'Categoria';
    };

    const closeNewCategory = () => {
        setShowNewCategory(false);
        setNewCategoryName('');
        setNewCategoryColor(PRESET_COLORS[6]);
    };

    const closeNewTag = () => {
        setShowNewTag(null);
        setNewTagName('');
        setNewTagColor(PRESET_COLORS[0]);
    };

    const handleStartCreateTag = (categoryId: number | null) => {
        const target = categoryId === null ? 'uncategorized' : categoryId;
        const inheritedColor = categoryId === null
            ? PRESET_COLORS[0]
            : categories.find(category => category.id === categoryId)?.color || PRESET_COLORS[0];

        setEditingTag(null);
        setNewTagName('');
        setNewTagColor(inheritedColor);
        setShowNewTag(target);
        setSelectedFilter(target);
    };

    const handleCreateCategory = async () => {
        const trimmedName = newCategoryName.trim();
        if (!trimmedName || !companyId) return;

        try {
            setActionLoading(true);
            const createdCategory = await createTagCategory({
                company_id: companyId,
                name: trimmedName,
                color: newCategoryColor,
            });
            closeNewCategory();
            await fetchData();
            setSelectedFilter(createdCategory.id);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Erro ao criar categoria');
        } finally {
            setActionLoading(false);
        }
    };

    const handleUpdateCategory = async (category: TagCategory) => {
        const trimmedName = category.name.trim();
        if (!trimmedName) return;

        try {
            setActionLoading(true);
            await updateTagCategory(category.id, {
                name: trimmedName,
                color: category.color,
            });
            setEditingCategory(null);
            await fetchData();
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Erro ao atualizar categoria');
        } finally {
            setActionLoading(false);
        }
    };

    const handleDeleteCategory = async (categoryId: number) => {
        const category = categories.find(item => item.id === categoryId);
        setDeleteTarget({ type: 'category', id: categoryId, name: category?.name || 'categoria' });
    };

    const confirmDeleteTarget = async () => {
        if (!deleteTarget) return;

        try {
            setActionLoading(true);
            if (deleteTarget.type === 'category') {
                await deleteTagCategory(deleteTarget.id);
                if (selectedFilter === deleteTarget.id) {
                    setSelectedFilter('uncategorized');
                }
            } else {
                await deleteTag(deleteTarget.id);
            }
            setDeleteTarget(null);
            await fetchData();
        } catch (err: any) {
            setError(err.response?.data?.detail || (deleteTarget.type === 'category' ? 'Erro ao excluir categoria' : 'Erro ao excluir tag'));
        } finally {
            setActionLoading(false);
        }
    };

    const handleCreateTag = async (categoryId: number | null) => {
        const trimmedName = newTagName.trim();
        if (!trimmedName || !companyId) return;

        try {
            setActionLoading(true);
            await createTag({
                company_id: companyId,
                name: trimmedName,
                color: newTagColor,
                category_id: categoryId ?? undefined,
            });
            closeNewTag();
            setSelectedFilter(categoryId === null ? 'uncategorized' : categoryId);
            await fetchData();
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Erro ao criar tag');
        } finally {
            setActionLoading(false);
        }
    };

    const handleUpdateTag = async (tag: Tag) => {
        const trimmedName = tag.name.trim();
        if (!trimmedName) return;

        try {
            setActionLoading(true);
            await updateTag(tag.id, {
                name: trimmedName,
                color: tag.color,
                category_id: tag.category_id,
            });
            const nextFilter = tag.category_id === null ? 'uncategorized' : tag.category_id;
            setEditingTag(null);
            await fetchData();
            if (selectedFilter !== 'all') {
                setSelectedFilter(nextFilter);
            }
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Erro ao atualizar tag');
        } finally {
            setActionLoading(false);
        }
    };

    const handleDeleteTag = async (tagId: number) => {
        const tag = safeTags.find(item => item.id === tagId);
        setDeleteTarget({ type: 'tag', id: tagId, name: tag?.name || 'tag' });
    };

    const newTagCategoryId = typeof showNewTag === 'number' ? showNewTag : null;
    const hasSearch = searchTerm.trim().length > 0;
    const rootClass = cx(styles.root, isDark && styles['root--dark']);

    if (loading) {
        return (
            <div className={cx(agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10 2xl:px-12'), rootClass)}>
                <div className={styles.shell}>
                    <div className={cx(styles.panel, 'flex items-center gap-3 px-5 py-4')}>
                        <Loader2 className="h-5 w-5 animate-spin" />
                        <span className="text-sm font-medium">Carregando tags...</span>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className={cx(agentivePageClass(isDark, 'px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10 2xl:px-12'), rootClass)}>
            <div className={styles.shell}>
                {/* Cabeçalho de página compacto (sem hero de landing page) */}
                <header className={styles.pageHead}>
                    <div className={styles.pageHeadCopy}>
                        <h1 className={styles.pageTitle}>Filtros &amp; Tags</h1>
                        <p className={styles.pageSubtitle}>
                            Segmentos visuais para contatos, campanhas e filtros do CRM.
                        </p>
                    </div>
                    <div className={styles.pageActions}>
                        <button
                            className={agentiveSecondaryButtonClass(isDark, 'w-full sm:w-auto')}
                            onClick={() => handleStartCreateTag(typeof selectedFilter === 'number' ? selectedFilter : null)}
                            type="button"
                        >
                            <Plus className="h-4 w-4" />
                            Nova tag
                        </button>
                        <button
                            className={agentivePrimaryButtonClass('w-full sm:w-auto')}
                            onClick={() => {
                                setEditingCategory(null);
                                setShowNewCategory(true);
                            }}
                            type="button"
                        >
                            <Folder className="h-4 w-4" />
                            Nova categoria
                        </button>
                    </div>
                </header>

                {error && (
                    <AgentiveAlert variant="error" title="Não foi possível concluir a ação" onClose={() => setError(null)}>
                        {error}
                    </AgentiveAlert>
                )}

                {/* KPIs operacionais — número grande tabular, sem ícone decorativo */}
                <section className={styles.kpiGrid}>
                    <KpiCard
                        detail="segmentos disponíveis"
                        label="Tags"
                        value={safeTags.length}
                    />
                    <KpiCard
                        detail="grupos organizados"
                        label="Categorias"
                        value={categories.length}
                    />
                    <KpiCard
                        detail="aguardando organização"
                        label="Sem categoria"
                        value={uncategorizedTags.length}
                    />
                </section>

                {showNewCategory && (
                    <section className={cx(styles.panel, 'p-4')}>
                        <div className={styles.editorGrid}>
                            <div>
                                <label className={styles.fieldLabel}>Nova categoria</label>
                                <input
                                    autoFocus
                                    className={agentiveInputClass(isDark)}
                                    disabled={actionLoading}
                                    onChange={event => setNewCategoryName(event.target.value)}
                                    onKeyDown={event => {
                                        if (event.key === 'Enter') handleCreateCategory();
                                        if (event.key === 'Escape') closeNewCategory();
                                    }}
                                    placeholder="Ex: Origem do lead"
                                    type="text"
                                    value={newCategoryName}
                                />
                            </div>
                            <div>
                                <label className={cx(styles.fieldLabel, 'flex items-center gap-1')}>
                                    <Palette className="h-3.5 w-3.5" />
                                    Cor
                                </label>
                                <ColorSwatches
                                    disabled={actionLoading}
                                    onChange={setNewCategoryColor}
                                    selectedColor={newCategoryColor}
                                />
                            </div>
                            <div className="flex gap-2">
                                <button
                                    className={agentivePrimaryButtonClass('min-h-10 px-3')}
                                    disabled={actionLoading || !newCategoryName.trim()}
                                    onClick={handleCreateCategory}
                                    title="Salvar categoria"
                                    type="button"
                                >
                                    <Check className="h-4 w-4" />
                                    <span className="sm:hidden">Salvar</span>
                                </button>
                                <button
                                    className={agentiveIconButtonClass(isDark)}
                                    disabled={actionLoading}
                                    onClick={closeNewCategory}
                                    title="Cancelar"
                                    type="button"
                                >
                                    <X className="h-4 w-4" />
                                </button>
                            </div>
                        </div>
                    </section>
                )}

                {/* Workspace: sidebar de categorias + painel de tags */}
                <div className={styles.workspaceGrid}>
                    <aside className={styles.panel}>
                        <div className={styles.panelHead}>
                            <div className={styles.panelHeadCopy}>
                                <div className={styles.panelHeadTitleRow}>
                                    <Layers className="h-4 w-4" />
                                    <h2 className={styles.panelHeadTitle}>Categorias</h2>
                                </div>
                                <p className={styles.panelHeadSubtitle}>
                                    {categories.length} grupo{categories.length === 1 ? '' : 's'}
                                </p>
                            </div>
                            <button
                                className={agentiveIconButtonClass(isDark, 'primary')}
                                onClick={() => setShowNewCategory(true)}
                                title="Nova categoria"
                                type="button"
                            >
                                <Plus className="h-4 w-4" />
                            </button>
                        </div>

                        <div className={styles.navList}>
                            <button
                                className={cx(styles.navItem, selectedFilter === 'all' && styles.navItemActive)}
                                onClick={() => setSelectedFilter('all')}
                                type="button"
                            >
                                <Tags className="h-4 w-4 shrink-0 opacity-60" />
                                <span className={styles.navItemCopy}>
                                    <span className={styles.navItemLabel}>Todas as tags</span>
                                </span>
                                <span className={styles.navCount}>{safeTags.length}</span>
                            </button>

                            {categories.map(category => {
                                const isActive = selectedFilter === category.id;
                                const isEditing = editingCategory?.id === category.id;
                                const count = getCategoryCount(category.id);

                                if (isEditing && editingCategory) {
                                    return (
                                        <div className={styles.editorCard} key={category.id}>
                                            <input
                                                autoFocus
                                                className={cx(agentiveInputClass(isDark), 'mb-2')}
                                                disabled={actionLoading}
                                                onChange={event => setEditingCategory({ ...editingCategory, name: event.target.value })}
                                                onKeyDown={event => {
                                                    if (event.key === 'Enter') handleUpdateCategory(editingCategory);
                                                    if (event.key === 'Escape') setEditingCategory(null);
                                                }}
                                                value={editingCategory.name}
                                            />
                                            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between lg:flex-col lg:items-stretch">
                                                <ColorSwatches
                                                    disabled={actionLoading}
                                                    onChange={color => setEditingCategory({ ...editingCategory, color })}
                                                    selectedColor={editingCategory.color}
                                                    size="sm"
                                                />
                                                <div className="flex justify-end gap-1">
                                                    <button
                                                        className={agentiveIconButtonClass(isDark, 'success', 'min-h-8 min-w-8 p-1.5')}
                                                        disabled={actionLoading || !editingCategory.name.trim()}
                                                        onClick={() => handleUpdateCategory(editingCategory)}
                                                        title="Salvar categoria"
                                                        type="button"
                                                    >
                                                        <Check className="h-3.5 w-3.5" />
                                                    </button>
                                                    <button
                                                        className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-8 min-w-8 p-1.5')}
                                                        disabled={actionLoading}
                                                        onClick={() => setEditingCategory(null)}
                                                        title="Cancelar edição"
                                                        type="button"
                                                    >
                                                        <X className="h-3.5 w-3.5" />
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    );
                                }

                                return (
                                    <div
                                        className={cx(styles.categoryRow, isActive && styles.categoryRowActive)}
                                        key={category.id}
                                    >
                                        <button
                                            className={styles.categoryTrigger}
                                            onClick={() => setSelectedFilter(category.id)}
                                            type="button"
                                        >
                                            <span className={styles.colorDot} style={{ backgroundColor: category.color }} />
                                            <span className={styles.categoryTriggerCopy}>
                                                <span className={styles.navItemLabel}>{category.name}</span>
                                            </span>
                                            <span className={styles.navCount}>{count}</span>
                                        </button>
                                        <button
                                            className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-8 min-w-8 p-1.5')}
                                            onClick={() => handleStartCreateTag(category.id)}
                                            title="Adicionar tag"
                                            type="button"
                                        >
                                            <Plus className="h-3.5 w-3.5" />
                                        </button>
                                        <button
                                            className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-8 min-w-8 p-1.5')}
                                            onClick={() => setEditingCategory(category)}
                                            title="Editar categoria"
                                            type="button"
                                        >
                                            <Edit2 className="h-3.5 w-3.5" />
                                        </button>
                                        <button
                                            className={agentiveIconButtonClass(isDark, 'danger', 'min-h-8 min-w-8 p-1.5')}
                                            onClick={() => handleDeleteCategory(category.id)}
                                            title="Excluir categoria"
                                            type="button"
                                        >
                                            <Trash2 className="h-3.5 w-3.5" />
                                        </button>
                                    </div>
                                );
                            })}

                            <div className={cx(styles.categoryRow, selectedFilter === 'uncategorized' && styles.categoryRowActive)}>
                                <button
                                    className={styles.categoryTrigger}
                                    onClick={() => setSelectedFilter('uncategorized')}
                                    type="button"
                                >
                                    <Hash className="h-4 w-4 shrink-0 opacity-60" />
                                    <span className={styles.categoryTriggerCopy}>
                                        <span className={styles.navItemLabel}>Sem categoria</span>
                                    </span>
                                    <span className={styles.navCount}>{uncategorizedTags.length}</span>
                                </button>
                                <button
                                    className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-8 min-w-8 p-1.5')}
                                    onClick={() => handleStartCreateTag(null)}
                                    title="Adicionar tag sem categoria"
                                    type="button"
                                >
                                    <Plus className="h-3.5 w-3.5" />
                                </button>
                            </div>

                            {categories.length === 0 && (
                                <div className={styles.emptyNav}>
                                    Nenhuma categoria criada.
                                </div>
                            )}
                        </div>
                    </aside>

                    <section className={styles.panel}>
                        <div className={styles.panelHead}>
                            <div className={styles.panelHeadCopy}>
                                <div className={styles.panelHeadTitleRow}>
                                    {selectedCategory && (
                                        <span className={styles.colorDotLg} style={{ backgroundColor: selectedCategory.color }} />
                                    )}
                                    <h2 className={styles.panelHeadTitle}>{selectedTitle}</h2>
                                    <span className={styles.countChip}>{selectedTags.length}</span>
                                </div>
                                <p className={styles.panelHeadSubtitle}>{selectedDescription}</p>
                            </div>
                            <div className={styles.panelControls}>
                                <label className="relative min-w-0 sm:w-56">
                                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 opacity-40" />
                                    <input
                                        className={agentiveInputClass(isDark, 'pl-9')}
                                        onChange={event => setSearchTerm(event.target.value)}
                                        placeholder="Buscar tag"
                                        type="search"
                                        value={searchTerm}
                                    />
                                </label>
                                <button
                                    className={agentivePrimaryButtonClass('shrink-0')}
                                    onClick={() => handleStartCreateTag(typeof selectedFilter === 'number' ? selectedFilter : null)}
                                    type="button"
                                >
                                    <Plus className="h-4 w-4" />
                                    Adicionar
                                </button>
                            </div>
                        </div>

                        <div className={styles.panelBody}>
                            {showNewTag !== null && (
                                <div className={cx(styles.editorCard, styles.editorCardMuted)}>
                                    <div className={styles.editorGrid}>
                                        <div>
                                            <label className={styles.fieldLabel}>
                                                Nova tag {showNewTag === 'uncategorized' ? 'sem categoria' : ''}
                                            </label>
                                            <input
                                                autoFocus
                                                className={agentiveInputClass(isDark)}
                                                disabled={actionLoading}
                                                onChange={event => setNewTagName(event.target.value)}
                                                onKeyDown={event => {
                                                    if (event.key === 'Enter') handleCreateTag(newTagCategoryId);
                                                    if (event.key === 'Escape') closeNewTag();
                                                }}
                                                placeholder="Ex: VIP, retorno, indicação"
                                                type="text"
                                                value={newTagName}
                                            />
                                        </div>
                                        <div>
                                            <label className={cx(styles.fieldLabel, 'flex items-center gap-1')}>
                                                <Palette className="h-3.5 w-3.5" />
                                                Cor
                                            </label>
                                            <ColorSwatches
                                                disabled={actionLoading}
                                                onChange={setNewTagColor}
                                                selectedColor={newTagColor}
                                            />
                                        </div>
                                        <div className="flex gap-2">
                                            <button
                                                className={agentivePrimaryButtonClass('min-h-10 px-3')}
                                                disabled={actionLoading || !newTagName.trim()}
                                                onClick={() => handleCreateTag(newTagCategoryId)}
                                                title="Salvar tag"
                                                type="button"
                                            >
                                                <Check className="h-4 w-4" />
                                                <span className="sm:hidden">Salvar</span>
                                            </button>
                                            <button
                                                className={agentiveIconButtonClass(isDark)}
                                                disabled={actionLoading}
                                                onClick={closeNewTag}
                                                title="Cancelar"
                                                type="button"
                                            >
                                                <X className="h-4 w-4" />
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {filteredTags.length > 0 ? (
                                <div className={styles.tagsGrid}>
                                    {filteredTags.map(tag => {
                                        const isEditing = editingTag?.id === tag.id;

                                        return (
                                            <article className={styles.tagCard} key={tag.id}>
                                                {isEditing && editingTag ? (
                                                    <div className="space-y-3">
                                                        <input
                                                            autoFocus
                                                            className={agentiveInputClass(isDark)}
                                                            disabled={actionLoading}
                                                            onChange={event => setEditingTag({ ...editingTag, name: event.target.value })}
                                                            onKeyDown={event => {
                                                                if (event.key === 'Enter') handleUpdateTag(editingTag);
                                                                if (event.key === 'Escape') setEditingTag(null);
                                                            }}
                                                            value={editingTag.name}
                                                        />
                                                        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
                                                            {categories.length > 0 && (
                                                                <div>
                                                                    <label className={styles.fieldLabel}>
                                                                        Categoria
                                                                    </label>
                                                                    <select
                                                                        className={agentiveInputClass(isDark)}
                                                                        disabled={actionLoading}
                                                                        onChange={event => {
                                                                            const nextCategoryId = event.target.value === 'uncategorized' ? null : Number(event.target.value);
                                                                            const nextCategory = nextCategoryId === null
                                                                                ? null
                                                                                : categories.find(category => category.id === nextCategoryId) || null;

                                                                            setEditingTag({
                                                                                ...editingTag,
                                                                                category_id: nextCategoryId,
                                                                                category_name: nextCategory?.name || null,
                                                                            });
                                                                        }}
                                                                        value={editingTag.category_id === null ? 'uncategorized' : String(editingTag.category_id)}
                                                                    >
                                                                        <option value="uncategorized">Sem categoria</option>
                                                                        {categories.map(category => (
                                                                            <option key={category.id} value={category.id}>
                                                                                {category.name}
                                                                            </option>
                                                                        ))}
                                                                    </select>
                                                                </div>
                                                            )}
                                                            <div>
                                                                <label className={cx(styles.fieldLabel, 'flex items-center gap-1')}>
                                                                    <Palette className="h-3.5 w-3.5" />
                                                                    Cor
                                                                </label>
                                                                <ColorSwatches
                                                                    disabled={actionLoading}
                                                                    onChange={color => setEditingTag({ ...editingTag, color })}
                                                                    selectedColor={editingTag.color}
                                                                    size="sm"
                                                                />
                                                            </div>
                                                        </div>
                                                        <div className="flex justify-end gap-1">
                                                            <button
                                                                className={agentiveIconButtonClass(isDark, 'success', 'min-h-8 min-w-8 p-1.5')}
                                                                disabled={actionLoading || !editingTag.name.trim()}
                                                                onClick={() => handleUpdateTag(editingTag)}
                                                                title="Salvar tag"
                                                                type="button"
                                                            >
                                                                <Check className="h-3.5 w-3.5" />
                                                            </button>
                                                            <button
                                                                className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-8 min-w-8 p-1.5')}
                                                                disabled={actionLoading}
                                                                onClick={() => setEditingTag(null)}
                                                                title="Cancelar edição"
                                                                type="button"
                                                            >
                                                                <X className="h-3.5 w-3.5" />
                                                            </button>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div className={styles.tagCardMain}>
                                                        <div className={styles.tagIdentity}>
                                                            <span className={styles.colorDotLg} style={{ backgroundColor: tag.color }} />
                                                            <div className="min-w-0">
                                                                <h3 className={styles.tagName}>{tag.name}</h3>
                                                                <p className={styles.tagMeta}>{getTagCategoryName(tag)}</p>
                                                            </div>
                                                        </div>
                                                        <div className="flex shrink-0 items-center gap-1">
                                                            <button
                                                                className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-8 min-w-8 p-1.5')}
                                                                onClick={() => setEditingTag(tag)}
                                                                title="Editar tag"
                                                                type="button"
                                                            >
                                                                <Edit2 className="h-3.5 w-3.5" />
                                                            </button>
                                                            <button
                                                                className={agentiveIconButtonClass(isDark, 'danger', 'min-h-8 min-w-8 p-1.5')}
                                                                onClick={() => handleDeleteTag(tag.id)}
                                                                title="Excluir tag"
                                                                type="button"
                                                            >
                                                                <Trash2 className="h-3.5 w-3.5" />
                                                            </button>
                                                        </div>
                                                    </div>
                                                )}
                                            </article>
                                        );
                                    })}
                                </div>
                            ) : hasSearch ? (
                                <AgentiveEmptyState
                                    action={(
                                        <button
                                            className={agentiveSecondaryButtonClass(isDark)}
                                            onClick={() => setSearchTerm('')}
                                            type="button"
                                        >
                                            <X className="h-4 w-4" />
                                            Limpar busca
                                        </button>
                                    )}
                                    icon={Search}
                                    title="Nenhuma tag encontrada"
                                    description="A busca não encontrou uma tag nessa seleção."
                                />
                            ) : (
                                <AgentiveEmptyState
                                    action={(
                                        <button
                                            className={agentivePrimaryButtonClass()}
                                            onClick={() => handleStartCreateTag(typeof selectedFilter === 'number' ? selectedFilter : null)}
                                            type="button"
                                        >
                                            <Plus className="h-4 w-4" />
                                            Criar tag
                                        </button>
                                    )}
                                    icon={TagIcon}
                                    title={safeTags.length === 0 ? 'Nenhuma tag criada ainda' : 'Nenhuma tag nesta seleção'}
                                    description={safeTags.length === 0 ? 'Crie a primeira tag para segmentar contatos, campanhas e filtros operacionais.' : 'Esta categoria ainda não possui tags vinculadas.'}
                                />
                            )}
                        </div>
                    </section>
                </div>
            </div>

            <ConfirmDeleteModal
                confirmText={deleteTarget?.type === 'category' ? 'Excluir categoria' : 'Excluir tag'}
                isLoading={actionLoading}
                isOpen={Boolean(deleteTarget)}
                message={
                    deleteTarget?.type === 'category'
                        ? 'As tags desta categoria serão mantidas como sem categoria.'
                        : 'A tag será removida dos contatos vinculados.'
                }
                onClose={() => setDeleteTarget(null)}
                onConfirm={confirmDeleteTarget}
                title={deleteTarget?.type === 'category' ? 'Excluir categoria?' : 'Excluir tag?'}
            >
                <span className="text-sm">
                    Item selecionado: <strong>{deleteTarget?.name}</strong>
                </span>
            </ConfirmDeleteModal>
        </div>
    );
};

export default TagsManagement;
