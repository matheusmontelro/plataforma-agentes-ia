import React from 'react';
import { getMessageMedia, API_URL } from '../services/api.ts';
import type { ContactMessageData, OptimizedMessage, NPSMessageData } from '../services/api.ts';
import AudioWaveform from './AudioWaveform.tsx';
import VideoPlayer from './VideoPlayer.tsx';
import OptimizedImageContent from './OptimizedImageContent.tsx';
import { NPSMessage } from './NPSMessage.tsx';
import { useTheme } from '../contexts/ThemeContext.tsx';
import { Check, CheckCheck, Clock, Phone, Reply, UserRound, XCircle } from 'lucide-react';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

/**
 * 🔥 CORREÇÃO: Converter URLs WAHA do banco para proxy do backend
 * URLs salvas como: http://localhost:3000/api/files/sessao-exemplo/arquivo.jpeg
 * Convertidas para: {API_URL}/api/waha/media/sessao-exemplo/arquivo.jpeg
 */
function convertWahaUrl(url: string): string {
  if (!url) return url;

  console.log(`🔍 [convertWahaUrl] URL recebida: ${url}`);

  // Padrão 1: http://localhost:3000/api/files/...
  if (url.includes('localhost:3000/api/files/')) {
    const match = url.match(/localhost:3000\/api\/files\/(.+)$/);
    if (match) {
      const wahaPath = match[1];
      const convertedUrl = `${API_URL}/api/waha/media/${wahaPath}`;
      console.log(`✅ [convertWahaUrl] Convertendo (localhost): ${url.substring(0, 60)}... -> ${convertedUrl}`);
      return convertedUrl;
    }
  }

  // Padrão 2: Qualquer URL com /api/files/... (qualquer host)
  if (url.includes('/api/files/') && !url.includes('/api/waha/')) {
    const match = url.match(/\/api\/files\/(.+)$/);
    if (match) {
      const wahaPath = match[1];
      const convertedUrl = `${API_URL}/api/waha/media/${wahaPath}`;
      console.log(`✅ [convertWahaUrl] Convertendo (genérico): ${url.substring(0, 60)}... -> ${convertedUrl}`);
      return convertedUrl;
    }
  }

  console.log(`⚠️ [convertWahaUrl] URL não convertida: ${url}`);
  return url;
}

/**
 * Função auxiliar para normalizar caminhos de mídia.
 * Se path for 'data:' ou 'http', marcamos como isBase64OrHttp = true e retornamos inalterado.
 * Caso seja 'client_6/company_4/video/...' -> vira '6/4/video/...'
 * Senão, retorna o path como está.
 */
function normalizeMediaPath(
  path: string,
  mediaType: 'image' | 'video' | 'audio'
): { isBase64OrHttp: boolean; finalPath: string } {
  // Se for base64 ou URL externa, retornamos sem mexer
  if (path.startsWith('data:') || path.startsWith('http://') || path.startsWith('https://')) {
    return { isBase64OrHttp: true, finalPath: path };
  }

  // Tentar casar "client_X/company_Y/(image|video|audio)/arquivo"
  const regex = /^client_(\d+)\/company_(\d+)\/(image|video|audio)\/(.+)$/;
  const match = path.match(regex);
  if (match) {
    const clientId = match[1];
    const companyId = match[2];
    // match[3] é o subfolder "image"/"video"/"audio", mas usaremos mediaType
    const filename = match[4];

    return {
      isBase64OrHttp: false,
      finalPath: `${clientId}/${companyId}/${mediaType}/${filename}`,
    };
  }

  // Se não bater no regex, devolve path inalterado
  return { isBase64OrHttp: false, finalPath: path };
}

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null
);

const firstString = (...values: unknown[]) => {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }
  return '';
};

const extractContactDetails = (content: OptimizedMessage['content']): Required<Pick<ContactMessageData, 'displayName'>> & {
  organization: string;
  phone: string;
} => {
  if (typeof content === 'string') {
    const trimmed = content.trim();
    if (trimmed.startsWith('{')) {
      try {
        return extractContactDetails(JSON.parse(trimmed) as ContactMessageData);
      } catch {
        return { displayName: trimmed || 'Contato', organization: '', phone: '' };
      }
    }

    return { displayName: trimmed || 'Contato', organization: '', phone: '' };
  }

  if (!isRecord(content)) {
    return { displayName: 'Contato', organization: '', phone: '' };
  }

  const phones = Array.isArray(content.phones)
    ? content.phones.filter((phone): phone is string => typeof phone === 'string' && Boolean(phone.trim()))
    : [];

  return {
    displayName: firstString(content.displayName, content.fullName, content.name, 'Contato'),
    organization: firstString(content.organization),
    phone: firstString(content.phone, content.phoneNumber, phones[0], content.whatsappId),
  };
};

interface OptimizedMessageContentProps {
  message: OptimizedMessage;
  isOwn: boolean;
  onReply?: (message: OptimizedMessage) => void;
  onReact?: (message: OptimizedMessage, reaction: string) => void;
}

export const OptimizedMessageContent: React.FC<OptimizedMessageContentProps> = React.memo(({
  message,
  isOwn,
  onReply,
  onReact,
}) => {
  const { isDark } = useTheme();
  // DEBUG: Log cada renderização do componente
  console.log('🔄 [DEBUG] OptimizedMessageContent renderizado:', {
    messageId: message.id,
    messageType: message.type,
    renderTime: Date.now(),
    renderTimestamp: new Date().toISOString()
  });

  // Classes base para estilizar as mensagens
  const baseClasses = cx(
    'max-w-[min(72vw,420px)] rounded-2xl p-3 break-words whitespace-pre-wrap shadow-flat',
    isOwn
      ? 'bg-brand text-white'
      : isDark
        ? 'border border-white/10 bg-white/[0.08] text-white'
        : 'border border-brand/10 bg-white text-brand'
  );

  // Formata a hora (HH:mm) a partir de string, se quiser algo simples
  const formatTime = (timestamp: string) => {
    if (!timestamp) return '';
    const parts = timestamp.split(':');
    if (parts.length >= 2) {
      return `${parts[0]}:${parts[1]}`;
    }
    return timestamp;
  };

  const resolvedStatus = isOwn ? message.status || 'sent' : undefined;

  const getStatusMeta = () => {
    if (resolvedStatus === 'sending') return { label: 'Enviando', Icon: Clock };
    if (resolvedStatus === 'failed') return { label: 'Falhou', Icon: XCircle };
    if (resolvedStatus === 'sent') return { label: 'Enviado', Icon: Check };
    if (resolvedStatus === 'delivered') return { label: 'Entregue', Icon: CheckCheck };
    if (resolvedStatus === 'played') return { label: 'Reproduzido', Icon: CheckCheck };
    return { label: 'Lido', Icon: CheckCheck };
  };

  const renderStatusIndicator = (outside = false) => {
    if (!resolvedStatus) return null;

    const { label, Icon } = getStatusMeta();
    const statusTone = resolvedStatus === 'read' || resolvedStatus === 'played'
      ? (outside && !isDark ? 'text-sky-600' : 'text-sky-200')
      : resolvedStatus === 'failed'
        ? (outside && !isDark ? 'text-red-600' : 'text-red-200')
        : outside
          ? (isDark ? 'text-white/65' : 'text-brand/60')
          : 'text-white/70';

    return (
      <span
        className={cx(
          'inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium leading-none',
          outside
            ? isDark
              ? 'bg-white/[0.08] ring-1 ring-white/10'
              : 'bg-white ring-1 ring-brand/10 shadow-flat'
            : 'bg-white/10',
          statusTone
        )}
        title={`Status da mensagem: ${label}`}
        aria-label={`Status da mensagem: ${label}`}
      >
        <Icon className="h-3 w-3" aria-hidden="true" />
        <span>{label}</span>
      </span>
    );
  };

  const renderFooter = (outside = false) => (
    <div className="flex justify-end items-center">
      <span className={cx('text-xs inline-flex items-center gap-1.5', outside ? (isDark ? 'text-white/45' : 'text-brand/45') : isOwn ? 'text-white/65' : isDark ? 'text-white/45' : 'text-brand/45')}>
        {formatTime(message.timestamp)}
        {renderStatusIndicator(outside)}
      </span>
    </div>
  );

  const renderReplyPreview = () => {
    const reply = message.replyTo;
    if (!reply) return null;

    const body = reply.body || reply.content || reply.type || 'Mensagem';
    return (
      <div className={cx('mb-2 rounded-xl border-l-2 px-2 py-1.5 text-xs', isOwn ? 'border-white/50 bg-white/10' : isDark ? 'border-white/30 bg-white/5' : 'border-brand/25 bg-brand-canvas')}>
        <div className={cx('font-semibold', isOwn ? 'text-white/75' : isDark ? 'text-white/70' : 'text-brand/65')}>
          {reply.senderName || 'Mensagem respondida'}
        </div>
        <div className={cx('truncate', isOwn ? 'text-white/70' : isDark ? 'text-white/55' : 'text-brand/55')}>
          {body}
        </div>
      </div>
    );
  };

  const renderReactions = () => {
    if (!message.reactions?.length) return null;
    return (
      <div className={cx('mt-1 flex flex-wrap gap-1', isOwn ? 'justify-end' : 'justify-start')}>
        {message.reactions.map((reaction, index) => (
          <span
            key={`${reaction.actorId || 'actor'}-${reaction.emoji}-${index}`}
            className={cx('inline-flex h-6 min-w-6 items-center justify-center rounded-full border px-1.5 text-xs shadow-flat', isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand')}
            title={reaction.fromMe ? 'Sua reação' : 'Reação recebida'}
          >
            {reaction.emoji}
          </span>
        ))}
      </div>
    );
  };

  const renderActions = () => {
    if (!onReply && !onReact) return null;
    const quickReactions = ['👍', '❤️', '😂'];
    return (
      <div className={cx('absolute -top-8 z-10 flex items-center gap-1 rounded-xl border px-1.5 py-1 opacity-100 shadow-flat transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100', isOwn ? 'right-0' : 'left-0', isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand')}>
        {onReply && (
          <button
            type="button"
            onClick={() => onReply(message)}
            className={cx('flex h-6 w-6 items-center justify-center rounded-lg transition-colors', isDark ? 'hover:bg-white/10' : 'hover:bg-brand-canvas')}
            title="Responder"
          >
            <Reply className="h-3.5 w-3.5" />
          </button>
        )}
        {onReact && (
          <>
            {quickReactions.map(reaction => (
              <button
                key={reaction}
                type="button"
                onClick={() => onReact(message, reaction)}
                className={cx('flex h-6 w-6 items-center justify-center rounded-lg text-sm transition-colors', isDark ? 'hover:bg-white/10' : 'hover:bg-brand-canvas')}
                title={`Reagir com ${reaction}`}
              >
                {reaction}
              </button>
            ))}
            <button
              type="button"
              onClick={() => onReact(message, '')}
              className={cx('flex h-6 w-6 items-center justify-center rounded-lg transition-colors', isDark ? 'hover:bg-white/10' : 'hover:bg-brand-canvas')}
              title="Remover reação"
            >
              <XCircle className="h-3.5 w-3.5" />
            </button>
          </>
        )}
      </div>
    );
  };

  // ===================================
  // Caso seja mensagem de TEXTO
  // ===================================
  if (message.type === 'text') {
    const content = typeof message.content === 'string' ? message.content : '';
    return (
      <div className="group relative">
        {renderActions()}
        <div className={baseClasses}>
          <div className="flex flex-col">
            {renderReplyPreview()}
            <p className="text-sm mb-1 overflow-hidden text-ellipsis">{content}</p>
            {renderFooter()}
          </div>
        </div>
        {renderReactions()}

      </div>
    );
  }

  // ===================================
  // Caso seja mensagem de CONTATO
  // ===================================
  if (message.type === 'contact') {
    const contact = extractContactDetails(message.content);
    return (
      <div className="group relative">
        {renderActions()}
        <div className={cx(
          'max-w-[min(72vw,420px)] rounded-2xl p-3 shadow-flat',
          isOwn
            ? 'bg-brand text-white'
            : isDark
              ? 'border border-white/10 bg-white/[0.08] text-white'
              : 'border border-brand/10 bg-white text-brand'
        )}>
          <div className="flex flex-col gap-2">
            {renderReplyPreview()}
            <div className="flex items-center gap-3">
              <div className={cx(
                'flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl',
                isOwn
                  ? 'bg-white/12 text-white'
                  : isDark
                    ? 'bg-white/10 text-white'
                    : 'bg-brand-canvas text-brand'
              )}>
                <UserRound className="h-5 w-5" aria-hidden="true" />
              </div>
              <div className="min-w-0 flex-1">
                <div className={cx('text-[11px] font-medium uppercase tracking-normal', isOwn ? 'text-white/60' : isDark ? 'text-white/45' : 'text-brand/45')}>
                  Contato
                </div>
                <div className="truncate text-sm font-semibold">
                  {contact.displayName}
                </div>
                {contact.organization && (
                  <div className={cx('truncate text-xs', isOwn ? 'text-white/65' : isDark ? 'text-white/55' : 'text-brand/55')}>
                    {contact.organization}
                  </div>
                )}
              </div>
            </div>
            {contact.phone && (
              <div className={cx(
                'flex items-center gap-2 rounded-xl px-2.5 py-2 text-xs',
                isOwn
                  ? 'bg-white/10 text-white/75'
                  : isDark
                    ? 'bg-white/[0.06] text-white/65'
                    : 'bg-brand-canvas text-brand/65'
              )}>
                <Phone className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span className="truncate">{contact.phone}</span>
              </div>
            )}
            {renderFooter()}
          </div>
        </div>
        {renderReactions()}
      </div>
    );
  }

  // ===================================
  // Caso seja mensagem de IMAGEM
  // ===================================
  if (message.type === 'image') {
    const imageContent = message.content;
    let imageUrl = '';
    let mediaPath: string | undefined;
    let needsLoading = false;

    if (typeof imageContent === 'string') {
      // Se for base64 (data:) ou http(s), usamos diretamente em imageUrl
      if (imageContent.startsWith('data:image/') || imageContent.startsWith('http')) {
        // 🔥 CORREÇÃO: Converter URLs WAHA para proxy
        console.log('🖼️ OptimizedMessageContent - Imagem original:', imageContent.substring(0, 80) + '...');
        imageUrl = convertWahaUrl(imageContent);
        console.log('🖼️ OptimizedMessageContent - Imagem convertida:', imageUrl.substring(0, 80) + '...');
      } else {
        // Normalizar caminho local
        const { isBase64OrHttp, finalPath } = normalizeMediaPath(imageContent, 'image');
        if (isBase64OrHttp) {
          // Se detectou data: ou http
          imageUrl = finalPath;
        } else {
          // Caminho local => usaremos mediaPath + needsLoading
          mediaPath = finalPath;
          needsLoading = true;
        }
      }
    } else if (imageContent && typeof imageContent === 'object') {
      // Se vier no formato { url, mediaPath, needsLoading }
      const contentObj = imageContent as {
        url?: string;
        mediaPath?: string;
        needsLoading?: boolean;
      };

      imageUrl = contentObj.url || '';
      mediaPath = contentObj.mediaPath;
      needsLoading = !!contentObj.needsLoading;
    }

    // Se ao final não há nem imageUrl nem mediaPath, erro
    if (!imageUrl && !mediaPath) {
      console.error('URL da imagem não encontrada:', message);
      return (
        <div className="max-w-[300px] rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-500">
          Erro ao carregar imagem
        </div>
      );
    }

    return (
      <div className="group relative max-w-[min(72vw,420px)] space-y-1">
        {renderActions()}
        {renderReplyPreview()}
        <OptimizedImageContent
          src={imageUrl}
          mediaPath={mediaPath}
          needsLoading={needsLoading}
          alt="Imagem compartilhada"
          isOwn={isOwn}
        />
        {renderFooter(true)}
        {renderReactions()}
      </div>
    );
  }

  // ===================================
  // Caso seja mensagem de ÁUDIO
  // ===================================
  if (message.type === 'audio') {
    const audioContent = message.content;
    let audioUrl = '';
    let mediaPath: string | undefined;
    let needsLoading = false;

    console.log('🔍 OptimizedMessageContent - áudio recebido:', {
      id: message.id,
      contentType: typeof audioContent,
      content: typeof audioContent === 'string' ?
        audioContent.substring(0, 100) + '...' :
        JSON.stringify(audioContent).substring(0, 100) + '...',
      fromMe: message.fromMe
    });

    if (typeof audioContent === 'string') {
      if (audioContent.startsWith('data:audio/') || audioContent.startsWith('http') || audioContent.startsWith('blob:')) {
        // 🔥 CORREÇÃO: Converter URLs WAHA para proxy
        audioUrl = convertWahaUrl(audioContent);
        console.log('🎵 OptimizedMessageContent - usando URL:', audioUrl.substring(0, 50) + '...');
      } else {
        const { isBase64OrHttp, finalPath } = normalizeMediaPath(audioContent, 'audio');
        console.log('🎵 OptimizedMessageContent - caminho normalizado:', { isBase64OrHttp, finalPath });
        if (isBase64OrHttp) {
          audioUrl = finalPath;
        } else {
          mediaPath = finalPath;
          needsLoading = true;
        }
      }
    } else if (audioContent && typeof audioContent === 'object') {
      const contentObj = audioContent as {
        url?: string;
        mediaPath?: string;
        needsLoading?: boolean;
      };

      console.log('🎵 OptimizedMessageContent - objeto de áudio:', contentObj);
      audioUrl = contentObj.url || '';
      mediaPath = contentObj.mediaPath;
      needsLoading = !!contentObj.needsLoading;

      if (audioUrl && audioUrl.startsWith('blob:')) {
        console.log('🎵 OptimizedMessageContent - usando blob URL:', audioUrl);
        needsLoading = false;
      }
    }

    const finalSrc = audioUrl || mediaPath || '';
    console.log('🎵 OptimizedMessageContent - áudio final para AudioWaveform:', finalSrc);

    // Extrair a duração, se disponível
    let audioDuration: number | undefined;
    if (typeof audioContent === 'object' && audioContent) {
      audioDuration = (audioContent as any).duration;
    }

    return (
      <div className="group relative">
        {renderActions()}
        <div className={cx(
          'max-w-[min(72vw,420px)] rounded-2xl p-2 shadow-flat',
          isOwn
            ? 'bg-brand text-white'
            : isDark
              ? 'border border-white/10 bg-white/[0.08] text-white'
              : 'border border-brand/10 bg-white text-brand'
        )}>
          {renderReplyPreview()}
          <AudioWaveform
            src={finalSrc}
            messageColor={isOwn ? 'light' : 'dark'}
            className="w-full"
            duration={audioDuration}
          />
          <div className="mt-1">
            {renderFooter()}
          </div>
        </div>
        {renderReactions()}
      </div>
    );
  }

  // ===================================
  // Caso seja mensagem de VÍDEO
  // ===================================
  if (message.type === 'video') {
    console.log('🎥 [DEBUG] Entrando na seção de vídeo:', {
      messageId: message.id,
      entryTime: Date.now(),
      entryTimestamp: new Date().toISOString()
    });
    const videoContent = message.content;
    let videoUrl = '';
    let videoPath: string | undefined;
    let thumbnailUrl = '';
    let needsLoading = false;

    if (typeof videoContent === 'string') {
      // Se for data:video/ ou http(s), definimos videoUrl e não usamos mediaPath
      if (videoContent.startsWith('data:video/') || videoContent.startsWith('http')) {
        // 🔥 CORREÇÃO: Converter URLs WAHA para proxy
        videoUrl = convertWahaUrl(videoContent);
        needsLoading = false; // Já temos o conteúdo, não precisa carregar
      } else {
        // Caso contrário, interpretamos como caminho local
        const { isBase64OrHttp, finalPath } = normalizeMediaPath(videoContent, 'video');
        if (isBase64OrHttp) {
          videoUrl = finalPath;
          needsLoading = false; // Já temos o conteúdo, não precisa carregar
        } else {
          videoPath = finalPath;
          needsLoading = true;
        }
      }
    } else if (videoContent && typeof videoContent === 'object') {
      const contentObj = videoContent as {
        url?: string;
        mediaPath?: string;
        thumbnailUrl?: string;
        mimeType?: string;
        needsLoading?: boolean;
      };

      videoUrl = contentObj.url || '';
      videoPath = contentObj.mediaPath;
      thumbnailUrl = contentObj.thumbnailUrl || '';
      needsLoading = !!contentObj.needsLoading;
    }

    console.log('Processando conteúdo de vídeo:', {
      messageId: message.id,
      original: message.content,
      videoUrl,
      videoPath,
      needsLoading,
      fromMe: message.fromMe,
    });

    if (!videoUrl && !videoPath) {
      console.error('URL ou caminho do vídeo não encontrado:', message);
      return (
        <div className="max-w-[300px] rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-500">
          Erro ao carregar vídeo
        </div>
      );
    }

    // Renderiza o player
    return (
      <div className="group relative max-w-[min(72vw,420px)] space-y-1">
        {renderActions()}
        {renderReplyPreview()}
        <VideoPlayer
          src={videoUrl}
          mediaPath={videoPath}
          needsLoading={needsLoading}
          messageColor={isOwn ? 'light' : 'dark'}
          thumbnailUrl={thumbnailUrl}
          status={resolvedStatus}
          fromMe={message.fromMe}
          className="rounded-2xl overflow-hidden w-full"
        />
        {renderFooter(true)}
        {renderReactions()}
      </div>
    );
  }

  // ===================================
  // Caso seja mensagem de NPS
  // ===================================
  if (message.type === 'nps') {
    const npsContent = message.content;
    let npsData: NPSMessageData;

    // Parse do conteúdo (pode ser string JSON ou objeto)
    try {
      let parsedContent: any;
      if (typeof npsContent === 'string') {
        parsedContent = JSON.parse(npsContent);
      } else if (typeof npsContent === 'object') {
        parsedContent = npsContent;
      }

      if (parsedContent?.nps_data) {
        npsData = parsedContent.nps_data;
      } else {
        throw new Error('No nps_data found');
      }
    } catch (e) {
      // Fallback caso não tenha nps_data estruturado
      npsData = {
        question: 'Em uma escala de 1 a 5, como você avalia nosso atendimento?',
        status: 'sent'
      };
    }

    return (
      <NPSMessage
        npsData={npsData}
        isOwn={isOwn}
        timestamp={message.timestamp}
      />
    );
  }

  // Fallback caso o tipo não seja reconhecido
  return null;
});
