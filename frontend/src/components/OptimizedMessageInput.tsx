import React, { useState, useRef } from 'react';
import { Send, ImageIcon, Video as VideoIcon, BarChart3, MoreHorizontal, Smile, X } from 'lucide-react';
import AudioRecorder from './AudioRecorder.tsx';
import { useTheme } from '../contexts/ThemeContext.tsx';
import { agentiveIconButtonClass } from './AgentiveUI.tsx';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

interface OptimizedMessageInputProps {
  onSendText: () => void;
  onSendImage: (file: File) => void;
  onSendVideo: (file: File) => void;
  onSendAudio?: (audioBlob: Blob, durationSeconds: number) => void;
  onSendNPS?: () => void;
  onStartRecording?: () => void;
  disabled?: boolean;
  placeholder?: string;
  value?: string;
  onChange?: (value: string) => void;
  extraControl?: React.ReactNode;
  extraControlLabel?: string;
  actionsMode?: 'inline' | 'menu';
}

export const OptimizedMessageInput: React.FC<OptimizedMessageInputProps> = ({
  onSendText,
  onSendImage,
  onSendVideo,
  onSendAudio,
  onSendNPS,
  onStartRecording,
  disabled = false,
  placeholder = 'Digite uma mensagem...',
  value = '',
  onChange,
  extraControl,
  extraControlLabel = 'Atendimento',
  actionsMode = 'inline'
}) => {
  const { isDark } = useTheme();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const videoInputRef = useRef<HTMLInputElement>(null);
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [showActionMenu, setShowActionMenu] = useState(false);
  const isMenuMode = actionsMode === 'menu';

  const EMOJIS_POPULARES = [
    '😊', '👍', '❤️', '😢', '😂', '🙏',
    '✅', '❌', '⚠️', '🎉', '💯', '🔥',
    '📞', '📅', '🦷', '💊', '🏥', '⭐'
  ];

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (onChange) {
      onChange(e.target.value);
    }
  };

  const insertEmoji = (emoji: string) => {
    const currentValue = value || '';
    const newValue = currentValue + emoji;
    if (onChange) {
      onChange(newValue);
    }
    setShowEmojiPicker(false);
    setShowActionMenu(false);
  };

  const handleSubmit = () => {
    if (value.trim() && !disabled) {
      onSendText();
      if (onChange) {
        onChange('');
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>, type: 'image' | 'video') => {
    if (!e.target.files || e.target.files.length === 0) return;

    const file = e.target.files[0];
    e.target.value = '';

    if (type === 'image') {
      onSendImage(file);
    } else {
      onSendVideo(file);
    }
  };

  const closeActionMenu = () => {
    setShowActionMenu(false);
    setShowEmojiPicker(false);
  };

  const openActionMenu = () => {
    setShowEmojiPicker(false);
    setShowActionMenu(true);
  };

  const openImagePicker = () => {
    fileInputRef.current?.click();
    closeActionMenu();
  };

  const openVideoPicker = () => {
    videoInputRef.current?.click();
    closeActionMenu();
  };

  const handleSendNPSFromMenu = () => {
    onSendNPS?.();
    closeActionMenu();
  };

  const renderInlineActions = () => (
    <div className="flex shrink-0 items-center gap-1">
      <AudioRecorder
        onAudioRecorded={(blob, durationSeconds) => {
          if (onSendAudio) {
            onSendAudio(blob, durationSeconds);
          }
        }}
      />

      <button
        type="button"
        onClick={() => setShowEmojiPicker(!showEmojiPicker)}
        disabled={disabled}
        className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-9 min-w-9')}
        title="Emojis"
      >
        <Smile className="h-5 w-5" />
      </button>

      <button
        type="button"
        onClick={openImagePicker}
        disabled={disabled}
        className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-9 min-w-9')}
        title="Enviar imagem"
      >
        <ImageIcon className="h-5 w-5" />
      </button>

      <button
        type="button"
        onClick={openVideoPicker}
        disabled={disabled}
        className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-9 min-w-9')}
        title="Enviar vídeo"
      >
        <VideoIcon className="h-5 w-5" />
      </button>

      {onSendNPS && (
        <button
          type="button"
          onClick={handleSendNPSFromMenu}
          disabled={disabled}
          className={agentiveIconButtonClass(isDark, 'primary', 'min-h-9 min-w-9')}
          title="Enviar pesquisa NPS"
        >
          <BarChart3 className="h-5 w-5" />
        </button>
      )}
    </div>
  );

  const actionItemClass = cx(
    'flex w-full items-center justify-between gap-3 rounded-2xl border px-3 py-3 text-left text-sm font-semibold transition-colors',
    isDark
      ? 'border-white/10 bg-white/[0.04] text-white hover:bg-white/[0.08]'
      : 'border-brand/10 bg-brand-canvas text-brand hover:bg-white'
  );

  return (
    <div className={cx('relative flex items-end gap-2 border-t p-2.5 sm:p-3', isDark ? 'border-white/10 bg-white/[0.05]' : 'border-brand/10 bg-white')}>
      {showActionMenu && isMenuMode && (
        <div className="fixed inset-0 z-[70] flex items-end justify-center bg-brand/45 p-3 pb-[calc(1rem+env(safe-area-inset-bottom))] backdrop-blur-sm" onClick={closeActionMenu}>
          <div
            className={cx(
              'w-full max-w-md rounded-[24px] border p-3 shadow-[0_24px_70px_rgba(2,3,35,0.25)]',
              isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand'
            )}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between gap-3 px-1">
              <div>
                <p className={cx('text-[10px] font-bold uppercase tracking-[0.16em]', isDark ? 'text-white/35' : 'text-brand/35')}>
                  Ações do chat
                </p>
                <p className={cx('mt-1 text-sm', isDark ? 'text-white/65' : 'text-brand/60')}>
                  Envie mídias, áudio e controles da conversa.
                </p>
              </div>
              <button
                type="button"
                className={agentiveIconButtonClass(isDark, 'neutral')}
                onClick={closeActionMenu}
                aria-label="Fechar ações"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-2">
              {extraControl && (
                <div className={actionItemClass}>
                  <span>{extraControlLabel}</span>
                  {extraControl}
                </div>
              )}

              <div className={actionItemClass}>
                <span>Gravar áudio</span>
                <AudioRecorder
                  onAudioRecorded={(blob, durationSeconds) => {
                    if (onSendAudio) {
                      onSendAudio(blob, durationSeconds);
                    }
                    closeActionMenu();
                  }}
                />
              </div>

              <button type="button" className={actionItemClass} onClick={() => setShowEmojiPicker(!showEmojiPicker)} disabled={disabled}>
                <span>Emojis</span>
                <Smile className="h-5 w-5" />
              </button>

              <button type="button" className={actionItemClass} onClick={openImagePicker} disabled={disabled}>
                <span>Enviar imagem</span>
                <ImageIcon className="h-5 w-5" />
              </button>

              <button type="button" className={actionItemClass} onClick={openVideoPicker} disabled={disabled}>
                <span>Enviar vídeo</span>
                <VideoIcon className="h-5 w-5" />
              </button>

              {onSendNPS && (
                <button type="button" className={actionItemClass} onClick={handleSendNPSFromMenu} disabled={disabled}>
                  <span>Enviar pesquisa NPS</span>
                  <BarChart3 className="h-5 w-5" />
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Popup Picker de Emojis */}
      {showEmojiPicker && (
        <div className={cx(isMenuMode ? 'fixed inset-x-3 bottom-[calc(1rem+env(safe-area-inset-bottom))] z-[80] mx-auto max-w-md rounded-2xl border p-3 shadow-[0_18px_45px_rgba(2,3,35,0.18)]' : 'absolute bottom-full left-3 z-50 mb-2 rounded-2xl border p-3 shadow-[0_18px_45px_rgba(2,3,35,0.18)]', isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand')}>
          <div className="grid grid-cols-6 gap-2">
            {EMOJIS_POPULARES.map(emoji => (
              <button
                key={emoji}
                onClick={() => insertEmoji(emoji)}
                className={cx('rounded-xl p-1 text-xl transition-colors', isDark ? 'hover:bg-white/10' : 'hover:bg-brand-canvas')}
                title={`Inserir ${emoji}`}
              >
                {emoji}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Área dos controles (audio recorder, botões de mídia e controles extra) */}
      {isMenuMode ? (
        <button
          type="button"
          onClick={openActionMenu}
          disabled={disabled}
          className={agentiveIconButtonClass(isDark, 'neutral', 'min-h-11 min-w-11')}
          title="Mais ações"
          aria-label="Mais ações do chat"
        >
          <MoreHorizontal className="h-5 w-5" />
        </button>
      ) : renderInlineActions()}

      {/* Campo de texto */}
      <div className={cx('flex min-w-0 flex-1 items-center overflow-hidden rounded-2xl border px-1', isDark ? 'border-white/10 bg-white/[0.06]' : 'border-brand/10 bg-brand-canvas')}>
        {!isMenuMode && extraControl && (
          <div className="flex shrink-0 items-center">
            {extraControl}
          </div>
        )}

        <textarea
          value={value}
          onChange={handleTextChange}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
          placeholder={placeholder}
          disabled={disabled}
          className={cx('max-h-24 min-h-[44px] flex-1 resize-none bg-transparent p-3 text-sm outline-none', isDark ? 'text-white placeholder:text-white/35' : 'text-brand placeholder:text-brand/35')}
          rows={1}
        />
      </div>

      {/* Botão enviar */}
      <button
        onClick={handleSubmit}
        disabled={!value.trim() || disabled}
        className={cx(
          'flex min-h-10 min-w-10 items-center justify-center rounded-xl p-2.5 transition-all duration-200',
          value.trim() && !disabled
            ? 'bg-brand text-white shadow-flat hover:bg-brand/90'
            : isDark ? 'bg-white/10 text-white/35' : 'bg-brand/10 text-brand/35'
        )}
        title="Enviar mensagem"
      >
        <Send className="h-5 w-5" />
      </button>

      {/* Inputs invisíveis */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => handleFileChange(e, 'image')}
      />
      <input
        ref={videoInputRef}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(e) => handleFileChange(e, 'video')}
      />
    </div>
  );
};
