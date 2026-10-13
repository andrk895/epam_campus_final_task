import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type DocumentMeta, type Project } from "../api";
import { useAuth } from "../auth";
import { useApiStatus } from "../apiStatus";
import { Empty, ErrorBox, NotYet, RoleBadge, Spinner, errorText, fileKind, formatDate, formatSize } from "../components";

// Allowed types per D8 in specification.md. The backend is the real gatekeeper; this just
// filters the file picker.
const ACCEPT = ".png,.jpg,.jpeg,.gif,.webp,.pdf,.doc,.docx";

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const { session } = useAuth();
  const status = useApiStatus();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const infoMissing = status.missing("GET", "/projects/{project_id}/info");

  const load = useCallback(async () => {
    try {
      setProject(await api.getProject(projectId, session?.login));
      setLoadError(null);
    } catch (e) {
      setLoadError(errorText(e));
    }
  }, [projectId, session?.login]);

  useEffect(() => {
    if (!infoMissing) void load();
  }, [load, infoMissing]);

  if (infoMissing) {
    return (
      <div className="page">
        <BackLink />
        <NotYet endpoint={infoMissing} what="Project details" />
      </div>
    );
  }
  if (loadError && !project) {
    return (
      <div className="page">
        <BackLink />
        <ErrorBox error={loadError === "Not found" ? "This project doesn't exist, or you don't have access to it." : loadError} />
      </div>
    );
  }
  if (!project) return <div className="page"><Spinner /></div>;

  const isOwner = project.role === "owner";

  return (
    <div className="page">
      <BackLink />
      <DetailsSection project={project} isOwner={isOwner} onChanged={load} onDeleted={() => navigate("/projects")} />
      <div className="two-col">
        <DocumentsSection projectId={project.id} isOwner={isOwner} fallback={project.documents} />
        <MembersSection project={project} isOwner={isOwner} onChanged={load} />
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <Link to="/projects" className="back-link">
      ← All projects
    </Link>
  );
}

// ---------------- details ----------------

function DetailsSection({ project, isOwner, onChanged, onDeleted }: { project: Project; isOwner: boolean; onChanged: () => Promise<void>; onDeleted: () => void }) {
  const status = useApiStatus();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const editMissing = status.missing("PUT", "/projects/{project_id}/info");
  const deleteMissing = status.missing("DELETE", "/projects/{project_id}");

  function startEdit() {
    setName(project.name);
    setDescription(project.description);
    setError(null);
    setEditing(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("The name can't be empty.");
    setBusy(true);
    try {
      await api.updateProject(project.id, name.trim(), description.trim());
      await onChanged();
      setEditing(false);
      setError(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    const ok = window.confirm(`Delete "${project.name}"?\n\nThis permanently deletes the project and all ${project.documents.length || "its"} documents for every member.`);
    if (!ok) return;
    setBusy(true);
    try {
      await api.deleteProject(project.id);
      onDeleted();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <form className="card stack" onSubmit={save}>
        <label className="field">
          <span>Name</span>
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </label>
        <label className="field">
          <span>Description</span>
          <textarea rows={5} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={5000} />
        </label>
        <ErrorBox error={error} />
        <div className="row">
          <button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save changes"}</button>
          <button type="button" className="btn" onClick={() => setEditing(false)}>Cancel</button>
        </div>
      </form>
    );
  }

  return (
    <section className="card details">
      <div className="details-head">
        <div>
          <div className="row">
            <h1>{project.name}</h1>
            <RoleBadge role={project.role} />
          </div>
          <p className="muted small">
            {project.ownerLogin && <>Owner: {project.ownerLogin} · </>}
            Created {formatDate(project.createdAt)}
            {project.updatedAt && <> · Updated {formatDate(project.updatedAt)}</>}
          </p>
        </div>
        <div className="row">
          <button className="btn" onClick={startEdit} disabled={!!editMissing} title={editMissing ? `Comes in ${editMissing.task}` : undefined}>
            Edit
          </button>
          {isOwner && (
            <button className="btn btn-danger" onClick={remove} disabled={busy || !!deleteMissing} title={deleteMissing ? `Comes in ${deleteMissing.task}` : undefined}>
              Delete project
            </button>
          )}
        </div>
      </div>
      <p className="description">{project.description || <span className="muted">No description.</span>}</p>
      <ErrorBox error={error} />
    </section>
  );
}

// ---------------- documents ----------------

function DocumentsSection({ projectId, isOwner, fallback }: { projectId: string; isOwner: boolean; fallback: DocumentMeta[] }) {
  const status = useApiStatus();
  const [docs, setDocs] = useState<DocumentMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);
  const replaceInput = useRef<HTMLInputElement>(null);
  const replaceTarget = useRef<DocumentMeta | null>(null);

  const listMissing = status.missing("GET", "/projects/{project_id}/documents");
  const uploadMissing = status.missing("POST", "/projects/{project_id}/documents");
  const canDownload = status.has("GET", "/documents/{document_id}");
  const canReplace = status.has("PUT", "/documents/{document_id}");
  const canDelete = status.has("DELETE", "/documents/{document_id}");

  const load = useCallback(async () => {
    try {
      setDocs(await api.listDocuments(projectId));
    } catch (e) {
      setError(errorText(e));
      setDocs([]);
    }
  }, [projectId]);

  useEffect(() => {
    if (!listMissing) void load();
  }, [load, listMissing]);

  async function upload(files: File[]) {
    if (files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadDocuments(projectId, files);
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setUploading(false);
    }
  }

  async function act(doc: DocumentMeta, fn: () => Promise<unknown>, reload = true) {
    setBusyId(doc.id);
    setError(null);
    try {
      await fn();
      if (reload) await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusyId(null);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (!uploadMissing) void upload(Array.from(e.dataTransfer.files));
  }

  // Before the documents endpoint exists, show whatever came with the project details.
  const shown = listMissing ? fallback : docs;

  return (
    <section className="card">
      <div className="section-head">
        <h2>Documents</h2>
        {shown && <span className="muted small">{shown.length}</span>}
      </div>

      {uploadMissing ? (
        <NotYet endpoint={uploadMissing} what="Uploading documents" />
      ) : (
        <div
          className={`dropzone ${dragOver ? "over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => uploadInput.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && uploadInput.current?.click()}
        >
          {uploading ? <Spinner label="Uploading…" /> : (
            <>
              <strong>Drop files here</strong> or click to choose
              <div className="muted small">Images, PDF, Word · several at once is fine</div>
            </>
          )}
          <input
            ref={uploadInput}
            type="file"
            multiple
            accept={ACCEPT}
            hidden
            onChange={(e) => {
              void upload(Array.from(e.target.files ?? []));
              e.target.value = "";
            }}
          />
        </div>
      )}

      <input
        ref={replaceInput}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          const target = replaceTarget.current;
          e.target.value = "";
          if (file && target) void act(target, () => api.replaceDocument(target.id, file));
        }}
      />

      <ErrorBox error={error} />

      {shown === null ? (
        <Spinner />
      ) : shown.length === 0 ? (
        <Empty title="No documents yet" />
      ) : (
        <ul className="doc-list">
          {shown.map((d) => (
            <li key={d.id} className="doc">
              <span className={`doc-kind kind-${fileKind(d.contentType, d.filename)}`}>{fileKind(d.contentType, d.filename)}</span>
              <div className="doc-main">
                <div className="doc-name" title={d.filename}>{d.filename}</div>
                <div className="muted small">
                  {formatSize(d.size)}
                  {d.uploadedBy && <> · by {d.uploadedBy}</>} · {formatDate(d.updatedAt ?? d.createdAt)}
                </div>
              </div>
              <div className="doc-actions">
                {busyId === d.id ? (
                  <span className="spinner" aria-label="Working" />
                ) : (
                  <>
                    {canDownload && (
                      <button className="btn btn-small" onClick={() => void act(d, () => api.downloadDocument(d), false)}>Download</button>
                    )}
                    {canReplace && (
                      <button
                        className="btn btn-small"
                        onClick={() => {
                          replaceTarget.current = d;
                          replaceInput.current?.click();
                        }}
                      >
                        Replace
                      </button>
                    )}
                    {/* D6: only the owner may delete documents */}
                    {canDelete && isOwner && (
                      <button
                        className="btn btn-small btn-danger-ghost"
                        onClick={() => window.confirm(`Delete "${d.filename}"?`) && void act(d, () => api.deleteDocument(d.id))}
                      >
                        Delete
                      </button>
                    )}
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------------- members ----------------

function MembersSection({ project, isOwner, onChanged }: { project: Project; isOwner: boolean; onChanged: () => Promise<void> }) {
  const status = useApiStatus();
  const [invitee, setInvitee] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const inviteMissing = status.missing("POST", "/projects/{project_id}/invite");
  const canRemove = status.has("DELETE", "/projects/{project_id}/participants/{login}");

  const members = project.participants ?? (project.ownerLogin ? [{ login: project.ownerLogin, role: "owner" }] : []);
  const sorted = [...members].sort((a, b) => (a.role === "owner" ? -1 : b.role === "owner" ? 1 : a.login.localeCompare(b.login)));

  async function invite(e: FormEvent) {
    e.preventDefault();
    const login = invitee.trim();
    if (!login) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await api.invite(project.id, login);
      setInvitee("");
      setInfo(`${login} now has access to this project.`);
      await onChanged();
    } catch (err) {
      const msg = errorText(err);
      setError(msg === "Not found" ? `There's no user called "${login}".` : msg);
    } finally {
      setBusy(false);
    }
  }

  async function remove(login: string) {
    if (!window.confirm(`Remove ${login} from this project? They lose access immediately.`)) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await api.removeParticipant(project.id, login);
      await onChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <div className="section-head">
        <h2>Members</h2>
        <span className="muted small">{members.length}</span>
      </div>

      {sorted.length === 0 ? (
        <p className="muted small">The backend didn't return a member list.</p>
      ) : (
        <ul className="member-list">
          {sorted.map((m) => (
            <li key={m.login} className="member">
              <span className="avatar" aria-hidden>{m.login.slice(0, 1).toUpperCase()}</span>
              <span className="member-name">{m.login}</span>
              <RoleBadge role={m.role} />
              {isOwner && canRemove && m.role !== "owner" && (
                <button className="btn btn-small btn-danger-ghost" disabled={busy} onClick={() => void remove(m.login)}>
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {isOwner ? (
        inviteMissing ? (
          <NotYet endpoint={inviteMissing} what="Inviting people" />
        ) : (
          <form className="invite" onSubmit={invite}>
            <input placeholder="Login of the person to invite" value={invitee} onChange={(e) => setInvitee(e.target.value)} />
            <button className="btn btn-primary" disabled={busy || !invitee.trim()}>Invite</button>
          </form>
        )
      ) : (
        <p className="muted small">Only the owner can invite or remove people.</p>
      )}
      {info && <div className="notice notice-success">{info}</div>}
      <ErrorBox error={error} />
    </section>
  );
}
