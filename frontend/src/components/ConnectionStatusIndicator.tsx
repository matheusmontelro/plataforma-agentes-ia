// src/components/ConnectionStatusIndicator.tsx
import React, { useState, useEffect } from 'react';
import { unifiedWebSocketManager } from '../services/api.ts';

interface ConnectionStatusIndicatorProps {
  showLabel?: boolean;
  className?: string;
}

export const ConnectionStatusIndicator: React.FC<ConnectionStatusIndicatorProps> = ({
  showLabel = true,
  className = ''
}) => {
  const [isConnected, setIsConnected] = useState<boolean>(unifiedWebSocketManager.isConnected());

  useEffect(() => {
    // Registra para receber atualizações de status
    const unsubscribe = unifiedWebSocketManager.onConnectionStatus(setIsConnected);

    return unsubscribe;
  }, []);

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className={`h-3 w-3 rounded-full ${
        isConnected ? 'bg-green-500' : 'bg-red-500 animate-pulse'
      }`}></div>

      {showLabel && (
        <span className="text-xs text-gray-500">
          {isConnected ? 'Conectado' : 'Reconectando...'}
        </span>
      )}
    </div>
  );
};