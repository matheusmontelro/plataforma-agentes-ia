
import React, { useEffect, useState } from 'react';
import {
  getMirrorWebhookUrl,
  createMirrorWebhookUrl,
  updateMirrorWebhookUrl,
  deleteMirrorWebhookUrl
} from '../services/api';  // Ajuste o path conforme seu projeto

interface MirrorWebhookResponse {
  company_id?: number;
  mirror_webhook_url: string | null;
}

const MirrorWebhookConfig: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [mirrorUrl, setMirrorUrl] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [tempUrl, setTempUrl] = useState('');
  // `tempUrl` serve para armazenar o valor do input enquanto editamos/criamos

  useEffect(() => {
    const fetchData = async () => {
      try {
        const data: MirrorWebhookResponse = await getMirrorWebhookUrl();
        if (data && data.mirror_webhook_url) {
          setMirrorUrl(data.mirror_webhook_url);
        } else {
          // Significa que não existe link configurado
          setMirrorUrl(null);
        }
      } catch (error) {
        console.error("Erro ao carregar Mirror Webhook:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  // Quando clica em "Salvar" no modo de criação
  const handleCreate = async () => {
    if (!tempUrl.trim()) {
      alert("Insira uma URL válida!");
      return;
    }
    try {
      await createMirrorWebhookUrl(tempUrl.trim());
      alert("URL salva com sucesso!");
      setMirrorUrl(tempUrl.trim());
      setEditing(false);
      setTempUrl('');
    } catch (error: any) {
      console.error("Erro ao salvar Mirror Webhook:", error.message);
      alert(error.message || "Erro ao salvar Mirror Webhook!");
    }
  };

  // Quando clica em "Salvar" no modo de edição
  const handleUpdate = async () => {
    if (!tempUrl.trim()) {
      alert("Insira uma URL válida!");
      return;
    }
    try {
      await updateMirrorWebhookUrl(tempUrl.trim());
      alert("URL atualizada com sucesso!");
      setMirrorUrl(tempUrl.trim());
      setEditing(false);
      setTempUrl('');
    } catch (error: any) {
      console.error("Erro ao atualizar Mirror Webhook:", error.message);
      alert(error.message || "Erro ao atualizar Mirror Webhook!");
    }
  };

  // Quando clica em "Deletar" (se já existe um link)
  const handleDelete = async () => {
    if (!window.confirm("Tem certeza que deseja remover o Mirror Webhook?")) {
      return;
    }
    try {
      await deleteMirrorWebhookUrl();
      alert("URL removida com sucesso!");
      setMirrorUrl(null);
      setEditing(false);
      setTempUrl('');
    } catch (error: any) {
      console.error("Erro ao deletar Mirror Webhook:", error.message);
      alert(error.message || "Erro ao deletar Mirror Webhook!");
    }
  };

  // Quando clica em "Editar"
  const startEditing = () => {
    if (mirrorUrl) {
      setTempUrl(mirrorUrl);
    } else {
      setTempUrl('');
    }
    setEditing(true);
  };

  // Quando clica em "Cancelar" edição
  const cancelEditing = () => {
    setEditing(false);
    setTempUrl('');
  };

  if (loading) {
    return (
      <div className="p-4">
        Carregando Mirror Webhook...
      </div>
    );
  }

  // Se não tem mirrorUrl cadastrado e não está editando
  // => Modo "Criar" (mas só se a pessoa clicar no botão, por ex.)
  if (!mirrorUrl && !editing) {
    // Podemos exibir o input direto ou exibir um botão "Configurar" e só então abrir o input.
    // Aqui, para simplificar, vou mostrar o input direto.
    return (
      <div className="p-4 bg-white shadow rounded">
        <h2 className="text-xl font-semibold mb-2">Mirror Webhook (Personalizado)</h2>
        <p className="text-sm text-gray-600 mb-4">
          Nenhuma URL configurada ainda. Insira abaixo para configurar:
        </p>

        <div className="flex gap-2">
          <input
            type="text"
            className="border px-2 py-1 rounded flex-1"
            placeholder="https://meuwebhook.com/espelho"
            value={tempUrl}
            onChange={(e) => setTempUrl(e.target.value)}
          />
          <button
            onClick={handleCreate}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 transition-colors"
          >
            Salvar
          </button>
        </div>
      </div>
    );
  }

  // Se há um MirrorUrl cadastrado, mas estamos sem editar => modo visualização
  if (mirrorUrl && !editing) {
    return (
      <div className="p-4 bg-white shadow rounded">
        <h2 className="text-xl font-semibold mb-2">Mirror Webhook (Personalizado)</h2>
        <p className="text-gray-700">URL atual configurada:</p>
        <p className="text-sm text-blue-600 mb-4 break-all">{mirrorUrl}</p>

        <div className="space-x-2">
          <button
            onClick={startEditing}
            className="px-3 py-1 bg-yellow-500 text-white rounded hover:bg-yellow-600"
          >
            Editar
          </button>
          <button
            onClick={handleDelete}
            className="px-3 py-1 bg-red-500 text-white rounded hover:bg-red-600"
          >
            Deletar
          </button>
        </div>
      </div>
    );
  }

  // Se estamos no modo de edição (editing = true), tanto para atualizar quanto para criar
  // mas nesse if, assumimos que mirrorUrl não é null => Ou seja, já existia valor
  // caso prefira reusar esse form para "criar", unifique a lógica acima.
  return (
    <div className="p-4 bg-white shadow rounded">
      <h2 className="text-xl font-semibold mb-2">Editar Mirror Webhook</h2>
      <p className="text-sm text-gray-600 mb-4">
        Atualize a URL do webhook para fazer o espelhamento de mensagens.
      </p>

      <div className="flex gap-2 mb-4">
        <input
          type="text"
          className="border px-2 py-1 rounded flex-1"
          value={tempUrl}
          onChange={(e) => setTempUrl(e.target.value)}
        />
      </div>

      <div className="space-x-2">
        <button
          onClick={handleUpdate}
          className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          Salvar
        </button>
        <button
          onClick={cancelEditing}
          className="px-3 py-1 bg-gray-300 text-gray-800 rounded hover:bg-gray-400"
        >
          Cancelar
        </button>
      </div>
    </div>
  );
};

export default MirrorWebhookConfig;
