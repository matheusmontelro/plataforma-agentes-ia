import React from 'react';
import { Settings, Sparkles, Target, Users, TrendingUp, Shield } from 'lucide-react';

interface CustomFieldPreviewProps {
  isDark: boolean;
}

const CustomFieldPreview: React.FC<CustomFieldPreviewProps> = ({ isDark }) => {
  const benefits = [
    {
      icon: Settings,
      title: "Configuração Flexível",
      description: "Crie campos personalizados adaptados às necessidades específicas do seu negócio",
      color: isDark ? 'text-blue-400' : 'text-blue-600'
    },
    {
      icon: Target,
      title: "Dados Precisos",
      description: "Colete informações relevantes com validação e regras específicas",
      color: isDark ? 'text-green-400' : 'text-green-600'
    },
    {
      icon: Users,
      title: "Melhor Atendimento",
      description: "Conheça melhor seus clientes com dados completos e organizados",
      color: isDark ? 'text-purple-400' : 'text-purple-600'
    },
    {
      icon: TrendingUp,
      title: "Insights Valiosos",
      description: "Analise tendências e padrões com dados customizados",
      color: isDark ? 'text-orange-400' : 'text-orange-600'
    }
  ];

  const fieldExamples = [
    {
      type: "Dados Pessoais",
      fields: ["CPF", "Data de Nascimento", "Estado Civil", "Profissão"],
      icon: "👤"
    },
    {
      type: "Contato",
      fields: ["Telefone Secundário", "Rede Social", "Indicação", "Preferência de Contato"],
      icon: "📱"
    },
    {
      type: "Negócio",
      fields: ["Origem", "Interesse", "Orçamento", "Prazo", "Concorrência"],
      icon: "💼"
    },
    {
      type: "Médico",
      fields: ["Plano de Saúde", "Médico Responsável", "Histórico", "Alergias"],
      icon: "🏥"
    }
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className={`text-center p-6 rounded-lg ${
        isDark ? 'bg-gradient-to-r from-blue-500/20 to-purple-500/20' : 'bg-gradient-to-r from-blue-50 to-purple-50'
      }`}>
        <div className="flex justify-center mb-4">
          <div className={`p-3 rounded-full ${
            isDark ? 'bg-blue-500/30' : 'bg-blue-100'
          }`}>
            <Sparkles className={`w-8 h-8 ${isDark ? 'text-blue-400' : 'text-blue-600'}`} />
          </div>
        </div>
        <h3 className={`text-xl font-semibold mb-2 ${isDark ? 'text-white' : 'text-gray-900'}`}>
          Potencialize Seu CRM
        </h3>
        <p className={`text-sm ${isDark ? 'text-gray-300' : 'text-gray-600'}`}>
          Campos customizados transformam dados em insights poderosos para o seu negócio
        </p>
      </div>

      {/* Benefits */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {benefits.map((benefit, index) => (
          <div
            key={index}
            className={`p-4 rounded-lg border ${
              isDark ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
            }`}
          >
            <div className="flex items-start gap-3">
              <div className={`p-2 rounded-lg ${
                isDark ? 'bg-gray-700' : 'bg-gray-100'
              }`}>
                <benefit.icon className={`w-5 h-5 ${benefit.color}`} />
              </div>
              <div>
                <h4 className={`font-medium mb-1 ${isDark ? 'text-white' : 'text-gray-900'}`}>
                  {benefit.title}
                </h4>
                <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                  {benefit.description}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Field Examples */}
      <div>
        <h4 className={`font-medium mb-4 ${isDark ? 'text-white' : 'text-gray-900'}`}>
          📋 Exemplos de Campos
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {fieldExamples.map((example, index) => (
            <div
              key={index}
              className={`p-4 rounded-lg border ${
                isDark ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
              }`}
            >
              <div className="flex items-center gap-2 mb-3">
                <span className="text-2xl">{example.icon}</span>
                <h5 className={`font-medium ${isDark ? 'text-white' : 'text-gray-900'}`}>
                  {example.type}
                </h5>
              </div>
              <div className="space-y-2">
                {example.fields.map((field, fieldIndex) => (
                  <div key={fieldIndex} className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${
                      isDark ? 'bg-blue-500' : 'bg-blue-600'
                    }`}></div>
                    <span className={`text-sm ${isDark ? 'text-gray-300' : 'text-gray-700'}`}>
                      {field}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Quick Tips */}
      <div className={`p-4 rounded-lg ${
        isDark ? 'bg-yellow-500/20 border-yellow-500/30' : 'bg-yellow-50 border-yellow-200'
      } border`}>
        <div className="flex items-start gap-3">
          <div className={`p-1 rounded ${
            isDark ? 'bg-yellow-500/30' : 'bg-yellow-100'
          }`}>
            <Shield className={`w-5 h-5 ${isDark ? 'text-yellow-400' : 'text-yellow-600'}`} />
          </div>
          <div>
            <h4 className={`font-medium mb-2 ${isDark ? 'text-white' : 'text-gray-900'}`}>
              💡 Dicas Rápidas
            </h4>
            <ul className={`text-sm space-y-1 ${isDark ? 'text-gray-300' : 'text-gray-700'}`}>
              <li>• Comece com campos essenciais e expanda conforme necessário</li>
              <li>• Use nomes claros e objetivos para facilitar o preenchimento</li>
              <li>• Defina campos como obrigatórios apenas quando realmente necessário</li>
              <li>• Utilize validação para garantir a qualidade dos dados</li>
              <li>• Mantenha um equilíbrio entre informação útil e facilidade de uso</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className={`text-center p-3 rounded-lg ${
          isDark ? 'bg-gray-800' : 'bg-gray-50'
        }`}>
          <div className={`text-2xl font-bold ${isDark ? 'text-blue-400' : 'text-blue-600'}`}>
            ∞
          </div>
          <div className={`text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
            Campos Ilimitados
          </div>
        </div>
        <div className={`text-center p-3 rounded-lg ${
          isDark ? 'bg-gray-800' : 'bg-gray-50'
        }`}>
          <div className={`text-2xl font-bold ${isDark ? 'text-green-400' : 'text-green-600'}`}>
            6
          </div>
          <div className={`text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
            Tipos de Campo
          </div>
        </div>
        <div className={`text-center p-3 rounded-lg ${
          isDark ? 'bg-gray-800' : 'bg-gray-50'
        }`}>
          <div className={`text-2xl font-bold ${isDark ? 'text-purple-400' : 'text-purple-600'}`}>
            ✓
          </div>
          <div className={`text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
            Validação
          </div>
        </div>
        <div className={`text-center p-3 rounded-lg ${
          isDark ? 'bg-gray-800' : 'bg-gray-50'
        }`}>
          <div className={`text-2xl font-bold ${isDark ? 'text-orange-400' : 'text-orange-600'}`}>
            🎯
          </div>
          <div className={`text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
            Personalizado
          </div>
        </div>
      </div>
    </div>
  );
};

export default CustomFieldPreview;