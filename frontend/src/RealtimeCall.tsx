import { useEffect, useRef, useState } from "react";
import {
  addCallTranscriptEntry,
  createCallSession,
  createRealtimeToken,
  fetchCallDelegationState,
  runCallAction,
  updateCallSession,
} from "./api";
import type { CallSession } from "./types";

type Props = { onSessionsChanged: () => void | Promise<void> };

export default function RealtimeCall({ onSessionsChanged }: Props) {
  const [goal, setGoal] = useState("Talk with Corv");
  const [session, setSession] = useState<CallSession | null>(null);
  const [status, setStatus] = useState<"idle" | "connecting" | "live">("idle");
  const [error, setError] = useState("");
  const [transcript, setTranscript] = useState<string[]>([]);
  const [pushToTalk, setPushToTalk] = useState(() => localStorage.getItem("corvPushToTalk") === "true");
  const [isTalking, setIsTalking] = useState(false);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const responseActiveRef = useRef(false);
  const pushToTalkRef = useRef(pushToTalk);
  const isTalkingRef = useRef(false);
  const delegationCursorRef = useRef("");
  const delegationWaitingRef = useRef(false);

  const addLine = (line: string) => setTranscript((items) => [...items.slice(-11), line]);

  function setMicEnabled(enabled: boolean) {
    streamRef.current?.getAudioTracks().forEach((track) => { track.enabled = enabled; });
  }

  function sendRealtimeEvent(event: Record<string, unknown>) {
    if (dcRef.current?.readyState === "open") dcRef.current.send(JSON.stringify(event));
  }

  function configureInputMode(pushToTalkEnabled: boolean) {
    sendRealtimeEvent({
      type: "session.update",
      session: { audio: { input: { turn_detection: pushToTalkEnabled ? null : { type: "server_vad" } } } },
    });
  }

  function stopTalking() {
    if (!isTalkingRef.current) return;
    isTalkingRef.current = false;
    setIsTalking(false);
    if (!pushToTalkRef.current) return;
    setMicEnabled(false);
    sendRealtimeEvent({ type: "input_audio_buffer.commit" });
    sendRealtimeEvent({ type: "response.create" });
  }

  function startTalking() {
    if (status !== "live" || !pushToTalkRef.current || isTalkingRef.current) return;
    isTalkingRef.current = true;
    setIsTalking(true);
    if (responseActiveRef.current) {
      sendRealtimeEvent({ type: "response.cancel" });
      responseActiveRef.current = false;
    }
    sendRealtimeEvent({ type: "input_audio_buffer.clear" });
    setMicEnabled(true);
  }

  function changePushToTalk(enabled: boolean) {
    if (isTalkingRef.current) stopTalking();
    pushToTalkRef.current = enabled;
    configureInputMode(enabled);
    setPushToTalk(enabled);
    localStorage.setItem("corvPushToTalk", String(enabled));
    isTalkingRef.current = false;
    setIsTalking(false);
    // Push-to-talk starts muted. Returning to open mic restores the existing behavior.
    if (streamRef.current) setMicEnabled(!enabled);
  }

  useEffect(() => {
    if (status !== "live" || !session) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const state = await fetchCallDelegationState(session.id, delegationCursorRef.current);
        if (cancelled) return;
        delegationCursorRef.current = state.cursor;
        if (state.waiting !== delegationWaitingRef.current) {
          delegationWaitingRef.current = state.waiting;
          sendRealtimeEvent({ type: "session.update", session: { instructions: state.waiting
            ? "A Codex delegation wait is active. Keep this call open and focused on waiting. Call perform_corv_action when the user asks to interrupt, resume, switch, list, or start another delegation."
            : "No delegation wait is active. Continue normally. New Codex delegations wait by default without asking first; the user can interrupt afterward." } });
        }
        for (const update of state.updates) {
          addLine(`Codex: ${update.content}`);
          sendRealtimeEvent({ type: "conversation.item.create", item: { type: "message", role: "system", content: [{ type: "input_text", text: `Tell the user this delegation update now: ${update.content}` }] } });
          sendRealtimeEvent({ type: "response.create" });
        }
      } catch { /* best effort while call remains live */ }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [status, session?.id]);

  useEffect(() => {
    const release = () => stopTalking();
    const onVisibility = () => { if (document.hidden) release(); };
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
    window.addEventListener("blur", release);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
      window.removeEventListener("blur", release);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  async function handleEvent(sessionId: string, raw: string) {
    let evt: any;
    try { evt = JSON.parse(raw); } catch { return; }
    if (evt.type === "response.created") {
      responseActiveRef.current = true;
      if (pushToTalkRef.current && isTalkingRef.current) {
        sendRealtimeEvent({ type: "response.cancel" });
        responseActiveRef.current = false;
        return;
      }
    }
    if (evt.type === "response.done") responseActiveRef.current = false;
    if (evt.type === "response.function_call_arguments.done" && evt.name === "perform_corv_action") {
      let instruction = "";
      try { instruction = JSON.parse(evt.arguments || "{}").instruction || ""; } catch {}
      addLine(`Corv is working on: ${instruction}`);
      let result: string;
      try { result = (await runCallAction(sessionId, instruction)).result; }
      catch (err: any) { result = `The action failed. ${err?.message || "Please try again."}`; }
      addLine(`Action result: ${result}`);
      dcRef.current?.send(JSON.stringify({
        type: "conversation.item.create",
        item: { type: "function_call_output", call_id: evt.call_id, output: result },
      }));
      dcRef.current?.send(JSON.stringify({ type: "response.create" }));
      return;
    }
    const text = evt.transcript || evt.text;
    if (evt.type === "conversation.item.input_audio_transcription.completed" && text) {
      addLine(`You: ${text}`);
      void addCallTranscriptEntry(sessionId, { role: "user", content: text });
    }
    if (evt.type === "response.audio_transcript.done" && text) {
      addLine(`Corv: ${text}`);
      void addCallTranscriptEntry(sessionId, { role: "assistant", content: text });
    }
  }

  async function start() {
    setError(""); setTranscript([]); setStatus("connecting");
    delegationCursorRef.current = ""; delegationWaitingRef.current = false;
    let createdSession: CallSession | null = null;
    try {
      const next = await createCallSession({ goal: goal.trim() || "Talk with Corv", origin: "web" });
      createdSession = next;
      await updateCallSession(next.id, { status: "in_call" });
      setSession({ ...next, status: "in_call" });
      const token: any = await createRealtimeToken(next.id, true);
      const secret = token?.value || token?.client_secret?.value || token?.client_secret || token?.ephemeral_key || token?.token;
      if (!secret) throw new Error("Realtime token was not returned");
      const pc = new RTCPeerConnection(); pcRef.current = pc;
      pc.ontrack = (event) => {
        if (audioRef.current) { audioRef.current.srcObject = event.streams[0]; void audioRef.current.play(); }
      };
      const local = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = local;
      local.getAudioTracks().forEach((track) => { track.enabled = !pushToTalkRef.current; });
      local.getTracks().forEach((track) => pc.addTrack(track, local));
      const dc = pc.createDataChannel("oai-events"); dcRef.current = dc;
      dc.onmessage = (event) => void handleEvent(next.id, event.data);
      const offer = await pc.createOffer(); await pc.setLocalDescription(offer);
      const response = await fetch("https://api.openai.com/v1/realtime/calls", {
        method: "POST",
        headers: { Authorization: `Bearer ${secret}`, "Content-Type": "application/sdp" },
        body: offer.sdp,
      });
      if (!response.ok) throw new Error(`Realtime connection failed with status ${response.status}`);
      await pc.setRemoteDescription({ type: "answer", sdp: await response.text() });
      dc.onopen = () => {
        setStatus("live");
        configureInputMode(pushToTalkRef.current);
        dc.send(JSON.stringify({ type: "response.create", response: {
          modalities: ["audio", "text"],
          instructions: `Start the call about ${next.goal}. Reply in one crisp sentence when possible; be specific and dry-witty. You can call perform_corv_action: try relevant actions and useful fallbacks before claiming you don't know, can't do it, or lack access.`,
        }}));
      };
      await onSessionsChanged();
    } catch (err: any) {
      setError(err?.message || "Could not start the call");
      if (createdSession) {
        await updateCallSession(createdSession.id, { status: "canceled" }).catch(() => undefined);
      }
      await stop(false);
    }
  }

  async function stop(markCompleted = true) {
    dcRef.current?.close(); dcRef.current = null;
    pcRef.current?.close(); pcRef.current = null;
    isTalkingRef.current = false; setIsTalking(false);
    streamRef.current?.getTracks().forEach((track) => track.stop()); streamRef.current = null;
    if (session && markCompleted) await updateCallSession(session.id, { status: "completed" }).catch(() => undefined);
    setSession(null); setStatus("idle"); await onSessionsChanged();
  }

  return <section className="realtime-call-card">
    <div className="realtime-call-heading">
      <div className="realtime-call-icon" aria-hidden="true">☎</div>
      <div>
        <h3>Talk with Corv</h3>
        <p>Start a live voice session and ask Corv to take action.</p>
      </div>
    </div>
    <div className="realtime-call-controls">
      <input aria-label="Call goal" value={goal} onChange={(e) => setGoal(e.target.value)} disabled={status !== "idle"} />
      {status === "idle" ? <button type="button" className="primary call-start-button" onClick={start}>Call Corv now</button> :
        <button type="button" className="call-end-button" onClick={() => void stop()}>End call</button>}
    </div>
    <div className="call-input-mode">
      <div>
        <strong>Microphone mode</strong>
        <span>{pushToTalk ? "Corv listens while held and only answers after you release." : "Open mic sends audio continuously during the call."}</span>
      </div>
      <button
        type="button"
        className={`mode-toggle ${pushToTalk ? "active" : ""}`}
        aria-pressed={pushToTalk}
        onClick={() => changePushToTalk(!pushToTalk)}
      >
        {pushToTalk ? "Push to talk on" : "Enable push to talk"}
      </button>
    </div>
    {status === "live" && pushToTalk && (
      <button
        type="button"
        className={`push-to-talk-button ${isTalking ? "talking" : ""}`}
        aria-label="Hold to talk to Corv"
        aria-pressed={isTalking}
        onPointerDown={(event) => {
          event.preventDefault();
          event.currentTarget.setPointerCapture?.(event.pointerId);
          startTalking();
        }}
        onPointerUp={stopTalking}
        onPointerCancel={stopTalking}
        onLostPointerCapture={stopTalking}
        onKeyDown={(event) => {
          if ((event.key === " " || event.key === "Enter") && !event.repeat) {
            event.preventDefault();
            startTalking();
          }
        }}
        onKeyUp={(event) => {
          if (event.key === " " || event.key === "Enter") {
            event.preventDefault();
            stopTalking();
          }
        }}
        onContextMenu={(event) => event.preventDefault()}
      >
        <span className="push-to-talk-icon" aria-hidden="true">●</span>
        <span>{isTalking ? "Talking — release to mute" : "Hold to talk"}</span>
        <small>Mouse, touch, Space, or Enter</small>
      </button>
    )}
    <div className={`call-state call-state-${status}`} aria-live="polite">
      <span className="call-state-dot" aria-hidden="true" />
      {status === "live"
        ? pushToTalk
          ? isTalking ? "Live with Corv — sending your voice" : "Live with Corv — microphone muted"
          : "Live with Corv — microphone open"
        : status === "connecting" ? "Connecting microphone" : "Ready to call"}
    </div>
    {error && <div className="alert">{error}</div>}
    {transcript.length > 0 && <div className="call-transcript" aria-live="polite">{transcript.map((line, i) => <div key={i}>{line}</div>)}</div>}
    <audio ref={audioRef} autoPlay />
  </section>;
}
