# Vault AI task delegation: current runtime flow

This report describes the current working-tree implementation of **feature delegation**. A feature delegation is the multi-turn, optionally QA-gated path; the smaller `delegate_task` path creates one `CodingTurn` directly and is not an autonomous delegation loop.

## Plain-English flow

1. Vault AI chooses the registered `coding_sessions.delegate_feature` tool, or a user submits the Feature Delegations form. Both pass a coding session, title, description, acceptance criteria, the QA choice, and an iteration limit to `FeatureDelegationService.create()`.
2. Creation validates Codex login and session exclusivity, saves a `FeatureDelegation`, starts a daemon thread, and returns the queued database record immediately. The tool call does not wait for implementation or transfer execution to another remote service.
3. The daemon builds a coder prompt and starts a normal `CodingTurn` with source `feature`. `CodingSessionService` launches the local Codex CLI in structured-output mode. Codex works in a local control workspace and reaches the configured source repository through the generated `./ssh-target` broker wrapper.
4. The loop waits for the coder. A completed turn supplies an implementation summary; `needs_input` pauses with Codex's question/options; failure stops the loop as `failed`.
5. If QA is disabled, the delegation completes. Otherwise a separate Codex QA thread receives the specification plus the coder's latest summary. QA can run a persistent, action-by-action browser session. A pass completes, a reproducible failure automatically starts another coder/fix cycle, and a blocked/error result pauses for user input.
6. The web UI polls every 1.8 seconds while active and renders status, cycle, coder summary, latest QA verdict/evidence, and pending decisions. Vault AI can read the same bounded payload and resume or stop it with registered tools.

## Entry points and creation

- **Vault AI/tool path:** `coding_sessions.delegate_feature` is registered in `orchestration/tools/coding_sessions.py:300-333`. The common runner resolves and calls registered handlers in `orchestration/services.py:141-197`; the AI loop constructs the call and feeds its immediate result back into planning in `orchestration/function_caller.py:465-488`. Routing guidance reserves this path for substantial autonomous work in `orchestration/migrations/0050_codex_and_ssh_routing_context.py:4-10`.
- **Web path:** `POST /coding/sessions/{session_id}/delegations` calls the same service in `coding/views.py:187-201`; fields are in `coding/schemas.py:22-27`. The form calls it at `frontend/src/FeatureDelegationPanel.tsx:97-111` through `shared/api.ts:936-946`.
- **Common logic:** `FeatureDelegationService.create()` (`coding/delegations.py:49-82`) requires Codex authentication, a non-stopped session, no direct Codex/tmux process, no other active/waiting delegation, and non-empty specification fields. It clamps iterations to 1-12, creates the row, and calls `_spawn()`.
- **Asynchronous handoff:** `_spawn()` (`coding/delegations.py:84-101`) guards against duplicate work inside the current process and starts `_run_loop()` in a Python daemon thread. The caller receives a `queued` payload, not the eventual result.

## What is handed to Codex

There is no generic executor abstraction here: implementation and QA both directly spawn the locally installed `codex` CLI.

### Coder

- `_run_loop()` sets `coding`/`fixing`, increments the cycle, and creates a feature-sourced turn at `coding/delegations.py:484-507`.
- `_coder_prompt()` (`coding/delegations.py:129-153`) passes title, description, numbered acceptance criteria, and autonomy/verification instructions. Later cycles add the latest QA summary/failures; a user decision adds continuation text.
- `start_turn()` persists a queued `CodingTurn` and starts a daemon worker (`coding/services.py:408-445`). `_run_turn()` wraps the text in the Corv coding-worker instruction, starts Codex, and streams JSON events (`coding/services.py:448-507`).
- Codex runs as `codex exec`/`codex exec resume` with approval/sandbox bypass, JSON output, and a strict result schema (`coding/services.py:245-256`). The session `codex_thread_id` is reused, so coder cycles share a Codex conversation (`coding/services.py:469-470`, `498-504`).
- `prepare_workspace()` creates schemas, `AGENTS.md`, and SSH/tunnel/browser wrappers (`coding/services.py:85-211`). No SSH secrets or repository snapshot are put in the prompt. `AGENTS.md` provides target metadata and rules; commands cross a local Unix-socket SSH broker (`coding/services.py:97-124`, `132-146`).

Context therefore consists of explicit feature fields, latest QA feedback or user continuation, the persisted coder thread, and generated workspace instructions. Vault AI's full chat transcript, arbitrary job metadata, and prior tool results are not copied unless included in the description, criteria, or continuation.

### Independent QA

- `_run_qa()` creates one `FeatureQaRun` per cycle (`coding/delegations.py:308-327`). `_qa_prompt()` passes the specification, coder summary, optional retry instruction, and independent verification/browser rules (`coding/delegations.py:155-190`), not the coder's full log/conversation.
- `_execute_qa_turn()` starts a second `codex exec` process and parses a structured verdict (`coding/delegations.py:233-305`). QA has a separate delegation-level `qa_thread_id` reused across QA calls/cycles (`coding/delegations.py:244`, `286-289`).
- Browser QA is an action loop capped at 60 actions (`coding/delegations.py:308-396`). Each observation and screenshot returns to the same QA thread; evidence and verdict are persisted at `coding/delegations.py:398-441`.

## State, progress, and result delivery

- `FeatureDelegation` stores specification, aggregate status, cycles, QA thread ID, coder turn IDs, summaries, pending decision/error, and timestamps (`coding/models.py:127-173`).
- `CodingTurn` stores prompt, status, coder thread ID, summary, question/options, event log, error, and timestamps (`coding/models.py:78-124`).
- `FeatureQaRun` stores cycle, verdict, failures, evidence, question/options, event log, error, and timestamps (`coding/models.py:176-209`). Logs are capped at 1 MiB (`coding/services.py:28`, `coding/delegations.py:276-281`, `428-441`).
- `_run_loop()` is the state machine (`coding/delegations.py:450-604`): coder input/failure pauses or fails; QA pass completes; QA blocked/error pauses; QA failure loops into a fix cycle. At the cycle limit it asks whether to add three cycles (`coding/delegations.py:468-482`). Push notifications are best-effort (`coding/delegations.py:34-47`).
- `payload()` returns aggregate state and at most 20 coder turns/QA runs, without raw logs (`coding/delegations.py:723-785`). Combined bounded logs come from `live_logs_payload()` (`coding/services.py:366-389`); screenshots are served after containment/type checks (`coding/views.py:235-252`).
- The panel polls active work and renders paused/final state (`frontend/src/FeatureDelegationPanel.tsx:85-95`, `161-169`). Vault AI reads the same payload via list/get tools (`orchestration/tools/coding_sessions.py:336-365`). The initial tool result is only acknowledgement; a later status read is required to surface completion in chat.
- Resume supports `auto`, `qa`, and `coding`; blocked/errored QA defaults to QA-only retry, while coding starts another implementation cycle (`coding/delegations.py:607-658`). Stop cancels tracked coder turns/QA processes (`coding/delegations.py:660-685`).

## Limitations and edge cases

1. **Process-local execution:** rows survive restart, but daemon threads/process maps do not. Lazy reconciliation on payload read marks active work `needs_input`; nothing auto-resumes (`coding/delegations.py:687-725`).
2. **No cross-process duplicate guard:** `_active` is process-local. Creation has no unique constraint/transaction lock, so concurrent requests or web workers can race.
3. **No guaranteed proactive result delivery:** creation returns immediately, UI/chat depend on polling/status reads, and push failures are swallowed.
4. **Permissive coder result parsing:** invalid final JSON is treated as a completed text summary (`coding/services.py:520-530`). QA output is stricter.
5. **QA-disabled work trusts Codex:** a completed coder turn immediately completes (`coding/delegations.py:537-547`). QA failures otherwise loop automatically to the cap.
6. **Partial/stale context risk:** later prompts promote summaries/failures, not full logs/chat. The session-wide coder thread can include earlier non-feature tasks; QA uses one thread across its runs.
7. **Bounded visibility:** payload history is limited to 20 turns/runs, list calls omit history, logs truncate, and the panel shows only latest QA.
8. **Cooperative stopping:** only subprocesses tracked in the current process can be terminated. After restart, reconciliation cannot prove or kill an orphan OS process.
9. **Iteration asymmetry:** creation caps at 12, while resume can extend by three to 15 (`coding/delegations.py:637-638`). QA-only retries do not consume coding iterations.
