import React from 'react';
import { GripVertical, Edit2, Eye, Trash2, ToggleLeft, ToggleRight, Type, Hash, Mail, Calendar, MessageSquare, List } from 'lucide-react';
import { LeadCustomField, CustomFieldType } from '../services/api.ts';

interface CustomFieldListProps {
  fields: LeadCustomField[];
  onEdit: (field: LeadCustomField) => void;
  onDelete: (field: LeadCustomField) => void;
  onPreview: (field: LeadCustomField) => void;
  onDragStart: (e: React.DragEvent, fieldId: number) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent, targetFieldId: number) => void;
  isReordering: boolean;
  draggedFieldId: number | null;
  isDark: boolean;
}

const CustomFieldList: React.FC<CustomFieldListProps> = ({
  fields,
  onEdit,
  onDelete,
  onPreview,
  onDragStart,
  onDragOver,
  onDrop,
  isReordering,
  draggedFieldId,
  isDark
}) => {
  // Obter ícone do tipo de campo
  const getFieldIcon = (fieldType: CustomFieldType) => {
    switch (fieldType) {
      case 'text':
        return <Type className="w-4 h-4" />;
      case 'textarea':
        return <MessageSquare className="w-4 h-4" />;
      case 'email':
        return <Mail className="w-4 h-4" />;
      case 'number':
        return <Hash className="w-4 h-4" />;
      case 'date':
        return <Calendar className="w-4 h-4" />;
      case 'select':
        return <List className="w-4 h-4" />;
      default:
        return <Type className="w-4 h-4" />;
    }
  };

  // Obter cor do tipo de campo
  const getFieldColor = (fieldType: CustomFieldType) => {
    switch (fieldType) {
      case 'text':
      case 'textarea':
        return isDark ? 'text-blue-400' : 'text-blue-600';
      case 'email':
        return isDark ? 'text-green-400' : 'text-green-600';
      case 'number':
        return isDark ? 'text-purple-400' : 'text-purple-600';
      case 'date':
        return isDark ? 'text-orange-400' : 'text-orange-600';
      case 'select':
        return isDark ? 'text-pink-400' : 'text-pink-600';
      default:
        return isDark ? 'text-gray-400' : 'text-gray-600';
    }
  };

  // Obter rótulo do tipo de campo
  const getFieldLabel = (fieldType: CustomFieldType) => {
    switch (fieldType) {
      case 'text':
        return 'Texto';
      case 'textarea':
        return 'Texto Longo';
      case 'email':
        return 'E-mail';
      case 'number':
        return 'Número';
      case 'date':
        return 'Data';
      case 'select':
        return 'Seleção';
      default:
        return fieldType;
    }
  };

  // Renderizar valor padrão ou opções
  const renderDefaultValue = (field: LeadCustomField) => {
    if (field.field_type === 'select' && Array.isArray(field.default_value)) {
      return (
        <div className="flex flex-wrap gap-1">
          {field.default_value.slice(0, 3).map((option, index) => (
            <span
              key={index}
              className={`px-2 py-1 text-xs rounded-full ${
                isDark ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-600'
              }`}
            >
              {option}
            </span>
          ))}
          {field.default_value.length > 3 && (
            <span className={`px-2 py-1 text-xs rounded-full ${
              isDark ? 'bg-gray-700 text-gray-400' : 'bg-gray-100 text-gray-500'
            }`}>
              +{field.default_value.length - 3}
            </span>
          )}
        </div>
      );
    }

    if (field.default_value && typeof field.default_value === 'string') {
      return (
        <span className={`text-sm ${
          isDark ? 'text-gray-400' : 'text-gray-600'
        }`}>
          {field.default_value}
        </span>
      );
    }

    return (
      <span className={`text-sm italic ${
        isDark ? 'text-gray-500' : 'text-gray-400'
      }`}>
        Sem valor padrão
      </span>
    );
  };

  // Renderizar regras de validação
  const renderValidationRules = (field: LeadCustomField) => {
    if (!field.validation_rules || Object.keys(field.validation_rules).length === 0) {
      return null;
    }

    const rules = [];
    const { validation_rules } = field;

    if (validation_rules.min_length) {
      rules.push(`min: ${validation_rules.min_length}`);
    }
    if (validation_rules.max_length) {
      rules.push(`max: ${validation_rules.max_length}`);
    }
    if (validation_rules.min_value !== undefined) {
      rules.push(`min: ${validation_rules.min_value}`);
    }
    if (validation_rules.max_value !== undefined) {
      rules.push(`max: ${validation_rules.max_value}`);
    }
    if (validation_rules.pattern) {
      rules.push('regex');
    }

    if (rules.length === 0) {
      return null;
    }

    return (
      <div className="flex flex-wrap gap-1 mt-2">
        {rules.map((rule, index) => (
          <span
            key={index}
            className={`px-2 py-1 text-xs rounded ${
              isDark ? 'bg-gray-700 text-gray-400' : 'bg-gray-100 text-gray-600'
            }`}
          >
            {rule}
          </span>
        ))}
      </div>
    );
  };

  if (fields.length === 0) {
    return (
      <div className={`text-center py-12 rounded-lg border-2 border-dashed ${
        isDark ? 'border-gray-700 text-gray-400' : 'border-gray-300 text-gray-500'
      }`}>
        <Type className="w-12 h-12 mx-auto mb-4 opacity-50" />
        <p className="font-medium">Nenhum campo customizado</p>
        <p className="text-sm mt-2">Crie seu primeiro campo para começar</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {fields.map((field) => (
        <div
          key={field.id}
          draggable={!isReordering}
          onDragStart={(e) => onDragStart(e, field.id)}
          onDragOver={onDragOver}
          onDrop={(e) => onDrop(e, field.id)}
          className={`p-4 rounded-lg border transition-all cursor-default ${
            isReordering && draggedFieldId === field.id
              ? 'opacity-50 scale-95'
              : isReordering
                ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                : isDark
                  ? 'bg-gray-800 border-gray-700 hover:border-gray-600'
                  : 'bg-white border-gray-200 hover:border-gray-300'
          }`}
        >
          <div className="flex items-start gap-3">
            {/* Drag Handle */}
            <div
              className={`mt-1 p-1 rounded cursor-move transition-colors ${
                isDark ? 'hover:bg-gray-700' : 'hover:bg-gray-100'
              }`}
              title="Arraste para reordenar"
            >
              <GripVertical className={`w-4 h-4 ${isDark ? 'text-gray-500' : 'text-gray-400'}`} />
            </div>

            {/* Field Icon */}
            <div className={`p-2 rounded-lg ${
              isDark ? 'bg-gray-700' : 'bg-gray-100'
            }`}>
              <div className={getFieldColor(field.field_type)}>
                {getFieldIcon(field.field_type)}
              </div>
            </div>

            {/* Field Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <h3 className={`font-medium truncate ${
                    isDark ? 'text-white' : 'text-gray-900'
                  }`}>
                    {field.field_name}
                  </h3>
                  <div className="flex items-center gap-2 mt-1">
                    <span className={`text-xs font-medium capitalize ${getFieldColor(field.field_type)}`}>
                      {getFieldLabel(field.field_type)}
                    </span>
                    {field.is_required && (
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        isDark ? 'bg-red-500/20 text-red-400' : 'bg-red-100 text-red-600'
                      }`}>
                        Obrigatório
                      </span>
                    )}
                    {!field.is_active && (
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        isDark ? 'bg-gray-600 text-gray-300' : 'bg-gray-200 text-gray-600'
                      }`}>
                        Inativo
                      </span>
                    )}
                  </div>
                </div>

                {/* Status Toggle */}
                <div className={`px-2 py-1 rounded text-xs font-medium ${
                  field.is_active
                    ? isDark
                      ? 'bg-green-500/20 text-green-400'
                      : 'bg-green-100 text-green-600'
                    : isDark
                      ? 'bg-gray-700 text-gray-400'
                      : 'bg-gray-200 text-gray-500'
                }`}>
                  {field.is_active ? 'Ativo' : 'Inativo'}
                </div>
              </div>

              {/* Field Key */}
              <div className={`text-xs mt-1 font-mono ${
                isDark ? 'text-gray-500' : 'text-gray-400'
              }`}>
                {field.field_key}
              </div>

              {/* Default Value */}
              {field.default_value && (
                <div className="mt-2">
                  <div className={`text-xs font-medium mb-1 ${
                    isDark ? 'text-gray-400' : 'text-gray-600'
                  }`}>
                    Valor Padrão:
                  </div>
                  {renderDefaultValue(field)}
                </div>
              )}

              {/* Validation Rules */}
              {renderValidationRules(field)}

              {/* Action Buttons */}
              <div className="flex items-center gap-1 mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                <button
                  onClick={() => onPreview(field)}
                  className={`p-1.5 rounded transition-colors ${
                    isDark
                      ? 'hover:bg-blue-500/20 text-blue-400'
                      : 'hover:bg-blue-100 text-blue-600'
                  }`}
                  title="Visualizar campo"
                >
                  <Eye className="w-4 h-4" />
                </button>

                <button
                  onClick={() => onEdit(field)}
                  className={`p-1.5 rounded transition-colors ${
                    isDark
                      ? 'hover:bg-yellow-500/20 text-yellow-400'
                      : 'hover:bg-yellow-100 text-yellow-600'
                  }`}
                  title="Editar campo"
                >
                  <Edit2 className="w-4 h-4" />
                </button>

                <button
                  onClick={() => onDelete(field)}
                  className={`p-1.5 rounded transition-colors ${
                    isDark
                      ? 'hover:bg-red-500/20 text-red-400'
                      : 'hover:bg-red-100 text-red-600'
                  }`}
                  title="Excluir campo"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};

export default CustomFieldList;