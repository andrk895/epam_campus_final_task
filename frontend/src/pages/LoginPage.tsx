import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { useApiStatus } from "../apiStatus";
import { ErrorBox, NotYet, errorText } from "../components";

type Mode = "login" | "register";

export function LoginPage() {
  const { session, notice, login, register } = useAuth();
  const status = useApiStatus();
  const location = useLocation();
  const [mode, setMode] = useState<Mode>("login");
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const from = (location.state as { from?: string } | null)?.from ?? "/projects";
  if (session) return <Navigate to={from} replace />;

  const missing = mode === "login" ? status.missing("POST", "/login") : status.missing("POST", "/auth");

  // Client-side checks mirror D11 in specification.md; the backend validates again.
  function validate(): string | null {
    const l = loginName.trim();
    if (l.length < 3 || l.length > 50) return "Login must be 3–50 characters.";
    if (mode === "register") {
      if (password.length < 8) return "Password must be at least 8 characters.";
      if (password !== confirm) return "Passwords don't match.";
    } else if (!password) {
      return "Enter your password.";
    }
    return null;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const problem = validate();
    if (problem) return setError(problem);
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(loginName.trim(), password);
      else await register(loginName.trim(), password);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  function switchMode(m: Mode) {
    setMode(m);
    setError(null);
    setConfirm("");
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card card">
        <div className="auth-brand">
          <span className="logo" aria-hidden />
          <div>
            <h1>Project Hub</h1>
            <p className="muted">Organize projects, share documents, work together.</p>
          </div>
        </div>

        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={mode === "login"} className={mode === "login" ? "tab active" : "tab"} onClick={() => switchMode("login")}>
            Log in
          </button>
          <button role="tab" aria-selected={mode === "register"} className={mode === "register" ? "tab active" : "tab"} onClick={() => switchMode("register")}>
            Create account
          </button>
        </div>

        {notice && <div className="notice notice-info">{notice}</div>}
        {missing && <NotYet endpoint={missing} what={mode === "login" ? "Logging in" : "Registration"} />}

        <form onSubmit={onSubmit} className="stack">
          <label className="field">
            <span>Login</span>
            <input autoFocus autoComplete="username" value={loginName} onChange={(e) => setLoginName(e.target.value)} maxLength={50} />
          </label>
          <label className="field">
            <span>Password</span>
            <input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
            {mode === "register" && <small className="muted">At least 8 characters.</small>}
          </label>
          {mode === "register" && (
            <label className="field">
              <span>Confirm password</span>
              <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </label>
          )}
          <ErrorBox error={error} />
          <button className="btn btn-primary btn-block" disabled={busy || !!missing}>
            {busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>
      </div>
    </div>
  );
}
