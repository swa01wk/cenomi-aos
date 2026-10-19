import { createContext, useContext, type ReactNode } from "react";

export type ShellKind = "workspace" | "console";

const ShellContext = createContext<ShellKind>("workspace");

export function ShellProvider({ shell, children }: { shell: ShellKind; children: ReactNode }) {
  return <ShellContext.Provider value={shell}>{children}</ShellContext.Provider>;
}

export function useShell(): ShellKind {
  return useContext(ShellContext);
}
