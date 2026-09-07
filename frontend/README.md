# Dashboard (Next.js)

Not yet scaffolded. Bootstrap it with:

```bash
npx create-next-app@latest . --typescript --tailwind --app
npm install @radix-ui/react-icons recharts lucide-react
npx shadcn@latest init
```

Read-only mirror of the backend's Postgres tables via the FastAPI REST/WebSocket
endpoints — never talks to the database directly, and never accepts input
(documents go in via Slack, not the dashboard). Renders:

- Document repository view (ingestion status, chunking/vectorization metrics)
- Compliance & risk breakdown
- LangGraph run trace / reasoning graph visualizer
- Security & audit log stream

See `docs/project-architecture-plan.md` sections 4 and 10-11.
