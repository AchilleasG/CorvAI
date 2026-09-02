import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  createFeatureDelegation,
  fetchFeatureDelegation,
  fetchFeatureDelegations,
  fetchFeatureQaEvidence,
  fetchFiles,
  resumeFeatureDelegation,
  stopFeatureDelegation,
  uploadFile,
} from "./api";
import type { CodingSession, FeatureDelegation, FeatureQaRun, ManagedFile } from "./types";
import FileCard from "./FileCard";


const ACTIVE = new Set(["queued", "coding", "qa", "fixing"]);

function message(error: unknown): string {
  if (!(error instanceof Error)) return "Feature delegation failed";
  try {
    const body = JSON.parse(error.message);
    return body.detail || body.message || error.message;
  } catch {
    return error.message;
  }
}

function EvidenceGallery({ run }: { run: FeatureQaRun }) {
  const imageIndexes = useMemo(
    () => run.evidence.map((value, index) => ({ value, index })).filter(({ value }) => /\.(png|jpe?g|webp)$/i.test(value)),
    [run.evidence],
  );
  const [images, setImages] = useState<Array<{ index: number; url: string }>>([]);

  useEffect(() => {
    let disposed = false;
    const urls: string[] = [];
    Promise.all(imageIndexes.map(async ({ index }) => {
      const blob = await fetchFeatureQaEvidence(run.id, index);
      const url = URL.createObjectURL(blob);
      urls.push(url);
      return { index, url };
    })).then((items) => { if (!disposed) setImages(items); }).catch(() => undefined);
    return () => {
      disposed = true;
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [run.id, imageIndexes]);

  if (!images.length) return null;
  return <div className="feature-evidence">{images.map(({ index, url }) => (
    <a href={url} target="_blank" rel="noreferrer" key={index}>
      <img src={url} alt={`QA evidence ${index + 1}`} />
    </a>
  ))}</div>;
}


function DelegationArtifacts({ delegation }: { delegation: FeatureDelegation }) {
  const [files, setFiles] = useState<ManagedFile[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let disposed = false;
    const load = () => fetchFiles({ delegation_id: delegation.id })
      .then((response) => { if (!disposed) { setFiles(response.files); setError(""); } })
      .catch((err) => { if (!disposed) setError(message(err)); });
    load();
    const timer = ACTIVE.has(delegation.status) ? window.setInterval(load, 2500) : undefined;
    return () => { disposed = true; if (timer) window.clearInterval(timer); };
  }, [delegation.id, delegation.status]);

  if (!files.length && !error) return null;
  return <div className="feature-report delegation-artifacts">
    <strong>File artifacts</strong>
    {error && <p className="coding-turn-error">{error}</p>}
    {!!files.length && <div className="managed-file-grid">{files.map((file) => <FileCard key={file.id} file={file} />)}</div>}
  </div>;
}

export default function FeatureDelegationPanel({ session, onSessionChange }: {
  session: CodingSession;
  onSessionChange: () => void;
}) {
  const [items, setItems] = useState<FeatureDelegation[]>([]);
  const [selected, setSelected] = useState<FeatureDelegation | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [criteria, setCriteria] = useState("");
  const [inputFiles, setInputFiles] = useState<File[]>([]);
  const [qaEnabled, setQaEnabled] = useState(true);
  const [decision, setDecision] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sessionIdRef = useRef(session.id);
  const refreshVersion = useRef(0);
  sessionIdRef.current = session.id;

  async function refresh(preferred?: string) {
    const requestedSessionId = session.id;
    const version = ++refreshVersion.current;
    const response = await fetchFeatureDelegations(requestedSessionId);
    if (version !== refreshVersion.current || sessionIdRef.current !== requestedSessionId) return;
    setItems(response.delegations);
    const preferredBelongsToSession = preferred
      ? response.delegations.some((item) => item.id === preferred)
      : false;
    const id = preferredBelongsToSession ? preferred : response.delegations[0]?.id;
    if (!id) {
      setSelected(null);
      return;
    }
    const item = await fetchFeatureDelegation(id);
    if (
      version === refreshVersion.current
      && sessionIdRef.current === requestedSessionId
      && item.session_id === requestedSessionId
    ) setSelected(item);
  }

  useEffect(() => {
    ++refreshVersion.current;
    setItems([]);
    setSelected(null);
    setShowForm(false);
    refresh().catch((err) => setError(message(err)));
  }, [session.id]);

  useEffect(() => {
    if (!selected || !ACTIVE.has(selected.status)) return;
    const timer = window.setInterval(() => {
      const requestedSessionId = session.id;
      fetchFeatureDelegation(selected.id).then((item) => {
        if (sessionIdRef.current !== requestedSessionId || item.session_id !== requestedSessionId) return;
        setSelected(item);
        setItems((current) => current.map((entry) => entry.id === item.id ? item : entry));
        onSessionChange();
      }).catch(() => undefined);
    }, 1800);
    return () => window.clearInterval(timer);
  }, [selected?.id, selected?.status]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const acceptance = criteria.split("\n").map((item) => item.replace(/^\s*[-*\d.)]+\s*/, "").trim()).filter(Boolean);
    if (!acceptance.length) return setError("Add at least one acceptance criterion, one per line.");
    setBusy(true);
    setError("");
    try {
      const uploaded = await Promise.all(inputFiles.map((file) => uploadFile(file, { session_id: session.id, tags: ["feature-input"] })));
      const item = await createFeatureDelegation(session.id, {
        title: title.trim(), description: description.trim(), acceptance_criteria: acceptance,
        qa_enabled: qaEnabled, max_iterations: 6, file_ids: uploaded.map((file) => file.id),
      });
      setTitle(""); setDescription(""); setCriteria(""); setInputFiles([]); setShowForm(false);
      await refresh(item.id);
      onSessionChange();
    } catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }

  async function resume(value?: string, mode: "auto" | "qa" | "coding" = "auto") {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const item = await resumeFeatureDelegation(selected.id, (value ?? decision).trim(), mode);
      setDecision(""); setSelected(item); await refresh(item.id); onSessionChange();
    } catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }

  async function stop() {
    if (!selected || !window.confirm(`Stop feature delegation “${selected.title}”?`)) return;
    setBusy(true);
    try { const item = await stopFeatureDelegation(selected.id); setSelected(item); await refresh(item.id); onSessionChange(); }
    catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }

  const latestQa = selected?.qa_runs[0];
  return <div className="card feature-delegations">
    <div className="card-head">
      <div><p className="eyebrow">Autonomous delivery loop</p><h3>Feature delegations</h3></div>
      <button type="button" className="primary" onClick={() => setShowForm((value) => !value)} disabled={!['ready', 'failed'].includes(session.status)}>Delegate feature</button>
    </div>
    <div className="feature-explainer">
      <div className="feature-explainer-copy">
        <strong>From specification to verified result</strong>
        <span>Corv keeps the work moving across multiple Codex turns and only pauses when your decision is genuinely needed.</span>
      </div>
      <div className="feature-flow" aria-label="Feature delegation workflow">
        <span><i>1</i><small>Coder</small>Build</span>
        <b aria-hidden>→</b>
        <span><i>2</i><small>QA bot</small>Verify</span>
        <b aria-hidden>→</b>
        <span><i>3</i><small>Automatic</small>Fix or finish</span>
      </div>
    </div>
    {error && <div className="alert">{error}</div>}
    {showForm && <form className="feature-form" onSubmit={submit}>
      <label>Feature name<input required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Reliable password reset" /></label>
      <label>What should be built?<textarea required rows={4} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe the behavior, constraints, and useful context in detail." /></label>
      <label>Acceptance criteria <small>one per line</small><textarea required rows={5} value={criteria} onChange={(event) => setCriteria(event.target.value)} placeholder={"A user can request a reset link\nExpired links show a useful error\nThe complete flow works in the browser"} /></label>
      <label className="coding-file-picker">Attach reference files<input hidden type="file" multiple onChange={(event) => { setInputFiles((items) => [...items, ...Array.from(event.target.files || [])]); event.target.value = ""; }} /></label>
      {!!inputFiles.length && <div className="input-attachments">{inputFiles.map((file, index) => <span key={`${file.name}-${index}`}>{file.name}<button type="button" onClick={() => setInputFiles((items) => items.filter((_, i) => i !== index))}>×</button></span>)}</div>}
      <label className="feature-qa-toggle"><input type="checkbox" checked={qaEnabled} onChange={(event) => setQaEnabled(event.target.checked)} /><span><strong>Run independent QA bot</strong><small>Runs tests and browser checks with screenshots when appropriate, then automatically requests fixes until it passes.</small></span></label>
      <div className="actions-row"><button type="button" className="ghost" onClick={() => setShowForm(false)}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Starting…" : "Start delegation"}</button></div>
    </form>}
    {!!items.length && <div className="feature-tabs">{items.map((item) => <button type="button" key={item.id} className={selected?.id === item.id ? "active" : ""} onClick={() => { const requestedSessionId = session.id; fetchFeatureDelegation(item.id).then((detail) => { if (sessionIdRef.current === requestedSessionId && detail.session_id === requestedSessionId) setSelected(detail); }).catch((err) => setError(message(err))); }}><strong>{item.title}</strong><span>{item.status.replace("_", " ")}</span></button>)}</div>}
    {selected && <section className="feature-detail">
      <div className="feature-progress"><span className={`feature-status ${selected.status}`}>{selected.status.replace("_", " ")}</span><span>Cycle {selected.current_iteration}/{selected.max_iterations}</span><span>{selected.qa_enabled ? "QA enabled" : "QA skipped"}</span>{ACTIVE.has(selected.status) && <button type="button" className="ghost danger" onClick={stop} disabled={busy}>Stop</button>}</div>
      <h4>{selected.title}</h4>
      <p>{selected.description}</p>
      <ol>{selected.acceptance_criteria.map((criterion) => <li key={criterion}>{criterion}</li>)}</ol>
      <DelegationArtifacts delegation={selected} />
      {selected.implementation_summary && <div className="feature-report"><strong>Coder report</strong><p>{selected.implementation_summary}</p></div>}
      {latestQa && <div className={`feature-report qa-${latestQa.status}`}><strong>QA cycle {latestQa.iteration}: {latestQa.status}</strong>{latestQa.summary && <p>{latestQa.summary}</p>}{!!latestQa.failures.length && <ul>{latestQa.failures.map((failure) => <li key={failure}>{failure}</li>)}</ul>}<EvidenceGallery run={latestQa} />{latestQa.error && <p className="coding-turn-error">{latestQa.error}</p>}</div>}
      {selected.last_error && <div className="alert">{selected.last_error}</div>}
      {(selected.status === "needs_input" || selected.status === "stopped") && <div className="feature-question"><strong>{selected.status === "stopped" ? "Delegation stopped" : "Decision needed"}</strong><p>{selected.pending_question || "Continue this delegation from its saved coder and QA threads."}</p>{selected.can_retry_qa && <div className="coding-options"><button type="button" className="primary" onClick={() => resume(undefined, "qa")} disabled={busy}>Retry QA only</button><button type="button" className="ghost" onClick={() => resume(decision || "Review the QA blocker and make any required application changes.", "coding")} disabled={busy}>Return to coder</button></div>}{!!selected.pending_options.length && <div className="coding-options">{selected.pending_options.map((option) => <button type="button" className="ghost" key={option} onClick={() => resume(option)} disabled={busy}>{option}</button>)}</div>}<div className="coding-decision-input"><input value={decision} onChange={(event) => setDecision(event.target.value)} placeholder={selected.can_retry_qa ? "Optional instruction for the QA retry…" : "Optional continuation instruction…"} /><button type="button" className="primary" onClick={() => resume()} disabled={busy}>{selected.can_retry_qa ? "Retry QA" : "Resume delegation"}</button></div></div>}
    </section>}
    {!items.length && !showForm && <p className="muted">No feature delegations in this session yet.</p>}
  </div>;
}
