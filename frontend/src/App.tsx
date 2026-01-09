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
  fetchCalendarCombined,
  fetchScheduledTasks,
  createScheduledTask,
  updateScheduledTask,
  fetchScheduledTaskRuns,
} from "./api";
import {
  ChatListItem,
  Message,
  Job,
  UsageEvent,
  UsageSummary,
  SettingsPayload,
  CombinedCalendar,
  ScheduledTask,
  ScheduledTaskRun,
} from "./types";

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

function MicIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm-7-3a1 1 0 0 1 2 0 5 5 0 0 0 10 0 1 1 0 1 1 2 0 7 7 0 0 1-6 6.93V21a1 1 0 0 1-2 0v-2.07A7 7 0 0 1 5 12Z" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M3.2 4.1c-.2-.7.5-1.3 1.2-1.1l16.8 6c.9.3.9 1.6 0 1.9l-16.8 6c-.7.2-1.4-.4-1.2-1.1L5.2 12 3.2 4.1Z" />
      <path d="M7 9v6l7-3-7-3Z" />
    </svg>
  );
}

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
  const [showCalendar, setShowCalendar] = useState(false);
  const [showScheduler, setShowScheduler] = useState(false);
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
  const [authed, setAuthed] = useState<boolean>(() => !!localStorage.getItem("appAccessToken"));
  const [authError, setAuthError] = useState<string | null>(null);
  const [passwordInput, setPasswordInput] = useState("");
  const [showMicSettings, setShowMicSettings] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const [calendarData, setCalendarData] = useState<CombinedCalendar | null>(null);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [scheduledTasks, setScheduledTasks] = useState<ScheduledTask[]>([]);
  const [schedulerError, setSchedulerError] = useState<string | null>(null);
  const [schedulerLoading, setSchedulerLoading] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [taskRuns, setTaskRuns] = useState<ScheduledTaskRun[]>([]);
  const [taskRunsLoading, setTaskRunsLoading] = useState(false);

  function handleAuthError(err: any): boolean {
    const status = err?.status;
    const msg = (err?.message || "").toString().toLowerCase();
    if (status === 401 || msg.includes("unauthorized")) {
      localStorage.removeItem("appAccessToken");
      setAuthed(false);
      setAuthError("Access password required or invalid. Please sign in again.");
      return true;
    }
    return false;
  }

  useEffect(() => {
    (async () => {
      if (!authed) return;
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
        if (handleAuthError(err)) return;
      }
    })();
  }, [authed]);

  useEffect(() => {
    if (!authed) return;
    if (!showCalendar) return;
    setCalendarLoading(true);
    setCalendarError(null);
    fetchCalendarCombined({ days: 14 })
      .then((data) => setCalendarData(data))
      .catch((err: any) => {
        if (handleAuthError(err)) return;
        setCalendarError(err.message || "Failed to load calendar");
      })
      .finally(() => setCalendarLoading(false));
  }, [authed, showCalendar]);

  useEffect(() => {
    if (!authed) return;
    if (!showScheduler) return;
    refreshScheduledTasks();
  }, [authed, showScheduler]);

  useEffect(() => {
    if (!authed) return;
    if (!activeChatId) return;
    setLoadingMessages(true);
    fetchMessages(activeChatId, true)
      .then((msgs) => setMessages(msgs))
      .catch((err: any) => {
        if (handleAuthError(err)) return;
        setError(err.message || "Failed to load messages");
      })
      .finally(() => setLoadingMessages(false));
    fetchJobs(activeChatId)
      .then((data) => setJobs(data))
      .catch((err) => {
        handleAuthError(err);
      });
  }, [activeChatId, authed]);

  // Poll jobs periodically for active chat
  useEffect(() => {
    if (!authed) return;
    if (!activeChatId) return;
    const id = setInterval(() => {
      fetchJobs(activeChatId)
        .then((data) => setJobs(data))
        .catch((err) => {
          handleAuthError(err);
        });
    }, 5000);
    return () => clearInterval(id);
  }, [activeChatId, authed]);

  // Poll messages periodically so background job updates appear without reload.
  useEffect(() => {
    if (!authed) return;
    if (!activeChatId) return;
    const id = setInterval(() => {
      fetchMessages(activeChatId, true)
        .then((msgs) => setMessages(msgs))
        .catch((err) => {
          handleAuthError(err);
        });
    }, 3000);
    return () => clearInterval(id);
  }, [activeChatId, authed]);

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
      if (handleAuthError(err)) return;
      setError(err.message || "Failed to cancel job");
    }
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

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
        max_function_result_chars: Number(formData.get("max_function_result_chars") || 0) || undefined,
      };
    const updated = await updateSettings(payload);
    setSettings(updated);
  } catch (err: any) {
    if (handleAuthError(err)) return;
    setSettingsError(err.message || "Failed to save settings");
  } finally {
    setSavingSettings(false);
  }
}

  async function refreshScheduledTasks() {
    try {
      setSchedulerLoading(true);
      setSchedulerError(null);
      const data = await fetchScheduledTasks();
      setScheduledTasks(data);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSchedulerError(err.message || "Failed to load scheduled tasks");
    } finally {
      setSchedulerLoading(false);
    }
  }

  async function handleCreateScheduledTask(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSchedulerError(null);
    const formData = new FormData(e.currentTarget);
    const prompt = (formData.get("prompt") as string) || "";
    const recurrence = (formData.get("recurrence") as string) || "once";
    const startRaw = (formData.get("start_at") as string) || "";
    if (!prompt.trim()) {
      setSchedulerError("Prompt is required");
      return;
    }
    try {
      const payload: { prompt: string; recurrence: string; start_at?: string } = {
        prompt: prompt.trim(),
        recurrence,
      };
      if (startRaw) {
        payload.start_at = new Date(startRaw).toISOString();
      }
      await createScheduledTask(payload);
      e.currentTarget.reset();
      await refreshScheduledTasks();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSchedulerError(err.message || "Failed to create scheduled task");
    }
  }

  async function handleToggleScheduledTask(task: ScheduledTask) {
    const nextStatus = task.status === "paused" ? "active" : "paused";
    try {
      await updateScheduledTask(task.id, { status: nextStatus });
      await refreshScheduledTasks();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSchedulerError(err.message || "Failed to update scheduled task");
    }
  }

  async function handleLoadRuns(taskId: string) {
    try {
      setTaskRunsLoading(true);
      setTaskRuns([]);
      setSelectedTaskId(taskId);
      const runs = await fetchScheduledTaskRuns(taskId);
      setTaskRuns(runs);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSchedulerError(err.message || "Failed to load task runs");
    } finally {
      setTaskRunsLoading(false);
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
      if (handleAuthError(err)) return [];
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
      if (handleAuthError(err)) return;
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
      if (handleAuthError(err)) return;
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
      if (handleAuthError(err)) return;
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
      if (handleAuthError(err)) return;
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
      if (handleAuthError(err)) return;
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
      if (handleAuthError(err)) return;
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

  if (!authed) {
    return (
      <div className="auth-gate">
        <div className="card auth-card">
          <h2>Corv Access</h2>
          <p className="muted small">Enter the shared access password to continue.</p>
          {authError && <div className="error-banner">{authError}</div>}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!passwordInput.trim()) {
                setAuthError("Password required");
                return;
              }
              localStorage.setItem("appAccessToken", passwordInput.trim());
              setAuthError(null);
              setAuthed(true);
            }}
            className="settings-form"
            style={{ marginTop: "0.75rem" }}
          >
            <label className="field">
              <span>Password</span>
              <input
                type="password"
                value={passwordInput}
                onChange={(e) => setPasswordInput(e.target.value)}
                autoFocus
              />
            </label>
            <div className="actions-row">
              <button className="primary" type="submit">
                Enter
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

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
            <button
              className="ghost full"
              onClick={() => setShowMicSettings((v) => !v)}
              style={{ marginTop: "0.35rem" }}
            >
              {showMicSettings ? "Hide mic settings" : "Mic settings"}
            </button>
            <button
              className="ghost full"
              onClick={() => {
                localStorage.removeItem("appAccessToken");
                setAuthed(false);
                setAuthError(null);
              }}
              style={{ marginTop: "0.35rem" }}
            >
              Log out
            </button>
            <div className="chat-list">
              {sortedChats.map((chat) => {
                const isActive = chat.chat_id === activeChatId;
                return (
                  <div key={chat.chat_id} className={`chat-pill ${isActive ? "active" : ""}`}>
                    <button
                      type="button"
                      className="chat-select"
                      onClick={() => {
                        setActiveChatId(chat.chat_id);
                        setShowSettings(false);
                        setShowCalendar(false);
                        setShowScheduler(false);
                      }}
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
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Models</p>
                    <h3>Model selection</h3>
                    <p className="muted small">Tune how Corv routes requests between Frontman and Caller.</p>
                  </div>
                  <div className="pill-stack">
                    <span className="pill">Frontman: {settings.frontman_model || "gpt-5.2"}</span>
                    <span className="pill">Caller: {settings.caller_model || "gpt-5.2"}</span>
                    <span className="pill">Cache: {settings.cache_mode || "off"}</span>
                    <span className="pill">
                      Max result: {settings.max_function_result_chars ?? "6000"} chars
                    </span>
                  </div>
                </div>
                <form onSubmit={handleSaveSettings} className="settings-form">
                  {settingsError && <div className="error-banner">{settingsError}</div>}
                  <div className="form-grid">
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
                    <label className="field">
                      <span>Max function result chars</span>
                      <input
                        name="max_function_result_chars"
                        type="number"
                        min={500}
                        step={100}
                        defaultValue={settings.max_function_result_chars ?? 6000}
                      />
                    </label>
                  </div>
                  <div className="actions-row">
                    <button className="primary" type="submit" disabled={savingSettings}>
                      {savingSettings ? "Saving..." : "Save settings"}
                    </button>
                  </div>
                </form>
              </div>
              <div className="card">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Usage</p>
                    <h3>Last 7 days</h3>
                    <p className="muted small">Token footprint and spend, including cached hits.</p>
                  </div>
                </div>
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
                      <div className="stat-grid">
                        <div className="stat-card">
                          <p className="muted small">Prompt tokens</p>
                          <div className="stat-value">{promptTokens.toLocaleString()}</div>
                          <div className="stat-sub">Cached {cachedPromptTokens.toLocaleString()}</div>
                        </div>
                        <div className="stat-card">
                          <p className="muted small">Completion tokens</p>
                          <div className="stat-value">{completionTokens.toLocaleString()}</div>
                          <div className="stat-sub">Generated responses</div>
                        </div>
                        <div className="stat-card">
                          <p className="muted small">Total tokens</p>
                          <div className="stat-value">
                            {computedTotalTokens.toLocaleString()}
                            {totalMismatch && (
                              <span className="muted small"> (server {serverTotalTokens.toLocaleString()})</span>
                            )}
                          </div>
                          <div className="stat-sub">Prompt + completion</div>
                        </div>
                        <div className="stat-card">
                          <p className="muted small">Cost</p>
                          <div className="stat-value">${Number(usageSummary.totals.total_cost ?? 0).toFixed(4)}</div>
                          <div className="stat-sub">
                            Prompt ${Number(usageSummary.totals.prompt_cost ?? 0).toFixed(4)} · Completion $
                            {Number(usageSummary.totals.completion_cost ?? 0).toFixed(4)}
                          </div>
                        </div>
                      </div>
                    );
                  })()
                ) : (
                  <p className="muted">No usage yet.</p>
                )}
              </div>
              <div className="card full">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Recent</p>
                    <h3>Recent calls</h3>
                    <p className="muted small">Most recent 20 usage events.</p>
                  </div>
                </div>
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
        ) : showCalendar ? (
          <div className="settings-panel">
            <header className="main-header">
              <div>
                <p className="eyebrow">Calendar</p>
                <h2>Hard + Soft Events</h2>
              </div>
              <div className="main-actions">
                <button className="ghost" onClick={() => setShowCalendar(false)}>Back to chat</button>
                <button
                  className="ghost"
                  onClick={() => {
                    setCalendarLoading(true);
                    setCalendarError(null);
                    fetchCalendarCombined({ days: 14 })
                      .then((data) => setCalendarData(data))
                      .catch((err: any) => setCalendarError(err.message || "Failed to load calendar"))
                      .finally(() => setCalendarLoading(false));
                  }}
                >
                  Refresh
                </button>
              </div>
            </header>
            {calendarError && <div className="alert">{calendarError}</div>}
            {calendarLoading && <div className="muted">Loading calendar…</div>}
            {!calendarLoading && calendarData && (
              <div className="calendar-grid">
                <div className="card">
                  <div className="card-head">
                    <div>
                      <p className="eyebrow">Planned</p>
                      <h3>Next two weeks</h3>
                      <p className="muted small">
                        Window {new Date(calendarData.window_start).toLocaleDateString()} –{" "}
                        {new Date(calendarData.window_end).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                  <div className="calendar-list">
                    {[...calendarData.hard_events.map((e) => ({ ...e, type: "hard" as const })), ...calendarData.soft_slots.map((s) => ({
                      id: s.id,
                      title: s.title,
                      start: s.start,
                      end: s.end,
                      status: s.status,
                      type: "soft" as const,
                      rationale: s.rationale,
                      deferral_count: s.deferral_count,
                      promoted: s.promoted,
                    }))].sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime()).map((item) => {
                      const start = new Date(item.start).toLocaleString();
                      const end = new Date(item.end).toLocaleString();
                      const isSoft = item.type === "soft";
                      return (
                        <div key={`${item.type}-${item.id}`} className="cal-row">
                          <div className={`cal-badge ${isSoft ? "soft" : "hard"}`}>
                            {isSoft ? "Soft" : "Hard"}
                          </div>
                          <div className="cal-body">
                            <div className="cal-title">
                              {item.title}
                              {isSoft && item.promoted && <span className="pill" style={{ marginLeft: "0.5rem" }}>Promoted</span>}
                            </div>
                            <div className="cal-time">{start} → {end}</div>
                            {"status" in item && item.status && (
                              <div className="cal-meta muted small">
                                Status: {item.status}
                                {"deferral_count" in item && item.deferral_count ? ` · Deferrals: ${item.deferral_count}` : ""}
                              </div>
                            )}
                            {"rationale" in item && item.rationale && (
                              <div className="cal-note muted small">{item.rationale}</div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                    {!calendarData.hard_events.length && !calendarData.soft_slots.length && (
                      <div className="muted">No events scheduled.</div>
                    )}
                  </div>
                </div>
                <div className="card">
                  <div className="card-head">
                    <div>
                      <p className="eyebrow">Unscheduled soft</p>
                      <h3>Need a slot</h3>
                    </div>
                  </div>
                  {calendarData.soft_events_unscheduled.length ? (
                    <div className="calendar-list">
                      {calendarData.soft_events_unscheduled.map((se) => (
                        <div key={se.id} className="cal-row">
                          <div className="cal-badge soft">Soft</div>
                          <div className="cal-body">
                            <div className="cal-title">{se.title}</div>
                            <div className="cal-meta muted small">
                              Priority {se.priority}
                              {se.soft_deadline && ` · Soft deadline ${new Date(se.soft_deadline).toLocaleDateString()}`}
                              {se.hard_deadline && ` · Hard deadline ${new Date(se.hard_deadline).toLocaleDateString()}`}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">No unscheduled soft events.</p>
                  )}
                </div>
              </div>
            )}
          </div>
        ) : showScheduler ? (
          <div className="settings-panel">
            <header className="main-header">
              <div>
                <p className="eyebrow">Scheduler</p>
                <h2>Scheduled tasks</h2>
              </div>
              <div className="main-actions">
                <button className="ghost" onClick={() => setShowScheduler(false)}>Back to chat</button>
              </div>
            </header>
            <div className="settings-grid">
              <div className="card">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">New</p>
                    <h3>Create task</h3>
                    <p className="muted small">Tasks run without user clarification.</p>
                  </div>
                </div>
                <form onSubmit={handleCreateScheduledTask} className="settings-form">
                  {schedulerError && <div className="error-banner">{schedulerError}</div>}
                  <label className="field">
                    <span>Prompt</span>
                    <textarea name="prompt" rows={5} placeholder="Describe the task..." />
                  </label>
                  <label className="field">
                    <span>Start time (local)</span>
                    <input name="start_at" type="datetime-local" />
                  </label>
                  <label className="field">
                    <span>Recurrence</span>
                    <select name="recurrence" defaultValue="once">
                      <option value="once">once</option>
                      <option value="daily">daily</option>
                      <option value="weekly">weekly</option>
                      <option value="monthly">monthly</option>
                    </select>
                  </label>
                  <div className="actions-row">
                    <button className="primary" type="submit">Schedule</button>
                  </div>
                </form>
              </div>
              <div className="card">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Tasks</p>
                    <h3>Upcoming</h3>
                  </div>
                  <button className="ghost" onClick={refreshScheduledTasks} disabled={schedulerLoading}>
                    {schedulerLoading ? "Refreshing…" : "Refresh"}
                  </button>
                </div>
                {scheduledTasks.length ? (
                  <div className="calendar-list">
                    {scheduledTasks.map((task) => (
                      <div key={task.id} className="cal-row">
                        <div style={{ flex: 1 }}>
                          <div className="cal-title">{task.prompt.slice(0, 80)}</div>
                          <div className="cal-time muted">
                            Next: {task.next_run_at ? new Date(task.next_run_at).toLocaleString() : "—"}
                          </div>
                          <div className="muted small">Recurrence: {task.recurrence}</div>
                        </div>
                        <div className="chat-actions">
                          <button className="ghost pill-action" onClick={() => handleLoadRuns(task.id)}>
                            Logs
                          </button>
                          {task.status !== "completed" && (
                            <button className="ghost pill-action" onClick={() => handleToggleScheduledTask(task)}>
                              {task.status === "paused" ? "Resume" : "Pause"}
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No scheduled tasks yet.</p>
                )}
              </div>
              <div className="card full">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Runs</p>
                    <h3>Task logs</h3>
                  </div>
                </div>
                {taskRunsLoading ? (
                  <div className="muted">Loading runs…</div>
                ) : selectedTaskId ? (
                  taskRuns.length ? (
                    <div className="calendar-list">
                      {taskRuns.map((run) => (
                        <div key={run.id} className="cal-row">
                          <div style={{ flex: 1 }}>
                            <div className="cal-title">{run.status.toUpperCase()}</div>
                            <div className="cal-time muted">
                              {run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
                            </div>
                            {run.summary && <div className="muted small">{run.summary}</div>}
                            {run.error_summary && <div className="alert">{run.error_summary}</div>}
                            {run.log_entries?.length ? (
                              <div className="messages" style={{ marginTop: "0.5rem" }}>
                                {run.log_entries.map((entry) => (
                                  <div key={entry.id} className="message tool">
                                    <div className="message-meta">
                                      <span className="badge badge-system">{entry.role}</span>
                                      {entry.created_at && (
                                        <span className="timestamp">
                                          {new Date(entry.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                                        </span>
                                      )}
                                      <span className="tag">{entry.level}</span>
                                    </div>
                                    <div className="message-text">{entry.message}</div>
                                  </div>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">No runs yet.</p>
                  )
                ) : (
                  <p className="muted">Select a task to view its logs.</p>
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
                <button
                  className="ghost"
                  onClick={() => {
                    setShowSettings(false);
                    setShowCalendar(true);
                    setShowScheduler(false);
                  }}
                >
                  Calendar
                </button>
                <button
                  className="ghost"
                  onClick={() => {
                    setShowCalendar(false);
                    setShowSettings(false);
                    setShowScheduler(true);
                  }}
                >
                  Scheduler
                </button>
                <button
                  className="ghost"
                  onClick={() => {
                    setShowCalendar(false);
                    setShowSettings(true);
                    setShowScheduler(false);
                  }}
                >
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
                  className={`icon-btn ${recording ? "recording" : ""}`}
                  onClick={toggleVoiceRecording}
                  disabled={sending || voiceSending}
                  aria-label={recording ? "Stop recording" : "Record voice"}
                  title={recording ? "Stop recording" : voiceSending ? "Sending voice…" : "Record voice"}
                >
                  {recording ? <span className="icon-square" /> : <MicIcon />}
                </button>
                <button
                  type="submit"
                  className="icon-btn send-btn"
                  disabled={sending || !input.trim()}
                  aria-label="Send message"
                  title="Send"
                >
                  {sending ? "…" : <SendIcon />}
                </button>
              </div>
              {showMicSettings && mics.length > 0 && (
                <div className="muted mic-row">
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
                  {!micReady && !recording && !voiceSending && (
                    <button
                      type="button"
                      className="ghost"
                      style={{ padding: "0.25rem 0.5rem", minWidth: "auto" }}
                      onClick={requestMicPermission}
                      disabled={sending}
                    >
                      Give mic permission
                    </button>
                  )}
                </div>
              )}
            </form>
          </>
        )}
      </main>
    </div>
  );
}
