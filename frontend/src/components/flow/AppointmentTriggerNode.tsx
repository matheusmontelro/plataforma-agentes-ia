import React, { memo, useEffect, useRef, useState } from 'react';
import { Handle, Position, NodeProps, useReactFlow } from 'reactflow';
import { CalendarClock, Trash2 } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { calendarApi, type Agenda } from '../../services/calendar_api.ts';
import { useFlowVariables } from '../../contexts/FlowVariablesContext.tsx';
import { NodeContextMenu } from './NodeContextMenu.tsx';
import { useFlowConfirm } from './FlowConfirmContext.tsx';

const eventOptions = [
    { value: 'appointment_scheduled', label: 'Criado ou remarcado' },
    { value: 'appointment_created', label: 'Agendamento criado' },
    { value: 'appointment_rescheduled', label: 'Agendamento remarcado' },
    { value: 'appointment_status_changed', label: 'Status alterado' },
];

const statusOptions = [
    { value: '', label: 'Qualquer status' },
    { value: 'SCHEDULED', label: 'Agendado' },
    { value: 'NO_SHOW', label: 'No-show' },
    { value: 'CONFIRMED', label: 'Confirmado' },
];

const AppointmentTriggerNode = ({ data, id, selected }: NodeProps) => {
    const { isDark } = useTheme();
    const { deleteElements } = useReactFlow();
    const { setNodeExecutionData } = useFlowVariables();
    const { confirm } = useFlowConfirm();
    const [eventType, setEventType] = useState(data.eventType || 'appointment_scheduled');
    const [status, setStatus] = useState(data.status || data.statusFilter || '');
    const [agendaId, setAgendaId] = useState(data.agendaId || '');
    const [agendas, setAgendas] = useState<Agenda[]>([]);
    const [loadingAgendas, setLoadingAgendas] = useState(false);
    const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);
    const lastRunRef = useRef<number>(Number(data.triggerRunOnce) || 0);

    useEffect(() => {
        let mounted = true;

        const loadAgendas = async () => {
            setLoadingAgendas(true);
            try {
                const items = await calendarApi.listAgendas();
                if (mounted) setAgendas(items);
            } catch (error) {
                console.error('Erro ao carregar agendas para o gatilho', error);
            } finally {
                if (mounted) setLoadingAgendas(false);
            }
        };

        loadAgendas();

        return () => {
            mounted = false;
        };
    }, []);

    useEffect(() => {
        const runToken = Number(data.triggerRunOnce) || 0;
        if (!runToken || runToken === lastRunRef.current) return;

        lastRunRef.current = runToken;
        const startsAt = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
        const selectedAgendaId = agendaId ? Number(agendaId) : null;
        const sample = {
            event: eventType === 'appointment_scheduled' ? 'appointment_created' : eventType,
            anchor_at: startsAt,
            phone: '5500000000007',
            name: 'Cliente Exemplo',
            lead_id: 123,
            appointment_id: 456,
            appointment: {
                id: 456,
                lead_id: 123,
                agenda_id: selectedAgendaId,
                status: status || 'SCHEDULED',
                starts_at: startsAt,
                consulta_data: startsAt,
                name: 'Cliente Exemplo',
                phone: '5500000000007'
            }
        };

        setNodeExecutionData(id, sample, true, true);
    }, [agendaId, data.triggerRunOnce, eventType, id, setNodeExecutionData, status]);

    const updateData = (updates: Record<string, unknown>) => {
        Object.assign(data, updates);
        data.onDataChange?.(id, updates);
    };

    const handleEventTypeChange = (value: string) => {
        setEventType(value);
        updateData({ eventType: value, label: 'Agendamento' });
    };

    const handleStatusChange = (value: string) => {
        setStatus(value);
        updateData({ status: value, label: 'Agendamento' });
    };

    const handleAgendaChange = (value: string) => {
        setAgendaId(value);
        updateData({ agendaId: value, label: 'Agendamento' });
    };

    const handleContextMenu = (event: React.MouseEvent) => {
        event.preventDefault();
        event.stopPropagation();
        setMenuPosition({ x: event.clientX, y: event.clientY });
    };

    const handleDelete = async () => {
        const confirmed = await confirm({
            confirmText: 'Excluir gatilho',
            message: 'Este gatilho e suas conexões serão removidos do fluxo.',
            title: 'Excluir gatilho de agendamento?',
            variant: 'danger',
        });

        if (confirmed) {
            deleteElements({ nodes: [{ id }] });
        }
    };

    return (
        <div
            onContextMenu={handleContextMenu}
            className={`rounded-lg border-l-4 border-cyan-500 bg-white text-xs shadow-lg dark:bg-gray-800 ${selected ? 'ring-2 ring-cyan-300' : ''}`}
        >
            {menuPosition && (
                <NodeContextMenu
                    x={menuPosition.x}
                    y={menuPosition.y}
                    onClose={() => setMenuPosition(null)}
                    actions={[
                        { label: 'Excluir', icon: <Trash2 className="h-3 w-3" />, onClick: handleDelete, danger: true },
                    ]}
                />
            )}

            <div className="flex items-center gap-2 border-b border-gray-100 p-2 font-medium dark:border-gray-700">
                <CalendarClock size={13} className="text-cyan-500" />
                Agendamento
            </div>

            <div className="w-[240px] space-y-3 p-3">
                <div>
                    <label className="mb-1 block text-[10px] text-gray-500">Evento</label>
                    <select
                        className="nodrag w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700"
                        value={eventType}
                        onMouseDown={(event) => event.stopPropagation()}
                        onChange={(event) => handleEventTypeChange(event.target.value)}
                    >
                        {eventOptions.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                    </select>
                </div>

                <div>
                    <label className="mb-1 block text-[10px] text-gray-500">Status</label>
                    <select
                        className="nodrag w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700"
                        value={status}
                        onMouseDown={(event) => event.stopPropagation()}
                        onChange={(event) => handleStatusChange(event.target.value)}
                    >
                        {statusOptions.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                    </select>
                </div>

                <div>
                    <label className="mb-1 block text-[10px] text-gray-500">Agenda</label>
                    <select
                        className="nodrag w-full rounded border border-gray-200 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700"
                        value={agendaId}
                        onMouseDown={(event) => event.stopPropagation()}
                        onChange={(event) => handleAgendaChange(event.target.value)}
                    >
                        <option value="">{loadingAgendas ? 'Carregando agendas...' : 'Todas as agendas'}</option>
                        {agendas.map((agenda) => (
                            <option key={agenda.id} value={agenda.id}>
                                {agenda.name}
                            </option>
                        ))}
                    </select>
                </div>

                <div className={`rounded p-2 text-[10px] ${isDark ? 'bg-cyan-900/20 text-cyan-200' : 'bg-cyan-50 text-cyan-700'}`}>
                    Variáveis: {'{{trigger.appointment.starts_at}}'}, {'{{phone}}'}, {'{{name}}'}
                </div>
            </div>

            <Handle type="source" position={Position.Right} />
        </div>
    );
};

export default memo(AppointmentTriggerNode);
