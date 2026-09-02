# CorvAI

> A personal AI workspace built around agentic LLMs: one conversational front door, specialized tools, and autonomous coding workers that carry work through implementation and QA.

CorvAI is a passion project developed by **Achilleas Georgiou**. Its focus is practical agentic LLM orchestration—not merely generating an answer, but deciding when to act, selecting the right capability, executing multi-step work, retaining useful context, and returning a verifiable result.

Corv can chat or speak with you, search personal knowledge and the internet, manage everyday information, operate trusted SSH machines, and delegate substantial software work to Codex. The web and mobile interfaces expose the same underlying system as a personal workspace.

## Why CorvAI exists

Most assistant demos stop at a prompt and a response. CorvAI explores the harder parts:

- How does a conversational model decide when a tool is useful?
- How can tool calls become durable jobs rather than fragile request-bound actions?
- How can an assistant pause for a decision and resume with the right context?
- How should long-running coding work survive restarts and return files or QA evidence?
- How can personal memory stay searchable without reducing everything to rigid filters?
- How can text chat and live voice share one personality and one action system?

The result is an evolving, self-hosted agentic workspace rather than a single chatbot endpoint.

## Architecture

```mermaid
flowchart LR
    U[Web or mobile user] --> I[Text / voice input]
    I --> F[Frontman]
    F -->|answer directly| C[Conversation]
    F -->|action needed| J[Durable job]
    J --> P[Function Caller]
    P -->|one planned action| R[Function Runner]
    R --> T[(Tool modules)]
    T --> P
    P -->|done| C
    P -->|decision needed| W[Wait for user]
    W --> P
    T --> D[Codex delegation]
    D --> S[SSH broker + workspace]
    D --> Q[Independent QA]
    S --> A[Files and artifacts]
    Q --> C
    A --> C
```

### The agent stack

1. **Frontman** is the conversational layer. It applies Corv's persona and user context, then decides whether to reply directly or hand the request to the action system.
2. **Function Caller** is an iterative planner. It receives the registered tool catalog, module guidance, relevant context, and prior results. It chooses exactly one next action, asks for input, or finishes.
3. **Function Runner** validates and invokes the selected registered function. Its result returns to the caller for the next planning step.
4. **Durable jobs** record status, progress, events, errors, pending questions, and user-visible summaries. Conversation waits can be interrupted, resumed, or switched between concurrent delegations.
5. **Codex workers** handle repository discovery, implementation, debugging, testing, and file generation. Coding sessions use isolated control workspaces and an SSH broker so credentials are not copied into prompts or workspaces.
6. **Independent QA** can inspect a completed feature, run tests, drive a bounded browser session, collect screenshots, and route reproducible failures back into another coding cycle.

### Runtime services

| Service | Role |
| --- | --- |
| Django + Django Ninja | API, persistence, orchestration, file delivery, and server-side workflows |
| React + Vite | Responsive web workspace |
| Expo + React Native | Native mobile client and call experience |
| PostgreSQL + pgvector | Durable state, structured knowledge, tags, and vector search |
| Redis | Celery broker and result backend |
| Celery worker | Background and scheduled execution |
| Celery Beat | Reminder/call polling, planning checks, and expired-note cleanup |
| OpenAI / xAI | Configurable LLM, embedding, transcription, and voice providers |
| Codex CLI | Autonomous coding and QA execution |

## Capabilities

Corv's action catalog is registered at startup and persisted as modules/functions with descriptions, JSON schemas, examples, embeddings, and planner instructions.

### Conversation and voice

- Persistent chats with rename, archive, and delete controls
- Shared concise, dry-witty Corv personality across text and calls
- Markdown presentation and icon-bearing source chips in text mode
- Realtime voice calls, push-to-talk, transcripts, configurable voices, and call actions
- Search-before-unknown behavior for personal or public questions
- Concurrent delegations with per-job wait, interrupt, resume, and decision handling

### Knowledge and notes

- Plain notes plus extensible typed entities in one unified notes experience
- Structured people and locations with facts, relationships, coordinates, map search, and map picking
- Unified tags and semantic vector search across every knowledge type
- Semantic-first retrieval with entity-aware ranking
- Expiring notes and automatic cleanup
- Stable note-writing guidance: absolute dates and time-stable facts instead of relative wording

### Work and planning

- Objectives, nested objectives, tasks, deadlines, priorities, and remaining-effort tracking
- Fixed calendar events and flexible scheduled work
- Two-week planning across commitments, effort, priorities, and deadlines
- Scheduled tasks, execution history, user messages, and notification delivery
- Google Calendar support when credentials are configured

### Coding and remote execution

- Saved SSH machines with encrypted credentials, host-key pinning, per-machine notes, and a user-selected default
- Persistent SSH terminals and command history
- Reusable Codex sessions tied to a selected SSH machine and working directory
- Simple one-turn delegations, including editable speech-to-text task drafting
- Autonomous feature delegations with acceptance criteria, iterative fixes, restart recovery, and independent QA
- Browser QA with bounded interaction specifications and screenshots
- File artifacts uploaded during or after delegation, scoped to their coding session and visible in Files
- Codex API-key or account-login profiles, with usage visibility where supported

### Dedicated workspaces

- Workout plans, exercise directory, live check-off sessions, history, goals, consistency, and progress trends
- Study courses, topics, exams, assignments, uploaded material, generated outputs, and audiobooks
- File library with previews for text, images, PDFs, audio, video, and supported documents
- Usage/cost views and configurable orchestration models
- Administrative action modules for persona, settings, modules, and cache behavior

## Quick start with Docker Compose

### Prerequisites

- Git
- Docker Engine with Docker Compose v2
- A reachable PostgreSQL database with permission to create the `vector` extension
- An OpenAI API key for the default model, embeddings, transcription, and related AI features

> A SQLite fallback exists for limited development paths, but the full knowledge system uses PostgreSQL arrays and pgvector. Use PostgreSQL for a real Corv installation.

### 1. Clone the repository

```bash
git clone https://github.com/AchilleasG/CorvAI.git
cd CorvAI
```

The primary branch is currently `master`.

### 2. Create the environment file

```bash
cp .env.example .env
```

At minimum, set:

```dotenv
DATABASE_URL=postgresql://corv:replace-me@your-postgres-host:5432/corv
OPENAI_KEY=replace-me
APP_ACCESS_TOKEN=choose-a-long-random-password
```

The database user must be able to run `CREATE EXTENSION IF NOT EXISTS vector`, which the migration performs automatically.

### 3. Start Corv

```bash
docker compose up --build -d
docker compose ps
```

The web container runs migrations before starting the API. Tool modules are imported and registered during Django startup.

Open:

- Web UI: <http://localhost:5173>
- API documentation: <http://localhost:8004/api/docs>
- Django admin: <http://localhost:8004/admin/>

Enter `APP_ACCESS_TOKEN` at the Corv access screen. If it is blank, the token middleware permits unauthenticated access; that is convenient locally and inappropriate for an exposed instance.

### 4. Configure Codex and SSH

Open **Coding** in the web UI and choose API-key or account-login mode. Complete authentication, then open **SSH** and add a machine Corv may use:

1. Save its host, username, and authentication method.
2. Enable **Allow Corv to execute commands on this machine**.
3. Optionally make it the default machine.
4. Add notes describing repositories, paths, capabilities, package managers, and constraints.
5. Connect once to pin and verify the host key.

Corv can now create a coding session against that machine and delegate tasks or complete feature cycles.

## Configuration

Copy [`.env.example`](.env.example) and supply only the integrations you intend to use.

### Core

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Yes for full functionality | PostgreSQL connection string |
| `OPENAI_KEY` | Yes for default AI functionality | OpenAI models, embeddings, and transcription |
| `APP_ACCESS_TOKEN` | Strongly recommended | Shared token protecting API and web access |
| `MODULE_SECRET_KEY` | For stored module secrets | URL-safe base64 key decoding to exactly 32 bytes |
| `CORV_PUBLIC_BASE_URL` | For remote artifact callbacks | Public origin such as `https://corv.example.com` |
| `TIME_ZONE` | Optional | Celery timezone; Django stores timestamps in UTC |

Generate a module encryption key with:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

### Models and voice

| Variable | Default | Purpose |
| --- | --- | --- |
| `XAI_API_KEY` | unset | Enables models whose names begin with `grok` |
| `XAI_BASE_URL` | `https://api.x.ai/v1` | xAI-compatible API origin |
| `TRANSCRIPTION_MODEL` | `gpt-4o-mini-transcribe` | Speech-to-text model |

Frontman, Function Caller, planning, and embedding model names can also be changed from Settings and are stored in the database.

### Files and background work

| Variable | Default | Purpose |
| --- | --- | --- |
| `CORV_CODING_DIR` | `/var/lib/corv-coding` | Coding control workspaces |
| `CORV_MEDIA_DIR` | project `media/` | Uploaded/generated media storage |
| `CORV_LOG_DIR` | project root, then `/tmp` | Runtime log destination |
| `CORV_MAX_UPLOAD_SIZE` | 100 MiB | Django in-memory upload limit |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` in Compose | Celery broker |
| `CELERY_RESULT_BACKEND` | broker URL | Celery results |
| `CELERY_RESULT_EXPIRES` | `3600` | Result expiry in seconds |

### Optional integrations

| Variables | Feature |
| --- | --- |
| `GOOGLE_CALENDAR_CREDENTIALS_JSON` or `GOOGLE_CALENDAR_CREDENTIALS_FILE` | Google Calendar service account |
| `GOOGLE_CALENDAR_DELEGATED_USER` | Optional Workspace user impersonation |
| `GOOGLE_CALENDAR_DEFAULT_ID` | Calendar used when none is specified |
| `GOOGLE_CALENDAR_DEFAULT_TIMEZONE` | Planning timezone; defaults to `Europe/Athens` |
| `FCM_PROJECT_ID` plus `FCM_SERVICE_ACCOUNT_JSON` or `FCM_SERVICE_ACCOUNT_FILE` | Firebase notifications |
| `NOMINATIM_BASE_URL` | Alternate/self-hosted OpenStreetMap geocoder |

## Development without Compose

Docker is recommended because the image includes Chromium, ChromeDriver, SSH tooling, tmux, speech support, Node, and Codex CLI.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py run_coding_server 0.0.0.0:8000
```

In separate terminals:

```bash
redis-server
celery -A CorvAI worker -l info
celery -A CorvAI beat -l info
```

Web client:

```bash
cd frontend
npm install
npm run dev
```

Mobile client:

```bash
cd mobile
npm install
npm start
```

Native notifications, calls, microphone access, and WebRTC require platform permissions and, in several cases, an Expo development build rather than Expo Go.

## Verification

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput
npm --prefix frontend run build
```

Service health and logs:

```bash
docker compose ps
docker compose logs -f web celery-worker celery-beat frontend
```

## Repository map

```text
CorvAI/              Django project settings and URLs
api/                 Top-level Django Ninja API assembly
chat/                Conversations, messages, and Frontman handoff
orchestration/       Jobs, planner, tool registry, calls, scheduler, and tools
coding/              Codex sessions, delegations, QA, files, and SSH broker
ssh_connections/     Saved machines, credentials, terminals, and command history
study/               Study domain models and workflows
workout/             Workout plans, live sessions, history, goals, and trends
input/               Text and voice ingestion
openai_integration/  Model, transcription, and media integrations
frontend/            React/Vite web workspace
mobile/              Expo/React Native client
shared/              Shared TypeScript API client and types
docs/                Focused technical notes
```

## Security and deployment notes

CorvAI is a personal passion project under active development, not a hardened multi-tenant SaaS product.

- Never commit `.env`, SSH keys, provider credentials, Firebase credentials, or generated media.
- Set `APP_ACCESS_TOKEN` before exposing the service.
- Use TLS and a reverse proxy for public deployments.
- Restrict network access to PostgreSQL and Redis; development Compose publishes Redis for convenience.
- Only enable AI commands on machines you trust Corv and Codex to operate.
- Review machine notes and working directories carefully; coding sessions can execute commands and change files.
- Back up PostgreSQL, media storage, and the `codex-data` / `coding-data` volumes.
- Review Django's production checklist before changing deployment topology.

## Project status

CorvAI is intentionally broad and experimental. Features evolve quickly, and some integrations require external accounts or infrastructure. The repository currently prioritizes a powerful personal deployment and transparent agent workflow over turnkey multi-user hosting.

## Author

**Achilleas Georgiou** — creator and developer of CorvAI.

Built as a passion project focused on making agentic LLMs genuinely useful: capable of remembering, choosing tools, doing work, asking when necessary, and showing what happened afterward.
