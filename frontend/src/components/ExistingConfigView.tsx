import React, { useEffect, useState } from 'react';
import { getAgentConfig, deleteAgentConfig } from '../services/api.ts';
import {
  Users,
  MapPin,
  Calendar,
  DollarSign,
  MessageSquare,
  Edit2,
  Trash2,
  CheckCircle,
  AlertCircle,
  Loader,
  Bot,
  Building,
  Phone,
  Globe,
  Clock
} from 'lucide-react';

interface ConfigData {
  assistant_identity?: any;
  company_info?: any;
  team_and_specialties?: any;
  scheduling_config?: any;
  financial_config?: any;
  conversation_flow?: any;
}

interface ExistingConfigViewProps {
  onReset: () => void;
  onUpdate: (newAssistantName: string) => void;
}

const ConfigCard = ({ title, icon: Icon, children }: { title: string; icon: any; children: React.ReactNode }) => (
  <div className="bg-white p-5 rounded-lg border border-gray-200 shadow-sm transition-all duration-200 hover:shadow-md">
    <div className="flex items-center gap-3 mb-4 pb-3 border-b border-gray-100">
      <div className="p-2 rounded-lg bg-indigo-50 text-indigo-600">
        <Icon className="w-5 h-5" />
      </div>
      <h2 className="text-lg font-medium text-gray-800">{title}</h2>
    </div>
    <div className="space-y-2">{children}</div>
  </div>
);

const InfoRow = ({ label, value }: { label: string; value: string | number | boolean | undefined }) => {
  if (value === undefined || value === '') return null;

  // Truncate long values
  const displayValue = typeof value === 'string' && value.length > 100
    ? value.substring(0, 100) + '...'
    : String(value);

  return (
    <div className="flex flex-col sm:flex-row sm:items-start py-2 border-b border-gray-100 last:border-0">
      <span className="text-sm font-medium text-gray-600 sm:w-1/3 mb-1 sm:mb-0">{label}</span>
      <span className="text-sm text-gray-800 sm:w-2/3">{displayValue}</span>
    </div>
  );
};

const ExistingConfigView: React.FC<ExistingConfigViewProps> = ({ onReset, onUpdate }) => {
  const [configData, setConfigData] = useState<ConfigData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const data = await getAgentConfig();
        setConfigData(data);
      } catch (err: any) {
        console.error("Erro ao obter config existente:", err.message);
        setError(err.message || "Erro ao obter configurações.");
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const handleResetClick = async () => {
    if (!window.confirm("Tem certeza que deseja excluir esta configuração? Esta ação não pode ser desfeita.")) {
      return;
    }
    try {
      await deleteAgentConfig();
      onReset();
    } catch (err: any) {
      console.error("Erro ao deletar config:", err);
      alert(err.message || "Erro ao deletar configurações!");
    }
  };

  const handleEditClick = () => {
    const currentAssistantName = configData?.assistant_identity?.assistant_name || "";
    onUpdate(currentAssistantName);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="text-center">
          <Loader className="w-10 h-10 text-indigo-500 animate-spin mx-auto mb-4" />
          <p className="text-gray-600">Carregando configurações...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <div className="bg-red-50 p-4 rounded-lg border border-red-200 flex gap-3 items-start">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <h3 className="text-red-700 font-medium mb-1">Erro ao carregar configurações</h3>
            <p className="text-sm text-red-600">{error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!configData) {
    return (
      <div className="p-8 text-center">
        <AlertCircle className="w-10 h-10 text-gray-400 mx-auto mb-3" />
        <p className="text-gray-600 font-medium">Nenhuma configuração encontrada.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-3">
          <CheckCircle className="w-5 h-5 text-green-500" />
          <h2 className="text-xl font-medium text-gray-800">Configuração Atual</h2>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleEditClick}
            className="px-3 py-2 bg-indigo-50 text-indigo-600 rounded-lg flex items-center gap-2 hover:bg-indigo-100 transition-colors"
          >
            <Edit2 className="w-4 h-4" />
            <span className="text-sm font-medium">Editar</span>
          </button>

          <button
            onClick={handleResetClick}
            className="px-3 py-2 bg-red-50 text-red-600 rounded-lg flex items-center gap-2 hover:bg-red-100 transition-colors"
          >
            <Trash2 className="w-4 h-4" />
            <span className="text-sm font-medium">Excluir</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {configData.assistant_identity && (
          <ConfigCard title="Identidade do Assistente" icon={Bot}>
            <InfoRow label="Nome" value={configData.assistant_identity.assistant_name} />
            <InfoRow label="Função/Cargo" value={configData.assistant_identity.assistant_role} />
            <InfoRow label="Responsabilidade" value={configData.assistant_identity.assistant_responsibility} />
            <InfoRow label="Formalidade" value={configData.assistant_identity.assistant_formality} />
            <InfoRow label="Tom de voz" value={configData.assistant_identity.assistant_tone} />
            <InfoRow label="Idioma" value={configData.assistant_identity.assistant_language} />
          </ConfigCard>
        )}

        {configData.company_info && (
          <ConfigCard title="Informações da Empresa" icon={Building}>
            <InfoRow label="Nome" value={configData.company_info.company_name} />
            <InfoRow label="Localização" value={configData.company_info.company_location} />
            <InfoRow label="Endereço" value={configData.company_info.company_address} />
            <InfoRow label="Telefone" value={configData.company_info.company_phone_fixed} />
            <InfoRow label="WhatsApp" value={configData.company_info.company_whatsapp} />

            <div className="mt-3 pt-2 border-t border-gray-100">
              <h3 className="text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
                <Globe className="w-4 h-4 text-indigo-400" />
                <span>Presença Digital</span>
              </h3>
              <InfoRow label="Maps" value={configData.company_info.company_maps} />
              <InfoRow label="Instagram" value={configData.company_info.company_instagram} />
              <InfoRow label="Facebook" value={configData.company_info.company_facebook} />
              <InfoRow label="Site" value={configData.company_info.company_site} />
            </div>
          </ConfigCard>
        )}

        {configData.team_and_specialties && (
          <ConfigCard title="Equipe e Especialidades" icon={Users}>
            <InfoRow label="Responsável Técnico" value={configData.team_and_specialties.technical_responsible} />
            {Array.isArray(configData.team_and_specialties.treatments) && configData.team_and_specialties.treatments.length > 0 && (
              <div className="mt-3 pt-2 border-t border-gray-100">
                <h3 className="text-sm font-medium text-gray-700 mb-2">Tratamentos</h3>
                {configData.team_and_specialties.treatments.map((treatment: any, index: number) => (
                  <div key={index} className="mb-3 pl-3 border-l-2 border-indigo-100 py-1">
                    <p className="font-medium text-sm text-gray-700">{treatment.treatmentTitle}</p>
                    <p className="text-xs text-gray-500">{treatment.description}</p>
                  </div>
                ))}
              </div>
            )}
          </ConfigCard>
        )}

        {configData.scheduling_config && (
          <ConfigCard title="Agendamento" icon={Calendar}>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 mb-4">
              {["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].map(day => {
                const dayConfig = (configData.scheduling_config as any)[day];
                if (!dayConfig || !dayConfig.open) {
                  return (
                    <div key={day} className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full bg-red-200"></div>
                      <span className="text-sm text-gray-500">
                        {day.charAt(0).toUpperCase() + day.slice(1)}
                      </span>
                    </div>
                  );
                }
                return (
                  <div key={day} className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-green-400"></div>
                    <span className="text-sm text-gray-700">
                      {day.charAt(0).toUpperCase() + day.slice(1)}
                    </span>
                  </div>
                );
              })}
            </div>

            <div className="border-t border-gray-100 pt-2">
              <div className="flex items-center gap-2 mb-2">
                <Clock className="w-4 h-4 text-indigo-400" />
                <span className="text-sm font-medium text-gray-700">Tempos</span>
              </div>
              <InfoRow
                label="Duração das consultas"
                value={`${configData.scheduling_config.consultation_duration || 30} minutos`}
              />
              <InfoRow
                label="Quantidade de sugestões"
                value={configData.scheduling_config.number_of_suggestions || 3}
              />
            </div>
          </ConfigCard>
        )}

        {configData.financial_config && (
          <ConfigCard title="Informações Financeiras" icon={DollarSign}>
            <InfoRow
              label="Aceita Plano de Saúde"
              value={configData.financial_config.accepts_health_insurance ? "Sim" : "Não"}
            />
            <InfoRow
              label="Convênios aceitos"
              value={configData.financial_config.health_insurance_plans}
            />
            <InfoRow
              label="Formas de Pagamento"
              value={Array.isArray(configData.financial_config.payment_methods) ? configData.financial_config.payment_methods.join(", ") : ""}
            />
            <InfoRow
              label="Condições de Parcelamento"
              value={configData.financial_config.installment_conditions}
            />
            <InfoRow
              label="Preço de avaliação"
              value={configData.financial_config.evaluation_price}
            />
          </ConfigCard>
        )}

        {configData.conversation_flow && (
          <ConfigCard title="Fluxo de Conversa" icon={MessageSquare}>
            <InfoRow label="Etapa 0" value={configData.conversation_flow.step0} />
            <InfoRow label="Etapa 1 (1ª parte)" value={configData.conversation_flow.step1First} />
            <InfoRow label="Etapa 1 (2ª parte)" value={configData.conversation_flow.step1Second} />
            <InfoRow label="Etapa 2" value={configData.conversation_flow.step2} />
            <InfoRow label="Etapa 3" value={configData.conversation_flow.step3} />
            <InfoRow label="Limite de tokens" value={configData.conversation_flow.max_tokens} />

            <div className="mt-3 pt-2 border-t border-gray-100">
              <h3 className="text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
                <Phone className="w-4 h-4 text-indigo-400" />
                <span>Redirecionamentos</span>
              </h3>
              <InfoRow
                label="Questões financeiras"
                value={configData.conversation_flow.financial_redirect?.number}
              />
              <InfoRow
                label="Agendamentos regulares"
                value={configData.conversation_flow.regular_redirect?.number}
              />
              <InfoRow
                label="Manutenção"
                value={configData.conversation_flow.maintenance_redirect?.number}
              />
              <InfoRow
                label="Clientes ativos"
                value={configData.conversation_flow.active_customers_redirect?.number}
              />
            </div>

            {Array.isArray(configData.conversation_flow.few_shots) && configData.conversation_flow.few_shots.length > 0 && (
              <div className="mt-3 pt-2 border-t border-gray-100">
                <h3 className="text-sm font-medium text-gray-700 mb-2">Few-Shot Examples</h3>
                <div className="space-y-3">
                  {configData.conversation_flow.few_shots.map((shot: any, index: number) => (
                    <div key={index} className="pl-3 border-l-2 border-indigo-100 py-1">
                      <p className="font-medium text-sm text-gray-700">{shot.objectionType}</p>
                      <div className="mt-1 space-y-1 text-xs">
                        <p className="text-gray-500">
                          <span className="font-medium">Usuário:</span> {shot.userMessage}
                        </p>
                        <p className="text-gray-700">
                          <span className="font-medium">Assistente:</span> {shot.botResponse.length > 60 ? shot.botResponse.substring(0, 60) + "..." : shot.botResponse}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </ConfigCard>
        )}
      </div>
    </div>
  );
};

export default ExistingConfigView;