import React, { useState, useEffect, useCallback } from 'react';
import { CheckCircle, XCircle, AlertTriangle, RefreshCw } from 'lucide-react';
import { LeadCustomField, LeadCustomFieldsValidationRequest, validarLeadCustomFields } from '../services/api.ts';

interface CustomFieldValidatorProps {
  fields: LeadCustomField[];
  values: Record<string, any>;
  onChange?: (values: Record<string, any>) => void;
  onValidationChange?: (isValid: boolean, errors: string[]) => void;
  isDark?: boolean;
  disabled?: boolean;
  autoValidate?: boolean;
  showRealTimeValidation?: boolean;
}

interface FieldValidation {
  fieldKey: string;
  fieldName: string;
  isValid: boolean;
  errors: string[];
  warnings: string[];
}

const CustomFieldValidator = ({
  fields,
  values,
  onChange,
  onValidationChange,
  isDark = false,
  disabled = false,
  autoValidate = true,
  showRealTimeValidation = false
}: CustomFieldValidatorProps) => {
  const [fieldValidations, setFieldValidations] = useState<Record<string, FieldValidation>>({});
  const [isValidating, setIsValidating] = useState(false);
  const [lastValidationResult, setLastValidationResult] = useState<{
    isValid: boolean;
    errors: string[];
    fieldInfo: Record<string, any>;
  } | null>(null);

  // Obter IDs do usuário e empresa
  const storedClientId = Number(localStorage.getItem('client_id'));
  const storedCompanyId = Number(localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
  const clientId = Number.isInteger(storedClientId) && storedClientId > 0 ? storedClientId : null;
  const companyId = Number.isInteger(storedCompanyId) && storedCompanyId > 0 ? storedCompanyId : null;
  const apiKey = '';

  // Validar campo individual
  const validateField = useCallback((field: LeadCustomField, value: any): FieldValidation => {
    const validation: FieldValidation = {
      fieldKey: field.field_key,
      fieldName: field.field_name,
      isValid: true,
      errors: [],
      warnings: []
    };

    // Campo obrigatório
    if (field.is_required && (value === null || value === undefined || value === '')) {
      validation.isValid = false;
      validation.errors.push(`O campo '${field.field_name}' é obrigatório`);
      return validation;
    }

    // Se campo não é obrigatório e está vazio, é válido
    if (!field.is_required && (value === null || value === undefined || value === '')) {
      return validation;
    }

    // Validação por tipo
    const fieldRules = field.validation_rules || {};

    switch (field.field_type) {
      case 'text':
      case 'textarea':
        const stringValue = String(value || '');

        // Tamanho mínimo
        if (fieldRules.min_length && stringValue.length < fieldRules.min_length) {
          validation.isValid = false;
          validation.errors.push(`O campo deve ter no mínimo ${fieldRules.min_length} caracteres`);
        }

        // Tamanho máximo
        if (fieldRules.max_length && stringValue.length > fieldRules.max_length) {
          validation.isValid = false;
          validation.errors.push(`O campo deve ter no máximo ${fieldRules.max_length} caracteres`);
        }

        // Pattern (regex)
        if (fieldRules.pattern && !new RegExp(fieldRules.pattern).test(stringValue)) {
          validation.isValid = false;
          validation.errors.push(`Formato inválido para o campo`);
        }

        // Avisos
        if (fieldRules.min_length && stringValue.length === fieldRules.min_length) {
          validation.warnings.push(`Considere adicionar mais detalhes ao campo`);
        }
        break;

      case 'email':
        const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
        if (!emailRegex.test(value)) {
          validation.isValid = false;
          validation.errors.push('E-mail inválido');
        }
        break;

      case 'number':
        const numValue = parseFloat(value);

        if (isNaN(numValue)) {
          validation.isValid = false;
          validation.errors.push('Valor inválido');
        } else {
          if (fieldRules.min_value !== undefined && numValue < fieldRules.min_value) {
            validation.isValid = false;
            validation.errors.push(`Valor deve ser maior ou igual a ${fieldRules.min_value}`);
          }

          if (fieldRules.max_value !== undefined && numValue > fieldRules.max_value) {
            validation.isValid = false;
            validation.errors.push(`Valor deve ser menor ou igual a ${fieldRules.max_value}`);
          }
        }
        break;

      case 'date':
        try {
          const date = new Date(value);
          if (isNaN(date.getTime())) {
            validation.isValid = false;
            validation.errors.push('Data inválida');
          } else {
            // Verificar se a data não está no passado para campos futuros
            const today = new Date();
            if (date < today && field.field_name.toLowerCase().includes('futuro')) {
              validation.warnings.push('Data parece estar no passado');
            }
          }
        } catch {
          validation.isValid = false;
          validation.errors.push('Data inválida');
        }
        break;

      case 'select':
        const allowedValues = Array.isArray(field.default_value) ? field.default_value : [];
        if (allowedValues.length > 0 && !allowedValues.includes(value)) {
          validation.isValid = false;
          validation.errors.push('Selecione uma opção válida');
        }
        break;
    }

    return validation;
  }, []);

  // Validar todos os campos localmente
  const validateAllFieldsLocal = useCallback(() => {
    const validations: Record<string, FieldValidation> = {};

    fields.forEach(field => {
      validations[field.field_key] = validateField(field, values[field.field_key]);
    });

    setFieldValidations(validations);

    // Calcular validade geral
    const allValid = Object.values(validations).every(v => v.isValid);
    const allErrors = Object.values(validations).flatMap(v => v.errors);

    if (onValidationChange) {
      onValidationChange(allValid, allErrors);
    }

    return { allValid, allErrors, validations };
  }, [fields, values, validateField, onValidationChange]);

  // Validar no backend
  const validateOnServer = useCallback(async () => {
    if (disabled || !autoValidate) {
      return;
    }

    if (!clientId || !companyId) {
      validateAllFieldsLocal();
      return;
    }

    setIsValidating(true);

    try {
      const validationRequest: LeadCustomFieldsValidationRequest = {
        values: values
      };

      const result = await validarLeadCustomFields(clientId, companyId, validationRequest, apiKey);
      setLastValidationResult({
        isValid: result.is_valid,
        errors: result.errors,
        fieldInfo: result.field_info || {}
      });

      if (onValidationChange) {
        onValidationChange(result.is_valid, result.errors);
      }

    } catch (error) {
      console.error('Erro ao validar no servidor:', error);
      // Fallback para validação local
      validateAllFieldsLocal();
    } finally {
      setIsValidating(false);
    }
  }, [values, clientId, companyId, disabled, autoValidate, onValidationChange, validateAllFieldsLocal]);

  // Validar quando valores mudam
  useEffect(() => {
    if (showRealTimeValidation) {
      const timer = setTimeout(() => {
        validateAllFieldsLocal();
      }, 500);

      return () => clearTimeout(timer);
    }
  }, [values, showRealTimeValidation, validateAllFieldsLocal]);

  // Renderizar status de validação
  const renderValidationStatus = () => {
    const hasErrors = Object.values(fieldValidations).some(v => !v.isValid);
    const hasWarnings = Object.values(fieldValidations).some(v => v.warnings.length > 0);

    if (isValidating) {
      return (
        <div className="flex items-center gap-2 text-blue-600 dark:text-blue-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span className="text-sm">Validando...</span>
        </div>
      );
    }

    if (hasErrors) {
      return (
        <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
          <XCircle className="w-4 h-4" />
          <span className="text-sm">Existem erros de validação</span>
        </div>
      );
    }

    if (hasWarnings) {
      return (
        <div className="flex items-center gap-2 text-yellow-600 dark:text-yellow-400">
          <AlertTriangle className="w-4 h-4" />
          <span className="text-sm">Existem avisos</span>
        </div>
      );
    }

    return (
      <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
        <CheckCircle className="w-4 h-4" />
        <span className="text-sm">Todos os campos válidos</span>
      </div>
    );
  };

  // Renderizar resumo de validação
  const renderValidationSummary = () => {
    const errors = Object.values(fieldValidations).flatMap(v => v.errors);
    const warnings = Object.values(fieldValidations).flatMap(v => v.warnings);

    if (errors.length === 0 && warnings.length === 0) {
      return null;
    }

    return (
      <div className={`space-y-2 ${isDark ? 'text-gray-300' : 'text-gray-700'}`}>
        {errors.length > 0 && (
          <div className={`p-3 rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20`}>
            <h4 className="font-medium text-red-800 dark:text-red-200 mb-2">Erros:</h4>
            <ul className="text-sm space-y-1 text-red-700 dark:text-red-300">
              {errors.map((error, index) => (
                <li key={index}>• {error}</li>
              ))}
            </ul>
          </div>
        )}

        {warnings.length > 0 && (
          <div className={`p-3 rounded-lg border border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-900/20`}>
            <h4 className="font-medium text-yellow-800 dark:text-yellow-200 mb-2">Avisos:</h4>
            <ul className="text-sm space-y-1 text-yellow-700 dark:text-yellow-300">
              {warnings.map((warning, index) => (
                <li key={index}>• {warning}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  };

  // Renderizar validação por campo
  const renderFieldValidation = (fieldKey: string) => {
    const validation = fieldValidations[fieldKey];
    if (!validation) return null;

    return (
      <div className={`text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
        {validation.errors.length > 0 && (
          <span className="text-red-500">
            {validation.errors.join(', ')}
          </span>
        )}
        {validation.warnings.length > 0 && (
          <span className="text-yellow-500">
            {validation.warnings.join(', ')}
          </span>
        )}
        {validation.isValid && validation.errors.length === 0 && validation.warnings.length === 0 && (
          <span className="text-green-500">✓ Válido</span>
        )}
      </div>
    );
  };

  return {
    // API para uso externo
    validateAllFieldsLocal,
    validateOnServer,
    fieldValidations,
    isValidating,
    lastValidationResult,

    // Componentes renderizáveis
    ValidationStatus: renderValidationStatus,
    ValidationSummary: renderValidationSummary,
    FieldValidation: renderFieldValidation
  };
};

export default CustomFieldValidator;
