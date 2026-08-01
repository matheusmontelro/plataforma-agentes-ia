import React, { useState } from 'react';
import { Calendar, Mail, Hash, MessageSquare, List, Eye, EyeOff, AlertCircle } from 'lucide-react';
import { CustomFieldType, LeadCustomField, CustomFieldValidationRules } from '../services/api.ts';

interface CustomFieldRendererProps {
  field: LeadCustomField;
  value?: any;
  onChange?: (value: any) => void;
  onValidationChange?: (isValid: boolean, error?: string) => void;
  disabled?: boolean;
  isPreview?: boolean;
  isDark?: boolean;
  showValidation?: boolean;
}

const CustomFieldRenderer: React.FC<CustomFieldRendererProps> = ({
  field,
  value = '',
  onChange,
  onValidationChange,
  disabled = false,
  isPreview = false,
  isDark = false,
  showValidation = true
}) => {
  const [localValue, setLocalValue] = useState(value);
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);
  const [validationError, setValidationError] = useState<string>('');

  // Atualizar valor quando prop mudar
  React.useEffect(() => {
    setLocalValue(value);
  }, [value]);

  // Validar campo
  const validateField = (newValue: any): boolean => {
    if (!showValidation || !onValidationChange) {
      return true;
    }

    // Campo obrigatório
    if (field.is_required && (newValue === null || newValue === undefined || newValue === '')) {
      const error = `O campo '${field.field_name}' é obrigatório`;
      setValidationError(error);
      onValidationChange(false, error);
      return false;
    }

    // Se campo não é obrigatório e está vazio, é válido
    if (!field.is_required && (newValue === null || newValue === undefined || newValue === '')) {
      setValidationError('');
      onValidationChange(true);
      return true;
    }

    // Validação por tipo
    const fieldRules = field.validation_rules || {};
    let error = '';

    switch (field.field_type) {
      case 'text':
      case 'textarea':
        const stringValue = String(newValue || '');

        // Tamanho mínimo
        if (fieldRules.min_length && stringValue.length < fieldRules.min_length) {
          error = `O campo deve ter no mínimo ${fieldRules.min_length} caracteres`;
        }

        // Tamanho máximo
        if (fieldRules.max_length && stringValue.length > fieldRules.max_length) {
          error = `O campo deve ter no máximo ${fieldRules.max_length} caracteres`;
        }

        // Pattern (regex)
        if (fieldRules.pattern && !new RegExp(fieldRules.pattern).test(stringValue)) {
          error = `Formato inválido para o campo`;
        }
        break;

      case 'email':
        const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
        if (!emailRegex.test(newValue)) {
          error = 'E-mail inválido';
        }
        break;

      case 'number':
        const numValue = parseFloat(newValue);

        if (isNaN(numValue)) {
          error = 'Valor inválido';
        } else {
          if (fieldRules.min_value !== undefined && numValue < fieldRules.min_value) {
            error = `Valor deve ser maior ou igual a ${fieldRules.min_value}`;
          }

          if (fieldRules.max_value !== undefined && numValue > fieldRules.max_value) {
            error = `Valor deve ser menor ou igual a ${fieldRules.max_value}`;
          }
        }
        break;

      case 'date':
        try {
          const date = new Date(newValue);
          if (isNaN(date.getTime())) {
            error = 'Data inválida';
          }
        } catch {
          error = 'Data inválida';
        }
        break;

      case 'select':
        const allowedValues = Array.isArray(field.default_value) ? field.default_value : [];
        if (allowedValues.length > 0 && !allowedValues.includes(newValue)) {
          error = 'Selecione uma opção válida';
        }
        break;

      default:
        return true;
    }

    setValidationError(error);
    onValidationChange(!error, error);
    return !error;
  };

  // Lidar com mudança de valor
  const handleValueChange = (newValue: any) => {
    setLocalValue(newValue);

    if (onChange) {
      onChange(newValue);
    }

    // Validar com debounce
    const timer = setTimeout(() => {
      validateField(newValue);
    }, 300);

    return () => clearTimeout(timer);
  };

  // Renderizar ícone do campo
  const renderFieldIcon = () => {
    const iconClass = `w-5 h-5 ${isDark ? 'text-gray-400' : 'text-gray-500'}`;

    switch (field.field_type) {
      case 'email':
        return <Mail className={iconClass} />;
      case 'number':
        return <Hash className={iconClass} />;
      case 'date':
        return <Calendar className={iconClass} />;
      case 'textarea':
        return <MessageSquare className={iconClass} />;
      case 'select':
        return <List className={iconClass} />;
      default:
        return null;
    }
  };

  // Renderizar campo baseado no tipo
  const renderField = () => {
    const baseClasses = `w-full px-3 py-2 rounded-lg border transition-colors ${
      validationError
        ? 'border-red-500 focus:border-red-500'
        : isDark
          ? 'border-gray-600 focus:border-blue-500 bg-gray-700'
          : 'border-gray-300 focus:border-blue-500 bg-white'
    } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`;

    const inputClasses = `${baseClasses} ${isDark ? 'text-white' : 'text-gray-900'}`;

    switch (field.field_type) {
      case 'text':
        return (
          <input
            type="text"
            value={localValue || ''}
            onChange={(e) => handleValueChange(e.target.value)}
            placeholder={isPreview ? `Exemplo de ${field.field_name.toLowerCase()}` : ''}
            disabled={disabled}
            className={inputClasses}
          />
        );

      case 'textarea':
        return (
          <textarea
            value={localValue || ''}
            onChange={(e) => handleValueChange(e.target.value)}
            placeholder={isPreview ? `Exemplo de ${field.field_name.toLowerCase()}` : ''}
            disabled={disabled}
            rows={3}
            className={`${inputClasses} resize-none`}
          />
        );

      case 'email':
        return (
          <input
            type="email"
            value={localValue || ''}
            onChange={(e) => handleValueChange(e.target.value)}
            placeholder={isPreview ? 'exemplo@email.com' : ''}
            disabled={disabled}
            className={inputClasses}
          />
        );

      case 'number':
        return (
          <input
            type="number"
            value={localValue || ''}
            onChange={(e) => handleValueChange(e.target.value)}
            placeholder={isPreview ? '123' : ''}
            disabled={disabled}
            min={field.validation_rules?.min_value}
            max={field.validation_rules?.max_value}
            step="any"
            className={inputClasses}
          />
        );

      case 'date':
        return (
          <input
            type="date"
            value={localValue || ''}
            onChange={(e) => handleValueChange(e.target.value)}
            disabled={disabled}
            className={inputClasses}
          />
        );

      case 'select':
        const options = Array.isArray(field.default_value) ? field.default_value : [];

        return (
          <select
            value={localValue || ''}
            onChange={(e) => handleValueChange(e.target.value)}
            disabled={disabled}
            className={`${inputClasses} cursor-pointer`}
          >
            <option value="">Selecione uma opção...</option>
            {options.map((option, index) => (
              <option key={index} value={option}>
                {option}
              </option>
            ))}
          </select>
        );

      default:
        return (
          <input
            type="text"
            value={localValue || ''}
            onChange={(e) => handleValueChange(e.target.value)}
            disabled={disabled}
            className={inputClasses}
          />
        );
    }
  };

  // Renderizar informações de validação
  const renderValidationInfo = () => {
    if (!showValidation || !field.validation_rules) {
      return null;
    }

    const rules = field.validation_rules;
    const info = [];

    if (rules.min_length) {
      info.push(`Mínimo: ${rules.min_length} caracteres`);
    }
    if (rules.max_length) {
      info.push(`Máximo: ${rules.max_length} caracteres`);
    }
    if (rules.min_value !== undefined) {
      info.push(`Mínimo: ${rules.min_value}`);
    }
    if (rules.max_value !== undefined) {
      info.push(`Máximo: ${rules.max_value}`);
    }
    if (rules.pattern) {
      info.push('Formato específico required');
    }

    if (info.length === 0) {
      return null;
    }

    return (
      <div className={`text-xs mt-1 space-y-1 ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
        {info.map((text, index) => (
          <p key={index}>• {text}</p>
        ))}
      </div>
    );
  };

  return (
    <div className="space-y-2">
      {/* Label */}
      <label className={`flex items-center gap-2 text-sm font-medium ${isDark ? 'text-gray-300' : 'text-gray-700'}`}>
        {renderFieldIcon()}
        {field.field_name}
        {field.is_required && <span className="text-red-500">*</span>}
      </label>

      {/* Input Field */}
      <div className="relative">
        {renderField()}

        {/* Validation Error Icon */}
        {validationError && (
          <div className="absolute right-3 top-1/2 transform -translate-y-1/2">
            <AlertCircle className="w-5 h-5 text-red-500" />
          </div>
        )}
      </div>

      {/* Validation Error Message */}
      {validationError && (
        <p className="text-sm text-red-500 flex items-center gap-1">
          <AlertCircle className="w-4 h-4" />
          {validationError}
        </p>
      )}

      {/* Validation Info */}
      {renderValidationInfo()}

      {/* Preview Mode Info */}
      {isPreview && (
        <div className={`text-xs p-2 rounded-lg ${isDark ? 'bg-blue-500/20 text-blue-400' : 'bg-blue-100 text-blue-600'}`}>
          💡 Este é um exemplo de como o campo "{field.field_name}" aparecerá para o usuário
        </div>
      )}
    </div>
  );
};

export default CustomFieldRenderer;