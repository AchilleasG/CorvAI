import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  answerCodingDecision,
  cancelCodingDeviceAuth,
  closeCodingTerminal,
  createCodingSession,
  deleteCodingSession,
  fetchCodingSession,
  fetchCodingSessionLogs,
  fetchCodingSessions,
  fetchCodingStatus,
  fetchCodingDeviceAuth,
  fetchCodingTerminal,
  fetchSshMachines,
  sendCodingTerminalInput,
  startCodingDeviceAuth,
  startCodingTask,
  startCodingTerminal,
  stopCodingSession,
  logoutCodingCodex,
} from "./api";
import type { CodingCliStatus, CodingDeviceAuth, CodingLiveLogs, CodingSession, CodingTerminal, SshMachine } from "./types";
import "./coding.css";
import FeatureDelegationPanel from "./FeatureDelegationPanel";
import CodingLogViewer from "./CodingLogViewer";


function errorText(error: unknown): string {
  if (!(error instanceof Error)) return "Something went wrong";
  try {
    const parsed = JSON.parse(error.message);
    return parsed.detail || parsed.message || error.message;
  } catch {
    return error.message;
  }
}

function statusLabel(status: CodingSession["status"]): string {
  return {
    ready: "Ready",
    running: "Codex working",
    needs_input: "Decision needed",
    direct: "Direct CLI",
    failed: "Failed",
    stopped: "Stopped",
  }[status];
}

export default function CodingPanel() {
  const [cliStatus, setCliStatus] = useState<CodingCliStatus | null>(null);
  const [deviceAuth, setDeviceAuth] = useState<CodingDeviceAuth | null>(null);
  const [machines, setMachines] = useState<SshMachine[]>([]);
  const [sessions, setSessions] = useState<CodingSession[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<CodingSession | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [machineId, setMachineId] = useState("");
  const [remoteDirectory, setRemoteDirectory] = useState("~");
  const [task, setTask] = useState("");
  const [decision, setDecision] = useState("");
  const [terminal, setTerminal] = useState<CodingTerminal | null>(null);
  const [terminalInput, setTerminalInput] = useState("");
  const [showLogs, setShowLogs] = useState(false);
  const [liveLogs, setLiveLogs] = useState<CodingLiveLogs | null>(null);
  const [followLogs, setFollowLogs] = useState(true);
  const [rawLogs, setRawLogs] = useState(false);
  const [busy, setBusy] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const terminalRef = useRef<HTMLPreElement | null>(null);
  const logsRef = useRef<HTMLDivElement | null>(null);

  const eligibleMachines = useMemo(
    () => machines.filter((machine) => machine.allow_ai_commands),
    [machines],
  );

  async function refreshList(preferredId?: string | null) {
    const response = await fetchCodingSessions();
    setSessions(response.sessions);
    setSelectedId((current) => {
      const candidate = preferredId === undefined ? current : preferredId;
      return candidate && response.sessions.some((session) => session.id === candidate)
        ? candidate
        : response.sessions[0]?.id || null;
    });
  }

  async function refreshSelected(sessionId = selectedId) {
    if (!sessionId) {
      setSelected(null);
      return;
    }
    const session = await fetchCodingSession(sessionId);
    setSelected(session);
    setSessions((current) => current.map((item) => item.id === session.id ? session : item));
    if (session.direct_terminal_running) {
      setTerminal(await fetchCodingTerminal(session.id));
    } else {
      setTerminal(null);
    }
  }

  useEffect(() => {
    Promise.all([fetchCodingStatus(), fetchCodingDeviceAuth(), fetchSshMachines(), fetchCodingSessions()])
      .then(([status, auth, machineResponse, sessionResponse]) => {
        setCliStatus(status);
        setDeviceAuth(auth);
        setMachines(machineResponse.machines);
        setSessions(sessionResponse.sessions);
        setSelectedId(sessionResponse.sessions[0]?.id || null);
        setMachineId(machineResponse.machines.find((machine) => machine.allow_ai_commands)?.id || "");
      })
      .catch((err) => setError(errorText(err)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!deviceAuth?.active) return;
    const timer = window.setInterval(() => {
      fetchCodingDeviceAuth()
        .then(async (auth) => {
          setDeviceAuth(auth);
          if (auth.status === "succeeded") setCliStatus(await fetchCodingStatus());
        })
        .catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [deviceAuth?.active]);

  useEffect(() => {
    refreshSelected(selectedId).catch((err) => setError(errorText(err)));
    setShowLogs(false);
    setLiveLogs(null);
  }, [selectedId]);

  useEffect(() => {
    if (!showLogs || !selectedId) return;
    let disposed = false;
    const refresh = () => fetchCodingSessionLogs(selectedId)
      .then((payload) => { if (!disposed) setLiveLogs(payload); })
      .catch((err) => { if (!disposed) setError(errorText(err)); });
    refresh();
    const timer = window.setInterval(refresh, 650);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [showLogs, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    const delay = selected?.direct_terminal_running ? 700 : selected?.status === "running" ? 1500 : 4000;
    const timer = window.setInterval(() => {
      refreshSelected(selectedId).catch(() => undefined);
      refreshList().catch(() => undefined);
    }, delay);
    return () => window.clearInterval(timer);
  }, [selectedId, selected?.status, selected?.direct_terminal_running]);

  useEffect(() => {
    const viewport = terminalRef.current;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }, [terminal?.output]);

  useEffect(() => {
    const viewport = logsRef.current;
    if (viewport && followLogs) viewport.scrollTop = viewport.scrollHeight;
  }, [liveLogs?.content, followLogs]);

  async function createSession(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await createCodingSession({
        name: name.trim(),
        machine_id: machineId,
        remote_working_directory: remoteDirectory.trim() || "~",
      });
      setCreating(false);
      setName("");
      await refreshList(session.id);
      setSelectedId(session.id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function beginCodexLogin() {
    setAuthBusy(true);
    setError(null);
    try {
      const auth = await startCodingDeviceAuth();
      setDeviceAuth(auth);
      if (auth.status === "succeeded") setCliStatus(await fetchCodingStatus());
    } catch (err) {
      setError(errorText(err));
    } finally {
      setAuthBusy(false);
    }
  }

  async function cancelCodexLogin() {
    setAuthBusy(true);
    try {
      setDeviceAuth(await cancelCodingDeviceAuth());
    } catch (err) {
      setError(errorText(err));
    } finally {
      setAuthBusy(false);
    }
  }

  async function logoutCodex() {
    if (!window.confirm("Log Codex CLI out of this Corv installation?")) return;
    setAuthBusy(true);
    setError(null);
    try {
      await logoutCodingCodex();
      const [status, auth] = await Promise.all([fetchCodingStatus(), fetchCodingDeviceAuth()]);
      setCliStatus(status);
      setDeviceAuth(auth);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setAuthBusy(false);
    }
  }

  async function copyDeviceCode() {
    if (!deviceAuth?.user_code) return;
    try {
      await navigator.clipboard.writeText(deviceAuth.user_code);
    } catch {
      setError("Could not copy automatically; select the code and copy it manually.");
    }
  }

  async function submitTask(event: FormEvent) {
    event.preventDefault();
    if (!selected || !task.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await startCodingTask(selected.id, task.trim());
      setTask("");
      await refreshSelected(selected.id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitDecision(value?: string) {
    if (!selected) return;
    const answer = (value || decision).trim();
    if (!answer) return;
    setBusy(true);
    setError(null);
    try {
      await answerCodingDecision(selected.id, answer);
      setDecision("");
      await refreshSelected(selected.id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function openTerminal() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      setTerminal(await startCodingTerminal(selected.id));
      await refreshSelected(selected.id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function sendTerminal(event: FormEvent) {
    event.preventDefault();
    if (!selected || !terminalInput) return;
    try {
      setTerminal(await sendCodingTerminalInput(selected.id, { text: terminalInput, key: "Enter" }));
      setTerminalInput("");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function sendKey(key: "Up" | "Down" | "Tab" | "Escape" | "C-c" | "C-d") {
    if (!selected) return;
    try {
      setTerminal(await sendCodingTerminalInput(selected.id, { key }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function closeTerminalSession() {
    if (!selected || !window.confirm("Close the direct CLI? The Codex thread remains saved and resumable.")) return;
    setBusy(true);
    try {
      await closeCodingTerminal(selected.id);
      setTerminal(null);
      await refreshSelected(selected.id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function stopSession() {
    if (!selected || !window.confirm("Stop this coding session and any active Codex process?")) return;
    setBusy(true);
    try {
      await stopCodingSession(selected.id);
      setTerminal(null);
      await refreshSelected(selected.id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function removeSession() {
    if (!selected || !window.confirm(`Delete coding session “${selected.name}” and its history?`)) return;
    setBusy(true);
    try {
      await deleteCodingSession(selected.id);
      setSelected(null);
      await refreshList(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-panel coding-panel">
      <header className="main-header">
        <div><p className="eyebrow">Remote development</p><h2>Codex coding sessions</h2></div>
        <div className="main-actions">
          <div className="coding-runtime-status" aria-label="Codex runtime status">
            {cliStatus?.authenticated && <span className="coding-status-chip ready"><i aria-hidden />Codex ready</span>}
            <span className="coding-status-chip access">Full access</span>
          </div>
          {cliStatus?.authenticated && <button className="ghost" onClick={logoutCodex} disabled={authBusy}>Log out Codex</button>}
          <button className="primary" onClick={() => setCreating(true)} disabled={!cliStatus?.authenticated}>New session</button>
        </div>
      </header>

      {error && <div className="alert">{error}</div>}
      {cliStatus && (!cliStatus.installed || !cliStatus.tmux_available || !cliStatus.ssh_available) && (
        <div className="alert coding-setup-alert">
          <strong>Coding runtime needs setup.</strong>
          <span>{cliStatus.auth_message}</span>
        </div>
      )}
      {cliStatus?.installed && !cliStatus.authenticated && (
        <div className="card coding-auth-card">
          <div>
            <p className="eyebrow">Codex authentication</p>
            <h3>Sign in with ChatGPT</h3>
            <p className="muted">Corv will show a one-time code. Authentication is completed only on OpenAI’s website.</p>
          </div>
          {deviceAuth?.active ? (
            <div className="coding-device-flow">
              <p>{deviceAuth.message}</p>
              {deviceAuth.user_code && (
                <div className="coding-device-code">
                  <span>{deviceAuth.user_code}</span>
                  <button type="button" className="ghost" onClick={copyDeviceCode}>Copy code</button>
                </div>
              )}
              <div className="actions-row">
                <button type="button" className="ghost" onClick={cancelCodexLogin} disabled={authBusy}>Cancel</button>
                {deviceAuth.verification_url && deviceAuth.user_code && <a className="primary button-link" href={deviceAuth.verification_url} target="_blank" rel="noreferrer">Open OpenAI sign-in</a>}
              </div>
              {deviceAuth.expires_at && <small className="muted">Code expires {new Date(deviceAuth.expires_at).toLocaleTimeString()}.</small>}
            </div>
          ) : (
            <div className="coding-auth-start">
              {deviceAuth && deviceAuth.status !== "idle" && <p className={`coding-auth-message ${deviceAuth.status}`}>{deviceAuth.message}</p>}
              <button type="button" className="primary" onClick={beginCodexLogin} disabled={authBusy}>{authBusy ? "Starting…" : "Sign in through browser"}</button>
            </div>
          )}
        </div>
      )}

      <div className="coding-layout">
        <aside className="card coding-session-list">
          <div className="card-head"><h3>Sessions</h3></div>
          {loading ? <p className="muted">Loading…</p> : sessions.map((session) => (
            <button
              type="button"
              key={session.id}
              className={`coding-session-row ${selectedId === session.id ? "active" : ""}`}
              onClick={() => { setSelectedId(session.id); setCreating(false); }}
            >
              <span className={`coding-status-dot ${session.status}`} />
              <span><strong>{session.name}</strong><small>{session.machine_name} · {statusLabel(session.status)}</small></span>
            </button>
          ))}
          {!loading && !sessions.length && <p className="muted">No coding sessions yet.</p>}
        </aside>

        <section className="coding-workspace">
          {creating ? (
            <form className="card coding-create" onSubmit={createSession}>
              <div className="card-head"><h3>New persistent session</h3></div>
              <label>Session name<input required value={name} onChange={(event) => setName(event.target.value)} placeholder="Backend maintenance" /></label>
              <label>SSH machine<select required value={machineId} onChange={(event) => setMachineId(event.target.value)}><option value="">Choose a machine</option>{eligibleMachines.map((machine) => <option key={machine.id} value={machine.id}>{machine.name} — {machine.username}@{machine.host}</option>)}</select></label>
              {!eligibleMachines.length && <p className="muted">Enable “Allow Corv to execute commands” on an SSH machine first.</p>}
              <label>Remote project directory<input required value={remoteDirectory} onChange={(event) => setRemoteDirectory(event.target.value)} placeholder="/srv/my-project" /></label>
              <div className="coding-danger-note"><strong>Full-access session</strong><span>Codex will run without approvals or sandbox restrictions and receives the selected machine’s SSH access.</span></div>
              <div className="actions-row"><button type="button" className="ghost" onClick={() => setCreating(false)}>Cancel</button><button className="primary" disabled={busy || !machineId}>{busy ? "Creating…" : "Create session"}</button></div>
            </form>
          ) : selected ? (
            <>
              <div className="card coding-session-detail">
                <div className="card-head">
                  <div><p className="eyebrow">{statusLabel(selected.status)}</p><h3>{selected.name}</h3></div>
                  <div className="main-actions">
                    <button className="ghost coding-live-log-button" onClick={() => setShowLogs((value) => !value)}>{showLogs ? "Hide logs" : "Live logs"}</button>
                    {selected.status === "stopped" ? <button className="ghost" onClick={removeSession} disabled={busy}>Delete</button> : <button className="ghost danger" onClick={stopSession} disabled={busy}>Stop session</button>}
                    {!selected.direct_terminal_running && selected.status !== "stopped" && <button className="primary" onClick={openTerminal} disabled={busy || selected.status === "running" || !cliStatus?.authenticated}>Open Codex CLI</button>}
                  </div>
                </div>
                <div className="coding-facts"><span><small>Machine</small>{selected.machine_target}</span><span><small>Remote project</small>{selected.remote_working_directory}</span><span><small>Permissions</small>{selected.permission_mode}</span><span><small>Codex thread</small>{selected.codex_thread_id || "Created on first turn"}</span></div>
                {selected.last_error && <div className="alert">{selected.last_error}</div>}
              </div>

              {showLogs && <div className="card coding-live-logs">
                <div className="card-head"><div><p className="eyebrow">Real-time session output</p><h3>Coder and QA logs</h3></div><div className="coding-log-controls"><button type="button" className="ghost" onClick={() => setRawLogs((value) => !value)}>{rawLogs ? "Pretty view" : "Raw JSON"}</button><label className="coding-log-follow"><input type="checkbox" checked={followLogs} onChange={(event) => setFollowLogs(event.target.checked)} /> Follow output</label></div></div>
                <div className="coding-log-state"><i className={liveLogs?.active ? "active" : ""} />{liveLogs?.active ? "Receiving output" : "Session idle"}<span>{liveLogs?.updated_at ? `Updated ${new Date(liveLogs.updated_at).toLocaleTimeString()}` : "Connecting…"}</span></div>
                <div ref={logsRef} className="coding-log-viewport">{rawLogs ? <pre className="coding-log-raw">{liveLogs?.content || "Waiting for delegated session output…"}</pre> : <CodingLogViewer content={liveLogs?.content || "[waiting for output…]"} />}</div>
              </div>}

              {selected.pending_question && (
                <div className="card coding-decision">
                  <p className="eyebrow">Codex needs your decision</p>
                  <h3>{selected.pending_question}</h3>
                  {!!selected.pending_options.length && <div className="coding-options">{selected.pending_options.map((option) => <button className="ghost" type="button" key={option} onClick={() => submitDecision(option)} disabled={busy}>{option}</button>)}</div>}
                  <div className="coding-decision-input"><input value={decision} onChange={(event) => setDecision(event.target.value)} placeholder="Or give Corv your own decision…" /><button className="primary" onClick={() => submitDecision()} disabled={busy || !decision.trim()}>Continue</button></div>
                </div>
              )}

              {selected.direct_terminal_running && terminal ? (
                <div className="card coding-terminal">
                  <div className="card-head"><div><p className="eyebrow">Persistent direct control</p><h3>Codex CLI</h3></div><button className="ghost" onClick={closeTerminalSession} disabled={busy}>Close CLI</button></div>
                  <pre ref={terminalRef}>{terminal.output || "Codex is starting…"}</pre>
                  <form className="coding-terminal-input" onSubmit={sendTerminal}><span>›</span><input value={terminalInput} onChange={(event) => setTerminalInput(event.target.value)} placeholder="Type directly into Codex…" autoComplete="off" /><button className="primary" disabled={!terminalInput}>Send</button></form>
                  <div className="coding-terminal-keys"><button type="button" className="ghost" onClick={() => sendKey("Up")}>↑</button><button type="button" className="ghost" onClick={() => sendKey("Down")}>↓</button><button type="button" className="ghost" onClick={() => sendKey("Tab")}>Tab</button><button type="button" className="ghost" onClick={() => sendKey("Escape")}>Esc</button><button type="button" className="ghost danger" onClick={() => sendKey("C-c")}>Ctrl-C</button></div>
                </div>
              ) : selected.status !== "stopped" && (
                <form className="card coding-task" onSubmit={submitTask}>
                  <div className="card-head"><div><p className="eyebrow">Corv-managed work</p><h3>Delegate to Codex</h3></div></div>
                  <textarea rows={5} value={task} onChange={(event) => setTask(event.target.value)} placeholder="Describe a small one-turn change. Use Feature delegation below for larger work with explicit acceptance criteria and QA." disabled={!['ready', 'failed'].includes(selected.status)} />
                  <div className="actions-row"><span className="muted">The session and context remain available after each task.</span><button className="primary" disabled={busy || !['ready', 'failed'].includes(selected.status) || !task.trim() || !cliStatus?.authenticated}>{selected.status === "running" ? "Codex is working…" : "Delegate task"}</button></div>
                </form>
              )}

              {!selected.direct_terminal_running && <FeatureDelegationPanel session={selected} onSessionChange={() => refreshSelected(selected.id).catch(() => undefined)} />}

              <div className="card coding-history">
                <div className="card-head"><h3>Managed turn history</h3></div>
                {selected.turns.length ? selected.turns.map((turn) => <article key={turn.id} className={`coding-turn ${turn.status}`}><header><strong>{turn.source === "corv" ? "From Corv" : turn.source === "decision" ? "Decision" : turn.source === "feature" ? "Feature cycle" : "From coding module"}</strong><span>{turn.status.replace("_", " ")} · {new Date(turn.created_at).toLocaleString()}</span></header><p className="coding-turn-prompt">{turn.prompt}</p>{turn.summary && <p>{turn.summary}</p>}{turn.question && <p className="coding-turn-question">Decision: {turn.question}</p>}{turn.error && <p className="coding-turn-error">{turn.error}</p>}</article>) : <p className="muted">No managed Codex turns yet.</p>}
              </div>
            </>
          ) : <div className="card"><p className="muted">Create a coding session to begin.</p></div>}
        </section>
      </div>
    </div>
  );
}
