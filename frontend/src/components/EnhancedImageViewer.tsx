import React, { useState, useRef, useEffect } from 'react';
import { X, ZoomIn, ZoomOut, RotateCw, Download, Share, ChevronLeft, ChevronRight } from 'lucide-react';

interface EnhancedImageViewerProps {
  src: string;
  alt?: string;
  onClose: () => void;
  additionalImages?: string[];
  currentIndex?: number;
  onChangeImage?: (index: number) => void;
}

const EnhancedImageViewer: React.FC<EnhancedImageViewerProps> = ({
  src,
  alt = 'Imagem',
  onClose,
  additionalImages = [],
  currentIndex = 0,
  onChangeImage,
}) => {
  const [scale, setScale] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);

  // Combinar a imagem atual com quaisquer imagens adicionais
  const allImages = additionalImages.length > 0
    ? additionalImages
    : [src];

  const handleZoomIn = () => {
    setScale(prev => Math.min(prev + 0.25, 3));
  };

  const handleZoomOut = () => {
    setScale(prev => Math.max(prev - 0.25, 0.5));
  };

  const handleRotate = () => {
    setRotation(prev => (prev + 90) % 360);
  };

  const handleDownload = () => {
    const link = document.createElement('a');
    link.href = allImages[currentIndex];
    link.download = `imagem-${currentIndex + 1}.jpg`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleShare = async () => {
    if (navigator.share) {
      try {
        await navigator.share({
          title: alt,
          url: allImages[currentIndex]
        });
      } catch (error) {
        console.error('Erro ao compartilhar:', error);
      }
    } else {
      // Fallback para dispositivos que não suportam a API de compartilhamento
      navigator.clipboard.writeText(allImages[currentIndex])
        .then(() => alert('Link da imagem copiado para a área de transferência'))
        .catch(err => console.error('Erro ao copiar link:', err));
    }
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return; // Apenas botão esquerdo do mouse

    setIsDragging(true);
    setDragStart({
      x: e.clientX - position.x,
      y: e.clientY - position.y
    });

    e.preventDefault();
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDragging) return;

    setPosition({
      x: e.clientX - dragStart.x,
      y: e.clientY - dragStart.y
    });

    e.preventDefault();
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleTouchStart = (e: React.TouchEvent<HTMLDivElement>) => {
    if (e.touches.length !== 1) return;

    setIsDragging(true);
    setDragStart({
      x: e.touches[0].clientX - position.x,
      y: e.touches[0].clientY - position.y
    });
  };

  const handleTouchMove = (e: React.TouchEvent<HTMLDivElement>) => {
    if (!isDragging || e.touches.length !== 1) return;

    setPosition({
      x: e.touches[0].clientX - dragStart.x,
      y: e.touches[0].clientY - dragStart.y
    });

    e.preventDefault();
  };

  const handleTouchEnd = () => {
    setIsDragging(false);
  };

  const handleDoubleClick = () => {
    // Resetar o zoom e posição ao dar duplo clique
    if (scale !== 1) {
      setScale(1);
      setPosition({ x: 0, y: 0 });
    } else {
      setScale(2);
    }
  };

  const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (e.deltaY < 0) {
      handleZoomIn();
    } else {
      handleZoomOut();
    }
  };

  const handlePrevImage = () => {
    const newIndex = (currentIndex - 1 + allImages.length) % allImages.length;
    if (onChangeImage) {
      onChangeImage(newIndex);
    }
    // Resetar zoom e posição ao mudar de imagem
    setScale(1);
    setPosition({ x: 0, y: 0 });
    setRotation(0);
  };

  const handleNextImage = () => {
    const newIndex = (currentIndex + 1) % allImages.length;
    if (onChangeImage) {
      onChangeImage(newIndex);
    }
    // Resetar zoom e posição ao mudar de imagem
    setScale(1);
    setPosition({ x: 0, y: 0 });
    setRotation(0);
  };

  const handleImageLoad = () => {
    setLoading(false);
    setError(false);
  };

  const handleImageError = () => {
    setLoading(false);
    setError(true);
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'ArrowLeft') {
        handlePrevImage();
      } else if (e.key === 'ArrowRight') {
        handleNextImage();
      } else if (e.key === '+') {
        handleZoomIn();
      } else if (e.key === '-') {
        handleZoomOut();
      } else if (e.key === 'r') {
        handleRotate();
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    // Desativar scroll do corpo quando o visualizador está aberto
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'auto';
    };
  }, [currentIndex]);

  // Resetar o estado ao trocar de imagem
  useEffect(() => {
    setLoading(true);
    setError(false);
    setScale(1);
    setRotation(0);
    setPosition({ x: 0, y: 0 });
  }, [src]);

  return (
    <div className="fixed inset-0 z-50 bg-black/90 backdrop-blur-sm flex flex-col">
      {/* Barra superior */}
      <div className="flex items-center justify-between p-4 bg-gradient-to-b from-black/70 to-transparent">
        <div>
          {/* Contador de imagens se houver mais de uma */}
          {allImages.length > 1 && (
            <span className="text-white text-sm">
              {currentIndex + 1} / {allImages.length}
            </span>
          )}
        </div>

        <div className="flex gap-2">
          <button
            onClick={handleZoomOut}
            className="p-2 rounded-full text-white hover:bg-white/20 transition-colors"
            title="Diminuir zoom"
          >
            <ZoomOut size={20} />
          </button>
          <button
            onClick={handleZoomIn}
            className="p-2 rounded-full text-white hover:bg-white/20 transition-colors"
            title="Aumentar zoom"
          >
            <ZoomIn size={20} />
          </button>
          <button
            onClick={handleRotate}
            className="p-2 rounded-full text-white hover:bg-white/20 transition-colors"
            title="Rotacionar"
          >
            <RotateCw size={20} />
          </button>
          <button
            onClick={handleDownload}
            className="p-2 rounded-full text-white hover:bg-white/20 transition-colors"
            title="Download"
          >
            <Download size={20} />
          </button>
          <button
            onClick={handleShare}
            className="p-2 rounded-full text-white hover:bg-white/20 transition-colors"
            title="Compartilhar"
          >
            <Share size={20} />
          </button>
          <button
            onClick={onClose}
            className="p-2 rounded-full text-white bg-red-500/80 hover:bg-red-600 transition-colors ml-2"
            title="Fechar"
          >
            <X size={20} />
          </button>
        </div>
      </div>

      {/* Área da imagem */}
      <div
        ref={containerRef}
        className="flex-1 overflow-hidden relative flex items-center justify-center cursor-grab active:cursor-grabbing"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onDoubleClick={handleDoubleClick}
        onWheel={handleWheel}
      >
        {/* Navegação lateral */}
        {allImages.length > 1 && (
          <>
            <button
              onClick={handlePrevImage}
              className="absolute left-4 top-1/2 -translate-y-1/2 p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors z-10"
              title="Imagem anterior"
            >
              <ChevronLeft size={24} />
            </button>
            <button
              onClick={handleNextImage}
              className="absolute right-4 top-1/2 -translate-y-1/2 p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors z-10"
              title="Próxima imagem"
            >
              <ChevronRight size={24} />
            </button>
          </>
        )}

        {/* Estado de carregamento */}
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-12 h-12 rounded-full border-4 border-white/30 border-t-white animate-spin"></div>
          </div>
        )}

        {/* Estado de erro */}
        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-white">
            <div className="text-red-500 mb-2">
              <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="8" x2="12" y2="12"></line>
                <line x1="12" y1="16" x2="12.01" y2="16"></line>
              </svg>
            </div>
            <p>Erro ao carregar imagem</p>
          </div>
        )}

        {/* Imagem com transformações */}
        <img
          ref={imageRef}
          src={allImages[currentIndex]}
          alt={alt}
          className="max-h-full max-w-full object-contain transition-opacity"
          style={{
            transform: `translate(${position.x}px, ${position.y}px) scale(${scale}) rotate(${rotation}deg)`,
            opacity: loading || error ? 0 : 1,
            transition: isDragging ? 'none' : 'transform 0.2s ease-out'
          }}
          onLoad={handleImageLoad}
          onError={handleImageError}
          draggable="false"
        />
      </div>

      {/* Instruções de uso */}
      <div className="p-2 bg-gradient-to-t from-black/70 to-transparent text-center text-white/70 text-xs">
        Dica: Use a roda do mouse para zoom, duplo clique para expandir, clique e arraste para mover
      </div>

      {/* Miniaturas se houver múltiplas imagens */}
      {allImages.length > 1 && (
        <div className="flex p-2 gap-2 overflow-x-auto bg-black/80">
          {allImages.map((img, idx) => (
            <button
              key={idx}
              onClick={() => onChangeImage && onChangeImage(idx)}
              className={`relative flex-shrink-0 w-16 h-16 rounded overflow-hidden border-2 transition-all ${
                idx === currentIndex ? 'border-blue-500 scale-110' : 'border-transparent opacity-70 hover:opacity-100'
              }`}
            >
              <img
                src={img}
                alt={`Miniatura ${idx + 1}`}
                className="w-full h-full object-cover"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default EnhancedImageViewer;