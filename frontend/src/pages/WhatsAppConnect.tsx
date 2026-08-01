import React, { useEffect, useState, useRef } from 'react';
import api, {
  getWahaSessionStatus,
  startWahaSession,
  requestWahaPairingCode,
  connectWaha
} from '../services/api';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  QrCode,
  RefreshCcw,
  Smartphone,
  AlertCircle,
  Power,
  RotateCcw,
  ArrowLeft,
  Activity,
  CheckCircle2,
  Clock3,
  ShieldCheck,
  Wifi,
  Loader2,
  KeyRound,
  Copy,
  Phone,
} from 'lucide-react';
import ConfirmDeleteModal from '../components/ConfirmDeleteModal.tsx';
import {
  AgentiveAlert,
  agentiveIconButtonClass,
  agentiveInputClass,
  agentivePanelClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from '../components/AgentiveUI.tsx';
import { branding } from '../config/branding.ts';
import { toPublicAppUrl } from '../config/runtime.ts';

interface StatusData {
  connected: boolean;
  state: string;
  [key: string]: any;
}

interface DeviceData {
  id: string;
  name: string;
  phone: string;
  imgUrl: string;
  isBusiness: boolean;
  device: {
    sessionName: string;
    device_model: string;
  };
  [key: string]: any;
}

type Provider = 'zapi' | 'waha' | null;

type ClientStatusTone = 'success' | 'warning' | 'danger' | 'neutral';

interface ClientStatusCopy {
  label: string;
  helper: string;
  tone: ClientStatusTone;
}

const normalizeWhatsAppStatus = (rawStatus?: string | null) => {
  return String(rawStatus || '').trim().toUpperCase().replace(/[-\s]/g, '_');
};

const getWhatsAppStatusCopy = (
  connected: boolean,
  rawStatus?: string | null,
  hasProvider = false,
  isConfiguring = false,
): ClientStatusCopy => {
  const normalized = normalizeWhatsAppStatus(rawStatus);

  if (connected || normalized === 'WORKING' || normalized === 'READY') {
    return {
      label: 'Conectado',
      helper: 'Pronto para atender e automatizar conversas.',
      tone: 'success',
    };
  }

  if (normalized === 'SCAN_QR' || normalized === 'SCAN_QR_CODE' || normalized === 'QR_PENDENTE') {
    return {
      label: 'Aguardando leitura do QR',
      helper: 'Escaneie o QR Code no celular para concluir.',
      tone: 'warning',
    };
  }

  if (normalized === 'STARTING' || normalized === 'CONNECTING') {
    return {
      label: 'Conectando',
      helper: 'Estamos preparando a conexão com este WhatsApp.',
      tone: 'warning',
    };
  }

  if (normalized === 'FAILED') {
    return {
      label: 'Precisa reconectar',
      helper: 'Reconecte este WhatsApp para voltar a usar o canal.',
      tone: 'danger',
    };
  }

  if (normalized === 'STOPPED' || normalized === 'DISCONNECTED') {
    return {
      label: 'Desconectado',
      helper: 'Conecte este WhatsApp para liberar atendimento e automações.',
      tone: 'neutral',
    };
  }

  if (normalized === 'NOT_FOUND') {
    return {
      label: 'Não configurado',
      helper: 'Crie a conexão deste WhatsApp para começar.',
      tone: 'neutral',
    };
  }

  if (isConfiguring) {
    return {
      label: 'Configurando',
      helper: 'Estamos preparando uma conexão segura para este WhatsApp.',
      tone: 'warning',
    };
  }

  if (hasProvider) {
    return {
      label: 'Verificando conexão',
      helper: 'Consultando o status deste WhatsApp.',
      tone: 'warning',
    };
  }

  return {
    label: 'Sem configuração',
    helper: 'Conecte um WhatsApp para iniciar.',
    tone: 'neutral',
  };
};

const toClientWhatsAppMessage = (value?: string | null) => {
  return String(value || '')
    .replace(/\bwaha\b/gi, 'WhatsApp')
    .replace(/\bz-api\b/gi, 'WhatsApp')
    .replace(/\bsess[aã]o\s+WhatsApp\b/gi, 'conexão do WhatsApp')
    .replace(/\bprovider\b/gi, 'canal');
};

const isWhatsAppConnectedStatus = (status?: Partial<StatusData> | null) => {
  const normalized = normalizeWhatsAppStatus(status?.state || status?.status);
  return Boolean(status?.connected) || normalized === 'WORKING' || normalized === 'READY';
};

const WhatsAppConnectPage: React.FC = () => {
  const { isDark } = useTheme();

  // Legacy WhatsApp states
  const [instanceId, setInstanceId] = useState('');
  const [instanceToken, setInstanceToken] = useState('');
  const [hasConfig, setHasConfig] = useState(false);

  // WhatsApp QR states
  const [hasWahaConfig, setHasWahaConfig] = useState(false);
  const [wahaSessionName, setWahaSessionName] = useState('');

  // Connection management
  const [currentProvider, setCurrentProvider] = useState<Provider>(null);
  const [selectedProvider, setSelectedProvider] = useState<Provider>(null);

  // Common states
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [deviceData, setDeviceData] = useState<DeviceData | null>(null);
  const [statusData, setStatusData] = useState<StatusData | null>(null);
  const [qrcodeBase64, setQrcodeBase64] = useState<string>('');
  const [pairingPhoneNumber, setPairingPhoneNumber] = useState('');
  const [pairingCode, setPairingCode] = useState('');
  const [isPairingCodeLoading, setIsPairingCodeLoading] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [qrAttempts, setQrAttempts] = useState(0);
  const qrIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const statusCheckIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Refs para manter valores atualizados nos intervals (evitar stale closure)
  const currentProviderRef = useRef<Provider>(currentProvider);
  const statusDataRef = useRef<StatusData | null>(statusData);

  // Modals
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [showResetModal, setShowResetModal] = useState(false);

  const clearStates = () => {
    setError('');
    setMessage('');
    setDeviceData(null);
    setStatusData(null);
    setQrcodeBase64('');
    setPairingCode('');
    setQrAttempts(0);
  };

  // Sincronizar refs com states (effect)
  useEffect(() => {
    currentProviderRef.current = currentProvider;
    console.log('🔄 Canal atual atualizado:', currentProvider);
  }, [currentProvider]);

  useEffect(() => {
    statusDataRef.current = statusData;
    console.log('🔄 statusDataRef atualizado:', statusData?.connected);
  }, [statusData]);

  // ==========================================
  // UNIFIED CONFIG DETECTION
  // ==========================================

  async function fetchWhatsAppConfig(): Promise<{ provider: Provider; hasConfig: boolean }> {
    try {
      const resp = await api.get('/webhook/whatsapp/config');
      const { provider, config } = resp.data;

      console.log('📡 Config detectada:', provider, config);

      if (!provider || !config) {
        return { provider: null, hasConfig: false };
      }

      // Detectar conexão por QR Code
      if (provider === 'waha') {
        setWahaSessionName(config.session_name);
        setHasWahaConfig(true);
        setCurrentProvider('waha');
        console.log('✅ WhatsApp por QR Code detectado:', config.session_name);
        return { provider: 'waha', hasConfig: true };
      }

      // Detectar conexão legada
      if (provider === 'zapi') {
        setInstanceId(config.instance_id);
        setInstanceToken(config.instance_token);
        setHasConfig(true);
        setCurrentProvider('zapi');
        console.log('✅ WhatsApp legado detectado');
        return { provider: 'zapi', hasConfig: true };
      }


      return { provider: null, hasConfig: false };
    } catch (err) {
      console.error('❌ Erro ao buscar config:', err);
      return { provider: null, hasConfig: false };
    }
  }

  // ==========================================
  // Legacy WhatsApp functions
  // ==========================================

  async function fetchZapiConfig(): Promise<boolean> {
    // Mantido para compatibilidade, mas não usado mais
    const result = await fetchWhatsAppConfig();
    return result.provider === 'zapi' && result.hasConfig;
  }

  async function fetchZapiStatus() {
    try {
      const resp = await api.get('/webhook/whatsapp/status');
      setStatusData(resp.data);
      return resp.data as StatusData;
    } catch (err) {
      console.error('Erro ao verificar status do WhatsApp legado:', err);
      setError('Não foi possível verificar o status deste WhatsApp.');
      return null;
    }
  }

  async function fetchZapiDevice() {
    try {
      const resp = await api.get('/webhook/whatsapp/device');
      setDeviceData(resp.data);
    } catch (err) {
      console.error('Erro ao obter dados do WhatsApp legado:', err);
    }
  }

  async function fetchZapiQRCode() {
    if (isWhatsAppConnectedStatus(statusData) || qrAttempts >= 3) return;

    try {
      const resp = await api.get('/webhook/whatsapp/qrcode');
      let qrcode = resp.data.qrcode;

      // Garantir que o QR code tenha o prefixo correto para exibição
      if (qrcode && !qrcode.startsWith('data:')) {
        qrcode = `data:image/png;base64,${qrcode}`;
      }

      setQrcodeBase64(qrcode);
      setQrAttempts((prev) => prev + 1);
    } catch (err) {
      console.error('Erro ao obter QR Code do WhatsApp legado:', err);
      setError('Não foi possível gerar o QRCode para conexão.');
    }
  }


  // ==========================================
  // WhatsApp QR functions
  // ==========================================

  async function fetchWahaStatus() {
    try {
      const resp = await api.get('/webhook/whatsapp/status');
      const statusData: StatusData = {
        connected: resp.data.connected,
        state: resp.data.state || resp.data.status
      };
      setStatusData(statusData);
      return statusData;
    } catch (err) {
      console.error('Erro ao verificar status do WhatsApp:', err);
      setError('Não foi possível verificar o status deste WhatsApp.');
      return null;
    }
  }

  async function fetchWahaDevice() {
    try {
      const resp = await api.get('/webhook/whatsapp/device');
      const data = resp.data;
      const deviceData: DeviceData = {
        id: data.id || '',
        name: data.name || data.pushname || '',
        phone: data.phone || data.me?.id?.user || '',
        imgUrl: data.imgUrl || '',
        isBusiness: data.isBusiness || false,
        device: {
          sessionName: wahaSessionName,
          device_model: data.platform || 'WhatsApp'
        }
      };
      setDeviceData(deviceData);
      console.log('WhatsApp carregado:', deviceData);
    } catch (err) {
      console.error('Erro ao obter dados do WhatsApp:', err);
    }
  }

  function handleWahaFailedStatus(sessionStatus: { status?: string; message?: string | null }) {
    const failedMessage = sessionStatus.message
      || 'Este WhatsApp falhou antes de gerar o QR Code. Tente novamente; se persistir, resetar a conexão pode resolver.';

    console.error('❌ [fetchWahaQRCode] WhatsApp em falha:', sessionStatus);
    setError(toClientWhatsAppMessage(failedMessage));
    setQrcodeBase64('');
    setQrAttempts(10);
    stopQrInterval();
    return true;
  }

  async function fetchWahaQRCode() {
    const currentStatus = statusDataRef.current;
    console.log(`🔍 [fetchWahaQRCode] Tentativas: ${qrAttempts}/20, Connected: ${currentStatus?.connected}`);

    if (isWhatsAppConnectedStatus(currentStatus)) {
      console.log('⚠️ [fetchWahaQRCode] Já conectado, ignorando...');
      return;
    }

    try {
      // 1. Verificar status da conexão do WhatsApp
      console.log('📡 [fetchWahaQRCode] Verificando status do WhatsApp...');
      const sessionStatus = await getWahaSessionStatus();
      console.log('📊 [fetchWahaQRCode] Status do WhatsApp:', sessionStatus);

      // O status FAILED precisa passar pelo fluxo de recuperação, mesmo após várias tentativas.
      if (qrAttempts >= 10 && !sessionStatus.needsStart && !sessionStatus.needsQR && !sessionStatus.connected) {
        console.log('⚠️ [fetchWahaQRCode] Limite de tentativas excedido (10), parando busca...');
        setError('Não foi possível gerar o QR Code. Por favor, tente resetar a conexão.');
        stopQrInterval();
        return;
      }

      // 2. Se a conexão está parada, iniciar automaticamente
      if (sessionStatus.needsStart) {
        console.log('🚀 [fetchWahaQRCode] WhatsApp parado, iniciando automaticamente...');
        const startResult = await startWahaSession();
        console.log('✅ [fetchWahaQRCode] WhatsApp iniciado:', startResult);

        // Aguardar um pouco para a conexão ficar pronta
        await new Promise(resolve => setTimeout(resolve, 2000));

        // Verificar status novamente após iniciar
        const newStatus = await getWahaSessionStatus();
        console.log('📊 [fetchWahaQRCode] Status após iniciar:', newStatus);

        if (newStatus.status === 'FAILED' || newStatus.failed) {
          handleWahaFailedStatus(newStatus);
          return;
        }

        // Se ainda precisa de QR Code, buscar
        if (newStatus.needsQR) {
          console.log('📱 [fetchWahaQRCode] QR Code disponível, buscando...');
          const resp = await api.get('/webhook/whatsapp/qrcode');
          let qrcode = resp.data.qrcode;

          // Garantir que o QR code tenha o prefixo correto para exibição
          if (qrcode && !qrcode.startsWith('data:')) {
            qrcode = `data:image/png;base64,${qrcode}`;
          }

          console.log('✅ [fetchWahaQRCode] QR Code obtido com sucesso!');
          setQrcodeBase64(qrcode);
          setQrAttempts((prev) => prev + 1);
        } else if (isWhatsAppConnectedStatus(newStatus as any)) {
          console.log('✅ [fetchWahaQRCode] WhatsApp já está conectado!');
          stopQrInterval();
          stopStatusCheckInterval();
          await handleFetchAllData(currentProvider);
          return;
        } else {
          console.log('⏳ [fetchWahaQRCode] WhatsApp iniciado, mas QR Code ainda não disponível. Aguardando próxima tentativa...');
          setQrAttempts((prev) => prev + 1);
        }
      }
      // 3. Se a conexão precisa de QR Code, buscar normalmente
      else if (sessionStatus.needsQR) {
        console.log('📱 [fetchWahaQRCode] WhatsApp precisa de QR Code, buscando...');
        const resp = await api.get('/webhook/whatsapp/qrcode');
        let qrcode = resp.data.qrcode;

        // Garantir que o QR code tenha o prefixo correto para exibição
        if (qrcode && !qrcode.startsWith('data:')) {
          qrcode = `data:image/png;base64,${qrcode}`;
        }

        console.log('✅ [fetchWahaQRCode] QR Code obtido com sucesso!');
        setQrcodeBase64(qrcode);
        setQrAttempts((prev) => prev + 1);
      }
      // 4. Se já está conectado, parar
      else if (isWhatsAppConnectedStatus(sessionStatus as any)) {
        console.log('✅ [fetchWahaQRCode] WhatsApp já está conectado!');
        stopQrInterval();
        stopStatusCheckInterval();
        await handleFetchAllData(currentProvider);
        return;
      }
      // 5. Se está em estado FAILED, parar a busca e mostrar erro acionável
      else if (sessionStatus.status === 'FAILED' || sessionStatus.failed) {
        handleWahaFailedStatus(sessionStatus);
        return;
      }
      // 5.1. Se está em estado NOT_FOUND, criar e iniciar conexão
      else if (sessionStatus.status === 'NOT_FOUND') {
        console.log('🆕 [fetchWahaQRCode] WhatsApp não encontrado, criando nova conexão...');
        try {
          // Tentar iniciar a conexão (isso vai criar automaticamente)
          const startResult = await startWahaSession();
          console.log('✅ [fetchWahaQRCode] Novo WhatsApp criado e iniciado:', startResult);

          setQrAttempts((prev) => prev + 1);
          setMessage('Novo WhatsApp criado. Aguardando geração do QR Code...');
        } catch (createErr: any) {
          console.error('❌ [fetchWahaQRCode] Erro ao criar novo WhatsApp:', createErr);
          setError('Falha ao criar a conexão deste WhatsApp. Tente novamente.');
          stopQrInterval();
        }
      }
      // 6. Se está em outro estado (STARTING), aguardar próxima tentativa
      else {
        console.log('⏳ [fetchWahaQRCode] WhatsApp em estado:', sessionStatus.status, '- aguardando próxima tentativa...');
        setQrAttempts((prev) => prev + 1);
      }
    } catch (err: any) {
      // Tratar erro de rede (ERR_FAILED) e outros erros sem response
      if (!err.response) {
        console.error('❌ [fetchWahaQRCode] Erro de rede:', err.message || err.code || err.toString());
        setError('Erro de conexão com o servidor. Verifique sua conexão e tente novamente.');
        stopQrInterval();
        return;
      }

      const errorMessage = err.response?.data?.detail || '';

      if (errorMessage.includes('já está conectado') || errorMessage.includes('already connected')) {
        console.log('✅ WhatsApp já está conectado');
        stopQrInterval();
        stopStatusCheckInterval();
        await handleFetchAllData(currentProvider);
        return;
      }

      console.error('❌ [fetchWahaQRCode] Erro:', err.response?.status, errorMessage || 'Sem mensagem de erro');

      // Se a conexão saiu do estado esperado, tente recuperar apenas quando houver falha explícita.
      if (
        err.response?.status === 422
        || (err.response?.status === 409 && errorMessage.includes('falhou'))
      ) {
        console.log('🔧 [fetchWahaQRCode] Estado recuperável detectado, tentando iniciar/reiniciar WhatsApp...');
        try {
          const startResult = await startWahaSession();
          console.log('✅ [fetchWahaQRCode] WhatsApp iniciado/reiniciado como fallback:', startResult);
          setQrAttempts((prev) => prev + 1);
        } catch (startErr: any) {
          console.error('❌ [fetchWahaQRCode] Erro ao recuperar WhatsApp como fallback:', startErr);
          setError('Não foi possível iniciar este WhatsApp. Tente resetar a conexão.');
          stopQrInterval();
        }
      } else if ((err.response?.status === 400 || err.response?.status === 409) && qrAttempts < 10) {
        console.log(`⏳ QR code ainda não disponível, tentativa ${qrAttempts + 1}/10...`);
        setQrAttempts((prev) => prev + 1);
      } else if (err.response?.status === 400 || err.response?.status === 409) {
        console.log('🛑 Limite de tentativas excedido');
        setError('Não foi possível gerar o QR Code. Por favor, tente resetar a conexão.');
        stopQrInterval();
      } else {
        console.log('🛑 Erro real ao gerar QR Code');
        setError('Não foi possível gerar o QR Code para conexão.');
        stopQrInterval();
      }
    }
  }

  // ==========================================
  // Unified WhatsApp functions
  // ==========================================

  async function fetchStatus() {
    // Usar ref para evitar stale closure em setInterval
    const provider = currentProviderRef.current;
    console.log('🔍 [fetchStatus] Canal do ref:', provider);

    if (provider === 'zapi') {
      return await fetchZapiStatus();
    } else if (provider === 'waha') {
      return await fetchWahaStatus();
    }
    console.warn('⚠️ [fetchStatus] Canal inválido ou null:', provider);
    return null;
  }

  async function fetchDeviceData() {
    // Usar ref para evitar stale closure em setInterval
    const provider = currentProviderRef.current;
    console.log('🔍 [fetchDeviceData] Canal do ref:', provider);

    if (provider === 'zapi') {
      await fetchZapiDevice();
    } else if (provider === 'waha') {
      await fetchWahaDevice();
    }
  }

  async function fetchQrCode() {
    // Usar ref para evitar stale closure em setInterval
    const provider = currentProviderRef.current;
    console.log('🔍 [fetchQrCode] Canal do ref:', provider);

    if (provider === 'zapi') {
      await fetchZapiQRCode();
    } else if (provider === 'waha') {
      await fetchWahaQRCode();
    }
  }

  function startQrInterval() {
    if (qrIntervalRef.current) {
      clearInterval(qrIntervalRef.current);
    }
    qrIntervalRef.current = setInterval(() => {
      fetchQrCode();
    }, 15000);
  }

  function stopQrInterval() {
    if (qrIntervalRef.current) {
      clearInterval(qrIntervalRef.current);
      qrIntervalRef.current = null;
    }
  }

  function startStatusCheckInterval() {
    // Parar intervalo existente se houver
    if (statusCheckIntervalRef.current) {
      clearInterval(statusCheckIntervalRef.current);
    }

    console.log('🔄 Iniciando polling de status (verifica a cada 3 segundos)...');

    // Verificar status a cada 3 segundos para detectar quando conectar (mais rápido)
    statusCheckIntervalRef.current = setInterval(async () => {
      try {
        console.log('🔍 [Polling] Verificando status...');

        const status = await fetchStatus();
        console.log('📊 Status verificado:', isWhatsAppConnectedStatus(status) ? 'CONECTADO ✅' : 'desconectado ⏳');

        if (isWhatsAppConnectedStatus(status)) {
          console.log('🎉 Conexão detectada! Atualizando dados...');

          // Parar intervalos primeiro
          stopQrInterval();
          stopStatusCheckInterval();

          // Atualizar todos os states
          setStatusData({ ...status, connected: true }); // Force new object reference
          setQrcodeBase64(''); // Limpar QR code
          setQrAttempts(0); // Resetar tentativas
          setMessage('✅ WhatsApp conectado com sucesso!');

          // Buscar dados do device
          await fetchDeviceData();

          console.log('✅ UI atualizada com sucesso!');
        }
      } catch (err) {
        console.error('❌ Erro ao verificar status no polling:', err);
      }
    }, 3000); // Reduzido de 5s para 3s
  }

  function stopStatusCheckInterval() {
    if (statusCheckIntervalRef.current) {
      clearInterval(statusCheckIntervalRef.current);
      statusCheckIntervalRef.current = null;
    }
  }

  async function handleFetchAllData(provider?: Provider, forceRefresh: boolean = false) {
    // Não limpar states se estiver apenas atualizando (já conectado)
    const isUpdate = isWhatsAppConnectedStatus(statusData);

    if (!isUpdate) {
      clearStates();
    }

    setIsLoading(true);

    const providerToUse = provider || currentProvider;

    try {
      let status: StatusData | null = null;


      {
        console.log('🔍 Verificando status normalmente...');
        console.log(`   - forceRefresh: ${forceRefresh}`);
        console.log(`   - canal: ${providerToUse}`);
        console.log(`   - statusData presente: ${!!statusData}`);

        if (providerToUse === 'zapi') {
          status = await fetchZapiStatus();
        } else if (providerToUse === 'waha') {
          status = await fetchWahaStatus();
          console.log(`   - Status retornado: connected=${status?.connected}, state=${status?.state}`);
        }
      }

      console.log(`📊 Status final para processamento: connected=${status?.connected}, state=${status?.state}`);

      if (status) {
        if (isWhatsAppConnectedStatus(status)) {
          console.log('✅ Branch: WhatsApp CONECTADO');
          // Se conectado, buscar dados do device
          if (providerToUse === 'zapi') {
            await fetchZapiDevice();
          } else if (providerToUse === 'waha') {
            await fetchWahaDevice();
          }

          // Parar todos os intervalos quando conectado
          stopQrInterval();
          stopStatusCheckInterval();

          // Limpar QR Code quando conectado
          setQrcodeBase64('');
          setQrAttempts(0);

          console.log('✅ WhatsApp conectado com sucesso!');
        } else {
          // Se desconectado, buscar QR Code
          console.log('❌ Branch: WhatsApp DESCONECTADO');
          console.log('⏳ WhatsApp desconectado, buscando QR Code...');
          console.log(`📊 Estado atual: qrAttempts=${qrAttempts}, forceRefresh=${forceRefresh}, canal=${providerToUse}`);


          if (providerToUse === 'zapi') {
            await fetchZapiQRCode();
          } else if (providerToUse === 'waha') {
            console.log(`🔍 Chamando fetchWahaQRCode com qrAttempts=${qrAttempts}`);
            await fetchWahaQRCode();
          }

          // Iniciar intervalo de atualização do QR
          console.log('🔄 Iniciando intervalo de atualização de QR Code');
          startQrInterval();

          // Iniciar polling de status para detectar quando conectar
          startStatusCheckInterval();
        }
      }
    } catch (error) {
      console.error('Erro em handleFetchAllData:', error);
      setError('Erro ao carregar dados da conexão.');
    } finally {
      setIsLoading(false);
    }
  }

  // ==========================================
  // CONNECT HANDLERS
  // ==========================================

  async function handleConnectZapi(e: React.FormEvent) {
    e.preventDefault();
    clearStates();
    setIsLoading(true);

    try {
      const resp = await api.post('/webhook/whatsapp/connect', {
        instance_id: instanceId,
        instance_token: instanceToken,
      });
      setMessage(toClientWhatsAppMessage(resp.data.message) || 'WhatsApp configurado com sucesso!');
      setHasConfig(true);
      setCurrentProvider('zapi');
      setSelectedProvider(null);
      await handleFetchAllData('zapi');
    } catch (err: any) {
      console.error('Erro ao salvar configuração do WhatsApp legado:', err);
      setError('Erro ao salvar as configurações deste WhatsApp. Verifique as credenciais.');
    } finally {
      setIsLoading(false);
    }
  }


  async function handleConnectWaha(e: React.FormEvent) {
    e.preventDefault();
    clearStates();
    setIsLoading(true);

    try {
      console.log('🚀 [handleConnectWaha] Criando conexão segura do WhatsApp');
      const result = await connectWaha();
      console.log('✅ [handleConnectWaha] WhatsApp conectado:', result);

      setWahaSessionName(result.session_name);
      setMessage(toClientWhatsAppMessage(result.message) || 'WhatsApp configurado com sucesso!');
      setHasWahaConfig(true);
      setCurrentProvider('waha');
      setSelectedProvider(null);

      // Buscar todos os dados do WhatsApp
      await handleFetchAllData('waha');
    } catch (err: any) {
      console.error('❌ [handleConnectWaha] Erro ao conectar WhatsApp:', err);
      const errorDetail = err.response?.data?.detail;
      const errorMessage = Array.isArray(errorDetail)
        ? errorDetail.map(err => err.msg).join(', ')
        : typeof errorDetail === 'string'
          ? errorDetail
          : 'Erro ao conectar este WhatsApp.';
      setError(toClientWhatsAppMessage(errorMessage));
    } finally {
      setIsLoading(false);
    }
  }

  // ==========================================
  // DISCONNECT/RESET HANDLERS
  // ==========================================

  async function handleDisconnect() {
    setShowDisconnectModal(false);
    setIsLoading(true);
    setError('');
    setMessage('');

    try {
      if (currentProvider === 'zapi') {
        const resp = await api.get('/webhook/whatsapp/disconnect');
        setMessage(toClientWhatsAppMessage(resp.data.message) || 'WhatsApp desconectado com sucesso!');

        // Para conexão legada, usar fluxo normal
        console.log('⏳ Aguardando backend processar desconexão...');
        await new Promise(resolve => setTimeout(resolve, 500));
        await handleFetchAllData(undefined, true);


      } else if (currentProvider === 'waha') {
        console.log('🔄 Desconectando WhatsApp...');
        const resp = await api.get('/webhook/whatsapp/disconnect');
        console.log('✅ WhatsApp desconectado, recarregando página em 2s...');

        // Mostrar mensagem de sucesso
        setMessage(toClientWhatsAppMessage(resp.data.message) || 'WhatsApp desconectado com sucesso!');

        // Aguardar 2 segundos e RECARREGAR A PÁGINA
        await new Promise(resolve => setTimeout(resolve, 2000));

        console.log('🔄 Recarregando página...');
        window.location.reload();
      }
    } catch (err) {
      setError('Erro ao desconectar este WhatsApp.');
      console.error(err);
      setIsLoading(false);
    }
  }

  async function handleResetConfig() {
    setShowResetModal(false);
    setIsLoading(true);
    setError('');
    setMessage('');

    try {
      // Reset universal para os canais de WhatsApp disponíveis
      const resp = await api.post('/webhook/whatsapp/reset');

      if (currentProvider === 'zapi') {
        setMessage(toClientWhatsAppMessage(resp.data.message) || 'WhatsApp resetado com sucesso!');
        setHasConfig(false);
        setInstanceId('');
        setInstanceToken('');
      } else if (currentProvider === 'waha') {
        setMessage(toClientWhatsAppMessage(resp.data.message) || 'WhatsApp resetado com sucesso!');
        setHasWahaConfig(false);
        setWahaSessionName('');
      }

      // Limpar canal atual
      setCurrentProvider(null);
      stopQrInterval();
      stopStatusCheckInterval();

      // Limpar estados comuns
      clearStates();

      // Para conexão por QR Code, recarregar página após 2 segundos para limpar completamente
      if (currentProvider === 'waha') {
        console.log('✅ WhatsApp resetado, recarregando página em 2s...');
        await new Promise(resolve => setTimeout(resolve, 2000));
        window.location.reload();
      }
    } catch (err) {
      setError('Erro ao resetar a configuração.');
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleManualRetry() {
    setError('');
    setMessage('');
    setQrAttempts(0);
    setQrcodeBase64('');
    setPairingCode('');
    if (qrIntervalRef.current) {
      clearInterval(qrIntervalRef.current);
      qrIntervalRef.current = null;
    }
    await fetchQrCode();
    if (qrAttempts < 3 && !isWhatsAppConnectedStatus(statusData)) {
      startQrInterval();
    }
  }

  async function handleRefreshQRCode() {
    // Função específica para refresh de QR Code
    const provider = currentProviderRef.current;
    console.log(`🔄 Atualizando QR Code do canal ${provider?.toUpperCase()}...`);
    setError('');
    setMessage('');
    setQrcodeBase64('');
    setPairingCode('');

    // Resetar contadores de tentativas
    setQrAttempts(0);

    // Parar intervalos existentes completamente
    stopQrInterval();
    stopStatusCheckInterval();

    setIsLoading(true);

    try {
      // Buscar novo QR Code baseado no canal
      if (provider === 'waha') {
        console.log('🔄 [handleRefreshQRCode] Buscando novo QR Code do WhatsApp...');
        await fetchWahaQRCode();

        // Aguardar um pouco e verificar se obteve QR Code
        setTimeout(() => {
          if (qrcodeBase64) {
            console.log('✅ [handleRefreshQRCode] QR Code obtido, reiniciando intervalos...');
            startQrInterval();
            startStatusCheckInterval();
            setMessage('QR Code atualizado! Escaneie para conectar.');
          } else {
            console.log('⏳ [handleRefreshQRCode] QR Code ainda não disponível, iniciando intervalos para continuar tentando...');
            startQrInterval();
            startStatusCheckInterval();
            setMessage('Aguardando geração do QR Code...');
          }
        }, 500);
      }
    } catch (error) {
      console.error('Erro ao atualizar QR Code:', error);
      setError('Erro ao atualizar QR Code. Tente novamente.');

      // Mesmo com erro, tentar reiniciar intervalos para continuar tentando
      if (provider === 'waha') {
        console.log('🔧 [handleRefreshQRCode] Erro detectado, reiniciando intervalos para continuar tentando...');
        startQrInterval();
        startStatusCheckInterval();
      }
    } finally {
      setIsLoading(false);
    }
  }

  async function handleRequestPairingCode(e: React.FormEvent) {
    e.preventDefault();

    const normalizedPhone = pairingPhoneNumber.replace(/\D/g, '');
    if (normalizedPhone.length < 10) {
      setError('Informe o telefone com DDI e DDD para gerar o código de pareamento.');
      return;
    }

    setError('');
    setMessage('');
    setPairingCode('');
    setIsPairingCodeLoading(true);

    try {
      const result = await requestWahaPairingCode(normalizedPhone);
      setPairingPhoneNumber(result.phoneNumber);
      setPairingCode(result.pairingCode);
      setMessage(toClientWhatsAppMessage(result.message) || 'Código de pareamento gerado.');
      startStatusCheckInterval();
    } catch (err: any) {
      console.error('Erro ao solicitar código de pareamento:', err);
      const errorDetail = err.response?.data?.detail;
      const errorMessage = typeof errorDetail === 'string'
        ? errorDetail
        : 'Não foi possível gerar o código de pareamento. Use o QR Code como alternativa.';
      setError(toClientWhatsAppMessage(errorMessage));
    } finally {
      setIsPairingCodeLoading(false);
    }
  }

  async function handleCopyPairingCode() {
    if (!pairingCode || !navigator.clipboard) return;

    try {
      await navigator.clipboard.writeText(pairingCode);
      setMessage('Código de pareamento copiado.');
    } catch (err) {
      console.error('Erro ao copiar código de pareamento:', err);
      setError('Não foi possível copiar o código automaticamente.');
    }
  }

  // ==========================================
  // INITIALIZATION
  // ==========================================

  useEffect(() => {
    async function initialize() {
      setIsLoading(true);

      console.log('🚀 Inicializando detecção de canal...');

      // Detectar canal configurado usando função unificada
      const { provider, hasConfig } = await fetchWhatsAppConfig();

      console.log('📡 Resultado da detecção:', { provider, hasConfig });

      // Se detectou canal, buscar todos os dados
      if (hasConfig && provider) {
        console.log(`✅ Canal detectado: ${provider}`);
        await handleFetchAllData(provider);
      } else {
        // Sem configuração - mostrar tela de seleção
        console.log('❌ Nenhum canal configurado');
        setCurrentProvider(null);
        setIsLoading(false);
      }
    }

    initialize();

    return () => {
      stopQrInterval();
      stopStatusCheckInterval();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const webhookUrl = currentProvider === 'zapi'
    ? toPublicAppUrl(`/webhook/${instanceId}`)
    : currentProvider === 'waha'
      ? toPublicAppUrl(`/webhook/${wahaSessionName}`)
      : '';

  const hasActiveProvider = Boolean(currentProvider);
  const isConfiguringWhatsApp = Boolean(selectedProvider && !currentProvider);
  const rawSessionStatus = statusData?.state || statusData?.status;
  const isConnected = isWhatsAppConnectedStatus(statusData);
  const statusCopy = getWhatsAppStatusCopy(isConnected, rawSessionStatus, hasActiveProvider, isConfiguringWhatsApp);
  const statusLabel = statusCopy.label;
  const stateLabel = statusCopy.helper;
  const providerLabel = hasActiveProvider ? 'WhatsApp conectado' : selectedProvider ? 'Novo WhatsApp' : 'Nenhum WhatsApp';
  const activeWhatsAppLabel = deviceData?.phone || deviceData?.name || (hasActiveProvider ? 'WhatsApp atual' : 'Novo WhatsApp');
  const currentWhatsAppDetail = hasActiveProvider
    ? activeWhatsAppLabel
    : selectedProvider
      ? 'Configuração em andamento'
      : 'Aguardando conexão';
  const qrInstruction = 'Abra o WhatsApp em Dispositivos conectados e escaneie o código.';

  const pageClass = isDark ? 'bg-brand text-white' : 'bg-brand-canvas text-brand';
  const panelClass = isDark
    ? 'border-white/10 bg-white/[0.06] shadow-[0_22px_55px_rgba(0,0,0,0.22)]'
    : 'border-brand/10 bg-white shadow-[0_22px_55px_rgba(2,3,35,0.08)]';
  const softPanelClass = isDark ? 'border-white/10 bg-white/[0.05]' : 'border-brand/10 bg-brand-canvas';
  const mutedClass = isDark ? 'text-white/55' : 'text-brand/55';
  const subtleClass = isDark ? 'text-white/40' : 'text-brand/40';
  const statusBadgeClass = statusCopy.tone === 'success'
    ? isDark
      ? 'bg-emerald-400/10 text-emerald-200 ring-emerald-400/25'
      : 'bg-emerald-50 text-emerald-700 ring-emerald-200'
    : statusCopy.tone === 'danger'
      ? isDark
        ? 'bg-red-400/10 text-red-200 ring-red-400/25'
        : 'bg-red-50 text-red-700 ring-red-200'
      : statusCopy.tone === 'warning'
        ? isDark
          ? 'bg-amber-400/10 text-amber-200 ring-amber-400/25'
          : 'bg-amber-50 text-amber-700 ring-amber-200'
        : isDark
          ? 'bg-white/10 text-white/70 ring-white/10'
          : 'bg-brand-canvas text-brand/70 ring-brand/10';
  const statusDotClass = statusCopy.tone === 'success'
    ? 'bg-emerald-500'
    : statusCopy.tone === 'danger'
      ? 'bg-red-500'
      : statusCopy.tone === 'warning'
        ? 'bg-amber-500'
        : isDark ? 'bg-white/35' : 'bg-brand/35';

  const operationSteps = [
    {
      label: 'Configurar WhatsApp',
      helper: hasActiveProvider ? activeWhatsAppLabel : 'Defina este WhatsApp',
      done: hasActiveProvider,
      active: selectedProvider === 'waha' && !hasActiveProvider,
    },
    {
      label: 'Parear no celular',
      helper: isConnected ? 'Leitura confirmada' : hasActiveProvider ? 'QR Code ou código disponível' : 'Aguardando configuração',
      done: isConnected,
      active: hasActiveProvider && !isConnected,
    },
    {
      label: 'Liberar operação',
      helper: isConnected ? 'Chat e automações podem usar o canal' : 'Disponível após conectar',
      done: isConnected,
      active: false,
    },
  ];

  const summaryCards = [
    { label: 'Status', value: statusLabel, helper: stateLabel, icon: Activity },
    { label: 'Canal', value: providerLabel, helper: hasActiveProvider ? 'Ativo para esta empresa' : 'Seleção pendente', icon: ShieldCheck },
    { label: 'WhatsApp', value: activeWhatsAppLabel, helper: currentWhatsAppDetail, icon: Wifi },
  ];

  const renderOperationChecklist = () => (
    <div className="space-y-2">
      {operationSteps.map((step) => (
        <div
          key={step.label}
          className={`flex items-start gap-3 rounded-2xl border p-3 ${step.active
            ? isDark ? 'border-amber-400/20 bg-amber-400/10' : 'border-amber-200 bg-amber-50'
            : softPanelClass
            }`}
        >
          <div className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${step.done
            ? isDark ? 'bg-emerald-400/10 text-emerald-200' : 'bg-emerald-50 text-emerald-700'
            : step.active
              ? isDark ? 'bg-amber-400/10 text-amber-200' : 'bg-amber-100 text-amber-700'
              : isDark ? 'bg-white/10 text-white/45' : 'bg-white text-brand/45'
            }`}
          >
            {step.done ? <CheckCircle2 className="h-4 w-4" /> : step.active ? <Clock3 className="h-4 w-4" /> : <span className="h-2 w-2 rounded-full bg-current" />}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold">{step.label}</p>
            <p className={`mt-0.5 text-xs leading-relaxed ${mutedClass}`}>{step.helper}</p>
          </div>
        </div>
      ))}
    </div>
  );

  const renderOperationPanel = () => (
    <aside className={`rounded-2xl border p-4 sm:p-5 ${panelClass}`}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className={`mb-1 text-[10px] font-semibold uppercase ${subtleClass}`}>
            Operação
          </div>
          <h2 className="text-lg font-semibold">WhatsApp atual</h2>
          <p className={`mt-1 text-sm ${mutedClass}`}>As ações abaixo afetam apenas {activeWhatsAppLabel}.</p>
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${statusBadgeClass}`}>
          <span className={`h-2 w-2 rounded-full ${statusDotClass}`} />
          {statusLabel}
        </span>
      </div>

      {renderOperationChecklist()}

      {hasActiveProvider && !isLoading && (
        <div className={`mt-4 rounded-2xl border p-3 ${softPanelClass}`}>
          <p className={`mb-3 text-[10px] font-semibold uppercase ${subtleClass}`}>
            Ações
          </p>
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => {
                if (currentProvider === 'waha' && !isConnected) {
                  handleRefreshQRCode();
                } else {
                  handleFetchAllData(undefined, true);
                }
              }}
              disabled={isLoading}
              className={agentivePrimaryButtonClass('w-full px-4 py-2.5 font-semibold')}
            >
              <RefreshCcw className="h-4 w-4" />
              {currentProvider === 'waha' && !isConnected ? 'Atualizar QR Code deste WhatsApp' : 'Atualizar este WhatsApp'}
            </button>

            {isConnected && (
              <button
                type="button"
                onClick={() => setShowDisconnectModal(true)}
                disabled={isLoading}
                className={`inline-flex w-full items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-semibold transition disabled:opacity-50 ${isDark
                  ? 'border-amber-400/20 bg-amber-400/10 text-amber-200 hover:bg-amber-400/15'
                  : 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100'
                  }`}
              >
                <Power className="h-4 w-4" />
                Desconectar este WhatsApp
              </button>
            )}

            {(currentProvider === 'zapi' || currentProvider === 'waha') && (
              <button
                type="button"
                onClick={() => setShowResetModal(true)}
                disabled={isLoading}
                className={`inline-flex w-full items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-semibold transition disabled:opacity-50 ${isDark
                  ? 'border-red-400/20 bg-red-400/10 text-red-200 hover:bg-red-400/15'
                  : 'border-red-200 bg-red-50 text-red-700 hover:bg-red-100'
                  }`}
              >
                <RotateCcw className="h-4 w-4" />
                Resetar este WhatsApp
              </button>
            )}
          </div>
        </div>
      )}
    </aside>
  );

  const renderProviderSelection = () => (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className={`rounded-2xl border p-4 sm:p-5 ${panelClass}`}>
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-center">
          <div>
            <div className={`mb-2 text-[10px] font-semibold uppercase ${subtleClass}`}>
              Primeiro acesso
            </div>
            <h2 className="text-xl font-semibold sm:text-2xl">Conectar WhatsApp</h2>
            <p className={`mt-2 max-w-2xl text-sm leading-relaxed ${mutedClass}`}>
              Adicione o número que será usado nos chats, follow-ups e fluxos automatizados.
            </p>
          </div>

          <button
            type="button"
            onClick={() => setSelectedProvider('waha')}
            className={`group rounded-2xl border p-4 text-left transition-all hover:-translate-y-0.5 hover:shadow-[0_18px_40px_rgba(2,3,35,0.10)] ${softPanelClass}`}
          >
            <div className="flex items-start gap-3">
              <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
                <Smartphone className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="text-base font-semibold">WhatsApp</h3>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${isDark ? 'bg-white/10 text-white/70' : 'bg-white text-brand/55'}`}>
                    Padrão
                  </span>
                </div>
                <p className={`mt-1 text-sm leading-relaxed ${mutedClass}`}>Conexão por QR Code ou código para atendimento e automações.</p>
                <span className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white transition-colors group-hover:bg-brand/90 sm:w-auto">
                  Conectar WhatsApp
                </span>
              </div>
            </div>
          </button>
        </div>
      </section>

      {renderOperationPanel()}
    </div>
  );

  const renderWahaForm = () => (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className={`rounded-2xl border p-4 sm:p-5 ${panelClass}`}>
        <div className="mb-5 flex items-start gap-3">
          <button
            type="button"
            onClick={() => setSelectedProvider(null)}
            className={agentiveIconButtonClass(isDark, 'neutral')}
            aria-label="Voltar para seleção de WhatsApp"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div className="min-w-0">
            <div className={`mb-1 text-[10px] font-semibold uppercase ${subtleClass}`}>
              Novo WhatsApp
            </div>
            <h2 className="text-xl font-semibold">Configurar WhatsApp</h2>
            <p className={`mt-1 text-sm ${mutedClass}`}>{branding.appName} prepara automaticamente uma conexão exclusiva para sua empresa.</p>
          </div>
        </div>

        <form onSubmit={handleConnectWaha} className="space-y-5">
          <div className={`grid gap-3 md:grid-cols-2`}>
            <div className={`rounded-2xl border p-4 ${softPanelClass}`}>
              <QrCode className={`mb-3 h-5 w-5 ${mutedClass}`} />
              <p className="text-sm font-semibold">QR Code automático</p>
              <p className={`mt-1 text-xs leading-relaxed ${mutedClass}`}>A conexão gera QR Code para pareamento.</p>
            </div>
            <div className={`rounded-2xl border p-4 ${softPanelClass}`}>
              <KeyRound className={`mb-3 h-5 w-5 ${mutedClass}`} />
              <p className="text-sm font-semibold">Código de pareamento</p>
              <p className={`mt-1 text-xs leading-relaxed ${mutedClass}`}>O número também pode receber um código para digitar no celular.</p>
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className={agentivePrimaryButtonClass('w-full px-5 py-3 font-semibold')}
          >
            <Wifi className="h-4 w-4" />
            {isLoading ? 'Configurando WhatsApp...' : 'Criar conexão WhatsApp'}
          </button>
        </form>
      </section>

      {renderOperationPanel()}
    </div>
  );

  const renderQrPanel = () => (
    <section className={currentProvider === 'zapi' ? agentivePanelClass(isDark, 'p-4 sm:p-5') : `rounded-2xl border p-4 sm:p-5 ${panelClass}`}>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
            <QrCode className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className={`mb-1 text-[10px] font-semibold uppercase ${subtleClass}`}>
              Pareamento
            </div>
            <h2 className="text-xl font-semibold">QR Code WhatsApp</h2>
            <p className={`mt-1 text-sm ${mutedClass}`}>{qrInstruction}</p>
          </div>
        </div>
        <span className={`inline-flex w-fit items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${statusBadgeClass}`}>
          <span className={`h-2 w-2 rounded-full ${statusDotClass}`} />
          {qrcodeBase64 ? 'Pronto para escanear' : error ? 'Erro no QR' : `Tentativa ${qrAttempts}/${currentProvider === 'waha' ? 10 : 3}`}
        </span>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(260px,360px)_minmax(0,1fr)] lg:items-center">
        <div className="flex justify-center lg:justify-start">
          <div className={`flex aspect-square w-full max-w-[300px] items-center justify-center rounded-[24px] border p-3 sm:max-w-[320px] sm:p-5 ${error
            ? isDark ? 'border-red-400/20 bg-red-400/10' : 'border-red-200 bg-red-50'
            : softPanelClass
            }`}
          >
            {qrcodeBase64 ? (
              <img src={qrcodeBase64} alt="QR Code do WhatsApp" className="h-auto w-full max-w-[240px] rounded-xl bg-white sm:max-w-[264px]" />
            ) : error ? (
              <div className="text-center">
                <AlertCircle className={`mx-auto h-10 w-10 ${isDark ? 'text-red-300' : 'text-red-600'}`} />
                <p className={`mt-3 text-sm font-semibold ${isDark ? 'text-red-200' : 'text-red-700'}`}>QR indisponível</p>
              </div>
            ) : (
              <div className="text-center">
                <Loader2 className="mx-auto h-9 w-9 animate-spin text-brand" />
                <p className={`mt-3 text-sm font-semibold ${mutedClass}`}>Gerando QR Code</p>
              </div>
            )}
          </div>
        </div>

        <div className="space-y-3">
          <div className={`rounded-2xl border p-4 ${softPanelClass}`}>
            <p className="text-sm font-semibold">{qrcodeBase64 ? 'Escaneie agora' : error ? 'Aguardando nova tentativa' : 'Preparando conexão'}</p>
            <p className={`mt-1 text-sm leading-relaxed ${mutedClass}`}>
              {qrcodeBase64
                ? qrInstruction
                : error
                  ? 'Tente atualizar o QR Code ou resetar a conexão se o estado persistir.'
                  : currentProvider === 'waha'
                    ? `Aguardando QR Code deste WhatsApp... tentativa ${qrAttempts}/10.`
                    : 'Gerando QR Code deste WhatsApp.'}
            </p>
          </div>

          {qrAttempts >= 10 && !qrcodeBase64 && (
            <button
              type="button"
              onClick={handleManualRetry}
              className={agentiveSecondaryButtonClass(isDark, 'w-full px-4 py-2.5 font-semibold')}
            >
              <RefreshCcw className="h-4 w-4" />
              Tentar novamente
            </button>
          )}

          {currentProvider === 'waha' && (
            <form onSubmit={handleRequestPairingCode} className={`rounded-2xl border p-4 ${softPanelClass}`}>
              <div className="flex items-start gap-3">
                <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${isDark ? 'bg-white/10 text-white' : 'bg-white text-brand'}`}>
                  <KeyRound className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold">Conectar por código</p>
                  <p className={`mt-1 text-xs leading-relaxed ${mutedClass}`}>
                    Informe o número com DDI e digite o código no WhatsApp do celular.
                  </p>
                </div>
              </div>

              <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                <div className="relative min-w-0 flex-1">
                  <Phone className={`pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${mutedClass}`} />
                  <input
                    type="tel"
                    value={pairingPhoneNumber}
                    onChange={(e) => setPairingPhoneNumber(e.target.value.replace(/\D/g, ''))}
                    className={agentiveInputClass(isDark, 'pl-9 pr-4 py-2.5')}
                    placeholder="5500000000007"
                    disabled={isPairingCodeLoading || isLoading}
                  />
                </div>
                <button
                  type="submit"
                  disabled={isPairingCodeLoading || isLoading}
                  className={agentiveSecondaryButtonClass(isDark, 'w-full shrink-0 px-4 py-2.5 font-semibold sm:w-auto')}
                >
                  {isPairingCodeLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
                  Gerar código
                </button>
              </div>

              {pairingCode && (
                <div className={`mt-4 rounded-2xl border p-4 ${isDark ? 'border-emerald-400/20 bg-emerald-400/10' : 'border-emerald-200 bg-emerald-50'}`}>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className={`text-xs font-semibold uppercase ${isDark ? 'text-emerald-100/70' : 'text-emerald-700/70'}`}>
                        Código de pareamento
                      </p>
                      <p className={`mt-1 font-mono text-2xl font-semibold ${isDark ? 'text-emerald-100' : 'text-emerald-800'}`}>
                        {pairingCode}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={handleCopyPairingCode}
                      className={`inline-flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm font-semibold transition ${isDark
                        ? 'border-emerald-300/20 bg-emerald-300/10 text-emerald-100 hover:bg-emerald-300/15'
                        : 'border-emerald-200 bg-white text-emerald-800 hover:bg-emerald-100'
                        }`}
                    >
                      <Copy className="h-4 w-4" />
                      Copiar
                    </button>
                  </div>
                </div>
              )}

              <p className={`mt-3 text-xs leading-relaxed ${mutedClass}`}>
                Se o código não funcionar, escaneie o QR Code acima.
              </p>
            </form>
          )}
        </div>
      </div>
    </section>
  );

  const renderConnectedPanel = () => (
    <section className={`rounded-2xl border p-4 sm:p-5 ${panelClass}`}>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-center">
        <div className="flex min-w-0 items-start gap-4">
          {deviceData?.imgUrl ? (
            <img
              src={deviceData.imgUrl}
              alt="Perfil"
              className="h-16 w-16 shrink-0 rounded-2xl border border-brand/10 object-cover shadow-[0_12px_30px_rgba(2,3,35,0.12)]"
            />
          ) : (
            <div className={`grid h-16 w-16 shrink-0 place-items-center rounded-2xl ${isDark ? 'bg-white/10 text-white' : 'bg-brand text-white'}`}>
              <Smartphone className="h-7 w-7" />
            </div>
          )}
          <div className="min-w-0">
            <div className={`mb-1 text-[10px] font-semibold uppercase ${subtleClass}`}>
              Canal ativo
            </div>
            <h2 className="truncate text-2xl font-semibold">{deviceData?.name || 'Dispositivo conectado'}</h2>
            <div className={`mt-2 flex flex-wrap gap-2 text-xs ${mutedClass}`}>
              <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 ${softPanelClass}`}>
                <Smartphone className="h-3.5 w-3.5" />
                {deviceData?.phone || 'Telefone sincronizado'}
              </span>
              <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 ${softPanelClass}`}>
                <Wifi className="h-3.5 w-3.5" />
                {deviceData?.device?.device_model || 'WhatsApp'}
              </span>
            </div>
          </div>
        </div>

        <div className={`rounded-2xl border p-4 ${isDark ? 'border-emerald-400/20 bg-emerald-400/10' : 'border-emerald-200 bg-emerald-50'}`}>
          <div className="flex items-center gap-3">
            <CheckCircle2 className={`h-8 w-8 ${isDark ? 'text-emerald-200' : 'text-emerald-700'}`} />
            <div>
              <p className={`text-sm font-semibold ${isDark ? 'text-emerald-100' : 'text-emerald-800'}`}>Conexão pronta</p>
              <p className={`mt-1 text-xs leading-relaxed ${isDark ? 'text-emerald-100/70' : 'text-emerald-700/70'}`}>
                O canal está disponível para conversas e automações.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );

  return (
    <div className={`flex min-h-screen w-full justify-center px-3 pb-[calc(8.5rem+env(safe-area-inset-bottom))] pt-3 sm:px-6 sm:pb-28 sm:pt-4 lg:px-8 xl:px-10 2xl:px-12 ${pageClass}`}>
      <div className="w-full max-w-screen-2xl space-y-5">
        <header className={`rounded-2xl border p-4 sm:p-5 ${panelClass}`}>
          <div className="grid gap-5 xl:grid-cols-[minmax(260px,1fr)_minmax(360px,520px)] xl:items-end">
            <div>
              <div className={`mb-2 text-[10px] font-semibold uppercase ${subtleClass}`}>
                Conexões
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-semibold sm:text-3xl">WhatsApp</h1>
                <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${statusBadgeClass}`}>
                  <span className={`h-2 w-2 rounded-full ${statusDotClass}`} />
                  {statusLabel}
                </span>
                <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${isDark ? 'bg-white/10 text-white/70 ring-white/10' : 'bg-brand-canvas text-brand/60 ring-brand/10'}`}>
                  {providerLabel}
                </span>
              </div>
              <p className={`mt-2 max-w-3xl text-sm leading-relaxed ${mutedClass}`}>
                Conecte e monitore o WhatsApp usado pelos atendimentos, follow-ups e automações.
              </p>
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              {summaryCards.map(({ label, value, helper, icon: Icon }) => (
                <div key={label} className={`min-w-0 rounded-2xl border p-3 ${softPanelClass}`}>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className={`truncate text-[10px] font-semibold uppercase ${subtleClass}`}>{label}</span>
                    <Icon className={`h-4 w-4 shrink-0 ${mutedClass}`} />
                  </div>
                  <p className="truncate text-sm font-semibold">{value}</p>
                  <p className={`mt-1 truncate text-xs ${mutedClass}`}>{helper}</p>
                </div>
              ))}
            </div>
          </div>
        </header>

        {/* Alert Messages */}
        {message && (
          <AgentiveAlert variant="success" title="Status atualizado" onClose={() => setMessage('')}>
            {message}
          </AgentiveAlert>
        )}

        {error && (
          <AgentiveAlert variant="error" title="Não foi possível concluir a ação" onClose={() => setError('')}>
            {error}
          </AgentiveAlert>
        )}

        {!currentProvider && !selectedProvider && renderProviderSelection()}

        {!currentProvider && selectedProvider === 'waha' && renderWahaForm()}

        {currentProvider && (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="space-y-5">
              {isConnected ? renderConnectedPanel() : renderQrPanel()}

              {webhookUrl && currentProvider === 'zapi' && (
                <section className={agentivePanelClass(isDark, 'p-4 sm:p-5')}>
                  <div className="mb-3 flex items-center gap-2">
                    <ShieldCheck className={`h-4 w-4 ${mutedClass}`} />
                    <h3 className="text-base font-semibold">URL do Webhook</h3>
                  </div>
                  <div className={`rounded-2xl border p-4 ${softPanelClass}`}>
                    <p className={`break-all font-mono text-sm ${isDark ? 'text-white/75' : 'text-brand/75'}`}>
                      {webhookUrl}
                    </p>
                  </div>
                </section>
              )}
            </div>

            {renderOperationPanel()}
          </div>
        )}

        <ConfirmDeleteModal
          isOpen={showDisconnectModal}
          onClose={() => setShowDisconnectModal(false)}
          onConfirm={handleDisconnect}
          title="Desconectar WhatsApp?"
          message={currentProvider === 'waha'
            ? `A conexão de ${activeWhatsAppLabel} será fechada e será necessário escanear o QR Code novamente.`
            : 'A conexão será fechada e será necessário escanear o QR Code novamente.'}
          confirmText="Desconectar este WhatsApp"
          variant="warning"
        />

        <ConfirmDeleteModal
          isOpen={showResetModal}
          onClose={() => setShowResetModal(false)}
          onConfirm={handleResetConfig}
          title="Resetar conexão?"
          message={currentProvider === 'waha'
            ? `A conexão de ${activeWhatsAppLabel} será removida e será necessário configurar este WhatsApp novamente.`
            : 'A configuração deste WhatsApp será removida e será necessário configurar tudo novamente.'}
          confirmText="Resetar este WhatsApp"
        />

        {/* Loading Overlay */}
        {isLoading && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand/45 backdrop-blur-sm">
            <div className={`flex items-center rounded-2xl border p-6 shadow-2xl ${isDark ? 'border-white/10 bg-brand' : 'border-brand/10 bg-white'
              }`}>
              <Loader2 className="mr-4 h-7 w-7 animate-spin text-brand" />
              <p className={`text-lg font-semibold ${isDark ? 'text-white' : 'text-brand'}`}>
                Processando...
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default WhatsAppConnectPage;
