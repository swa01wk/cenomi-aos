import { forwardRef, useId, type ButtonHTMLAttributes, type MouseEvent } from "react";
import { useShell } from "../ShellContext";
import styles from "./Button.module.css";

export type ButtonVariant = "primary" | "secondary" | "dark" | "danger";

export type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "disabled"> & {
  variant?: ButtonVariant;
  disabledReason?: string;
  size?: "workspace" | "console";
  iconOnly?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    disabledReason,
    size,
    iconOnly,
    className,
    onClick,
    children,
    title,
    ...rest
  },
  ref,
) {
  const shell = useShell();
  const resolvedSize = size ?? shell;
  const reasonId = useId();
  const isDisabled = Boolean(disabledReason);

  const handleClick = (e: MouseEvent<HTMLButtonElement>) => {
    if (isDisabled) {
      e.preventDefault();
      return;
    }
    onClick?.(e);
  };

  const variantClass =
    variant === "primary"
      ? styles.primary
      : variant === "dark"
        ? styles.dark
        : variant === "danger"
          ? styles.danger
          : styles.secondary;

  return (
    <button
      ref={ref}
      type="button"
      {...rest}
      className={[
        styles.button,
        resolvedSize === "workspace" ? styles.workspace : styles.console,
        variantClass,
        iconOnly ? styles.iconOnly : "",
        iconOnly && resolvedSize === "console" ? styles.consoleSize : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      aria-disabled={isDisabled ? "true" : undefined}
      aria-describedby={isDisabled ? reasonId : undefined}
      title={isDisabled ? disabledReason : title}
      onClick={handleClick}
    >
      {children}
      {isDisabled && (
        <span id={reasonId} className={styles.srOnly}>
          {disabledReason}
        </span>
      )}
    </button>
  );
});
