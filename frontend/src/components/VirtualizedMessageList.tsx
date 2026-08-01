// Modificação para o componente VirtualizedMessageList.tsx para incluir esqueleto de carregamento interno
// Isto é útil para quando já temos o componente renderizado mas ainda estamos carregando mensagens adicionais

import React, { useRef, useEffect } from 'react';
import { OptimizedMessage } from '../services/api.ts';
import { OptimizedMessageContent } from './OptimizedMessageContent.tsx';
import { DateSeparator } from './DateSeparator.tsx';
import { groupMessagesByDay, MessageGroup } from '../utils/messageGrouping.ts';
import { useTheme } from '../contexts/ThemeContext.tsx';
import { AgentiveEmptyState } from './AgentiveUI.tsx';
import { MessageSquare } from 'lucide-react';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

interface VirtualizedMessageListProps {
  messages: OptimizedMessage[];
  isLoading: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  onReply?: (message: OptimizedMessage) => void;
  onReact?: (message: OptimizedMessage, reaction: string) => void;
}

export const VirtualizedMessageList: React.FC<VirtualizedMessageListProps> = ({
  messages,
  isLoading,
  hasMore,
  onLoadMore,
  onReply,
  onReact
}) => {
  const { isDark } = useTheme();
  const containerRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const loadingRef = useRef<HTMLDivElement>(null);
  const endOfMessagesRef = useRef<HTMLDivElement>(null);
  const prevMessagesLengthRef = useRef<number>(0);

  // Configurar o intersection observer para carregar mais mensagens
  useEffect(() => {
    if (isLoading) return;

    const options = {
      root: containerRef.current,
      rootMargin: '0px',
      threshold: 0.1
    };

    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && hasMore) {
        onLoadMore();
      }
    }, options);

    if (loadingRef.current) {
      observer.observe(loadingRef.current);
    }

    observerRef.current = observer;

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [hasMore, isLoading, onLoadMore]);

  // Controlar posição de scroll e comportamento de rolagem automática
  useEffect(() => {
    // Se as mensagens foram redefinidas (mudança de contato), resetar referência
    if (messages.length === 0) {
      prevMessagesLengthRef.current = 0;
      return;
    }

    // Carregamento inicial (primeiro conjunto de mensagens)
    const isInitialLoad = prevMessagesLengthRef.current === 0 && messages.length > 0;

    // Verificar se mensagens foram adicionadas ao final (novas mensagens)
    // ou ao início (histórico antigo)
    const messagesAdded = messages.length - prevMessagesLengthRef.current;

    if (!isLoading && endOfMessagesRef.current) {
      if (isInitialLoad) {
        // No carregamento inicial, sempre rolamos para o final
        endOfMessagesRef.current.scrollIntoView({ behavior: 'auto', block: 'end' });
      } else if (messagesAdded > 0 && prevMessagesLengthRef.current > 0) {
        // Verificar se mensagens foram adicionadas no final (novas)
        // Essa lógica presume que as mensagens são ordenadas por data
        const lastPrevTimestamp = messages[prevMessagesLengthRef.current - 1]?.timestampNumber || 0;
        const areNewMessages = messages[messages.length - 1]?.timestampNumber > lastPrevTimestamp;

        // Só rolar automaticamente para o final se forem novas mensagens
        // e não se estiver carregando histórico antigo
        if (areNewMessages && !hasMore) {
          endOfMessagesRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
      }
    }

    // Atualizar o contador de mensagens
    prevMessagesLengthRef.current = messages.length;
  }, [messages.length, isLoading, hasMore, messages]);

  // Agrupar mensagens por dia
  const groupedMessages = groupMessagesByDay(messages);

  // Componente de esqueleto de carregamento para mensagens adicionais
  const MessageLoadingSkeleton = () => (
    <div className="space-y-6 py-4 opacity-75">
      {/* Esqueleto de mensagem recebida */}
      <div className="flex items-start animate-pulse">
        <div className={cx('mr-2 h-8 w-8 rounded-xl', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
        <div className="max-w-[70%]">
          <div className={cx('h-12 w-36 rounded-2xl p-3', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
        </div>
      </div>

      {/* Esqueleto de mensagem enviada */}
      <div className="flex items-start justify-end animate-pulse">
        <div className="max-w-[70%]">
          <div className={cx('h-14 w-48 rounded-2xl p-3', isDark ? 'bg-white/15' : 'bg-brand/20')}></div>
        </div>
        <div className={cx('ml-2 h-8 w-8 rounded-xl', isDark ? 'bg-white/10' : 'bg-brand/10')}></div>
      </div>
    </div>
  );

  return (
    <div
      ref={containerRef}
      className={cx('min-h-0 flex-1 overflow-y-auto p-4', isDark ? 'bg-brand/60' : 'bg-brand-canvas')}
    >
      {/* Indicador de carregamento no topo (para carregar mensagens mais antigas) */}
      {hasMore && (
        <div
          ref={loadingRef}
          className="flex justify-center py-2"
        >
          {isLoading ? (
            <MessageLoadingSkeleton />
          ) : (
            <div className="h-4" />
          )}
        </div>
      )}

      {messages.length === 0 && isLoading ? (
        <div className="h-full flex flex-col justify-center">
          <MessageLoadingSkeleton />
          <MessageLoadingSkeleton />
        </div>
      ) : messages.length === 0 && !isLoading ? (
        <AgentiveEmptyState
          icon={MessageSquare}
          title="Nenhuma mensagem"
          description="Envie uma mensagem para iniciar este atendimento."
        />
      ) : (
        // Mensagens agrupadas por data
        groupedMessages.map((group) => (
          <div key={group.dayLabel} className="mb-6">
            <DateSeparator date={group.dayLabel} />

            <div className="space-y-3 mt-3">
              {group.messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex ${message.fromMe ? 'justify-end' : 'justify-start'}`}
                >
                  <OptimizedMessageContent
                    message={message}
                    isOwn={message.fromMe}
                    onReply={onReply}
                    onReact={onReact}
                  />
                </div>
              ))}
            </div>
          </div>
        ))
      )}

      {/* Referência para o final das mensagens (para auto-scroll) */}
      <div ref={endOfMessagesRef} className="h-4" />
    </div>
  );
}
