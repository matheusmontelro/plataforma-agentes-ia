import api from './api.ts';

export type MoneyValue = number | string;

export interface CustomerBillingSummary {
  id: number;
  contact_id: number;
  company_id: number;
  nome: string;
  telefone: string;
  email?: string | null;
  cpf_cnpj?: string | null;
  mobile_phone?: string | null;
  postal_code?: string | null;
  address?: string | null;
  address_number?: string | null;
  complement?: string | null;
  province?: string | null;
  city?: string | null;
  state?: string | null;
  status: string;
  categoria: string;
  convertido_de_lead_id?: number | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
  mrr: MoneyValue;
  total_paid: MoneyValue;
  open_amount: MoneyValue;
  overdue_amount: MoneyValue;
  active_contracts: number;
  open_invoices: number;
  overdue_invoices: number;
  next_invoice_date?: string | null;
  last_payment_date?: string | null;
  churned_at?: string | null;
}

export interface CustomerBillingResponse {
  id: number;
  contact_id: number;
  company_id: number;
  nome: string;
  telefone: string;
  email?: string | null;
  cpf_cnpj?: string | null;
  mobile_phone?: string | null;
  postal_code?: string | null;
  address?: string | null;
  address_number?: string | null;
  complement?: string | null;
  province?: string | null;
  city?: string | null;
  state?: string | null;
  status: string;
  categoria: string;
  convertido_de_lead_id?: number | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CustomerRevenueOverview {
  total_customers: number;
  active_customers: number;
  churned_customers: number;
  mrr: MoneyValue;
  open_amount: MoneyValue;
  overdue_amount: MoneyValue;
  paid_amount: MoneyValue;
  open_invoices: number;
  overdue_invoices: number;
}

export interface BillingContractSummary {
  id: number;
  customer_id?: number | null;
  contact_id?: number | null;
  lead_id?: number | null;
  status: string;
  start_date: string;
  end_date?: string | null;
  billing_anchor_date?: string | null;
  next_invoice_date?: string | null;
  canceled_at?: string | null;
  cancellation_reason?: string | null;
  total_value: MoneyValue;
  total_paid: MoneyValue;
  mrr: MoneyValue;
  is_recurring: boolean;
  payment_method?: string | null;
  notes?: string | null;
  external_id?: string | null;
  gateway?: string | null;
}

export interface BillingInvoiceSummary {
  id: number;
  customer_id?: number | null;
  contract_id?: number | null;
  invoice_number: string;
  external_id?: string | null;
  recurrence_key?: string | null;
  status: string;
  issue_date: string;
  due_date?: string | null;
  paid_at?: string | null;
  total: MoneyValue;
  amount_paid: MoneyValue;
  amount_due: MoneyValue;
  payment_method?: string | null;
  customer_name?: string | null;
  installment_number?: number | null;
  installments?: number | null;
  gateway?: string | null;
}

export interface BillingInvoiceDetail extends BillingInvoiceSummary {
  notes?: string | null;
}

export interface BillingPaymentSummary {
  id: number;
  customer_id?: number | null;
  contract_id?: number | null;
  invoice_id?: number | null;
  type: string;
  status: string;
  amount: MoneyValue;
  payment_method?: string | null;
  payment_date?: string | null;
  gateway?: string | null;
}

export interface ManagedCompanySummary {
  id: number;
  owner_company_id: number;
  customer_id: number;
  managed_company_id: number;
  name: string;
  name_company?: string | null;
  cnpj?: string | null;
  logo_url?: string | null;
  trial_days: number;
  trial_started_at?: string | null;
  trial_ends_at?: string | null;
  lifecycle_status: string;
  trial_days_remaining?: number | null;
  trial_progress_percent?: number | null;
  is_trial_expired?: boolean;
  ai_credit_balance?: MoneyValue;
  trial_credits_granted?: MoneyValue;
  created_at: string;
}

export interface CustomerBillingDetail extends CustomerBillingSummary {
  contracts: BillingContractSummary[];
  invoices: BillingInvoiceSummary[];
  payments: BillingPaymentSummary[];
  managed_companies: ManagedCompanySummary[];
}

export interface BillingLineItemCreate {
  plan_id?: number | null;
  description: string;
  quantity: number;
  unit_price: number;
  discount_percent?: number;
  discount_amount?: number;
  billing_interval:
    | 'once'
    | 'weekly'
    | 'biweekly'
    | 'monthly'
    | 'bimonthly'
    | 'quarterly'
    | 'semiannually'
    | 'yearly';
  sessions_total?: number | null;
}

export interface CustomerSaleCreate {
  lead_id?: number | null;
  contact_id?: number | null;
  start_date?: string;
  end_date?: string;
  payment_method?: string | null;
  installments: number;
  notes?: string;
  items: BillingLineItemCreate[];
  total_value?: number;
  create_initial_invoice: boolean;
  initial_invoice_due_date?: string;
  initial_payment_amount?: number;
  initial_payment_method?: string | null;
  initial_payment_date?: string;
  initial_payment_installment?: number;
}

export interface PlanResponse {
  id: number;
  company_id: number;
  name: string;
  code?: string | null;
  description?: string | null;
  price: MoneyValue;
  currency: string;
  billing_interval: string;
  billing_interval_count: number;
  trial_period_days: number;
  is_active: boolean;
  category?: string | null;
}

export interface PlanCreate {
  name: string;
  code?: string;
  description?: string;
  price: number;
  currency?: string;
  billing_interval: 'once' | 'monthly' | 'quarterly' | 'yearly';
  billing_interval_count?: number;
  trial_period_days?: number;
  is_active?: boolean;
}

export interface PlanUpdate {
  name?: string;
  code?: string | null;
  description?: string | null;
  price?: number;
  currency?: string;
  billing_interval?: 'once' | 'monthly' | 'quarterly' | 'yearly';
  billing_interval_count?: number;
  trial_period_days?: number;
  is_active?: boolean;
}

export interface InvoiceCreate {
  contract_id?: number | null;
  contact_id?: number | null;
  customer_id?: number | null;
  due_date?: string | null;
  payment_method?: string | null;
  notes?: string | null;
  line_items: Array<{
    description: string;
    quantity: number;
    unit_price: number;
    discount_amount?: number;
    type?: 'subscription' | 'one_time' | 'refund';
    period_start?: string | null;
    period_end?: string | null;
    plan_id?: number | null;
    contract_item_id?: number | null;
  }>;
}

export interface InvoiceUpdate {
  due_date?: string | null;
  payment_method?: string | null;
  notes?: string | null;
}

export interface CustomerBillingProfilePayload {
  cpf_cnpj?: string | null;
  mobile_phone?: string | null;
  postal_code?: string | null;
  address?: string | null;
  address_number?: string | null;
  complement?: string | null;
  province?: string | null;
  city?: string | null;
  state?: string | null;
}

export interface CepLookupResponse {
  postal_code: string;
  address?: string | null;
  complement?: string | null;
  province?: string | null;
  city?: string | null;
  state?: string | null;
}

export interface CustomerCreate extends CustomerBillingProfilePayload {
  contact_id?: number | null;
  lead_id?: number | null;
  name?: string;
  phone?: string;
  email?: string | null;
  notes?: string | null;
}

export interface CustomerUpdate extends CustomerBillingProfilePayload {
  name?: string;
  phone?: string;
  email?: string | null;
  status?: 'ativo' | 'inativo' | 'bloqueado';
  categoria?: 'cliente' | 'lead_qualificado' | 'prospect' | 'ex_cliente';
  notes?: string | null;
}

const getAuthIds = () => {
  const clientId = parseInt(localStorage.getItem('client_id') || sessionStorage.getItem('client_id') || '0', 10);
  const companyId = parseInt(
    (localStorage.getItem('company_id') || localStorage.getItem('clinic_id')) ||
    (sessionStorage.getItem('company_id') || sessionStorage.getItem('clinic_id')) ||
    '0',
    10
  );
  const userType = localStorage.getItem('user_type') || sessionStorage.getItem('user_type');
  const effectiveClientId = userType === 'master_user'
    ? parseInt(localStorage.getItem('master_client_id') || sessionStorage.getItem('master_client_id') || '0', 10)
    : clientId;

  if (!effectiveClientId || !companyId) {
    throw new Error('Informações de autenticação não encontradas');
  }

  return { clientId: effectiveClientId, companyId };
};

const billingBase = () => {
  const { clientId, companyId } = getAuthIds();
  return `/api/clients/${clientId}/companies/${companyId}`;
};

export const customerBillingApi = {
  async listCustomers(search?: string): Promise<CustomerBillingSummary[]> {
    const params = new URLSearchParams();
    if (search?.trim()) params.set('search', search.trim());
    const query = params.toString();
    const response = await api.get(`${billingBase()}/customers/${query ? `?${query}` : ''}`);
    return response.data;
  },

  async getOverview(): Promise<CustomerRevenueOverview> {
    const response = await api.get(`${billingBase()}/customers/overview`);
    return response.data;
  },

  async getCustomer(customerId: number): Promise<CustomerBillingDetail> {
    const response = await api.get(`${billingBase()}/customers/${customerId}`);
    return response.data;
  },

  async createCustomer(payload: CustomerCreate): Promise<CustomerBillingResponse> {
    const response = await api.post(`${billingBase()}/customers/`, payload);
    return response.data;
  },

  async updateCustomer(customerId: number, payload: CustomerUpdate): Promise<CustomerBillingResponse> {
    const response = await api.put(`${billingBase()}/customers/${customerId}`, payload);
    return response.data;
  },

  async deleteCustomer(customerId: number): Promise<void> {
    await api.delete(`${billingBase()}/customers/${customerId}`);
  },

  async lookupPostalCode(postalCode: string): Promise<CepLookupResponse> {
    const response = await api.get(`${billingBase()}/customers/address/cep/${postalCode.replace(/\D/g, '')}`);
    return response.data;
  },

  async createCustomerContract(customerId: number, payload: CustomerSaleCreate): Promise<BillingContractSummary> {
    const response = await api.post(`${billingBase()}/customers/${customerId}/contracts`, payload);
    return response.data;
  },

  async createSaleFromLead(leadId: number, payload: CustomerSaleCreate): Promise<BillingContractSummary> {
    const response = await api.post(`${billingBase()}/customers/sales/from-lead/${leadId}`, payload);
    return response.data;
  },

  async createSaleFromContact(contactId: number, payload: CustomerSaleCreate): Promise<BillingContractSummary> {
    const response = await api.post(`${billingBase()}/customers/sales/from-contact/${contactId}`, payload);
    return response.data;
  },

  async generateNextInvoice(contractId: number, dueDate?: string): Promise<BillingInvoiceSummary> {
    const response = await api.post(`${billingBase()}/customers/contracts/${contractId}/generate-next-invoice`, {
      due_date: dueDate || undefined,
    });
    return response.data;
  },

  async cancelContract(contractId: number, reason?: string): Promise<BillingContractSummary> {
    const response = await api.post(`${billingBase()}/customers/contracts/${contractId}/cancel`, { reason });
    return response.data;
  },

  async listManagedCompanies(customerId: number): Promise<ManagedCompanySummary[]> {
    const response = await api.get(`${billingBase()}/customers/${customerId}/managed-companies`);
    return response.data;
  },

  async linkManagedCompany(customerId: number, managedCompanyId: number): Promise<ManagedCompanySummary> {
    const response = await api.post(`${billingBase()}/customers/${customerId}/managed-companies`, {
      managed_company_id: managedCompanyId,
    });
    return response.data;
  },

  async unlinkManagedCompany(customerId: number, linkId: number): Promise<void> {
    await api.delete(`${billingBase()}/customers/${customerId}/managed-companies/${linkId}`);
  },

  async listInvoices(customerId?: number): Promise<BillingInvoiceSummary[]> {
    const params = new URLSearchParams();
    if (customerId) params.set('customer_id', String(customerId));
    const query = params.toString();
    const response = await api.get(`${billingBase()}/invoices/${query ? `?${query}` : ''}`);
    return response.data;
  },

  async createInvoice(payload: InvoiceCreate): Promise<BillingInvoiceSummary> {
    const response = await api.post(`${billingBase()}/invoices/`, payload);
    return response.data;
  },

  async getInvoice(invoiceId: number): Promise<BillingInvoiceDetail> {
    const response = await api.get(`${billingBase()}/invoices/${invoiceId}`);
    return response.data;
  },

  async updateInvoice(invoiceId: number, payload: InvoiceUpdate): Promise<BillingInvoiceDetail> {
    const response = await api.put(`${billingBase()}/invoices/${invoiceId}`, payload);
    return response.data;
  },

  async deleteInvoice(invoiceId: number): Promise<void> {
    await api.delete(`${billingBase()}/invoices/${invoiceId}`);
  },

  async markInvoicePaid(invoiceId: number, paymentMethod?: string): Promise<BillingInvoiceSummary> {
    const response = await api.post(`${billingBase()}/invoices/${invoiceId}/mark-paid`, {
      payment_method: paymentMethod,
    });
    return response.data;
  },

  async listPlans(): Promise<PlanResponse[]> {
    const response = await api.get(`${billingBase()}/plans/`);
    return response.data;
  },

  async createPlan(payload: PlanCreate): Promise<PlanResponse> {
    const response = await api.post(`${billingBase()}/plans/`, {
      currency: 'BRL',
      billing_interval_count: 1,
      trial_period_days: 0,
      is_active: true,
      ...payload,
    });
    return response.data;
  },

  async updatePlan(planId: number, payload: PlanUpdate): Promise<PlanResponse> {
    const response = await api.put(`${billingBase()}/plans/${planId}`, {
      currency: 'BRL',
      billing_interval_count: 1,
      ...payload,
    });
    return response.data;
  },
};

export default customerBillingApi;
