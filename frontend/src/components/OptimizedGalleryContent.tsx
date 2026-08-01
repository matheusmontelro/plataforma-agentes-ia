import React, { useState, useEffect } from 'react';
import { ZoomIn, Image as ImageIcon } from 'lucide-react';
import EnhancedImageViewer from './EnhancedImageViewer.tsx';

interface GalleryContentProps {
  images: string[];
  isOwn?: boolean;
  maxPreview?: number;
}

const OptimizedGalleryContent: React.FC<GalleryContentProps> = ({
  images,
  isOwn = false,
  maxPreview = 4,
}) => {
  const [openedIndex, setOpenedIndex] = useState<number | null>(null);
  const [imageErrors, setImageErrors] = useState<Record<number, boolean>>({});
  const [validImages, setValidImages] = useState<string[]>([]);
  const [attemptedRetries, setAttemptedRetries] = useState<Record<number, boolean>>({});

  // Validar as imagens ao montar o componente ou quando a prop images mudar
  useEffect(() => {
    // Filtrar apenas URLs válidas
    const filtered = images.filter(img =>
      img && typeof img === 'string' && img.trim().length > 0
    );
    setValidImages(filtered);
    // Resetar os erros quando as imagens mudarem
    setImageErrors({});
    setAttemptedRetries({});
  }, [images]);

  const handleImageError = (index: number) => {
    // Verifica se já tentamos carregar esta imagem de outra forma
    if (attemptedRetries[index]) {
      // Se já tentamos, marcamos como erro definitivo
      setImageErrors(prev => ({...prev, [index]: true}));
      console.error(`Falha definitiva ao carregar imagem: ${validImages[index]}`);
    } else {
      // Se ainda não tentamos, marcamos como tentado
      setAttemptedRetries(prev => ({...prev, [index]: true}));

      // Tenta carregar a imagem de outra forma
      // Por exemplo, você poderia tentar adicionar um prefixo ou sufixo à URL
      // ou fazer alguma transformação específica para seu caso

      // Aqui estamos apenas registrando que tentamos, a lógica real dependeria
      // de como suas imagens são organizadas
      console.warn(`Primeira falha ao carregar imagem: ${validImages[index]}, tentando alternativa...`);

      // Se tiver uma lógica alternativa para URL, aplicaria aqui
      // Por exemplo:
      // const newImages = [...validImages];
      // newImages[index] = newImages[index] + '?retry=true'; // ou outra transformação
      // setValidImages(newImages);
    }
  };

  const isBase64Image = (src: string): boolean => {
    return Boolean(src && (src.startsWith('data:image/') || src.startsWith('data:video/')));
  };

  const openImage = (index: number) => {
    if (!imageErrors[index]) {
      setOpenedIndex(index);
    }
  };

  const closeImage = () => {
    setOpenedIndex(null);
  };

  const handleChangeImage = (newIndex: number) => {
    setOpenedIndex(newIndex);
  };

  // Limitar a pré-visualização ao número máximo definido
  const displayImages = validImages.slice(0, maxPreview);
  const remainingCount = Math.max(0, validImages.length - maxPreview);

  // Verificar se há pelo menos uma imagem válida para exibir
  if (displayImages.length === 0) {
    return (
      <div className="rounded-lg overflow-hidden p-4 bg-gray-100 text-center">
        <ImageIcon size={24} className="mx-auto mb-2 text-gray-400" />
        <p className="text-gray-500">Sem imagens disponíveis</p>
      </div>
    );
  }

  return (
    <>
      <div className={`rounded-lg overflow-hidden p-1 ${isOwn ? 'bg-blue-500' : 'bg-white'}`}>
        <div className={`grid gap-1 ${
          displayImages.length === 1 ? 'grid-cols-1' :
          displayImages.length === 2 ? 'grid-cols-2' :
          displayImages.length >= 3 ? 'grid-cols-2' : ''
        }`}>
          {displayImages.map((src, index) => {
            // Verifica se é base64 para tratamento especial
            const isBase64 = isBase64Image(src);

            return (
              <div
                key={index}
                className={`relative overflow-hidden rounded
                  ${index === 0 && displayImages.length === 3 ? 'row-span-2' : ''}
                  ${index === 0 && displayImages.length >= 4 ? 'col-span-2' : ''}
                `}
                style={{
                  aspectRatio: index === 0 ? '1/1' : '1/1',
                  maxHeight: index === 0 ? '240px' : '120px'
                }}
              >
                {/* Renderização condicional baseada no estado de erro */}
                {!imageErrors[index] ? (
                  <img
                    src={src}
                    alt={`Imagem ${index + 1}`}
                    className="w-full h-full object-cover transition-transform hover:scale-105"
                    onClick={() => openImage(index)}
                    onError={() => handleImageError(index)}
                    loading="lazy"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center bg-gray-200">
                    <ImageIcon size={24} className="text-gray-400" />
                  </div>
                )}

                {/* Overlay para última imagem exibindo número de imagens restantes */}
                {index === displayImages.length - 1 && remainingCount > 0 && (
                  <div
                    className="absolute inset-0 bg-black/60 flex items-center justify-center text-white cursor-pointer"
                    onClick={() => openImage(index)}
                  >
                    <div className="flex flex-col items-center">
                      <ImageIcon size={24} className="mb-1" />
                      <span className="text-xl font-bold">+{remainingCount}</span>
                    </div>
                  </div>
                )}

                {/* Botão de zoom - só mostrar se a imagem carregou corretamente */}
                {!imageErrors[index] && (
                  <button
                    onClick={() => openImage(index)}
                    className="absolute top-2 right-2 p-1.5 bg-black/60 hover:bg-black/80 rounded-full text-white opacity-0 hover:opacity-100 transition-opacity"
                    title="Ampliar imagem"
                  >
                    <ZoomIn size={16} />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Visualizador expandido - só mostrar para imagens válidas */}
      {openedIndex !== null && !imageErrors[openedIndex] && (
        <EnhancedImageViewer
          src={validImages[openedIndex]}
          alt={`Imagem ${openedIndex + 1}`}
          onClose={closeImage}
          additionalImages={validImages.filter((_, idx) => !imageErrors[idx])}
          currentIndex={openedIndex}
          onChangeImage={handleChangeImage}
        />
      )}
    </>
  );
};

export default OptimizedGalleryContent;