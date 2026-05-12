# miniBOT

miniBOT is a small FastAPI + LangChain + LangGraph + Vue scaffold inspired by YUXI's extensible resource flow.

## Architecture

- Backend: `backend/app`
  - `api`: FastAPI routers.
  - `db`: SQLAlchemy async PostgreSQL models and repositories.
  - `plugins`: MCP, Skill, and Subagent resource registry.
  - `graph`: LangGraph graph assembly with middleware-style resource handling.
- Frontend: `frontend/src`
  - `apis`: API wrappers.
  - `stores`: selection state.
  - `components`: reusable resource selectors and chat test panel.
  - `views`: page composition.

## Development

Start PostgreSQL:

```powershell
docker compose up -d postgres
```

Install and run backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Install and run frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Current Resource Flow

1. Backend seeds example MCP, Skill, and Subagent records into PostgreSQL on startup.
2. Frontend loads resource lists from `/api/resources`.
3. User checks MCP, Skill, and Subagent names.
4. Frontend saves names to `/api/selections/{user_key}`.
5. Chat runtime resolves selected names back to PostgreSQL resource records.
6. LangGraph receives resolved resources and passes them through middleware before the assistant node.

This keeps the first version small while preserving the YUXI-style pattern: database-backed resource metadata, runtime name resolution, and graph middleware composition.
