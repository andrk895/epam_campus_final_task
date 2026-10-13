import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Project } from "../api";
import { useAuth } from "../auth";
import { useApiStatus } from "../apiStatus";
import { Empty, ErrorBox, NotYet, RoleBadge, Spinner, errorText, formatDate } from "../components";

export function ProjectsPage() {
  const { session } = useAuth();
  const status = useApiStatus();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const listMissing = status.missing("GET", "/projects");
  const createMissing = status.missing("POST", "/projects");

  const load = useCallback(async () => {
    setError(null);
    try {
      setProjects(await api.listProjects(session?.login));
    } catch (e) {
      setError(errorText(e));
      setProjects([]);
    }
  }, [session?.login]);

  useEffect(() => {
    if (!listMissing) void load();
  }, [load, listMissing]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Your projects</h1>
          <p className="muted">Projects you own or were invited to.</p>
        </div>
        {!creating && (
          <button className="btn btn-primary" onClick={() => setCreating(true)} disabled={!!createMissing} title={createMissing ? `Comes in ${createMissing.task}` : undefined}>
            + New project
          </button>
        )}
      </div>

      {creating && (
        <NewProjectForm
          onCancel={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            if (id && status.has("GET", "/projects/{project_id}/info")) navigate(`/projects/${id}`);
            else void load();
          }}
        />
      )}
      {createMissing && !listMissing && <NotYet endpoint={createMissing} what="Creating projects" />}

      {listMissing ? (
        <NotYet endpoint={listMissing} what="The project list" />
      ) : projects === null ? (
        <Spinner />
      ) : (
        <>
          <ErrorBox error={error} />
          {projects.length === 0 && !error ? (
            <Empty title="No projects yet">Create your first project, or ask a colleague to invite you to theirs.</Empty>
          ) : (
            <div className="grid">
              {projects.map((p) => (
                <Link key={p.id} to={`/projects/${p.id}`} className="card project-card">
                  <div className="project-card-head">
                    <h2>{p.name}</h2>
                    <RoleBadge role={p.role} />
                  </div>
                  <p className="project-desc">{p.description || <span className="muted">No description</span>}</p>
                  <div className="project-meta">
                    {p.ownerLogin && <span>Owner: {p.ownerLogin}</span>}
                    <span>
                      {p.documents.length} document{p.documents.length === 1 ? "" : "s"}
                    </span>
                    <span>Updated {formatDate(p.updatedAt ?? p.createdAt)}</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function NewProjectForm({ onCancel, onCreated }: { onCancel: () => void; onCreated: (id?: string) => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Give the project a name.");
    setBusy(true);
    setError(null);
    try {
      const created = await api.createProject(name.trim(), description.trim());
      onCreated(created?.id != null ? String(created.id) : undefined);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <form className="card stack form-card" onSubmit={onSubmit}>
      <h2>New project</h2>
      <label className="field">
        <span>Name</span>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
      </label>
      <label className="field">
        <span>
          Description <span className="muted">(optional)</span>
        </span>
        <textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={5000} />
      </label>
      <ErrorBox error={error} />
      <div className="row">
        <button className="btn btn-primary" disabled={busy}>
          {busy ? "Creating…" : "Create project"}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
