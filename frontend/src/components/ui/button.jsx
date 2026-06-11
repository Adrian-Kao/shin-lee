import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva } from 'class-variance-authority';

import { cn } from '../../lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-700 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      // Conservative law-firm palette (★10): navy is the dominant brand /
      // primary action colour, rose is destructive. Kept as explicit Tailwind
      // colour classes so the JIT scanner picks every state up at build time.
      variant: {
        // `primary` and `default` are aliases so existing/new call sites can
        // use either name interchangeably.
        primary: 'bg-navy-900 text-white shadow-sm hover:bg-navy-700 disabled:bg-slate-400',
        default: 'bg-navy-900 text-white shadow-sm hover:bg-navy-700 disabled:bg-slate-400',
        destructive: 'bg-rose-600 text-white shadow-sm hover:bg-rose-700',
        outline:
          'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800/50 dark:hover:text-slate-100',
        secondary:
          'bg-slate-200 text-slate-800 hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-slate-600',
        ghost:
          'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100',
        link: 'text-navy-700 underline-offset-4 hover:underline dark:text-navy-200',
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-9 rounded-md px-3',
        lg: 'h-11 rounded-md px-8',
        // Compact size matching the existing hand-written chips/buttons
        // (px-2.5/py-1, text-xs) so swapping them in is visually neutral.
        xs: 'h-auto rounded-md px-2.5 py-1 text-xs',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
);

const Button = React.forwardRef(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : 'button';
  return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
});
Button.displayName = 'Button';

export { Button, buttonVariants };
