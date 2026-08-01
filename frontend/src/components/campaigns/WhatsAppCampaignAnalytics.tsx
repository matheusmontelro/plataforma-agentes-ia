import React, { useEffect, useState } from 'react';
import {
    AlertTriangle,
    CalendarDays,
    CheckCircle,
    ChevronDown,
    ChevronUp,
    Clock,
    Loader2,
    MessageSquare,
    MoreHorizontal,
    Pause,
    Play,
    Send,
    Timer,
    Trash2,
    TrendingUp,
    Users,
    XCircle,
} from 'lucide-react';
import { format } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import {
    CampaignAnalytics,
    getWhatsAppCampaignAnalytics,
    getWhatsAppCampaignExecutions,
    WhatsAppCampaign,
    WhatsAppCampaignExecution,
} from '../../services/whatsappCampaignService';
import styles from './WhatsAppCampaignAnalytics.module.css';

interface WhatsAppCampaignAnalyticsProps {
    campaign: WhatsAppCampaign;
    onStart?: (id: number) => void;
    onPause?: (id: number) => void;
    onDelete?: (id: number) => void;
    isStarting?: boolean;
    isPausing?: boolean;
    isDeleting?: boolean;
}

const cx = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

const getStatusIcon = (status: string) => {
    switch (status) {
        case 'COMPLETED':
            return <CheckCircle className={styles.statusGlyph} aria-hidden="true" />;
        case 'PROCESSING':
            return <Loader2 className={cx(styles.statusGlyph, styles.spin)} aria-hidden="true" />;
        case 'FAILED':
            return <XCircle className={styles.statusGlyph} aria-hidden="true" />;
        case 'PAUSED':
            return <Pause className={styles.statusGlyph} aria-hidden="true" />;
        case 'DRAFT':
            return <Clock className={styles.statusGlyph} aria-hidden="true" />;
        default:
            return <AlertTriangle className={styles.statusGlyph} aria-hidden="true" />;
    }
};

const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
        DRAFT: 'Rascunho',
        PROCESSING: 'Em Andamento',
        COMPLETED: 'Concluído',
        PAUSED: 'Pausado',
        FAILED: 'Falhou',
        CANCELED: 'Cancelado',
    };
    return labels[status] || status;
};

const getStatusClass = (status: string) => {
    switch (status) {
        case 'PROCESSING':
            return styles.statusProcessing;
        case 'COMPLETED':
            return styles.statusCompleted;
        case 'PAUSED':
            return styles.statusPaused;
        case 'FAILED':
            return styles.statusFailed;
        case 'DRAFT':
            return styles.statusDraft;
        default:
            return styles.statusNeutral;
    }
};

const getExecutionStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
        PENDING: 'Pendente',
        SCHEDULED: 'Agendado',
        SENT: 'Enviado',
        REPLIED: 'Respondido',
        FAILED: 'Falhou',
        SKIPPED: 'Pulado',
    };
    return labels[status] || status;
};

const getExecutionStatusClass = (status: string) => {
    switch (status) {
        case 'REPLIED':
            return styles.executionReplied;
        case 'SENT':
            return styles.executionSent;
        case 'FAILED':
            return styles.executionFailed;
        case 'SCHEDULED':
            return styles.executionScheduled;
        case 'PENDING':
            return styles.executionPending;
        default:
            return styles.executionNeutral;
    }
};

const DAY_LABELS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sab', 'Dom'];

const formatDateTime = (value?: string | null) => {
    if (!value) return '-';

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-';

    return format(date, 'dd/MM/yyyy HH:mm', { locale: ptBR });
};

const formatShortTime = (value?: string | null) => {
    if (!value) return '-';

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-';

    return format(date, 'HH:mm', { locale: ptBR });
};

const formatAllowedDays = (days?: number[]) => {
    if (!days || days.length === 0 || days.length >= 7) return 'Todos os dias';

    return days
        .map((day) => DAY_LABELS[day])
        .filter(Boolean)
        .join(', ');
};

const formatSendWindow = (campaign: WhatsAppCampaign) => {
    if (!campaign.daily_start_time || !campaign.daily_end_time) return 'Janela livre';
    return `${campaign.daily_start_time} - ${campaign.daily_end_time}`;
};

export const WhatsAppCampaignAnalytics: React.FC<WhatsAppCampaignAnalyticsProps> = ({
    campaign,
    onStart,
    onPause,
    onDelete,
    isStarting,
    isPausing,
    isDeleting,
}) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const [analytics, setAnalytics] = useState<CampaignAnalytics | null>(null);
    const [executions, setExecutions] = useState<WhatsAppCampaignExecution[]>([]);
    const [loadingData, setLoadingData] = useState(false);

    useEffect(() => {
        if (isExpanded) {
            fetchData();
        }
    }, [isExpanded, campaign.id]);

    const fetchData = async () => {
        try {
            setLoadingData(true);
            const [analyticsData, executionsData] = await Promise.all([
                getWhatsAppCampaignAnalytics(campaign.id),
                getWhatsAppCampaignExecutions(campaign.id, undefined, 0, 50), // Last 50 executions
            ]);
            setAnalytics(analyticsData);
            setExecutions(executionsData);
        } catch (error) {
            console.error('Error fetching campaign details:', error);
        } finally {
            setLoadingData(false);
        }
    };

    const progress = campaign.total_contacts > 0
        ? Math.round((campaign.processed_contacts / campaign.total_contacts) * 100)
        : 0;
    const detailsId = `campaign-details-${campaign.id}`;
    const statusClass = getStatusClass(campaign.status);

    return (
        <article className={cx(styles.card, isExpanded && styles.cardExpanded)}>
            <div className={styles.summary}>
                <div className={styles.identity}>
                    <span className={cx(styles.statusIcon, statusClass)}>
                        {getStatusIcon(campaign.status)}
                    </span>

                    <div className={styles.identityCopy}>
                        <div className={styles.titleRow}>
                            <h3 className={styles.title}>{campaign.name}</h3>
                            <span className={cx(styles.statusBadge, statusClass)}>
                                {getStatusLabel(campaign.status)}
                            </span>
                            {campaign.status === 'PROCESSING' && (
                                <span className={styles.sendingBadge}>
                                    <Loader2 className={cx(styles.inlineIcon, styles.spin)} aria-hidden="true" />
                                    Enviando
                                </span>
                            )}
                        </div>

                        <div className={styles.metadata}>
                            <span className={styles.metaItem}>
                                <Users className={styles.metaIcon} aria-hidden="true" />
                                {campaign.total_contacts} contatos
                            </span>
                            <span className={styles.metaItem}>
                                <CalendarDays className={styles.metaIcon} aria-hidden="true" />
                                {formatAllowedDays(campaign.allowed_days)}
                            </span>
                            <span className={styles.metaItem}>
                                <Timer className={styles.metaIcon} aria-hidden="true" />
                                {formatSendWindow(campaign)}
                            </span>
                            <span className={styles.metaItem}>
                                <Clock className={styles.metaIcon} aria-hidden="true" />
                                {formatDateTime(campaign.created_at)}
                            </span>
                        </div>
                    </div>
                </div>

                <div className={styles.actions}>
                    {campaign.status === 'DRAFT' || campaign.status === 'PAUSED' ? (
                        <button
                            type="button"
                            className={cx(styles.button, styles.buttonPrimary)}
                            onClick={(event) => {
                                event.stopPropagation();
                                onStart?.(campaign.id);
                            }}
                            disabled={isStarting}
                        >
                            {isStarting ? (
                                <Loader2 className={cx(styles.buttonIcon, styles.spin)} aria-hidden="true" />
                            ) : (
                                <Play className={styles.buttonIcon} aria-hidden="true" />
                            )}
                            Iniciar
                        </button>
                    ) : campaign.status === 'PROCESSING' ? (
                        <button
                            type="button"
                            className={cx(styles.button, styles.buttonSecondary)}
                            onClick={(event) => {
                                event.stopPropagation();
                                onPause?.(campaign.id);
                            }}
                            disabled={isPausing}
                        >
                            {isPausing ? (
                                <Loader2 className={cx(styles.buttonIcon, styles.spin)} aria-hidden="true" />
                            ) : (
                                <Pause className={styles.buttonIcon} aria-hidden="true" />
                            )}
                            Pausar
                        </button>
                    ) : null}

                    {campaign.status !== 'PROCESSING' && (
                        <button
                            type="button"
                            className={cx(styles.button, styles.iconButton, styles.buttonDanger)}
                            onClick={(event) => {
                                event.stopPropagation();
                                onDelete?.(campaign.id);
                            }}
                            disabled={isDeleting}
                            title="Excluir campanha"
                            aria-label="Excluir campanha"
                        >
                            {isDeleting ? (
                                <Loader2 className={cx(styles.buttonIcon, styles.spin)} aria-hidden="true" />
                            ) : (
                                <Trash2 className={styles.buttonIcon} aria-hidden="true" />
                            )}
                        </button>
                    )}

                    <button
                        type="button"
                        className={cx(styles.button, styles.buttonSecondary, styles.detailsButton)}
                        onClick={() => setIsExpanded(!isExpanded)}
                        aria-expanded={isExpanded}
                        aria-controls={detailsId}
                    >
                        {isExpanded ? (
                            <ChevronUp className={styles.buttonIcon} aria-hidden="true" />
                        ) : (
                            <ChevronDown className={styles.buttonIcon} aria-hidden="true" />
                        )}
                        Detalhes
                    </button>
                </div>
            </div>

            <div className={styles.progressSection}>
                <div className={styles.progressCopy}>
                    <span>
                        Processados: <strong>{campaign.processed_contacts}</strong> de {campaign.total_contacts}
                    </span>
                    <strong>{progress}%</strong>
                </div>
                <div
                    className={styles.progressTrack}
                    role="progressbar"
                    aria-label={`Progresso da campanha ${campaign.name}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={progress}
                >
                    <span
                        className={cx(styles.progressBar, campaign.status === 'FAILED' && styles.progressBarFailed)}
                        style={{ width: `${progress}%` }}
                    />
                </div>
            </div>

            {isExpanded && (
                <div id={detailsId} className={styles.details}>
                    {loadingData && !analytics ? (
                        <div className={styles.loadingState} role="status">
                            <Loader2 className={cx(styles.loadingIcon, styles.spin)} aria-hidden="true" />
                            <span>Carregando desempenho da campanha...</span>
                        </div>
                    ) : analytics ? (
                        <div className={styles.detailsContent}>
                            <section className={styles.metricGrid} aria-label="Métricas da campanha">
                                <div className={styles.metric}>
                                    <div className={styles.metricHead}>
                                        <span>Mensagens enviadas</span>
                                        <Send className={styles.metricIcon} aria-hidden="true" />
                                    </div>
                                    <strong className={styles.metricValue}>{analytics.sent_count}</strong>
                                    <span className={styles.metricDetail}>
                                        Total processado: {analytics.total_contacts}
                                    </span>
                                </div>

                                <div className={styles.metric}>
                                    <div className={styles.metricHead}>
                                        <span>Respostas recebidas</span>
                                        <MessageSquare className={cx(styles.metricIcon, styles.successIcon)} aria-hidden="true" />
                                    </div>
                                    <div className={styles.metricValueRow}>
                                        <strong className={styles.metricValue}>{analytics.replied_count}</strong>
                                        <span className={styles.rateBadge}>{analytics.reply_rate}% taxa</span>
                                    </div>
                                    <span className={styles.metricDetail}>Engajamento real</span>
                                </div>

                                <div className={styles.metric}>
                                    <div className={styles.metricHead}>
                                        <span>Eficiência</span>
                                        <TrendingUp className={styles.metricIcon} aria-hidden="true" />
                                    </div>
                                    <strong className={styles.metricValue}>
                                        {analytics.sent_count > 0
                                            ? Math.round((analytics.replied_count / analytics.sent_count) * 100)
                                            : 0}%
                                    </strong>
                                    <span className={styles.metricDetail}>Conversão de resposta</span>
                                </div>
                            </section>

                            <div className={styles.listGrid}>
                                <section className={styles.listPanel}>
                                    <header className={styles.listHeader}>
                                        <h4 className={styles.listTitle}>
                                            <MessageSquare className={cx(styles.listTitleIcon, styles.successIcon)} aria-hidden="true" />
                                            Quem respondeu
                                        </h4>
                                        <span className={styles.countBadge}>
                                            {analytics.contacts_who_replied.length} leads
                                        </span>
                                    </header>

                                    <div className={styles.listScroll}>
                                        {analytics.contacts_who_replied.length === 0 ? (
                                            <div className={styles.emptyState}>
                                                Nenhuma resposta registrada ainda.
                                            </div>
                                        ) : (
                                            <div className={styles.rows}>
                                                {analytics.contacts_who_replied.map((contact) => (
                                                    <div key={contact.contact_id} className={styles.row}>
                                                        <div className={styles.rowIdentity}>
                                                            <strong className={styles.rowName}>{contact.name}</strong>
                                                            <span className={styles.rowSecondary}>{contact.phone}</span>
                                                        </div>
                                                        <div className={styles.rowMeta}>
                                                            <span className={styles.replyBadge}>Respondeu</span>
                                                            <time className={styles.rowTime}>
                                                                {formatDateTime(contact.replied_at)}
                                                            </time>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </section>

                                <section className={styles.listPanel}>
                                    <header className={styles.listHeader}>
                                        <h4 className={styles.listTitle}>
                                            <Send className={styles.listTitleIcon} aria-hidden="true" />
                                            Últimos envios
                                        </h4>
                                        <MoreHorizontal className={styles.headerIcon} aria-hidden="true" />
                                    </header>

                                    <div className={styles.listScroll}>
                                        {executions.length === 0 ? (
                                            <div className={styles.emptyState}>
                                                Nenhum envio realizado ainda.
                                            </div>
                                        ) : (
                                            <div className={styles.rows}>
                                                {executions.map((execution) => (
                                                    <div key={execution.id} className={styles.row}>
                                                        <div className={styles.rowIdentity}>
                                                            <strong className={styles.rowName}>
                                                                {execution.contact_name || 'Desconhecido'}
                                                            </strong>
                                                            <span className={styles.rowSecondary}>
                                                                {execution.contact_phone || '-'}
                                                            </span>
                                                        </div>
                                                        <div className={styles.rowMeta}>
                                                            <span className={cx(styles.executionBadge, getExecutionStatusClass(execution.status))}>
                                                                {getExecutionStatusLabel(execution.status)}
                                                            </span>
                                                            <time className={styles.rowTime}>
                                                                {execution.sent_at
                                                                    ? formatShortTime(execution.sent_at)
                                                                    : execution.scheduled_for
                                                                        ? formatShortTime(execution.scheduled_for)
                                                                        : '-'}
                                                            </time>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </section>
                            </div>
                        </div>
                    ) : (
                        <div className={styles.errorState} role="alert">
                            <AlertTriangle className={styles.errorIcon} aria-hidden="true" />
                            Erro ao carregar dados da campanha.
                        </div>
                    )}
                </div>
            )}
        </article>
    );
};
