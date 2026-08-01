// src/utils/useIntersectionObserver.ts
import { useEffect, useRef, useState } from 'react';

interface IntersectionObserverOptions {
  root?: Element | null;
  rootMargin?: string;
  threshold?: number | number[];
}

export const useIntersectionObserver = (
  options: IntersectionObserverOptions = {}
) => {
  const [isIntersecting, setIsIntersecting] = useState(false);
  const targetRef = useRef<Element | null>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  const setRef = (element: Element | null) => {
    if (targetRef.current) {
      // Limpa o observer atual
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    }

    targetRef.current = element;

    if (!element) {
      return;
    }

    // Cria um novo observer
    observerRef.current = new IntersectionObserver(([entry]) => {
      setIsIntersecting(entry.isIntersecting);
    }, options);

    observerRef.current.observe(element);
  };

  useEffect(() => {
    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, []);

  return { setRef, isIntersecting };
};