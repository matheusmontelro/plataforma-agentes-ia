// components/DateSeparator.tsx - Complemento
import React from 'react';

interface DateSeparatorProps {
  date: string;
}

export const DateSeparator: React.FC<DateSeparatorProps> = ({ date }) => {
  return (
    <div className="flex justify-center my-4">
      <div className="bg-gray-200 rounded-full px-4 py-1">
        <span className="text-xs text-gray-600 font-medium">
          {date}
        </span>
      </div>
    </div>
  );
};