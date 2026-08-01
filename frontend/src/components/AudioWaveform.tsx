import React, { useEffect, useRef, useState } from 'react';
import { PlayIcon, PauseIcon, Volume2, VolumeX } from 'lucide-react';

/**
 * Propriedades do componente de áudio com forma de onda simulada.
 */
interface AudioWaveformProps {
  /** URL do áudio (local ou remoto). */
  src: string;
  /** Classe adicional para estilizar o container. */
  className?: string;
  /** Tema de cor (clara ou escura) */
  messageColor?: 'light' | 'dark';
  /** Duração do áudio, se já conhecida (ex.: do momento da gravação). */
  duration?: number;
}

/**
 * Componente que exibe um player de áudio + forma de onda simulada.
 * Se `duration` for informado, ignora os metadados do <audio>.
 */
const AudioWaveform: React.FC<AudioWaveformProps> = ({
  src,
  className = '',
  messageColor = 'dark',
  duration: propDuration // Renomeamos para evitar conflito com state
}) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);

  // Se recebemos `propDuration`, começamos com ele; senão, 0.
  const [duration, setDuration] = useState(propDuration || 0);

  // Tempo atual de reprodução
  const [currentTime, setCurrentTime] = useState(0);

  // Dados simulados para desenhar a forma de onda
  const [waveformData, setWaveformData] = useState<number[]>([]);

  // Indica se já carregamos o suficiente para exibir o canvas
  const [isLoaded, setIsLoaded] = useState(false);

  // Referências a elementos
  const audioRef = useRef<HTMLAudioElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number | null>(null);

  // Tema de cores para as barras da forma de onda
  const colors = {
    light: {
      waveform: 'rgba(255, 255, 255, 0.5)',
      progress: 'rgba(255, 255, 255, 0.9)',
      text: 'text-white',
      button: 'bg-white/20 hover:bg-white/30 text-white',
    },
    dark: {
      waveform: 'rgba(0, 0, 0, 0.2)',
      progress: 'rgba(59, 130, 246, 0.8)',
      text: 'text-gray-700',
      button: 'bg-gray-100 hover:bg-gray-200 text-gray-700',
    }
  };

  /**
   * Gera uma forma de onda “aleatória” que simula o padrão de fala humana.
   */
  useEffect(() => {
    const numBars = 40; // Número de barrinhas que vamos desenhar
    const simulatedWave = Array(numBars).fill(0).map(() => {
      // Padrão sinusoidal simples, pra parecer voz
      const pos = Math.random();
      const centerEffect = Math.sin(pos * Math.PI);
      const randomVariation = 0.3 + Math.random() * 0.7;
      return centerEffect * randomVariation;
    });

    setWaveformData(simulatedWave);

    // Simula um loading rápido para o canvas
    const timer = setTimeout(() => {
      setIsLoaded(true);
    }, 300);

    return () => clearTimeout(timer);
  }, [src]);

  /**
   * Configura o elemento de áudio, attach de eventos.
   * Se temos propDuration, ignoramos metadados do <audio>.
   */
  useEffect(() => {
    if (!audioRef.current) return;
    const audio = audioRef.current;

    // Garante preload de metadados (para fallback)
    audio.preload = 'metadata';

    const handleLoadedMetadata = () => {
      console.log(`✅ AudioWaveform - Metadados carregados: duration=${audio.duration}`);

      // Se não temos propDuration, usamos a do <audio>.
      if (!propDuration) {
        if (audio.duration && !isNaN(audio.duration) && audio.duration !== Infinity) {
          setDuration(audio.duration);
        } else {
          console.warn('⚠️ AudioWaveform - Duração inválida, usando fallback 30 seg.');
          setDuration(30);
        }
      }

      setIsLoaded(true);
    };

    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime);
    };

    const handleEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
      audio.currentTime = 0;
    };

    const handleError = (e: Event) => {
      console.error('❌ AudioWaveform - Erro no <audio>:', audio.error);
      // Fallback de 30s, mas só se não tiver propDuration.
      if (!propDuration) setDuration(30);
      setIsLoaded(true);
    };

    // Se NÃO temos propDuration, ouvimos loadedmetadata para pegar fallback do <audio>.
    if (!propDuration) {
      audio.addEventListener('loadedmetadata', handleLoadedMetadata);
    }
    audio.addEventListener('timeupdate', handleTimeUpdate);
    audio.addEventListener('ended', handleEnded);
    audio.addEventListener('error', handleError);

    // Timeout caso o <audio> não carregue rápido
    const metadataTimeout = setTimeout(() => {
      if (
        !propDuration &&
        (audio.duration === Infinity || isNaN(audio.duration) || audio.duration === 0)
      ) {
        console.warn('⏰ Timeout: metadados não carregaram, usando fallback 30 seg.');
        setDuration(30);
        setIsLoaded(true);
      }
    }, 2000);

    return () => {
      if (!propDuration) {
        audio.removeEventListener('loadedmetadata', handleLoadedMetadata);
      }
      audio.removeEventListener('timeupdate', handleTimeUpdate);
      audio.removeEventListener('ended', handleEnded);
      audio.removeEventListener('error', handleError);
      clearTimeout(metadataTimeout);

      // Cancela animações pendentes
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [propDuration]);

  /**
   * Desenha a forma de onda no canvas sempre que currentTime ou duration mudarem.
   */
  useEffect(() => {
    if (!canvasRef.current || waveformData.length === 0 || !isLoaded) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Limpa a área antes de redesenhar
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Cálculos de tamanho das barras
    const barWidth = canvas.width / waveformData.length;
    const barSpacing = 2;
    const barWidthWithSpacing = barWidth - barSpacing;
    const maxBarHeight = canvas.height * 0.8;

    // Proporção de quanto do áudio já tocou
    const progressPosition = (currentTime / duration) * canvas.width;

    waveformData.forEach((value, index) => {
      const x = index * barWidth;
      const barHeight = value * maxBarHeight;
      const y = (canvas.height - barHeight) / 2;

      // Define se a barra já foi “tocada” (parte do progresso)
      const isPlayed = x < progressPosition;
      ctx.fillStyle = isPlayed
        ? colors[messageColor].progress
        : colors[messageColor].waveform;

      // Desenha barra com canto arredondado (roundRect)
      ctx.beginPath();
      (ctx as any).roundRect(x, y, barWidthWithSpacing, barHeight, 2);
      ctx.fill();
    });

    // Se está tocando, anima a cada frame
    if (isPlaying) {
      animationRef.current = requestAnimationFrame(() => {
        setCurrentTime(audioRef.current?.currentTime || 0);
      });
    }
  }, [waveformData, currentTime, duration, isPlaying, isLoaded, messageColor]);

  /**
   * Formata o tempo (em segundos) para MM:SS
   */
  const formatTime = (time: number) => {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  /**
   * Ao clicar no canvas, avança/retrocede o playback para a posição clicada.
   */
  const handleWaveformClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!audioRef.current || !isLoaded) return;

    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const clickRatio = x / rect.width;

    audioRef.current.currentTime = duration * clickRatio;
    setCurrentTime(duration * clickRatio);
  };

  /**
   * Inicia ou pausa a reprodução do áudio.
   */
  const togglePlay = () => {
    if (!audioRef.current || !isLoaded) return;

    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      audioRef.current.play();
      setIsPlaying(true);
    }
  };

  /**
   * Ativa/desativa o som (mute).
   */
  const toggleMute = () => {
    if (!audioRef.current) return;
    audioRef.current.muted = !isMuted;
    setIsMuted(!isMuted);
  };

  return (
    <div className={`relative w-full rounded-lg overflow-hidden ${className}`}>
      {/* Player de áudio “invisível” */}
      <audio ref={audioRef} src={src} className="hidden" preload="metadata" />

      <div className="flex items-center space-x-2 p-1">
        {/* Botão de reprodução/pausa */}
        <button
          onClick={togglePlay}
          disabled={!isLoaded}
          className={`p-2 rounded-full flex items-center justify-center transition-colors ${colors[messageColor].button}`}
        >
          {isPlaying ? <PauseIcon className="w-4 h-4" /> : <PlayIcon className="w-4 h-4" />}
        </button>

        {/* Área da forma de onda + timeline */}
        <div className="flex-1 space-y-1">
          <div className="relative w-full cursor-pointer">
            {!isLoaded ? (
              <div className="h-12 flex items-center justify-center">
                {/* Spinner de loading */}
                <div className="w-6 h-6 border-2 border-t-blue-500 border-r-transparent border-b-transparent border-l-transparent rounded-full animate-spin"></div>
              </div>
            ) : (
              <canvas
                ref={canvasRef}
                height={40}
                width={300}
                onClick={handleWaveformClick}
                className="w-full h-12"
              />
            )}
          </div>

          {/* Tempo: atual e total */}
          <div className="flex justify-between items-center">
            <span className={`text-xs ${colors[messageColor].text}`}>
              {formatTime(currentTime)}
            </span>
            <span className={`text-xs ${colors[messageColor].text}`}>
              {formatTime(duration)}
            </span>
          </div>
        </div>

        {/* Botão de mudo */}
        <button
          onClick={toggleMute}
          className={`p-2 rounded-full flex items-center justify-center transition-colors ${colors[messageColor].button}`}
        >
          {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );
};

export default AudioWaveform;
