import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { EndpointInfo } from "./api";

export function NotYet({ endpoint, what }: { endpoint: EndpointInfo; what: string }) {
  return (
    <div className="notice notice-pending">
      <strong>{what} isn't available yet.</strong> The backend doesn't have{" "}
      <code>
        {endpoint.method} {endpoint.path}
      </code>{" "}
      yet. It comes in task <strong>{endpoint.task}</strong>. See <Link to="/status">Backend progress</Link>.
    </div>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="notice notice-error" role="alert">
      {error}
    </div>
  );
}

export function RoleBadge({ role }: { role?: string }) {
  if (!role) return null;
  return <span className={`badge badge-${role}`}>{role}</span>;
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="spinner-row">
      <span className="spinner" aria-hidden /> {label}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {children && <div className="empty-body">{children}</div>}
    </div>
  );
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDate(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function fileKind(contentType: string, filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (contentType.startsWith("image/")) return "IMG";
  if (contentType === "application/pdf" || ext === "pdf") return "PDF";
  if (ext === "doc" || ext === "docx" || contentType.includes("word")) return "DOC";
  return ext.toUpperCase().slice(0, 4) || "FILE";
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
