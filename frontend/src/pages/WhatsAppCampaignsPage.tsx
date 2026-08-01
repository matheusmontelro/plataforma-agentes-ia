import React, { useMemo, useState, useEffect } from 'react';
import {
    Loader2,
    MessageSquare,
    PauseCircle,
    Plus,
    RefreshCw,
    Search,
    Send,
} from 'lucide-react';
import { WhatsAppCampaignModal } from '../components/campaigns/WhatsAppCampaignModal';
import { WhatsAppCampaignAnalytics } from '../components/campaigns/WhatsAppCampaignAnalytics';
import {
    AgentiveAlert,
    AgentiveConfirmModal,
    AgentiveEmptyState,
    agentivePrimaryButtonClass,
    agentiveSecondaryButtonClass,
} from '../components/AgentiveUI';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
    listWhatsAppCampaigns,
    startWhatsAppCampaign,
    pauseWhatsAppCampaign,
    deleteWhatsAppCampaign,
    WhatsAppCampaign
} from '../services/whatsappCampaignService';
import styles from './WhatsAppCampaignsPage.module.css';

type CampaignStatusFilter = 'ALL' | WhatsAppCampaign['status'];

const statusFilters: Array<{ id: CampaignStatusFilter; label: string }> = [
    { id: 'ALL', label: 'Todas' },
    { id: 'PROCESSING', label: 'Em andamento' },
    { id: 'DRAFT', label: 'Rascunhos' },
    { id: 'PAUSED', label: 'Pausadas' },
    { id: 'COMPLETED', label: 'Concluídas' },
    { id: 'FAILED', label: 'Com falha' },
];

const getStatusCount = (campaigns: WhatsAppCampaign[], status: CampaignStatusFilter) => {
    if (status === 'ALL') return campaigns.length;
    return campaigns.filter((campaign) => campaign.status === status).length;
};

const cx = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const KpiCard: React.FC<{
    detail: string;
    label: string;
    value: React.ReactNode;
}> = ({ detail, label, value }) => (
    <article className={styles.kpiCard}>
        <span className={styles.kpiLabel}>{label}</span>
        <strong className={styles.kpiValue}>{value}</strong>
        <span className={styles.kpiDetail}>{detail}</span>
    </article>
);

const WhatsAppCampaignsPage: React.FC = () => {
    const { isDark } = useTheme();
    const [campaigns, setCampaigns] = useState<WhatsAppCampaign[]>([]);
    const [loading, setLoading] = useState(true);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [actionLoading, setActionLoading] = useState<{ [key: number]: 'starting' | 'pausing' | 'deleting' | null }>({});
    const [campaignToDelete, setCampaignToDelete] = useState<WhatsAppCampaign | null>(null);
    const [campaignToStart, setCampaignToStart] = useState<WhatsAppCampaign | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [statusFilter, setStatusFilter] = useState<CampaignStatusFilter>('ALL');
    const [searchTerm, setSearchTerm] = useState('');

    const companyId = parseInt((localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) || '0');

    useEffect(() => {
        if (companyId) {
            fetchCampaigns();
        } else {
            setLoading(false);
            setError('Nenhuma empresa ativa foi encontrada para carregar campanhas.');
        }
    }, [companyId]);

    const fetchCampaigns = async () => {
        try {
            setLoading(true);
            setError(null);
            const data = await listWhatsAppCampaigns();
            setCampaigns(data);
        } catch (err) {
            console.error("Error fetching campaigns:", err);
            setError("Não foi possível carregar as campanhas.");
        } finally {
            setLoading(false);
        }
    };

    const handleCreateSuccess = () => {
        fetchCampaigns();
        setIsModalOpen(false);
    };

    const requestStartCampaign = (campaignId: number) => {
        const campaign = campaigns.find(item => item.id === campaignId);
        if (campaign) setCampaignToStart(campaign);
    };

    const confirmStartCampaign = async () => {
        if (!campaignToStart) return;

        try {
            setActionLoading(prev => ({ ...prev, [campaignToStart.id]: 'starting' }));
            await startWhatsAppCampaign(campaignToStart.id);
            setCampaignToStart(null);
            fetchCampaigns();
        } catch (err) {
            console.error("Error starting campaign:", err);
            setError("Erro ao iniciar campanha.");
        } finally {
            setActionLoading(prev => campaignToStart ? ({ ...prev, [campaignToStart.id]: null }) : prev);
        }
    };

    const handlePauseCampaign = async (campaignId: number) => {
        try {
            setActionLoading(prev => ({ ...prev, [campaignId]: 'pausing' }));
            await pauseWhatsAppCampaign(campaignId);
            fetchCampaigns();
        } catch (err) {
            console.error("Error pausing campaign:", err);
            setError("Erro ao pausar campanha.");
        } finally {
            setActionLoading(prev => ({ ...prev, [campaignId]: null }));
        }
    };

    const handleDeleteCampaign = async (campaignId: number) => {
        const campaign = campaigns.find(item => item.id === campaignId);
        if (campaign) setCampaignToDelete(campaign);
    };

    const confirmDeleteCampaign = async () => {
        if (!campaignToDelete) return;
        try {
            setActionLoading(prev => ({ ...prev, [campaignToDelete.id]: 'deleting' }));
            await deleteWhatsAppCampaign(campaignToDelete.id);
            setCampaignToDelete(null);
            fetchCampaigns();
        } catch (err) {
            console.error("Error deleting campaign:", err);
            setError("Erro ao excluir campanha.");
        } finally {
            setActionLoading(prev => campaignToDelete ? ({ ...prev, [campaignToDelete.id]: null }) : prev);
        }
    };

    const filteredCampaigns = useMemo(() => {
        const normalizedSearch = searchTerm.trim().toLowerCase();

        return campaigns.filter((campaign) => {
            const matchesStatus = statusFilter === 'ALL' || campaign.status === statusFilter;
            const matchesSearch = !normalizedSearch || campaign.name.toLowerCase().includes(normalizedSearch);

            return matchesStatus && matchesSearch;
        });
    }, [campaigns, searchTerm, statusFilter]);

    const summary = useMemo(() => {
        const totalContacts = campaigns.reduce((sum, campaign) => sum + (campaign.total_contacts || 0), 0);
        const processedContacts = campaigns.reduce((sum, campaign) => sum + (campaign.processed_contacts || 0), 0);
        const failedContacts = campaigns.reduce((sum, campaign) => sum + (campaign.failed_count || 0), 0);
        const successContacts = campaigns.reduce((sum, campaign) => sum + (campaign.success_count || 0), 0);
        const progress = totalContacts > 0 ? Math.round((processedContacts / totalContacts) * 100) : 0;

        return {
            completed: campaigns.filter((campaign) => campaign.status === 'COMPLETED').length,
            failedContacts,
            processing: campaigns.filter((campaign) => campaign.status === 'PROCESSING').length,
            progress,
            successContacts,
            totalContacts,
        };
    }, [campaigns]);

    return (
        <div className={cx('px-4 pb-28 pt-4 sm:px-6 lg:px-8 xl:px-10 2xl:px-12', styles.root, isDark && styles['root--dark'])}>
            <div className={styles.shell}>
                {/* Cabeçalho de página compacto (sem hero de landing) */}
                <header className={styles.pageHead}>
                    <div className={styles.pageHeadCopy}>
                        <h1 className={styles.pageTitle}>Campanhas de WhatsApp</h1>
                        <p className={styles.pageSubtitle}>
                            Disparos segmentados com cadência inteligente, janela de envio e respostas em tempo real.
                        </p>
                    </div>
                    <div className={styles.pageActions}>
                        <button
                            type="button"
                            onClick={fetchCampaigns}
                            disabled={loading || !companyId}
                            className={agentiveSecondaryButtonClass(isDark, 'min-h-9 px-3')}
                        >
                            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                            Atualizar
                        </button>
                        <button
                            type="button"
                            onClick={() => setIsModalOpen(true)}
                            disabled={!companyId}
                            className={agentivePrimaryButtonClass('min-h-9 px-3')}
                        >
                            <Plus className="h-4 w-4" />
                            Nova campanha
                        </button>
                    </div>
                </header>

                {error && (
                    <AgentiveAlert variant="error" title="Ação não concluída" onClose={() => setError(null)}>
                        {error}
                    </AgentiveAlert>
                )}

                {/* KPIs operacionais — número grande tabular, sem ícone decorativo */}
                <section className={styles.kpiGrid} aria-label="Resumo das campanhas">
                    <KpiCard
                        detail={`${summary.processing} em andamento`}
                        label="Total de campanhas"
                        value={campaigns.length}
                    />
                    <KpiCard
                        detail={`${summary.progress}% da fila processada`}
                        label="Contatos na fila"
                        value={summary.totalContacts}
                    />
                    <KpiCard
                        detail={`${summary.completed} campanhas concluídas`}
                        label="Mensagens enviadas"
                        value={summary.successContacts}
                    />
                    <KpiCard
                        detail="Falhas registradas nos envios"
                        label="Falhas"
                        value={summary.failedContacts}
                    />
                </section>

                {/* Toolbar: busca + pills de status (segmented, seleção quieta) */}
                <section className={cx(styles.panel, styles.toolbar)} aria-label="Filtros de campanhas">
                    <div className={styles.searchBox}>
                        <Search className={styles.searchIcon} />
                        <input
                            aria-label="Buscar campanha por nome"
                            value={searchTerm}
                            onChange={(event) => setSearchTerm(event.target.value)}
                            placeholder="Buscar campanha por nome"
                            className={styles.searchInput}
                        />
                    </div>
                    <div className={styles.filterPills}>
                        {statusFilters.map((filter) => {
                            const isActive = statusFilter === filter.id;
                            return (
                                <button
                                    key={filter.id}
                                    type="button"
                                    onClick={() => setStatusFilter(filter.id)}
                                    aria-pressed={isActive}
                                    className={cx(styles.pillButton, isActive && styles.pillActive)}
                                >
                                    <span>{filter.label}</span>
                                    <span className={styles.pillBadge}>{getStatusCount(campaigns, filter.id)}</span>
                                </button>
                            );
                        })}
                    </div>
                </section>

                {/* Layout principal: lista + sidebar operacional */}
                <div className={styles.mainLayout}>
                    <section className={styles.listColumn} aria-label="Campanhas">
                        {loading ? (
                            <div className={styles.loadingCard}>
                                <span className={styles.loadingInner}>
                                    <Loader2 className="h-5 w-5 animate-spin" />
                                    Carregando campanhas...
                                </span>
                            </div>
                        ) : campaigns.length === 0 ? (
                            <AgentiveEmptyState
                                action={(
                                    <button
                                        type="button"
                                        onClick={() => setIsModalOpen(true)}
                                        className={agentivePrimaryButtonClass('min-h-9 px-3')}
                                    >
                                        <Plus className="h-4 w-4" />
                                        Criar primeira campanha
                                    </button>
                                )}
                                icon={MessageSquare}
                                title="Nenhuma campanha encontrada"
                                description="Crie uma campanha para organizar público, mensagem e janela de envio antes de iniciar o disparo."
                            />
                        ) : filteredCampaigns.length === 0 ? (
                            <AgentiveEmptyState
                                icon={Search}
                                title="Nenhuma campanha neste filtro"
                                description="Ajuste a busca por nome ou selecione outro status para visualizar as campanhas."
                            />
                        ) : (
                            filteredCampaigns.map((campaign) => (
                                <WhatsAppCampaignAnalytics
                                    key={campaign.id}
                                    campaign={campaign}
                                    onStart={requestStartCampaign}
                                    onPause={handlePauseCampaign}
                                    onDelete={handleDeleteCampaign}
                                    isStarting={actionLoading[campaign.id] === 'starting'}
                                    isPausing={actionLoading[campaign.id] === 'pausing'}
                                    isDeleting={actionLoading[campaign.id] === 'deleting'}
                                />
                            ))
                        )}
                    </section>

                    {/* Sidebar operacional densa */}
                    <aside className={styles.sidebarPanel} aria-label="Resumo da fila operacional">
                        <div className={styles.sidebarHeader}>
                            <div className={styles.panelHeadCopy}>
                                <div className={styles.sidebarTitleRow}>
                                    <Send className="h-4 w-4" />
                                    <h2 className={styles.sidebarTitle}>Fila Operacional</h2>
                                </div>
                                <p className={styles.sidebarSubtitle}>Andamento das campanhas</p>
                            </div>
                        </div>

                        <div className={styles.sidebarBody}>
                            <div className={styles.progressBlock}>
                                <div className={styles.progressHead}>
                                    <span>Processamento geral</span>
                                    <span className={styles.progressValue}>{summary.progress}%</span>
                                </div>
                                <div
                                    className={styles.progressTrack}
                                    role="progressbar"
                                    aria-label="Processamento geral"
                                    aria-valuemin={0}
                                    aria-valuemax={100}
                                    aria-valuenow={summary.progress}
                                >
                                    <div className={styles.progressBar} style={{ width: `${summary.progress}%` }} />
                                </div>
                            </div>

                            <div className={styles.statusList}>
                                <div className={styles.statusRow}>
                                    <span className={styles.statusRowLabel}>
                                        <span className={styles.statusDot} style={{ background: 'var(--camp-success)' }} />
                                        Em andamento
                                    </span>
                                    <strong className={styles.statusRowValue}>{getStatusCount(campaigns, 'PROCESSING')}</strong>
                                </div>
                                <div className={styles.statusRow}>
                                    <span className={styles.statusRowLabel}>
                                        <span className={styles.statusDot} style={{ background: 'var(--camp-warning)' }} />
                                        Pausadas
                                    </span>
                                    <strong className={styles.statusRowValue}>{getStatusCount(campaigns, 'PAUSED')}</strong>
                                </div>
                                <div className={styles.statusRow}>
                                    <span className={styles.statusRowLabel}>
                                        <span className={styles.statusDot} style={{ background: 'var(--camp-signal)' }} />
                                        Concluídas
                                    </span>
                                    <strong className={styles.statusRowValue}>{getStatusCount(campaigns, 'COMPLETED')}</strong>
                                </div>
                            </div>
                        </div>
                    </aside>
                </div>
            </div>

            {/* Campaign Modals */}
            <WhatsAppCampaignModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                companyId={companyId}
                onSuccess={handleCreateSuccess}
            />

            <AgentiveConfirmModal
                cancelText="Cancelar"
                confirmText="Iniciar campanha"
                isLoading={campaignToStart ? actionLoading[campaignToStart.id] === 'starting' : false}
                isOpen={Boolean(campaignToStart)}
                message="A fila de envio será liberada para os contatos segmentados nesta campanha."
                onClose={() => setCampaignToStart(null)}
                onConfirm={confirmStartCampaign}
                title="Iniciar campanha?"
                variant="warning"
            >
                <span className="text-sm">
                    Campanha selecionada: <strong>{campaignToStart?.name}</strong>
                </span>
            </AgentiveConfirmModal>

            <AgentiveConfirmModal
                isOpen={Boolean(campaignToDelete)}
                onClose={() => setCampaignToDelete(null)}
                onConfirm={confirmDeleteCampaign}
                isLoading={campaignToDelete ? actionLoading[campaignToDelete.id] === 'deleting' : false}
                title="Excluir campanha?"
                message="Esta campanha e seu histórico operacional serão removidos permanentemente."
                confirmText="Excluir campanha"
                variant="danger"
            >
                <span className="text-sm">
                    Campanha selecionada: <strong>{campaignToDelete?.name}</strong>
                </span>
            </AgentiveConfirmModal>
        </div>
    );
};

export default WhatsAppCampaignsPage;
