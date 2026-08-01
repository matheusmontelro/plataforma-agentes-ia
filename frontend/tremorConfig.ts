// src/config/tremorConfig.ts
import { customColors } from "@tremor/react";

// Aqui podemos estender ou personalizar as cores do tema do Tremor
export const tremorConfig = {
  colors: {
    ...customColors,
    // Cores personalizadas para o dashboard
    brand: {
      50: "#E8F4FF",
      100: "#C9E2FF",
      200: "#A3CBFF",
      300: "#75ACFF",
      400: "#5289FF",
      500: "#3366FF",
      600: "#2952CC",
      700: "#1F3E99",
      800: "#162A66",
      900: "#0C1933",
    },
  },
};

// Adicione aqui qualquer outra configuração global para o Tremor que queira usar em toda a aplicação