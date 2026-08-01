import React, { useEffect, useMemo, useState } from 'react';
import { createWhatsAppCampaign, estimateWhatsAppCampaignContacts } from '../../services/whatsappCampaignService';
import { getTags, type Tag } from '../../services/tagsApi';
import {
    ArrowLeft,
    ArrowRight,
    Calendar,
    Check,
    Clock,
    Hash,
    Loader2,
    MessageSquare,
    Play,
    Send,
    Sparkles,
    Timer,
    Users,
    X,
} from 'lucide-react';
import {
    AgentiveAlert,
    AgentiveConfirmModal,
} from '../AgentiveUI';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import styles from './WhatsAppCampaignModal.module.css';

const DAYS_OF_WEEK = [
    { id: 0, label: 'Seg' },
    { id: 1, label: 'Ter' },
    { id: 2, label: 'Qua' },
    { id: 3, label: 'Qui' },
    { id: 4, label: 'Sex' },
    { id: 5, label: 'Sab' },
    { id: 6, label: 'Dom' },
];

type CampaignStep = 'message' | 'audience' | 'cadence' | 'review';

const STEPS: Array<{
    id: CampaignStep;
    label: string;
    icon: React.ComponentType<{ className?: string }>;
}> = [
    { id: 'message', label: 'Mensagem', icon: MessageSquare },
    { id: 'audience', label: 'Público', icon: Users },
    { id: 'cadence', label: 'Cadência', icon: Timer },
    { id: 'review', label: 'Revisão', icon: Check },
];

const cx = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(' ');

interface WhatsAppCampaignModalProps {
    isOpen: boolean;
    onClose: () => void;
    companyId: number;
    onSuccess?: () => void;
}

const formatSelectedDays = (allowedDays: number[]) => {
    if (allowedDays.length === 0 || allowedDays.length === DAYS_OF_WEEK.length) return 'Todos os dias';

    return allowedDays
        .map((dayId) => DAYS_OF_WEEK.find((day) => day.id === dayId)?.label)
        .filter(Boolean)
        .join(', ');
};

export function WhatsAppCampaignModal({ isOpen, onClose, companyId, onSuccess }: WhatsAppCampaignModalProps) {
    const { isDark } = useTheme();
    const [loading, setLoading] = useState(false);
    const [initializing, setInitializing] = useState(false);
    const [estimating, setEstimating] = useState(false);
    const [estimatedContacts, setEstimatedContacts] = useState<number | null>(null);
    const [currentStep, setCurrentStep] = useState<CampaignStep>('message');
    const [showLaunchConfirm, setShowLaunchConfirm] = useState(false);

    const [name, setName] = useState('');
    const [messageText, setMessageText] = useState('');
    const [selectedTags, setSelectedTags] = useState<number[]>([]);
    const [excludedTags, setExcludedTags] = useState<number[]>([]);
    const [intervalMin, setIntervalMin] = useState(1);
    const [intervalMax, setIntervalMax] = useState(5);
    const [dailyStartTime, setDailyStartTime] = useState('08:00');
    const [dailyEndTime, setDailyEndTime] = useState('20:00');
    const [allowedDays, setAllowedDays] = useState<number[]>([]);

    const [tags, setTags] = useState<Tag[]>([]);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (isOpen) {
            fetchData();
            setName('');
            setMessageText('');
            setSelectedTags([]);
            setExcludedTags([]);
            setEstimatedContacts(null);
            setIntervalMin(1);
            setIntervalMax(5);
            setDailyStartTime('08:00');
            setDailyEndTime('20:00');
            setAllowedDays([]);
            setCurrentStep('message');
            setShowLaunchConfirm(false);
            setError(null);
        }
    }, [isOpen]);

    useEffect(() => {
        if (selectedTags.length > 0) {
            handleEstimate();
        } else {
            setEstimatedContacts(null);
        }
    }, [selectedTags, excludedTags]);

    const currentStepIndex = STEPS.findIndex((step) => step.id === currentStep);
    const isLastStep = currentStep === 'review';

    const includedTagNames = useMemo(
        () => tags.filter((tag) => selectedTags.includes(tag.id)).map((tag) => tag.name),
        [selectedTags, tags]
    );
    const excludedTagNames = useMemo(
        () => tags.filter((tag) => excludedTags.includes(tag.id)).map((tag) => tag.name),
        [excludedTags, tags]
    );

    const fetchData = async () => {
        setInitializing(true);
        setError(null);
        try {
            const tagsData = await getTags(companyId);
            setTags(tagsData || []);
        } catch (err) {
            console.error('Error fetching data', err);
            setError('Não foi possível carregar as tags.');
        } finally {
            setInitializing(false);
        }
    };

    const handleEstimate = async () => {
        if (selectedTags.length === 0) return;

        setEstimating(true);
        try {
            const data = await estimateWhatsAppCampaignContacts({
                tag_ids: selectedTags,
                exclude_tag_ids: excludedTags,
            });
            setEstimatedContacts(data.count);
        } catch (err) {
            console.error('Error estimating contacts', err);
        } finally {
            setEstimating(false);
        }
    };

    const validateStep = (step: CampaignStep) => {
        if (step === 'message') {
            if (!name.trim()) return 'Informe o nome da campanha.';
            if (!messageText.trim()) return 'Escreva a mensagem base da campanha.';
        }

        if (step === 'audience' && selectedTags.length === 0) {
            return 'Selecione pelo menos uma tag para definir o público.';
        }

        if (step === 'cadence') {
            if (dailyStartTime >= dailyEndTime) return 'O horário de início deve ser anterior ao horário de fim.';
            if (intervalMin > intervalMax) return 'O intervalo mínimo não pode ser maior que o máximo.';
            if (intervalMin < 1 || intervalMax < 1) return 'Os intervalos precisam ser maiores que zero.';
        }

        return null;
    };

    const validateAll = () => {
        for (const step of STEPS) {
            const stepError = validateStep(step.id);
            if (stepError) {
                setCurrentStep(step.id);
                return stepError;
            }
        }

        return null;
    };

    const handleNext = () => {
        const stepError = validateStep(currentStep);
        if (stepError) {
            setError(stepError);
            return;
        }

        setError(null);
        const nextStep = STEPS[currentStepIndex + 1]?.id;
        if (nextStep) setCurrentStep(nextStep);
    };

    const handleBack = () => {
        setError(null);
        const previousStep = STEPS[currentStepIndex - 1]?.id;
        if (previousStep) setCurrentStep(previousStep);
    };

    const requestSubmit = () => {
        const formError = validateAll();
        if (formError) {
            setError(formError);
            return;
        }

        setError(null);
        setShowLaunchConfirm(true);
    };

    const handleSubmit = async () => {
        setLoading(true);
        setError(null);
        try {
            await createWhatsAppCampaign({
                name: name.trim(),
                message_text: messageText.trim(),
                tag_ids: selectedTags,
                exclude_tag_ids: excludedTags,
                interval_min: intervalMin,
                interval_max: intervalMax,
                start_immediately: true,
                daily_start_time: dailyStartTime,
                daily_end_time: dailyEndTime,
                allowed_days: allowedDays.length > 0 ? allowedDays : undefined,
            });

            setShowLaunchConfirm(false);
            onSuccess?.();
            onClose();
        } catch (err) {
            console.error('Error creating campaign', err);
            setShowLaunchConfirm(false);
            setError('Ocorreu um erro ao tentar criar a campanha via API.');
        } finally {
            setLoading(false);
        }
    };

    const toggleTag = (tagId: number, type: 'include' | 'exclude') => {
        if (type === 'include') {
            setSelectedTags(prev =>
                prev.includes(tagId) ? prev.filter(id => id !== tagId) : [...prev, tagId]
            );

            if (excludedTags.includes(tagId)) {
                setExcludedTags(prev => prev.filter(id => id !== tagId));
            }
        } else {
            setExcludedTags(prev =>
                prev.includes(tagId) ? prev.filter(id => id !== tagId) : [...prev, tagId]
            );

            if (selectedTags.includes(tagId)) {
                setSelectedTags(prev => prev.filter(id => id !== tagId));
            }
        }
    };

    const renderTags = (type: 'include' | 'exclude') => {
        const activeIds = type === 'include' ? selectedTags : excludedTags;

        if (tags.length === 0) {
            return (
                <div className={styles.emptyTags}>
                    Nenhuma tag disponível.
                </div>
            );
        }

        return (
            <div className={styles.tagList}>
                {tags.map(tag => {
                    const isSelected = activeIds.includes(tag.id);

                    return (
                        <button
                            key={`${type}-${tag.id}`}
                            type="button"
                            onClick={() => toggleTag(tag.id, type)}
                            aria-pressed={isSelected}
                            className={cx(
                                styles.tagButton,
                                isSelected && (
                                    type === 'include'
                                        ? styles.tagButtonIncluded
                                        : styles.tagButtonExcluded
                                )
                            )}
                        >
                            {tag.name}
                        </button>
                    );
                })}
            </div>
        );
    };

    const renderStepContent = () => {
        if (initializing) {
            return (
                <div className={styles.loadingState} role="status">
                    <Loader2 className={styles.loadingSpinner} aria-hidden="true" />
                    <span>Carregando configurações da campanha…</span>
                </div>
            );
        }

        if (currentStep === 'message') {
            return (
                <div className={cx(styles.stepPane, styles.messageGrid)}>
                    <div className={styles.formStack}>
                        <div className={styles.field}>
                            <label className={styles.fieldLabel} htmlFor="campaign-name">Nome da campanha</label>
                            <input
                                id="campaign-name"
                                value={name}
                                onChange={(event) => setName(event.target.value)}
                                placeholder="Ex: Reativação de leads"
                                className={styles.input}
                            />
                        </div>

                        <div className={styles.field}>
                            <div className={styles.fieldLabelRow}>
                                <label className={styles.fieldLabel} htmlFor="campaign-message">Mensagem base</label>
                                <button
                                    type="button"
                                    onClick={() => setMessageText(prev => `${prev}${prev.endsWith(' ') || prev.length === 0 ? '' : ' '}{{primeiro_nome}}`)}
                                    className={styles.tokenButton}
                                >
                                    <Hash aria-hidden="true" />
                                    Primeiro nome
                                </button>
                            </div>
                            <textarea
                                id="campaign-message"
                                value={messageText}
                                onChange={(event) => setMessageText(event.target.value)}
                                placeholder="Escreva a mensagem que será usada como base do disparo."
                                className={styles.textarea}
                            />
                        </div>
                    </div>

                    <aside className={cx(styles.sectionPanel, styles.previewPanel)}>
                        <div className={styles.panelHeader}>
                            <span className={styles.sectionIcon}>
                                <Sparkles aria-hidden="true" />
                            </span>
                            <div>
                                <h3 className={styles.panelTitle}>Prévia da mensagem</h3>
                                <p className={styles.panelMeta}>{messageText.length} caracteres</p>
                            </div>
                        </div>
                        <div className={styles.previewStage}>
                            <div className={cx(styles.messageBubble, !messageText.trim() && styles.messageBubblePlaceholder)}>
                                {messageText.trim()
                                    ? messageText.replace('{{primeiro_nome}}', 'Ana')
                                    : 'A mensagem aparecerá aqui.'}
                            </div>
                        </div>
                    </aside>
                </div>
            );
        }

        if (currentStep === 'audience') {
            return (
                <div className={styles.stepPane}>
                    <div className={styles.audienceGrid}>
                        <section className={styles.sectionPanel}>
                            <div className={styles.panelHeader}>
                                <div>
                                    <h3 className={styles.panelTitle}>Incluir tags</h3>
                                    <p className={styles.panelMeta}>{selectedTags.length} selecionadas</p>
                                </div>
                                <Users className={styles.panelHeaderIcon} aria-hidden="true" />
                            </div>
                            {renderTags('include')}
                        </section>

                        <section className={styles.sectionPanel}>
                            <div className={styles.panelHeader}>
                                <div>
                                    <h3 className={styles.panelTitle}>Excluir tags</h3>
                                    <p className={styles.panelMeta}>{excludedTags.length} selecionadas</p>
                                </div>
                                <X className={styles.panelHeaderIcon} aria-hidden="true" />
                            </div>
                            {renderTags('exclude')}
                        </section>
                    </div>

                    <div className={styles.audienceEstimate}>
                        <div className={styles.estimateCopy}>
                            <span className={styles.estimateIcon}>
                                <Users aria-hidden="true" />
                            </span>
                            <div>
                                <p className={styles.panelTitle}>Estimativa de público</p>
                                <p className={styles.panelMeta}>Contatos únicos no recorte selecionado</p>
                            </div>
                        </div>
                        <div className={styles.estimateValue} aria-live="polite">
                            {estimating ? (
                                <Loader2 className={styles.inlineSpinner} aria-hidden="true" />
                            ) : estimatedContacts !== null ? (
                                <span>{estimatedContacts}</span>
                            ) : (
                                <span className={styles.valuePlaceholder}>--</span>
                            )}
                        </div>
                    </div>
                </div>
            );
        }

        if (currentStep === 'cadence') {
            return (
                <div className={cx(styles.stepPane, styles.cadenceGrid)}>
                    <section className={styles.sectionPanel}>
                        <div className={styles.panelHeader}>
                            <span className={styles.sectionIcon}>
                                <Timer aria-hidden="true" />
                            </span>
                            <div>
                                <h3 className={styles.panelTitle}>Intervalo entre envios</h3>
                                <p className={styles.panelMeta}>Distribuição entre cada contato</p>
                            </div>
                        </div>
                        <div className={styles.twoColumnFields}>
                            <div className={styles.field}>
                                <label className={styles.fieldLabel} htmlFor="campaign-interval-min">Mínimo em minutos</label>
                                <input
                                    id="campaign-interval-min"
                                    type="number"
                                    min={1}
                                    max={60}
                                    value={intervalMin}
                                    onChange={(event) => setIntervalMin(parseInt(event.target.value, 10) || 1)}
                                    className={styles.input}
                                />
                            </div>
                            <div className={styles.field}>
                                <label className={styles.fieldLabel} htmlFor="campaign-interval-max">Máximo em minutos</label>
                                <input
                                    id="campaign-interval-max"
                                    type="number"
                                    min={1}
                                    max={60}
                                    value={intervalMax}
                                    onChange={(event) => setIntervalMax(parseInt(event.target.value, 10) || 1)}
                                    className={styles.input}
                                />
                            </div>
                        </div>
                    </section>

                    <section className={styles.sectionPanel}>
                        <div className={styles.panelHeader}>
                            <span className={styles.sectionIcon}>
                                <Clock aria-hidden="true" />
                            </span>
                            <div>
                                <h3 className={styles.panelTitle}>Janela diária</h3>
                                <p className={styles.panelMeta}>Horário permitido para envios</p>
                            </div>
                        </div>
                        <div className={styles.twoColumnFields}>
                            <div className={styles.field}>
                                <label className={styles.fieldLabel} htmlFor="campaign-daily-start">Início</label>
                                <input
                                    id="campaign-daily-start"
                                    type="time"
                                    value={dailyStartTime}
                                    onChange={(event) => setDailyStartTime(event.target.value)}
                                    className={styles.input}
                                />
                            </div>
                            <div className={styles.field}>
                                <label className={styles.fieldLabel} htmlFor="campaign-daily-end">Fim</label>
                                <input
                                    id="campaign-daily-end"
                                    type="time"
                                    value={dailyEndTime}
                                    onChange={(event) => setDailyEndTime(event.target.value)}
                                    className={styles.input}
                                />
                            </div>
                        </div>
                    </section>

                    <section className={cx(styles.sectionPanel, styles.daysPanel)}>
                        <div className={styles.panelHeader}>
                            <span className={styles.sectionIcon}>
                                <Calendar aria-hidden="true" />
                            </span>
                            <div>
                                <h3 className={styles.panelTitle}>Dias permitidos</h3>
                                <p className={styles.panelMeta}>{formatSelectedDays(allowedDays)}</p>
                            </div>
                        </div>
                        <div className={styles.daysList}>
                            {DAYS_OF_WEEK.map((day) => {
                                const isSelected = allowedDays.includes(day.id);

                                return (
                                    <button
                                        key={day.id}
                                        type="button"
                                        onClick={() => {
                                            setAllowedDays(prev =>
                                                prev.includes(day.id)
                                                    ? prev.filter(d => d !== day.id)
                                                    : [...prev, day.id].sort()
                                            );
                                        }}
                                        aria-pressed={isSelected}
                                        className={cx(styles.dayButton, isSelected && styles.dayButtonSelected)}
                                    >
                                        {day.label}
                                    </button>
                                );
                            })}
                        </div>
                    </section>
                </div>
            );
        }

        return (
            <div className={cx(styles.stepPane, styles.reviewGrid)}>
                <section className={styles.sectionPanel}>
                    <div className={styles.panelHeader}>
                        <span className={styles.sectionIcon}>
                            <MessageSquare aria-hidden="true" />
                        </span>
                        <div>
                            <h3 className={styles.panelTitle}>Campanha</h3>
                            <p className={styles.panelMeta}>Conteúdo que será enviado</p>
                        </div>
                    </div>
                    <dl className={styles.reviewList}>
                        <div className={styles.reviewBlock}>
                            <dt>Nome</dt>
                            <dd>{name || '-'}</dd>
                        </div>
                        <div className={styles.reviewBlock}>
                            <dt>Mensagem</dt>
                            <dd className={styles.reviewMessage}>
                                {messageText || '-'}
                            </dd>
                        </div>
                    </dl>
                </section>

                <section className={styles.sectionPanel}>
                    <div className={styles.panelHeader}>
                        <span className={styles.sectionIcon}>
                            <Send aria-hidden="true" />
                        </span>
                        <div>
                            <h3 className={styles.panelTitle}>Envio</h3>
                            <p className={styles.panelMeta}>Público e regras da fila</p>
                        </div>
                    </div>
                    <dl className={styles.reviewList}>
                        <div className={styles.reviewRow}>
                            <dt>Público estimado</dt>
                            <dd>{estimatedContacts ?? '--'}</dd>
                        </div>
                        <div className={styles.reviewBlock}>
                            <dt>Tags incluídas</dt>
                            <dd>{includedTagNames.length > 0 ? includedTagNames.join(', ') : '-'}</dd>
                        </div>
                        <div className={styles.reviewBlock}>
                            <dt>Tags excluídas</dt>
                            <dd>{excludedTagNames.length > 0 ? excludedTagNames.join(', ') : '-'}</dd>
                        </div>
                        <div className={styles.reviewRow}>
                            <dt>Intervalo</dt>
                            <dd>{intervalMin} - {intervalMax} min</dd>
                        </div>
                        <div className={styles.reviewRow}>
                            <dt>Janela</dt>
                            <dd>{dailyStartTime} - {dailyEndTime}</dd>
                        </div>
                        <div className={styles.reviewBlock}>
                            <dt>Dias</dt>
                            <dd>{formatSelectedDays(allowedDays)}</dd>
                        </div>
                    </dl>
                </section>
            </div>
        );
    };

    if (!isOpen) return null;

    return (
        <div className={cx(styles.root, isDark && styles.rootDark)}>
            <div
                className={styles.dialog}
                role="dialog"
                aria-modal="true"
                aria-labelledby="campaign-modal-title"
                aria-describedby="campaign-modal-description"
            >
                <header className={styles.header}>
                    <div className={styles.headerCopy}>
                        <span className={styles.headerIcon}>
                            <MessageSquare aria-hidden="true" />
                        </span>
                        <div className={styles.headerText}>
                            <div className={styles.eyebrow}>Campanha WhatsApp</div>
                            <h2 id="campaign-modal-title" className={styles.title}>Nova campanha</h2>
                            <p id="campaign-modal-description" className={styles.subtitle}>
                                Configure mensagem, público e cadência antes do envio.
                            </p>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={loading}
                        className={styles.closeButton}
                        aria-label="Fechar modal"
                    >
                        <X aria-hidden="true" />
                    </button>
                </header>

                <nav className={styles.stepper} aria-label="Etapas da campanha">
                    {STEPS.map((step, index) => {
                        const Icon = step.icon;
                        const isActive = step.id === currentStep;
                        const isDone = index < currentStepIndex;

                        return (
                            <React.Fragment key={step.id}>
                                {index > 0 && (
                                    <span
                                        className={cx(styles.stepConnector, index <= currentStepIndex && styles.stepConnectorDone)}
                                        aria-hidden="true"
                                    />
                                )}
                                <button
                                    type="button"
                                    disabled={index > currentStepIndex || loading || initializing}
                                    onClick={() => setCurrentStep(step.id)}
                                    aria-current={isActive ? 'step' : undefined}
                                    className={cx(
                                        styles.stepButton,
                                        isActive && styles.stepButtonActive,
                                        isDone && styles.stepButtonDone
                                    )}
                                >
                                    <span className={styles.stepIcon}>
                                        {isDone ? <Check aria-hidden="true" /> : <Icon aria-hidden="true" />}
                                    </span>
                                    <span className={styles.stepCopy}>
                                        <span className={styles.stepNumber}>Etapa {index + 1}</span>
                                        <span className={styles.stepLabel}>{step.label}</span>
                                    </span>
                                </button>
                            </React.Fragment>
                        );
                    })}
                </nav>

                <div className={styles.body}>
                    <div className={styles.content}>
                        {error && (
                            <div className={styles.alert}>
                                <AgentiveAlert variant="error" title="Revise a campanha">
                                    {error}
                                </AgentiveAlert>
                            </div>
                        )}
                        {renderStepContent()}
                    </div>
                </div>

                <footer className={styles.footer}>
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={loading}
                        className={styles.secondaryButton}
                    >
                        Cancelar
                    </button>

                    <div className={styles.footerActions}>
                        {currentStepIndex > 0 && (
                            <button
                                type="button"
                                onClick={handleBack}
                                disabled={loading || initializing}
                                className={styles.secondaryButton}
                            >
                                <ArrowLeft aria-hidden="true" />
                                Voltar
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={isLastStep ? requestSubmit : handleNext}
                            disabled={loading || initializing}
                            className={styles.primaryButton}
                        >
                            {isLastStep ? (
                                <>
                                    <Play aria-hidden="true" />
                                    Iniciar campanha
                                </>
                            ) : (
                                <>
                                    Continuar
                                    <ArrowRight aria-hidden="true" />
                                </>
                            )}
                        </button>
                    </div>
                </footer>
            </div>

            <AgentiveConfirmModal
                cancelText="Revisar"
                confirmText="Iniciar envio"
                isLoading={loading}
                isOpen={showLaunchConfirm}
                message={(
                    <span>
                        A campanha será criada e a fila será iniciada para {estimatedContacts ?? 'os'} contatos estimados.
                    </span>
                )}
                onClose={() => setShowLaunchConfirm(false)}
                onConfirm={handleSubmit}
                title="Iniciar campanha agora?"
                variant="warning"
            />
        </div>
    );
}
