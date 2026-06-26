"use client";

// Global dismissible error banner shown below the top bar (ADR-0090). A context
// provider lets any page push an operator-facing failure (with an optional error
// class/reference) without prop drilling; page-local views stay usable.
import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

export type BannerError = { message: string; reference?: string };

type ErrorBannerContextValue = {
  error: BannerError | null;
  showError: (message: string, reference?: string) => void;
  clearError: () => void;
};

const ErrorBannerContext = createContext<ErrorBannerContextValue | null>(null);

export function useErrorBanner(): ErrorBannerContextValue {
  const ctx = useContext(ErrorBannerContext);
  if (!ctx) {
    throw new Error("useErrorBanner must be used inside <ErrorBannerProvider>");
  }
  return ctx;
}

export function ErrorBannerProvider({ children }: { children: ReactNode }) {
  const [error, setError] = useState<BannerError | null>(null);
  const showError = useCallback((message: string, reference?: string) => {
    setError({ message, reference });
  }, []);
  const clearError = useCallback(() => setError(null), []);
  return (
    <ErrorBannerContext.Provider value={{ error, showError, clearError }}>
      {children}
    </ErrorBannerContext.Provider>
  );
}

export function GlobalErrorBanner() {
  const { error, clearError } = useErrorBanner();
  if (!error) return null;
  return (
    <div
      role="alert"
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
        padding: "0.5rem 1rem",
        background: "#fdecea",
        borderBottom: "1px solid #f5c6cb",
        color: "#8a1c1c",
        fontSize: "0.875rem",
      }}
    >
      <span style={{ flex: 1 }}>{error.message}</span>
      {error.reference ? (
        <code style={{ opacity: 0.8 }}>{error.reference}</code>
      ) : null}
      <button
        type="button"
        onClick={clearError}
        aria-label="Dismiss error"
        style={{ cursor: "pointer" }}
      >
        Dismiss
      </button>
    </div>
  );
}
