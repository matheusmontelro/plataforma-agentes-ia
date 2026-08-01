import { useState, useEffect, useCallback, useRef } from 'react';
import {
  OptimizedMessage,
  getPagedMessages,
  messageCacheManager,
  unifiedWebSocketManager,
  API_URL
} from '../services/api';

interface UseOptimizedMessagesOptions {
  pageSize?: number;
  initialLoadDelay?: number;
  onUpdateContact?: (phone: string, type: string, content: any) => void;
}

export const useOptimizedMessages = (
  contactPhone: string | null,
  options: UseOptimizedMessagesOptions = {}
) => {
  const {
    pageSize = 30,
    initialLoadDelay = 0,
    onUpdateContact
  } = options;

  const [messages, setMessages] = useState<OptimizedMessage[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [hasMore, setHasMore] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const messagesRef = useRef<OptimizedMessage[]>([]);

  // Ref para rastrear IDs locais já processados
  const processedLocalIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  /**
   * Ajuste principal:
   * Se for 'video', deixamos `url: ''` (sem placeholder).
   * Para imagem/áudio, ainda podemos usar placeholders se quiser.
   */
  const processMediaContent = (content: any, mediaType: string): any => {
    console.log(`[processMediaContent] Processando mídia tipo: ${mediaType}`);
    console.log(`[processMediaContent] Tipo do conteúdo:`, typeof content);

    if (typeof content === 'object' && content.url) {
      console.log(`[processMediaContent] Conteúdo já é objeto com URL`);
      if (typeof content.url === 'string' && content.url.includes('/api/files/') && !content.url.includes('/api/waha/')) {
        const currentApiUrl = API_URL || window.location.origin;
        const match = content.url.match(/\/api\/files\/(.+)$/);
        if (match) {
          return {
            ...content,
            url: `${currentApiUrl}/api/waha/media/${match[1]}`,
          };
        }
      }
      return content;
    }

    // Se for string
    if (typeof content === 'string') {
      if (content.startsWith('/api/waha/media/')) {
        console.log(`[processMediaContent] Conteúdo é proxy WAHA same-origin`);
        return { url: content };
      }

      // Se já for URL ou data:
      if (content.startsWith('http') || content.startsWith('blob:') || content.startsWith('data:')) {
        console.log(`[processMediaContent] Conteúdo é URL/blob/data`);

        // Converter URLs WAHA de qualquer host para o proxy same-origin.
        if (content.includes('/api/files/') && !content.includes('/api/waha/')) {
          const currentApiUrl = API_URL || window.location.origin;
          const match = content.match(/\/api\/files\/(.+)$/);
          if (match) {
            const wahaPath = match[1];
            const convertedUrl = `${currentApiUrl}/api/waha/media/${wahaPath}`;
            console.log('🔥 [WAHA Fix] Convertendo para proxy:', convertedUrl);
            return { url: convertedUrl };
          }

          console.warn('[processMediaContent] Não foi possível converter URL WAHA, usando original');
        }

        return { url: content };
      }

      // Se for image/video/audio local, geramos { mediaPath, needsLoading, url="" ou placeholder... }
      if (mediaType === 'image' || mediaType === 'video' || mediaType === 'audio') {
        // Atribui 'mediaPath' e 'needsLoading'
        const mediaPath = content;
        return {
          mediaPath,
          needsLoading: true,
          // Diferença: para vídeo, não colocamos placeholder.
          url: mediaType === 'image'
            ? '/assets/image-placeholder.png'
            : mediaType === 'audio'
              ? '/assets/audio-placeholder.png'
              : ''
        };
      }

      // Se não for image/video/audio, retorna como texto
      return content;
    }

    // Caso padrão
    return content;
  };

  // Processa array de mensagens para converter mídias em URLs (objeto {mediaPath, ...})
  const processMessagesMedia = (msgs: OptimizedMessage[]): OptimizedMessage[] => {
    return msgs.map(msg => {
      if (msg.type === 'image' || msg.type === 'video' || msg.type === 'audio') {
        return {
          ...msg,
          content: processMediaContent(msg.content, msg.type)
        };
      }
      return msg;
    });
  };

  useEffect(() => {
    if (!contactPhone) {
      setMessages([]);
      setHasMore(false);
      return;
    }

    let mounted = true;

    const loadInitialMessages = async () => {
      console.log(`[loadInitialMessages] Carregando mensagens para ${contactPhone}`);
      setIsLoading(true);
      setError(null);

      try {
        // Tenta cache primeiro
        console.log(`[loadInitialMessages] Verificando cache...`);
        const cachedMessages = messageCacheManager.getMessages(contactPhone);
        if (cachedMessages && cachedMessages.length > 0) {
          console.log(`[loadInitialMessages] ${cachedMessages.length} mensagens encontradas no cache`);
          // Filtrar mensagens inválidas do cache
          const validCachedMessages = cachedMessages.filter(m => {
            if ((m.type as string) === 'unknown' || (!m.content && m.type !== 'image' && m.type !== 'video' && m.type !== 'audio' && m.type !== 'nps' && (m.type as string) !== 'contact')) {
              return false;
            }
            return true;
          });
          const processedCached = processMessagesMedia(validCachedMessages);
          console.log(`[loadInitialMessages] Mensagens processadas do cache, definindo estado...`);
          setMessages(processedCached);
          setIsLoading(false);
        } else {
          console.log(`[loadInitialMessages] Nenhuma mensagem no cache`);
        }

        // Sempre tenta API
        try {
          console.log(`[loadInitialMessages] Buscando mensagens da API...`);
          const resp = await getPagedMessages(contactPhone, pageSize);
          console.log(`[loadInitialMessages] Resposta da API:`, resp.messages?.length || 0, 'mensagens');

          // Debug: verificar mensagens de mídia da API
          if (resp.messages) {
            const apiMediaMessages = resp.messages.filter((m: any) =>
              m.type === 'audio' || m.type === 'image' || m.type === 'video'
            );
            console.log(`[loadInitialMessages] Mensagens de mídia da API: ${apiMediaMessages.length}`);
            apiMediaMessages.forEach((m: any) => {
              console.log(`[loadInitialMessages] Mídia da API - tipo: ${m.type}, id: ${m.id}, content:`,
                typeof m.content === 'string' ? m.content.substring(0, 100) : m.content);
            });
          }

          if (mounted && resp.messages && resp.messages.length > 0) {
            const processedApi = processMessagesMedia(resp.messages);
            console.log(`[loadInitialMessages] Mensagens processadas da API, salvando no estado e cache...`);

            // Debug: verificar após processamento
            const processedMediaMessages = processedApi.filter((m: any) =>
              m.type === 'audio' || m.type === 'image' || m.type === 'video'
            );
            console.log(`[loadInitialMessages] Mensagens de mídia após processamento: ${processedMediaMessages.length}`);
            processedMediaMessages.forEach((m: any) => {
              console.log(`[loadInitialMessages] Mídia processada - tipo: ${m.type}, content type:`, typeof m.content,
                m.content?.url ? `URL length: ${m.content.url.length}` : 'sem URL');
            });

            setMessages(processedApi);
            setHasMore(resp.pagination.hasMore);
            messageCacheManager.saveMessages(contactPhone, processedApi);
          }
        } catch (apiError) {
          console.warn('[loadInitialMessages] Falha ao obter mensagens da API:', apiError);
          if ((!cachedMessages || cachedMessages.length === 0)) {
            setError(apiError instanceof Error ? apiError : new Error(String(apiError)));
          }
        }
      } catch (err) {
        if (mounted) {
          console.error('Erro ao carregar mensagens:', err);
          setError(err instanceof Error ? err : new Error(String(err)));
          setMessages([]);
          setHasMore(false);
        }
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    };

    const handleNewMessage = (message: any) => {
      // DEBUG: Log imediatamente no início da função
      const now = Date.now();
      console.log('🔍 [DEBUG] handleNewMessage chamado:', {
        messageId: message.id,
        messageType: message.type,
        fromMe: message.fromMe,
        timestamp: message.timestamp,
        contentLength: typeof message.content === 'string' ? message.content.length : 'object',
        currentMessagesCount: messagesRef.current.length,
        debugTime: now,
        debugTimestamp: new Date().toISOString()
      });

      console.log('📨 [useOptimizedMessages] Nova mensagem recebida:', {
        phone: message.phone,
        contactPhone: contactPhone,
        fromMe: message.fromMe,
        fromApi: message.fromApi,
        type: message.type,
        content: message.content?.substring?.(0, 30)
      });

      // Log apenas para debug
      if (message.phone === contactPhone) {
        console.log(`📨 useOptimizedMessages: Recebeu ${message.type} para contato correto`);
      }

      if (message.type === 'contact_mode_changed' ||
        message.content === '[CONTACT_MODE_CHANGED]' ||
        (typeof message.content === 'string' &&
          message.content.includes('CONTACT_MODE_CHANGED'))) {
        console.log('Mensagem de modo ignorada:', message);
        return;
      }

      if (message.type === 'message_status_update') {
        const candidateIds = [
          message.dbMessageId,
          message.messageId,
          message.providerMessageId,
          message.localMessageId
        ].filter(Boolean).map(String);

        if (mounted && message.phone === contactPhone && candidateIds.length > 0) {
          setMessages(prev => {
            const updated = prev.map(msg => {
              const msgIds = [msg.id, msg.providerMessageId].filter(Boolean).map(String);
              const matches = msgIds.some(id => candidateIds.includes(id));
              if (!matches) return msg;

              return {
                ...msg,
                id: message.dbMessageId ? String(message.dbMessageId) : msg.id,
                providerMessageId: message.providerMessageId || message.messageId || msg.providerMessageId,
                deliveryAck: message.ack ?? msg.deliveryAck,
                status: message.status || msg.status,
              };
            });
            messageCacheManager.saveMessages(contactPhone, updated);
            return updated;
          });
        }
        return;
      }

      if (message.type === 'message_reaction_update') {
        const candidateIds = [
          message.dbMessageId,
          message.messageId,
          message.providerMessageId
        ].filter(Boolean).map(String);

        if (mounted && message.phone === contactPhone && candidateIds.length > 0) {
          setMessages(prev => {
            const updated = prev.map(msg => {
              const msgIds = [msg.id, msg.providerMessageId].filter(Boolean).map(String);
              const matches = msgIds.some(id => candidateIds.includes(id));
              return matches ? { ...msg, reactions: Array.isArray(message.reactions) ? message.reactions : [] } : msg;
            });
            messageCacheManager.saveMessages(contactPhone, updated);
            return updated;
          });
        }
        return;
      }

      // NOVO: Ignorar mensagens próprias recentes (mas não mensagens do celular)
      if (message.fromMe === true && message.fromApi !== false) {
        // Verificar se foi uma mensagem enviada recentemente (últimos 5 segundos)
        const recentMessages = messagesRef.current.filter(m =>
          m.fromMe &&
          m.timestampNumber &&
          (Date.now() - m.timestampNumber) < 5000
        );

        // Verificar se já existe uma mensagem similar recente
        const isDuplicateRecent = recentMessages.some(m => {
          if (message.type !== m.type) return false;

          // Para texto, comparar conteúdo
          if (message.type === 'text' && m.type === 'text') {
            return m.content === message.content;
          }

          // Para mídia, comparar mais especificamente para evitar falsos positivos
          if (message.type === 'video' && m.type === 'video') {
            // Para vídeo, comparar se ambos têm conteúdo de mídia similar
            const msgContent = typeof message.content === 'object' ? message.content?.url || '' : '';
            const mContent = typeof m.content === 'object' ? m.content?.url || '' : '';

            // Se ambos começam com data:video/, considerar duplicada
            if (msgContent.startsWith('data:video/') && mContent.startsWith('data:video/')) {
              // Comparar primeiros 50 caracteres para verificar se é o mesmo vídeo
              return msgContent.substring(0, 50) === mContent.substring(0, 50);
            }
          }

          // Para imagem, comparar de forma similar
          if (message.type === 'image' && m.type === 'image') {
            const msgContent = typeof message.content === 'object' ? message.content?.url || '' : '';
            const mContent = typeof m.content === 'object' ? m.content?.url || '' : '';

            if (msgContent.startsWith('data:image/') && mContent.startsWith('data:image/')) {
              return msgContent.substring(0, 50) === mContent.substring(0, 50);
            }
          }

          // Para áudio, comparar de forma similar
          if (message.type === 'audio' && m.type === 'audio') {
            const msgContent = typeof message.content === 'object' ? message.content?.url || '' : '';
            const mContent = typeof m.content === 'object' ? m.content?.url || '' : '';

            if (msgContent.startsWith('data:audio/') && mContent.startsWith('data:audio/')) {
              return msgContent.substring(0, 50) === mContent.substring(0, 50);
            }
          }

          return false;
        });

        if (isDuplicateRecent) {
          console.log('🚫 [useOptimizedMessages] Ignorando mensagem própria duplicada recente:', message.type, message.content);
          return;
        }
      }

      // 🔥 CORREÇÃO MELHORADA: Evitar renderização duplicada de mídias (vídeo, imagem, áudio)
      if (message.type === 'video' || message.type === 'image' || message.type === 'audio') {
        // Identificar mídias duplicadas pelo conteúdo, timestamp ou padrão de ID local
        const existingMediaIndex = messagesRef.current.findIndex(m => {
          // Verificar se IDs existem antes de comparar
          const mId = m.id || '';
          const msgId = message.id || '';

          return m.type === message.type &&
            mId !== msgId &&
            (
              // 1. Se ambos têm conteúdo exatamente igual (URLs/base64)
              (JSON.stringify(m.content) === JSON.stringify(message.content)) ||
              // 2. Se um tem ID local e o outro é real e foram criados muito próximos (até 30s)
              (
                mId && msgId && (
                  (mId.startsWith('local_') && !msgId.startsWith('local_')) ||
                  (!mId.startsWith('local_') && msgId.startsWith('local_'))
                ) &&
                Math.abs((m.timestampNumber || 0) - (message.timestamp || Date.now())) < 30000
              ) ||
              // 3. Se ambos são IDs locais e foram criados no mesmo segundo
              (
                mId && msgId && mId.startsWith('local_') && msgId.startsWith('local_') &&
                Math.abs((m.timestampNumber || 0) - (message.timestamp || Date.now())) < 1000
              ) ||
              // 4. Comparação de conteúdo base64 para mídias com mesmo tipo
              (
                typeof m.content === 'object' && typeof message.content === 'object' &&
                m.content?.url && message.content?.url &&
                (
                  (m.content.url.startsWith('data:') && message.content.url.startsWith('data:') &&
                    m.content.url.substring(0, 100) === message.content.url.substring(0, 100)) ||
                  (m.content.url === message.content.url)
                )
              )
            );
        });

        if (existingMediaIndex !== -1) {
          const existingMessage = messagesRef.current[existingMediaIndex];
          const mId = existingMessage.id || '';
          const msgId = message.id || '';
          console.log(`🚫 [useOptimizedMessages] Ignorando ${message.type} duplicado:`, {
            messageId: msgId,
            existingMessageId: mId,
            timeDiff: Date.now() - (existingMessage.timestampNumber || 0),
            isLocalMessage: msgId ? msgId.startsWith('local_') : false,
            existingIsLocal: mId ? mId.startsWith('local_') : false
          });
          return;
        }
      }

      // Tratar atualizações NPS específicas
      if (message.type === 'nps_update') {
        console.log('🎯 [useOptimizedMessages] Recebeu nps_update:', {
          messagePhone: message.phone,
          contactPhone,
          pollMessageId: message.poll_message_id,
          score: message.score
        });

        if (mounted && message.phone === contactPhone) {
          setMessages(prev => {
            return prev.map(msg => {
              // Encontrar a mensagem NPS pelo poll_message_id
              if (msg.type === 'nps') {
                let parsedContent: any;
                let npsData: any;

                // Parse do conteúdo (pode ser string JSON ou objeto)
                try {
                  if (typeof msg.content === 'string') {
                    parsedContent = JSON.parse(msg.content);
                  } else if (typeof msg.content === 'object') {
                    parsedContent = msg.content;
                  } else {
                    return msg; // Conteúdo inválido
                  }

                  npsData = parsedContent.nps_data;
                  if (!npsData || !npsData.message_id) {
                    return msg; // Não tem estrutura NPS válida
                  }

                } catch (e) {
                  console.log('⚠️ [useOptimizedMessages] Erro ao fazer parse do conteúdo NPS:', e);
                  return msg;
                }

                // Verificar se é a mensagem NPS que estamos procurando
                if (npsData.message_id === message.poll_message_id) {
                  const updatedNpsData = {
                    ...npsData,
                    status: 'answered' as const,
                    score: message.score,
                    answered_at: message.answered_at
                  };

                  const updatedContent = {
                    ...parsedContent,
                    nps_data: updatedNpsData
                  };

                  console.log('🎯 [useOptimizedMessages] Atualizando mensagem NPS:', {
                    messageId: msg.id,
                    oldStatus: npsData.status,
                    newScore: message.score
                  });

                  return {
                    ...msg,
                    content: typeof msg.content === 'string'
                      ? JSON.stringify(updatedContent)
                      : updatedContent
                  };
                }
              }
              return msg;
            });
          });
        }
        return; // Não processar como mensagem normal
      }

      // Atualiza só se o phone bater
      if (mounted && message.phone === contactPhone) {
        setMessages(prev => {
          const msgId = message.messageId || message.id || `${message.phone}_${Date.now()}`;
          const msgTimestamp = message.timestamp || Date.now();

          // Debug dos dados para comparação
          // console.log(`[MergeDebug] Buscando match para: ID=${msgId}, Type=${message.type}`);

          // Passo 1: Verificar se já existe EXATAMENTE essa mensagem (Duplicata Real)
          const existingRealIndex = prev.findIndex(m => m.id === msgId);
          if (existingRealIndex !== -1) {
            console.log(`🚫 [useOptimizedMessages] Mensagem já existe (ID exato): ${msgId}`);
            return prev;
          }

          // Passo 2: Verificar se existe uma mensagem LOCAL que corresponde a esta (para substituição)
          // Critérios:
          // - ID local (começa com 'local_')
          // - Mesmo tipo
          // - Proximidade de tempo (30s)
          // - Se for texto/nps, conteúdo igual. Se mídia, aceita substituição por confirmação.

          let matchIndex = -1;

          // Priorizar busca por ID local passado explicitamente (se o backend retornasse... mas geralmente não retorna)
          // Então buscamos por heurística

          matchIndex = prev.findIndex(m => {
            if (!m.id.startsWith('local_')) return false; // Só substitui locais
            if (m.type !== message.type) return false;    // Mesmo tipo

            const timeDiff = Math.abs((m.timestampNumber || 0) - msgTimestamp);
            if (timeDiff > 30000) return false;           // Máximo 30s de diferença

            // Para texto, conteúdo deve bater
            if (m.type === 'text') {
              return m.content === message.content;
            }

            // Para mídias (video, image, audio), assumimos que é a confirmação do envio local
            // Não comparamos conteúdo estrito pois local é base64 e remoto é URL
            return true;
          });

          // Preparar novo objeto de mensagem
          let processedContent;
          if (message.type === 'image' || message.type === 'video' || message.type === 'audio') {
            processedContent = processMediaContent(message.content, message.type);
          } else if (message.type === 'nps') {
            processedContent = {
              nps_data: {
                question: message.content || 'Em uma escala de 1 a 5, como você avalia nosso atendimento?',
                status: 'sent',
                message_id: msgId
              }
            };
          } else if (message.type === 'contact') {
            processedContent = message.contact || message.content;
          } else {
            processedContent = message.content;
          }

          const newMessage: OptimizedMessage = {
            id: msgId,
            type: message.type,
            content: processedContent,
            sender: {
              phone: message.phone,
              name: message.senderName || 'Desconhecido',
              photo: message.photo || ''
            },
            timestamp: new Date(msgTimestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            timestampNumber: msgTimestamp,
            fromMe: message.fromMe,
            status: message.status || (message.fromMe ? 'sent' : 'delivered'),
            providerMessageId: message.providerMessageId || message.messageId,
            deliveryAck: message.deliveryAck,
            replyTo: message.replyTo || null,
            reactions: Array.isArray(message.reactions) ? message.reactions : []
          };

          if (matchIndex !== -1) {
            // 🔄 MERGE: Substituir mensagem local pela confirmada
            console.log(`✅ [useOptimizedMessages] Mesclando mensagem local (${prev[matchIndex].id}) com confirmada (${msgId})`);
            const updated = [...prev];
            updated[matchIndex] = newMessage; // Substitui mantendo a posição
            messageCacheManager.saveMessages(contactPhone, updated);
            return updated;
          }

          // Se não encontrou match, apenas adiciona
          // Verificação extra de duplicata por conteúdo para evitar duplicação visual se ID for diferente mas conteúdo for igual (ex: duplo envio evento)
          const isVisualDuplicate = prev.some(m =>
            !m.id.startsWith('local_') && // Ignora locais (já checados acima)
            m.type === message.type &&
            JSON.stringify(m.content) === JSON.stringify(newMessage.content) &&
            Math.abs((m.timestampNumber || 0) - newMessage.timestampNumber) < 5000
          );

          if (isVisualDuplicate) {
            console.log(`🚫 [useOptimizedMessages] Duplicata visual detectada (conteúdo idêntico): ${msgId}`);
            return prev;
          }

          console.log(`📥 [useOptimizedMessages] Adicionando nova mensagem: ${msgId}`);
          const updated = [...prev, newMessage].sort((a, b) =>
            (a.timestampNumber || 0) - (b.timestampNumber || 0)
          );
          messageCacheManager.saveMessages(contactPhone, updated);
          return updated;
        });
      }
    };

    // Inscrever no tópico do telefone específico
    console.log('🔔 [useOptimizedMessages] Inscrevendo no tópico:', contactPhone);
    unifiedWebSocketManager.subscribe(contactPhone);

    // Registrar handler para mensagens deste telefone
    console.log('🎯 [useOptimizedMessages] Registrando handler para:', contactPhone);
    const unsubscribe = unifiedWebSocketManager.onMessage(contactPhone, handleNewMessage);

    // Log de inscrição
    console.log(`🔔 useOptimizedMessages inscrito no tópico: ${contactPhone}`);

    loadInitialMessages();

    return () => {
      mounted = false;
      unsubscribe();
      // Desinscrever do tópico quando o componente desmontar
      unifiedWebSocketManager.unsubscribe(contactPhone);
    };
  }, [contactPhone, pageSize, initialLoadDelay]);

  const loadMoreMessages = useCallback(async () => {
    if (!contactPhone || !hasMore || isLoading) return;

    setIsLoading(true);
    try {
      const oldest = messages.length > 0 ? messages[0] : null;
      let resp: Awaited<ReturnType<typeof getPagedMessages>>;
      if (oldest) {
        resp = await getPagedMessages(contactPhone, pageSize, oldest.id, undefined);
      } else {
        resp = await getPagedMessages(contactPhone, pageSize);
      }

      if (resp.messages.length > 0) {
        const processed = processMessagesMedia(resp.messages);
        setMessages(prev => {
          const combined = [...processed, ...prev];
          const unique = combined.filter(
            (m, idx, self) => idx === self.findIndex(x => x.id === m.id)
          );
          unique.sort((a, b) => (a.timestampNumber || 0) - (b.timestampNumber || 0));
          messageCacheManager.saveMessages(contactPhone, unique);
          return unique;
        });
      }

      setHasMore(resp.pagination.hasMore);
    } catch (err) {
      console.error('Erro ao carregar mais msgs:', err);
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setIsLoading(false);
    }
  }, [contactPhone, messages, hasMore, isLoading, pageSize]);

  const sendMessage = useCallback((
    content: any,
    type: 'text' | 'image' | 'audio' | 'video' | 'nps' = 'text',
    localMessageId?: string,
    metadata: Partial<OptimizedMessage> = {}
  ) => {
    console.log(`[useOptimizedMessages] sendMessage chamado - tipo: ${type}, phone: ${contactPhone}`);
    console.log(`[useOptimizedMessages] Conteúdo recebido:`, typeof content === 'object' ?
      { ...content, url: content.url ? content.url.substring(0, 100) + '...' : undefined } : content);

    if (!contactPhone) {
      console.warn('[useOptimizedMessages] sendMessage: contactPhone é null, abortando');
      return;
    }

    const processedContent = (type === 'image' || type === 'video' || type === 'audio')
      ? processMediaContent(content, type)
      : content;

    console.log(`[useOptimizedMessages] Conteúdo processado:`, typeof processedContent === 'object' ?
      { ...processedContent, url: processedContent.url ? processedContent.url.substring(0, 100) + '...' : undefined } : processedContent);

    // Gerar ID único se não foi fornecido
    const messageId = localMessageId || `local_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;
    console.log(`[useOptimizedMessages] ID da mensagem: ${messageId}`);

    // Adicionar ID ao conjunto de processados
    processedLocalIds.current.add(messageId);

    // Limpar ID após 5 minutos para evitar vazamento de memória
    setTimeout(() => {
      processedLocalIds.current.delete(messageId);
    }, 5 * 60 * 1000);

    const newMsg: OptimizedMessage = {
      id: messageId,
      type,
      content: processedContent,
      sender: {
        phone: 'me',
        name: 'Você',
        photo: ''
      },
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      timestampNumber: Date.now(),
      fromMe: true,
      status: 'sending',
      replyTo: metadata.replyTo || null,
      reactions: metadata.reactions || [],
      localMessageId: messageId // Adicionar campo para rastreamento
    } as OptimizedMessage & { localMessageId?: string };

    console.log(`[useOptimizedMessages] Adicionando nova mensagem ao estado...`);
    setMessages(prev => {
      console.log(`[useOptimizedMessages] Mensagens anteriores: ${prev.length}`);
      const updated = [...prev, newMsg].sort((a, b) => (a.timestampNumber || 0) - (b.timestampNumber || 0));
      console.log(`[useOptimizedMessages] Mensagens atualizadas: ${updated.length}`);
      console.log(`[useOptimizedMessages] Salvando no cache para ${contactPhone}...`);
      messageCacheManager.saveMessages(contactPhone, updated);
      return updated;
    });

    return { ...newMsg, localMessageId: messageId };
  }, [contactPhone]);

  return {
    messages,
    isLoading,
    hasMore,
    error,
    loadMoreMessages,
    sendMessage
  };
};
