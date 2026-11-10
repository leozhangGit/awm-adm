import { useEffect, useState } from "react";
import { authApi, saveSession } from "./api.ts";
import type { Session } from "./types.ts";
import { Badge, Notice } from "./components.tsx";

export function Login({
  ready,
  onLogin,
}: {
  ready: boolean;
  onLogin: () => void;
}) {
  const [mode, setMode] = useState<"login" | "setup" | "recover">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    if (!ready) return;
    let live = true;
    authApi<{ setup_required: boolean }>("/status")
      .then((value) => {
        if (live) {
          setMode(value.setup_required ? "setup" : "login");
          setChecked(true);
        }
      })
      .catch(() => {
        if (live)
          setError(
            "Cannot check administrator setup. Reload when the local service is ready.",
          );
      });
    return () => {
      live = false;
    };
  }, [ready]);
  async function submit() {
    setError("");
    setMessage("");
    if (mode !== "login" && password !== confirm) {
      setError("The passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      if (mode === "recover") {
        await authApi("/recover", { reset_token: token.trim(), password });
        setMode("login");
        setMessage("Password reset. Sign in with your email and new password.");
      } else {
        const value = await authApi<Session>("/" + mode, {
          email,
          password,
          ...(mode === "setup" ? { bootstrap_token: token.trim() } : {}),
        });
        saveSession({ id: value.id, csrf: value.csrf });
        onLogin();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPassword("");
      setConfirm("");
      setToken("");
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <div className="login-intro">
        <span className="brand">
          AWM<span> / </span>ADM
        </span>
        <p className="eyebrow">YOUR LOCAL INTELLIGENCE WORKSPACE</p>
        <h1>
          Knowledge you own.
          <br />
          Reasoning you can inspect.
        </h1>
        <p>
          Build independent domain models and work with their accepted
          knowledge.
        </p>
        <div className="login-stats">
          <span>Local execution</span>
          <span>Explicit theories</span>
          <span>Independent models</span>
        </div>
      </div>
      <section className="panel login-card">
        <Badge tone={ready ? "green" : "amber"}>
          {ready ? "Local service online" : "Waiting for local service"}
        </Badge>
        <h2>
          {mode === "setup"
            ? "Create your administrator"
            : mode === "recover"
              ? "Reset your password"
              : "Welcome back"}
        </h2>
        <p className="muted">
          {mode === "setup"
            ? "One local administrator. Your email is a sign-in identifier; no email will be sent."
            : mode === "recover"
              ? "Use the short-lived reset credential created by your local operator. No email or provider connection is needed."
              : "Sign in to your local workspace."}
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {mode !== "recover" && (
            <>
              <label htmlFor="admin-email">Email</label>
              <input
                id="admin-email"
                type="email"
                autoComplete="username"
                maxLength={254}
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </>
          )}
          {mode !== "login" && (
            <>
              <label htmlFor="admin-token">
                {mode === "setup" ? "Setup credential" : "Reset credential"}
              </label>
              <input
                id="admin-token"
                type="password"
                autoComplete="off"
                maxLength={256}
                required
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </>
          )}
          <label htmlFor="admin-password">
            {mode === "login" ? "Password" : "New password"}
          </label>
          <input
            id="admin-password"
            type="password"
            autoComplete={
              mode === "login" ? "current-password" : "new-password"
            }
            required
            minLength={mode === "login" ? 1 : 15}
            maxLength={1024}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {mode !== "login" && (
            <>
              <p className="muted">
                Use at least 15 characters. A long, unique passphrase works
                well.
              </p>
              <label htmlFor="admin-confirm">Confirm new password</label>
              <input
                id="admin-confirm"
                type="password"
                autoComplete="new-password"
                required
                maxLength={1024}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </>
          )}
          {error && (
            <Notice error>
              {error.includes("Authentication required")
                ? "The credentials are invalid or expired. Check them and try again."
                : error.includes("capacity")
                  ? "Too many attempts. Wait 15 minutes before trying again."
                  : error}
            </Notice>
          )}
          {message && <Notice>{message}</Notice>}
          <button
            className="primary wide"
            disabled={busy || !ready || !checked}
          >
            {busy
              ? "Please wait…"
              : mode === "setup"
                ? "Create administrator"
                : mode === "recover"
                  ? "Reset password"
                  : "Sign in"}
          </button>
        </form>
        {mode !== "setup" && (
          <button
            className="text-button"
            disabled={busy}
            onClick={() => {
              setMode(mode === "recover" ? "login" : "recover");
              setPassword("");
              setConfirm("");
              setToken("");
              setError("");
            }}
          >
            {mode === "recover" ? "Back to sign in" : "Forgot password?"}
          </button>
        )}
        {mode !== "login" && (
          <details>
            <summary>Local operator instructions</summary>
            <p>
              Run this helper from the project directory. It uses the separate
              operator container and reports the private credential file to read
              locally. Add --project when using a named Compose installation.
            </p>
            <pre>{`python3 scripts/admin_credential.py ${mode === "setup" ? "bootstrap" : "recovery"}`}</pre>
            <p>
              Setup credentials expire after 15 minutes; reset credentials after
              10 minutes. Use a fresh output filename each time. Never paste a
              provider key here.
            </p>
          </details>
        )}
      </section>
    </main>
  );
}

export function Account({ onSignedOut }: { onSignedOut: () => void }) {
  const [email, setEmail] = useState("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    void authApi<{ administrator: { email: string } }>("/me")
      .then((v) => setEmail(v.administrator.email))
      .catch((e) => setError(e.message));
  }, []);
  async function submit() {
    if (next !== confirm) {
      setError("The passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await authApi("/password", {
        current_password: current,
        new_password: next,
      });
      onSignedOut();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCurrent("");
      setNext("");
      setConfirm("");
      setBusy(false);
    }
  }
  return (
    <section className="panel login-card">
      <h1>Administrator account</h1>
      <p>{email}</p>
      <h2>Change password</h2>
      <p>
        This signs out every browser session. Scoped API clients keep their
        existing permissions.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label htmlFor="current-password">Current password</label>
        <input
          id="current-password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={1024}
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <label htmlFor="new-password">
          New password (at least 15 characters)
        </label>
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          minLength={15}
          maxLength={1024}
          required
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <label htmlFor="confirm-password">Confirm new password</label>
        <input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          required
          maxLength={1024}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        {error && <Notice error>{error}</Notice>}
        <button className="primary" disabled={busy}>
          {busy ? "Changing…" : "Change password and sign out"}
        </button>
      </form>
    </section>
  );
}
