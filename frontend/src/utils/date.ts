// src/utils/date.ts

export function formatChatTimestamp(timestampMillis: number): string {
    if (!timestampMillis) return '';

    const date = new Date(timestampMillis);
    const now = new Date();

    const dateOnly = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const nowOnly = new Date(now.getFullYear(), now.getMonth(), now.getDate());

    const dayMs = 24 * 60 * 60 * 1000;
    const diffDays = Math.floor((nowOnly.getTime() - dateOnly.getTime()) / dayMs);

    if (diffDays === 0) {
      // Hoje -> exibir HH:mm
      return date.toLocaleTimeString('pt-BR', {
        hour: '2-digit',
        minute: '2-digit',
      });
    } else if (diffDays === 1) {
      // Ontem
      return 'Ontem';
    } else if (diffDays < 7) {
      // Últimos 7 dias -> dia da semana (Dom, Seg, Ter...)
      const daysOfWeek = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
      return daysOfWeek[date.getDay()];
    } else {
      // Mais antigo -> DD/MM/YYYY
      return date.toLocaleDateString('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      });
    }
  }