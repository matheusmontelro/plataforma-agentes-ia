// src/App.tsx

import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { ThemeProvider } from './contexts/ThemeContext.tsx';
import Login from './pages/Login.tsx';
import ResetPassword from './pages/ResetPassword.tsx';
import NewCompanyAdminPage from './pages/CreateNewCompanyPage.tsx';
import PrivateRoute from './components/PrivateRoute.tsx';
import ProtectedLayout from './components/ProtectedLayout.tsx';
import Dashboard from './pages/Dashboard.tsx';
import ChatPage4 from './pages/Chat.tsx';

import { FlowControlPanel } from './components/FlowControlPanel.tsx';
import AgentsPage from './pages/Agents.tsx';
import AgentBuilder from './pages/AgentBuilder.tsx';
import CompanyConfigPage from './pages/CompanyConfig.tsx';
import WhatsAppConnectPage from './pages/WhatsAppConnect.tsx';

// <-- Importe as novas páginas -->
import SupportGroupIntegration from './pages/SupportGroupIntegration.tsx';
import CalendarConfigPage from './pages/CalendarConfigPage.tsx';
import WhatsAppCampaignsPage from './pages/WhatsAppCampaignsPage.tsx';

import ContactsList from './pages/ContactsList.tsx';
import TagsManagement from './pages/TagsManagement.tsx';
import ReferralCampaigns from './pages/ReferralCampaigns.tsx';
import CRMv4 from './pages/CRM_v4.tsx';
import LeadCustomFieldsConfig from './pages/LeadCustomFieldsConfig.tsx';
import WebhookManager from './pages/WebhookManager.tsx';
import FlowList from './pages/FlowList.tsx';
import FlowBuilder from './pages/FlowBuilder.tsx';
import MediaManagement from './pages/MediaManagement.tsx';
import AIProviderPage from './pages/AIProviderPage.tsx';
import AccountProfile from './pages/AccountProfile.tsx';
import CustomerManagement from './pages/CustomerManagement.tsx';
import IntegrationsHub from './pages/IntegrationsHub.tsx';
import TelegramIntegration from './pages/TelegramIntegration.tsx';

const AgendaIntegrationRedirect: React.FC = () => {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  params.set('tab', 'integrations');

  return <Navigate to={`/calendar-config?${params.toString()}`} replace />;
};

const App: React.FC = () => {
  return (
    <div className="app-container">
      <ThemeProvider>
        <Router>
          <div className="min-h-screen bg-surface-secondary">
            <Routes>
              {/* Rotas públicas */}
              <Route path="/" element={<Login />} />
              <Route path="/login" element={<Login />} />
              <Route path="/reset-password" element={<ResetPassword />} />

              {/* Rotas privadas */}
              <Route element={<PrivateRoute />}>
                <Route path="/new-company-admin" element={<NewCompanyAdminPage />} />
                <Route path="/new-clinic-admin" element={<Navigate to="/new-company-admin" replace />} />

                {/* Layout protegido */}
                <Route element={<ProtectedLayout />}>
                  {/* Dashboard principal */}
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/dashboard/ads" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/dashboard/metrics" element={<Navigate to="/dashboard" replace />} />

                  {/* CRM e Contatos */}
                  <Route path="/crm" element={<CRMv4 />} />
                  <Route path="/contacts" element={<ContactsList />} />
                  <Route path="/tags" element={<TagsManagement />} />
                  <Route path="/config/midias" element={<MediaManagement />} />
                  <Route path="/chat" element={<ChatPage4 />} />
                  <Route path="/customers" element={<CustomerManagement />} />
                  <Route path="/customers/invoices" element={<CustomerManagement />} />
                  <Route path="/customers/plans" element={<CustomerManagement />} />
                  <Route path="/customers/revenue" element={<CustomerManagement />} />

                  {/* Automação centralizada */}
                  <Route path="/follow-up/*" element={<Navigate to="/flows" replace />} />

                  {/* Configurações da Empresa */}
                  <Route path="/account/profile" element={<AccountProfile />} />
                  <Route path="/company" element={<CompanyConfigPage />} />
                  <Route path="/company/ai-provider" element={<AIProviderPage />} />
                  <Route path="/company/ai-credits" element={<Navigate to="/company/ai-provider" replace />} />
                  <Route path="/company/controle-fluxos" element={<FlowControlPanel />} />
                  <Route path="/company/custom-fields" element={<LeadCustomFieldsConfig />} />
                  <Route path="/clinic" element={<Navigate to="/company" replace />} />
                  <Route path="/clinic/controle-fluxos" element={<Navigate to="/company/controle-fluxos" replace />} />
                  <Route path="/clinic/custom-fields" element={<Navigate to="/company/custom-fields" replace />} />

                  {/* Integrações */}
                  <Route path="/whatsapp" element={<WhatsAppConnectPage />} />
                  <Route path="/integrations" element={<IntegrationsHub />} />
                  <Route path="/integrations/telegram" element={<TelegramIntegration />} />
                  <Route path="/campaigns/whatsapp" element={<WhatsAppCampaignsPage />} />

                  {/* Configurações de IA */}
                  <Route path="/agents" element={<AgentsPage />} />
                  <Route path="/agents/editor/:workforceId" element={<AgentBuilder />} />
                  <Route path="/prompt" element={<Navigate to="/agents" replace />} />
                  <Route path="/prompt/agenda" element={<AgendaIntegrationRedirect />} />
                  <Route path="/prompt/support-group" element={<SupportGroupIntegration />} />
                  <Route path="/prompt/indicacoes" element={<ReferralCampaigns />} />
                  <Route path="/webhooks" element={<WebhookManager />} />
                  <Route path="/flows" element={<FlowList />} />
                  <Route path="/flows/editor/:flowId" element={<FlowBuilder />} />

                  {/* Calendar Config */}
                  <Route path="/calendar-config" element={<CalendarConfigPage />} />


                </Route>
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        </Router>
      </ThemeProvider>
    </div>
  );
};

export default App;
