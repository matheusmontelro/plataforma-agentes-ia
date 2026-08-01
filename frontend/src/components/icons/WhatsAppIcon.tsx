import React from 'react';
import { FaWhatsapp } from 'react-icons/fa';
import { LucideIcon } from 'lucide-react';

// Wrapper para fazer o ícone do WhatsApp funcionar como um Lucide Icon
const WhatsAppIcon: LucideIcon = React.forwardRef<
  SVGSVGElement,
  React.ComponentPropsWithoutRef<'svg'>
>(({ className, ...props }, ref) => {
  // Extrair tamanho da className se existir (ex: w-5 h-5)
  const sizeMatch = className?.match(/[hw]-(\d+)/);
  const size = sizeMatch ? parseInt(sizeMatch[1]) * 4 : 20; // Converter Tailwind para pixels

  return (
    <FaWhatsapp
      size={size}
      className={className}
      {...props}
    />
  );
});

WhatsAppIcon.displayName = 'WhatsAppIcon';

export default WhatsAppIcon;