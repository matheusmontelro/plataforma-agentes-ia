import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Loader,
  AlertCircle,
  Maximize,
  Download,
  ExternalLink
} from 'lucide-react';
import { getMessageMedia, API_URL } from '../services/api.ts';

interface VideoPlayerProps {
  src?: string;
  mediaPath?: string;
  needsLoading?: boolean;
  className?: string;
  messageColor?: 'light' | 'dark';
  thumbnailUrl?: string;
  status?: 'sending' | 'sent' | 'delivered' | 'read' | 'played' | 'failed';
  fromMe?: boolean;
}

const VideoPlayer: React.FC<VideoPlayerProps> = ({
  src = '',
  mediaPath,
  needsLoading = false,
  className = '',
  messageColor = 'dark',
  thumbnailUrl,
  status = 'sent',
  fromMe = false
}) => {
  // Estados
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [loadingState, setLoadingState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [isSending, setIsSending] = useState(status === 'sending');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [processedSrc, setProcessedSrc] = useState<string>('');
  const [isProcessingMedia, setIsProcessingMedia] = useState(needsLoading);

  // Refs
  const videoRef = useRef<HTMLVideoElement>(null);
  const progressBarRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Função para carregar mídia
  const loadMedia = useCallback(async () => {
    if (!needsLoading || !mediaPath) return;

    setIsProcessingMedia(true);
    try {
      console.log("Carregando vídeo do caminho:", mediaPath);
      const mediaUrl = await getMessageMedia(mediaPath, fromMe);
      console.log("Vídeo carregado com sucesso:", mediaUrl);
      setProcessedSrc(mediaUrl);
    } catch (error) {
      console.error("Erro ao carregar mídia:", error);
      setErrorMessage("Não foi possível carregar o vídeo");
      setLoadingState('error');
    } finally {
      setIsProcessingMedia(false);
    }
  }, [needsLoading, mediaPath, fromMe]);

  // Carregar mídia se necessário
  useEffect(() => {
    // Se temos src (base64 ou URL direta), usar diretamente e não carregar via mediaPath
    if (src) {
      setProcessedSrc(src);
    }
    // Se não temos src mas temos mediaPath e needsLoading, carregar via API
    else if (mediaPath && needsLoading) {
      loadMedia();
    }
  }, [src, mediaPath, needsLoading, fromMe, loadMedia]);

  // Alternar reprodução
  const togglePlay = () => {
    if (!videoRef.current || loadingState !== 'ready') return;

    if (isPlaying) {
      videoRef.current.pause();
    } else {
      videoRef.current.play().catch(err => {
        console.error("Erro ao reproduzir vídeo:", err);
      });
    }
    setIsPlaying(!isPlaying);
  };

  // Alternar mudo
  const toggleMute = () => {
    if (!videoRef.current) return;
    setIsMuted(!isMuted);
  };

  // Controle da barra de progresso
  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!videoRef.current || !progressBarRef.current || loadingState !== 'ready') return;

    const rect = progressBarRef.current.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    videoRef.current.currentTime = Math.max(0, Math.min(pos * duration, duration));
  };

  // Entrar em tela cheia
  const enterFullscreen = () => {
    if (videoRef.current) {
      videoRef.current.requestFullscreen().catch(err => {
        console.error("Erro ao entrar em tela cheia:", err);
      });
    }
  };

  // Efeito para verificar se o vídeo está pronto
  useEffect(() => {
    if (!videoRef.current || !processedSrc) return;

    // Se o status for 'sending', definir isSending como true
    if (status === 'sending') {
      setIsSending(true);
      setLoadingState('loading');
    }

    const video = videoRef.current;

    const handleLoadedMetadata = () => {
      setDuration(video.duration);
      setLoadingState('ready');
      console.log("Metadados do vídeo carregados:", {
        src: processedSrc,
        width: video.videoWidth,
        height: video.videoHeight,
        duration: video.duration
      });
    };

    const handleTimeUpdate = () => {
      setCurrentTime(video.currentTime);
    };

    const handleEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
      video.currentTime = 0;
    };

    const handleCanPlay = () => {
      setLoadingState('ready');
      console.log("Vídeo pode ser reproduzido:", processedSrc);
    };

    const handleError = async () => {
      console.error('Erro ao carregar vídeo:', video.error);

      setLoadingState('error');

      if (video.error) {
        let errorMsg = "Erro desconhecido ao carregar o vídeo";

        switch (video.error.code) {
          case MediaError.MEDIA_ERR_ABORTED:
            errorMsg = "Carregamento do vídeo foi abortado";
            break;
          case MediaError.MEDIA_ERR_NETWORK:
            errorMsg = "Erro de rede ao carregar o vídeo";
            break;
          case MediaError.MEDIA_ERR_DECODE:
            errorMsg = "Formato de vídeo não suportado. O vídeo está sendo convertido automaticamente.";
            // Tentar recarregar após um delay
            setTimeout(() => {
              console.log("Tentando recarregar vídeo após conversão...");
              if (mediaPath && videoRef.current) {
                loadMedia(); // Tentar recarregar
              }
            }, 3000);
            break;
          case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
            errorMsg = "Formato de vídeo não suportado. O vídeo está sendo convertido automaticamente.";
            // Tentar recarregar após um delay
            setTimeout(() => {
              console.log("Tentando recarregar vídeo após conversão...");
              if (mediaPath && videoRef.current) {
                loadMedia(); // Tentar recarregar
              }
            }, 3000);
            break;
        }

        setErrorMessage(errorMsg);
      }
    };

    // Registrar listeners
    video.addEventListener('loadedmetadata', handleLoadedMetadata);
    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('ended', handleEnded);
    video.addEventListener('canplay', handleCanPlay);
    video.addEventListener('error', handleError);

    // Cleanup
    return () => {
      video.removeEventListener('loadedmetadata', handleLoadedMetadata);
      video.removeEventListener('timeupdate', handleTimeUpdate);
      video.removeEventListener('ended', handleEnded);
      video.removeEventListener('canplay', handleCanPlay);
      video.removeEventListener('error', handleError);
    };
  }, [processedSrc, status, loadMedia, mediaPath]);

  // Efeito para atualizar o estado de envio com base no status
  useEffect(() => {
    setIsSending(status === 'sending');

    if (isSending && status !== 'sending') {
      setIsSending(false);
      if (loadingState === 'loading' && videoRef.current) {
        videoRef.current.load();
      }
    }
  }, [status, isSending, loadingState]);

  // Efeito para atualizar mudo no vídeo
  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.muted = isMuted;
    }
  }, [isMuted]);

  // Formatar tempo em MM:SS
  const formatTime = (time: number) => {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  // Tentar carregar novamente
  const handleRetryLoading = async () => {
    if (!mediaPath) return;

    setLoadingState('loading');
    setIsProcessingMedia(true);

    try {
      console.log("Tentando carregar vídeo novamente do caminho:", mediaPath);
      const mediaUrl = await getMessageMedia(mediaPath, fromMe);
      console.log("Vídeo recarregado com sucesso:", mediaUrl);

      setProcessedSrc(mediaUrl);

      if (videoRef.current) {
        videoRef.current.src = mediaUrl;
        videoRef.current.load();
      }
    } catch (error) {
      console.error("Erro ao recarregar vídeo:", error);
      setErrorMessage("Não foi possível carregar o vídeo após nova tentativa");
      setLoadingState('error');
    } finally {
      setIsProcessingMedia(false);
    }
  };

  // URL para download
  const downloadUrl = useMemo(() => {
    if (processedSrc.startsWith('data:')) {
      return processedSrc;
    }

    if (processedSrc.startsWith('http')) {
      return processedSrc;
    }

    if (mediaPath) {
      const clientId = localStorage.getItem('client_id');
      const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

      if (clientId && companyId) {
        // Se o caminho já tem formato client_X/company_Y
        if (mediaPath.match(/^client_\d+\/company_\d+\//)) {
          const parts = mediaPath.match(/^client_(\d+)\/company_(\d+)\/(.+)$/);
          if (parts) {
            return `${API_URL}/media/messages/${parts[1]}/${parts[2]}/${parts[3]}`;
          }
        }

        // Formato normal
        return `${API_URL}/media/messages/${clientId}/${companyId}/${mediaPath}`;
      }
    }

    return processedSrc;
  }, [processedSrc, mediaPath]);

  return (
    <div
      ref={containerRef}
      className={`relative rounded-lg overflow-hidden shadow-sm ${className}`}
      style={{ maxWidth: '280px' }}
    >
      {/* Vídeo */}
      <div className="bg-black">
        <video
          ref={videoRef}
          src={processedSrc}
          className="w-full object-contain max-h-80"
          poster={thumbnailUrl}
          preload="auto"
          playsInline
          controls={false}
          onClick={togglePlay}
        />
      </div>

      {/* Overlay de carregamento */}
      {(loadingState === 'loading' || isProcessingMedia) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/50">
          <Loader className="w-8 h-8 text-white animate-spin mb-2" />
          <p className="text-xs text-white">Carregando vídeo...</p>
        </div>
      )}

      {/* Overlay de erro com mensagem detalhada */}
      {loadingState === 'error' && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60">
          <div className="flex flex-col items-center p-2 text-center">
            <AlertCircle className="w-8 h-8 text-red-500 mb-1" />
            <span className="text-xs text-white mb-2">
              {errorMessage || "Erro ao carregar vídeo"}
            </span>
            <div className="flex flex-col space-y-2">
              <div className="flex space-x-2">
                <a
                  href={downloadUrl}
                  download
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-2 py-1 bg-blue-500 rounded text-xs text-white hover:bg-blue-600 flex items-center"
                >
                  <Download className="w-3 h-3 mr-1" />
                  <span>Baixar</span>
                </a>
                <button
                  onClick={() => window.open(downloadUrl, '_blank')}
                  className="px-2 py-1 bg-gray-500 rounded text-xs text-white hover:bg-gray-600 flex items-center"
                >
                  <ExternalLink className="w-3 h-3 mr-1" />
                  <span>Abrir</span>
                </button>
              </div>
              {mediaPath && (
                <button
                  onClick={handleRetryLoading}
                  className="px-2 py-1 bg-green-500 rounded text-xs text-white hover:bg-green-600 mt-2"
                >
                  Tentar novamente
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Botão de Play central */}
      {loadingState === 'ready' && !isPlaying && (
        <div
          className="absolute inset-0 flex items-center justify-center cursor-pointer"
          onClick={togglePlay}
        >
          <div className="rounded-full bg-black/50 p-3">
            <Play className="w-6 h-6 text-white" />
          </div>
        </div>
      )}

      {/* Controles inferiores */}
      {loadingState === 'ready' && (
        <div className="bg-black px-2 py-1 flex flex-col">
          {/* Barra de progresso */}
          <div
            ref={progressBarRef}
            className="h-1 w-full mb-1 bg-gray-600 rounded-full cursor-pointer"
            onClick={handleProgressClick}
          >
            <div
              className="h-full bg-blue-500 rounded-full"
              style={{ width: `${(currentTime / duration) * 100}%` }}
            />
          </div>

          {/* Linha de controles */}
          <div className="flex items-center justify-between">
            {/* Play/Pause */}
            <button
              onClick={togglePlay}
              className="p-1 text-white focus:outline-none"
            >
              {isPlaying ? (
                <Pause className="w-4 h-4" />
              ) : (
                <Play className="w-4 h-4" />
              )}
            </button>

            {/* Timer */}
            <div className="text-xs text-gray-300">
              {formatTime(currentTime)} / {formatTime(duration)}
            </div>

            <div className="flex items-center space-x-2">
              {/* Mute */}
              <button
                onClick={toggleMute}
                className="p-1 text-white focus:outline-none"
              >
                {isMuted ? (
                  <VolumeX className="w-4 h-4" />
                ) : (
                  <Volume2 className="w-4 h-4" />
                )}
              </button>

              {/* Fullscreen */}
              <button
                onClick={enterFullscreen}
                className="p-1 text-white focus:outline-none"
              >
                <Maximize className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default VideoPlayer;
