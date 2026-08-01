type ExecutionDataMap = Record<string, any>;

type InterpolateVariablesOptions = {
    nameMode?: 'first_name_for_messages';
};

export const flattenObject = (obj: any, prefix = '', filterEmpty = false): string[] => {
    if (!obj || typeof obj !== 'object') return [];

    return Object.keys(obj).reduce((acc: string[], k: string) => {
        const pre = prefix.length ? prefix + '.' : '';
        const value = obj[k];

        if (filterEmpty && (value === '' || value === null || value === undefined)) {
            return acc;
        }

        if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
            acc.push(...flattenObject(value, pre + k, filterEmpty));
        } else {
            acc.push(pre + k);
        }
        return acc;
    }, []);
};

const normalizeFieldKey = (input: string): string => {
    const base = String(input || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '');

    return base || 'field';
};

const getFieldDataArray = (triggerData: any): any[] => {
    if (!triggerData || typeof triggerData !== 'object') return [];
    if (Array.isArray(triggerData.field_data)) return triggerData.field_data;
    if (triggerData.body && typeof triggerData.body === 'object' && Array.isArray(triggerData.body.field_data)) {
        return triggerData.body.field_data;
    }
    return [];
};

const getFirstValue = (item: any): any => {
    if (!item || typeof item !== 'object') return '';
    const values = item.values;
    if (Array.isArray(values)) {
        if (values.length === 0) return '';
        if (values.length === 1) return values[0];
        return values.join(', ');
    }
    if (values === null || values === undefined) return '';
    return values;
};

const buildFieldDataMap = (fieldData: any[]): Record<string, any> => {
    const out: Record<string, any> = {};
    const usedKeys = new Set<string>();

    fieldData.forEach((item) => {
        if (!item || typeof item !== 'object') return;
        const rawName = String(item.name || '').trim();
        if (!rawName) return;

        const normalizedBase = normalizeFieldKey(rawName);
        let key = normalizedBase;
        let counter = 2;
        while (usedKeys.has(key)) {
            key = `${normalizedBase}_${counter}`;
            counter += 1;
        }
        usedKeys.add(key);
        out[key] = getFirstValue(item);
    });

    return out;
};

const CORE_NAME_ALIASES = new Set([
    'name',
    'nome',
    'full_name',
    'nome_completo',
    'first_name',
    'last_name',
]);

const CORE_PHONE_ALIASES = new Set([
    'phone',
    'phone_number',
    'telefone',
    'telefone_principal',
    'celular',
    'whatsapp',
    'whatsapp_number',
    'numero_whatsapp',
    'numero_do_whatsapp',
    'n_do_whatsapp',
]);

const CORE_EMAIL_ALIASES = new Set([
    'email',
    'e_mail',
]);

const getCoreCanonicalKey = (normalizedKey: string): 'name' | 'phone' | 'email' | null => {
    if (CORE_NAME_ALIASES.has(normalizedKey)) return 'name';
    if (CORE_PHONE_ALIASES.has(normalizedKey)) return 'phone';
    if (CORE_EMAIL_ALIASES.has(normalizedKey)) return 'email';
    return null;
};

const isPresentValue = (value: any): boolean => {
    return value !== undefined && value !== null && String(value).trim() !== '';
};

const MESSAGE_FIRST_NAME_ALIASES = new Set(['name', 'nome', 'first_name', 'primeiro_nome']);
const MESSAGE_FULL_NAME_ALIASES = new Set(['full_name', 'nome_completo']);
const CONTACT_NAME_CONTAINER_KEYS = ['lead', 'contact', 'client', 'customer', 'body', 'fields', 'field_data_values'];

const MESSAGE_FIRST_NAME_RELATIVE_PATHS = new Set([
    'name',
    'nome',
    'first_name',
    'primeiro_nome',
    'lead.name',
    'lead.nome',
    'lead.first_name',
    'lead.primeiro_nome',
    'contact.name',
    'contact.nome',
    'contact.first_name',
    'contact.primeiro_nome',
    'client.name',
    'client.nome',
    'client.first_name',
    'client.primeiro_nome',
    'customer.name',
    'customer.nome',
    'customer.first_name',
    'customer.primeiro_nome',
    'body.name',
    'body.nome',
    'body.first_name',
    'body.primeiro_nome',
    'body.lead.name',
    'body.lead.nome',
    'body.lead.first_name',
    'body.lead.primeiro_nome',
    'body.contact.name',
    'body.contact.nome',
    'body.contact.first_name',
    'body.contact.primeiro_nome',
    'body.client.name',
    'body.client.nome',
    'body.client.first_name',
    'body.client.primeiro_nome',
    'body.customer.name',
    'body.customer.nome',
    'body.customer.first_name',
    'body.customer.primeiro_nome',
    'body.body.name',
    'body.body.nome',
    'body.body.first_name',
    'body.body.primeiro_nome',
    'fields.name',
    'fields.nome',
    'fields.first_name',
    'fields.primeiro_nome',
    'field_data_values.name',
    'field_data_values.nome',
    'field_data_values.first_name',
    'field_data_values.primeiro_nome',
    'body.field_data_values.name',
    'body.field_data_values.nome',
    'body.field_data_values.first_name',
    'body.field_data_values.primeiro_nome',
]);

const MESSAGE_FULL_NAME_RELATIVE_PATHS = new Set([
    'full_name',
    'nome_completo',
    'lead.full_name',
    'lead.nome_completo',
    'contact.full_name',
    'contact.nome_completo',
    'client.full_name',
    'client.nome_completo',
    'customer.full_name',
    'customer.nome_completo',
    'body.full_name',
    'body.nome_completo',
    'body.lead.full_name',
    'body.lead.nome_completo',
    'body.contact.full_name',
    'body.contact.nome_completo',
    'body.client.full_name',
    'body.client.nome_completo',
    'body.customer.full_name',
    'body.customer.nome_completo',
    'body.body.full_name',
    'body.body.nome_completo',
    'fields.full_name',
    'fields.nome_completo',
    'field_data_values.full_name',
    'field_data_values.nome_completo',
    'body.field_data_values.full_name',
    'body.field_data_values.nome_completo',
]);

const MESSAGE_FIRST_NAME_PATHS = new Set([
    'trigger.name',
    'trigger.nome',
    'trigger.first_name',
    'trigger.primeiro_nome',
    'trigger.lead.name',
    'trigger.lead.nome',
    'trigger.lead.first_name',
    'trigger.lead.primeiro_nome',
    'trigger.body.name',
    'trigger.body.nome',
    'trigger.body.first_name',
    'trigger.body.primeiro_nome',
    'trigger.body.lead.name',
    'trigger.body.lead.nome',
    'trigger.body.lead.first_name',
    'trigger.body.lead.primeiro_nome',
    'trigger.body.body.name',
    'trigger.body.body.nome',
    'trigger.body.body.first_name',
    'trigger.body.body.primeiro_nome',
    'trigger.fields.name',
    'trigger.fields.nome',
    'trigger.fields.first_name',
    'trigger.fields.primeiro_nome',
    'lead.name',
    'lead.nome',
    'lead.first_name',
    'lead.primeiro_nome',
    'body.name',
    'body.nome',
    'body.first_name',
    'body.primeiro_nome',
]);

const MESSAGE_FULL_NAME_PATHS = new Set([
    'trigger.full_name',
    'trigger.nome_completo',
    'trigger.lead.full_name',
    'trigger.lead.nome_completo',
    'trigger.body.full_name',
    'trigger.body.nome_completo',
    'trigger.body.lead.full_name',
    'trigger.body.lead.nome_completo',
    'trigger.body.body.full_name',
    'trigger.body.body.nome_completo',
    'trigger.fields.full_name',
    'trigger.fields.nome_completo',
    'lead.full_name',
    'lead.nome_completo',
    'body.full_name',
    'body.nome_completo',
]);

const cleanContactName = (value: any): string => {
    const text = String(value ?? '').trim();
    if (!text) return '';

    const hasLetter = Array.from(text).some((character) => character.toLowerCase() !== character.toUpperCase());
    const digits = text.replace(/\D/g, '');
    if (!hasLetter && digits.length >= 8) return '';

    return text;
};

const firstNameFromValue = (value: any): string => {
    const contactName = cleanContactName(value);
    if (!contactName) return '';
    return contactName.split(/\s+/)[0] || '';
};

const dictOrNull = (value: any): Record<string, any> | null => {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
};

const collectContactNamePayloads = (payload: Record<string, any>, depth = 3): Array<Record<string, any>> => {
    const payloads = [payload];
    if (depth <= 0) return payloads;

    CONTACT_NAME_CONTAINER_KEYS.forEach((key) => {
        const nestedPayload = dictOrNull(payload[key]);
        if (nestedPayload) {
            payloads.push(...collectContactNamePayloads(nestedPayload, depth - 1));
        }
    });

    return payloads;
};

const getContactNamesForMessage = (triggerData: any): { firstName: string; fullName: string } => {
    const trigger = dictOrNull(triggerData) || {};
    const payloads = collectContactNamePayloads(trigger);

    let firstName = '';
    let fullName = '';

    for (const payload of payloads) {
        firstName = firstNameFromValue(payload.first_name || payload.primeiro_nome);
        if (firstName) break;
    }

    for (const payload of payloads) {
        fullName = cleanContactName(
            payload.full_name || payload.nome_completo || payload.name || payload.nome
        );
        if (fullName) break;
    }

    return {
        firstName: firstName || firstNameFromValue(fullName),
        fullName: fullName || firstName,
    };
};

export interface WebhookStandardMapping {
    lead_phone_path?: string;
    lead_name_path?: string;
    lead_email_path?: string;
    lead_id_path?: string;
    event_type_path?: string;
    company_id_path?: string;
}

export const WEBHOOK_STANDARD_MAPPING_FIELDS: Array<{
    key: keyof WebhookStandardMapping;
    label: string;
    variable: string;
}> = [
    { key: 'lead_phone_path', label: 'Telefone', variable: '{{lead.phone}}' },
    { key: 'lead_name_path', label: 'Nome', variable: '{{lead.name}}' },
    { key: 'lead_email_path', label: 'Email', variable: '{{lead.email}}' },
    { key: 'lead_id_path', label: 'ID do lead', variable: '{{lead.id}}' },
    { key: 'event_type_path', label: 'Evento', variable: '{{event.type}}' },
    { key: 'company_id_path', label: 'Empresa', variable: '{{company.id}}' },
];

const WEBHOOK_STANDARD_DEFAULT_PATHS: Record<keyof WebhookStandardMapping, string[]> = {
    lead_phone_path: [
        'lead.phone',
        'lead.whatsapp',
        'client.phone',
        'client.whatsapp',
        'contact.phone',
        'contact.whatsapp',
        'body.lead.phone',
        'body.lead.whatsapp',
        'body.client.phone',
        'body.client.whatsapp',
        'body.contact.phone',
        'body.contact.whatsapp',
        'phone',
        'whatsapp',
        'telefone',
        'celular',
        'body.phone',
        'body.whatsapp',
        'body.telefone',
        'body.celular',
    ],
    lead_name_path: [
        'lead.name',
        'lead.full_name',
        'client.name',
        'client.full_name',
        'contact.name',
        'contact.full_name',
        'body.lead.name',
        'body.lead.full_name',
        'body.client.name',
        'body.client.full_name',
        'body.contact.name',
        'body.contact.full_name',
        'name',
        'nome',
        'full_name',
        'nome_completo',
        'body.name',
        'body.nome',
        'body.full_name',
        'body.nome_completo',
    ],
    lead_email_path: [
        'lead.email',
        'client.email',
        'contact.email',
        'body.lead.email',
        'body.client.email',
        'body.contact.email',
        'email',
        'e_mail',
        'body.email',
        'body.e_mail',
    ],
    lead_id_path: [
        'lead.id',
        'lead.lead_id',
        'lead_id',
        'leadId',
        'body.lead.id',
        'body.lead.lead_id',
        'body.lead_id',
        'body.leadId',
    ],
    event_type_path: [
        'event.type',
        'event_type',
        'eventType',
        'event',
        'type',
        'body.event.type',
        'body.event_type',
        'body.eventType',
        'body.event',
        'body.type',
    ],
    company_id_path: [
        'company.id',
        'company_id',
        'companyId',
        'body.company.id',
        'body.company_id',
        'body.companyId',
    ],
};

const normalizeWebhookMapping = (mapping: any): WebhookStandardMapping => {
    if (!mapping || typeof mapping !== 'object') return {};

    const out: WebhookStandardMapping = {};
    WEBHOOK_STANDARD_MAPPING_FIELDS.forEach(({ key }) => {
        const rawValue = mapping[key];
        if (typeof rawValue === 'string' && rawValue.trim()) {
            out[key] = rawValue.trim();
        }
    });
    return out;
};

const withWebhookBodyAlias = (payload: any): Record<string, any> => {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return {};

    const enriched: Record<string, any> = { ...payload };
    if (enriched.body && typeof enriched.body === 'object' && !Array.isArray(enriched.body)) {
        enriched.body = { ...enriched.body };
        return enriched;
    }

    const bodyAlias: Record<string, any> = {};
    Object.entries(enriched).forEach(([key, value]) => {
        if (key !== 'body') bodyAlias[key] = value;
    });
    enriched.body = bodyAlias;
    return enriched;
};

export const resolvePayloadPath = (payload: any, path: string): any => {
    if (!path) return undefined;
    let current = payload;
    const parts = String(path).split('.');

    for (const part of parts) {
        if (!part) return undefined;
        if (current && typeof current === 'object' && !Array.isArray(current) && part in current) {
            current = current[part];
            continue;
        }
        if (Array.isArray(current) && /^\d+$/.test(part)) {
            current = current[Number(part)];
            continue;
        }
        return undefined;
    }

    return current;
};

const resolveScalarPath = (payload: any, path?: string): any => {
    if (!path) return undefined;
    const value = resolvePayloadPath(payload, path);
    if (!isPresentValue(value) || typeof value === 'object') return undefined;
    return value;
};

const resolveFirstStandardPath = (
    payload: any,
    configuredPath: string | undefined,
    defaultPaths: string[]
) => {
    const paths = configuredPath ? [configuredPath, ...defaultPaths] : defaultPaths;
    const seen = new Set<string>();

    for (const path of paths) {
        if (seen.has(path)) continue;
        seen.add(path);
        const value = resolveScalarPath(payload, path);
        if (value !== undefined) return { path, value };
    }

    return null;
};

export const detectWebhookStandardMapping = (payload: any): WebhookStandardMapping => {
    const normalizedPayload = withWebhookBodyAlias(payload);
    const mapping: WebhookStandardMapping = {};

    WEBHOOK_STANDARD_MAPPING_FIELDS.forEach(({ key }) => {
        const detected = resolveFirstStandardPath(
            normalizedPayload,
            undefined,
            WEBHOOK_STANDARD_DEFAULT_PATHS[key]
        );
        if (detected?.path) {
            mapping[key] = detected.path;
        }
    });

    return mapping;
};

const applyWebhookStandardFields = (
    triggerData: any,
    mappingInput?: WebhookStandardMapping
): Record<string, any> => {
    const enriched = withWebhookBodyAlias(triggerData);
    const mapping = normalizeWebhookMapping(mappingInput);

    const lead = {
        ...(enriched.lead && typeof enriched.lead === 'object' && !Array.isArray(enriched.lead) ? enriched.lead : {}),
    };

    const phone = resolveFirstStandardPath(enriched, mapping.lead_phone_path, WEBHOOK_STANDARD_DEFAULT_PATHS.lead_phone_path);
    if (phone && (mapping.lead_phone_path || !isPresentValue(lead.phone))) lead.phone = phone.value;

    const name = resolveFirstStandardPath(enriched, mapping.lead_name_path, WEBHOOK_STANDARD_DEFAULT_PATHS.lead_name_path);
    if (name && (mapping.lead_name_path || !isPresentValue(lead.name))) lead.name = name.value;

    const email = resolveFirstStandardPath(enriched, mapping.lead_email_path, WEBHOOK_STANDARD_DEFAULT_PATHS.lead_email_path);
    if (email && (mapping.lead_email_path || !isPresentValue(lead.email))) lead.email = email.value;

    const leadId = resolveFirstStandardPath(enriched, mapping.lead_id_path, WEBHOOK_STANDARD_DEFAULT_PATHS.lead_id_path);
    if (leadId && (mapping.lead_id_path || !isPresentValue(lead.id))) lead.id = leadId.value;

    if (Object.keys(lead).length > 0) {
        enriched.lead = lead;
    }

    const company = {
        ...(enriched.company && typeof enriched.company === 'object' && !Array.isArray(enriched.company) ? enriched.company : {}),
    };
    const companyId = resolveFirstStandardPath(enriched, mapping.company_id_path, WEBHOOK_STANDARD_DEFAULT_PATHS.company_id_path);
    if (companyId && (mapping.company_id_path || !isPresentValue(company.id))) company.id = companyId.value;
    if (Object.keys(company).length > 0) {
        enriched.company = company;
    }

    const eventType = resolveFirstStandardPath(enriched, mapping.event_type_path, WEBHOOK_STANDARD_DEFAULT_PATHS.event_type_path);
    const eventData = {
        ...(enriched.event_data && typeof enriched.event_data === 'object' && !Array.isArray(enriched.event_data) ? enriched.event_data : {}),
    };
    if (eventType && (mapping.event_type_path || !isPresentValue(eventData.type))) eventData.type = eventType.value;
    if (Object.keys(eventData).length > 0) {
        enriched.event_data = eventData;
    }

    enriched.webhook_mapping = mapping;
    return enriched;
};

export const buildWebhookExecutionContext = (
    payload: any,
    mapping?: WebhookStandardMapping
): Record<string, any> => applyWebhookStandardFields(payload, mapping);

export const getWebhookPayloadPathOptions = (payload: any): string[] => {
    const normalizedPayload = withWebhookBodyAlias(payload);
    return flattenObject(normalizedPayload, '', true)
        .filter((key) => shouldIncludeFlattenedKey(key, normalizedPayload));
};

const getStandardEventType = (triggerData: any): any => {
    if (!triggerData || typeof triggerData !== 'object') return undefined;
    if (triggerData.event_data && typeof triggerData.event_data === 'object' && isPresentValue(triggerData.event_data.type)) {
        return triggerData.event_data.type;
    }
    if (triggerData.event && typeof triggerData.event === 'object' && isPresentValue(triggerData.event.type)) {
        return triggerData.event.type;
    }
    if (isPresentValue(triggerData.event) && typeof triggerData.event !== 'object') {
        return triggerData.event;
    }
    return undefined;
};

const enrichTriggerDataForVariables = (triggerData: any): any => {
    if (!triggerData || typeof triggerData !== 'object') return triggerData;

    const mapping = normalizeWebhookMapping(triggerData.webhook_mapping || triggerData.webhookMapping);
    const enriched: Record<string, any> = applyWebhookStandardFields(triggerData, mapping);
    const body = enriched.body && typeof enriched.body === 'object'
        ? { ...enriched.body }
        : null;

    const fieldData = getFieldDataArray(enriched);
    const rawFieldDataMap = buildFieldDataMap(fieldData);
    const fieldDataMap: Record<string, any> = {};

    Object.entries(rawFieldDataMap).forEach(([key, value]) => {
        const coreKey = getCoreCanonicalKey(key);

        if (coreKey) {
            const topLevelValue = enriched[coreKey];
            const bodyValue = body ? body[coreKey] : undefined;

            // If canonical value already exists on trigger/body, don't duplicate under trigger.fields.*.
            if (isPresentValue(topLevelValue) || isPresentValue(bodyValue)) {
                return;
            }

            // If canonical value doesn't exist, promote this field_data value to canonical key.
            if (!isPresentValue(topLevelValue) && !isPresentValue(bodyValue)) {
                enriched[coreKey] = value;
                if (body) body[coreKey] = value;
            }
            return;
        }

        fieldDataMap[key] = value;
    });

    // Canonical shortcut for form fields: {{trigger.fields.<normalized_key>}}
    enriched.fields = {
        ...(enriched.fields && typeof enriched.fields === 'object' ? enriched.fields : {}),
        ...fieldDataMap,
    };

    if (body) {
        body.field_data_values = {
            ...(body.field_data_values && typeof body.field_data_values === 'object' ? body.field_data_values : {}),
            ...fieldDataMap,
        };
        enriched.body = body;

        // Convenience aliases for webhook payloads that are wrapped in body.
        if ((enriched.name === undefined || enriched.name === null || enriched.name === '') && body.name !== undefined) {
            enriched.name = body.name;
        }
        if ((enriched.phone === undefined || enriched.phone === null || enriched.phone === '') && body.phone !== undefined) {
            enriched.phone = body.phone;
        }
        if ((enriched.email === undefined || enriched.email === null || enriched.email === '') && body.email !== undefined) {
            enriched.email = body.email;
        }
    }

    return applyWebhookStandardFields(enriched, mapping);
};

const shouldIncludeFlattenedKey = (key: string, triggerData: any): boolean => {
    if (!key) return false;

    // Hide verbose/raw branches from variable picker.
    if (
        key === 'raw'
        || key.startsWith('raw.')
        || key === 'field_data'
        || key.startsWith('field_data.')
        || key.startsWith('body.raw')
        || key.startsWith('body.field_data')
        || key.startsWith('body.field_data_values')
        || key === 'webhook_mapping'
        || key.startsWith('webhook_mapping.')
    ) {
        return false;
    }

    // If we already expose top-level alias (name/phone/email etc), avoid duplicated body.* paths.
    if (key.startsWith('body.')) {
        const bodyPath = key.slice(5);
        const topLevelKey = bodyPath.split('.')[0];
        if (topLevelKey && triggerData && typeof triggerData === 'object' && topLevelKey in triggerData) {
            return false;
        }
    }

    return true;
};

const getTriggerExecutionKey = (executionData: ExecutionDataMap): string | undefined => {
    const keys = Object.keys(executionData);
    if (keys.length === 0) return undefined;

    const byKnownType = keys.find((k) => k.toLowerCase().includes('whatsapptrigger'))
        || keys.find((k) => k.toLowerCase().includes('webhooktrigger'))
        || keys.find((k) => k.toLowerCase().includes('webhooknode'));
    if (byKnownType) return byKnownType;

    const byTriggerKeyword = keys.find((k) => k.toLowerCase().includes('trigger'));
    if (byTriggerKeyword) return byTriggerKeyword;

    const byShape = keys.find((k) => {
        const value = executionData[k];
        return (
            value
            && typeof value === 'object'
            && (
                ('phone' in value && 'body' in value)
                || ('body' in value && 'timestamp' in value)
            )
        );
    });
    if (byShape) return byShape;

    if (keys.length === 1) {
        const onlyKey = keys[0];
        const knownOutputPrefixes = [
            'agentWorkforce_',
            'agent_workforce_',
            'agentResponse_',
            'agent_response_',
            'createLead_',
            'create_lead_',
            'moveCrmStage_',
            'move_crm_stage_',
            'humanHandoff_',
            'human_handoff_',
            'sendMessage_',
            'send_message_',
            'sendTelegramMessage_',
            'send_telegram_message_',
        ];
        if (knownOutputPrefixes.some((prefix) => onlyKey.startsWith(prefix))) return undefined;
        return onlyKey;
    }
    return undefined;
};

const resolveTargetId = (nodeAlias: string, executionData: ExecutionDataMap): string | undefined => {
    if (executionData[nodeAlias]) return nodeAlias;

    const triggerKey = getTriggerExecutionKey(executionData);

    if (nodeAlias === 'trigger') {
        return triggerKey;
    }

    // Backward compatibility for legacy placeholders like {{webhook.*}}.
    if ((nodeAlias === 'webhook' || nodeAlias === 'whatsapp') && triggerKey) {
        return triggerKey;
    }

    if ((nodeAlias === 'lead' || nodeAlias === 'event' || nodeAlias === 'company') && triggerKey) {
        return triggerKey;
    }

    const aliasPrefixes: Record<string, string[]> = {
        agent_workforce: ['agentWorkforce_', 'agent_workforce_'],
        agentWorkforce: ['agentWorkforce_', 'agent_workforce_'],
        agent_response: ['agentResponse_', 'agent_response_'],
        agentResponse: ['agentResponse_', 'agent_response_'],
        create_lead: ['createLead_', 'create_lead_'],
        createLead: ['createLead_', 'create_lead_'],
        move_crm_stage: ['moveCrmStage_', 'move_crm_stage_'],
        moveCrmStage: ['moveCrmStage_', 'move_crm_stage_'],
        human_handoff: ['humanHandoff_', 'human_handoff_'],
        humanHandoff: ['humanHandoff_', 'human_handoff_'],
    };

    const matchingPrefixes = aliasPrefixes[nodeAlias];
    if (matchingPrefixes) {
        const byAlias = Object.keys(executionData).find((key) => (
            matchingPrefixes.some((prefix) => key.startsWith(prefix))
        ));
        if (byAlias) return byAlias;
    }

    const fuzzyKey = Object.keys(executionData).find((k) => k.startsWith(nodeAlias));
    if (fuzzyKey) return fuzzyKey;

    return undefined;
};

const getNodeVariableAlias = (nodeId: string): string => {
    if (nodeId.startsWith('agentWorkforce_') || nodeId.startsWith('agent_workforce_')) return 'agent_workforce';
    if (nodeId.startsWith('agentResponse_') || nodeId.startsWith('agent_response_')) return 'agent_response';
    if (nodeId.startsWith('createLead_') || nodeId.startsWith('create_lead_')) return 'create_lead';
    if (nodeId.startsWith('moveCrmStage_') || nodeId.startsWith('move_crm_stage_')) return 'move_crm_stage';
    if (nodeId.startsWith('humanHandoff_') || nodeId.startsWith('human_handoff_')) return 'human_handoff';
    if (nodeId.startsWith('addTag_') || nodeId.startsWith('add_tag_')) return 'add_tag';
    if (nodeId.startsWith('tagFilter_') || nodeId.startsWith('tag_filter_')) return 'tag_filter';
    if (nodeId.startsWith('sendMessage_') || nodeId.startsWith('send_message_')) return 'send_message';
    if (nodeId.startsWith('sendTelegramMessage_') || nodeId.startsWith('send_telegram_message_')) return 'send_telegram_message';
    return nodeId;
};

const getNodeVariableGroup = (alias: string): string => {
    if (alias === 'agent_workforce') return 'Equipe IA';
    if (alias === 'agent_response') return 'Agente IA';
    if (alias === 'create_lead') return 'Lead';
    if (alias === 'move_crm_stage') return 'CRM';
    if (alias === 'human_handoff') return 'Atendimento';
    if (alias === 'add_tag') return 'Adicionar tag';
    if (alias === 'tag_filter') return 'Filtro por tag';
    if (alias === 'send_message') return 'Mensagem WhatsApp';
    if (alias === 'send_telegram_message') return 'Mensagem Telegram';
    return 'Nós';
};

const getMessageNamesFromExecutionData = (executionData: ExecutionDataMap): { firstName: string; fullName: string } => {
    const triggerKey = getTriggerExecutionKey(executionData);
    if (!triggerKey || !executionData[triggerKey] || typeof executionData[triggerKey] !== 'object') {
        return { firstName: '', fullName: '' };
    }

    return getContactNamesForMessage(enrichTriggerDataForVariables(executionData[triggerKey]));
};

const getTriggerRelativeNamePath = (variablePath: string, executionData: ExecutionDataMap): string | null => {
    const parts = variablePath.split('.');
    if (parts.length < 2) return null;

    const nodeAlias = parts[0];
    const triggerKey = getTriggerExecutionKey(executionData);
    const targetId = resolveTargetId(nodeAlias, executionData);

    if (triggerKey && (nodeAlias === triggerKey || targetId === triggerKey)) {
        return parts.slice(1).join('.');
    }

    return null;
};

const resolveMessageNamePath = (variablePath: string, executionData: ExecutionDataMap): string | null => {
    const normalizedPath = variablePath.trim();
    const names = getMessageNamesFromExecutionData(executionData);

    if (MESSAGE_FIRST_NAME_ALIASES.has(normalizedPath) || MESSAGE_FIRST_NAME_PATHS.has(normalizedPath)) {
        return names.firstName || '';
    }

    if (MESSAGE_FULL_NAME_ALIASES.has(normalizedPath) || MESSAGE_FULL_NAME_PATHS.has(normalizedPath)) {
        return names.fullName || '';
    }

    const relativePath = getTriggerRelativeNamePath(normalizedPath, executionData);
    if (relativePath && MESSAGE_FIRST_NAME_RELATIVE_PATHS.has(relativePath)) {
        return names.firstName || '';
    }

    if (relativePath && MESSAGE_FULL_NAME_RELATIVE_PATHS.has(relativePath)) {
        return names.fullName || '';
    }

    return null;
};

export const getVariablesFromExecutionData = (executionData: ExecutionDataMap) => {
    const variables: { label: string; value: string; group: string }[] = [];
    const seenValues = new Set<string>();
    const triggerKey = getTriggerExecutionKey(executionData);

    const pushVariable = (label: string, value: string, group = 'Trigger') => {
        if (seenValues.has(value)) return;
        seenValues.add(value);
        variables.push({ label, value, group });
    };

    if (triggerKey && executionData[triggerKey] && typeof executionData[triggerKey] === 'object') {
        const triggerData = enrichTriggerDataForVariables(executionData[triggerKey]);
        const keys = flattenObject(triggerData, '', true).filter((key) => shouldIncludeFlattenedKey(key, triggerData));

        if (triggerData.lead && typeof triggerData.lead === 'object') {
            if (isPresentValue(triggerData.lead.phone)) pushVariable('lead.phone', '{{lead.phone}}', 'Lead');
            if (isPresentValue(triggerData.lead.name)) pushVariable('lead.name', '{{lead.name}}', 'Lead');
            if (isPresentValue(triggerData.lead.email)) pushVariable('lead.email', '{{lead.email}}', 'Lead');
            if (isPresentValue(triggerData.lead.id)) pushVariable('lead.id', '{{lead.id}}', 'Lead');
        }

        const messageNames = getContactNamesForMessage(triggerData);
        if (isPresentValue(messageNames.firstName)) {
            pushVariable('primeiro_nome', '{{primeiro_nome}}', 'Lead');
        }
        if (isPresentValue(messageNames.fullName)) {
            pushVariable('nome_completo', '{{nome_completo}}', 'Lead');
        }

        const eventType = getStandardEventType(triggerData);
        if (isPresentValue(eventType)) pushVariable('event.type', '{{event.type}}', 'Evento');

        if (triggerData.company && typeof triggerData.company === 'object' && isPresentValue(triggerData.company.id)) {
            pushVariable('company.id', '{{company.id}}', 'Empresa');
        }

        keys.forEach((key) => {
            pushVariable(key, `{{trigger.${key}}}`, 'Trigger');
        });

        // Add friendlier aliases for facebook lead form fields derived from field_data[].
        const fieldData = getFieldDataArray(triggerData);
        const availableFieldMap = (triggerData.fields && typeof triggerData.fields === 'object')
            ? triggerData.fields as Record<string, any>
            : {};
        if (fieldData.length > 0) {
            fieldData.forEach((item) => {
                const originalName = String(item?.name || '').trim();
                if (!originalName) return;
                const normalizedKey = normalizeFieldKey(originalName);
                if (!(normalizedKey in availableFieldMap)) return;

                pushVariable(
                    `fields.${normalizedKey} (${originalName})`,
                    `{{trigger.fields.${normalizedKey}}}`,
                    'Trigger'
                );
            });
        }
    }

    const nodeAliasCounts = Object.keys(executionData).reduce<Record<string, number>>((acc, nodeId) => {
        if (nodeId === triggerKey) return acc;
        const alias = getNodeVariableAlias(nodeId);
        acc[alias] = (acc[alias] || 0) + 1;
        return acc;
    }, {});

    Object.entries(executionData).forEach(([nodeId, nodeData]) => {
        if (nodeId === triggerKey || !nodeData || typeof nodeData !== 'object') return;

        const alias = getNodeVariableAlias(nodeId);
        const variableRoot = nodeAliasCounts[alias] === 1 ? alias : nodeId;
        const group = getNodeVariableGroup(alias);
        const keys = flattenObject(nodeData, '', true);

        keys.forEach((key) => {
            pushVariable(`${alias}.${key}`, `{{${variableRoot}.${key}}}`, group);
        });
    });

    return variables;
};

export const interpolateVariables = (
    text: string,
    executionData: ExecutionDataMap,
    options: InterpolateVariablesOptions = {}
): string => {
    if (!text || typeof text !== 'string') return text;

    return text.replace(/\{\{([^}]+)\}\}/g, (match, variablePath) => {
        const normalizedPath = String(variablePath || '').trim();

        if (normalizedPath === 'now') {
            const date = new Date();
            const year = date.toLocaleString('en-US', { timeZone: 'America/Sao_Paulo', year: 'numeric' });
            const month = date.toLocaleString('en-US', { timeZone: 'America/Sao_Paulo', month: '2-digit' });
            const day = date.toLocaleString('en-US', { timeZone: 'America/Sao_Paulo', day: '2-digit' });
            const time = date.toLocaleString('en-US', {
                timeZone: 'America/Sao_Paulo',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false
            });

            return `${year}-${month}-${day} ${time}`;
        }

        if (options.nameMode === 'first_name_for_messages') {
            const messageNameValue = resolveMessageNamePath(normalizedPath, executionData);
            if (messageNameValue !== null) return messageNameValue;
        }

        const parts = normalizedPath.split('.');
        const nodeAlias = parts[0];
        const path = parts.slice(1);
        const targetId = resolveTargetId(nodeAlias, executionData);

        if (!targetId || !executionData[targetId]) {
            console.warn(`Variable ID not found: ${nodeAlias}. Available:`, Object.keys(executionData));
            return match;
        }

        let current = executionData[targetId];
        if (nodeAlias === 'trigger' || nodeAlias === 'webhook' || nodeAlias === 'whatsapp') {
            current = enrichTriggerDataForVariables(current);
        } else if (nodeAlias === 'lead') {
            current = enrichTriggerDataForVariables(current).lead;
        } else if (nodeAlias === 'company') {
            current = enrichTriggerDataForVariables(current).company;
        } else if (nodeAlias === 'event') {
            const eventType = getStandardEventType(enrichTriggerDataForVariables(current));
            current = isPresentValue(eventType) ? { type: eventType } : {};
        }

        for (const key of path) {
            if (current && typeof current === 'object' && key in current) {
                current = current[key];
            } else {
                return match;
            }
        }

        return String(current);
    });
};
