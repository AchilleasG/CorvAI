import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChat,
  fetchChats,
  fetchMessages,
  fetchJobs,
  sendText,
  sendVoice,
  renameChat,
  deleteChat,
  cancelJob,
  fetchJobMessagesDirect,
  fetchUsageRecent,
  fetchUsageSummary,
  fetchSettings,
  updateSettings,
} from "./api";
import { ChatListItem, Message, Job, UsageEvent, UsageSummary, SettingsPayload } from "./types";

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

type MessageBubbleProps = {
  msg: Message;
  jobLogMessages: Message[];
  jobLogAnchorId: string | null;
  showJobLog: boolean;
  onShowJobLog: (jobId: string) => void;
  onHideJobLog: () => void;
  isLastJobMessage: boolean;
};

function MessageBubble({
  msg,
  jobLogMessages,
  jobLogAnchorId,
  showJobLog,
  onShowJobLog,
  onHideJobLog,
  isLastJobMessage,
}: MessageBubbleProps) {
  const isAnchor = showJobLog && jobLogAnchorId === msg.job_id;
  return (
    <div className={`message ${msg.role}`} style={{ position: "relative" }}>
      <div className="message-meta">
        <RoleBadge role={msg.role} />
        {msg.created_at && <span className="timestamp">{new Date(msg.created_at).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}</span>}
      </div>
      <div className="message-text">{msg.text}</div>
      {msg.job_id && isLastJobMessage && (
        <div className="job-log-inline">
          <button
            type="button"
            className="ghost pill-action"
            onClick={() => onShowJobLog(msg.job_id!)}
          >
            View job log
          </button>
          {isAnchor && (
            <div className="job-log-popover">
              <div className="job-log-title">Job log</div>
              {jobLogMessages.length > 0 ? (
                <div className="job-log-entries">
                  {jobLogMessages.map((m) => (
                    <div key={m.id} className="job-log-row">
                      <div className="job-log-meta">
                        <span className={`badge badge-${m.role}`}>{m.role}</span>
                        {m.created_at && (
                          <span className="timestamp">
                            {new Date(m.created_at).toLocaleTimeString([], {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </span>
                        )}
                        {m.message_type && <span className="tag">{m.message_type}</span>}
                      </div>
                      <div className="job-log-text">{m.text}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="job-log-empty muted">No log entries yet.</div>
              )}
              <div style={{ textAlign: "right", marginTop: "0.35rem" }}>
                <button type="button" className="ghost pill-action" onClick={onHideJobLog}>
                  Close
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [chats, setChats] = useState<ChatListItem[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [usageRecent, setUsageRecent] = useState<UsageEvent[]>([]);
  const [usageSummary, setUsageSummary] = useState<UsageSummary | null>(null);
  const [input, setInput] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [settings, setSettings] = useState<SettingsPayload>({});
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [voiceSending, setVoiceSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [micReady, setMicReady] = useState(false);
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [selectedMicId, setSelectedMicId] = useState<string>("");
  const [openChatActionsId, setOpenChatActionsId] = useState<string | null>(null);
  const [jobLogMessages, setJobLogMessages] = useState<Message[]>([]);
  const [showJobLog, setShowJobLog] = useState(false);
  const [jobLogAnchorId, setJobLogAnchorId] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    (async () => {
      await refreshChats();
      try {
        const [recent, summary, settingsResp] = await Promise.all([
          fetchUsageRecent(20),
          fetchUsageSummary(7),
          fetchSettings(),
        ]);
        setUsageRecent(recent);
        setUsageSummary(summary);
        setSettings(settingsResp);
      } catch (err) {
        // ignore usage/settings load errors
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

  // Poll messages periodically so background job updates appear without reload.
  useEffect(() => {
    if (!activeChatId) return;
    const id = setInterval(() => {
      fetchMessages(activeChatId, true)
        .then((msgs) => setMessages(msgs))
        .catch(() => {});
    }, 3000);
    return () => clearInterval(id);
  }, [activeChatId]);

  async function loadJobLog(jobId: string) {
    try {
      const log = await fetchJobMessagesDirect(jobId);
      setJobLogMessages(log);
      setJobLogAnchorId(jobId);
    } catch {
      // swallow errors in hover log fetch
    }
  }

  async function handleCancelJob(jobId: string) {
    try {
      await cancelJob(jobId);
      const jobsData = await fetchJobs(activeChatId || undefined);
      setJobs(jobsData);
      if (activeChatId) {
        const msgs = await fetchMessages(activeChatId, false);
        setMessages(msgs);
      }
    } catch (err: any) {
      setError(err.message || "Failed to cancel job");
    }
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  useEffect(() => {
    (async () => {
      try {
        const [recent, summary] = await Promise.all([fetchUsageRecent(20), fetchUsageSummary(7)]);
        setUsageRecent(recent);
        setUsageSummary(summary);
      } catch {
        // ignore usage load errors
      }
    })();
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const [recent, summary] = await Promise.all([
          fetchUsageRecent(20),
          fetchUsageSummary(7),
        ]);
        setUsageRecent(recent);
        setUsageSummary(summary);
      } catch (err) {
        // ignore usage load errors in UI
      }
    })();
  }, []);

  const activeChat = useMemo(
    () => chats.find((c) => c.chat_id === activeChatId) || null,
    [chats, activeChatId],
  );
  const sortedChats = useMemo(() => {
    return [...chats].sort((a, b) => {
      const aTime = a.last_activity_at ? new Date(a.last_activity_at).getTime() : 0;
      const bTime = b.last_activity_at ? new Date(b.last_activity_at).getTime() : 0;
      return bTime - aTime;
    });
  }, [chats]);

  async function handleSaveSettings(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSavingSettings(true);
    setSettingsError(null);
    try {
      const formData = new FormData(e.currentTarget);
      const payload: SettingsPayload = {
        frontman_model: formData.get("frontman_model") as string,
        caller_model: formData.get("caller_model") as string,
        cache_mode: formData.get("cache_mode") as string,
      };
      const updated = await updateSettings(payload);
      setSettings(updated);
    } catch (err: any) {
      setSettingsError(err.message || "Failed to save settings");
    } finally {
      setSavingSettings(false);
    }
  }

  async function refreshChats(preferredActiveId?: string | null) {
    try {
      const data = await fetchChats();
      setChats(data);
      if (preferredActiveId && data.some((c) => c.chat_id === preferredActiveId)) {
        setActiveChatId(preferredActiveId);
        return data;
      }
      if (!activeChatId && data.length) {
        setActiveChatId(data[0].chat_id);
      } else if (activeChatId && !data.some((c) => c.chat_id === activeChatId)) {
        const fallbackId = data[0]?.chat_id || null;
        setActiveChatId(fallbackId);
        if (!fallbackId) {
          setMessages([]);
          setJobs([]);
        }
      } else if (!data.length) {
        setActiveChatId(null);
        setMessages([]);
        setJobs([]);
      }
      return data;
    } catch (err: any) {
      setError(err.message || "Failed to load chats");
      return [];
    }
  }

  async function ensureChat(): Promise<string> {
    if (activeChatId) return activeChatId;
    const created = await createChat("");
    await refreshChats(created.chat_id);
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
      await refreshChats(created.chat_id);
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
      await refreshChats(chatId);
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
      await refreshChats(chatId);
      setMessages(msgs);
      setJobs(jobsData);
    } catch (err: any) {
      setError(err.message || "Failed to send voice message");
    } finally {
      setVoiceSending(false);
    }
  }

  async function handleRenameChat(chat_id: string) {
    const chat = chats.find((c) => c.chat_id === chat_id);
    const currentLabel = chat ? formatChatLabel(chat) : "Chat";
    const nextName = window.prompt("Rename chat", currentLabel);
    if (nextName === null) return;
    try {
      await renameChat(chat_id, { nickname: nextName.trim() });
      await refreshChats(activeChatId === chat_id ? chat_id : undefined);
      setOpenChatActionsId(null);
    } catch (err: any) {
      setError(err.message || "Failed to rename chat");
    }
  }

  async function handleArchiveChat(chat_id: string) {
    const confirmArchive = window.confirm("Archive this chat? It will disappear from the list.");
    if (!confirmArchive) return;
    try {
      await renameChat(chat_id, { archived: true });
      await refreshChats(activeChatId === chat_id ? null : activeChatId);
      setOpenChatActionsId(null);
    } catch (err: any) {
      setError(err.message || "Failed to archive chat");
    }
  }

  async function handleDeleteChat(chat_id: string) {
    const confirmDelete = window.confirm("Delete this chat permanently?");
    if (!confirmDelete) return;
    try {
      await deleteChat(chat_id);
      await refreshChats(activeChatId === chat_id ? null : activeChatId);
      setOpenChatActionsId(null);
    } catch (err: any) {
      setError(err.message || "Failed to delete chat");
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
              {sortedChats.map((chat) => {
                const isActive = chat.chat_id === activeChatId;
                return (
                  <div key={chat.chat_id} className={`chat-pill ${isActive ? "active" : ""}`}>
                    <button
                      type="button"
                      className="chat-select"
                      onClick={() => setActiveChatId(chat.chat_id)}
                    >
                      <span>{formatChatLabel(chat)}</span>
                    </button>
                    <div className="chat-actions-row">
                      <button
                        type="button"
                        className="ghost pill-action"
                        onClick={() =>
                          setOpenChatActionsId((prev) =>
                            prev === chat.chat_id ? null : chat.chat_id,
                          )
                        }
                        aria-expanded={openChatActionsId === chat.chat_id}
                        aria-label="Chat actions"
                      >
                        Actions ▾
                      </button>
                      {openChatActionsId === chat.chat_id && (
                        <div className="chat-actions-menu">
                          <button
                            type="button"
                            className="ghost pill-action"
                            onClick={() => handleRenameChat(chat.chat_id)}
                          >
                            Rename
                          </button>
                          <button
                            type="button"
                            className="ghost pill-action"
                            onClick={() => handleArchiveChat(chat.chat_id)}
                          >
                            Archive
                          </button>
                          <button
                            type="button"
                            className="ghost pill-action danger"
                            onClick={() => handleDeleteChat(chat.chat_id)}
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
              {!chats.length && <p className="muted">No chats yet.</p>}
            </div>
          </>
        )}
      </aside>

      <main className="main">
        {showSettings ? (
          <div className="settings-panel">
            <header className="main-header">
              <div>
                <p className="eyebrow">Settings</p>
                <h2>Models & Usage</h2>
              </div>
              <div className="main-actions">
                <button className="ghost" onClick={() => setShowSettings(false)}>Back to chat</button>
              </div>
            </header>
            <div className="settings-grid">
              <div className="card">
                <h3>Model selection</h3>
                <form onSubmit={handleSaveSettings} className="settings-form">
                  {settingsError && <div className="error-banner">{settingsError}</div>}
                  <label className="field">
                    <span>Frontman model</span>
                    <input name="frontman_model" defaultValue={settings.frontman_model || "gpt-5.2"} />
                  </label>
                  <label className="field">
                    <span>Caller model</span>
                    <input name="caller_model" defaultValue={settings.caller_model || "gpt-5.2"} />
                  </label>
                  <label className="field">
                    <span>Cache mode</span>
                    <select name="cache_mode" defaultValue={settings.cache_mode || "off"}>
                      <option value="off">off</option>
                      <option value="frontman">frontman</option>
                      <option value="caller">caller</option>
                      <option value="all">all</option>
                    </select>
                  </label>
                  <div className="actions-row">
                    <button className="primary" type="submit" disabled={savingSettings}>
                      {savingSettings ? "Saving..." : "Save settings"}
                    </button>
                  </div>
                </form>
              </div>
              <div className="card">
                <h3>Usage (last 7 days)</h3>
                {usageSummary ? (
                  (() => {
                    const promptTokens = Number(usageSummary.totals.prompt_tokens ?? 0);
                    const cachedPromptTokens = Number(usageSummary.totals.cached_prompt_tokens ?? 0);
                    const completionTokens = Number(usageSummary.totals.completion_tokens ?? 0);
                    const computedTotalTokens = promptTokens + completionTokens;
                    const serverTotalTokens = Number(
                      usageSummary.totals.total_tokens ?? computedTotalTokens,
                    );
                    const totalMismatch = serverTotalTokens !== computedTotalTokens;
                    return (
                      <div className="usage-summary">
                        <div className="usage-totals">
                          <div>
                            <strong>Prompt</strong>{" "}
                            {promptTokens.toLocaleString()} ({cachedPromptTokens.toLocaleString()} cached)
                          </div>
                          <div><strong>Completion</strong> {completionTokens.toLocaleString()}</div>
                          <div>
                            <strong>Total</strong> {computedTotalTokens.toLocaleString()}
                            {totalMismatch && (
                              <span className="muted"> (server {serverTotalTokens.toLocaleString()})</span>
                            )}
                          </div>
                        </div>
                        <div className="usage-totals" style={{ marginTop: "0.35rem" }}>
                          <div><strong>Prompt $</strong> ${Number(usageSummary.totals.prompt_cost ?? 0).toFixed(4)}</div>
                          <div><strong>Completion $</strong> ${Number(usageSummary.totals.completion_cost ?? 0).toFixed(4)}</div>
                          <div><strong>Total $</strong> ${Number(usageSummary.totals.total_cost ?? 0).toFixed(4)}</div>
                        </div>
                      </div>
                    );
                  })()
                ) : (
                  <p className="muted">No usage yet.</p>
                )}
              </div>
              <div className="card full">
                <h3>Recent calls</h3>
                {usageRecent.length ? (
                  <div className="usage-table">
                    <div className="usage-row usage-head">
                      <span>When</span><span>Source</span><span>Model</span><span>Prompt</span><span>Cached</span><span>Completion</span><span>Total</span><span>$</span>
                    </div>
                    {usageRecent.map((u) => (
                      <div key={u.id} className="usage-row">
                        <span>{new Date(u.created_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}</span>
                        <span>{u.source}</span>
                        <span>{u.model}</span>
                        <span>{u.prompt_tokens.toLocaleString()}</span>
                        <span>{u.cached_prompt_tokens.toLocaleString()}</span>
                        <span>{u.completion_tokens.toLocaleString()}</span>
                        <span>{u.total_tokens.toLocaleString()}</span>
                        <span>${(u.total_cost || 0).toFixed(4)}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No recent usage.</p>
                )}
              </div>
            </div>
          </div>
        ) : (
          <>
            <header className="main-header">
              <div>
                <p className="eyebrow">Chat</p>
                <h2>{activeChat ? formatChatLabel(activeChat) : "Start a chat"}</h2>
                {jobs.some((j) => j.status === "running" || j.status === "waiting_on_user" || j.cancel_requested) && (
                  <div
                    className="job-indicator"
                    style={{ marginTop: "0.4rem", position: "relative" }}
                  >
                    <span className="pulse" aria-hidden />
                    {(() => {
                      const latestJob = [...jobs].sort((a, b) => {
                        const at = a.updated_at ? new Date(a.updated_at).getTime() : 0;
                        const bt = b.updated_at ? new Date(b.updated_at).getTime() : 0;
                        return bt - at;
                      })[0];
                      const statusText =
                        latestJob?.status === "completed"
                          ? "Last job completed"
                          : latestJob?.status === "failed"
                            ? "Last job failed"
                            : latestJob?.status === "waiting_on_user"
                              ? "Job waiting on you…"
                              : "Job in progress…";
                      return <span>{statusText}</span>;
                    })()}
                    {(() => {
                      const latestJob = [...jobs]
                        .sort((a, b) => {
                          const at = a.updated_at ? new Date(a.updated_at).getTime() : 0;
                          const bt = b.updated_at ? new Date(b.updated_at).getTime() : 0;
                          return bt - at;
                        })[0];
                      if (!latestJob) return null;
                      return (
                        <button
                          type="button"
                          className="ghost pill-action"
                          style={{ marginLeft: "0.5rem" }}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCancelJob(latestJob.id);
                          }}
                          disabled={
                            latestJob.cancel_requested ||
                            latestJob.status === "completed" ||
                            latestJob.status === "failed"
                          }
                          title={
                            latestJob.cancel_requested
                              ? "Cancel requested"
                              : latestJob.status === "completed" || latestJob.status === "failed"
                                ? "Job finished"
                                : "Cancel job"
                          }
                        >
                          {latestJob.cancel_requested
                            ? "Canceling…"
                            : latestJob.status === "completed"
                              ? "Done"
                              : latestJob.status === "failed"
                                ? "Failed"
                                : "Cancel job"}
                        </button>
                      );
                    })()}
                  </div>
            )}
          </div>
          <div className="header-actions">
            <button className="ghost" onClick={() => setShowSettings(true)}>
              Settings
            </button>
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
                  {(() => {
                    const visibleMessages = messages.filter(
                      (m) => m.message_type === undefined || m.message_type === "user_visible",
                    );
                    const lastJobIndex: Record<string, number> = {};
                    visibleMessages.forEach((m, idx) => {
                      if (m.job_id) {
                        lastJobIndex[m.job_id] = idx;
                      }
                    });
                    return visibleMessages.map((m, idx) => {
                      const isLastJobMessage = m.job_id ? lastJobIndex[m.job_id] === idx : false;
                      return (
                        <MessageBubble
                          key={m.id}
                          msg={m}
                          jobLogMessages={jobLogMessages}
                          jobLogAnchorId={jobLogAnchorId}
                          showJobLog={showJobLog}
                          isLastJobMessage={isLastJobMessage}
                          onShowJobLog={(jobId) => {
                            setShowJobLog(true);
                            setJobLogAnchorId(jobId);
                            loadJobLog(jobId);
                          }}
                          onHideJobLog={() => {
                            setShowJobLog(false);
                            setJobLogAnchorId(null);
                          }}
                        />
                      );
                    });
                  })()}
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
          </>
        )}
      </main>
    </div>
  );
}
