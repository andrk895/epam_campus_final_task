import type { ReactNode } from "react";
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { ApiStatusProvider, useApiStatus } from "./apiStatus";
import { LoginPage } from "./pages/LoginPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ProjectPage } from "./pages/ProjectPage";
import { StatusPage } from "./pages/StatusPage";

export function App() {
  return (
    <BrowserRouter>
      <ApiStatusProvider>
        <AuthProvider>
          <Header />
          <main>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/status" element={<StatusPage />} />
              <Route path="/projects" element={<RequireAuth><ProjectsPage /></RequireAuth>} />
              <Route path="/projects/:projectId" element={<RequireAuth><ProjectPage /></RequireAuth>} />
              <Route path="*" element={<Navigate to="/projects" replace />} />
            </Routes>
          </main>
        </AuthProvider>
      </ApiStatusProvider>
    </BrowserRouter>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const location = useLocation();
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

function Header() {
  const { session, logout } = useAuth();
  const { reachable } = useApiStatus();
  return (
    <header className="topbar">
      <Link to="/projects" className="brand">
        <span className="logo" aria-hidden />
        Project Hub
      </Link>
      <nav>
        {session && <NavLink to="/projects">Projects</NavLink>}
        <NavLink to="/status">
          <span className={`dot ${reachable === false ? "dot-down" : reachable ? "dot-up" : ""}`} aria-hidden />
          Backend progress
        </NavLink>
      </nav>
      <div className="topbar-user">
        {session ? (
          <>
            <span className="avatar" aria-hidden>{session.login.slice(0, 1).toUpperCase()}</span>
            <span className="user-name">{session.login}</span>
            <button className="btn btn-small" onClick={() => logout()}>Log out</button>
          </>
        ) : (
          <Link to="/login" className="btn btn-small">Log in</Link>
        )}
      </div>
    </header>
  );
}
