import React, { useEffect, useState } from 'react';
import { MessageSquare, Bell, Edit2, Trash2, Save, X, Link as LinkIcon } from 'lucide-react';
import {
  getSupportGroupIntegration,
  updateSupportGroupIntegration,
  deleteSupportGroupIntegration
} from '../services/api';

const SupportGroupIntegration = () => {
  const [webhooks, setWebhooks] = useState({
    appointments: "",
    canceled: ""
  });
  const [hasIntegration, setHasIntegration] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchIntegration();
  }, []);

  const fetchIntegration = async () => {
    setLoading(true);
    try {
      const data = await getSupportGroupIntegration();
      // Verifica se realmente tem dados válidos
      if (data && (data.webhook_scheduling?.trim() || data.webhook_cancellation?.trim())) {
        setWebhooks({
          appointments: data.webhook_scheduling || "",
          canceled: data.webhook_cancellation || ""
        });
        setHasIntegration(true);
        setIsEditing(false);
      } else {
        // Se não tem dados, limpa tudo e vai para modo de criação
        setWebhooks({ appointments: "", canceled: "" });
        setHasIntegration(false);
        setIsEditing(true);
      }
    } catch (error) {
      console.error("Erro ao carregar integrações:", error);
      // Se der erro, assume que não tem integração e vai para modo de criação
      setWebhooks({ appointments: "", canceled: "" });
      setHasIntegration(false);
      setIsEditing(true);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      const payload = {
        webhook_scheduling: webhooks.appointments.trim(),
        webhook_cancellation: webhooks.canceled.trim()
      };

      await updateSupportGroupIntegration(payload);
      await fetchIntegration(); // Recarrega os dados após salvar
    } catch (error: any) {
      alert(error.message || "Erro ao salvar configurações!");
    }
  };

  const handleDelete = async () => {
    if (!window.confirm("Tem certeza que deseja remover esta integração?")) return;

    try {
      await deleteSupportGroupIntegration();
      setWebhooks({ appointments: "", canceled: "" });
      setHasIntegration(false);
      setIsEditing(true);
    } catch (error: any) {
      alert(error.message || "Erro ao deletar configuração!");
    }
  };

  const WebhookCard = ({ title, value, icon: Icon, description, fieldName }) => (
    <div className="bg-white rounded-lg border border-gray-200 p-6 transition-all hover:shadow-md">
      <div className="flex items-start space-x-4">
        <div className="p-3 bg-blue-50 rounded-lg">
          <Icon className="w-6 h-6 text-blue-600" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-lg font-medium text-gray-900">{title}</h3>
          <p className="mt-1 text-sm text-gray-500">{description}</p>
          {!isEditing ? (
            <p className="mt-2 text-sm font-mono bg-gray-50 p-2 rounded border border-gray-100 break-all">
              {value || "Nenhum webhook configurado"}
            </p>
          ) : (
            <input
              type="url"
              id={fieldName}
              className="mt-2 w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500"
              placeholder="https://exemplo.com/webhook"
              defaultValue={value}
              onChange={(e) => {
                setWebhooks(prev => ({
                  ...prev,
                  [fieldName]: e.target.value
                }));
              }}
            />
          )}
        </div>
      </div>
    </div>
  );

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 p-6">
        <div className="max-w-3xl mx-auto">
          <div className="animate-pulse space-y-6">
            <div className="h-8 bg-gray-200 rounded w-1/3"></div>
            <div className="space-y-4">
              <div className="h-40 bg-gray-200 rounded"></div>
              <div className="h-40 bg-gray-200 rounded"></div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              Integração com Grupo de Suporte
            </h1>
            <p className="mt-2 text-gray-600">
              Configure os webhooks para sincronização de agendamentos e cancelamentos
            </p>
          </div>

          {hasIntegration && !isEditing && (
            <div className="flex items-center space-x-3">
              <button
                onClick={() => setIsEditing(true)}
                className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                <Edit2 className="w-4 h-4 mr-2" />
                Editar
              </button>
              <button
                onClick={handleDelete}
                className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-red-600 hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
              >
                <Trash2 className="w-4 h-4 mr-2" />
                Remover
              </button>
            </div>
          )}
        </div>

        <div className="space-y-6">
          <WebhookCard
            title="Webhook de Agendamentos"
            value={webhooks.appointments}
            icon={MessageSquare}
            description="Recebe notificações quando novos agendamentos são criados"
            fieldName="appointments"
          />

          <WebhookCard
            title="Webhook de Cancelamentos"
            value={webhooks.canceled}
            icon={Bell}
            description="Recebe notificações quando consultas são canceladas"
            fieldName="canceled"
          />
        </div>

        {isEditing && (
          <div className="flex justify-end space-x-3 mt-6">
            {hasIntegration && (
              <button
                onClick={() => {
                  setIsEditing(false);
                  fetchIntegration(); // Recarrega os dados originais ao cancelar
                }}
                className="inline-flex items-center px-4 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                <X className="w-4 h-4 mr-2" />
                Cancelar
              </button>
            )}
            <button
              onClick={handleSave}
              className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500"
            >
              <Save className="w-4 h-4 mr-2" />
              {hasIntegration ? 'Atualizar' : 'Salvar'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default SupportGroupIntegration;