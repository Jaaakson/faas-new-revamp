import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge class names with Tailwind conflict resolution.
 *
 * `clsx` handles conditionals; `twMerge` resolves conflicts so a caller's
 * `className` reliably overrides a component's default rather than depending on
 * stylesheet order. Without it, `<Button className="bg-red-500">` silently
 * loses to the variant's own background.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
