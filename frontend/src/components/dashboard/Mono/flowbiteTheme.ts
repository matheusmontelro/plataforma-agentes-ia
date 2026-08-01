import { createTheme } from 'flowbite-react';

const emptyColors = {
  blue: '',
  cyan: '',
  dark: '',
  default: '',
  failure: '',
  gray: '',
  green: '',
  indigo: '',
  info: '',
  light: '',
  lime: '',
  pink: '',
  purple: '',
  red: '',
  success: '',
  teal: '',
  warning: '',
  yellow: '',
};

const emptyButtonColors = {
  ...emptyColors,
  alternative: '',
  monoDate: '',
  monoDefault: '',
  monoGhost: '',
  monoIcon: '',
  monoPrimary: '',
};

export const monoFlowbiteTheme = createTheme({
  alert: {
    base: 'mono-alert',
    borderAccent: '',
    closeButton: {
      base: '',
      color: emptyColors,
      icon: '',
    },
    color: {
      ...emptyColors,
      failure: 'mono-alert--danger',
      info: 'mono-alert--info',
      success: 'mono-alert--success',
      warning: 'mono-alert--warning',
    },
    icon: 'mono-alert-icon',
    rounded: '',
    wrapper: 'mono-flowbite-alert-wrapper',
  },
  badge: {
    icon: {
      off: '',
      on: 'mono-badge--with-icon',
      size: {
        sm: '',
        xs: '',
      },
    },
    root: {
      base: 'mono-badge',
      color: {
        ...emptyColors,
        mono: '',
      },
      size: {
        sm: '',
        xs: '',
      },
    },
  },
  button: {
    base: 'mono-flowbite-button',
    color: emptyButtonColors,
    disabled: '',
    fullSized: 'w-full',
    grouped: '',
    outlineColor: emptyButtonColors,
    pill: '',
    size: {
      lg: '',
      md: '',
      mono: '',
      monoIcon: '',
      sm: '',
      xl: '',
      xs: '',
    },
  },
  select: {
    addon: '',
    base: 'mono-flowbite-select',
    field: {
      base: 'mono-flowbite-select-field',
      icon: {
        base: '',
        svg: '',
      },
      select: {
        base: 'mono-select',
        colors: {
          failure: '',
          gray: '',
          info: '',
          mono: '',
          success: '',
          warning: '',
        },
        sizes: {
          lg: '',
          md: '',
          mono: '',
          sm: '',
        },
        withAddon: {
          off: '',
          on: '',
        },
        withIcon: {
          off: '',
          on: '',
        },
        withShadow: {
          off: '',
          on: '',
        },
      },
    },
  },
  spinner: {
    base: 'mono-spinner-svg',
    color: {
      ...emptyColors,
      mono: '',
    },
    light: {
      off: {
        base: '',
        color: {
          ...emptyColors,
          mono: '',
        },
      },
      on: {
        base: '',
        color: {
          ...emptyColors,
          mono: '',
        },
      },
    },
    size: {
      lg: '',
      md: '',
      mono: '',
      sm: '',
      xl: '',
      xs: '',
    },
  },
  tooltip: {
    animation: 'transition-opacity',
    arrow: {
      base: 'mono-tooltip-arrow',
      placement: '-4px',
      style: {
        auto: '',
        dark: '',
        light: '',
      },
    },
    base: 'mono-tooltip',
    content: 'mono-tooltip-content',
    hidden: 'mono-tooltip--hidden',
    style: {
      auto: '',
      dark: '',
      light: '',
    },
    target: 'mono-tooltip-target',
  },
});

export const monoFlowbiteClearTheme = {
  alert: true,
  badge: true,
  button: true,
  select: true,
  spinner: true,
  tooltip: true,
} as const;

export const monoFlowbiteProps = {
  alert: {
    color: 'failure',
  },
  badge: {
    color: 'mono',
    size: 'xs',
  },
  button: {
    color: 'monoDefault',
    size: 'mono',
  },
  select: {
    color: 'mono',
    sizing: 'mono',
  },
  spinner: {
    color: 'mono',
    size: 'lg',
  },
} as const;
