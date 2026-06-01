import * as React from "react";
import { cn } from "@/lib/utils";

type Variant = "default" | "outline" | "destructive" | "ghost" | "link";
type Size = "sm" | "default" | "lg" | "icon";

const variants: Record<Variant, string> = {
  default: "bg-primary text-primary-foreground hover:bg-primary/90",
  outline: "border border-border bg-background hover:bg-accent hover:text-accent-foreground",
  destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
  ghost: "hover:bg-accent hover:text-accent-foreground",
  link: "underline-offset-4 hover:underline text-primary",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-sm",
  default: "h-10 px-4 py-2",
  lg: "h-12 px-6 text-base",
  icon: "h-10 w-10",
};

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:pointer-events-none disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
