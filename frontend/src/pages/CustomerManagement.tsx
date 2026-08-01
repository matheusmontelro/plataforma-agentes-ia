import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowUpDown,
  Ban,
  BarChart3,
  Building2,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  CreditCard,
  ExternalLink,
  FileText,
  Loader2,
  Package,
  Pencil,
  Plus,
  Receipt,
  RefreshCw,
  Repeat,
  Search,
  Trash2,
  TrendingDown,
  UserPlus,
  Users,
} from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveAlert,
  AgentiveConfirmModal,
  AgentiveEmptyState,
  agentiveInputClass,
  agentiveLabelClass,
  agentivePanelClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
  agentiveTextareaClass,
} from '../components/AgentiveUI.tsx';
import {
  BillingContractSummary,
  BillingInvoiceDetail,
  BillingInvoiceSummary,
  CustomerBillingDetail,
  CustomerBillingSummary,
  ManagedCompanySummary,
  CustomerRevenueOverview,
  PlanResponse,
  customerBillingApi,
} from '../services/customerBillingApi.ts';
import { getContacts, selectActiveCompany, type Contact } from '../services/api.ts';
import { branding } from '../config/branding.ts';
import styles from './CustomerManagement.module.css';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

type Section = 'customers' | 'invoices' | 'plans' | 'revenue';
type SaleStep = 'contact' | 'customer' | 'sale';
type SaleFlowMode = 'customer' | 'sale';
type CustomerDetailTab = 'overview' | 'workspaces' | 'contracts' | 'invoices';
type InvoiceChargeMode = 'payment' | 'subscription';

type CustomerProfileForm = {
  contactId: string;
  leadId: string;
  name: string;
  phone: string;
  email: string;
  cpfCnpj: string;
  mobilePhone: string;
  postalCode: string;
  address: string;
  addressNumber: string;
  complement: string;
  province: string;
  city: string;
  state: string;
  notes: string;
};

type CustomerEditProfileForm = CustomerProfileForm & {
  status: string;
  categoria: string;
};

type SalePricingSummary = {
  inputValue: number;
  invoiceTotal: number;
  mrr: number;
  installments: number;
  installmentAmount: number;
  isRecurring: boolean;
  months: number;
  monthlyMode: boolean;
};

type InvoiceSortKey = 'customer' | 'installment' | 'status' | 'issue_date' | 'due_date' | 'total' | 'amount_paid';
type InvoiceSortDirection = 'asc' | 'desc';
type InvoiceSortState = {
  key: InvoiceSortKey;
  direction: InvoiceSortDirection;
};
type PlanCatalogType = 'all' | 'once' | 'recurring';
type PlanCatalogStatus = 'all' | 'active' | 'inactive';

const sectionMeta: Record<Section, { label: string; path: string; icon: React.ElementType }> = {
  customers: { label: 'Clientes', path: '/customers', icon: Users },
  invoices: { label: 'Faturas', path: '/customers/invoices', icon: Receipt },
  plans: { label: 'Planos', path: '/customers/plans', icon: Package },
  revenue: { label: 'Receita', path: '/customers/revenue', icon: BarChart3 },
};

const sectionCopy: Record<Section, { title: string; description: string }> = {
  customers: {
    title: 'Carteira de clientes',
    description: 'Clientes, workspaces, contratos e cobranças organizados em uma única operação.',
  },
  invoices: {
    title: 'Faturas',
    description: 'Acompanhe vencimentos, pagamentos e cobranças vinculadas aos seus clientes.',
  },
  plans: {
    title: 'Planos e produtos',
    description: 'Padronize serviços avulsos e recorrentes usados nas vendas e faturas.',
  },
  revenue: {
    title: 'Receita e churn',
    description: 'Visualize recorrência, recebimentos, inadimplência e retenção da carteira.',
  },
};

const INVOICE_SORT_STORAGE_KEY = 'agentive.customerInvoices.sort';

const emptyOverview: CustomerRevenueOverview = {
  total_customers: 0,
  active_customers: 0,
  churned_customers: 0,
  mrr: 0,
  open_amount: 0,
  overdue_amount: 0,
  paid_amount: 0,
  open_invoices: 0,
  overdue_invoices: 0,
};

const money = (value: number | string | null | undefined) => (
  Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
);

const numberValue = (value: number | string | null | undefined) => Number(value || 0);

const clampPercent = (value: number | string | null | undefined) => Math.min(100, Math.max(0, numberValue(value)));

const parseBRL = (value: string) => {
  const normalized = value.replace(/\s/g, '').replace(/[R$]/g, '').replace(/\./g, '').replace(',', '.');
  return Number(normalized || 0);
};

const formatBRLTyping = (value: string) => {
  const cents = value.replace(/\D/g, '');
  if (!cents) return '';
  return (Number(cents) / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
};

const onlyDigits = (value: string) => value.replace(/\D/g, '');

const formatCpfCnpj = (value: string) => {
  const digits = onlyDigits(value).slice(0, 14);
  if (digits.length <= 11) {
    return digits
      .replace(/(\d{3})(\d)/, '$1.$2')
      .replace(/(\d{3})(\d)/, '$1.$2')
      .replace(/(\d{3})(\d{1,2})$/, '$1-$2');
  }
  return digits
    .replace(/^(\d{2})(\d)/, '$1.$2')
    .replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
    .replace(/\.(\d{3})(\d)/, '.$1/$2')
    .replace(/(\d{4})(\d{1,2})$/, '$1-$2');
};

const formatCep = (value: string) => onlyDigits(value).slice(0, 8).replace(/^(\d{5})(\d)/, '$1-$2');

const apiErrorMessage = (err: any, fallback: string) => {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object' && typeof detail.message === 'string' && detail.message.trim()) {
    return detail.message;
  }
  return typeof err?.message === 'string' && err.message.trim() ? err.message : fallback;
};

const allDigitsEqual = (digits: string) => /^(\d)\1+$/.test(digits);

const isValidCpf = (value: string) => {
  const cpf = onlyDigits(value);
  if (cpf.length !== 11 || allDigitsEqual(cpf)) return false;
  const calc = (length: number) => {
    const sum = cpf.slice(0, length).split('').reduce((acc, digit, index) => acc + Number(digit) * (length + 1 - index), 0);
    const result = (sum * 10) % 11;
    return result === 10 ? 0 : result;
  };
  return calc(9) === Number(cpf[9]) && calc(10) === Number(cpf[10]);
};

const isValidCnpj = (value: string) => {
  const cnpj = onlyDigits(value);
  if (cnpj.length !== 14 || allDigitsEqual(cnpj)) return false;
  const calc = (base: string, weights: number[]) => {
    const sum = base.split('').reduce((acc, digit, index) => acc + Number(digit) * weights[index], 0);
    const result = sum % 11;
    return result < 2 ? 0 : 11 - result;
  };
  const first = calc(cnpj.slice(0, 12), [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]);
  const second = calc(cnpj.slice(0, 13), [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]);
  return first === Number(cnpj[12]) && second === Number(cnpj[13]);
};

const documentStatus = (value: string) => {
  const digits = onlyDigits(value);
  if (!digits) return { state: 'empty' as const, message: 'Informe CPF ou CNPJ.' };
  if (digits.length < 11) return { state: 'invalid' as const, message: 'CPF incompleto.' };
  if (digits.length === 11) return isValidCpf(digits)
    ? { state: 'valid' as const, message: 'CPF válido.' }
    : { state: 'invalid' as const, message: 'CPF inválido.' };
  if (digits.length < 14) return { state: 'invalid' as const, message: 'CNPJ incompleto.' };
  return isValidCnpj(digits)
    ? { state: 'valid' as const, message: 'CNPJ válido.' }
    : { state: 'invalid' as const, message: 'CNPJ inválido.' };
};

const billingIntervalMonths = (interval: string) => {
  if (interval === 'monthly') return 1;
  if (interval === 'quarterly') return 3;
  if (interval === 'yearly') return 12;
  return 0;
};

const emptyCustomerProfileForm = (): CustomerProfileForm => ({
  contactId: '',
  leadId: '',
  name: '',
  phone: '',
  email: '',
  cpfCnpj: '',
  mobilePhone: '',
  postalCode: '',
  address: '',
  addressNumber: '',
  complement: '',
  province: '',
  city: '',
  state: '',
  notes: '',
});

const emptyCustomerEditProfileForm = (): CustomerEditProfileForm => ({
  ...emptyCustomerProfileForm(),
  status: 'ativo',
  categoria: 'cliente',
});

const shortDate = (value?: string | null) => {
  if (!value) return '-';
  const date = value.includes('T') ? new Date(value) : new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit' });
};

const monthLabel = (value: string) => {
  if (!value) return '';
  const date = new Date(`${value}-01T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
};

const todayISO = () => new Date().toISOString().slice(0, 10);

const currentMonthValue = () => todayISO().slice(0, 7);

const invoiceDateTimestamp = (value?: string | null) => {
  if (!value) return 0;
  const date = value.includes('T') ? new Date(value) : new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
};

const invoiceInstallmentInfo = (invoice: BillingInvoiceSummary, sourceInvoices: BillingInvoiceSummary[] = []) => {
  const directInstallmentNumber = Number(invoice.installment_number || 0);
  const directInstallments = Number(invoice.installments || 0);
  if (directInstallments > 1 && directInstallmentNumber >= 1) {
    return {
      installmentNumber: Math.min(directInstallmentNumber, directInstallments),
      installments: directInstallments,
    };
  }

  const match = invoice.recurrence_key?.match(/^(.*):installment:(\d+)$/);
  if (match) {
    const recurrenceBase = match[1];
    const installmentNumber = Number(match[2] || 1);
    const installmentGroup = sourceInvoices
      .filter(item => item.contract_id === invoice.contract_id && item.recurrence_key?.startsWith(`${recurrenceBase}:installment:`))
      .sort((first, second) =>
        invoiceDateTimestamp(first.due_date || first.issue_date) - invoiceDateTimestamp(second.due_date || second.issue_date)
        || (first.invoice_number || '').localeCompare(second.invoice_number || '', 'pt-BR', { numeric: true })
      );

    return {
      installmentNumber,
      installments: Math.max(installmentGroup.length, installmentNumber, 1),
    };
  }

  return { installmentNumber: 1, installments: 1 };
};

const invoiceInstallmentLabel = (invoice: BillingInvoiceSummary, sourceInvoices: BillingInvoiceSummary[] = []) => {
  const { installmentNumber, installments } = invoiceInstallmentInfo(invoice, sourceInvoices);
  return `${installmentNumber}/${installments}`;
};

const readInvoiceSortState = (): InvoiceSortState => {
  if (typeof window === 'undefined') return { key: 'due_date', direction: 'asc' };
  try {
    const saved = window.localStorage.getItem(INVOICE_SORT_STORAGE_KEY);
    if (!saved) return { key: 'due_date', direction: 'asc' };
    const parsed = JSON.parse(saved) as Partial<InvoiceSortState>;
    const allowedKeys: InvoiceSortKey[] = ['customer', 'installment', 'status', 'issue_date', 'due_date', 'total', 'amount_paid'];
    if (!parsed.key || !allowedKeys.includes(parsed.key)) return { key: 'due_date', direction: 'asc' };
    return {
      key: parsed.key,
      direction: parsed.direction === 'desc' ? 'desc' : 'asc',
    };
  } catch {
    return { key: 'due_date', direction: 'asc' };
  }
};

const canEditInvoice = (invoice: BillingInvoiceSummary) => (
  !invoice.external_id && !['paid', 'void', 'refunded'].includes(invoice.status)
);
const canDeleteInvoice = (invoice: BillingInvoiceSummary) => (
  !invoice.external_id
  && ['draft', 'open', 'overdue'].includes(invoice.status)
  && Number(invoice.amount_paid || 0) <= 0
);
const statusLabel: Record<string, string> = {
  active: 'Ativo',
  paused: 'Pausado',
  canceled: 'Churn',
  completed: 'Concluido',
  open: 'Aberta',
  overdue: 'Vencida',
  paid: 'Paga',
  void: 'Anulada',
  refunded: 'Estornada',
  trialing: 'Teste',
  expired: 'Expirado',
  archived: 'Arquivado',
  ativo: 'Ativo',
  inativo: 'Inativo',
  bloqueado: 'Bloqueado',
  cliente: 'Cliente',
  ex_cliente: 'Ex-cliente',
  prospect: 'Prospect',
};

const statusTone = (status: string) => {
  if (['paid', 'active', 'ativo', 'cliente'].includes(status)) return 'success';
  if (['overdue', 'canceled', 'ex_cliente', 'inativo', 'inactive', 'expired'].includes(status)) return 'danger';
  if (['paused', 'open', 'trialing'].includes(status)) return 'warning';
  return 'neutral';
};

const billingIntervalLabel: Record<string, string> = {
  once: 'Avulsa',
  weekly: 'Semanal',
  biweekly: 'Quinzenal',
  monthly: 'Mensal',
  bimonthly: 'Bimestral',
  quarterly: 'Trimestral',
  semiannually: 'Semestral',
  yearly: 'Anual',
};

const billingMethodOptions = [
  { value: 'undefined', label: 'Pergunte ao cliente' },
  { value: 'boleto', label: 'Boleto/Pix' },
  { value: 'credit_card', label: 'Cartão de crédito' },
];

const billingCycleOptions = [
  { value: 'WEEKLY', label: 'Semanal' },
  { value: 'BIWEEKLY', label: 'Quinzenal' },
  { value: 'MONTHLY', label: 'Mensal' },
  { value: 'BIMONTHLY', label: 'Bimestral' },
  { value: 'QUARTERLY', label: 'Trimestral' },
  { value: 'SEMIANNUALLY', label: 'Semestral' },
  { value: 'YEARLY', label: 'Anual' },
];

const contractCycleLabel = (contract: BillingContractSummary) => {
  if (contract.is_recurring) return 'Recorrente';
  return 'Avulso';
};

const contractTypeLabel = (contract: BillingContractSummary) => {
  if (contract.external_id) return 'Contrato externo';
  if (contract.is_recurring) return 'Contrato recorrente';
  return 'Venda avulsa';
};

const recordSourceLabel = (externalId?: string | null, gateway?: string | null) => (
  externalId ? `Externo${gateway ? ` - ${gateway}` : ''}` : 'Gestão local'
);

const billingCycleForPlan = (plan: PlanResponse) => {
  if (plan.billing_interval === 'quarterly') return 'QUARTERLY';
  if (plan.billing_interval === 'yearly') return 'YEARLY';
  return 'MONTHLY';
};

const billingIntervalForCycle = (
  cycle: string,
): 'weekly' | 'biweekly' | 'monthly' | 'bimonthly' | 'quarterly' | 'semiannually' | 'yearly' => {
  const intervals = {
    WEEKLY: 'weekly',
    BIWEEKLY: 'biweekly',
    MONTHLY: 'monthly',
    BIMONTHLY: 'bimonthly',
    QUARTERLY: 'quarterly',
    SEMIANNUALLY: 'semiannually',
    YEARLY: 'yearly',
  } as const;
  return intervals[cycle as keyof typeof intervals] || 'monthly';
};

const billingCycleCopy = (interval: string) => {
  if (interval === 'monthly') return 'mensal';
  if (interval === 'quarterly') return 'trimestral';
  if (interval === 'yearly') return 'anual';
  return 'avulsa';
};

const planPriceHelper = (interval: string) => {
  if (interval === 'monthly') return 'Este valor será cobrado todo mês e entra integralmente no MRR.';
  if (interval === 'quarterly') return 'Este valor será a fatura trimestral. O MRR estimado será este valor dividido por 3.';
  if (interval === 'yearly') return 'Este valor será a fatura anual. O MRR estimado será este valor dividido por 12.';
  return 'Este valor será usado em faturas avulsas e não entra em MRR recorrente.';
};

const invoiceLineTypeForPlan = (plan?: PlanResponse | null): 'subscription' | 'one_time' => (
  plan && plan.billing_interval !== 'once' ? 'subscription' : 'one_time'
);

const toneClass = (tone: string, isDark: boolean) => {
  const tones: Record<string, string> = {
    success: isDark ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-200' : 'border-emerald-200 bg-emerald-50 text-emerald-700',
    warning: isDark ? 'border-amber-400/20 bg-amber-400/10 text-amber-200' : 'border-amber-200 bg-amber-50 text-amber-700',
    danger: isDark ? 'border-red-400/20 bg-red-400/10 text-red-200' : 'border-red-200 bg-red-50 text-red-700',
    neutral: isDark ? 'border-white/10 bg-white/[0.06] text-white/65' : 'border-brand/10 bg-brand-canvas text-brand/60',
  };
  return tones[tone] || tones.neutral;
};

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const tone = statusTone(status);
  return (
    <span className={cx(styles.statusBadge, styles[`status${tone[0].toUpperCase()}${tone.slice(1)}`])}>
      {statusLabel[status] || status}
    </span>
  );
};

const RecordSourceBadge: React.FC<{
  compact?: boolean;
  externalId?: string | null;
  gateway?: string | null;
}> = ({ compact = false, externalId, gateway }) => {
  const isExternal = Boolean(externalId);
  const Icon = isExternal ? CreditCard : CheckCircle2;
  return (
    <span
      className={cx(
        styles.gatewayBadge,
        compact && styles.gatewayBadgeCompact,
        !isExternal && styles.gatewayBadgeSuccess,
      )}
    >
      <Icon />
      {recordSourceLabel(externalId, gateway)}
    </span>
  );
};

const WorkspaceMetric: React.FC<{ icon: React.ElementType; label: string; value: React.ReactNode; helper?: React.ReactNode }> = ({ icon: Icon, label, value, helper }) => {
  return (
    <div className={styles.workspaceMetric}>
      <div className={styles.workspaceMetricLabel}>
        <Icon />
        <span>{label}</span>
      </div>
      <p className={styles.workspaceMetricValue}>{value}</p>
      {helper && <p className={styles.workspaceMetricHelper}>{helper}</p>}
    </div>
  );
};

export default function CustomerManagement() {
  const { isDark } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const query = useMemo(() => new URLSearchParams(location.search), [location.search]);

  const activeSection: Section = location.pathname.includes('/invoices')
    ? 'invoices'
    : location.pathname.includes('/plans')
      ? 'plans'
      : location.pathname.includes('/revenue')
        ? 'revenue'
        : 'customers';

  const [overview, setOverview] = useState<CustomerRevenueOverview>(emptyOverview);
  const [customers, setCustomers] = useState<CustomerBillingSummary[]>([]);
  const [invoices, setInvoices] = useState<BillingInvoiceSummary[]>([]);
  const [invoiceMonthFilter, setInvoiceMonthFilter] = useState(currentMonthValue);
  const [invoiceSort, setInvoiceSort] = useState<InvoiceSortState>(readInvoiceSortState);
  const [plans, setPlans] = useState<PlanResponse[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(null);
  const [selectedCustomer, setSelectedCustomer] = useState<CustomerBillingDetail | null>(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [notice, setNotice] = useState<{ type: 'success' | 'error' | 'warning' | 'info'; message: string } | null>(null);
  const [showSaleModal, setShowSaleModal] = useState(false);
  const [saleFlowMode, setSaleFlowMode] = useState<SaleFlowMode>('sale');
  const [saleStep, setSaleStep] = useState<SaleStep>('contact');
  const [selectedSaleContact, setSelectedSaleContact] = useState<Contact | null>(null);
  const [saleCustomerId, setSaleCustomerId] = useState<number | null>(null);
  const [cancelTarget, setCancelTarget] = useState<BillingContractSummary | null>(null);
  const [paidTarget, setPaidTarget] = useState<BillingInvoiceSummary | null>(null);
  const [deleteInvoiceTarget, setDeleteInvoiceTarget] = useState<BillingInvoiceSummary | null>(null);
  const [deleteCustomerTarget, setDeleteCustomerTarget] = useState<CustomerBillingDetail | null>(null);
  const [recurringTarget, setRecurringTarget] = useState<BillingContractSummary | null>(null);
  const [churnReason, setChurnReason] = useState('');
  const [contactSearch, setContactSearch] = useState('');
  const [contactResults, setContactResults] = useState<Contact[]>([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  const [planSearch, setPlanSearch] = useState('');
  const [planCatalogSearch, setPlanCatalogSearch] = useState('');
  const [planCatalogType, setPlanCatalogType] = useState<PlanCatalogType>('all');
  const [planCatalogStatus, setPlanCatalogStatus] = useState<PlanCatalogStatus>('all');
  const [invoicePlanSearch, setInvoicePlanSearch] = useState('');
  const [editingPlan, setEditingPlan] = useState<PlanResponse | null>(null);
  const [editingInvoice, setEditingInvoice] = useState<BillingInvoiceDetail | null>(null);
  const [creatingInvoiceCustomer, setCreatingInvoiceCustomer] = useState<CustomerBillingDetail | null>(null);
  const [editingCustomer, setEditingCustomer] = useState<CustomerBillingDetail | null>(null);

  const [planEditForm, setPlanEditForm] = useState({
    name: '',
    price: '',
    billingInterval: 'once',
    isActive: true,
  });

  const [invoiceEditForm, setInvoiceEditForm] = useState({
    dueDate: '',
    paymentMethod: '',
    notes: '',
  });

  const [invoiceCreateForm, setInvoiceCreateForm] = useState({
    mode: 'payment' as InvoiceChargeMode,
    planId: '',
    description: '',
    amount: '',
    dueDate: todayISO(),
    paymentMethod: 'undefined',
    cycle: 'MONTHLY',
    endDate: '',
    notes: '',
  });

  const [saleForm, setSaleForm] = useState({
    contactId: '',
    leadId: query.get('leadId') || '',
    planId: '',
    description: '',
    unitPrice: '',
    priceMode: 'cycle',
    billingInterval: 'once',
    paymentMethod: 'boleto',
    installments: '1',
    dueDate: todayISO(),
    initialPaymentReceived: false,
    initialPayment: '',
    initialPaymentDate: todayISO(),
    initialPaymentInstallment: '1',
    initialPaymentMethod: 'boleto',
    notes: '',
  });

  const [saleCustomerForm, setSaleCustomerForm] = useState<CustomerProfileForm>(emptyCustomerProfileForm());
  const [customerEditForm, setCustomerEditForm] = useState<CustomerEditProfileForm>(emptyCustomerEditProfileForm());

  const [planForm, setPlanForm] = useState({
    name: '',
    price: '',
    billingInterval: 'once',
  });

  const customerToProfileForm = (customer: CustomerBillingDetail | CustomerBillingSummary): CustomerProfileForm => ({
    contactId: String(customer.contact_id || ''),
    leadId: customer.convertido_de_lead_id ? String(customer.convertido_de_lead_id) : '',
    name: customer.nome || '',
    phone: customer.telefone || '',
    email: customer.email || '',
    cpfCnpj: customer.cpf_cnpj || '',
    mobilePhone: customer.mobile_phone || customer.telefone || '',
    postalCode: customer.postal_code || '',
    address: customer.address || '',
    addressNumber: customer.address_number || '',
    complement: customer.complement || '',
    province: customer.province || '',
    city: customer.city || '',
    state: customer.state || '',
    notes: customer.notes || '',
  });

  const contactToProfileForm = (contact: Contact, leadId = ''): CustomerProfileForm => ({
    ...emptyCustomerProfileForm(),
    contactId: contact.id ? String(contact.id) : '',
    leadId: contact.lead_id ? String(contact.lead_id) : leadId,
    name: contact.name || '',
    phone: contact.phone || '',
    mobilePhone: contact.phone || '',
  });

  const customerProfilePayload = (form: CustomerProfileForm) => ({
    contact_id: Number(form.contactId) || undefined,
    lead_id: Number(form.leadId) || undefined,
    name: form.name.trim(),
    phone: form.phone.trim(),
    email: form.email.trim() || null,
    notes: form.notes.trim() || null,
    cpf_cnpj: onlyDigits(form.cpfCnpj) || null,
    mobile_phone: form.mobilePhone.trim() || null,
    postal_code: onlyDigits(form.postalCode) || null,
    address: form.address.trim() || null,
    address_number: form.addressNumber.trim() || null,
    complement: form.complement.trim() || null,
    province: form.province.trim() || null,
    city: form.city.trim() || null,
    state: form.state.trim().slice(0, 2).toUpperCase() || null,
  });

  const validateCustomerProfile = (form: CustomerProfileForm) => {
    const document = documentStatus(form.cpfCnpj);
    if (!form.name.trim()) return 'Informe o nome do cliente.';
    if (document.state !== 'valid') return document.message;
    if (!form.phone.trim()) return 'Informe o telefone principal do cliente.';
    if (!form.mobilePhone.trim()) return 'Informe o WhatsApp do cliente.';
    if (!form.email.trim()) return 'Informe o email do cliente.';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) return 'Informe um email válido.';
    return null;
  };

  const resetSaleFlow = () => {
    setShowSaleModal(false);
    setSaleFlowMode('sale');
    setSaleStep('contact');
    setSelectedSaleContact(null);
    setSaleCustomerId(null);
    setSaleCustomerForm(emptyCustomerProfileForm());
    setSaleForm({
      contactId: '',
      leadId: '',
      planId: '',
      description: '',
      unitPrice: '',
      priceMode: 'cycle',
      billingInterval: 'once',
      paymentMethod: 'boleto',
      installments: '1',
      dueDate: todayISO(),
      initialPaymentReceived: false,
      initialPayment: '',
      initialPaymentDate: todayISO(),
      initialPaymentInstallment: '1',
      initialPaymentMethod: 'boleto',
      notes: '',
    });
    setContactSearch('');
    setPlanSearch('');
  };

  const openSaleFlow = () => {
    setSaleFlowMode('sale');
    setSaleStep('contact');
    setSelectedSaleContact(null);
    setSaleCustomerId(null);
    setSaleCustomerForm(emptyCustomerProfileForm());
    setShowSaleModal(true);
  };

  const openCustomerModal = () => {
    setSaleFlowMode('customer');
    setSaleStep('contact');
    setSelectedSaleContact(null);
    setSaleCustomerId(null);
    setSaleCustomerForm(emptyCustomerProfileForm());
    setSaleForm(prev => ({ ...prev, contactId: '', leadId: '' }));
    setContactSearch('');
    setPlanSearch('');
    setShowSaleModal(true);
  };

  const loadData = async () => {
    try {
      setLoading(true);
      const [overviewData, customerData, invoiceData, planData] = await Promise.all([
        customerBillingApi.getOverview(),
        customerBillingApi.listCustomers(search),
        customerBillingApi.listInvoices(),
        customerBillingApi.listPlans(),
      ]);
      setOverview(overviewData);
      setCustomers(customerData);
      setInvoices(invoiceData);
      setPlans(planData);
      if (!selectedCustomerId && customerData.length > 0) {
        setSelectedCustomerId(customerData[0].id);
      }
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao carregar clientes') });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (query.get('action') === 'sale' || query.get('leadId')) {
      setSaleFlowMode('sale');
      setSaleStep('contact');
      setShowSaleModal(true);
      setSaleForm(prev => ({ ...prev, leadId: query.get('leadId') || prev.leadId }));
    }
  }, [query]);

  useEffect(() => {
    if (!showSaleModal) return;

    let cancelled = false;
    const timeout = window.setTimeout(async () => {
      try {
        setContactsLoading(true);
        const response = await getContacts({ search: contactSearch.trim() || undefined, limit: 8, offset: 0 });
        if (!cancelled) setContactResults(response.contacts);
      } catch (err: any) {
        if (!cancelled) {
          setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao buscar contatos') });
        }
      } finally {
        if (!cancelled) setContactsLoading(false);
      }
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [showSaleModal, contactSearch]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      loadData();
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [search]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(INVOICE_SORT_STORAGE_KEY, JSON.stringify(invoiceSort));
  }, [invoiceSort]);

  useEffect(() => {
    if (!selectedCustomerId) {
      setSelectedCustomer(null);
      return;
    }

    let cancelled = false;
    const loadCustomer = async () => {
      try {
        setDetailLoading(true);
        const detail = await customerBillingApi.getCustomer(selectedCustomerId);
        if (!cancelled) setSelectedCustomer(detail);
      } catch (err: any) {
        if (!cancelled) {
          setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao carregar cliente') });
        }
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    };
    loadCustomer();
    return () => {
      cancelled = true;
    };
  }, [selectedCustomerId]);

  const refreshAll = async (customerId: number | null = selectedCustomerId) => {
    await loadData();
    if (customerId) {
      setSelectedCustomerId(customerId);
      const detail = await customerBillingApi.getCustomer(customerId);
      setSelectedCustomer(detail);
    }
  };

  const filteredPlans = useMemo(() => {
    const term = planSearch.trim().toLowerCase();
    return plans
      .filter(plan => plan.is_active)
      .filter(plan => !term || plan.name.toLowerCase().includes(term))
      .slice(0, 8);
  }, [plans, planSearch]);

  const filteredInvoicePlans = useMemo(() => {
    const term = invoicePlanSearch.trim().toLowerCase();
    return plans
      .filter(plan => plan.is_active)
      .filter(plan => !term || plan.name.toLowerCase().includes(term))
      .slice(0, 8);
  }, [plans, invoicePlanSearch]);

  const filteredCatalogPlans = useMemo(() => {
    const term = planCatalogSearch.trim().toLowerCase();

    return plans
      .filter(plan => !term || plan.name.toLowerCase().includes(term))
      .filter(plan => planCatalogType === 'all'
        || (planCatalogType === 'once' ? plan.billing_interval === 'once' : plan.billing_interval !== 'once'))
      .filter(plan => planCatalogStatus === 'all'
        || (planCatalogStatus === 'active' ? plan.is_active : !plan.is_active))
      .sort((first, second) => {
        if (first.is_active !== second.is_active) return first.is_active ? -1 : 1;
        return first.name.localeCompare(second.name, 'pt-BR', { sensitivity: 'base' });
      });
  }, [plans, planCatalogSearch, planCatalogStatus, planCatalogType]);

  const planMetrics = useMemo(() => ({
    total: plans.length,
    active: plans.filter(plan => plan.is_active).length,
    recurring: plans.filter(plan => plan.billing_interval !== 'once').length,
    once: plans.filter(plan => plan.billing_interval === 'once').length,
  }), [plans]);

  const hasPlanCatalogFilters = Boolean(
    planCatalogSearch.trim()
    || planCatalogType !== 'all'
    || planCatalogStatus !== 'all'
  );

  const clearPlanCatalogFilters = () => {
    setPlanCatalogSearch('');
    setPlanCatalogType('all');
    setPlanCatalogStatus('all');
  };

  const selectedPlan = useMemo(
    () => plans.find(plan => String(plan.id) === saleForm.planId) || null,
    [plans, saleForm.planId]
  );

  const selectedInvoicePlan = useMemo(
    () => plans.find(plan => String(plan.id) === invoiceCreateForm.planId) || null,
    [plans, invoiceCreateForm.planId]
  );

  const invoiceMonthOptions = useMemo(() => {
    const months = invoices
      .map(invoice => invoice.due_date?.slice(0, 7))
      .filter((value): value is string => Boolean(value));

    return Array.from(new Set([currentMonthValue(), ...months])).sort((a, b) => b.localeCompare(a));
  }, [invoices]);

  const getInvoiceCustomerName = useCallback((invoice: BillingInvoiceSummary) => (
    invoice.customer_name
    || customers.find(customer => customer.id === invoice.customer_id)?.nome
    || 'Cliente sem nome'
  ), [customers]);

  const getInvoiceSortValue = useCallback((invoice: BillingInvoiceSummary, key: InvoiceSortKey) => {
    if (key === 'customer') return getInvoiceCustomerName(invoice).toLowerCase();
    if (key === 'installment') return invoiceInstallmentInfo(invoice, invoices).installmentNumber;
    if (key === 'status') return statusLabel[invoice.status] || invoice.status;
    if (key === 'issue_date') return invoice.issue_date || '';
    if (key === 'due_date') return invoice.due_date || '';
    if (key === 'total') return Number(invoice.total || 0);
    if (key === 'amount_paid') return Number(invoice.amount_paid || 0);
    return '';
  }, [getInvoiceCustomerName, invoices]);

  const filteredInvoices = useMemo(
    () => invoices.filter(invoice => !invoiceMonthFilter || invoice.due_date?.slice(0, 7) === invoiceMonthFilter),
    [invoices, invoiceMonthFilter]
  );

  const orderedInvoices = useMemo(() => {
    const direction = invoiceSort.direction === 'asc' ? 1 : -1;

    return [...filteredInvoices].sort((first, second) => {
      const firstValue = getInvoiceSortValue(first, invoiceSort.key);
      const secondValue = getInvoiceSortValue(second, invoiceSort.key);

      if (typeof firstValue === 'number' && typeof secondValue === 'number') {
        const numericCompare = firstValue - secondValue;
        if (numericCompare !== 0) return numericCompare * direction;
      } else {
        const stringCompare = String(firstValue).localeCompare(String(secondValue), 'pt-BR', {
          numeric: true,
          sensitivity: 'base',
        });
        if (stringCompare !== 0) return stringCompare * direction;
      }

      return (first.invoice_number || '').localeCompare(second.invoice_number || '', 'pt-BR', { numeric: true });
    });
  }, [filteredInvoices, invoiceSort, getInvoiceSortValue]);

  const invoiceMetrics = useMemo(() => {
    const totals = filteredInvoices.reduce((summary, invoice) => {
      const amountDue = numberValue(invoice.amount_due);
      summary.total += numberValue(invoice.total);
      summary.received += numberValue(invoice.amount_paid);
      summary.open += amountDue;
      if (invoice.status === 'overdue') {
        summary.overdue += amountDue;
        summary.overdueCount += 1;
      }
      return summary;
    }, { total: 0, received: 0, open: 0, overdue: 0, overdueCount: 0 });

    return totals;
  }, [filteredInvoices]);

  const toggleInvoiceSort = (key: InvoiceSortKey) => {
    setInvoiceSort(prev => ({
      key,
      direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc',
    }));
  };

  const renderInvoiceSortHeader = (key: InvoiceSortKey, label: string) => {
    const active = invoiceSort.key === key;
    const Icon = active ? (invoiceSort.direction === 'asc' ? ChevronUp : ChevronDown) : ArrowUpDown;

    return (
      <button
        type="button"
        onClick={() => toggleInvoiceSort(key)}
        className={cx(
          'inline-flex items-center gap-1 rounded-lg px-1.5 py-1 text-left font-medium transition',
          active && (isDark ? 'text-white' : 'text-brand'),
          isDark ? 'hover:bg-white/10' : 'hover:bg-white'
        )}
      >
        <span>{label}</span>
        <Icon className="h-3.5 w-3.5" />
      </button>
    );
  };

  const salePricing = useMemo(() => {
    const inputValue = parseBRL(saleForm.unitPrice);
    const months = billingIntervalMonths(saleForm.billingInterval);
    const isRecurring = months > 0;
    const monthlyMode = saleForm.priceMode === 'monthly' && isRecurring;
    const invoiceTotal = monthlyMode ? inputValue * months : inputValue;
    const mrr = isRecurring ? invoiceTotal / months : 0;
    const installments = Math.max(1, Number(saleForm.installments || 1));
    return {
      inputValue,
      invoiceTotal,
      mrr,
      installments,
      installmentAmount: invoiceTotal / installments,
      isRecurring,
      months,
      monthlyMode,
    };
  }, [saleForm.unitPrice, saleForm.billingInterval, saleForm.priceMode, saleForm.installments]);

  const selectContactForSale = async (contact: Contact) => {
    if (!contact.id) return;
    setSelectedSaleContact(contact);
    setSaleCustomerId(contact.customer_id || null);
    setSaleCustomerForm(contactToProfileForm(contact, saleForm.leadId));
    setSaleForm(prev => ({
      ...prev,
      contactId: String(contact.id),
      leadId: contact.lead_id ? String(contact.lead_id) : prev.leadId,
    }));
    setContactSearch(`${contact.name || 'Contato sem nome'} - ${contact.phone}`);
    if (contact.customer_id) {
      setSelectedCustomerId(contact.customer_id);
      try {
        setActionLoading(true);
        const detail = await customerBillingApi.getCustomer(contact.customer_id);
        setSaleCustomerForm(customerToProfileForm(detail));
        setSaleCustomerId(detail.id);
      } catch (err: any) {
        setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao carregar dados do cliente') });
      } finally {
        setActionLoading(false);
      }
    }
    setSaleStep('customer');
  };

  const selectPlanForSale = (plan: PlanResponse) => {
    setSaleForm(prev => ({
      ...prev,
      planId: String(plan.id),
      description: plan.name,
      unitPrice: money(plan.price),
      priceMode: 'cycle',
      billingInterval: plan.billing_interval || 'once',
    }));
    setPlanSearch(plan.name);
  };

  const selectPlanForInvoice = (plan: PlanResponse) => {
    setInvoiceCreateForm(prev => ({
      ...prev,
      mode: plan.billing_interval === 'once' ? 'payment' : 'subscription',
      planId: String(plan.id),
      description: plan.name,
      amount: money(plan.price),
      installments: '1',
      cycle: billingCycleForPlan(plan),
    }));
    setInvoicePlanSearch(plan.name);
  };

  const submitSaleCustomer = async (event: React.FormEvent) => {
    event.preventDefault();
    const validationError = validateCustomerProfile(saleCustomerForm);
    if (validationError) {
      setNotice({ type: 'error', message: validationError });
      return;
    }

    try {
      setActionLoading(true);
      const payload = customerProfilePayload(saleCustomerForm);
      const isExistingCustomer = Boolean(saleCustomerId);
      const customer = isExistingCustomer
        ? await customerBillingApi.updateCustomer(saleCustomerId, {
            ...payload,
            status: 'ativo',
            categoria: 'cliente',
          })
        : await customerBillingApi.createCustomer(payload);

      setSaleCustomerId(customer.id);
      setSelectedCustomerId(customer.id);
      setSaleCustomerForm(prev => ({
        ...prev,
        contactId: String(customer.contact_id || prev.contactId),
        leadId: customer.convertido_de_lead_id ? String(customer.convertido_de_lead_id) : prev.leadId,
      }));
      if (saleFlowMode === 'customer') {
        resetSaleFlow();
        setSelectedCustomerId(customer.id);
        setNotice({
          type: 'success',
          message: isExistingCustomer ? 'Cliente atualizado.' : 'Cliente criado.',
        });
        await refreshAll(customer.id);
        return;
      }
      setSaleStep('sale');
      setNotice({
        type: 'success',
        message: isExistingCustomer ? 'Cliente atualizado para a venda.' : 'Cliente cadastrado para a venda.',
      });
      await refreshAll(customer.id);
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao salvar cliente') });
    } finally {
      setActionLoading(false);
    }
  };

  const submitSale = async (event: React.FormEvent) => {
    event.preventDefault();
    const invoiceTotal = salePricing.invoiceTotal;
    const leadId = Number(saleForm.leadId);
    const installments = Number(saleForm.installments || 1);
    const initialPaymentAmount = saleForm.initialPaymentReceived ? parseBRL(saleForm.initialPayment) : undefined;

    if (!saleCustomerId) {
      setNotice({ type: 'error', message: 'Salve o cliente antes de criar a venda.' });
      setSaleStep('customer');
      return;
    }
    if (!invoiceTotal || invoiceTotal <= 0) {
      setNotice({ type: 'error', message: 'Informe um valor válido para a venda.' });
      return;
    }
    if (!saleForm.planId) {
      setNotice({ type: 'error', message: 'Selecione um produto ou plano cadastrado.' });
      return;
    }
    if (!installments || installments < 1) {
      setNotice({ type: 'error', message: 'Informe ao menos 1 parcela.' });
      return;
    }
    if (saleForm.initialPaymentReceived && (!initialPaymentAmount || initialPaymentAmount <= 0)) {
      setNotice({ type: 'error', message: 'Informe o valor recebido em BRL.' });
      return;
    }
    if (saleForm.initialPaymentReceived && initialPaymentAmount && initialPaymentAmount > invoiceTotal) {
      setNotice({ type: 'error', message: 'O pagamento recebido não pode ser maior que a fatura inicial.' });
      return;
    }
    if (saleForm.initialPaymentReceived && Number(saleForm.initialPaymentInstallment || 1) > installments) {
      setNotice({ type: 'error', message: 'A parcela recebida não pode ser maior que o total de parcelas.' });
      return;
    }

    try {
      setActionLoading(true);
      const payload = {
        start_date: todayISO(),
        lead_id: leadId || undefined,
        payment_method: saleForm.paymentMethod,
        installments,
        notes: saleForm.notes || undefined,
        create_initial_invoice: true,
        initial_invoice_due_date: saleForm.dueDate || undefined,
        initial_payment_amount: saleForm.initialPaymentReceived ? initialPaymentAmount : undefined,
        initial_payment_method: saleForm.initialPaymentReceived ? saleForm.initialPaymentMethod || saleForm.paymentMethod : undefined,
        initial_payment_date: saleForm.initialPaymentReceived && saleForm.initialPaymentDate
          ? new Date(`${saleForm.initialPaymentDate}T12:00:00`).toISOString()
          : undefined,
        initial_payment_installment: saleForm.initialPaymentReceived
          ? Number(saleForm.initialPaymentInstallment || 1)
          : undefined,
        items: [{
          plan_id: Number(saleForm.planId),
          description: saleForm.description || 'Contrato de serviço',
          quantity: 1,
          unit_price: invoiceTotal,
          discount_percent: 0,
          discount_amount: 0,
          billing_interval: saleForm.billingInterval as 'once' | 'monthly' | 'quarterly' | 'yearly',
        }],
      };

      const contract = await customerBillingApi.createCustomerContract(saleCustomerId, payload);
      const nextCustomerId = contract.customer_id || saleCustomerId || selectedCustomerId;

      resetSaleFlow();
      setSelectedCustomerId(nextCustomerId || null);
      setNotice({
        type: 'success',
        message: `Venda, contrato e fatura salvos em ${branding.appName}.`,
      });
      await refreshAll(nextCustomerId || null);
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao registrar venda') });
    } finally {
      setActionLoading(false);
    }
  };

  const openCustomerEdit = (customer: CustomerBillingDetail) => {
    setEditingCustomer(customer);
    setCustomerEditForm({
      ...customerToProfileForm(customer),
      status: customer.status || 'ativo',
      categoria: customer.categoria || 'cliente',
    });
  };

  const submitCustomerEdit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingCustomer) return;
    const validationError = validateCustomerProfile(customerEditForm);
    if (validationError) {
      setNotice({ type: 'error', message: validationError });
      return;
    }

    try {
      setActionLoading(true);
      const customer = await customerBillingApi.updateCustomer(editingCustomer.id, {
        ...customerProfilePayload(customerEditForm),
        name: customerEditForm.name.trim(),
        phone: customerEditForm.phone.trim(),
        email: customerEditForm.email.trim() || null,
        status: customerEditForm.status as 'ativo' | 'inativo' | 'bloqueado',
        categoria: customerEditForm.categoria as 'cliente' | 'lead_qualificado' | 'prospect' | 'ex_cliente',
      });
      setEditingCustomer(null);
      setNotice({
        type: 'success',
        message: 'Cliente atualizado.',
      });
      await refreshAll(customer.id);
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao editar cliente') });
    } finally {
      setActionLoading(false);
    }
  };

  const submitPlan = async (event: React.FormEvent) => {
    event.preventDefault();
    const price = parseBRL(planForm.price);
    if (!price || price <= 0) {
      setNotice({ type: 'error', message: 'Informe o valor do plano em BRL.' });
      return;
    }
    try {
      setActionLoading(true);
      await customerBillingApi.createPlan({
        name: planForm.name,
        price,
        billing_interval: planForm.billingInterval as 'once' | 'monthly' | 'quarterly' | 'yearly',
      });
      setPlanForm({ name: '', price: '', billingInterval: 'once' });
      setNotice({ type: 'success', message: 'Plano criado.' });
      await refreshAll();
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao criar plano') });
    } finally {
      setActionLoading(false);
    }
  };

  const openPlanEdit = (plan: PlanResponse) => {
    setEditingPlan(plan);
    setPlanEditForm({
      name: plan.name,
      price: money(plan.price),
      billingInterval: plan.billing_interval || 'once',
      isActive: plan.is_active,
    });
  };

  const submitPlanEdit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingPlan) return;

    const price = parseBRL(planEditForm.price);
    if (!planEditForm.name.trim()) {
      setNotice({ type: 'error', message: 'Informe o nome do plano.' });
      return;
    }
    if (!price || price <= 0) {
      setNotice({ type: 'error', message: 'Informe o valor do plano em BRL.' });
      return;
    }

    try {
      setActionLoading(true);
      await customerBillingApi.updatePlan(editingPlan.id, {
        name: planEditForm.name.trim(),
        price,
        billing_interval: planEditForm.billingInterval as 'once' | 'monthly' | 'quarterly' | 'yearly',
        is_active: planEditForm.isActive,
      });
      setEditingPlan(null);
      setNotice({ type: 'success', message: 'Plano atualizado.' });
      await refreshAll();
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao editar plano') });
    } finally {
      setActionLoading(false);
    }
  };

  const openInvoiceCreate = (customer: CustomerBillingDetail) => {
    setCreatingInvoiceCustomer(customer);
    setInvoiceCreateForm({
      mode: 'payment',
      planId: '',
      description: '',
      amount: '',
      dueDate: todayISO(),
      paymentMethod: 'undefined',
      cycle: 'MONTHLY',
      endDate: '',
      notes: '',
    });
    setInvoicePlanSearch('');
  };

  const submitInvoiceCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!creatingInvoiceCustomer) return;

    const amount = parseBRL(invoiceCreateForm.amount);
    const planId = Number(invoiceCreateForm.planId);
    if (!planId) {
      setNotice({ type: 'error', message: 'Selecione um produto ou plano para a fatura.' });
      return;
    }
    if (!invoiceCreateForm.description.trim()) {
      setNotice({ type: 'error', message: 'Informe a descrição da fatura.' });
      return;
    }
    if (!amount || amount <= 0) {
      setNotice({ type: 'error', message: 'Informe o valor da fatura em BRL.' });
      return;
    }
    if (!invoiceCreateForm.dueDate) {
      setNotice({ type: 'error', message: 'Informe o vencimento da fatura.' });
      return;
    }
    if (invoiceCreateForm.mode === 'subscription' && invoiceCreateForm.endDate && invoiceCreateForm.endDate < invoiceCreateForm.dueDate) {
      setNotice({ type: 'error', message: 'A data final da assinatura precisa ser posterior ao primeiro vencimento.' });
      return;
    }

    try {
      setActionLoading(true);
      if (invoiceCreateForm.mode === 'subscription') {
        await customerBillingApi.createCustomerContract(creatingInvoiceCustomer.id, {
          start_date: invoiceCreateForm.dueDate,
          end_date: invoiceCreateForm.endDate || undefined,
          payment_method: invoiceCreateForm.paymentMethod,
          installments: 1,
          notes: invoiceCreateForm.notes.trim() || undefined,
          create_initial_invoice: true,
          initial_invoice_due_date: invoiceCreateForm.dueDate,
          items: [{
            plan_id: planId,
            description: invoiceCreateForm.description.trim(),
            quantity: 1,
            unit_price: amount,
            discount_percent: 0,
            discount_amount: 0,
            billing_interval: billingIntervalForCycle(invoiceCreateForm.cycle),
          }],
        });
      } else {
        await customerBillingApi.createInvoice({
          customer_id: creatingInvoiceCustomer.id,
          contact_id: creatingInvoiceCustomer.contact_id,
          due_date: invoiceCreateForm.dueDate,
          payment_method: invoiceCreateForm.paymentMethod,
          notes: invoiceCreateForm.notes.trim() || null,
          line_items: [{
            description: invoiceCreateForm.description.trim(),
            quantity: 1,
            unit_price: amount,
            discount_amount: 0,
            type: invoiceLineTypeForPlan(selectedInvoicePlan),
            plan_id: planId,
          }],
        });
      }
      const customerId = creatingInvoiceCustomer.id;
      setCreatingInvoiceCustomer(null);
      setNotice({
        type: 'success',
        message: invoiceCreateForm.mode === 'subscription'
          ? `Contrato recorrente e primeira fatura salvos em ${branding.appName}.`
          : `Fatura salva em ${branding.appName}.`,
      });
      await refreshAll(customerId);
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao criar fatura') });
    } finally {
      setActionLoading(false);
    }
  };

  const openInvoiceEdit = async (invoice: BillingInvoiceSummary) => {
    if (!canEditInvoice(invoice)) {
      setNotice({ type: 'error', message: 'Faturas pagas, anuladas ou estornadas não podem ser editadas.' });
      return;
    }

    try {
      setActionLoading(true);
      const detail = await customerBillingApi.getInvoice(invoice.id);
      setEditingInvoice(detail);
      setInvoiceEditForm({
        dueDate: detail.due_date || '',
        paymentMethod: detail.payment_method || '',
        notes: detail.notes || '',
      });
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao carregar fatura') });
    } finally {
      setActionLoading(false);
    }
  };

  const submitInvoiceEdit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingInvoice) return;
    if (!canEditInvoice(editingInvoice)) {
      setNotice({ type: 'error', message: 'Esta fatura não pode ser editada.' });
      return;
    }

    try {
      setActionLoading(true);
      await customerBillingApi.updateInvoice(editingInvoice.id, {
        due_date: invoiceEditForm.dueDate || null,
        payment_method: invoiceEditForm.paymentMethod || null,
        notes: invoiceEditForm.notes.trim() || null,
      });
      const customerId = editingInvoice.customer_id || selectedCustomerId;
      setEditingInvoice(null);
      setNotice({ type: 'success', message: 'Fatura atualizada.' });
      await refreshAll(customerId || null);
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao editar fatura') });
    } finally {
      setActionLoading(false);
    }
  };

  const confirmMarkPaid = async () => {
    if (!paidTarget) return;
    try {
      setActionLoading(true);
      await customerBillingApi.markInvoicePaid(paidTarget.id, paidTarget.payment_method || undefined);
      setNotice({ type: 'success', message: 'Fatura marcada como paga.' });
      setPaidTarget(null);
      await refreshAll();
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao marcar fatura paga') });
    } finally {
      setActionLoading(false);
    }
  };

  const confirmDeleteInvoice = async () => {
    if (!deleteInvoiceTarget) return;
    try {
      setActionLoading(true);
      const customerId = deleteInvoiceTarget.customer_id || selectedCustomerId;
      await customerBillingApi.deleteInvoice(deleteInvoiceTarget.id);
      setNotice({ type: 'success', message: 'Fatura excluída.' });
      setDeleteInvoiceTarget(null);
      await refreshAll(customerId || null);
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao excluir fatura') });
    } finally {
      setActionLoading(false);
    }
  };

  const confirmDeleteCustomer = async () => {
    if (!deleteCustomerTarget) return;
    try {
      setActionLoading(true);
      await customerBillingApi.deleteCustomer(deleteCustomerTarget.id);
      setNotice({ type: 'success', message: 'Cliente excluído.' });
      setDeleteCustomerTarget(null);
      setSelectedCustomerId(null);
      setSelectedCustomer(null);
      await refreshAll(null);
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao excluir cliente') });
    } finally {
      setActionLoading(false);
    }
  };

  const confirmGenerateRecurring = async () => {
    if (!recurringTarget) return;
    try {
      setActionLoading(true);
      await customerBillingApi.generateNextInvoice(recurringTarget.id);
      setNotice({ type: 'success', message: 'Próxima fatura recorrente gerada.' });
      setRecurringTarget(null);
      await refreshAll();
    } catch (err: any) {
      setNotice({ type: 'error', message: apiErrorMessage(err, 'Erro ao gerar fatura recorrente') });
    } finally {
      setActionLoading(false);
    }
  };

  const confirmCancelContract = async () => {
    if (!cancelTarget) return;
    try {
      setActionLoading(true);
      await customerBillingApi.cancelContract(cancelTarget.id, churnReason || undefined);
      setNotice({
        type: 'success',
        message: 'Churn registrado e contrato cancelado.',
      });
      setCancelTarget(null);
      setChurnReason('');
      await refreshAll();
    } catch (err: any) {
      setNotice({
        type: 'error',
        message: apiErrorMessage(err, 'Erro ao registrar churn'),
      });
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreateWorkspace = (customer: CustomerBillingDetail) => {
    const params = new URLSearchParams({
      customerId: String(customer.id),
      customerName: customer.nome,
      returnTo: `${location.pathname}${location.search}`,
    });
    navigate(`/new-company-admin?${params.toString()}`);
  };

  const handleOpenManagedCompany = async (managedCompany: ManagedCompanySummary) => {
    try {
      setActionLoading(true);
      await selectActiveCompany(managedCompany.managed_company_id);
      const id = String(managedCompany.managed_company_id);
      localStorage.setItem('company_id', id);
      localStorage.setItem('clinic_id', id);
      window.location.href = '/agents';
    } catch (err: any) {
      setNotice({
        type: 'error',
        message: apiErrorMessage(err, 'Erro ao acessar workspace do cliente'),
      });
    } finally {
      setActionLoading(false);
    }
  };

  const renderTabs = () => (
    <nav className={styles.tabs} aria-label="Áreas da gestão de clientes">
      {(Object.keys(sectionMeta) as Section[]).map((key) => {
        const Icon = sectionMeta[key].icon;
        const active = key === activeSection;
        return (
          <button
            key={key}
            type="button"
            onClick={() => navigate(sectionMeta[key].path)}
            className={cx(
              styles.tab,
              active && styles.tabActive,
            )}
            aria-current={active ? 'page' : undefined}
          >
            <Icon />
            {sectionMeta[key].label}
          </button>
        );
      })}
    </nav>
  );

  const renderOverview = () => {
    const metrics = [
      { icon: Users, label: 'Clientes ativos', value: overview.active_customers, helper: `${overview.total_customers} no total` },
      { icon: Repeat, label: 'MRR recorrente', value: money(overview.mrr), helper: 'Contratos ativos recorrentes' },
      { icon: Receipt, label: 'Em aberto', value: money(overview.open_amount), helper: `${overview.open_invoices} faturas abertas` },
      { icon: TrendingDown, label: 'Churn', value: overview.churned_customers, helper: `${money(overview.overdue_amount)} vencido` },
    ];

    return (
      <section className={styles.metricsGrid} aria-label="Resumo da carteira">
        {metrics.map(({ icon: Icon, label, value, helper }) => (
          <div key={label} className={styles.metricCard}>
            <div className={styles.metricIcon}><Icon /></div>
            <div className={styles.metricCopy}>
              <p className={styles.metricLabel}>{label}</p>
              <p className={styles.metricValue}>{value}</p>
              <p className={styles.metricHelper}>{helper}</p>
            </div>
          </div>
        ))}
      </section>
    );
  };

  const renderCustomers = () => (
    <div className={styles.customerGrid}>
      <section className={cx(styles.panel, styles.customerListPanel)}>
        <div className={styles.panelHeader}>
          <div className={styles.panelHeadingRow}>
            <div>
              <h2 className={styles.panelTitle}>Clientes</h2>
              <p className={styles.panelDescription}>{customers.length} perfis na carteira</p>
            </div>
            <button type="button" onClick={openCustomerModal} className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}>
              <UserPlus />
              Cadastrar
            </button>
          </div>
          <div className={styles.searchField}>
            <Search />
            <input
              value={search}
              onChange={event => setSearch(event.target.value)}
              placeholder="Buscar por nome, telefone ou email"
              className={styles.searchInput}
            />
          </div>
        </div>

        {loading ? (
          <div className={styles.loadingState}>
            <Loader2 className="animate-spin" />
            Carregando clientes
          </div>
        ) : customers.length === 0 ? (
          <div className={styles.emptyState}>
            <CustomerContextEmptyState
              icon={Users}
              title="Nenhum cliente encontrado"
              description="Crie um cliente manualmente ou registre uma venda a partir de um lead ganho."
              action={<button type="button" onClick={openSaleFlow} className={cx(styles.button, styles.buttonPrimary)}><Plus />Nova venda</button>}
            />
          </div>
        ) : (
          <div className={styles.customerRows}>
            {customers.map(customer => (
              <button
                key={customer.id}
                type="button"
                onClick={() => setSelectedCustomerId(customer.id)}
                className={cx(
                  styles.customerRow,
                  selectedCustomerId === customer.id && styles.customerRowSelected,
                )}
              >
                <div className={styles.customerRowContent}>
                  <div className={styles.customerIdentity}>
                    <div className={styles.customerNameRow}>
                      <p className={styles.customerName}>{customer.nome}</p>
                      <StatusBadge status={customer.categoria} />
                    </div>
                    <p className={styles.customerContact}>{customer.telefone}</p>
                    {customer.cpf_cnpj && (
                      <p className={styles.customerDocument}>CPF/CNPJ {customer.cpf_cnpj}</p>
                    )}
                    <div className={styles.customerGateway}>
                      <RecordSourceBadge compact />
                    </div>
                  </div>
                  <div className={styles.customerBalance}>
                    <p>{money(customer.open_amount)}</p>
                    <span>em aberto</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <aside className={cx(styles.panel, styles.customerDetailPanel, !selectedCustomer && !detailLoading && styles.customerDetailPanelEmpty)}>
        {detailLoading ? (
          <div className={styles.loadingState}>
            <Loader2 className="animate-spin" />
            Carregando detalhe
          </div>
        ) : selectedCustomer ? (
          <CustomerDetailPanel
            customer={selectedCustomer}
            onEditCustomer={openCustomerEdit}
            onDeleteCustomer={setDeleteCustomerTarget}
            onCancel={setCancelTarget}
            onGenerate={setRecurringTarget}
            onEditInvoice={openInvoiceEdit}
            onCreateInvoice={openInvoiceCreate}
            onDeleteInvoice={setDeleteInvoiceTarget}
            onMarkPaid={setPaidTarget}
            onCreateWorkspace={handleCreateWorkspace}
            onOpenManagedCompany={handleOpenManagedCompany}
          />
        ) : (
          <div className={styles.detailEmpty}>
            <CustomerContextEmptyState
              icon={Users}
              title="Selecione um cliente"
              description="Consulte dados, workspaces, contratos e faturas neste painel."
              variant="detail"
            />
          </div>
        )}
      </aside>
    </div>
  );

  const renderInvoiceActions = (invoice: BillingInvoiceSummary, mobile = false) => (
    <div className={cx(styles.invoiceActions, mobile && styles.invoiceActionsMobile)}>
      {canEditInvoice(invoice) && (
        <button
          type="button"
          onClick={() => openInvoiceEdit(invoice)}
          className={styles.invoiceAction}
          aria-label={`Editar ${invoice.invoice_number}`}
          title="Editar fatura"
        >
          <Pencil />
          {mobile && <span>Editar</span>}
        </button>
      )}
      {canEditInvoice(invoice) && (
        <button
          type="button"
          onClick={() => setPaidTarget(invoice)}
          className={styles.invoiceAction}
          aria-label={`Registrar pagamento de ${invoice.invoice_number}`}
          title="Registrar pagamento"
        >
          <CheckCircle2 />
          {mobile && <span>Pagar</span>}
        </button>
      )}
      {canDeleteInvoice(invoice) && (
        <button
          type="button"
          onClick={() => setDeleteInvoiceTarget(invoice)}
          className={cx(styles.invoiceAction, styles.invoiceActionDanger)}
          aria-label={`Excluir ${invoice.invoice_number}`}
          title="Excluir fatura"
        >
          <Trash2 />
          {mobile && <span>Excluir</span>}
        </button>
      )}
    </div>
  );

  const renderInvoices = () => {
    const summary = [
      { icon: Receipt, label: 'Faturado no período', value: money(invoiceMetrics.total), helper: `${orderedInvoices.length} fatura${orderedInvoices.length === 1 ? '' : 's'}` },
      { icon: Clock, label: 'Em aberto', value: money(invoiceMetrics.open), helper: 'Saldo aguardando pagamento' },
      { icon: CheckCircle2, label: 'Recebido', value: money(invoiceMetrics.received), helper: 'Pagamentos confirmados' },
      { icon: AlertCircle, label: 'Vencido', value: money(invoiceMetrics.overdue), helper: `${invoiceMetrics.overdueCount} vencida${invoiceMetrics.overdueCount === 1 ? '' : 's'}` },
    ];

    return (
      <div className={styles.invoiceWorkspace}>
        <section className={styles.invoiceSummary} aria-label="Resumo das faturas do período">
          {summary.map(({ icon: Icon, label, value, helper }) => (
            <div key={label} className={styles.invoiceSummaryItem}>
              <div className={styles.invoiceSummaryIcon}><Icon /></div>
              <div className={styles.invoiceSummaryCopy}>
                <p className={styles.invoiceSummaryLabel}>{label}</p>
                <p className={styles.invoiceSummaryValue}>{value}</p>
                <p className={styles.invoiceSummaryHelper}>{helper}</p>
              </div>
            </div>
          ))}
        </section>

        <section className={cx(styles.panel, styles.invoicePanel)}>
          <div className={styles.invoiceToolbar}>
            <div className={styles.invoiceToolbarCopy}>
              <p className={styles.invoiceToolbarTitle}>Cobranças do período</p>
              <p className={styles.invoiceToolbarDescription}>
                {orderedInvoices.length} de {invoices.length} faturas exibidas
              </p>
            </div>
            <div className={styles.invoiceFilters}>
              <label className={styles.invoiceFilterField}>
                <span>Vencimento</span>
                <select
                  value={invoiceMonthFilter}
                  onChange={event => setInvoiceMonthFilter(event.target.value)}
                  className={styles.invoiceFilterSelect}
                >
                  <option value="">Todos os vencimentos</option>
                  {invoiceMonthOptions.map(month => (
                    <option key={month} value={month}>{monthLabel(month)}</option>
                  ))}
                </select>
              </label>
              {invoiceMonthFilter && (
                <button
                  type="button"
                  onClick={() => setInvoiceMonthFilter('')}
                  className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}
                >
                  Limpar
                </button>
              )}
            </div>
          </div>

          {loading ? (
            <div className={styles.loadingState}>
              <Loader2 className="animate-spin" />
              Carregando faturas
            </div>
          ) : orderedInvoices.length > 0 ? (
            <>
              <div className={styles.invoiceDesktop}>
                <div className={styles.invoiceTableScroll}>
                  <table className={styles.invoiceTable}>
                    <thead>
                      <tr>
                        <th>{renderInvoiceSortHeader('installment', 'Fatura')}</th>
                        <th>{renderInvoiceSortHeader('customer', 'Cliente')}</th>
                        <th>{renderInvoiceSortHeader('status', 'Status')}</th>
                        <th>{renderInvoiceSortHeader('issue_date', 'Emissão')}</th>
                        <th>{renderInvoiceSortHeader('due_date', 'Vencimento')}</th>
                        <th>{renderInvoiceSortHeader('total', 'Total')}</th>
                        <th>{renderInvoiceSortHeader('amount_paid', 'Recebido')}</th>
                        <th><span className={styles.invoiceActionsHeading}>Ações</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {orderedInvoices.map(invoice => (
                        <tr key={invoice.id}>
                          <td>
                            <div className={styles.invoiceIdentity}>
                              <div>
                                <p className={styles.invoiceInstallment}>Parcela {invoiceInstallmentLabel(invoice, invoices)}</p>
                                <p className={styles.invoiceNumber}>{invoice.invoice_number}</p>
                              </div>
                              <RecordSourceBadge externalId={invoice.external_id} gateway={invoice.gateway} compact />
                            </div>
                          </td>
                          <td><span className={styles.invoiceCustomer}>{getInvoiceCustomerName(invoice)}</span></td>
                          <td><StatusBadge status={invoice.status} /></td>
                          <td><span className={styles.invoiceDate}>{shortDate(invoice.issue_date)}</span></td>
                          <td><span className={styles.invoiceDateStrong}>{shortDate(invoice.due_date)}</span></td>
                          <td><span className={styles.invoiceMoney}>{money(invoice.total)}</span></td>
                          <td>
                            <div className={styles.invoicePaymentValues}>
                              <span className={styles.invoiceMoney}>{money(invoice.amount_paid)}</span>
                              {numberValue(invoice.amount_due) > 0 && <small>{money(invoice.amount_due)} em aberto</small>}
                            </div>
                          </td>
                          <td>{renderInvoiceActions(invoice)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className={styles.invoiceMobileList}>
                {orderedInvoices.map(invoice => (
                  <article key={invoice.id} className={styles.invoiceMobileCard}>
                    <div className={styles.invoiceMobileHeader}>
                      <div className={styles.invoiceMobileIdentity}>
                        <p>{getInvoiceCustomerName(invoice)}</p>
                        <span>{invoice.invoice_number} · Parcela {invoiceInstallmentLabel(invoice, invoices)}</span>
                      </div>
                      <StatusBadge status={invoice.status} />
                    </div>
                    <div className={styles.invoiceMobileGateway}>
                      <RecordSourceBadge externalId={invoice.external_id} gateway={invoice.gateway} compact />
                    </div>
                    <dl className={styles.invoiceMobileDetails}>
                      <div><dt>Vencimento</dt><dd>{shortDate(invoice.due_date)}</dd></div>
                      <div><dt>Total</dt><dd>{money(invoice.total)}</dd></div>
                      <div><dt>Recebido</dt><dd>{money(invoice.amount_paid)}</dd></div>
                      <div><dt>Em aberto</dt><dd>{money(invoice.amount_due)}</dd></div>
                    </dl>
                    {renderInvoiceActions(invoice, true)}
                  </article>
                ))}
              </div>
            </>
          ) : (
            <div className={styles.invoiceEmpty}>
              <CustomerContextEmptyState
                icon={Receipt}
                title={invoiceMonthFilter ? 'Nenhuma fatura neste mês' : 'Nenhuma fatura registrada'}
                description={invoiceMonthFilter ? `Não existem vencimentos em ${monthLabel(invoiceMonthFilter)}.` : 'As cobranças aparecem aqui após registrar uma venda ou gerar uma recorrência.'}
                action={invoiceMonthFilter ? (
                  <button type="button" onClick={() => setInvoiceMonthFilter('')} className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}>
                    Ver todas as faturas
                  </button>
                ) : undefined}
              />
            </div>
          )}
        </section>
      </div>
    );
  };

  const renderPlans = () => {
    const summary = [
      { icon: Package, label: 'Itens cadastrados', value: planMetrics.total, helper: 'Catálogo completo' },
      { icon: CheckCircle2, label: 'Planos ativos', value: planMetrics.active, helper: 'Disponíveis para venda' },
      { icon: Repeat, label: 'Recorrentes', value: planMetrics.recurring, helper: 'Cobranças periódicas' },
      { icon: Receipt, label: 'Avulsos', value: planMetrics.once, helper: 'Cobrança única' },
    ];

    return (
      <div className={styles.planWorkspace}>
        <section className={styles.planSummary} aria-label="Resumo do catálogo de planos">
          {summary.map(({ icon: Icon, label, value, helper }) => (
            <div key={label} className={styles.planSummaryItem}>
              <div className={styles.planSummaryIcon}><Icon /></div>
              <div className={styles.planSummaryCopy}>
                <p className={styles.planSummaryLabel}>{label}</p>
                <p className={styles.planSummaryValue}>{value}</p>
                <p className={styles.planSummaryHelper}>{helper}</p>
              </div>
            </div>
          ))}
        </section>

        <div className={styles.planManagementGrid}>
          <section className={cx(styles.panel, styles.planCatalogPanel)}>
            <div className={styles.planCatalogToolbar}>
              <div className={styles.planCatalogHeading}>
                <p>Catálogo comercial</p>
                <span>{filteredCatalogPlans.length} de {plans.length} itens</span>
              </div>
              <div className={styles.planCatalogFilters}>
                <label className={styles.planSearchField}>
                  <Search />
                  <input
                    value={planCatalogSearch}
                    onChange={event => setPlanCatalogSearch(event.target.value)}
                    placeholder="Buscar plano"
                    aria-label="Buscar plano por nome"
                  />
                </label>
                <select
                  value={planCatalogType}
                  onChange={event => setPlanCatalogType(event.target.value as PlanCatalogType)}
                  className={styles.planFilterSelect}
                  aria-label="Filtrar planos por tipo"
                >
                  <option value="all">Todos os tipos</option>
                  <option value="recurring">Recorrentes</option>
                  <option value="once">Avulsos</option>
                </select>
                <select
                  value={planCatalogStatus}
                  onChange={event => setPlanCatalogStatus(event.target.value as PlanCatalogStatus)}
                  className={styles.planFilterSelect}
                  aria-label="Filtrar planos por status"
                >
                  <option value="all">Todos os status</option>
                  <option value="active">Ativos</option>
                  <option value="inactive">Inativos</option>
                </select>
                {hasPlanCatalogFilters && (
                  <button type="button" onClick={clearPlanCatalogFilters} className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}>
                    Limpar
                  </button>
                )}
              </div>
            </div>

            {loading ? (
              <div className={styles.loadingState}>
                <Loader2 className="animate-spin" />
                Carregando planos
              </div>
            ) : filteredCatalogPlans.length > 0 ? (
              <div className={styles.planList}>
                {filteredCatalogPlans.map(plan => {
                  const TypeIcon = plan.billing_interval === 'once' ? Receipt : Repeat;
                  return (
                    <article key={plan.id} className={cx(styles.planRow, !plan.is_active && styles.planRowInactive)}>
                      <div className={styles.planIdentity}>
                        <div className={styles.planIcon}><Package /></div>
                        <div className={styles.planIdentityCopy}>
                          <div className={styles.planNameRow}>
                            <p className={styles.planName}>{plan.name}</p>
                            <StatusBadge status={plan.is_active ? 'ativo' : 'inativo'} />
                          </div>
                          <p className={styles.planDescription}>
                            {billingIntervalLabel[plan.billing_interval] || plan.billing_interval} · cobrança em BRL
                          </p>
                        </div>
                      </div>
                      <span className={styles.planTypeBadge}>
                        <TypeIcon />
                        {plan.billing_interval === 'once' ? 'Avulso' : 'Recorrente'}
                      </span>
                      <div className={styles.planPrice}>
                        <strong>{money(plan.price)}</strong>
                        <span>por cobrança {billingCycleCopy(plan.billing_interval)}</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => openPlanEdit(plan)}
                        className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact, styles.planEditButton)}
                      >
                        <Pencil />
                        Editar
                      </button>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className={styles.planEmpty}>
                <CustomerContextEmptyState
                  icon={hasPlanCatalogFilters ? Search : Package}
                  title={hasPlanCatalogFilters ? 'Nenhum plano encontrado' : 'Catálogo ainda vazio'}
                  description={hasPlanCatalogFilters ? 'Revise a busca ou os filtros aplicados.' : 'Use o formulário de criação para cadastrar o primeiro item.'}
                  action={hasPlanCatalogFilters ? (
                    <button type="button" onClick={clearPlanCatalogFilters} className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}>
                      Limpar filtros
                    </button>
                  ) : undefined}
                />
              </div>
            )}
          </section>

          <form onSubmit={submitPlan} className={cx(styles.panel, styles.planCreatePanel)}>
            <div className={styles.planCreateHeader}>
              <div className={styles.planCreateIcon}><Plus /></div>
              <div>
                <h2>Novo plano</h2>
                <p>Crie um item para vendas e cobranças.</p>
              </div>
            </div>
            <div className={styles.planCreateBody}>
              <Field label="Nome do plano">
                <input
                  value={planForm.name}
                  onChange={event => setPlanForm(prev => ({ ...prev, name: event.target.value }))}
                  className={styles.planControl}
                  placeholder="Ex.: Gestão mensal"
                  required
                />
              </Field>
              <Field label="Valor por cobrança">
                <input
                  inputMode="numeric"
                  value={planForm.price}
                  onChange={event => setPlanForm(prev => ({ ...prev, price: formatBRLTyping(event.target.value) }))}
                  onBlur={() => {
                    const value = parseBRL(planForm.price);
                    setPlanForm(prev => ({ ...prev, price: value > 0 ? money(value) : '' }));
                  }}
                  className={styles.planControl}
                  placeholder="R$ 0,00"
                  required
                />
              </Field>
              <Field label="Frequência da cobrança">
                <select
                  value={planForm.billingInterval}
                  onChange={event => setPlanForm(prev => ({ ...prev, billingInterval: event.target.value }))}
                  className={styles.planControl}
                >
                  <option value="once">Avulsa</option>
                  <option value="monthly">Mensal</option>
                  <option value="quarterly">Trimestral</option>
                  <option value="yearly">Anual</option>
                </select>
              </Field>
              <p className={styles.planFieldHelper}>{planPriceHelper(planForm.billingInterval)}</p>
              <button type="submit" disabled={actionLoading} className={cx(styles.button, styles.buttonPrimary, styles.planSubmitButton)}>
                {actionLoading ? <Loader2 className="animate-spin" /> : <Plus />}
                Criar plano
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  };

  const renderRevenue = () => {
    if (loading) {
      return (
        <section className={cx(styles.panel, styles.revenueLoading)} aria-live="polite" aria-busy="true">
          <Loader2 className="animate-spin" />
          <div>
            <p>Carregando indicadores financeiros</p>
            <span>Consolidando recebimentos, faturas e carteira.</span>
          </div>
        </section>
      );
    }

    const openAmount = numberValue(overview.open_amount);
    const overdueAmount = numberValue(overview.overdue_amount);
    const dueSoonAmount = Math.max(openAmount - overdueAmount, 0);
    const openInvoices = Number(overview.open_invoices || 0);
    const overdueInvoices = Number(overview.overdue_invoices || 0);
    const dueSoonInvoices = Math.max(openInvoices - overdueInvoices, 0);
    const overdueShare = openAmount > 0 ? clampPercent((overdueAmount / openAmount) * 100) : 0;
    const dueSoonShare = openAmount > 0 ? clampPercent((dueSoonAmount / openAmount) * 100) : 0;
    const totalCustomers = Number(overview.total_customers || 0);
    const activeCustomers = Number(overview.active_customers || 0);
    const churnedCustomers = Number(overview.churned_customers || 0);
    const otherCategories = Math.max(totalCustomers - churnedCustomers, 0);
    const customerShare = (value: number) => totalCustomers > 0
      ? clampPercent((value / totalCustomers) * 100)
      : 0;

    const summaryItems = [
      {
        label: 'MRR recorrente',
        value: money(overview.mrr),
        helper: 'Contratos recorrentes atuais',
        icon: Repeat,
      },
      {
        label: 'Recebido líquido',
        value: money(overview.paid_amount),
        helper: 'Pagamentos menos estornos',
        icon: CreditCard,
      },
      {
        label: 'Em aberto',
        value: money(openAmount),
        helper: `${openInvoices} ${openInvoices === 1 ? 'fatura' : 'faturas'}`,
        icon: Receipt,
      },
      {
        label: 'Vencido',
        value: money(overdueAmount),
        helper: `${overdueInvoices} ${overdueInvoices === 1 ? 'fatura' : 'faturas'}`,
        icon: AlertCircle,
        danger: overdueAmount > 0,
      },
    ];

    return (
      <div className={styles.revenueWorkspace}>
        <section className={styles.revenueSummary} aria-label="Resumo financeiro">
          {summaryItems.map(item => {
            const Icon = item.icon;
            return (
              <div key={item.label} className={styles.revenueSummaryItem}>
                <span className={cx(styles.revenueSummaryIcon, item.danger && styles.revenueSummaryIconDanger)}>
                  <Icon />
                </span>
                <div className={styles.revenueSummaryCopy}>
                  <p className={styles.revenueSummaryLabel}>{item.label}</p>
                  <p className={styles.revenueSummaryValue}>{item.value}</p>
                  <p className={styles.revenueSummaryHelper}>{item.helper}</p>
                </div>
              </div>
            );
          })}
        </section>

        <div className={styles.revenueDetailsGrid}>
          <section className={cx(styles.panel, styles.revenuePanel)}>
            <header className={styles.revenuePanelHeader}>
              <div>
                <p>Qualidade dos recebíveis</p>
                <span>Composição atual do saldo em aberto.</span>
              </div>
              <strong className={cx(styles.revenueRiskBadge, overdueAmount > 0 && styles.revenueRiskBadgeDanger)}>
                {Math.round(overdueShare)}% vencido
              </strong>
            </header>

            {openAmount > 0 ? (
              <div className={styles.receivablesBody}>
                <div
                  className={styles.receivablesTrack}
                  role="img"
                  aria-label={`${Math.round(dueSoonShare)}% a vencer e ${Math.round(overdueShare)}% vencido`}
                >
                  <span className={styles.receivablesTrackDue} style={{ width: `${dueSoonShare}%` }} />
                  <span className={styles.receivablesTrackOverdue} style={{ width: `${overdueShare}%` }} />
                </div>

                <div className={styles.receivablesLegend}>
                  <div className={styles.receivableRow}>
                    <span className={styles.receivableSignal} />
                    <div className={styles.receivableCopy}>
                      <p>A vencer</p>
                      <span>{dueSoonInvoices} {dueSoonInvoices === 1 ? 'fatura' : 'faturas'}</span>
                    </div>
                    <strong>{money(dueSoonAmount)}</strong>
                  </div>
                  <div className={styles.receivableRow}>
                    <span className={cx(styles.receivableSignal, styles.receivableSignalDanger)} />
                    <div className={styles.receivableCopy}>
                      <p>Vencido</p>
                      <span>{overdueInvoices} {overdueInvoices === 1 ? 'fatura' : 'faturas'}</span>
                    </div>
                    <strong className={overdueAmount > 0 ? styles.receivableValueDanger : undefined}>{money(overdueAmount)}</strong>
                  </div>
                </div>
              </div>
            ) : (
              <div className={styles.revenueInlineEmpty}>
                <CheckCircle2 />
                <div>
                  <p>Nenhum saldo em aberto</p>
                  <span>Não há faturas pendentes ou vencidas neste momento.</span>
                </div>
              </div>
            )}
          </section>

          <section className={cx(styles.panel, styles.revenuePanel)}>
            <header className={styles.revenuePanelHeader}>
              <div>
                <p>Saúde da carteira</p>
                <span>Status e retenção sobre a base atual.</span>
              </div>
              <div className={styles.healthTotal}>
                <strong>{totalCustomers}</strong>
                <span>clientes</span>
              </div>
            </header>

            <div className={styles.healthRows}>
              <div className={styles.healthRow}>
                <div className={styles.healthMeta}>
                  <span>Clientes ativos</span>
                  <strong>{activeCustomers} · {Math.round(customerShare(activeCustomers))}%</strong>
                </div>
                <div className={styles.healthTrack}>
                  <span className={styles.healthTrackFill} style={{ width: `${customerShare(activeCustomers)}%` }} />
                </div>
              </div>
              <div className={styles.healthRow}>
                <div className={styles.healthMeta}>
                  <span>Ex-clientes</span>
                  <strong>{churnedCustomers} · {Math.round(customerShare(churnedCustomers))}%</strong>
                </div>
                <div className={styles.healthTrack}>
                  <span className={cx(styles.healthTrackFill, styles.healthTrackFillDanger)} style={{ width: `${customerShare(churnedCustomers)}%` }} />
                </div>
              </div>
              <div className={styles.healthRow}>
                <div className={styles.healthMeta}>
                  <span>Demais categorias</span>
                  <strong>{otherCategories} · {Math.round(customerShare(otherCategories))}%</strong>
                </div>
                <div className={styles.healthTrack}>
                  <span className={cx(styles.healthTrackFill, styles.healthTrackFillNeutral)} style={{ width: `${customerShare(otherCategories)}%` }} />
                </div>
              </div>
            </div>

            <p className={styles.revenueNote}>
              Ex-clientes representa o churn acumulado por categoria; clientes ativos considera o status atual da carteira.
            </p>
          </section>
        </div>
      </div>
    );
  };

  const renderSaleModal = () => {
    const isCustomerFlow = saleFlowMode === 'customer';

    return (
      <ModalShell title={isCustomerFlow ? 'Novo cliente' : 'Nova venda'} onClose={resetSaleFlow} size="xl">
        <div className={styles.saleFlow}>
          <aside className={styles.saleFlowRail} aria-label="Etapas do cadastro">
            <div className={styles.saleFlowRailIntro}>
              <span className={styles.modalEyebrow}>{isCustomerFlow ? 'Cadastro integrado' : 'Fluxo comercial'}</span>
              <p>{isCustomerFlow ? 'Converta um contato da base em cliente.' : 'Do contato à primeira cobrança, sem trocar de tela.'}</p>
            </div>
            <SaleStepIndicator activeStep={saleStep} mode={saleFlowMode} />
          </aside>

          <div className={styles.saleFlowStage}>
            <div className={styles.deferredFlowNotice} role="status">
              <Clock />
              <div>
                <strong>Gestão financeira local</strong>
                <span>
                  Clientes, contratos, faturas e pagamentos ficam registrados e são gerenciados em {branding.appName}.
                </span>
              </div>
            </div>
            {saleStep === 'contact' && (
              <div className={styles.flowStepContent}>
                <FlowSectionHeader
                  eyebrow="Etapa 1"
                  title="Escolha o contato"
                  description={isCustomerFlow
                    ? 'Use um contato existente para manter CRM, cliente e dados financeiros conectados.'
                    : 'A venda começa por um contato existente e preserva todo o histórico comercial.'}
                  icon={Search}
                />
                <div className={styles.flowSearchBlock}>
                  <span className={styles.formLabel}>Buscar contato</span>
                  <div className={styles.flowSearchField}>
                    <Search />
                    <input
                      value={contactSearch}
                      onChange={event => {
                        setContactSearch(event.target.value);
                        setSaleForm(prev => ({ ...prev, contactId: '', leadId: '' }));
                        setSelectedSaleContact(null);
                        setSaleCustomerId(null);
                      }}
                      className={agentiveInputClass(isDark)}
                      placeholder="Buscar por nome ou telefone"
                      autoFocus
                    />
                  </div>
                  <div className={styles.flowResults}>
                    {contactsLoading ? (
                      <div className={styles.flowLoading}>
                        <Loader2 className="animate-spin" />
                        Buscando contatos
                      </div>
                    ) : contactResults.length > 0 ? (
                      contactResults.map(contact => (
                        <button
                          key={contact.id || contact.phone}
                          type="button"
                          onClick={() => selectContactForSale(contact)}
                          className={cx(styles.flowResult, String(contact.id) === saleForm.contactId && styles.flowResultSelected)}
                        >
                          <span className={styles.flowResultIdentity}>
                            <span className={styles.flowResultAvatar}>{(contact.name || contact.phone || 'C').trim().charAt(0).toUpperCase()}</span>
                            <span className={styles.flowResultCopy}>
                              <strong>{contact.name || 'Contato sem nome'}</strong>
                              <small>{contact.phone}</small>
                            </span>
                          </span>
                          <span className={styles.neutralBadge}>
                            {contact.customer_id ? 'Cliente existente' : contact.lead_id ? 'Lead' : 'Contato'}
                          </span>
                        </button>
                      ))
                    ) : (
                      <AgentiveEmptyState
                        icon={Search}
                        title="Nenhum contato encontrado"
                        description={isCustomerFlow
                          ? 'Revise a busca ou cadastre o contato pelo CRM antes de criar o cliente.'
                          : 'Revise a busca ou cadastre o contato pelo CRM antes da venda.'}
                      />
                    )}
                  </div>
                </div>
              </div>
            )}

            {saleStep === 'customer' && (
              <form onSubmit={submitSaleCustomer} className={styles.flowForm}>
                <FlowSectionHeader
                  eyebrow="Etapa 2"
                  title="Dados do cliente"
                  description={isCustomerFlow
                    ? 'Revise o contato e complete os dados necessários para criar o cliente.'
                    : 'Confirme os dados cadastrais antes de preparar contrato e cobrança.'}
                  icon={Users}
                  badge={selectedSaleContact ? selectedSaleContact.name || selectedSaleContact.phone : undefined}
                />
                <CustomerProfileFields
                  form={saleCustomerForm}
                  onChange={patch => setSaleCustomerForm(prev => ({ ...prev, ...patch }))}
                />
                <div className={styles.flowFooter}>
                  <button type="button" onClick={() => setSaleStep('contact')} className={cx(styles.button, styles.buttonSecondary)}>
                    Voltar
                  </button>
                  <button type="submit" disabled={actionLoading || Boolean(validateCustomerProfile(saleCustomerForm))} className={cx(styles.button, styles.buttonPrimary)}>
                    {actionLoading ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}
                    {isCustomerFlow ? 'Salvar cliente' : 'Salvar e continuar'}
                  </button>
                </div>
              </form>
            )}

            {!isCustomerFlow && saleStep === 'sale' && (
              <form onSubmit={submitSale} className={styles.flowForm}>
                <FlowSectionHeader
                  eyebrow="Etapa 3"
                  title="Venda, contrato e fatura"
                  description="Configure o serviço, a recorrência e a primeira cobrança deste cliente."
                  icon={FileText}
                  badge={saleCustomerForm.name || `Cliente #${saleCustomerId}`}
                />

                <section className={styles.formSection}>
                  <div className={styles.formSectionHeader}>
                    <div>
                      <h4>Produto ou plano</h4>
                      <p>Selecione o item que dará origem ao contrato.</p>
                    </div>
                    <Package />
                  </div>
                  <div className={styles.formSectionBody}>
                    <div className={styles.flowSearchField}>
                      <Search />
                      <input
                        value={planSearch}
                        onChange={event => {
                          setPlanSearch(event.target.value);
                          setSaleForm(prev => ({ ...prev, planId: '', description: '', unitPrice: '', priceMode: 'cycle' }));
                        }}
                        className={agentiveInputClass(isDark)}
                        placeholder="Buscar produto ou plano cadastrado"
                        required
                      />
                    </div>
                    <div className={cx(styles.flowResults, styles.flowResultsCompact)}>
                      {filteredPlans.length > 0 ? (
                        filteredPlans.map(plan => (
                          <button
                            key={plan.id}
                            type="button"
                            onClick={() => selectPlanForSale(plan)}
                            className={cx(styles.flowResult, String(plan.id) === saleForm.planId && styles.flowResultSelected)}
                          >
                            <span className={styles.flowResultCopy}>
                              <strong>{plan.name}</strong>
                              <small>{billingIntervalLabel[plan.billing_interval] || plan.billing_interval}</small>
                            </span>
                            <strong className={styles.flowResultValue}>{money(plan.price)}</strong>
                          </button>
                        ))
                      ) : (
                        <p className={styles.inlineEmpty}>Nenhum produto ativo encontrado. Cadastre em Planos antes de registrar a venda.</p>
                      )}
                    </div>
                    {selectedPlan && <p className={styles.formHint}>Selecionado: {selectedPlan.name} · {money(selectedPlan.price)}</p>}
                  </div>
                </section>

                <section className={styles.formSection}>
                  <div className={styles.formSectionHeader}>
                    <div>
                      <h4>Condição comercial</h4>
                      <p>Defina o valor e a frequência da cobrança.</p>
                    </div>
                    <Repeat />
                  </div>
                  <div className={styles.formSectionBody}>
                    <div className={styles.formGridTwo}>
                      <Field label={salePricing.monthlyMode ? 'Valor mensal em BRL' : 'Valor da fatura em BRL'}>
                        <input
                          inputMode="numeric"
                          value={saleForm.unitPrice}
                          onChange={event => setSaleForm(prev => ({ ...prev, unitPrice: formatBRLTyping(event.target.value) }))}
                          onBlur={() => {
                            const value = parseBRL(saleForm.unitPrice);
                            setSaleForm(prev => ({ ...prev, unitPrice: value > 0 ? money(value) : '' }));
                          }}
                          className={agentiveInputClass(isDark)}
                          placeholder="R$ 0,00"
                          required
                        />
                      </Field>
                      <Field label="Cobrança">
                        <select
                          value={saleForm.billingInterval}
                          onChange={event => setSaleForm(prev => ({
                            ...prev,
                            billingInterval: event.target.value,
                            priceMode: event.target.value === 'once' ? 'cycle' : prev.priceMode,
                          }))}
                          className={agentiveInputClass(isDark)}
                        >
                          <option value="once">Avulsa</option>
                          <option value="monthly">Mensal recorrente</option>
                          <option value="quarterly">Trimestral recorrente</option>
                          <option value="yearly">Anual recorrente</option>
                        </select>
                      </Field>
                    </div>

                    {salePricing.isRecurring && (
                      <div className={styles.priceModeGrid}>
                        <button
                          type="button"
                          onClick={() => setSaleForm(prev => ({ ...prev, priceMode: 'cycle' }))}
                          className={cx(styles.priceMode, saleForm.priceMode === 'cycle' && styles.priceModeSelected)}
                        >
                          <strong>Valor da fatura</strong>
                          <span>O valor informado já representa o total do ciclo.</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => setSaleForm(prev => ({ ...prev, priceMode: 'monthly' }))}
                          className={cx(styles.priceMode, saleForm.priceMode === 'monthly' && styles.priceModeSelected)}
                        >
                          <strong>Valor mensal</strong>
                          <span>O ciclo será calculado automaticamente a partir do MRR.</span>
                        </button>
                      </div>
                    )}
                    <SaleFinancialSummary pricing={salePricing} billingInterval={saleForm.billingInterval} dueDate={saleForm.dueDate} />
                  </div>
                </section>

                <section className={styles.formSection}>
                  <div className={styles.formSectionHeader}>
                    <div>
                      <h4>Pagamento</h4>
                      <p>Configure vencimento, parcelas e eventuais valores já recebidos.</p>
                    </div>
                    <CreditCard />
                  </div>
                  <div className={styles.formSectionBody}>
                    <div className={styles.formGridThree}>
                      <Field label="Método">
                        <select value={saleForm.paymentMethod} onChange={event => setSaleForm(prev => ({ ...prev, paymentMethod: event.target.value }))} className={agentiveInputClass(isDark)}>
                          <option value="boleto">Boleto/Pix</option>
                          <option value="credit_card">Cartão</option>
                          <option value="transfer">Transferência</option>
                          <option value="cash">Dinheiro</option>
                        </select>
                      </Field>
                      <Field label="Parcelas">
                        <input
                          type="number"
                          min="1"
                          value={saleForm.installments}
                          onChange={event => {
                            const nextInstallments = Math.max(1, Number(event.target.value || 1));
                            setSaleForm(prev => ({
                              ...prev,
                              installments: event.target.value,
                              initialPaymentInstallment: Number(prev.initialPaymentInstallment || 1) > nextInstallments
                                ? String(nextInstallments)
                                : prev.initialPaymentInstallment,
                            }));
                          }}
                          className={agentiveInputClass(isDark)}
                        />
                      </Field>
                      <Field label="Vencimento">
                        <input type="date" value={saleForm.dueDate} onChange={event => setSaleForm(prev => ({ ...prev, dueDate: event.target.value }))} className={agentiveInputClass(isDark)} />
                      </Field>
                    </div>

                    <label className={styles.formToggle}>
                      <input
                        type="checkbox"
                        checked={saleForm.initialPaymentReceived}
                        onChange={event => setSaleForm(prev => ({
                          ...prev,
                          initialPaymentReceived: event.target.checked,
                          initialPayment: event.target.checked ? prev.initialPayment : '',
                          initialPaymentInstallment: '1',
                          initialPaymentDate: todayISO(),
                        }))}
                      />
                      <span>
                        <strong>Pagamento já recebido</strong>
                        <small>Use somente quando houve uma entrada manual fora da plataforma.</small>
                      </span>
                    </label>

                    {saleForm.initialPaymentReceived && (
                      <div className={styles.formGridFour}>
                        <Field label="Valor recebido">
                          <input
                            inputMode="numeric"
                            value={saleForm.initialPayment}
                            onChange={event => setSaleForm(prev => ({ ...prev, initialPayment: formatBRLTyping(event.target.value) }))}
                            onBlur={() => {
                              const value = parseBRL(saleForm.initialPayment);
                              setSaleForm(prev => ({ ...prev, initialPayment: value > 0 ? money(value) : '' }));
                            }}
                            className={agentiveInputClass(isDark)}
                            placeholder="R$ 0,00"
                          />
                        </Field>
                        <Field label="Data">
                          <input type="date" value={saleForm.initialPaymentDate} onChange={event => setSaleForm(prev => ({ ...prev, initialPaymentDate: event.target.value }))} className={agentiveInputClass(isDark)} />
                        </Field>
                        <Field label="Método">
                          <select value={saleForm.initialPaymentMethod} onChange={event => setSaleForm(prev => ({ ...prev, initialPaymentMethod: event.target.value }))} className={agentiveInputClass(isDark)}>
                            <option value="boleto">Boleto/Pix</option>
                            <option value="credit_card">Cartão</option>
                            <option value="transfer">Transferência</option>
                            <option value="cash">Dinheiro</option>
                          </select>
                        </Field>
                        {Number(saleForm.installments || 1) > 1 && (
                          <Field label="Parcela">
                            <select value={saleForm.initialPaymentInstallment} onChange={event => setSaleForm(prev => ({ ...prev, initialPaymentInstallment: event.target.value }))} className={agentiveInputClass(isDark)}>
                              {Array.from({ length: Math.max(1, Number(saleForm.installments || 1)) }, (_, index) => (
                                <option key={index + 1} value={index + 1}>{index + 1}/{saleForm.installments}</option>
                              ))}
                            </select>
                          </Field>
                        )}
                      </div>
                    )}
                  </div>
                </section>

                <section className={styles.formSection}>
                  <div className={styles.formSectionHeader}>
                    <div>
                      <h4>Observações internas</h4>
                      <p>Contexto opcional para o histórico comercial.</p>
                    </div>
                    <FileText />
                  </div>
                  <div className={styles.formSectionBody}>
                    <textarea value={saleForm.notes} onChange={event => setSaleForm(prev => ({ ...prev, notes: event.target.value }))} className={agentiveTextareaClass(isDark)} />
                  </div>
                </section>

                <div className={styles.flowFooter}>
                  <button type="button" onClick={() => setSaleStep('customer')} className={cx(styles.button, styles.buttonSecondary)}>Voltar</button>
                  <button type="submit" disabled={actionLoading || !saleForm.planId || !salePricing.invoiceTotal} className={cx(styles.button, styles.buttonPrimary)}>
                    {actionLoading ? <Loader2 className="animate-spin" /> : <FileText />}
                    Salvar contrato e fatura
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      </ModalShell>
    );
  };

  const activeSectionCopy = sectionCopy[activeSection];

  return (
    <main className={cx(styles.page, isDark && styles.dark)}>
      <div className={styles.content}>
        <header className={styles.header}>
          <div className={styles.headerLead}>
            <Users className={styles.titleIcon} />
            <div className={styles.headerCopy}>
              <p className={styles.eyebrow}>Gestão de clientes</p>
              <h1 className={styles.title}>{activeSectionCopy.title}</h1>
              <p className={styles.subtitle}>{activeSectionCopy.description}</p>
            </div>
          </div>
        </header>

        {notice && (
          <AgentiveAlert className={styles.feedback} variant={notice.type} onClose={() => setNotice(null)}>
            {notice.message}
          </AgentiveAlert>
        )}

        <div className={styles.toolbar}>
          {renderTabs()}
          <div className={styles.toolbarActions}>
            <button type="button" onClick={openSaleFlow} className={cx(styles.button, styles.buttonPrimary)}>
              <Plus />
              Nova venda
            </button>
            <button
              type="button"
              onClick={() => refreshAll()}
              className={cx(styles.button, styles.buttonSecondary, styles.iconButton)}
              aria-label="Atualizar dados da carteira"
              title="Atualizar dados"
            >
              <RefreshCw />
            </button>
          </div>
        </div>

        {activeSection === 'customers' && renderOverview()}

        {activeSection === 'customers' && renderCustomers()}
        {activeSection === 'invoices' && renderInvoices()}
        {activeSection === 'plans' && renderPlans()}
        {activeSection === 'revenue' && renderRevenue()}
      </div>

      {showSaleModal && renderSaleModal()}

      {editingCustomer && (
        <ModalShell title="Editar perfil do cliente" onClose={() => setEditingCustomer(null)} size="xl">
          <form onSubmit={submitCustomerEdit} className="space-y-4">
            <CustomerProfileFields
              form={customerEditForm}
              onChange={patch => setCustomerEditForm(prev => ({ ...prev, ...patch }))}
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Status">
                <select
                  value={customerEditForm.status}
                  onChange={event => setCustomerEditForm(prev => ({ ...prev, status: event.target.value }))}
                  className={agentiveInputClass(isDark)}
                >
                  <option value="ativo">Ativo</option>
                  <option value="inativo">Inativo</option>
                  <option value="bloqueado">Bloqueado</option>
                </select>
              </Field>
              <Field label="Categoria">
                <select
                  value={customerEditForm.categoria}
                  onChange={event => setCustomerEditForm(prev => ({ ...prev, categoria: event.target.value }))}
                  className={agentiveInputClass(isDark)}
                >
                  <option value="cliente">Cliente</option>
                  <option value="prospect">Prospect</option>
                  <option value="lead_qualificado">Lead qualificado</option>
                  <option value="ex_cliente">Ex-cliente</option>
                </select>
              </Field>
            </div>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setEditingCustomer(null)} className={agentiveSecondaryButtonClass(isDark)}>Cancelar</button>
              <button type="submit" disabled={actionLoading || Boolean(validateCustomerProfile(customerEditForm))} className={agentivePrimaryButtonClass()}>
                {actionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pencil className="h-4 w-4" />}
                Salvar cliente
              </button>
            </div>
          </form>
        </ModalShell>
      )}

      {editingPlan && (
        <ModalShell title="Editar plano" onClose={() => setEditingPlan(null)}>
          <form onSubmit={submitPlanEdit} className={styles.planEditForm}>
            <div className={styles.planEditSummary}>
              <div className={styles.planCreateIcon}><Package /></div>
              <div className={styles.planEditSummaryCopy}>
                <p>{editingPlan.name}</p>
                <span>Atualize os dados usados nas próximas vendas.</span>
              </div>
              <StatusBadge status={planEditForm.isActive ? 'ativo' : 'inativo'} />
            </div>

            <section className={styles.formSection}>
              <div className={styles.formSectionHeader}>
                <div>
                  <h4>Configuração</h4>
                  <p>Identificação e disponibilidade comercial.</p>
                </div>
                <Package />
              </div>
              <div className={styles.formSectionBody}>
                <div className={styles.formGridTwo}>
                  <Field label="Nome do plano">
                    <input
                      value={planEditForm.name}
                      onChange={event => setPlanEditForm(prev => ({ ...prev, name: event.target.value }))}
                      className={styles.planControl}
                      required
                    />
                  </Field>
                  <Field label="Status">
                    <select
                      value={planEditForm.isActive ? 'active' : 'inactive'}
                      onChange={event => setPlanEditForm(prev => ({ ...prev, isActive: event.target.value === 'active' }))}
                      className={styles.planControl}
                    >
                      <option value="active">Ativo</option>
                      <option value="inactive">Inativo</option>
                    </select>
                  </Field>
                </div>
              </div>
            </section>

            <section className={styles.formSection}>
              <div className={styles.formSectionHeader}>
                <div>
                  <h4>Cobrança</h4>
                  <p>Valor e frequência usados em novas vendas.</p>
                </div>
                <Receipt />
              </div>
              <div className={styles.formSectionBody}>
                <div className={styles.formGridTwo}>
                  <Field label="Valor por cobrança">
                    <input
                      inputMode="numeric"
                      value={planEditForm.price}
                      onChange={event => setPlanEditForm(prev => ({ ...prev, price: formatBRLTyping(event.target.value) }))}
                      onBlur={() => {
                        const value = parseBRL(planEditForm.price);
                        setPlanEditForm(prev => ({ ...prev, price: value > 0 ? money(value) : '' }));
                      }}
                      className={styles.planControl}
                      placeholder="R$ 0,00"
                      required
                    />
                  </Field>
                  <Field label="Frequência">
                    <select
                      value={planEditForm.billingInterval}
                      onChange={event => setPlanEditForm(prev => ({ ...prev, billingInterval: event.target.value }))}
                      className={styles.planControl}
                    >
                      <option value="once">Avulsa</option>
                      <option value="monthly">Mensal</option>
                      <option value="quarterly">Trimestral</option>
                      <option value="yearly">Anual</option>
                    </select>
                  </Field>
                </div>
                <p className={styles.planFieldHelper}>{planPriceHelper(planEditForm.billingInterval)}</p>
              </div>
            </section>

            <div className={styles.planModalFooter}>
              <button type="button" onClick={() => setEditingPlan(null)} className={cx(styles.button, styles.buttonSecondary)}>Cancelar</button>
              <button type="submit" disabled={actionLoading} className={cx(styles.button, styles.buttonPrimary)}>
                {actionLoading ? <Loader2 className="animate-spin" /> : <Pencil />}
                Salvar plano
              </button>
            </div>
          </form>
        </ModalShell>
      )}

      {creatingInvoiceCustomer && (
        <ModalShell
          size="xl"
          title={`Registrar fatura para ${creatingInvoiceCustomer.nome}`}
          onClose={() => setCreatingInvoiceCustomer(null)}
        >
          <form onSubmit={submitInvoiceCreate} className="space-y-4">
            <div className={cx(styles.billingModeCard, styles.billingModeCardDeferred)}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3>Registro financeiro local</h3>
                  <p>
                    {invoiceCreateForm.mode === 'subscription'
                      ? `O contrato recorrente e a primeira fatura serão salvos e gerenciados em ${branding.appName}.`
                      : `A fatura será salva e gerenciada em ${branding.appName}.`}
                  </p>
                </div>
              </div>
            </div>

            <div className={cx('grid gap-2 rounded-2xl border p-2 sm:grid-cols-2', isDark ? 'border-white/10 bg-white/[0.04]' : 'border-brand/10 bg-white')}>
              {([
                { value: 'payment', label: 'Fatura avulsa', helper: 'Um lançamento único na gestão financeira.' },
                { value: 'subscription', label: 'Contrato recorrente', helper: `Recorrência e primeira fatura gerenciadas em ${branding.appName}.` },
              ] as const).map(option => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setInvoiceCreateForm(prev => ({
                    ...prev,
                    mode: option.value,
                  }))}
                  className={cx(
                    'rounded-xl px-3 py-2 text-left text-sm transition',
                    invoiceCreateForm.mode === option.value
                      ? isDark ? 'bg-white text-brand' : 'bg-brand text-white'
                      : isDark ? 'text-white/60 hover:bg-white/10' : 'text-brand/60 hover:bg-brand-canvas'
                  )}
                >
                  <span className="block font-semibold">{option.label}</span>
                  <span className="mt-0.5 block text-xs opacity-70">{option.helper}</span>
                </button>
              ))}
            </div>

            <div>
              <span className={agentiveLabelClass(isDark)}>Produto ou plano</span>
              <div className="relative">
                <Search className={cx('absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2', isDark ? 'text-white/35' : 'text-brand/35')} />
                <input
                  value={invoicePlanSearch}
                  onChange={event => {
                    setInvoicePlanSearch(event.target.value);
                    setInvoiceCreateForm(prev => ({ ...prev, planId: '', description: '', amount: '' }));
                  }}
                  className={agentiveInputClass(isDark, 'pl-9')}
                  placeholder="Buscar produto ou plano cadastrado"
                  required
                />
              </div>
              <div className="mt-2 max-h-44 space-y-2 overflow-y-auto pr-1">
                {filteredInvoicePlans.length > 0 ? (
                  filteredInvoicePlans.map(plan => (
                    <button
                      key={plan.id}
                      type="button"
                      onClick={() => selectPlanForInvoice(plan)}
                      className={cx(
                        'flex w-full items-center justify-between gap-3 rounded-xl border p-3 text-left text-sm transition',
                        String(plan.id) === invoiceCreateForm.planId
                          ? isDark ? 'border-white/30 bg-white/10' : 'border-brand/25 bg-brand-canvas'
                          : isDark ? 'border-white/10 hover:bg-white/[0.06]' : 'border-brand/10 hover:bg-brand-canvas'
                      )}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{plan.name}</span>
                        <span className={cx('mt-0.5 block truncate text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
                          {billingIntervalLabel[plan.billing_interval] || plan.billing_interval}
                        </span>
                      </span>
                      <span className="shrink-0 text-sm font-semibold">{money(plan.price)}</span>
                    </button>
                  ))
                ) : (
                  <p className={cx('rounded-xl border border-dashed p-3 text-sm', isDark ? 'border-white/10 text-white/45' : 'border-brand/10 text-brand/45')}>
                    Nenhum produto ativo encontrado. Cadastre em Planos antes de criar a fatura.
                  </p>
                )}
              </div>
              {selectedInvoicePlan && (
                <p className={cx('mt-2 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
                  Selecionado: {selectedInvoicePlan.name} - {money(selectedInvoicePlan.price)}
                </p>
              )}
            </div>

            <Field label="Descrição">
              <input
                value={invoiceCreateForm.description}
                onChange={event => setInvoiceCreateForm(prev => ({ ...prev, description: event.target.value }))}
                className={agentiveInputClass(isDark)}
                placeholder="Serviço, mensalidade ou cobrança avulsa"
                required
              />
            </Field>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Forma de pagamento registrada">
                <select
                  value={invoiceCreateForm.paymentMethod}
                  onChange={event => setInvoiceCreateForm(prev => ({ ...prev, paymentMethod: event.target.value }))}
                  className={agentiveInputClass(isDark)}
                >
                  {billingMethodOptions.map(option => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </Field>
              <Field label="Valor em BRL">
                <input
                  inputMode="numeric"
                  value={invoiceCreateForm.amount}
                  onChange={event => setInvoiceCreateForm(prev => ({ ...prev, amount: formatBRLTyping(event.target.value) }))}
                  onBlur={() => {
                    const value = parseBRL(invoiceCreateForm.amount);
                    setInvoiceCreateForm(prev => ({ ...prev, amount: value > 0 ? money(value) : '' }));
                  }}
                  className={agentiveInputClass(isDark)}
                  placeholder="R$ 0,00"
                  required
                />
              </Field>
              <Field label={invoiceCreateForm.mode === 'subscription' ? 'Primeiro vencimento' : 'Vencimento'}>
                <input
                  type="date"
                  value={invoiceCreateForm.dueDate}
                  onChange={event => setInvoiceCreateForm(prev => ({ ...prev, dueDate: event.target.value }))}
                  className={agentiveInputClass(isDark)}
                  required
                />
              </Field>
              {invoiceCreateForm.mode === 'subscription' && (
                <Field label="Intervalo">
                  <select
                    value={invoiceCreateForm.cycle}
                    onChange={event => setInvoiceCreateForm(prev => ({ ...prev, cycle: event.target.value }))}
                    className={agentiveInputClass(isDark)}
                  >
                    {billingCycleOptions.map(option => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </Field>
              )}
              {invoiceCreateForm.mode === 'subscription' && (
                <Field label="Fim da assinatura">
                  <input
                    type="date"
                    value={invoiceCreateForm.endDate}
                    onChange={event => setInvoiceCreateForm(prev => ({ ...prev, endDate: event.target.value }))}
                    className={agentiveInputClass(isDark)}
                  />
                </Field>
              )}
            </div>

            <AgentiveAlert variant="info" title="Gestão financeira local">
              {invoiceCreateForm.mode === 'subscription'
                ? `O contrato e as próximas faturas serão registrados em ${branding.appName} conforme o intervalo escolhido. Nenhuma cobrança é processada automaticamente.`
                : `${branding.appName} salvará uma única fatura no valor integral. Parcelamento, juros, multa e desconto não são processados automaticamente.`}
            </AgentiveAlert>

            <Field label="Observações">
              <textarea
                value={invoiceCreateForm.notes}
                onChange={event => setInvoiceCreateForm(prev => ({ ...prev, notes: event.target.value }))}
                className={agentiveTextareaClass(isDark, 'min-h-20')}
              />
            </Field>

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setCreatingInvoiceCustomer(null)} className={agentiveSecondaryButtonClass(isDark)}>Cancelar</button>
              <button
                type="submit"
                disabled={actionLoading || !invoiceCreateForm.planId || !invoiceCreateForm.description.trim() || !parseBRL(invoiceCreateForm.amount) || !invoiceCreateForm.dueDate}
                className={agentivePrimaryButtonClass()}
              >
                {actionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Receipt className="h-4 w-4" />}
                {invoiceCreateForm.mode === 'subscription' ? 'Salvar contrato recorrente' : 'Salvar fatura'}
              </button>
            </div>
          </form>
        </ModalShell>
      )}

      {editingInvoice && (
        <ModalShell title={`Editar fatura ${editingInvoice.invoice_number}`} onClose={() => setEditingInvoice(null)}>
          <form onSubmit={submitInvoiceEdit} className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Vencimento">
                <input
                  type="date"
                  value={invoiceEditForm.dueDate}
                  onChange={event => setInvoiceEditForm(prev => ({ ...prev, dueDate: event.target.value }))}
                  className={agentiveInputClass(isDark)}
                />
              </Field>
              <Field label="Método">
                <select
                  value={invoiceEditForm.paymentMethod}
                  onChange={event => setInvoiceEditForm(prev => ({ ...prev, paymentMethod: event.target.value }))}
                  className={agentiveInputClass(isDark)}
                >
                  <option value="">Não definido</option>
                  <option value="boleto">Boleto/Pix</option>
                  <option value="credit_card">Cartão</option>
                  <option value="transfer">Transferência</option>
                  <option value="cash">Dinheiro</option>
                </select>
              </Field>
            </div>
            <Field label="Observações">
              <textarea
                value={invoiceEditForm.notes}
                onChange={event => setInvoiceEditForm(prev => ({ ...prev, notes: event.target.value }))}
                className={agentiveTextareaClass(isDark, 'min-h-24')}
              />
            </Field>
            <div className={cx('rounded-xl border p-3 text-sm', isDark ? 'border-white/10 bg-white/[0.04] text-white/55' : 'border-brand/10 bg-brand-canvas text-brand/55')}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>Total {money(editingInvoice.total)} · em aberto {money(editingInvoice.amount_due)}</span>
                <div className="flex flex-wrap items-center gap-2">
                  <RecordSourceBadge externalId={editingInvoice.external_id} gateway={editingInvoice.gateway} compact />
                </div>
              </div>
            </div>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setEditingInvoice(null)} className={agentiveSecondaryButtonClass(isDark)}>Cancelar</button>
              <button type="submit" disabled={actionLoading} className={agentivePrimaryButtonClass()}>
                {actionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pencil className="h-4 w-4" />}
                Salvar fatura
              </button>
            </div>
          </form>
        </ModalShell>
      )}

      <AgentiveConfirmModal
        appearance="modern"
        isOpen={Boolean(paidTarget)}
        title="Marcar fatura como paga?"
        message={paidTarget ? `Isso registrará um pagamento manual de ${money(paidTarget.amount_due)} para ${paidTarget.invoice_number}.` : undefined}
        confirmText="Marcar como paga"
        variant="info"
        isLoading={actionLoading}
        onClose={() => setPaidTarget(null)}
        onConfirm={confirmMarkPaid}
      />

      <AgentiveConfirmModal
        appearance="modern"
        isOpen={Boolean(deleteInvoiceTarget)}
        title="Excluir fatura?"
        message={deleteInvoiceTarget ? `A fatura ${deleteInvoiceTarget.invoice_number} será removida definitivamente. Faturas com pagamento registrado não podem ser excluídas.` : undefined}
        confirmText="Excluir fatura"
        variant="danger"
        isLoading={actionLoading}
        onClose={() => setDeleteInvoiceTarget(null)}
        onConfirm={confirmDeleteInvoice}
      />

      <AgentiveConfirmModal
        appearance="modern"
        isOpen={Boolean(deleteCustomerTarget)}
        title="Excluir cliente?"
        message={deleteCustomerTarget ? `O cliente ${deleteCustomerTarget.nome} será removido junto com contratos e faturas sem pagamento. Clientes com pagamentos, faturas pagas ou workspace vinculado serão bloqueados.` : undefined}
        confirmText="Excluir cliente"
        variant="danger"
        isLoading={actionLoading}
        onClose={() => setDeleteCustomerTarget(null)}
        onConfirm={confirmDeleteCustomer}
      />

      <AgentiveConfirmModal
        appearance="modern"
        isOpen={Boolean(recurringTarget)}
        title="Gerar próxima fatura?"
        message="A recorrência será avançada para o próximo período. Se a fatura do período atual já existir, ela será reutilizada."
        confirmText="Gerar fatura"
        variant="info"
        isLoading={actionLoading}
        onClose={() => setRecurringTarget(null)}
        onConfirm={confirmGenerateRecurring}
      />

      <AgentiveConfirmModal
        appearance="modern"
        isOpen={Boolean(cancelTarget)}
        title="Registrar churn?"
        message="O contrato será cancelado e o cliente pode virar ex-cliente se não houver outro contrato ativo."
        confirmText="Registrar churn"
        variant="danger"
        isLoading={actionLoading}
        onClose={() => setCancelTarget(null)}
        onConfirm={confirmCancelContract}
      >
        <Field label="Motivo">
          <textarea value={churnReason} onChange={event => setChurnReason(event.target.value)} className={agentiveTextareaClass(isDark, 'min-h-20')} />
        </Field>
      </AgentiveConfirmModal>
    </main>
  );
}

const Metric: React.FC<{ label: string; value: React.ReactNode; tone?: string }> = ({ label, value, tone }) => {
  return (
    <div className={styles.detailMetric}>
      <p className={styles.detailMetricLabel}>{label}</p>
      <p className={cx(styles.detailMetricValue, tone === 'warning' && styles.detailMetricWarning)}>{value}</p>
    </div>
  );
};

const CustomerContextEmptyState: React.FC<{
  action?: React.ReactNode;
  description: string;
  icon: React.ElementType;
  title: string;
  variant?: 'list' | 'detail';
}> = ({ action, description, icon: Icon, title, variant = 'list' }) => (
  <div className={cx(styles.customerContextEmpty, variant === 'detail' && styles.customerContextEmptyDetail)}>
    <span className={styles.customerContextEmptyIcon} aria-hidden="true"><Icon /></span>
    <div className={styles.customerContextEmptyCopy}>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
    {action && <div className={styles.customerContextEmptyAction}>{action}</div>}
  </div>
);

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => {
  return (
    <label className={styles.formField}>
      <span className={styles.formLabel}>{label}</span>
      {children}
    </label>
  );
};

const ModalShell: React.FC<{ title: string; onClose: () => void; children: React.ReactNode; size?: 'md' | 'xl' }> = ({ title, onClose, children, size = 'md' }) => {
  const { isDark } = useTheme();
  return (
    <div className={styles.modalRoot}>
      <div className={styles.modalBackdrop} onClick={onClose} />
      <div className={cx(styles.modalPanel, size === 'xl' && styles.modalWide)} data-theme={isDark ? 'dark' : 'light'}>
        <header className={styles.modalHeader}>
          <div>
            <p className={styles.modalEyebrow}>Gestão de clientes</p>
            <h2 className={styles.modalTitle}>{title}</h2>
          </div>
          <button type="button" onClick={onClose} className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}>Fechar</button>
        </header>
        <div className={styles.modalBody}>{children}</div>
      </div>
    </div>
  );
};

const SaleStepIndicator: React.FC<{ activeStep: SaleStep; mode: SaleFlowMode }> = ({ activeStep, mode }) => {
  const steps: Array<{ key: SaleStep; label: string }> = mode === 'customer' ? [
    { key: 'contact', label: 'Contato' },
    { key: 'customer', label: 'Cliente' },
  ] : [
    { key: 'contact', label: 'Contato' },
    { key: 'customer', label: 'Cliente' },
    { key: 'sale', label: 'Venda e fatura' },
  ];
  const activeIndex = steps.findIndex(step => step.key === activeStep);

  return (
    <div className={cx(styles.saleSteps, mode === 'customer' ? styles.saleStepsTwo : styles.saleStepsThree)}>
      {steps.map((step, index) => {
        const active = step.key === activeStep;
        const completed = index < activeIndex;
        return (
          <div
            key={step.key}
            className={cx(
              styles.saleStep,
              active && styles.saleStepActive,
              completed && styles.saleStepCompleted,
            )}
          >
            <span className={cx(
              styles.saleStepNumber,
              active && styles.saleStepNumberActive,
              completed && styles.saleStepNumberCompleted,
            )}>
              {completed ? <CheckCircle2 /> : index + 1}
            </span>
            <span>{step.label}</span>
          </div>
        );
      })}
    </div>
  );
};

const FlowSectionHeader: React.FC<{
  eyebrow: string;
  title: string;
  description: string;
  icon: React.ElementType;
  badge?: string;
}> = ({ eyebrow, title, description, icon: Icon, badge }) => (
  <header className={styles.flowSectionHeader}>
    <div className={styles.flowSectionHeading}>
      <span className={styles.flowSectionIcon}><Icon /></span>
      <div>
        <span className={styles.modalEyebrow}>{eyebrow}</span>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
    </div>
    {badge && <span className={styles.neutralBadge}>{badge}</span>}
  </header>
);

const CustomerProfileFields: React.FC<{
  form: CustomerProfileForm;
  onChange: (patch: Partial<CustomerProfileForm>) => void;
}> = ({ form, onChange }) => {
  const { isDark } = useTheme();
  const docStatus = documentStatus(form.cpfCnpj);
  const postalDigits = onlyDigits(form.postalCode);
  const [cepStatus, setCepStatus] = useState<'idle' | 'loading' | 'found' | 'not_found' | 'error'>('idle');

  useEffect(() => {
    if (postalDigits.length !== 8) {
      setCepStatus('idle');
      return;
    }

    let cancelled = false;
    const timeout = window.setTimeout(async () => {
      try {
        setCepStatus('loading');
        const data = await customerBillingApi.lookupPostalCode(postalDigits);
        if (cancelled) return;
        onChange({
          postalCode: formatCep(data.postal_code),
          address: data.address || form.address,
          complement: data.complement || form.complement,
          province: data.province || form.province,
          city: data.city || form.city,
          state: data.state || form.state,
        });
        setCepStatus('found');
      } catch (err: any) {
        if (cancelled) return;
        const status = err.response?.status;
        setCepStatus(status === 404 ? 'not_found' : 'error');
      }
    }, 350);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [postalDigits]);

  const feedbackClass = (state: 'valid' | 'invalid' | 'neutral') => cx(
    styles.formFeedback,
    state === 'valid' && styles.formFeedbackValid,
    state === 'invalid' && styles.formFeedbackInvalid,
    state === 'neutral' && styles.formFeedbackNeutral,
  );
  const inputStateClass = (state: 'valid' | 'invalid' | 'neutral') => {
    if (state === 'valid') return styles.inputValid;
    if (state === 'invalid') return styles.inputInvalid;
    return '';
  };
  const cepFeedback = (() => {
    if (!postalDigits) return { state: 'neutral' as const, message: 'Digite o CEP para preencher o endereço automaticamente.' };
    if (postalDigits.length < 8) return { state: 'invalid' as const, message: 'CEP incompleto.' };
    if (cepStatus === 'loading') return { state: 'neutral' as const, message: 'Buscando endereço...' };
    if (cepStatus === 'found') return { state: 'valid' as const, message: 'Endereço preenchido pelo CEP.' };
    if (cepStatus === 'not_found') return { state: 'invalid' as const, message: 'CEP não encontrado.' };
    if (cepStatus === 'error') return { state: 'invalid' as const, message: 'Não foi possível consultar o CEP agora.' };
    return { state: 'neutral' as const, message: 'CEP pronto para consulta.' };
  })();
  return (
    <div className={styles.profileFormSections}>
      <section className={styles.formSection}>
        <div className={styles.formSectionHeader}>
          <div>
            <h4>Identificação</h4>
            <p>Dados usados na análise e no vínculo financeiro.</p>
          </div>
          <UserPlus />
        </div>
        <div className={styles.formSectionBody}>
          <div className={styles.formGridTwo}>
            <Field label="Nome">
              <input value={form.name} onChange={event => onChange({ name: event.target.value })} className={agentiveInputClass(isDark)} required />
            </Field>
            <Field label="CPF/CNPJ">
              <input
                inputMode="numeric"
                value={form.cpfCnpj}
                onChange={event => onChange({ cpfCnpj: formatCpfCnpj(event.target.value) })}
                className={agentiveInputClass(isDark, inputStateClass(docStatus.state === 'valid' ? 'valid' : docStatus.state === 'empty' ? 'neutral' : 'invalid'))}
                placeholder="Somente números"
                required
              />
              <p className={feedbackClass(docStatus.state === 'valid' ? 'valid' : docStatus.state === 'empty' ? 'neutral' : 'invalid')}>{docStatus.message}</p>
            </Field>
          </div>
        </div>
      </section>

      <section className={styles.formSection}>
        <div className={styles.formSectionHeader}>
          <div>
            <h4>Contato</h4>
            <p>Canais usados para comunicação e cobrança.</p>
          </div>
          <Users />
        </div>
        <div className={styles.formSectionBody}>
          <div className={styles.formGridThree}>
            <Field label="Telefone">
              <input value={form.phone} onChange={event => onChange({ phone: event.target.value })} className={agentiveInputClass(isDark)} required />
            </Field>
            <Field label="WhatsApp">
              <input value={form.mobilePhone} onChange={event => onChange({ mobilePhone: event.target.value })} className={agentiveInputClass(isDark)} required />
            </Field>
            <Field label="Email">
              <input type="email" value={form.email} onChange={event => onChange({ email: event.target.value })} className={agentiveInputClass(isDark)} required />
            </Field>
          </div>
        </div>
      </section>

      <section className={styles.formSection}>
        <div className={styles.formSectionHeader}>
          <div>
            <h4>Endereço</h4>
            <p>O preenchimento é automático assim que o CEP é concluído.</p>
          </div>
          <Building2 />
        </div>
        <div className={styles.formSectionBody}>
          <div className={styles.addressPrimaryGrid}>
            <Field label="CEP">
              <input
                inputMode="numeric"
                value={form.postalCode}
                onChange={event => onChange({ postalCode: formatCep(event.target.value) })}
                className={agentiveInputClass(isDark, inputStateClass(cepFeedback.state))}
              />
              <p className={feedbackClass(cepFeedback.state)}>
                {cepStatus === 'loading' && <Loader2 className="animate-spin" />}
                {cepFeedback.message}
              </p>
            </Field>
            <Field label="Endereço">
              <input value={form.address} onChange={event => onChange({ address: event.target.value })} className={agentiveInputClass(isDark)} />
            </Field>
            <Field label="Número">
              <input value={form.addressNumber} onChange={event => onChange({ addressNumber: event.target.value })} className={agentiveInputClass(isDark)} />
            </Field>
          </div>
          <div className={styles.formGridTwo}>
            <Field label="Bairro">
              <input value={form.province} onChange={event => onChange({ province: event.target.value })} className={agentiveInputClass(isDark)} />
            </Field>
            <Field label="Complemento">
              <input value={form.complement} onChange={event => onChange({ complement: event.target.value })} className={agentiveInputClass(isDark)} />
            </Field>
          </div>
          <div className={styles.cityGrid}>
            <Field label="Cidade">
              <input value={form.city} onChange={event => onChange({ city: event.target.value })} className={agentiveInputClass(isDark)} />
            </Field>
            <Field label="UF">
              <input value={form.state} onChange={event => onChange({ state: event.target.value.toUpperCase().slice(0, 2) })} className={agentiveInputClass(isDark)} maxLength={2} />
            </Field>
          </div>
        </div>
      </section>

      <section className={styles.formSection}>
        <div className={styles.formSectionHeader}>
          <div>
            <h4>Observações</h4>
            <p>Contexto interno deste cliente.</p>
          </div>
          <FileText />
        </div>
        <div className={styles.formSectionBody}>
          <Field label="Observações">
            <textarea value={form.notes} onChange={event => onChange({ notes: event.target.value })} className={agentiveTextareaClass(isDark)} />
          </Field>
        </div>
      </section>
    </div>
  );
};

const DetailValue: React.FC<{ label: string; value?: React.ReactNode }> = ({ label, value }) => {
  return (
    <div className={styles.detailValue}>
      <p className={styles.detailValueLabel}>{label}</p>
      <p className={styles.detailValueContent}>{value || '-'}</p>
    </div>
  );
};

const SaleFinancialSummary: React.FC<{
  pricing: SalePricingSummary;
  billingInterval: string;
  dueDate: string;
}> = ({ pricing, billingInterval, dueDate }) => {
  const hasInstallments = pricing.installments > 1;
  const cycleLabel = billingInterval === 'yearly'
    ? 'fatura anual'
    : billingInterval === 'quarterly'
      ? 'fatura trimestral'
      : billingInterval === 'monthly'
        ? 'fatura mensal'
        : 'fatura avulsa';
  return (
    <div className={styles.financialSummary}>
      <div className={styles.financialSummaryHeader}>
        <h4>Resumo da fatura</h4>
        <span className={styles.neutralBadge}>{billingIntervalLabel[billingInterval] || billingInterval}</span>
      </div>
      <div className={cx(styles.financialSummaryGrid, hasInstallments ? styles.financialSummaryGridFive : styles.financialSummaryGridFour)}>
        <Metric label={hasInstallments ? 'Valor total' : 'Valor da fatura'} value={money(pricing.invoiceTotal)} />
        {hasInstallments && <Metric label="Cada fatura" value={money(pricing.installmentAmount)} />}
        <Metric label="MRR estimado" value={money(pricing.mrr)} />
        <Metric label={hasInstallments ? 'Faturas' : 'Parcelas'} value={hasInstallments ? `${pricing.installments} mensais` : '1 fatura'} />
        <Metric label={hasInstallments ? '1º vencimento' : 'Vencimento'} value={shortDate(dueDate)} />
      </div>
      <p className={styles.financialSummaryDescription}>
        {hasInstallments
          ? `O sistema vai gerar ${pricing.installments} faturas mensais de ${money(pricing.installmentAmount)} para este contrato de ${money(pricing.invoiceTotal)}.`
          : pricing.monthlyMode
            ? `Você informou ${money(pricing.inputValue)} como valor mensal. O sistema vai gerar ${cycleLabel} de ${money(pricing.invoiceTotal)}.`
            : `Você informou ${money(pricing.invoiceTotal)} como valor da ${cycleLabel}. ${pricing.isRecurring ? `O MRR será ${money(pricing.mrr)}.` : 'Venda avulsa não entra em MRR.'}`}
      </p>
    </div>
  );
};

const CustomerDetailPanel: React.FC<{
  customer: CustomerBillingDetail;
  onEditCustomer: (customer: CustomerBillingDetail) => void;
  onDeleteCustomer: (customer: CustomerBillingDetail) => void;
  onCancel: (contract: BillingContractSummary) => void;
  onGenerate: (contract: BillingContractSummary) => void;
  onEditInvoice: (invoice: BillingInvoiceSummary) => void;
  onCreateInvoice: (customer: CustomerBillingDetail) => void;
  onDeleteInvoice: (invoice: BillingInvoiceSummary) => void;
  onMarkPaid: (invoice: BillingInvoiceSummary) => void;
  onCreateWorkspace: (customer: CustomerBillingDetail) => void;
  onOpenManagedCompany: (managedCompany: ManagedCompanySummary) => void;
}> = ({ customer, onEditCustomer, onDeleteCustomer, onCancel, onGenerate, onEditInvoice, onCreateInvoice, onDeleteInvoice, onMarkPaid, onCreateWorkspace, onOpenManagedCompany }) => {
  const [activeTab, setActiveTab] = useState<CustomerDetailTab>('overview');
  const managedCompanies = customer.managed_companies || [];
  const locationLine = [customer.city, customer.state].filter(Boolean).join(' / ');
  const streetLine = [customer.address, customer.address_number].filter(Boolean).join(', ');
  const fullAddress = [streetLine, customer.province, locationLine, customer.postal_code].filter(Boolean).join(' - ');
  const customerInitials = customer.nome
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part.charAt(0).toUpperCase())
    .join('') || 'CL';
  const detailTabs: Array<{ key: CustomerDetailTab; label: string; icon: React.ElementType; count?: number }> = [
    { key: 'overview', label: 'Visão geral', icon: Users },
    { key: 'workspaces', label: 'Workspaces', icon: Building2, count: managedCompanies.length },
    { key: 'contracts', label: 'Contratos', icon: FileText, count: customer.contracts.length },
    { key: 'invoices', label: 'Faturas', icon: Receipt, count: customer.invoices.length },
  ];
  const recentInvoices = useMemo(() => (
    [...customer.invoices]
      .sort((first, second) =>
        invoiceDateTimestamp(first.due_date || first.issue_date) - invoiceDateTimestamp(second.due_date || second.issue_date)
        || first.id - second.id
      )
      .slice(0, 5)
  ), [customer.invoices]);

  return (
    <div className={styles.customerDetail}>
      <div className={styles.profileHeader}>
        <div className={styles.profileTop}>
          <div className={styles.profileIdentity}>
            <div className={styles.profileAvatar} aria-hidden="true">{customerInitials}</div>
            <div className={styles.profileIdentityCopy}>
              <p className={styles.profileEyebrow}>Perfil do cliente</p>
              <div className={styles.profileTitleRow}>
                <h2 className={styles.profileTitle}>{customer.nome}</h2>
                <StatusBadge status={customer.status} />
              </div>
              <p className={styles.profileContact}>{customer.email || customer.telefone || 'Contato não informado'}</p>
            </div>
          </div>
          <div className={styles.profileActions}>
            <div className={styles.profileActionButtons}>
              <button type="button" onClick={() => onEditCustomer(customer)} className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}>
                <Pencil />
                Editar
              </button>
              <button type="button" onClick={() => onDeleteCustomer(customer)} className={cx(styles.button, styles.buttonGhostDanger, styles.buttonCompact)}>
                <Trash2 />
                Excluir
              </button>
            </div>
          </div>
        </div>
        <div className={styles.profileMetrics}>
          <Metric label="MRR" value={money(customer.mrr)} />
          <Metric label="Pago" value={money(customer.total_paid)} />
          <Metric label="Aberto" value={money(customer.open_amount)} />
        </div>
      </div>

      <nav className={styles.detailTabs} aria-label="Áreas do cliente">
        {detailTabs.map(tab => {
          const Icon = tab.icon;
          const active = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={cx(styles.detailTab, active && styles.detailTabActive)}
              aria-current={active ? 'page' : undefined}
            >
              <Icon />
              <span>{tab.label}</span>
              {typeof tab.count === 'number' && <small>{tab.count}</small>}
            </button>
          );
        })}
      </nav>

      <div className={styles.detailContent}>
        {activeTab === 'overview' && (
          <section className={styles.detailSection}>
            <div className={styles.sectionHeader}>
              <div className={styles.sectionHeadingIdentity}>
                <span className={styles.sectionIcon}><Users /></span>
                <div>
                  <h3 className={styles.sectionTitle}>Dados cadastrais</h3>
                  <p className={styles.sectionDescription}>Identificação, contato e endereço principal.</p>
                </div>
              </div>
            </div>
            <div className={styles.profileDetails}>
              <DetailValue label="CPF/CNPJ" value={customer.cpf_cnpj} />
              <DetailValue label="Email" value={customer.email} />
              <DetailValue label="Telefone" value={customer.telefone} />
              <DetailValue label="WhatsApp" value={customer.mobile_phone} />
              <DetailValue label="Endereço" value={fullAddress || customer.postal_code} />
              <DetailValue label="Categoria" value={customer.categoria} />
            </div>
            <div className={styles.syncBar}>
              <div className={styles.syncCopy}>
                <div className={styles.syncIdentity}>
                  <span className={styles.syncIcon}><CheckCircle2 /></span>
                  <div>
                    <p className={styles.syncLabel}>Gestão local</p>
                    <p className={styles.syncDescription}>Cliente salvo e gerenciado diretamente em {branding.appName}.</p>
                  </div>
                </div>
                <RecordSourceBadge />
              </div>
            </div>
          </section>
        )}

        {activeTab === 'workspaces' && <section className={styles.detailSection}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionHeadingIdentity}>
              <span className={styles.sectionIcon}><Building2 /></span>
              <div>
                <h3 className={styles.sectionTitle}>Workspaces do cliente</h3>
                <p className={styles.sectionDescription}>Acessos, período de teste e regras do workspace.</p>
              </div>
            </div>
            <button type="button" onClick={() => onCreateWorkspace(customer)} className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}>
              <Building2 />
              Criar
            </button>
          </div>
          <div className={styles.workspaceList}>
            {managedCompanies.map(company => {
              const lifecycleStatus = company.is_trial_expired ? 'expired' : (company.lifecycle_status || 'active');
              const isExpired = lifecycleStatus === 'expired';
              const hasTrial = Number(company.trial_days || 0) > 0;
              const trialProgress = clampPercent(company.trial_progress_percent);
              const remainingDays = company.trial_days_remaining;
              const remainingLabel = isExpired
                ? 'Teste encerrado'
                : remainingDays === null || remainingDays === undefined
                  ? 'Acesso ativo'
                  : remainingDays === 1
                    ? '1 dia restante'
                    : `${remainingDays} dias restantes`;

              return (
                <div key={company.id} className={styles.workspaceCard}>
                  <div className={styles.workspaceTop}>
                    <div className={styles.workspaceIdentity}>
                      {company.logo_url ? (
                        <img src={company.logo_url} alt="" className={styles.workspaceLogo} />
                      ) : (
                        <div className={styles.workspaceLogoFallback}>
                          <Building2 />
                        </div>
                      )}
                      <div className={styles.workspaceCopy}>
                        <p className={styles.workspaceName}>{company.name_company || company.name}</p>
                        <p className={styles.workspaceDocument}>{company.cnpj || `Empresa #${company.managed_company_id}`}</p>
                        <div className={styles.workspaceBadges}>
                          <StatusBadge status={lifecycleStatus} />
                          {hasTrial && <span className={styles.neutralBadge}>Trial {company.trial_days} dias</span>}
                        </div>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => onOpenManagedCompany(company)}
                      disabled={isExpired}
                      className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}
                    >
                      <ExternalLink />
                      {isExpired ? 'Expirado' : 'Entrar'}
                    </button>
                  </div>

                  <div className={styles.workspaceMetrics}>
                    <WorkspaceMetric
                      icon={Clock}
                      label={hasTrial ? 'Período de teste' : 'Acesso'}
                      value={hasTrial ? remainingLabel : 'Sem trial'}
                      helper={hasTrial ? `Vence em ${shortDate(company.trial_ends_at)}` : 'Ativo sem data de teste'}
                    />
                    <WorkspaceMetric
                      icon={AlertCircle}
                      label="Regra de acesso"
                      value={isExpired ? 'Login bloqueado' : 'Login liberado'}
                      helper={isExpired ? 'Cliente verá aviso ao tentar entrar' : 'Acesso válido neste momento'}
                    />
                  </div>

                  {hasTrial && (
                    <div className={styles.trialProgress}>
                      <div className={styles.trialTrack}>
                        <div
                          className={cx(styles.trialValue, isExpired && styles.trialValueExpired)}
                          style={{ width: `${trialProgress}%` }}
                        />
                      </div>
                      <div className={styles.trialLabels}>
                        <span>Início {shortDate(company.trial_started_at)}</span>
                        <span>{Math.round(trialProgress)}%</span>
                      </div>
                    </div>
                  )}

                  {isExpired && (
                    <div className={styles.workspaceWarning}>
                      <AlertCircle />
                      <span>O período de teste acabou. Para reativar, transforme este workspace em ativo antes do cliente tentar acessar.</span>
                    </div>
                  )}
                </div>
              );
            })}
            {managedCompanies.length === 0 && (
              <p className={styles.inlineEmpty}>
                Nenhum workspace vinculado a este cliente.
              </p>
            )}
          </div>
        </section>}

        {activeTab === 'contracts' && <section className={styles.detailSection}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionHeadingIdentity}>
              <span className={styles.sectionIcon}><FileText /></span>
              <div>
                <h3 className={styles.sectionTitle}>Vendas e contratos</h3>
                <p className={styles.sectionDescription}>Histórico comercial e recorrências vinculadas ao cliente.</p>
              </div>
            </div>
          </div>
          {customer.contracts.length > 0 ? (
            <div className={styles.tableShell}>
              <div className={styles.tableScroll}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th className="px-3 py-2.5 font-medium">Contrato</th>
                      <th className="px-3 py-2.5 font-medium">Status</th>
                      <th className="px-3 py-2.5 font-medium">Valor</th>
                      <th className="px-3 py-2.5 font-medium">Ciclo</th>
                      <th className="px-3 py-2.5 font-medium">Próximo evento</th>
                      <th className="px-3 py-2.5 font-medium">Origem</th>
                      <th className="px-3 py-2.5 text-right font-medium">Ações</th>
                    </tr>
                  </thead>
                  <tbody>
                    {customer.contracts.map(contract => {
                      const canAct = contract.status !== 'canceled';
                      const isExternalContract = Boolean(contract.external_id);

                      return (
                        <tr key={contract.id}>
                          <td className="px-3 py-3">
                            <p className="font-semibold">{contractTypeLabel(contract)}</p>
                            <p className={styles.tableMeta}>Contrato #{contract.id}</p>
                          </td>
                          <td className="px-3 py-3"><StatusBadge status={contract.status} /></td>
                          <td className="px-3 py-3">
                            <p className="font-semibold">{money(contract.total_value)}</p>
                            {contract.is_recurring && (
                              <p className={styles.tableMeta}>MRR {money(contract.mrr)}</p>
                            )}
                          </td>
                          <td className="px-3 py-3">{contractCycleLabel(contract)}</td>
                          <td className="px-3 py-3">
                            {contract.status === 'canceled'
                              ? `Cancelado em ${shortDate(contract.canceled_at)}`
                              : contract.next_invoice_date
                                ? shortDate(contract.next_invoice_date)
                                : contract.end_date
                                  ? shortDate(contract.end_date)
                                  : '-'}
                          </td>
                          <td className="px-3 py-3">
                            <RecordSourceBadge externalId={contract.external_id} gateway={contract.gateway} compact />
                          </td>
                          <td className="px-3 py-3">
                            <div className={styles.tableActions}>
                              {contract.is_recurring && canAct && !isExternalContract && (
                                <button type="button" onClick={() => onGenerate(contract)} className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}>
                                  <Repeat />
                                  Gerar fatura
                                </button>
                              )}
                              {canAct && !isExternalContract && (
                                <button type="button" onClick={() => onCancel(contract)} className={cx(styles.button, styles.buttonGhostDanger, styles.buttonCompact)}>
                                  <Ban />
                                  Registrar churn
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <p className={styles.inlineEmpty}>Nenhum contrato registrado.</p>
          )}
        </section>}

        {activeTab === 'invoices' && <section className={styles.detailSection}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionHeadingIdentity}>
              <span className={styles.sectionIcon}><Receipt /></span>
              <div>
                <h3 className={styles.sectionTitle}>Faturas</h3>
                <p className={styles.sectionDescription}>Cobranças, vencimentos e recebimentos recentes.</p>
              </div>
            </div>
            <button type="button" onClick={() => onCreateInvoice(customer)} className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}>
              <Receipt />
              Criar
            </button>
          </div>
          {recentInvoices.length > 0 ? (
            <div className={styles.tableShell}>
              <div className={styles.tableScroll}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th className="px-3 py-2.5 font-medium">Fatura</th>
                      <th className="px-3 py-2.5 font-medium">Status</th>
                      <th className="px-3 py-2.5 font-medium">Vencimento</th>
                      <th className="px-3 py-2.5 font-medium">Total</th>
                      <th className="px-3 py-2.5 font-medium">Aberto</th>
                      <th className="px-3 py-2.5 font-medium">Origem</th>
                      <th className="px-3 py-2.5 text-right font-medium">Ações</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentInvoices.map(invoice => (
                      <tr key={invoice.id}>
                        <td className="px-3 py-3">
                          <p className="font-semibold">Parcela {invoiceInstallmentLabel(invoice, customer.invoices)}</p>
                          <p className={styles.tableMeta}>{invoice.invoice_number}</p>
                        </td>
                        <td className="px-3 py-3"><StatusBadge status={invoice.status} /></td>
                        <td className="px-3 py-3">{shortDate(invoice.due_date)}</td>
                        <td className="px-3 py-3">{money(invoice.total)}</td>
                        <td className="px-3 py-3">{money(invoice.amount_due)}</td>
                        <td className="px-3 py-3"><RecordSourceBadge externalId={invoice.external_id} gateway={invoice.gateway} compact /></td>
                        <td className="px-3 py-3">
                          <div className={styles.tableActions}>
                            {canEditInvoice(invoice) && (
                              <button type="button" onClick={() => onEditInvoice(invoice)} className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)} aria-label="Editar fatura">
                                <Pencil />
                                Editar
                              </button>
                            )}
                            {canEditInvoice(invoice) && (
                              <button type="button" onClick={() => onMarkPaid(invoice)} className={cx(styles.button, styles.buttonSecondary, styles.buttonCompact)}>
                                <CheckCircle2 />
                                Pagar
                              </button>
                            )}
                            {canDeleteInvoice(invoice) && (
                              <button type="button" onClick={() => onDeleteInvoice(invoice)} className={cx(styles.button, styles.buttonGhostDanger, styles.buttonCompact)} aria-label="Excluir fatura">
                                <Trash2 />
                                Excluir
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {customer.invoices.length > recentInvoices.length && (
                <p className={styles.tableFootnote}>
                  Mostrando {recentInvoices.length} de {customer.invoices.length} faturas deste cliente.
                </p>
              )}
            </div>
          ) : (
            <p className={styles.inlineEmpty}>Nenhuma fatura registrada.</p>
          )}
        </section>}
      </div>
    </div>
  );
};
