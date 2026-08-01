// src/components/LazyImage.tsx
import React, { useState, useEffect } from 'react';
import { useIntersectionObserver } from '../utils/useIntersectionObserver.ts';

interface LazyImageProps {
  src: string;
  alt: string;
  className?: string;
  onError?: (e: React.SyntheticEvent<HTMLImageElement, Event>) => void;
  placeholderClassName?: string;
}

export const LazyImage: React.FC<LazyImageProps> = ({
  src,
  alt,
  className = '',
  onError,
  placeholderClassName = 'bg-gray-200 animate-pulse'
}) => {
  const [isLoaded, setIsLoaded] = useState(false);
  const [actualSrc, setActualSrc] = useState('');
  const { setRef, isIntersecting } = useIntersectionObserver({
    threshold: 0.1,
    rootMargin: '200px' // Carrega imagens quando estão a 200px da viewport
  });

  useEffect(() => {
    if (isIntersecting && !actualSrc) {
      setActualSrc(src);
    }
  }, [isIntersecting, src, actualSrc]);

  const handleLoad = () => {
    setIsLoaded(true);
  };

  const handleError = (e: React.SyntheticEvent<HTMLImageElement, Event>) => {
    if (onError) {
      onError(e);
    }
  };

  return (
    <div
      ref={setRef as any}
      className={`relative overflow-hidden ${className}`}
    >
      {(!isLoaded || !actualSrc) && (
        <div className={`absolute inset-0 ${placeholderClassName}`}></div>
      )}
      {actualSrc && (
        <img
          src={actualSrc}
          alt={alt}
          className={`w-full h-full object-cover transition-opacity duration-300 ${isLoaded ? 'opacity-100' : 'opacity-0'}`}
          onLoad={handleLoad}
          onError={handleError}
        />
      )}
    </div>
  );
};