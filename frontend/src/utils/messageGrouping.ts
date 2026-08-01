// utils/messageGrouping.ts - Versão final
import { OptimizedMessage } from '../services/api.ts';

export interface MessageGroup {
  dayLabel: string;
  messages: OptimizedMessage[];
}

export const groupMessagesByDay = (messages: OptimizedMessage[]): MessageGroup[] => {
  // Garantir que estejam ordenadas pela timestampNumber
  const sorted = [...messages].sort((a, b) => {
    const aTime = a.timestampNumber || 0;
    const bTime = b.timestampNumber || 0;
    return aTime - bTime; // do mais antigo pro mais recente
  });

  if (sorted.length === 0) {
    return [];
  }

  // Função para criar uma "chave" do tipo YYYY-MM-DD
  const getDayKey = (time: number) => {
    const d = new Date(time);
    // Retorna "ano-mês-dia"
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
      d.getDate()
    ).padStart(2, '0')}`;
  };

  // Função para formatar a label do dia (Hoje, Ontem ou DD/MM/AAAA)
  const getDayLabel = (time: number) => {
    const now = new Date();
    const d = new Date(time);

    const isSameDay = (a: Date, b: Date) =>
      a.getDate() === b.getDate() &&
      a.getMonth() === b.getMonth() &&
      a.getFullYear() === b.getFullYear();

    // Hoje
    if (isSameDay(now, d)) return 'Hoje';

    // Ontem
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    if (isSameDay(yesterday, d)) return 'Ontem';

    // Caso contrário, exibe a data no formato "DD/MM/YYYY"
    return d.toLocaleDateString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  };

  // Objeto intermediário para agrupar
  const groups: Record<string, OptimizedMessage[]> = {};

  for (const m of sorted) {
    const ts = m.timestampNumber || 0;
    const dayKey = getDayKey(ts);
    if (!groups[dayKey]) {
      groups[dayKey] = [];
    }
    groups[dayKey].push(m);
  }

  // Converte em um array de { dayLabel, messages } ordenado por data
  return Object.entries(groups)
    .map(([dayKey, groupMsgs]) => {
      // Usar o primeiro msg do grupo para gerar label
      const anyMsg = groupMsgs[0];
      const label = getDayLabel(anyMsg.timestampNumber || 0);

      return {
        dayLabel: label,
        messages: groupMsgs,
        // Adicionar este campo para ordenar os grupos
        _keyForSorting: dayKey
      };
    })
    .sort((a, b) => a._keyForSorting.localeCompare(b._keyForSorting))
    .map(({ dayLabel, messages }) => ({ dayLabel, messages }));
};