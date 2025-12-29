import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChat,
  fetchChats,
  fetchMessages,
  fetchJobs,
  sendText,
  sendVoice,
} from "./api";
import { ChatListItem, Message, Job } from "./types";

function formatChatLabel(chat: ChatListItem) {
  if (chat.chat_nickname && chat.chat_nickname.trim()) {
    return chat.chat_nickname.trim();
  }
  return `Chat ${chat.chat_id.slice(0, 6)}`;
}

function RoleBadge({ role }: { role: Message["role"] }) {
  const label = role === "assistant" ? "Corv" : role === "user" ? "You" : "System";
  return <span className={`badge badge-${role}`}>{label}</span>;
}

function MessageBubble({ msg }: { msg: Message }) {
  return (
    <div className={`message ${msg.role}`}>
      <div className="message-meta">
        <RoleBadge role={msg.role} />
        {msg.created_at && <span className="timestamp">{new Date(msg.created_at).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}</span>}
      </div>
      <div className="message-text">{msg.text}</div>
    </div>
  );
}

export default function App() {
  const [chats, setChats] = useState<ChatListItem[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [input, setInput] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [voiceSending, setVoiceSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [micReady, setMicReady] = useState(false);
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [selectedMicId, setSelectedMicId] = useState<string>("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchChats();
        setChats(data);
        if (data.length && !activeChatId) {
          setActiveChatId(data[0].chat_id);
        }
      } catch (err: any) {
        setError(err.message || "Failed to load chats");
      }
    })();
  }, []);

  useEffect(() => {
    if (!activeChatId) return;
    setLoadingMessages(true);
    fetchMessages(activeChatId, true)
      .then((msgs) => setMessages(msgs))
      .catch((err: any) => setError(err.message || "Failed to load messages"))
      .finally(() => setLoadingMessages(false));
    fetchJobs(activeChatId)
      .then((data) => setJobs(data))
      .catch(() => {});
  }, [activeChatId]);

  // Poll jobs periodically for active chat
  useEffect(() => {
    if (!activeChatId) return;
    const id = setInterval(() => {
      fetchJobs(activeChatId)
        .then((data) => setJobs(data))
        .catch(() => {});
    }, 5000);
    return () => clearInterval(id);
  }, [activeChatId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const activeChat = useMemo(
    () => chats.find((c) => c.chat_id === activeChatId) || null,
    [chats, activeChatId],
  );

  async function ensureChat(): Promise<string> {
    if (activeChatId) return activeChatId;
    const created = await createChat("");
    const nextChats = await fetchChats();
    setChats(nextChats);
    setActiveChatId(created.chat_id);
    return created.chat_id;
  }

  async function loadMics() {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const inputs = devices.filter((d) => d.kind === "audioinput");
      setMics(inputs);
      setSelectedMicId((prev) => {
        if (prev && inputs.some((d) => d.deviceId === prev)) return prev;
        return inputs[0]?.deviceId || "";
      });
    } catch (err) {
      console.warn("Could not enumerate devices", err);
    }
  }

  async function handleNewChat() {
    try {
      const created = await createChat("");
      const nextChats = await fetchChats();
      setChats(nextChats);
      setActiveChatId(created.chat_id);
      setMessages([]);
    } catch (err: any) {
      setError(err.message || "Could not create chat");
    }
  }

  async function handleSend(e?: React.FormEvent) {
    e?.preventDefault();
    if (!input.trim()) return;

    try {
      setSending(true);
      setError(null);

      const chatId = await ensureChat();

      await sendText(chatId, input.trim());
      setInput("");
      const [msgs, jobsData] = await Promise.all([
        fetchMessages(chatId, true),
        fetchJobs(chatId),
      ]);
      setMessages(msgs);
      setJobs(jobsData);
    } catch (err: any) {
      setError(err.message || "Failed to send");
    } finally {
      setSending(false);
    }
  }

  function cleanupStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  async function sendVoiceMessage(blob: Blob) {
    try {
      setVoiceSending(true);
      setError(null);
      const chatId = await ensureChat();
      await sendVoice(chatId, blob);
      const [msgs, jobsData] = await Promise.all([
        fetchMessages(chatId, true),
        fetchJobs(chatId),
      ]);
      setMessages(msgs);
      setJobs(jobsData);
    } catch (err: any) {
      setError(err.message || "Failed to send voice message");
    } finally {
      setVoiceSending(false);
    }
  }

  async function startVoiceRecording() {
    if (recording) return;
    if (!navigator.mediaDevices || typeof MediaRecorder === "undefined") {
      setError("Your browser does not support voice input");
      return;
    }
    try {
      const audioConstraints: MediaTrackConstraints =
        selectedMicId && selectedMicId !== "default"
          ? { deviceId: { exact: selectedMicId } }
          : {};
      const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
      streamRef.current = stream;
      audioChunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        setRecording(false);
        cleanupStream();
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        audioChunksRef.current = [];
        if (!blob.size) {
          setError("No audio captured");
          return;
        }
        await sendVoiceMessage(blob);
      };

      recorder.start();
      setRecording(true);
      setMicReady(true);
      loadMics();
    } catch (err: any) {
      cleanupStream();
      setError(err.message || "Microphone permission denied");
    }
  }

  function stopVoiceRecording() {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    } else {
      cleanupStream();
      setRecording(false);
    }
  }

  function toggleVoiceRecording() {
    if (recording) {
      stopVoiceRecording();
    } else {
      startVoiceRecording();
    }
  }

  async function requestMicPermission() {
    if (!navigator.mediaDevices) {
      setError("Microphone not supported in this browser");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
      setMicReady(true);
      setError(null);
      loadMics();
    } catch (err: any) {
      setMicReady(false);
      setError(err.message || "Microphone permission denied");
    }
  }

  useEffect(() => {
    if (!navigator.mediaDevices?.enumerateDevices) {
      return () => {
        recorderRef.current?.stop();
        cleanupStream();
      };
    }

    loadMics();
    const handler = () => {
      loadMics();
    };
    navigator.mediaDevices.addEventListener("devicechange", handler);

    return () => {
      navigator.mediaDevices.removeEventListener("devicechange", handler);
      recorderRef.current?.stop();
      cleanupStream();
    };
  }, []);

  return (
    <div className="page">
      <aside className={`sidebar ${sidebarOpen ? "open" : "closed"}`}>
        <div className="sidebar-header">
          <h1>Corv</h1>
          <button className="ghost" onClick={() => setSidebarOpen(!sidebarOpen)}>
            {sidebarOpen ? "Hide" : "Show"}
          </button>
        </div>
        {sidebarOpen && (
          <>
            <button className="primary full" onClick={handleNewChat}>
              + New chat
            </button>
            <div className="chat-list">
              {chats.map((chat) => {
                const isActive = chat.chat_id === activeChatId;
                return (
                  <button
                    key={chat.chat_id}
                    className={`chat-pill ${isActive ? "active" : ""}`}
                    onClick={() => setActiveChatId(chat.chat_id)}
                  >
                    <span>{formatChatLabel(chat)}</span>
                  </button>
                );
              })}
              {!chats.length && <p className="muted">No chats yet.</p>}
            </div>
          </>
        )}
      </aside>

      <main className="main">
        <header className="main-header">
          <div>
            <p className="eyebrow">Chat</p>
            <h2>{activeChat ? formatChatLabel(activeChat) : "Start a chat"}</h2>
            {jobs.some((j) => j.status === "running" || j.status === "waiting_on_user") && (
              <div className="job-indicator" style={{ marginTop: "0.4rem" }}>
                <span className="pulse" aria-hidden />
                <span>Job in progress…</span>
              </div>
            )}
          </div>
          <div className="header-actions">
            <button className="ghost" onClick={handleNewChat}>
              Start fresh
            </button>
          </div>
        </header>

        <section className="chat-window">
          {error && <div className="alert">{error}</div>}
          {loadingMessages ? (
            <div className="muted">Loading messages…</div>
          ) : (
            <div className="messages">
              {messages
                .filter((m) => m.message_type === undefined || m.message_type === "user_visible")
                .map((m) => (
                  <MessageBubble key={m.id} msg={m} />
                ))}
              <div ref={messagesEndRef} />
              {!messages.length && (
                <div className="muted empty">
                  <p>Ask Corv anything to begin.</p>
                </div>
              )}
            </div>
          )}
        </section>

        <form className="input-bar" onSubmit={handleSend}>
          <textarea
            placeholder="Send a message…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            disabled={sending}
          />
          <div className="input-actions">
            <button
              type="button"
              className={`ghost voice ${recording ? "recording" : ""}`}
              onClick={toggleVoiceRecording}
              disabled={sending || voiceSending}
            >
              {recording ? "Stop recording" : voiceSending ? "Sending voice…" : "Record voice"}
            </button>
            <button type="submit" className="primary" disabled={sending || !input.trim()}>
              {sending ? "Sending…" : "Send"}
            </button>
          </div>
          {mics.length > 0 && (
            <div className="muted" style={{ marginTop: "0.35rem", display: "flex", gap: "0.35rem", alignItems: "center" }}>
              <span>Mic:</span>
              <select
                className="mic-select"
                value={selectedMicId}
                onChange={(e) => setSelectedMicId(e.target.value)}
                disabled={recording}
              >
                {mics.map((mic, idx) => (
                  <option key={mic.deviceId} value={mic.deviceId}>
                    {mic.label || `Microphone ${idx + 1}`}
                  </option>
                ))}
              </select>
            </div>
          )}
          {!micReady && !recording && !voiceSending && (
            <div className="muted" style={{ marginTop: "0.35rem" }}>
              Having trouble?{" "}
              <button
                type="button"
                className="ghost"
                style={{ padding: 0, display: "inline", minWidth: "auto" }}
                onClick={requestMicPermission}
                disabled={sending}
              >
                Give mic permission
              </button>
            </div>
          )}
        </form>
      </main>
    </div>
  );
}
