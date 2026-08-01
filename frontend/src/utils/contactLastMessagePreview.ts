export type ContactLastMessagePreviewType = 'text' | 'image' | 'video' | 'audio' | 'nps';

export interface ContactLastMessagePreview {
  type: ContactLastMessagePreviewType;
  label: string;
}

const AUDIO_EXTENSIONS = /\.(mp3|wav|ogg|oga|opus|m4a|mpeg|mpga|webm)($|\?)/i;
const VIDEO_EXTENSIONS = /\.(mp4|mov|avi|wmv|flv|webm|mkv)($|\?)/i;
const IMAGE_EXTENSIONS = /\.(jpg|jpeg|png|gif|bmp|webp)($|\?)/i;

const normalizeMessageValue = (message: unknown): string => {
  if (message === null || message === undefined) return '';
  if (typeof message === 'string') return message.trim();

  if (typeof message === 'object') {
    const maybeMedia = message as {
      url?: unknown;
      mediaUrl?: unknown;
      imageUrl?: unknown;
      videoUrl?: unknown;
      audioUrl?: unknown;
      content?: unknown;
      message?: unknown;
    };

    const candidate =
      maybeMedia.url ||
      maybeMedia.mediaUrl ||
      maybeMedia.imageUrl ||
      maybeMedia.videoUrl ||
      maybeMedia.audioUrl ||
      maybeMedia.content ||
      maybeMedia.message;

    if (typeof candidate === 'string') return candidate.trim();

    try {
      return JSON.stringify(message);
    } catch {
      return '';
    }
  }

  return String(message).trim();
};

export const getContactLastMessagePreview = (message: unknown): ContactLastMessagePreview => {
  const raw = normalizeMessageValue(message);
  if (!raw) {
    return { type: 'text', label: '' };
  }

  const content = raw.toLowerCase();

  if (content === 'nps' || content.includes('"nps_data"') || content.includes('"nps_id"')) {
    return { type: 'nps', label: 'Pesquisa NPS' };
  }

  if (
    content === '[audio]' ||
    content === 'audio_message' ||
    content === 'audio' ||
    content === 'áudio' ||
    content === 'audio recebido' ||
    content === 'áudio recebido' ||
    content === '🎵 áudio' ||
    content === '🔊 áudio' ||
    content.startsWith('data:audio/') ||
    AUDIO_EXTENSIONS.test(raw) ||
    content.includes('/audio/') ||
    content.includes('audio/')
  ) {
    return { type: 'audio', label: 'Áudio' };
  }

  if (
    content === '[video]' ||
    content === 'video_message' ||
    content === 'video' ||
    content === 'vídeo' ||
    content === '🎥 vídeo' ||
    content.startsWith('data:video/') ||
    VIDEO_EXTENSIONS.test(raw) ||
    content.includes('/video/') ||
    content.includes('video/')
  ) {
    return { type: 'video', label: 'Vídeo' };
  }

  if (
    content === '[image]' ||
    content === 'image_message' ||
    content === 'image' ||
    content === 'imagem' ||
    content === 'foto' ||
    content === '🖼️ imagem' ||
    content.startsWith('data:image/') ||
    IMAGE_EXTENSIONS.test(raw) ||
    content.includes('/image/') ||
    content.includes('image/') ||
    content.includes('/file/') ||
    content.includes('backblaze') ||
    content.includes('f004.backblazeb2.com')
  ) {
    return { type: 'image', label: 'Imagem' };
  }

  return { type: 'text', label: raw };
};

export const normalizeContactLastMessage = (message: unknown): string => {
  return getContactLastMessagePreview(message).label;
};
