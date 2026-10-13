import { ENDPOINTS, endpointKey } from "../api";
import { useApiStatus } from "../apiStatus";

export function StatusPage() {
  const { available, reachable, checkedAt, refresh } = useApiStatus();
  const done = available ? ENDPOINTS.filter((e) => available.has(endpointKey(e.method, e.path))).length : 0;
  const pct = Math.round((done / ENDPOINTS.length) * 100);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Backend progress</h1>
          <p className="muted">
            The required API endpoints, checked live against the backend's <code>/openapi.json</code>. This page refreshes every 30 seconds.
          </p>
        </div>
        <button className="btn" onClick={refresh}>Check now</button>
      </div>

      {reachable === false && (
        <div className="notice notice-error">
          Can't reach the backend. Start it with <code>uv run uvicorn app.main:app --reload</code> in the project folder.
        </div>
      )}

      {reachable && (
        <div className="card progress-card">
          <div className="progress-numbers">
            <span className="big">{done}</span>
            <span className="muted">of {ENDPOINTS.length} endpoints available</span>
          </div>
          <div className="progress-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div style={{ width: `${pct}%` }} />
          </div>
          {checkedAt && <div className="muted small">Last checked {checkedAt.toLocaleTimeString()}</div>}
        </div>
      )}

      <div className="card table-card">
        <table className="status-table">
          <thead>
            <tr>
              <th>Feature</th>
              <th>Endpoint</th>
              <th>Task</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {ENDPOINTS.map((e) => {
              const ok = available?.has(endpointKey(e.method, e.path));
              return (
                <tr key={endpointKey(e.method, e.path)}>
                  <td>{e.label}</td>
                  <td>
                    <code className={`method method-${e.method}`}>{e.method}</code> <code>{e.path}</code>
                  </td>
                  <td>{e.task}</td>
                  <td>
                    {available == null ? (
                      <span className="muted">—</span>
                    ) : ok ? (
                      <span className="status status-ok">Available</span>
                    ) : (
                      <span className="status status-pending">Not yet</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
