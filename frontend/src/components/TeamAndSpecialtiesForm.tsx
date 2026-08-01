import React, { useRef, useEffect, useState } from 'react';
import { Users, UserPlus, Trash2, FilePlus, FileText, PlusCircle } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';

interface Treatment {
  treatmentTitle: string;
  description: string;
}

interface TeamAndSpecialtiesFormProps {
  technicalResponsible: string;
  setTechnicalResponsible: (val: string) => void;
  treatments: Treatment[];
  setTreatments: (treatments: Treatment[]) => void;
}

// Interface para os estados temporários dos tratamentos
interface TreatmentInputs {
  [key: string]: {
    treatmentTitle: string;
    description: string;
  }
}

const TeamAndSpecialtiesForm: React.FC<TeamAndSpecialtiesFormProps> = ({
  technicalResponsible,
  setTechnicalResponsible,
  treatments,
  setTreatments
}) => {
  const { isDark } = useTheme();

  // Ref para o input do responsável técnico
  const responsibleRef = useRef<HTMLInputElement>(null);

  // Estado local para armazenar os valores dos campos de tratamentos
  const [treatmentInputs, setTreatmentInputs] = useState<TreatmentInputs>({});

  // Inicializar valor do responsável técnico
  useEffect(() => {
    if (responsibleRef.current) {
      responsibleRef.current.value = technicalResponsible;
    }
  }, [technicalResponsible]);

  // Inicializar o estado treatmentInputs com os valores dos treatments
  useEffect(() => {
    const initialInputs: TreatmentInputs = {};
    treatments.forEach((treatment, index) => {
      initialInputs[`treatment-${index}`] = {
        treatmentTitle: treatment.treatmentTitle,
        description: treatment.description
      };
    });
    setTreatmentInputs(initialInputs);
  }, []);

  const addTreatment = () => {
    // Salvar posição atual do scroll
    const currentScrollY = window.scrollY;

    const newIndex = treatments.length;
    const newTreatment = { treatmentTitle: '', description: '' };

    // Criar uma cópia do estado atual para evitar problemas de concorrência
    const updatedTreatments = [...treatments, newTreatment];

    // Atualizar o estado local para incluir o novo item
    const newInputs = { ...treatmentInputs };
    newInputs[`treatment-${newIndex}`] = {
      treatmentTitle: '',
      description: ''
    };
    setTreatmentInputs(newInputs);

    // Atualizar o estado global
    setTreatments(updatedTreatments);

    // Manter posição de scroll após a atualização
    requestAnimationFrame(() => {
      window.scrollTo(0, currentScrollY);
    });
  };

  const removeTreatment = (index: number) => {
    // Salvar posição atual do scroll
    const currentScrollY = window.scrollY;

    // Remover do estado local
    const newInputs = { ...treatmentInputs };
    delete newInputs[`treatment-${index}`];

    // Reorganizar as chaves após a remoção
    const updatedInputs: TreatmentInputs = {};
    const newTreatments = treatments.filter((_, i) => i !== index);

    newTreatments.forEach((treatment, i) => {
      updatedInputs[`treatment-${i}`] = {
        treatmentTitle: treatment.treatmentTitle,
        description: treatment.description
      };
    });

    setTreatmentInputs(updatedInputs);
    setTreatments(newTreatments);

    // Manter posição de scroll após a atualização
    requestAnimationFrame(() => {
      window.scrollTo(0, currentScrollY);
    });
  };

  const updateTreatmentField = (index: number, field: keyof Treatment, value: string) => {
    const key = `treatment-${index}`;

    // Atualizar apenas se o valor realmente mudou, para evitar re-renderizações desnecessárias
    if (treatments[index][field] !== value) {
      // Atualizar o estado local
      setTreatmentInputs(prev => ({
        ...prev,
        [key]: {
          ...prev[key],
          [field]: value
        }
      }));

      // Atualizar o estado global
      const updatedTreatments = [...treatments];
      updatedTreatments[index] = {
        ...updatedTreatments[index],
        [field]: value
      };

      setTreatments(updatedTreatments);
    }
  };

  // Helper components (seguindo padrão perfeito)
  const Field: React.FC<{ label: string; children: React.ReactNode; hint?: string }> = ({ label, children, hint }) => (
    <label className="block text-sm">
      <span className={`mb-1 block ${
        isDark ? 'text-gray-300' : 'text-gray-700'
      }`}>{label}</span>
      {children}
      {hint && <span className={`mt-1 block text-[11px] ${
        isDark ? 'text-gray-400' : 'text-gray-500'
      }`}>{hint}</span>}
    </label>
  );

  const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>((props, ref) => (
    <input
      ref={ref}
      {...props}
      className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
        isDark
          ? 'border-gray-600 bg-gray-700 text-gray-200 placeholder:text-gray-400 focus:border-brand'
          : 'border-gray-300 bg-white text-gray-800 placeholder:text-gray-400 focus:border-brand'
      } ${props.className ?? ""}`}
    />
  ));

  const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>((props, ref) => (
    <textarea
      ref={ref}
      {...props}
      className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
        isDark
          ? 'border-gray-600 bg-gray-700 text-gray-200 placeholder:text-gray-400 focus:border-brand'
          : 'border-gray-300 bg-white text-gray-800 placeholder:text-gray-400 focus:border-brand'
      } ${props.className ?? ""}`}
    />
  ));

  return (
    <div className="space-y-4">
      {/* Responsável técnico - seguindo padrão */}
      <Field label="Responsável Técnico">
        <Input
          ref={responsibleRef}
          type="text"
          placeholder="Ex: Dr. João Silva (CRO-SP 12345)"
          defaultValue={technicalResponsible}
          onBlur={() => responsibleRef.current && setTechnicalResponsible(responsibleRef.current.value)}
        />
      </Field>

      {/* Tratamentos - seguindo padrão */}
      <div className="space-y-4">
        <div className="flex justify-between items-center">
          <span className={`text-sm font-medium ${
            isDark ? 'text-gray-300' : 'text-gray-700'
          }`}>Tratamentos Oferecidos</span>
          <button
            type="button"
            onClick={addTreatment}
            className="px-3 py-1.5 bg-brand text-white rounded-xl text-xs hover:bg-brand/90 transition-colors"
          >
            + Adicionar
          </button>
        </div>

        {treatments.length === 0 ? (
          <div className={`rounded-2xl border p-6 text-center ${
            isDark
              ? 'border-gray-600 bg-gray-800/50'
              : 'border-gray-200 bg-gray-50'
          }`}>
            <p className={`text-sm ${
              isDark ? 'text-gray-400' : 'text-gray-500'
            }`}>Nenhum tratamento configurado</p>
          </div>
        ) : (
          <div className="space-y-3">
            {treatments.map((treatment, index) => {
              const key = `treatment-${index}`;
              const inputs = treatmentInputs[key] || { treatmentTitle: treatment.treatmentTitle, description: treatment.description };

              return (
                <div key={index} className={`p-4 rounded-xl border ${
                  isDark
                    ? 'border-gray-600 bg-gray-800/50'
                    : 'border-gray-200 bg-gray-50/50'
                }`}>
                  <div className="flex justify-between items-center mb-3">
                    <span className={`text-sm font-medium ${
                      isDark ? 'text-gray-300' : 'text-gray-700'
                    }`}>Tratamento #{index + 1}</span>
                    <button
                      type="button"
                      onClick={() => removeTreatment(index)}
                      className="text-red-500 hover:text-red-600 text-xs px-2 py-1 rounded hover:bg-red-50 transition-colors"
                    >
                      Remover
                    </button>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <Field label="Nome do Tratamento">
                      <Input
                        type="text"
                        placeholder="Ex: Implante Dentário"
                        defaultValue={inputs.treatmentTitle}
                        onBlur={(e) => updateTreatmentField(index, 'treatmentTitle', e.target.value)}
                      />
                    </Field>

                    <Field label="Descrição">
                      <Textarea
                        placeholder="Descreva o tratamento..."
                        defaultValue={inputs.description}
                        onBlur={(e) => updateTreatmentField(index, 'description', e.target.value)}
                        rows={5}
                      />
                    </Field>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default TeamAndSpecialtiesForm;