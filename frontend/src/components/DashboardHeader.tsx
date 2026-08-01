// src/components/common/DashboardHeader.tsx
import React from 'react';
import { Title, Text, Flex, Select, SelectItem } from "@tremor/react";
import MonthlyCalendarFilter, { MonthlyFilterType } from './MonthlyCalendarFilter.tsx';

type DashboardHeaderProps = {
  companies: { id: number; name: string }[];
  selectedCompany?: number;
  onCompanyChange: (value: number | undefined) => void;

  // Props relacionadas ao filtro de período
  currentFilter: MonthlyFilterType;
  startDate?: string;
  endDate?: string;
  onFilterSelect: (filterType: MonthlyFilterType, startDate?: string, endDate?: string) => void;
  isLoading?: boolean;
};

export const DashboardHeader: React.FC<DashboardHeaderProps> = ({
  companies,
  selectedCompany,
  onCompanyChange,
  currentFilter,
  startDate,
  endDate,
  onFilterSelect,
  isLoading
}) => {
  return (
    <div className="mb-8">
      <Flex justifyContent="between" alignItems="center">
        <div>
          <Title>Dashboard de Performance</Title>
          <Text>Análise completa do funil de vendas</Text>
        </div>
        <Flex justifyContent="end" alignItems="center" className="gap-4">
          <div className="w-48">
            <Select
              placeholder="Selecione uma empresa"
              value={selectedCompany?.toString()}
              onValueChange={(value) => onCompanyChange(value ? parseInt(value) : undefined)}
              disabled={isLoading}
            >
              <SelectItem value="">Todas as empresas</SelectItem>
              {companies.map((company) => (
                <SelectItem key={company.id} value={company.id.toString()}>
                  {company.name}
                </SelectItem>
              ))}
            </Select>
          </div>
          <div className="w-64">
            <MonthlyCalendarFilter
              currentFilter={currentFilter}
              startDate={startDate}
              endDate={endDate}
              onFilterSelect={onFilterSelect}
              isLoading={isLoading}
              className="w-full"
            />
          </div>
        </Flex>
      </Flex>
    </div>
  );
};

export default DashboardHeader;