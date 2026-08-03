import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  connectSshMachine,
  createSshMachine,
  deleteSshMachine,
  disconnectSshMachine,
  closeSshTerminalSession,
  createSshTerminalSession,
  fetchSshCommandHistory,
  fetchSshMachines,
  fetchSshTerminalSessions,
  runSshTerminalCommand,
  updateSshMachine,
} from "./api";
import type { SshCommandRecord, SshCommandResult, SshMachine, SshMachineInput, SshTerminalSession } from "./types";
import "./ssh.css";


const emptyDraft: SshMachineInput = {
  name: "",
  host: "",
  port: 22,
  username: "",
  auth_type: "private_key",
  password: "",
  private_key: "",
  passphrase: "",
  allow_ai_commands: false,
  connect_timeout_seconds: 15,
  command_timeout_seconds: 120,
  keepalive_seconds: 30,
  notes: "",
};

function errorText(error: unknown): string {
  if (!(error instanceof Error)) return "Something went wrong";
  try {
    const parsed = JSON.parse(error.message);
    return parsed.detail || error.message;
  } catch {
    return error.message;
  }
}

export default function SshPanel() {
  const [machines, setMachines] = useState<SshMachine[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<SshMachineInput>(emptyDraft);
  const [editing, setEditing] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [command, setCommand] = useState("");
  const [terminalSessions, setTerminalSessions] = useState<SshTerminalSession[]>([]);
  const [activeTerminalId, setActiveTerminalId] = useState<string | null>(null);
  const [resultsBySession, setResultsBySession] = useState<Record<string, SshCommandResult[]>>({});
  const [history, setHistory] = useState<SshCommandRecord[]>([]);
  const terminalOutputRef = useRef<HTMLDivElement | null>(null);

  const selected = useMemo(
    () => machines.find((machine) => machine.id === selectedId) || null,
    [machines, selectedId],
  );
  const activeTerminal = useMemo(
    () => terminalSessions.find((session) => session.id === activeTerminalId) || null,
    [terminalSessions, activeTerminalId],
  );
  const results = activeTerminalId ? resultsBySession[activeTerminalId] || [] : [];

  useEffect(() => {
    const output = terminalOutputRef.current;
    if (output) output.scrollTop = output.scrollHeight;
  }, [activeTerminalId, results.length]);

  async function refresh(preferredId?: string | null) {
    setLoading(true);
    try {
      const response = await fetchSshMachines();
      setMachines(response.machines);
      setSelectedId((currentId) => {
        const nextId = preferredId === undefined ? currentId : preferredId;
        return nextId && response.machines.some((machine) => machine.id === nextId)
          ? nextId
          : response.machines[0]?.id || null;
      });
      setError(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const timer = window.setInterval(() => refresh(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setHistory([]);
      return;
    }
    fetchSshCommandHistory(selectedId)
      .then((response) => setHistory(response.commands))
      .catch(() => undefined);
    fetchSshTerminalSessions(selectedId)
      .then((response) => {
        setTerminalSessions(response.sessions);
        setActiveTerminalId((current) =>
          current && response.sessions.some((session) => session.id === current)
            ? current
            : response.sessions[0]?.id || null,
        );
      })
      .catch(() => {
        setTerminalSessions([]);
        setActiveTerminalId(null);
      });
  }, [selectedId]);

  function beginCreate() {
    setDraft({ ...emptyDraft });
    setSelectedId(null);
    setEditingId(null);
    setEditing(true);
  }

  function beginEdit(machine: SshMachine) {
    setDraft({
      name: machine.name,
      host: machine.host,
      port: machine.port,
      username: machine.username,
      auth_type: machine.auth_type,
      allow_ai_commands: machine.allow_ai_commands,
      connect_timeout_seconds: machine.connect_timeout_seconds,
      command_timeout_seconds: machine.command_timeout_seconds,
      keepalive_seconds: machine.keepalive_seconds,
      notes: machine.notes,
      password: "",
      private_key: "",
      passphrase: "",
    });
    setSelectedId(machine.id);
    setEditingId(machine.id);
    setEditing(true);
  }

  async function saveMachine(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      let saved: SshMachine;
      if (editingId) {
        const payload: Partial<SshMachineInput> = { ...draft };
        if (!payload.password) delete payload.password;
        if (!payload.private_key) delete payload.private_key;
        if (!payload.passphrase) delete payload.passphrase;
        saved = await updateSshMachine(editingId, payload);
      } else {
        saved = await createSshMachine(draft);
      }
      setEditing(false);
      await refresh(saved.id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  async function toggleConnection() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      if (selected.connected) await disconnectSshMachine(selected.id);
      else await connectSshMachine(selected.id);
      await refresh(selected.id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function executeCommand(event: FormEvent) {
    event.preventDefault();
    if (!selected || !activeTerminalId || !command.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await runSshTerminalCommand(selected.id, activeTerminalId, command.trim());
      setResultsBySession((current) => ({
        ...current,
        [activeTerminalId]: [...(current[activeTerminalId] || []), result],
      }));
      setTerminalSessions((current) => current.map((session) =>
        session.id === activeTerminalId
          ? { ...session, cwd: result.cwd || session.cwd, last_used_at: Date.now() / 1000 }
          : session,
      ));
      setCommand("");
      const response = await fetchSshCommandHistory(selected.id);
      setHistory(response.commands);
      await refresh(selected.id);
    } catch (err) {
      setError(errorText(err));
      const response = await fetchSshCommandHistory(selected.id).catch(() => null);
      if (response) setHistory(response.commands);
    } finally {
      setBusy(false);
    }
  }

  async function createTerminal() {
    if (!selected) return;
    const name = window.prompt("Session name", `Terminal ${terminalSessions.length + 1}`)?.trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      const session = await createSshTerminalSession(selected.id, name);
      setTerminalSessions((current) => [...current, session]);
      setActiveTerminalId(session.id);
      await refresh(selected.id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function closeTerminal(sessionId: string) {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await closeSshTerminalSession(selected.id, sessionId);
      const remaining = terminalSessions.filter((session) => session.id !== sessionId);
      setTerminalSessions(remaining);
      setActiveTerminalId((current) => current === sessionId ? remaining[0]?.id || null : current);
      setResultsBySession((current) => {
        const next = { ...current };
        delete next[sessionId];
        return next;
      });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function removeMachine() {
    if (!selected || !window.confirm(`Delete SSH machine “${selected.name}”?`)) return;
    setBusy(true);
    try {
      await deleteSshMachine(selected.id);
      setTerminalSessions([]);
      setActiveTerminalId(null);
      setResultsBySession({});
      await refresh(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function resetHostKey() {
    if (!selected || !window.confirm("Forget this machine’s pinned host key? The next connection will trust and pin the key it receives.")) return;
    setBusy(true);
    setError(null);
    try {
      await updateSshMachine(selected.id, { reset_host_key: true });
      await refresh(selected.id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-panel ssh-panel">
      <header className="main-header">
        <div>
          <p className="eyebrow">Remote systems</p>
          <h2>SSH connections</h2>
        </div>
        <div className="main-actions">
          <button className="ghost" onClick={() => refresh()} disabled={loading}>Refresh</button>
          <button className="primary" onClick={beginCreate}>Add machine</button>
        </div>
      </header>

      {error && <div className="alert">{error}</div>}
      <div className="ssh-layout">
        <aside className="card ssh-machine-list">
          <div className="card-head"><h3>Machines</h3></div>
          {loading && !machines.length ? <p className="muted">Loading…</p> : machines.map((machine) => (
            <button
              type="button"
              key={machine.id}
              className={`ssh-machine-row ${selectedId === machine.id ? "active" : ""}`}
              onClick={() => { setSelectedId(machine.id); setEditing(false); setTerminalSessions([]); setActiveTerminalId(null); }}
            >
              <span className={`ssh-status ${machine.connected ? "online" : "offline"}`} />
              <span>
                <strong>{machine.name}</strong>
                <small>{machine.username}@{machine.host}:{machine.port}</small>
              </span>
            </button>
          ))}
          {!loading && !machines.length && <p className="muted">No machines saved yet.</p>}
        </aside>

        <section className="ssh-workspace">
          {editing ? (
            <form className="card ssh-form" onSubmit={saveMachine}>
              <div className="card-head"><h3>{editingId ? "Edit machine" : "Add machine"}</h3></div>
              <div className="ssh-form-grid">
                <label>Name<input required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
                <label>Host<input required value={draft.host} onChange={(e) => setDraft({ ...draft, host: e.target.value })} /></label>
                <label>Port<input required type="number" min="1" max="65535" value={draft.port} onChange={(e) => setDraft({ ...draft, port: Number(e.target.value) })} /></label>
                <label>Username<input required value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} /></label>
                <label>Authentication<select value={draft.auth_type} onChange={(e) => setDraft({ ...draft, auth_type: e.target.value as SshMachineInput["auth_type"] })}><option value="private_key">Private key</option><option value="password">Password</option><option value="agent">SSH agent</option></select></label>
                {draft.auth_type === "password" && <label>Password<input type="password" placeholder={editingId && selected?.has_credentials ? "Leave blank to keep current" : "Password"} value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} /></label>}
                {draft.auth_type === "private_key" && <><label className="wide">Private key<textarea rows={8} placeholder={editingId && selected?.has_credentials ? "Leave blank to keep current key" : "Paste an OpenSSH private key"} value={draft.private_key} onChange={(e) => setDraft({ ...draft, private_key: e.target.value })} /></label><label>Key passphrase<input type="password" placeholder="Optional" value={draft.passphrase} onChange={(e) => setDraft({ ...draft, passphrase: e.target.value })} /></label></>}
                <label>Connect timeout (seconds)<input type="number" min="1" value={draft.connect_timeout_seconds} onChange={(e) => setDraft({ ...draft, connect_timeout_seconds: Number(e.target.value) })} /></label>
                <label>Command timeout (seconds)<input type="number" min="1" value={draft.command_timeout_seconds} onChange={(e) => setDraft({ ...draft, command_timeout_seconds: Number(e.target.value) })} /></label>
                <label>Keepalive interval (seconds)<input type="number" min="1" value={draft.keepalive_seconds} onChange={(e) => setDraft({ ...draft, keepalive_seconds: Number(e.target.value) })} /></label>
                <label className="wide">Notes<textarea rows={3} value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
                <label className="ssh-check wide"><input type="checkbox" checked={draft.allow_ai_commands} onChange={(e) => setDraft({ ...draft, allow_ai_commands: e.target.checked })} /><span>Allow Corv to execute commands on this machine</span></label>
              </div>
              <div className="actions-row"><button type="button" className="ghost" onClick={() => setEditing(false)}>Cancel</button><button className="primary" disabled={saving}>{saving ? "Saving…" : "Save machine"}</button></div>
            </form>
          ) : selected ? (
            <>
              <div className="card ssh-machine-detail">
                <div className="card-head"><div><p className="eyebrow">{selected.connected ? "Connected" : "Disconnected"}</p><h3>{selected.name}</h3></div><div className="main-actions"><button className="ghost" onClick={() => beginEdit(selected)}>Edit</button><button className="ghost" onClick={removeMachine} disabled={busy}>Delete</button><button className={selected.connected ? "ghost" : "primary"} onClick={toggleConnection} disabled={busy}>{selected.connected ? "Disconnect" : "Connect"}</button></div></div>
                <div className="ssh-facts"><span><small>Target</small>{selected.username}@{selected.host}:{selected.port}</span><span><small>Authentication</small>{selected.auth_type.replace("_", " ")}</span><span><small>Corv access</small>{selected.allow_ai_commands ? "Enabled" : "Disabled"}</span><span><small>Host key</small>{selected.host_key_fingerprint || "Captured on first connection"}</span></div>
                {selected.host_key_fingerprint && <button type="button" className="ghost pill-action" onClick={resetHostKey} disabled={busy}>Reset pinned host key</button>}
                {selected.notes && <p className="muted">{selected.notes}</p>}
                {selected.last_error && <div className="alert">Last error: {selected.last_error}</div>}
              </div>
              <form className="card ssh-terminal" onSubmit={executeCommand}>
                <div className="card-head"><div><p className="eyebrow">Persistent shells</p><h3>Terminal sessions</h3></div><button type="button" className="primary" onClick={createTerminal} disabled={busy}>New session</button></div>
                {terminalSessions.length ? (
                  <div className="ssh-session-tabs">
                    {terminalSessions.map((session) => (
                      <div key={session.id} className={`ssh-session-tab ${session.id === activeTerminalId ? "active" : ""}`}>
                        <button type="button" className="ssh-session-tab-main" onClick={() => setActiveTerminalId(session.id)}>
                          <span className="ssh-status online" />
                          <span className="ssh-session-label">
                            <strong className="ssh-session-name">{session.name}</strong>
                            <small className="ssh-session-path">{session.cwd || "Shell ready"}</small>
                          </span>
                        </button>
                        <button type="button" className="ssh-session-close" title="Close session" onClick={() => closeTerminal(session.id)}>×</button>
                      </div>
                    ))}
                  </div>
                ) : <p className="muted">Create a session to open a persistent remote shell.</p>}
                <div className="ssh-command-line"><span>$</span><input value={command} onChange={(e) => setCommand(e.target.value)} placeholder={activeTerminal ? "cd /var/log" : "Create a session first"} autoComplete="off" disabled={!activeTerminal} /><button className="primary" disabled={busy || !activeTerminal || !command.trim()}>{busy ? "Running…" : "Run"}</button></div>
                <div className="ssh-output" ref={terminalOutputRef}>
                  {results.length ? results.map((result, index) => <div className="ssh-result" key={`${result.duration_ms}-${index}`}><div className="ssh-result-head"><code>{result.cwd || "$"} $ {result.command}</code><span>exit {result.exit_status} · {result.duration_ms} ms</span></div>{result.stdout && <pre>{result.stdout}</pre>}{result.stderr && <pre className="stderr">{result.stderr}</pre>}{result.truncated && <p className="muted small">Output was truncated.</p>}</div>) : <p className="muted">{activeTerminal ? "This shell keeps its directory, environment variables, and activated environments between commands." : "No active shell session."}</p>}
                </div>
              </form>
              <div className="card"><div className="card-head"><h3>Command history</h3></div>{history.length ? <div className="ssh-history">{history.map((item) => <div key={item.id}><code>{item.command}</code><span>{item.source} · {item.error_summary || `exit ${item.exit_status ?? "—"}`} · {new Date(item.created_at).toLocaleString()}</span></div>)}</div> : <p className="muted">No commands recorded.</p>}</div>
            </>
          ) : (
            <div className="card"><p className="muted">Add a machine to begin.</p></div>
          )}
        </section>
      </div>
    </div>
  );
}
