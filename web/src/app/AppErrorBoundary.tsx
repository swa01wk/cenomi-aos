import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("App error", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <main style={{ padding: 40, display: "flex", flexDirection: "column", gap: 12 }}>
          <h1>Something went wrong</h1>
          <p className="sub">{this.state.error.message}</p>
          <button type="button" className="btn primary" onClick={() => window.location.reload()}>
            Reload the page
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}
