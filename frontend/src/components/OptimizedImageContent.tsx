import React, { useState, useEffect } from 'react';
import { ZoomIn, AlertCircle } from 'lucide-react';
import EnhancedImageViewer from './EnhancedImageViewer.tsx';
import api from '../services/api.ts';

interface ImageContentProps {
  src: string;
  mediaPath?: string;
  needsLoading?: boolean;
  alt?: string;
  className?: string;
  isOwn?: boolean;
}

const OptimizedImageContent: React.FC<ImageContentProps> = ({
  src,
  mediaPath,
  needsLoading = false,
  alt = 'Imagem',
  className = '',
  isOwn = false,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [actualSrc, setActualSrc] = useState('');
  const [loadAttempts, setLoadAttempts] = useState(0);
  const maxAttempts = 2;

  // Determinar se o conteúdo é base64
  const isBase64 = src && (src.startsWith('data:image/') || src.startsWith('data:video/'));

  // Efeito para determinar a fonte inicial da imagem
  useEffect(() => {
    if (isBase64) {
      // Se for base64, usa diretamente
      setActualSrc(src);
      setImageLoaded(true);
    } else if (!needsLoading) {
      // Se não precisa carregar e não é base64, usa a URL direta
      setActualSrc(src);
    } else if (src) {
      // Se tem src mas precisa carregar, possivelmente é uma URL relativa
      setActualSrc(src);
    }
    // Se needsLoading é true e mediaPath existe, o outro useEffect cuidará disso
  }, [src, isBase64, needsLoading]);

  // Efeito para carregar a mídia se necessário
  useEffect(() => {
    if (isBase64 || !needsLoading || !mediaPath || loadAttempts >= maxAttempts) return;

    let isMounted = true;

    const loadMedia = async () => {
      try {
        // Obter referências do localStorage
        const clientId = localStorage.getItem('client_id');
        const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

        if (!clientId || !companyId) {
          throw new Error('Client ID ou Company ID não encontrados');
        }

        // Construir a URL correta
        let mediaUrl = '';

        // Verificar se o mediaPath já tem o formato client_X/company_Y/caminho
        const pathMatch = mediaPath.match(/^client_(\d+)\/company_(\d+)\/(.+)$/);
        let fileName = '';
        let urlClientId = clientId;
        let urlCompanyId = companyId;

        if (pathMatch) {
          // Extrair os componentes numéricos do caminho
          const [_, pathClientId, pathCompanyId, actualPath] = pathMatch;
          urlClientId = pathClientId;
          urlCompanyId = pathCompanyId;
          fileName = actualPath;
          console.log(`Caminho extraído do padrão: client_${pathClientId}/company_${pathCompanyId}/${actualPath}`);
        } else if (!mediaPath.startsWith(`client_${clientId}/company_${companyId}/`)) {
          // Se não tem o prefixo e não é um caminho completo, usar os IDs do localStorage
          fileName = mediaPath;
          console.log(`Caminho construído com IDs do localStorage: ${clientId}/${companyId}/${mediaPath}`);
        } else {
          // Caso inesperado, tentar uma abordagem direta
          console.warn(`Formato de caminho não reconhecido: ${mediaPath}`);
          throw new Error('Formato de caminho não reconhecido');
        }

        console.log(`Tentando carregar mídia com o endpoint correto: /arquivos/files/view/${urlCompanyId}/${urlClientId}/${fileName}`);

        // Usar api.get com responseType: 'blob' para obter o arquivo usando o endpoint correto
        const response = await api.get(`/arquivos/files/view/${urlCompanyId}/${urlClientId}/${fileName}`, {
          responseType: 'blob',
          timeout: 15000
        });

        if (!response.data) {
          throw new Error('Resposta vazia');
        }

        // Criar URL do blob
        if (isMounted) {
          const responseContentType = response.headers['content-type'];
          const contentType = typeof responseContentType === 'string' ? responseContentType : 'image/jpeg';
          const blob = new Blob([response.data], { type: contentType });
          const blobUrl = URL.createObjectURL(blob);
          setActualSrc(blobUrl);
          setImageLoaded(true);
          console.log(`Mídia carregada com sucesso: ${mediaPath}`);
        }
      } catch (error) {
        console.error(`Erro ao carregar mídia ${mediaPath}:`, error);

        // Tentativa alternativa: tentar carregar diretamente pela URL absoluta
        if (isMounted && loadAttempts === 0) {
          try {
            console.log("Tentando abordagem alternativa com URL absoluta");
            const absoluteUrl = `${window.location.origin}/${mediaPath}`;
            const response = await fetch(absoluteUrl);

            if (response.ok) {
              const blob = await response.blob();
              const blobUrl = URL.createObjectURL(blob);
              setActualSrc(blobUrl);
              setImageLoaded(true);
              console.log(`Mídia carregada com sucesso via URL absoluta: ${absoluteUrl}`);
              return;
            }
          } catch (altError) {
            console.error("Falha na abordagem alternativa:", altError);
          }
        }

        if (isMounted) {
          const newAttempts = loadAttempts + 1;
          setLoadAttempts(newAttempts);

          if (newAttempts >= maxAttempts) {
            setImageError(true);
          }
        }
      }
    };

    loadMedia();

    return () => {
      isMounted = false;
    };
  }, [needsLoading, mediaPath, loadAttempts, isBase64]);

  const handleImageLoad = () => {
    setImageLoaded(true);
    setImageError(false);
  };

  const handleImageError = () => {
    console.error(`Erro ao carregar imagem ${actualSrc}`);

    // Se já tentamos várias abordagens e ainda falhou, marcar como erro
    if (loadAttempts >= maxAttempts) {
      setImageError(true);
      return;
    }

    // Tentar outra abordagem
    const newAttempts = loadAttempts + 1;
    setLoadAttempts(newAttempts);
  };

  const openImage = () => {
    if (imageLoaded && !imageError) {
      setIsExpanded(true);
    }
  };

  const closeImage = () => {
    setIsExpanded(false);
  };

  // Limpar URL do objeto ao desmontar componente
  useEffect(() => {
    return () => {
      if (actualSrc && actualSrc.startsWith('blob:')) {
        URL.revokeObjectURL(actualSrc);
      }
    };
  }, [actualSrc]);

  return (
    <>
      <div
        className={`relative rounded-lg overflow-hidden group ${className} ${
          isOwn ? 'bg-blue-500 p-1' : 'bg-white p-1'
        }`}
      >
        {/* Esqueleto de carregamento */}
        {!isBase64 && (!imageLoaded && !imageError) && (
          <div className="absolute inset-0 bg-gray-200 animate-pulse flex items-center justify-center">
            <div className="w-8 h-8 border-4 border-gray-300 border-t-blue-500 rounded-full animate-spin"></div>
          </div>
        )}

        {/* Indicador de erro */}
        {imageError && (
          <div className="absolute inset-0 bg-gray-100 flex flex-col items-center justify-center text-red-500 p-4">
            <AlertCircle className="mb-2" />
            <span className="text-xs text-center">Não foi possível carregar a imagem</span>
          </div>
        )}

        {/* Imagem ou conteúdo vazio enquanto carrega */}
        {actualSrc ? (
          <img
            src={actualSrc}
            alt={alt}
            className={`max-w-full max-h-64 rounded object-contain transition-opacity ${
              imageLoaded || isBase64 ? 'opacity-100' : 'opacity-0'
            }`}
            onLoad={handleImageLoad}
            onError={handleImageError}
            loading="lazy"
          />
        ) : (
          <div className="w-full h-48 flex items-center justify-center">
            {!imageError && <span className="text-gray-400 text-sm">Carregando...</span>}
          </div>
        )}

        {/* Botão de expandir */}
        {(imageLoaded || isBase64) && !imageError && (
          <button
            onClick={openImage}
            className="absolute top-2 right-2 p-1.5 bg-black/60 hover:bg-black/80 rounded-full text-white opacity-0 group-hover:opacity-100 transition-opacity"
            title="Ampliar imagem"
            aria-label="Ampliar imagem"
          >
            <ZoomIn size={16} />
          </button>
        )}
      </div>

      {/* Visualizador expandido */}
      {isExpanded && (
        <EnhancedImageViewer
          src={actualSrc}
          alt={alt}
          onClose={closeImage}
        />
      )}
    </>
  );
};

export default OptimizedImageContent;
