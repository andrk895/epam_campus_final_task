# Environment notes (for orchestrator / subagents)
- No Docker. PostgreSQL 16 runs locally via the `pgserver` pip package, installed in ~/.local/share/pg-local (outside the repo).
- localhost:5432, user postgres / password postgres, databases pm_app (dev) and pm_test (tests).
- Start: ~/.local/share/pg-local/bin/pg_ctl -D ~/.local/share/pg-local/data -l ~/.local/share/pg-local/server.log -o "-p 5432 -k /tmp -c listen_addresses=localhost" -w start
- Stop:  ~/.local/share/pg-local/bin/pg_ctl -D ~/.local/share/pg-local/data stop
- uv: ~/.local/bin/uv
