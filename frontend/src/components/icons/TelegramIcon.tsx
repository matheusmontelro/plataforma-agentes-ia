import React from 'react';
import { LucideIcon } from 'lucide-react';

const TelegramIcon: LucideIcon = React.forwardRef<
  SVGSVGElement,
  React.ComponentPropsWithoutRef<'svg'>
>(({ className, ...props }, ref) => (
  <svg
    ref={ref}
    viewBox="0 0 240 240"
    fill="none"
    className={className}
    aria-hidden="true"
    {...props}
  >
    <circle cx="120" cy="120" r="120" fill="#2AABEE" />
    <path
      d="M177.8 72.5 158.5 163c-1.5 6.4-5.3 8-10.8 5l-29.3-21.6-14.1 13.6c-1.6 1.6-2.9 2.9-5.9 2.9l2.1-29.8 54.3-49.1c2.4-2.1-.5-3.3-3.7-1.2l-67.1 42.3-28.9-9c-6.3-2-6.4-6.3 1.3-9.3L169.3 63.3c5.2-1.9 9.8 1.3 8.5 9.2Z"
      fill="#fff"
    />
  </svg>
));

TelegramIcon.displayName = 'TelegramIcon';

export default TelegramIcon;
