import { Component, StrictMode } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./style.css";

class ConsoleBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <main className="panel future">
        <h1>This view could not be displayed.</h1>
        <p>
          Your accepted models and durable requests remain in the local service.
        </p>
        <button className="primary" onClick={() => window.location.reload()}>
          Reload workspace
        </button>
      </main>
    ) : (
      this.props.children
    );
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConsoleBoundary>
      <App />
    </ConsoleBoundary>
  </StrictMode>,
);
