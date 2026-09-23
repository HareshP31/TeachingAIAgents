# Dashboard (Next.js)

Read-only, single-page operations console backed by FastAPI REST polling. It never talks to Postgres directly and never accepts document or workflow mutations. It renders:

- Document repository view (ingestion status, chunking/vectorization metrics)
- Compliance & risk breakdown
- LangGraph run trace / reasoning graph visualizer
- Security & audit log stream

Polling runs every 1.5 seconds while work is active and every 10 seconds when idle.

```bash
npm install
npm run dev
npm run build
```

Set `NEXT_PUBLIC_API_URL` when the backend is not on `http://localhost:8000`.
