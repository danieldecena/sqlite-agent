# sqlite-agent

Interactive SQLite CLI with named profiles (scout, ops, finance, …) pointing at this Mac's project databases. Entry: `sqlite_agent.py` and the `sqlite-agent` wrapper.

## Stack
Python 3, stdlib sqlite3. Paths are hardcoded to `/Users/home/...`.

## Do not
- Copy databases. Query in place.
- Invent a hosted `DATABASE_URL`. Durable data is local SQLite or Homebrew Postgres (`~/POSTGRES.md`).
