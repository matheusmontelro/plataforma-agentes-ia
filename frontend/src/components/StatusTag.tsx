import React from 'react';
import { Calendar, CheckCircle2, XCircle, DollarSign, MessageSquare, Target, Users } from 'lucide-react';
import { PipelineResponse, PipelineStage } from '../services/api.ts';

interface StatusTagProps {
  status: string;
  pipelines: PipelineResponse[];
  className?: string;
}

const StatusTag: React.FC<StatusTagProps> = ({ status, pipelines, className = "" }) => {
  // Tentar encontrar o estágio nos pipelines carregados
  let stageConfig: PipelineStage | undefined;

  if (pipelines && pipelines.length > 0) {
    for (const pipeline of pipelines) {
      // Tenta encontrar por ID (se status for número) ou Nome
      const found = pipeline.stages.find(s =>
        s.id.toString() === status ||
        s.name.toLowerCase() === status.toLowerCase()
      );
      if (found) {
        stageConfig = found;
        break;
      }
    }
  }

  // Configuração de fallback (hardcoded) para compatibilidade ou se não carregar pipelines
  const fallbackConfig: any = {
    contato: { bgColor: 'bg-orange-100', textColor: 'text-orange-700', Icon: MessageSquare, label: 'Contato' },
    lead: { bgColor: 'bg-blue-100', textColor: 'text-blue-700', Icon: Target, label: 'Lead' },
    agendado: { bgColor: 'bg-yellow-100', textColor: 'text-yellow-700', Icon: Calendar, label: 'Agendado' },
    cliente: { bgColor: 'bg-purple-100', textColor: 'text-purple-700', Icon: Users, label: 'Cliente' },
    compareceu: { bgColor: 'bg-green-100', textColor: 'text-green-700', Icon: CheckCircle2, label: 'Compareceu' },
    faltou: { bgColor: 'bg-red-100', textColor: 'text-red-700', Icon: XCircle, label: 'Faltou' },
    venda: { bgColor: 'bg-emerald-100', textColor: 'text-emerald-700', Icon: DollarSign, label: 'Venda' }
  };

  // Se encontrou no pipeline dinâmico
  if (stageConfig) {
    // Mapear ícone baseado no nome ou usar um padrão
    let Icon = Target;
    const nameLower = stageConfig.name.toLowerCase();
    if (nameLower.includes('agend')) Icon = Calendar;
    else if (nameLower.includes('vend') || nameLower.includes('fatur')) Icon = DollarSign;
    else if (nameLower.includes('falt') || nameLower.includes('cancel')) Icon = XCircle;
    else if (nameLower.includes('compar')) Icon = CheckCircle2;
    else if (nameLower.includes('client')) Icon = Users;
    else if (nameLower.includes('contat')) Icon = MessageSquare;

    // Usar cor do estágio ou default
    let stageColor = stageConfig.color || '#3B82F6'; // Default Blue

    // Fix: Se a cor vier como classe Tailwind (ex: border-indigo-500) do legado
    if (stageColor.includes('border-') || stageColor.includes('bg-') || !stageColor.startsWith('#')) {
      // Map to 600/700 weights for better text contrast and distinctness
      const colorMap: { [key: string]: string } = {
        'indigo': '#4f46e5', // Indigo 600
        'orange': '#ea580c', // Orange 600
        'yellow': '#ca8a04', // Yellow 600 (Darker/Mustard)
        'purple': '#9333ea', // Purple 600
        'green': '#16a34a',  // Green 600
        'red': '#dc2626',    // Red 600
        'blue': '#2563eb',   // Blue 600
        'emerald': '#059669', // Emerald 600
        'sky': '#0284c7',    // Sky 600
        'cyan': '#0891b2',   // Cyan 600
        'teal': '#0d9488',   // Teal 600
        'lime': '#65a30d',   // Lime 600
        'amber': '#d97706',  // Amber 600
        'pink': '#db2777',   // Pink 600
        'rose': '#e11d48',   // Rose 600
        'slate': '#475569',  // Slate 600
        'gray': '#4b5563',   // Gray 600
        'zinc': '#52525b',   // Zinc 600
        'neutral': '#525252',// Neutral 600
        'stone': '#57534e',  // Stone 600
      };

      for (const [name, hex] of Object.entries(colorMap)) {
        if (stageColor.includes(name)) {
          stageColor = hex;
          break;
        }
      }

      // Se ainda não for hex válido após tentativa de correção, fallback para azul
      if (!stageColor.startsWith('#')) {
        stageColor = '#2563eb'; // Blue 600
      }
    }

    return (
      <span
        className={`rounded-full px-2 py-0.5 text-xs font-medium flex items-center ${className}`}
        style={{
          backgroundColor: `${stageColor}20`,
          color: stageColor
        }}
      >
        <Icon className="w-3 h-3 mr-1 flex-shrink-0" />
        <span className="truncate">{stageConfig.name}</span>
      </span>
    );
  }

  // Fallback para configuração antiga
  if (!status) return null;

  const normalizedStatus = status.toLowerCase();

  if (!(normalizedStatus in fallbackConfig)) return null;
  const currentConfig = fallbackConfig[normalizedStatus];

  return (
    <span className={`${currentConfig.bgColor} ${currentConfig.textColor} rounded-full px-2 py-0.5 text-xs font-medium flex items-center ${className}`}>
      <currentConfig.Icon className="w-3 h-3 mr-1 flex-shrink-0" />
      <span className="truncate">{currentConfig.label}</span>
    </span>
  );
};
export const BetaTag = ({ className = "" }: { className?: string }) => (
  <span className={`inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800 ${className}`}>
    BETA
  </span>
);

export const NewTag = ({ className = "" }: { className?: string }) => (
  <span className={`inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 ${className}`}>
    NOVO
  </span>
);

export default StatusTag;
