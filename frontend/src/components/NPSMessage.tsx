import React from 'react';
import { NPSMessageData } from '../services/api.ts';

interface NPSMessageProps {
  npsData: NPSMessageData;
  isOwn: boolean;
  timestamp: string;
}

export const NPSMessage: React.FC<NPSMessageProps> = ({ npsData, isOwn, timestamp }) => {
  const formatTime = (timestamp: string) => {
    if (!timestamp) return '';
    const parts = timestamp.split(':');
    if (parts.length >= 2) {
      return `${parts[0]}:${parts[1]}`;
    }
    return timestamp;
  };

  const pollOptions = [
    { id: 1, label: '1 ⭐', emoji: '⭐' },
    { id: 2, label: '2 ⭐⭐', emoji: '⭐⭐' },
    { id: 3, label: '3 ⭐⭐⭐', emoji: '⭐⭐⭐' },
    { id: 4, label: '4 ⭐⭐⭐⭐', emoji: '⭐⭐⭐⭐' },
    { id: 5, label: '5 ⭐⭐⭐⭐⭐', emoji: '⭐⭐⭐⭐⭐' }
  ];

  const isAnswered = npsData.status === 'answered' && npsData.score !== undefined;
  const selectedOption = isAnswered ? pollOptions.find(opt => opt.id === npsData.score) : null;

  return (
    <div className={`rounded-lg p-0 max-w-[280px] ${
      isOwn ? 'bg-green-500' : 'bg-white'
    } shadow-sm border ${isOwn ? 'border-green-600' : 'border-gray-200'}`}>

      {/* Cabeçalho da enquete - estilo WhatsApp */}
      <div className={`px-3 py-2 ${
        isOwn ? 'bg-green-600' : 'bg-gray-50'
      } rounded-t-lg border-b ${isOwn ? 'border-green-700' : 'border-gray-200'}`}>
        <div className="flex items-center space-x-2">
          <span className="text-sm">📊</span>
          <span className={`text-sm font-medium ${
            isOwn ? 'text-white' : 'text-gray-700'
          }`}>
            ENQUETE
          </span>
        </div>
      </div>

      {/* Conteúdo da enquete */}
      <div className="px-3 py-3">
        {/* Pergunta */}
        <p className={`text-sm mb-3 ${
          isOwn ? 'text-white' : 'text-gray-900'
        }`}>
          {npsData.question}
        </p>

        {/* Opções da enquete */}
        <div className="space-y-1">
          {pollOptions.map((option) => {
            const isSelected = selectedOption?.id === option.id;
            const showVotes = isAnswered;

            return (
              <div
                key={option.id}
                className={`flex items-center justify-between p-2 rounded-md border transition-all ${
                  isSelected
                    ? (isOwn ? 'bg-green-400 border-green-300' : 'bg-green-100 border-green-300')
                    : (isOwn ? 'bg-green-400/20 border-green-400/30' : 'bg-gray-50 border-gray-200')
                } ${showVotes ? '' : 'hover:bg-opacity-80'}`}
              >
                <div className="flex items-center space-x-2">
                  <span className={`text-sm ${
                    isOwn ? 'text-white' : 'text-gray-900'
                  }`}>
                    {option.label}
                  </span>
                  {isSelected && (
                    <span className="text-xs">✓</span>
                  )}
                </div>

                {/* Porcentagem de votos (simulada) */}
                {showVotes && (
                  <div className="flex items-center space-x-1">
                    <div className={`h-1 w-8 rounded-full ${
                      isSelected
                        ? (isOwn ? 'bg-white' : 'bg-green-500')
                        : (isOwn ? 'bg-green-300' : 'bg-gray-300')
                    }`} />
                    <span className={`text-xs ${
                      isOwn ? 'text-white' : 'text-gray-600'
                    }`}>
                      {isSelected ? '100%' : '0%'}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Status e informações */}
        {isAnswered ? (
          <div className={`mt-3 text-xs ${
            isOwn ? 'text-green-100' : 'text-gray-500'
          }`}>
            ✓ Respondido: {selectedOption?.label}
          </div>
        ) : (
          <div className={`mt-3 text-xs ${
            isOwn ? 'text-green-100' : 'text-gray-500'
          }`}>
            Aguardando resposta do cliente
          </div>
        )}
      </div>

      {/* Timestamp */}
      <div className="px-3 pb-2">
        <div className="flex justify-end">
          <span className={`text-xs ${
            isOwn ? 'text-green-100' : 'text-gray-400'
          }`}>
            {formatTime(timestamp)}
          </span>
        </div>
      </div>
    </div>
  );
};