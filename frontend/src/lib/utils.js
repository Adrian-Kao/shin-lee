import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * shadcn/ui standard helper: merge conditional class names and dedupe
 * Tailwind utility conflicts (the latter wins).
 */
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
