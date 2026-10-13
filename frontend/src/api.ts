// Thin client for the FastAPI backend. All requests go through the Vite proxy at /api.
//
// The response shapes follow specification.md. Where the spec leaves field names open
// (e.g. how the owner or uploader is represented), the normalize* helpers accept the
// likely variants so the UI keeps working whichever one the backend ends up using.

const BASE = "/api";

export type Id = string;
export type Role = "owner" | "participant";

export interface DocumentMeta {
  id: Id;
  filename: string;
  contentType: string;
  size: number;
  uploadedBy?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface Member {
  login: string;
  role: string;
}

export interface Project {
  id: Id;
  name: string;
  description: string;
  role?: Role;
  ownerLogin?: string;
  participants?: Member[];
  documents: DocumentMeta[];
  createdAt?: string;
  updatedAt?: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in?: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}

let getToken: () => string | null = () => null;
let onUnauthorized: () => void = () => {};

export function configureApi(opts: { getToken: () => string | null; onUnauthorized: () => void }) {
  getToken = opts.getToken;
  onUnauthorized = opts.onUnauthorized;
}

const STATUS_TEXT: Record<number, string> = {
  400: "Bad request",
  401: "Not authenticated",
  403: "You don't have permission to do that",
  404: "Not found",
  409: "Conflict",
  413: "File is too large",
  415: "File type not allowed",
  422: "Invalid input",
  500: "Server error",
  502: "Backend is not reachable",
  503: "Backend is not reachable",
  504: "Backend is not reachable",
};

function errorFrom(status: number, body: unknown): ApiError {
  let message = STATUS_TEXT[status] ?? `Request failed (${status})`;
  let code: string | undefined;
  if (body && typeof body === "object" && "detail" in body) {
    const { detail } = body as { detail: unknown; code?: string };
    code = (body as { code?: string }).code;
    if (typeof detail === "string") {
      message = detail;
    } else if (Array.isArray(detail)) {
      // FastAPI validation errors: [{loc: ["body", "login"], msg: "..."}]
      message = detail
        .map((e: { loc?: unknown[]; msg?: string }) => {
          const field = (e.loc ?? []).filter((p) => p !== "body" && p !== "query").join(".");
          return field ? `${field}: ${e.msg}` : e.msg;
        })
        .join("; ");
    }
  }
  return new ApiError(status, message, code);
}

interface RequestOptions {
  json?: unknown;
  form?: FormData;
  query?: Record<string, string>;
  auth?: boolean;
}

async function send(method: string, path: string, opts: RequestOptions = {}): Promise<Response> {
  const { json, form, query, auth = true } = opts;
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = form;
  }
  const token = auth ? getToken() : null;
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const url = BASE + path + (query ? `?${new URLSearchParams(query)}` : "");
  let res: Response;
  try {
    res = await fetch(url, { method, headers, body });
  } catch {
    throw new ApiError(0, "Can't reach the frontend dev server");
  }
  if (!res.ok) {
    const text = await res.text();
    let parsed: unknown = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      // Non-JSON error body (e.g. the proxy's "connect ECONNREFUSED")
    }
    if (res.status === 401 && auth) onUnauthorized();
    throw errorFrom(res.status, parsed);
  }
  return res;
}

async function request<T>(method: string, path: string, opts?: RequestOptions): Promise<T> {
  const res = await send(method, path, opts);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

// ---------- normalization ----------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Raw = Record<string, any>;

function loginOf(value: unknown): string | undefined {
  if (value == null) return undefined;
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "object" && "login" in value) return String((value as Raw).login);
  return undefined;
}

export function normalizeDocument(raw: Raw): DocumentMeta {
  return {
    id: String(raw.id),
    filename: raw.filename ?? raw.name ?? "(unnamed)",
    contentType: raw.content_type ?? raw.contentType ?? "",
    size: Number(raw.size ?? 0),
    uploadedBy: raw.uploaded_by_login ?? loginOf(raw.uploader) ?? loginOf(raw.uploaded_by),
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

function normalizeMember(raw: Raw | string): Member {
  if (typeof raw === "string") return { login: raw, role: "participant" };
  return { login: raw.login ?? loginOf(raw.user) ?? "?", role: raw.role ?? "participant" };
}

export function normalizeProject(raw: Raw, myLogin?: string): Project {
  const participantsRaw: unknown = raw.participants ?? raw.members;
  const participants = Array.isArray(participantsRaw) ? participantsRaw.map(normalizeMember) : undefined;
  const ownerLogin =
    raw.owner_login ??
    loginOf(raw.owner) ??
    participants?.find((m) => m.role === "owner")?.login;
  let role: Role | undefined = raw.role ?? raw.my_role ?? raw.user_role;
  if (!role && myLogin) {
    const me = participants?.find((m) => m.login.toLowerCase() === myLogin.toLowerCase());
    if (me) role = me.role as Role;
    else if (ownerLogin) role = ownerLogin.toLowerCase() === myLogin.toLowerCase() ? "owner" : "participant";
  }
  return {
    id: String(raw.id),
    name: raw.name ?? "",
    description: raw.description ?? "",
    role,
    ownerLogin,
    participants,
    documents: Array.isArray(raw.documents) ? raw.documents.map(normalizeDocument) : [],
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

// ---------- endpoints ----------

export const api = {
  health: () => request<{ status: string }>("GET", "/health", { auth: false }),
  openapi: () => request<{ paths: Record<string, Record<string, unknown>> }>("GET", "/openapi.json", { auth: false }),

  register: (login: string, password: string) =>
    request<Raw>("POST", "/auth", { json: { login, password }, auth: false }),
  login: (login: string, password: string) =>
    request<TokenResponse>("POST", "/login", { json: { login, password }, auth: false }),

  listProjects: async (myLogin?: string) => {
    const data = await request<Raw[] | Raw>("GET", "/projects");
    // Tolerate either a bare list or a paginated {items: [...]} wrapper.
    const items: Raw[] = Array.isArray(data) ? data : (data.items ?? data.projects ?? []);
    return items.map((p) => normalizeProject(p, myLogin));
  },
  createProject: (name: string, description: string) =>
    request<Raw>("POST", "/projects", { json: { name, description } }),
  getProject: async (id: Id, myLogin?: string) =>
    normalizeProject(await request<Raw>("GET", `/projects/${id}/info`), myLogin),
  updateProject: (id: Id, name: string, description: string) =>
    request<Raw>("PUT", `/projects/${id}/info`, { json: { name, description } }),
  deleteProject: (id: Id) => request<void>("DELETE", `/projects/${id}`),

  invite: (id: Id, login: string) =>
    request<Raw>("POST", `/projects/${id}/invite`, { query: { user: login } }),
  removeParticipant: (id: Id, login: string) =>
    request<void>("DELETE", `/projects/${id}/participants/${encodeURIComponent(login)}`),

  listDocuments: async (projectId: Id) => {
    const data = await request<Raw[] | Raw>("GET", `/projects/${projectId}/documents`);
    const items: Raw[] = Array.isArray(data) ? data : (data.items ?? data.documents ?? []);
    return items.map(normalizeDocument);
  },
  uploadDocuments: (projectId: Id, files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    return request<Raw[]>("POST", `/projects/${projectId}/documents`, { form });
  },
  replaceDocument: (docId: Id, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Raw>("PUT", `/documents/${docId}`, { form });
  },
  deleteDocument: (docId: Id) => request<void>("DELETE", `/documents/${docId}`),

  /** Fetches the file with the auth header and hands it to the browser as a download. */
  downloadDocument: async (doc: DocumentMeta) => {
    const res = await send("GET", `/documents/${doc.id}`);
    const blob = await res.blob();
    const name = filenameFromDisposition(res.headers.get("Content-Disposition")) ?? doc.filename;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  },
};

function filenameFromDisposition(header: string | null): string | undefined {
  if (!header) return undefined;
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(header);
  if (star) return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ""));
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain?.[1];
}

// ---------- endpoint catalogue (for feature detection and the status page) ----------

export interface EndpointInfo {
  method: string;
  path: string;
  task: string;
  label: string;
}

export const ENDPOINTS: EndpointInfo[] = [
  { method: "GET", path: "/health", task: "T0.3", label: "Health check" },
  { method: "POST", path: "/auth", task: "T2.2", label: "Register" },
  { method: "POST", path: "/login", task: "T2.3", label: "Log in" },
  { method: "POST", path: "/projects", task: "T3.2", label: "Create project" },
  { method: "GET", path: "/projects", task: "T3.3", label: "List my projects" },
  { method: "GET", path: "/projects/{project_id}/info", task: "T3.4", label: "Project details" },
  { method: "PUT", path: "/projects/{project_id}/info", task: "T3.5", label: "Edit project" },
  { method: "DELETE", path: "/projects/{project_id}", task: "T3.6", label: "Delete project" },
  { method: "POST", path: "/projects/{project_id}/invite", task: "T4.1", label: "Invite user" },
  { method: "DELETE", path: "/projects/{project_id}/participants/{login}", task: "T4.2", label: "Remove participant" },
  { method: "POST", path: "/projects/{project_id}/documents", task: "T5.3", label: "Upload documents" },
  { method: "GET", path: "/projects/{project_id}/documents", task: "T5.4", label: "List documents" },
  { method: "GET", path: "/documents/{document_id}", task: "T5.5", label: "Download document" },
  { method: "PUT", path: "/documents/{document_id}", task: "T5.6", label: "Replace document" },
  { method: "DELETE", path: "/documents/{document_id}", task: "T5.7", label: "Delete document" },
];

/** "/projects/{id}/info" and "/projects/{project_id}/info" compare equal. */
export function endpointKey(method: string, path: string): string {
  return `${method.toUpperCase()} ${path.replace(/\{[^}]+\}/g, "{}").replace(/\/+$/, "")}`;
}
