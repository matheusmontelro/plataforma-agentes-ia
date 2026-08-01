import React, { useState, useRef, useEffect } from 'react';
import { Mic, StopCircle, PauseCircle, PlayCircle, Send, X } from 'lucide-react';

interface AudioRecorderProps {
  /**
   * Recebe o Blob final do áudio e a duração gravada (em segundos).
   */
  onAudioRecorded: (audioBlob: Blob, durationSeconds: number) => void;
}

enum RecordingState {
  IDLE = 'idle',
  RECORDING = 'recording',
  PAUSED = 'paused',
  COMPLETED = 'completed'
}

const AudioRecorder: React.FC<AudioRecorderProps> = ({ onAudioRecorded }) => {
  const [recordingState, setRecordingState] = useState<RecordingState>(RecordingState.IDLE);

  // Em vez de armazenar segundos num timer, vamos guardar a diferença de tempo real
  const [recordedDuration, setRecordedDuration] = useState(0);

  const [audioLevel, setAudioLevel] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  // Guardamos o momento (ms) que a gravação começou
  const startTimeRef = useRef<number | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioBlobRef = useRef<Blob | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanupResources();
    };
  }, []);

  const cleanupResources = () => {
    if (animationFrameRef.current) {
      window.cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close();
      audioContextRef.current = null;
      analyserRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
  };

  const startRecording = async () => {
    try {
      // Se já temos um áudio completo, resetamos tudo
      if (recordingState === RecordingState.COMPLETED) {
        audioBlobRef.current = null;
        audioChunksRef.current = [];
        setRecordedDuration(0);
      }

      // Marca o "startTime" para calcular a duração real ao parar
      startTimeRef.current = Date.now();

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });

      streamRef.current = stream;
      setupAudioAnalysis(stream);

      let mimeType = 'audio/mp4';
      const mimeTypes = [
        'audio/webm;codecs=opus',
        'audio/ogg;codecs=opus',
        'audio/ogg',
        'audio/mp4'
      ];
      for (const type of mimeTypes) {
        if (MediaRecorder.isTypeSupported(type)) {
          mimeType = type;
          console.log(`Usando formato de áudio: ${mimeType}`);
          break;
        }
      }

      const options = {
        mimeType,
        audioBitsPerSecond: 128000
      };

      const mediaRecorder = new MediaRecorder(stream, options);
      mediaRecorderRef.current = mediaRecorder;

      // Se não estivermos apenas resumindo, limpamos os chunks
      if (recordingState !== RecordingState.PAUSED) {
        audioChunksRef.current = [];
      }

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
          console.log(`Chunk de áudio recebido: ${event.data.size} bytes`);
        }
      };

      mediaRecorder.onstop = () => {
        console.log('MediaRecorder parou, processando chunks de áudio...');
        processAudioChunks(mimeType);
      };

      mediaRecorder.start(1000);
      console.log('Gravação iniciada/continuada');
      setRecordingState(RecordingState.RECORDING);

    } catch (error) {
      console.error('Erro ao iniciar gravação:', error);
      alert('Não foi possível acessar o microfone. Verifique as permissões do navegador.');
    }
  };

  const pauseRecording = () => {
    if (mediaRecorderRef.current && recordingState === RecordingState.RECORDING) {
      mediaRecorderRef.current.stop();
      setRecordingState(RecordingState.PAUSED);

      // Não limpamos "startTimeRef.current" aqui,
      // pois na regravação somamos novos chunks
      // e definimos novamente no `startRecording`.
    }
  };

  const resumeRecording = () => {
    if (streamRef.current && recordingState === RecordingState.PAUSED) {
      startRecording();
    }
  };

  const stopRecording = () => {
    if (recordingState === RecordingState.RECORDING || recordingState === RecordingState.PAUSED) {
      console.log(`Parando gravação a partir do estado: ${recordingState}`);
      setRecordingState(RecordingState.COMPLETED);

      if (recordingState === RecordingState.RECORDING && mediaRecorderRef.current) {
        mediaRecorderRef.current.stop();
      } else if (recordingState === RecordingState.PAUSED) {
        const mimeType = mediaRecorderRef.current?.mimeType || 'audio/mp4';
        processAudioChunks(mimeType);
      }
    }
  };

  const cancelRecording = () => {
    cleanupResources();
    audioChunksRef.current = [];
    audioBlobRef.current = null;
    setRecordedDuration(0);
    setAudioLevel(0);
    setRecordingState(RecordingState.IDLE);
  };

  /**
   * Ao enviar o áudio (clicar no ícone de “send”),
   * passamos o blob + a duração total ao componente-pai.
   */
  const sendAudio = () => {
    if (audioBlobRef.current) {
      console.log("Duração final:", recordedDuration, "segundos");
      onAudioRecorded(audioBlobRef.current, recordedDuration);
      cancelRecording();
    }
  };

  const processAudioChunks = (mimeType: string) => {
    console.log('Processando chunks de áudio...', {
      estado: recordingState,
      chunks: audioChunksRef.current.length
    });

    if (audioChunksRef.current.length > 0) {
      const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
      audioBlobRef.current = audioBlob;
      console.log(`Áudio gravado: ${audioBlob.size} bytes, tipo: ${audioBlob.type}`);

      // Calcula a duração real em segundos com base no tempo decorrido.
      if (startTimeRef.current) {
        const endTime = Date.now();
        const seconds = (endTime - startTimeRef.current) / 1000;
        setRecordedDuration(seconds);
      }
    } else {
      console.warn('Nenhum chunk de áudio para processar');
    }

    if (recordingState !== RecordingState.PAUSED) {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
      if (animationFrameRef.current) {
        window.cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      if (audioContextRef.current) {
        audioContextRef.current.close();
        audioContextRef.current = null;
        analyserRef.current = null;
      }
    }
  };

  const setupAudioAnalysis = (stream: MediaStream) => {
    try {
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close();
      }
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyserRef.current = analyser;
      analyser.fftSize = 256;
      source.connect(analyser);

      const analyzeAudio = () => {
        if (!analyserRef.current) return;
        const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(dataArray);

        const average = dataArray.reduce((sum, value) => sum + value, 0) / dataArray.length;
        const normalizedLevel = Math.min(average / 128, 1);
        setAudioLevel(normalizedLevel);

        animationFrameRef.current = window.requestAnimationFrame(analyzeAudio);
      };
      analyzeAudio();
    } catch (error) {
      console.error('Erro ao configurar análise de áudio:', error);
    }
  };

  // Formata o tempo como MM:SS
  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  };

  // Exemplo de “barrinhas” animadas
  const renderAudioLevelBars = () => {
    const bars: React.ReactNode[] = [];
    const numBars = 5;
    for (let i = 0; i < numBars; i++) {
      const threshold = i / numBars;
      const active = audioLevel >= threshold && recordingState === RecordingState.RECORDING;
      bars.push(
        <div
          key={i}
          className={`w-1 mx-px rounded-full transition-all duration-100 ${
            active ? 'bg-red-500' : 'bg-gray-300'
          }`}
          style={{
            height: `${(i + 1) * 3}px`,
            opacity: active ? 1 : 0.5
          }}
        />
      );
    }
    return <div className="flex items-end justify-center space-x-px">{bars}</div>;
  };

  const renderControls = () => {
    switch (recordingState) {
      case RecordingState.IDLE:
        return (
          <button
            onClick={startRecording}
            className="p-2 hover:bg-gray-100 hover:text-blue-500 rounded-full transition-colors flex items-center justify-center"
            title="Gravar áudio"
          >
            <Mic className="h-5 w-5 text-gray-500" />
          </button>
        );

      case RecordingState.RECORDING:
        return (
          <div className="flex items-center gap-2 bg-red-50 rounded-full pl-2 pr-3 py-1 border border-red-200">
            <div className="flex items-center">
              <button
                onClick={pauseRecording}
                className="p-1.5 bg-red-500 hover:bg-red-600 text-white rounded-full flex items-center justify-center transition-colors"
                title="Pausar gravação"
              >
                <PauseCircle className="h-4 w-4" />
              </button>
            </div>
            <div className="flex flex-col items-center mx-1">
              {renderAudioLevelBars()}
            </div>
            {/* Exibe o tempo decorrido neste momento */}
            <span className="text-xs font-medium text-red-500 min-w-[40px]">
              {formatTime((Date.now() - (startTimeRef.current || Date.now())) / 1000)}
            </span>
            <div className="flex items-center space-x-1">
              <button
                onClick={stopRecording}
                className="p-1 hover:bg-red-100 text-red-500 rounded-full flex items-center justify-center transition-colors"
                title="Finalizar gravação"
              >
                <StopCircle className="h-4 w-4" />
              </button>
              <button
                onClick={cancelRecording}
                className="p-1 hover:bg-gray-100 text-gray-500 rounded-full flex items-center justify-center transition-colors"
                title="Cancelar gravação"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        );

      case RecordingState.PAUSED:
        return (
          <div className="flex items-center gap-2 bg-yellow-50 rounded-full pl-2 pr-3 py-1 border border-yellow-200">
            <div className="flex items-center">
              <button
                onClick={resumeRecording}
                className="p-1.5 bg-yellow-500 hover:bg-yellow-600 text-white rounded-full flex items-center justify-center transition-colors"
                title="Continuar gravação"
              >
                <PlayCircle className="h-4 w-4" />
              </button>
            </div>
            <span className="text-xs font-medium text-yellow-700 min-w-[40px]">
              {formatTime(recordedDuration)}
            </span>
            <div className="flex items-center space-x-1">
              <button
                onClick={stopRecording}
                className="p-1 hover:bg-yellow-100 text-yellow-700 rounded-full flex items-center justify-center transition-colors"
                title="Finalizar gravação"
              >
                <StopCircle className="h-4 w-4" />
              </button>
              <button
                onClick={cancelRecording}
                className="p-1 hover:bg-gray-100 text-gray-500 rounded-full flex items-center justify-center transition-colors"
                title="Cancelar gravação"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        );

      case RecordingState.COMPLETED:
        return (
          <div className="flex items-center gap-2 bg-green-50 rounded-full pl-3 pr-3 py-1 border border-green-200">
            <span className="text-xs font-medium text-green-700 min-w-[40px]">
              {formatTime(recordedDuration)}
            </span>
            <div className="flex items-center space-x-1">
              <button
                onClick={sendAudio}
                className="p-1.5 bg-green-500 hover:bg-green-600 text-white rounded-full flex items-center justify-center transition-colors"
                title="Enviar áudio"
              >
                <Send className="h-4 w-4" />
              </button>
              <button
                onClick={cancelRecording}
                className="p-1 hover:bg-gray-100 text-gray-500 rounded-full flex items-center justify-center transition-colors"
                title="Cancelar"
              >
                <X className="h-4 w-4" />
              </button>
              <button
                onClick={startRecording}
                className="p-1 hover:bg-green-100 text-green-700 rounded-full flex items-center justify-center transition-colors"
                title="Nova gravação"
              >
                <Mic className="h-4 w-4" />
              </button>
            </div>
          </div>
        );
    }
  };

  return (
    <div className="relative">
      {renderControls()}
    </div>
  );
};

export default AudioRecorder;
