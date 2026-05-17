import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChat,
  createStudyCourse,
  updateStudyCourse,
  deleteStudyCourse,
  fetchChats,
  fetchStudyCourses,
  fetchStudyExams,
  fetchStudyMaterials,
  fetchStudyTopics,
  fetchMessages,
  fetchJobs,
  sendText,
  sendVoice,
  renameChat,
  deleteChat,
  cancelJob,
  fetchJobEvents,
  fetchJobMessagesDirect,
  fetchUsageRecent,
  fetchUsageSummary,
  fetchSettings,
  updateSettings,
  fetchCalendarCombined,
  createSoftEvent,
  updateSoftEvent,
  fetchSoftEvent,
  promoteSoftSlot,
  replanCalendar,
  createStudyTopic,
  createStudyExam,
  updateStudyExam,
  deleteStudyExam,
  updateStudyTopic,
  deleteStudyTopic,
  fetchScheduledTasks,
  createScheduledTask,
  updateScheduledTask,
  fetchScheduledTaskRuns,
  fetchInboxMessages,
  markMessageRead,
  fetchCallSessions,
  createCallSession,
  updateCallSession,
  uploadStudyMaterial,
  restartStudyJob,
} from "./api";
import {
  ChatListItem,
  Message,
  Job,
  JobEvent,
  UsageEvent,
  UsageSummary,
  SettingsPayload,
  CombinedCalendar,
  SoftEventDetail,
  ScheduledTask,
  ScheduledTaskRun,
  StudyCourse,
  StudyExam,
  StudyMaterial,
  StudyTopic,
  UserMessage,
  CallSession,
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

type SoftEventDraft = {
  id: string;
  title: string;
  description: string;
  notes: string;
  preferred_duration_minutes: string;
  min_duration_minutes: string;
  soft_deadline: string;
  hard_deadline: string;
  frequency: string;
  deferral_limit: string;
  priority: string;
  status: SoftEventDetail["status"];
};

type SoftEventMode = "create" | "edit";
type StudyOutputModalKind = "converted" | "solved" | "theory";

type StudyMaterialKind = "lecture" | "worksheet" | "assignment" | "exam" | "other";
type StudyMaterialInputMode = "file" | "text";
const STUDY_PREVIEW_COUNT = 3;
const STUDY_TOPIC_STATUS_OPTIONS = ["not_started", "in_progress", "review", "mastered"] as const;

function formatTopicStatus(status: string) {
  return status
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function topicStatusTone(status: string): "pending" | "processing" | "processed" {
  if (status === "mastered") return "processed";
  if (status === "in_progress" || status === "review") return "processing";
  return "pending";
}

function formatDateTime(value?: string | null) {
  if (!value) return "";
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toLocalInputValue(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function toIsoValue(value: string) {
  if (!value.trim()) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString();
}

function formatMaterialKind(kind: string) {
  return kind
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function asStringList(value: unknown): string[] {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? [trimmed] : [];
  }
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => String(item).trim())
    .filter(Boolean);
}

function parseTopicSummaryLines(summary: string): string[] {
  const raw = String(summary || "").trim();
  if (!raw) return [];

  // Normalize escaped line breaks from API text payloads.
  const normalized = raw.replace(/\\n/g, "\n");
  const normalizedNoLeadBullet = normalized.replace(/^[-*•]+\s*/, "");

  const cleanLine = (line: string) =>
    line
      .trim()
      .replace(/^[-*•]+\s*/, "")
      .replace(/^[\[\]"'`\s]+/, "")
      .replace(/[\[\]"'`\s]+$/, "")
      .replace(/^[-*•]+\s*/, "")
      .replace(/^\d+[.)]\s*/, "")
      .replace(/^[\[\]"'`\s]+/, "")
      .replace(/[\[\]"'`\s]+$/, "")
      .trim();

  // Handle serialized list strings like "['item a', 'item b']".
  const listLike = normalizedNoLeadBullet.match(/^\s*\[([\s\S]*)\]\s*$/);
  if (listLike) {
    const body = listLike[1]
      .replace(/',\s*'/g, "\n")
      .replace(/",\s*"/g, "\n")
      .replace(/',\s*"/g, "\n")
      .replace(/",\s*'/g, "\n")
      .replace(/,\s*'/g, "\n")
      .replace(/,\s*"/g, "\n");

    const listLines = body
      .split(/\n+/)
      .map(cleanLine)
      .filter(Boolean);

    if (listLines.length) return listLines;
  }

  const lines = normalizedNoLeadBullet
    .split(/\n+/)
    .map(cleanLine)
    .filter(Boolean);

  if (lines.length) return lines;

  // Fallback: split a single-line bullet stream (e.g. "• a • b • c").
  return normalized
    .split(/[•\u2022]+/)
    .map((part) => part.trim())
    .filter(Boolean);
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
  const [showStudy, setShowStudy] = useState(false);
  const [showCalendar, setShowCalendar] = useState(false);
  const [showScheduler, setShowScheduler] = useState(false);
  const [showMessages, setShowMessages] = useState(false);
  const [showCalls, setShowCalls] = useState(false);
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
  const studyFileInputRef = useRef<HTMLInputElement | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const [calendarData, setCalendarData] = useState<CombinedCalendar | null>(null);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [replanLoading, setReplanLoading] = useState(false);
  const [promoteLoadingId, setPromoteLoadingId] = useState<string | null>(null);
  const [softEventModalOpen, setSoftEventModalOpen] = useState(false);
  const [softEventLoading, setSoftEventLoading] = useState(false);
  const [softEventError, setSoftEventError] = useState<string | null>(null);
  const [softEventDraft, setSoftEventDraft] = useState<SoftEventDraft | null>(null);
  const [softEventMode, setSoftEventMode] = useState<SoftEventMode>("edit");
  const [scheduledTasks, setScheduledTasks] = useState<ScheduledTask[]>([]);
  const [schedulerError, setSchedulerError] = useState<string | null>(null);
  const [schedulerLoading, setSchedulerLoading] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [taskRuns, setTaskRuns] = useState<ScheduledTaskRun[]>([]);
  const [taskRunsLoading, setTaskRunsLoading] = useState(false);
  const [messagesInbox, setMessagesInbox] = useState<UserMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [callSessions, setCallSessions] = useState<CallSession[]>([]);
  const [callsLoading, setCallsLoading] = useState(false);
  const [callsError, setCallsError] = useState<string | null>(null);
  const [studyCourses, setStudyCourses] = useState<StudyCourse[]>([]);
  const [studyTopics, setStudyTopics] = useState<StudyTopic[]>([]);
  const [studyExams, setStudyExams] = useState<StudyExam[]>([]);
  const [studyMaterials, setStudyMaterials] = useState<StudyMaterial[]>([]);
  const [studyJobs, setStudyJobs] = useState<Job[]>([]);
  const [studySelectedJobId, setStudySelectedJobId] = useState<string | null>(null);
  const [studyJobEvents, setStudyJobEvents] = useState<JobEvent[]>([]);
  const [studyJobLogsLoading, setStudyJobLogsLoading] = useState(false);
  const [studyLoading, setStudyLoading] = useState(false);
  const [studySaving, setStudySaving] = useState(false);
  const [studyError, setStudyError] = useState<string | null>(null);
  const [studyCourseTitle, setStudyCourseTitle] = useState("");
  const [studyCourseCode, setStudyCourseCode] = useState("");
  const [studyCourseDescription, setStudyCourseDescription] = useState("");
  const [studySelectedCourseId, setStudySelectedCourseId] = useState<string | null>(null);
  const [studySelectedMaterialId, setStudySelectedMaterialId] = useState<string | null>(null);
  const [studyTopicStatusDrafts, setStudyTopicStatusDrafts] = useState<Record<string, string>>({});
  const [studyLessonTitle, setStudyLessonTitle] = useState("");
  const [studyLessonDescription, setStudyLessonDescription] = useState("");
  const [studyLessonEffort, setStudyLessonEffort] = useState("60");
  const [studyLessonWeight, setStudyLessonWeight] = useState("1.0");
  const [studyExamTitle, setStudyExamTitle] = useState("");
  const [studyExamKind, setStudyExamKind] = useState("other");
  const [studyExamDate, setStudyExamDate] = useState("");
  const [studyExamWeight, setStudyExamWeight] = useState("1.0");
  const [studyMaterialTitle, setStudyMaterialTitle] = useState("");
  const [studyMaterialKind, setStudyMaterialKind] = useState<StudyMaterialKind>("lecture");
  const [studyMaterialInputMode, setStudyMaterialInputMode] = useState<StudyMaterialInputMode>("file");
  const [studyMaterialNotes, setStudyMaterialNotes] = useState("");
  const [studyMaterialFile, setStudyMaterialFile] = useState<File | null>(null);
  const [studyFileDragOver, setStudyFileDragOver] = useState(false);
  const [studyMaterialText, setStudyMaterialText] = useState("");
  const [studyLessonDetailId, setStudyLessonDetailId] = useState<string | null>(null);
  const [studyOutputModalKind, setStudyOutputModalKind] = useState<StudyOutputModalKind | null>(null);
  const [showCreateCourseModal, setShowCreateCourseModal] = useState(false);
  const [showCreateLessonModal, setShowCreateLessonModal] = useState(false);
  const [showCreateExamModal, setShowCreateExamModal] = useState(false);
  const [showCreateMaterialModal, setShowCreateMaterialModal] = useState(false);
  const [studyShowAllCourses, setStudyShowAllCourses] = useState(false);
  const [studyShowAllLessons, setStudyShowAllLessons] = useState(false);
  const [studyShowAllExams, setStudyShowAllExams] = useState(false);
  const [studyShowAllMaterials, setStudyShowAllMaterials] = useState(false);
  const [studyShowAllJobs, setStudyShowAllJobs] = useState(false);

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
    if (!showStudy) return;
    refreshStudyData();
  }, [authed, showStudy, studySelectedCourseId]);

  useEffect(() => {
    if (!authed) return;
    if (!showStudy) return;
    const id = setInterval(() => {
      refreshStudyData();
    }, 5000);
    return () => clearInterval(id);
  }, [authed, showStudy, studySelectedCourseId]);

  useEffect(() => {
    if (!authed) return;
    if (!showCalendar) return;
    refreshCalendar();
  }, [authed, showCalendar]);

  useEffect(() => {
    if (!authed) return;
    if (!showScheduler) return;
    refreshScheduledTasks();
  }, [authed, showScheduler]);

  useEffect(() => {
    if (!authed) return;
    if (!showMessages) return;
    refreshInboxMessages();
  }, [authed, showMessages]);

  useEffect(() => {
    if (!authed) return;
    if (!showCalls) return;
    refreshCallSessions();
  }, [authed, showCalls]);

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
  const selectedStudyCourse = useMemo(
    () => studyCourses.find((course) => course.id === studySelectedCourseId) || null,
    [studyCourses, studySelectedCourseId],
  );
  const selectedStudyMaterial = useMemo(
    () => studyMaterials.find((material) => material.id === studySelectedMaterialId) || null,
    [studyMaterials, studySelectedMaterialId],
  );
  const selectedStudyMaterialJobs = useMemo(() => {
    if (!studySelectedMaterialId) return [];
    return studyJobs.filter(
      (job) => (job.metadata as Record<string, unknown> | undefined)?.study_material_id === studySelectedMaterialId,
    );
  }, [studyJobs, studySelectedMaterialId]);
  const selectedStudyJob = useMemo(
    () => selectedStudyMaterialJobs.find((job) => job.id === studySelectedJobId) || null,
    [selectedStudyMaterialJobs, studySelectedJobId],
  );
  const selectedStudyLesson = useMemo(
    () => studyTopics.find((topic) => topic.id === studyLessonDetailId) || null,
    [studyTopics, studyLessonDetailId],
  );
  const selectedStudyOutput = useMemo(() => {
    if (!selectedStudyMaterial || !studyOutputModalKind) return null;
    if (studyOutputModalKind === "converted") {
      return {
        title: "Converted markdown",
        body: selectedStudyMaterial.converted_markdown || "No converted markdown yet.",
      };
    }
    if (studyOutputModalKind === "solved") {
      return {
        title: "Solved markdown",
        body: selectedStudyMaterial.solved_markdown || "No solved output yet.",
      };
    }
    return {
      title: "Theory pack",
      body: selectedStudyMaterial.theory_markdown || "No theory output yet.",
    };
  }, [selectedStudyMaterial, studyOutputModalKind]);
  const visibleStudyCourses = useMemo(
    () => (studyShowAllCourses ? studyCourses : studyCourses.slice(0, STUDY_PREVIEW_COUNT)),
    [studyCourses, studyShowAllCourses],
  );
  const visibleStudyLessons = useMemo(
    () => (studyShowAllLessons ? studyTopics : studyTopics.slice(0, STUDY_PREVIEW_COUNT)),
    [studyTopics, studyShowAllLessons],
  );
  const visibleStudyExams = useMemo(
    () => (studyShowAllExams ? studyExams : studyExams.slice(0, STUDY_PREVIEW_COUNT)),
    [studyExams, studyShowAllExams],
  );
  const visibleStudyMaterials = useMemo(
    () => (studyShowAllMaterials ? studyMaterials : studyMaterials.slice(0, STUDY_PREVIEW_COUNT)),
    [studyMaterials, studyShowAllMaterials],
  );
  const visibleStudyJobs = useMemo(
    () => (studyShowAllJobs ? selectedStudyMaterialJobs : selectedStudyMaterialJobs.slice(0, STUDY_PREVIEW_COUNT)),
    [selectedStudyMaterialJobs, studyShowAllJobs],
  );
  useEffect(() => {
    if (!studySelectedMaterialId) {
      return;
    }
    if (!selectedStudyMaterialJobs.length) {
      return;
    }
    setStudySelectedJobId((prev) => {
      if (prev && selectedStudyMaterialJobs.some((job) => job.id === prev)) {
        return prev;
      }
      return selectedStudyMaterialJobs[0].id;
    });
  }, [studySelectedMaterialId, selectedStudyMaterialJobs]);
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
        study_model: formData.get("study_model") as string,
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

  async function refreshCalendar() {
    try {
      setCalendarLoading(true);
      setCalendarError(null);
      const data = await fetchCalendarCombined({ days: 14 });
      setCalendarData(data);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to load calendar");
    } finally {
      setCalendarLoading(false);
    }
  }

  async function refreshStudyData() {
    try {
      setStudyLoading(true);
      setStudyError(null);
      const [{ courses }, materialsResp, topicsResp, examsResp, jobsResp] = await Promise.all([
        fetchStudyCourses(),
        studySelectedCourseId
          ? fetchStudyMaterials(studySelectedCourseId)
          : Promise.resolve({ materials: [] as StudyMaterial[] }),
        studySelectedCourseId
          ? fetchStudyTopics(studySelectedCourseId)
          : Promise.resolve({ topics: [] as StudyTopic[] }),
        studySelectedCourseId
          ? fetchStudyExams(studySelectedCourseId)
          : Promise.resolve({ exams: [] as StudyExam[] }),
        fetchJobs(),
      ]);
      // Only update state if data actually changed
      setStudyCourses((prev) => 
        JSON.stringify(prev) !== JSON.stringify(courses) ? courses : prev
      );
      if (!studySelectedCourseId && courses.length) {
        setStudySelectedCourseId(courses[0].id);
      }
      const materials = materialsResp.materials || [];
      const topics = topicsResp.topics || [];
      const exams = examsResp.exams || [];
      setStudyMaterials((prev) =>
        JSON.stringify(prev) !== JSON.stringify(materials) ? materials : prev
      );
      setStudyTopics((prev) =>
        JSON.stringify(prev) !== JSON.stringify(topics) ? topics : prev
      );
      setStudyExams((prev) =>
        JSON.stringify(prev) !== JSON.stringify(exams) ? exams : prev
      );
      setStudyTopicStatusDrafts(
        Object.fromEntries(topics.map((topic) => [topic.id, topic.status || "not_started"])),
      );
      setStudyJobs((prev) => {
        const filtered = (jobsResp || []).filter((job) => job.module_slug === "study");
        return JSON.stringify(prev) !== JSON.stringify(filtered) ? filtered : prev;
      });
      setStudySelectedJobId((prev) => {
        const studyOnly = (jobsResp || []).filter((job) => job.module_slug === "study");
        const jobsForMaterial = studyOnly.filter(
          (job) => (job.metadata as Record<string, unknown> | undefined)?.study_material_id === studySelectedMaterialId,
        );
        if (prev && jobsForMaterial.some((job) => job.id === prev)) return prev;
        return jobsForMaterial[0]?.id || prev;
      });
      setStudySelectedMaterialId((prev) => {
        if (prev && materials.some((material) => material.id === prev)) {
          return prev;
        }
        return materials[0]?.id || null;
      });
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to load study data");
    } finally {
      setStudyLoading(false);
    }
  }

  async function handleSelectStudyJob(jobId: string) {
    try {
      setStudySelectedJobId(jobId);
      setStudyJobLogsLoading(true);
      const payload = await fetchJobEvents(jobId);
      setStudyJobEvents(payload.events || []);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to load job logs");
      setStudyJobEvents([]);
    } finally {
      setStudyJobLogsLoading(false);
    }
  }

  async function handleRestartStudyJob(job: Job, force = false) {
    try {
      setStudySaving(true);
      setStudyError(null);
      await restartStudyJob(job.id, force);
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      if (err?.status === 409 && !force) {
        await handleRestartStudyJob(job, true);
        return;
      }
      setStudyError(err.message || "Failed to restart job");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleCreateStudyLesson(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!studySelectedCourseId) {
      setStudyError("Select or create a course first");
      return;
    }
    if (!studyLessonTitle.trim()) {
      setStudyError("Lesson title is required");
      return;
    }
    try {
      setStudySaving(true);
      setStudyError(null);
      await createStudyTopic({
        course_id: studySelectedCourseId,
        name: studyLessonTitle.trim(),
        description: studyLessonDescription.trim() || undefined,
        estimated_effort_minutes: Number(studyLessonEffort) || 60,
        weight: Number(studyLessonWeight) || 1,
      });
      setStudyLessonTitle("");
      setStudyLessonDescription("");
      setStudyLessonEffort("60");
      setStudyLessonWeight("1.0");
      await refreshStudyData();
      setShowCreateLessonModal(false);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to create lesson");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleCreateStudyExam(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!studySelectedCourseId) {
      setStudyError("Select or create a course first");
      return;
    }
    if (!studyExamTitle.trim()) {
      setStudyError("Exam title is required");
      return;
    }
    try {
      setStudySaving(true);
      setStudyError(null);
      await createStudyExam({
        course_id: studySelectedCourseId,
        title: studyExamTitle.trim(),
        kind: studyExamKind,
        scheduled_at: studyExamDate ? new Date(studyExamDate).toISOString() : undefined,
        weight: Number(studyExamWeight) || 1,
      });
      setStudyExamTitle("");
      setStudyExamKind("other");
      setStudyExamDate("");
      setStudyExamWeight("1.0");
      await refreshStudyData();
      setShowCreateExamModal(false);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to create exam");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleSaveStudyTopic(topic: StudyTopic, payload: Partial<StudyTopic>) {
    try {
      setStudySaving(true);
      setStudyError(null);
      await updateStudyTopic(topic.id, payload);
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to update lesson");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleCreateStudyCourse(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!studyCourseTitle.trim()) {
      setStudyError("Course title is required");
      return;
    }
    try {
      setStudySaving(true);
      setStudyError(null);
      const created = await createStudyCourse({
        title: studyCourseTitle.trim(),
        code: studyCourseCode.trim() || undefined,
        description: studyCourseDescription.trim() || undefined,
      });
      setStudyCourseTitle("");
      setStudyCourseCode("");
      setStudyCourseDescription("");
      setStudySelectedCourseId(created.id);
      await refreshStudyData();
      setShowCreateCourseModal(false);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to create course");
    } finally {
      setStudySaving(false);
    }
  }

  function handleStudyFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const nextFile = e.target.files?.[0] || null;
    setStudyMaterialFile(nextFile);
    if (!studyMaterialTitle.trim() && nextFile?.name) {
      const baseName = nextFile.name.replace(/\.[^.]+$/, "");
      setStudyMaterialTitle(baseName);
    }
  }

  function handleStudyFileDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    if (studyMaterialInputMode !== "file") return;
    setStudyFileDragOver(true);
  }

  function handleStudyFileDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setStudyFileDragOver(false);
  }

  function handleStudyFileDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setStudyFileDragOver(false);
    if (studyMaterialInputMode !== "file") return;

    const droppedFile = e.dataTransfer.files?.[0] || null;
    if (!droppedFile) return;

    setStudyMaterialFile(droppedFile);
    if (!studyMaterialTitle.trim()) {
      const baseName = droppedFile.name.replace(/\.[^.]+$/, "");
      setStudyMaterialTitle(baseName);
    }
  }

  function openStudyFilePicker() {
    studyFileInputRef.current?.click();
  }

  async function handleEditStudyCourse(course: StudyCourse) {
    const title = window.prompt("Course title", course.title) ?? course.title;
    if (!title.trim()) return;
    const code = window.prompt("Course code", course.code || "") ?? course.code;
    const description = window.prompt("Course description", course.description || "") ?? course.description;
    try {
      setStudySaving(true);
      await updateStudyCourse(course.id, {
        title: title.trim(),
        code: code.trim(),
        description: description.trim(),
      });
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to update course");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleDeleteStudyCourse(course: StudyCourse) {
    if (!window.confirm(`Delete course '${course.title}'? This removes related study data.`)) return;
    try {
      setStudySaving(true);
      await deleteStudyCourse(course.id);
      if (studySelectedCourseId === course.id) {
        setStudySelectedCourseId(null);
      }
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to delete course");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleEditStudyLesson(topic: StudyTopic) {
    const name = window.prompt("Lesson title", topic.name) ?? topic.name;
    if (!name.trim()) return;
    const description = window.prompt("Lesson description", topic.description || "") ?? topic.description;
    const effortRaw = window.prompt("Estimated effort minutes", String(topic.estimated_effort_minutes)) ?? String(topic.estimated_effort_minutes);
    const weightRaw = window.prompt("Lesson weight", String(topic.weight)) ?? String(topic.weight);
    try {
      setStudySaving(true);
      await updateStudyTopic(topic.id, {
        name: name.trim(),
        description: description.trim(),
        estimated_effort_minutes: Number(effortRaw) || topic.estimated_effort_minutes,
        weight: Number(weightRaw) || topic.weight,
      });
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to update lesson");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleDeleteStudyLesson(topic: StudyTopic) {
    if (!window.confirm(`Delete lesson '${topic.name}'?`)) return;
    try {
      setStudySaving(true);
      await deleteStudyTopic(topic.id);
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to delete lesson");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleEditStudyExam(exam: StudyExam) {
    const title = window.prompt("Exam title", exam.title) ?? exam.title;
    if (!title.trim()) return;
    const kind = window.prompt("Exam kind", exam.kind || "other") ?? exam.kind;
    const scheduledAt = window.prompt("Scheduled at (ISO datetime)", exam.scheduled_at || "") ?? (exam.scheduled_at || "");
    const weightRaw = window.prompt("Exam weight", String(exam.weight)) ?? String(exam.weight);
    const notes = window.prompt("Exam notes", exam.notes || "") ?? exam.notes;
    try {
      setStudySaving(true);
      await updateStudyExam(exam.id, {
        title: title.trim(),
        kind: (kind || "other").trim(),
        scheduled_at: scheduledAt.trim() || undefined,
        weight: Number(weightRaw) || exam.weight,
        notes: notes.trim(),
      });
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to update exam");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleDeleteStudyExam(exam: StudyExam) {
    if (!window.confirm(`Delete exam '${exam.title}'?`)) return;
    try {
      setStudySaving(true);
      await deleteStudyExam(exam.id);
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to delete exam");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleUploadStudyMaterial(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!studySelectedCourseId) {
      setStudyError("Select or create a course first");
      return;
    }
    if (!studyMaterialTitle.trim()) {
      setStudyError("Material title is required");
      return;
    }
    if (studyMaterialInputMode === "file" && !studyMaterialFile) {
      setStudyError("Choose a file first");
      return;
    }
    if (studyMaterialInputMode === "text" && !studyMaterialText.trim()) {
      setStudyError("Paste the study text first");
      return;
    }
    try {
      setStudySaving(true);
      setStudyError(null);
      const created = await uploadStudyMaterial({
        course_id: studySelectedCourseId,
        title: studyMaterialTitle.trim(),
        kind: studyMaterialKind,
        notes: studyMaterialNotes.trim(),
        source_text: studyMaterialInputMode === "text" ? studyMaterialText.trim() : undefined,
        file: studyMaterialInputMode === "file" ? studyMaterialFile : undefined,
        process_now: true,
      });
      setStudyMaterialTitle("");
      setStudyMaterialNotes("");
      setStudyMaterialFile(null);
      setStudyFileDragOver(false);
      setStudyMaterialText("");
      setStudySelectedMaterialId(created.material.id);
      await refreshStudyData();
      setShowCreateMaterialModal(false);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to upload material");
    } finally {
      setStudySaving(false);
    }
  }

  async function refreshInboxMessages() {
    try {
      setMessagesLoading(true);
      const data = await fetchInboxMessages();
      setMessagesInbox(data);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setError(err.message || "Failed to load messages");
    } finally {
      setMessagesLoading(false);
    }
  }

  async function handleMarkMessageRead(messageId: string) {
    try {
      await markMessageRead(messageId);
      await refreshInboxMessages();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setError(err.message || "Failed to mark message read");
    }
  }

  async function refreshCallSessions() {
    try {
      setCallsLoading(true);
      setCallsError(null);
      const data = await fetchCallSessions();
      setCallSessions(data);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCallsError(err.message || "Failed to load call sessions");
    } finally {
      setCallsLoading(false);
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

  function toSoftEventDraft(detail: SoftEventDetail): SoftEventDraft {
    return {
      id: detail.id,
      title: detail.title || "",
      description: detail.description || "",
      notes: detail.notes || "",
      preferred_duration_minutes: String(detail.preferred_duration_minutes ?? ""),
      min_duration_minutes: String(detail.min_duration_minutes ?? ""),
      soft_deadline: toLocalInputValue(detail.soft_deadline),
      hard_deadline: toLocalInputValue(detail.hard_deadline),
      frequency: detail.frequency || "",
      deferral_limit: String(detail.deferral_limit ?? ""),
      priority: String(detail.priority ?? ""),
      status: detail.status,
    };
  }

  function newSoftEventDraft(): SoftEventDraft {
    return {
      id: "",
      title: "",
      description: "",
      notes: "",
      preferred_duration_minutes: "60",
      min_duration_minutes: "30",
      soft_deadline: "",
      hard_deadline: "",
      frequency: "",
      deferral_limit: "3",
      priority: "0",
      status: "active",
    };
  }

  function updateSoftEventDraftField(field: keyof SoftEventDraft, value: string) {
    setSoftEventDraft((prev) => {
      if (!prev) return prev;
      return { ...prev, [field]: value };
    });
  }

  async function openSoftEventEditor(softEventId: string) {
    try {
      setSoftEventError(null);
      setSoftEventLoading(true);
      setSoftEventMode("edit");
      setSoftEventModalOpen(true);
      const detail = await fetchSoftEvent(softEventId);
      setSoftEventDraft(toSoftEventDraft(detail));
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSoftEventError(err.message || "Failed to load soft event");
    } finally {
      setSoftEventLoading(false);
    }
  }

  function openSoftEventCreator() {
    setSoftEventError(null);
    setSoftEventMode("create");
    setSoftEventDraft(newSoftEventDraft());
    setSoftEventModalOpen(true);
  }

  async function saveSoftEventDraft() {
    if (!softEventDraft) return;
    if (!softEventDraft.title.trim()) {
      setSoftEventError("Title is required");
      return;
    }
    try {
      setSoftEventLoading(true);
      const preferredDuration = parseInt(softEventDraft.preferred_duration_minutes, 10);
      const minDuration = parseInt(softEventDraft.min_duration_minutes, 10);
      const deferral = parseInt(softEventDraft.deferral_limit, 10);
      const priority = parseInt(softEventDraft.priority, 10);
      const preferred = Number.isFinite(preferredDuration) ? preferredDuration : undefined;
      const minimum = Number.isFinite(minDuration) ? minDuration : undefined;
      const payload = {
        title: softEventDraft.title.trim(),
        description: softEventDraft.description.trim(),
        notes: softEventDraft.notes.trim(),
        preferred_duration_minutes: preferred,
        min_duration_minutes:
          minimum !== undefined && preferred !== undefined
            ? Math.min(minimum, preferred)
            : minimum,
        soft_deadline: toIsoValue(softEventDraft.soft_deadline) || null,
        hard_deadline: toIsoValue(softEventDraft.hard_deadline) || null,
        frequency: softEventDraft.frequency.trim(),
        deferral_limit: Number.isFinite(deferral) ? deferral : undefined,
        priority: Number.isFinite(priority) ? priority : undefined,
        status: softEventDraft.status,
      };
      if (softEventMode === "create") {
        await createSoftEvent(payload);
      } else {
        await updateSoftEvent(softEventDraft.id, payload);
      }
      setSoftEventModalOpen(false);
      setSoftEventDraft(null);
      await refreshCalendar();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSoftEventError(err.message || "Failed to save soft event");
    } finally {
      setSoftEventLoading(false);
    }
  }

  async function handlePromoteSoftSlot(slotId: string) {
    try {
      setPromoteLoadingId(slotId);
      await promoteSoftSlot(slotId);
      await refreshCalendar();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to promote soft slot");
    } finally {
      setPromoteLoadingId(null);
    }
  }

  async function handleReplanCalendar() {
    const note = window.prompt("Optional note for replanning", "");
    try {
      setReplanLoading(true);
      await replanCalendar({ days: 14, note: note?.trim() || undefined });
      await refreshCalendar();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to replan calendar");
    } finally {
      setReplanLoading(false);
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
      setShowSettings(false);
      setShowStudy(false);
      setShowCalendar(false);
      setShowScheduler(false);
      setShowMessages(false);
      setShowCalls(false);
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
                        setShowStudy(false);
                        setShowCalendar(false);
                        setShowScheduler(false);
                        setShowMessages(false);
                        setShowCalls(false);
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
                <button
                  className="ghost"
                  onClick={() => {
                    setShowSettings(false);
                    setShowStudy(false);
                    setShowCalendar(false);
                    setShowScheduler(false);
                    setShowMessages(false);
                    setShowCalls(false);
                  }}
                >
                  Back to chat
                </button>
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
                    <span className="pill">Frontman: {settings.frontman_model || "gpt-5-mini"}</span>
                    <span className="pill">Caller: {settings.caller_model || "gpt-5-mini"}</span>
                    <span className="pill">Study: {settings.study_model || "gpt-5-mini"}</span>
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
                      <input name="frontman_model" defaultValue={settings.frontman_model || "gpt-5-mini"} />
                    </label>
                    <label className="field">
                      <span>Caller model</span>
                      <input name="caller_model" defaultValue={settings.caller_model || "gpt-5-mini"} />
                    </label>
                    <label className="field">
                      <span>Study model</span>
                      <input name="study_model" defaultValue={settings.study_model || "gpt-5-mini"} />
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
                        <span>{new Date(u.created_at).toLocaleString([], { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</span>
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
        ) : showStudy ? (
          <div className="settings-panel">
            <header className="main-header">
              <div>
                <p className="eyebrow">Study</p>
                <h2>Course materials</h2>
              </div>
              <div className="main-actions">
                <input
                  name="study_model_quick"
                  className="ghost"
                  style={{ minWidth: 220 }}
                  value={settings.study_model || "gpt-5-mini"}
                  onChange={(e) => setSettings((prev) => ({ ...prev, study_model: e.target.value }))}
                  placeholder="Study model"
                />
                <button
                  className="ghost"
                  onClick={async () => {
                    try {
                      setSavingSettings(true);
                      setStudyError(null);
                      const updated = await updateSettings({ study_model: settings.study_model || "gpt-5-mini" });
                      setSettings(updated);
                    } catch (err: any) {
                      if (handleAuthError(err)) return;
                      setStudyError(err.message || "Failed to save study model");
                    } finally {
                      setSavingSettings(false);
                    }
                  }}
                  disabled={savingSettings}
                  title="Only affects study processing, solutions, and lesson generation"
                >
                  {savingSettings ? "Saving…" : "Save study model"}
                </button>
                <button
                  className="ghost"
                  onClick={() => {
                    setShowStudy(false);
                    setShowSettings(false);
                    setShowCalendar(false);
                    setShowScheduler(false);
                    setShowMessages(false);
                    setShowCalls(false);
                  }}
                >
                  Back to chat
                </button>
                <button className="ghost" onClick={refreshStudyData} disabled={studyLoading}>
                  {studyLoading ? "Refreshing…" : "Refresh"}
                </button>
              </div>
            </header>
            {studyError && <div className="alert">{studyError}</div>}
            <div className="settings-grid">
              <div className="card">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Library</p>
                    <h3>Your courses</h3>
                    <p className="muted small">Choose the course that new uploads should attach to.</p>
                  </div>
                  <div className="card-head-actions">
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setShowCreateCourseModal(true)}
                    >
                      +
                    </button>
                  </div>
                </div>
                {studyCourses.length ? (
                  <div className="study-course-list">
                    {visibleStudyCourses.map((course) => (
                      <div key={course.id} className={`study-course-pill ${studySelectedCourseId === course.id ? "active" : ""}`}>
                        <button
                          type="button"
                          className="study-course-select"
                          onClick={() => setStudySelectedCourseId(course.id)}
                        >
                          <span className="study-course-title">{course.title}</span>
                          <span className="study-course-meta">
                            {course.code || "No code"} · {course.status}
                          </span>
                        </button>
                        <div className="actions-row">
                          <button type="button" className="ghost" onClick={() => handleEditStudyCourse(course)} disabled={studySaving}>Edit</button>
                          <button type="button" className="ghost" onClick={() => handleDeleteStudyCourse(course)} disabled={studySaving}>Delete</button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No courses yet.</p>
                )}
                {studyCourses.length > STUDY_PREVIEW_COUNT && (
                  <div className="actions-row">
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setStudyShowAllCourses((prev) => !prev)}
                    >
                      {studyShowAllCourses ? "Show less" : `Show all (${studyCourses.length})`}
                    </button>
                  </div>
                )}
              </div>
              <div className="card full">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Lessons</p>
                    <h3>All lessons</h3>
                    <p className="muted small">Add lessons and track each topic through a study state workflow.</p>
                  </div>
                  <div className="card-head-actions">
                    <span className="pill">{studyTopics.length} lessons</span>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setShowCreateLessonModal(true)}
                    >
                      +
                    </button>
                  </div>
                </div>
                {studyTopics.length ? (
                  <div className="study-topic-list">
                    {visibleStudyLessons.map((topic) => {
                      const statusDraft = studyTopicStatusDrafts[topic.id] ?? topic.status;
                      const summaryLines = parseTopicSummaryLines(topic.summary || "");
                      return (
                        <div key={topic.id} className="study-topic-card">
                          <div className="study-topic-header">
                            <div>
                              <div className="study-material-title">{topic.name}</div>
                              <div className="study-topic-summary">
                                {summaryLines.length ? (
                                  <ul className="study-summary-list">
                                    {summaryLines.slice(0, 5).map((line, idx) => (
                                      <li key={`${topic.id}-summary-${idx}`}>{line}</li>
                                    ))}
                                  </ul>
                                ) : (
                                  <div className="muted small">{topic.description || "No description"}</div>
                                )}
                              </div>
                            </div>
                            <span className={`pill study-status ${topicStatusTone(statusDraft)}`}>
                              {formatTopicStatus(statusDraft)}
                            </span>
                          </div>
                          <div className="study-topic-controls">
                            <label className="field compact">
                              <span>Status</span>
                              <select
                                value={statusDraft}
                                onChange={(e) =>
                                  setStudyTopicStatusDrafts((prev) => ({
                                    ...prev,
                                    [topic.id]: e.target.value,
                                  }))
                                }
                              >
                                {STUDY_TOPIC_STATUS_OPTIONS.map((statusOption) => (
                                  <option key={statusOption} value={statusOption}>
                                    {formatTopicStatus(statusOption)}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <button
                              type="button"
                              className="ghost"
                              onClick={() =>
                                handleSaveStudyTopic(topic, {
                                  status: statusDraft,
                                })
                              }
                            >
                              Save status
                            </button>
                            <button
                              type="button"
                              className="ghost"
                              onClick={() => setStudyLessonDetailId(topic.id)}
                            >
                              View details
                            </button>
                            <button
                              type="button"
                              className="ghost"
                              onClick={() => handleEditStudyLesson(topic)}
                              disabled={studySaving}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className="ghost"
                              onClick={() => handleDeleteStudyLesson(topic)}
                              disabled={studySaving}
                            >
                              Delete
                            </button>
                          </div>
                          <div className="study-topic-meta">
                            Effort {topic.estimated_effort_minutes} min · Weight {topic.weight} · State {formatTopicStatus(statusDraft)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="muted">No lessons yet.</p>
                )}
                {studyTopics.length > STUDY_PREVIEW_COUNT && (
                  <div className="actions-row">
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setStudyShowAllLessons((prev) => !prev)}
                    >
                      {studyShowAllLessons ? "Show less" : `Show all (${studyTopics.length})`}
                    </button>
                  </div>
                )}
              </div>
              <div className="card full">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Exams</p>
                    <h3>Course exams</h3>
                    <p className="muted small">Add course-level exam checkpoints and keep their deadlines visible in one place.</p>
                  </div>
                  <div className="card-head-actions">
                    <span className="pill">{studyExams.length} exams</span>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setShowCreateExamModal(true)}
                    >
                      +
                    </button>
                  </div>
                </div>
                {studyExams.length ? (
                  <div className="study-exam-list">
                    {visibleStudyExams.map((exam) => (
                      <div key={exam.id} className="study-exam-card">
                        <div className="study-topic-header">
                          <div>
                            <div className="study-material-title">{exam.title}</div>
                            <div className="study-topic-meta">
                              {exam.kind} · {exam.weight}x
                              {exam.course_title ? ` · ${exam.course_title}` : ""}
                            </div>
                          </div>
                          <span className="pill">{exam.scheduled_at ? formatDateTime(exam.scheduled_at) : "No date"}</span>
                        </div>
                        {exam.notes && <div className="study-topic-meta">{exam.notes}</div>}
                        <div className="actions-row">
                          <button type="button" className="ghost" onClick={() => handleEditStudyExam(exam)} disabled={studySaving}>Edit</button>
                          <button type="button" className="ghost" onClick={() => handleDeleteStudyExam(exam)} disabled={studySaving}>Delete</button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No exams yet.</p>
                )}
                {studyExams.length > STUDY_PREVIEW_COUNT && (
                  <div className="actions-row">
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setStudyShowAllExams((prev) => !prev)}
                    >
                      {studyShowAllExams ? "Show less" : `Show all (${studyExams.length})`}
                    </button>
                  </div>
                )}
              </div>
              <div className="card full">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Upload</p>
                    <h3>Add study material</h3>
                    <p className="muted small">Upload a PDF or image, queue a study-processing job, and let Corv solve it in the background.</p>
                  </div>
                  <div className="card-head-actions">
                    {selectedStudyCourse && (
                      <span className="pill">Course: {selectedStudyCourse.title}</span>
                    )}
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setShowCreateMaterialModal(true)}
                    >
                      +
                    </button>
                  </div>
                </div>
                <p className="muted small">
                  Use the <code>+</code> button to add a new material item.
                </p>
              </div>
              <div className="card">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Jobs</p>
                    <h3>Study processing</h3>
                    <p className="muted small">Recent queued and completed study jobs.</p>
                  </div>
                </div>
                {studyJobs.length ? (
                  <div className="study-job-list">
                    {visibleStudyJobs.map((job) => (
                      <div key={job.id} className="study-job-card">
                        <div className="study-job-topline">
                          <span className="study-material-title">{job.user_visible_summary || "Study job"}</span>
                          <span className={`pill study-status ${job.status === "completed" ? "processed" : job.status === "failed" ? "failed" : job.status === "canceled" ? "failed" : "processing"}`}>
                            {job.status}
                          </span>
                        </div>
                        <div className="study-job-meta">
                          {Math.round((job.progress || 0) * 100)}% complete
                          {job.updated_at ? ` · Updated ${formatDateTime(job.updated_at)}` : ""}
                        </div>
                        <div className="study-job-progress">
                          <div className="study-job-progress-bar" style={{ width: `${Math.max(4, Math.round((job.progress || 0) * 100))}%` }} />
                        </div>
                        <div className="actions-row">
                          <button
                            type="button"
                            className="ghost"
                            onClick={() => handleSelectStudyJob(job.id)}
                            disabled={studyJobLogsLoading && studySelectedJobId === job.id}
                          >
                            {studySelectedJobId === job.id
                              ? studyJobLogsLoading
                                ? "Loading logs..."
                                : "Refresh logs"
                              : "View logs"}
                          </button>
                          <button
                            type="button"
                            className="ghost"
                            onClick={() => handleRestartStudyJob(job)}
                            disabled={studySaving}
                          >
                            Restart
                          </button>
                        </div>
                        {job.error_summary && <div className="alert">{job.error_summary}</div>}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No study jobs yet.</p>
                )}
                {studyJobs.length > STUDY_PREVIEW_COUNT && (
                  <div className="actions-row">
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setStudyShowAllJobs((prev) => !prev)}
                    >
                      {studyShowAllJobs ? "Show less" : `Show all (${studyJobs.length})`}
                    </button>
                  </div>
                )}
                {studySelectedJobId && (
                  <div className="study-job-log-panel">
                    <div className="study-job-topline">
                      <strong>Technical logs</strong>
                      <span className="muted small">
                        {selectedStudyJob ? `${selectedStudyJob.user_visible_summary || "Study job"} (${selectedStudyJob.status})` : studySelectedJobId}
                      </span>
                    </div>
                    {studyJobLogsLoading ? (
                      <p className="muted">Loading logs...</p>
                    ) : studyJobEvents.length ? (
                      <pre className="study-log-dump">
                        {studyJobEvents
                          .map((event) => {
                            const payloadText =
                              event.payload && Object.keys(event.payload).length
                                ? `\n${JSON.stringify(event.payload, null, 2)}`
                                : "";
                            return `${event.created_at || ""} [${event.event_type}] [${event.visibility}] [${event.role || "system"}] ${event.message || ""}${payloadText}`;
                          })
                          .join("\n\n")}
                      </pre>
                    ) : (
                      <p className="muted">No logs recorded for this job yet.</p>
                    )}
                  </div>
                )}
              </div>
              <div className="card">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Materials</p>
                    <h3>Processed set</h3>
                  </div>
                </div>
                {studyLoading && !studyMaterials.length ? (
                  <p className="muted">Loading materials…</p>
                ) : studyMaterials.length ? (
                  <div className="study-material-list">
                    {visibleStudyMaterials.map((material) => (
                      <button
                        key={material.id}
                        type="button"
                        className={`study-material-card ${studySelectedMaterialId === material.id ? "active" : ""}`}
                        onClick={() => setStudySelectedMaterialId(material.id)}
                      >
                        <div className="study-material-header">
                          <span className="study-material-title">{material.title}</span>
                          <span className={`pill study-status ${material.ingestion_status}`}>
                            {material.ingestion_status}
                          </span>
                        </div>
                        <div className="study-material-meta">
                          {formatMaterialKind(material.kind)}
                          {material.page_count ? ` · ${material.page_count} page${material.page_count === 1 ? "" : "s"}` : ""}
                        </div>
                        <div className="study-material-meta">
                          {material.processed_at ? `Processed ${formatDateTime(material.processed_at)}` : "Waiting to process"}
                        </div>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No materials for this course yet.</p>
                )}
                {studyMaterials.length > STUDY_PREVIEW_COUNT && (
                  <div className="actions-row">
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setStudyShowAllMaterials((prev) => !prev)}
                    >
                      {studyShowAllMaterials ? "Show less" : `Show all (${studyMaterials.length})`}
                    </button>
                  </div>
                )}
              </div>
              <div className="card">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Detail</p>
                    <h3>Material output</h3>
                  </div>
                </div>
                {selectedStudyMaterial ? (
                  <div className="study-detail">
                    <div className="study-detail-topline">
                      <div>
                        <div className="cal-title">{selectedStudyMaterial.title}</div>
                        <div className="cal-meta muted small">
                          {formatMaterialKind(selectedStudyMaterial.kind)}
                          {selectedStudyMaterial.processing_error ? ` · ${selectedStudyMaterial.processing_error}` : ""}
                        </div>
                      </div>
                      {selectedStudyMaterial.uploaded_file_url && (
                        <a
                          className="ghost"
                          href={`/api/study/materials/${selectedStudyMaterial.id}/original`}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Open original
                        </a>
                      )}
                    </div>
                    <div className="study-output-grid">
                      <button
                        type="button"
                        className="study-output-panel study-output-trigger"
                        onClick={() => setStudyOutputModalKind("converted")}
                      >
                        <h4>Converted markdown</h4>
                      </button>
                      <button
                        type="button"
                        className="study-output-panel study-output-trigger"
                        onClick={() => setStudyOutputModalKind("solved")}
                      >
                        <h4>Solved markdown</h4>
                      </button>
                      <button
                        type="button"
                        className="study-output-panel study-output-trigger"
                        onClick={() => setStudyOutputModalKind("theory")}
                      >
                        <h4>Theory pack</h4>
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="muted">Select a material to inspect its extracted content.</p>
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
                <button
                  className="ghost"
                  onClick={() => {
                    setShowCalendar(false);
                    setShowSettings(false);
                    setShowStudy(false);
                    setShowScheduler(false);
                    setShowMessages(false);
                    setShowCalls(false);
                  }}
                >
                  Back to chat
                </button>
                <button
                  className="ghost"
                  onClick={refreshCalendar}
                >
                  Refresh
                </button>
                <button className="ghost" onClick={handleReplanCalendar} disabled={replanLoading}>
                  {replanLoading ? "Replanning…" : "Replan"}
                </button>
                <button className="ghost" onClick={openSoftEventCreator}>
                  Add soft event
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
                      soft_event_id: s.soft_event_id,
                      title: s.title,
                      start: s.start,
                      end: s.end,
                      status: s.status,
                      type: "soft" as const,
                      rationale: s.rationale,
                      deferral_count: s.deferral_count,
                      promoted: s.promoted,
                      soft_deadline: s.soft_deadline,
                      hard_deadline: s.hard_deadline,
                    }))].sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime()).map((item) => {
                      const start = new Date(item.start).toLocaleString();
                      const end = new Date(item.end).toLocaleString();
                      const isSoft = item.type === "soft";
                      const softEventId = "soft_event_id" in item ? item.soft_event_id : "";
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
                            {"description" in item && item.description && (
                              <div className="cal-note muted small">{item.description}</div>
                            )}
                            {"status" in item && item.status && (
                              <div className="cal-meta muted small">
                                Status: {item.status}
                                {"deferral_count" in item && item.deferral_count ? ` · Deferrals: ${item.deferral_count}` : ""}
                              </div>
                            )}
                            {"rationale" in item && item.rationale && (
                              <div className="cal-note muted small">{item.rationale}</div>
                            )}
                            {isSoft && (
                              <div className="cal-actions">
                                <button
                                  type="button"
                                  className="ghost pill-action"
                                  onClick={() => openSoftEventEditor(softEventId)}
                                >
                                  Edit
                                </button>
                                <button
                                  type="button"
                                  className="ghost pill-action"
                                  onClick={() => handlePromoteSoftSlot(item.id)}
                                  disabled={promoteLoadingId === item.id}
                                >
                                  {promoteLoadingId === item.id ? "Promoting…" : "Promote"}
                                </button>
                              </div>
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
                        <div
                          key={se.id}
                          className="cal-row clickable"
                          onClick={() => openSoftEventEditor(se.id)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              openSoftEventEditor(se.id);
                            }
                          }}
                        >
                          <div className="cal-badge soft">Soft</div>
                          <div className="cal-body">
                            <div className="cal-title">{se.title}</div>
                            {se.notes && <div className="cal-note muted small">{se.notes}</div>}
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
                <button
                  className="ghost"
                  onClick={() => {
                    setShowScheduler(false);
                    setShowSettings(false);
                    setShowStudy(false);
                    setShowCalendar(false);
                    setShowMessages(false);
                    setShowCalls(false);
                  }}
                >
                  Back to chat
                </button>
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
        ) : showMessages ? (
          <div className="settings-panel">
            <header className="main-header">
              <div>
                <p className="eyebrow">Messages</p>
                <h2>Inbox</h2>
              </div>
              <div className="main-actions">
                <button
                  className="ghost"
                  onClick={() => {
                    setShowMessages(false);
                    setShowSettings(false);
                    setShowStudy(false);
                    setShowCalendar(false);
                    setShowScheduler(false);
                    setShowCalls(false);
                  }}
                >
                  Back to chat
                </button>
                <button className="ghost" onClick={refreshInboxMessages} disabled={messagesLoading}>
                  {messagesLoading ? "Refreshing…" : "Refresh"}
                </button>
              </div>
            </header>
            {messagesLoading && <div className="muted">Loading messages…</div>}
            {!messagesLoading && (
              messagesInbox.length ? (
                <div className="calendar-list">
                  {messagesInbox.map((msg) => (
                    <div
                      key={msg.id}
                      className={`cal-row clickable ${msg.read_at ? "" : "unread"}`}
                      onClick={() => {
                        if (!msg.read_at) {
                          handleMarkMessageRead(msg.id);
                        }
                      }}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          if (!msg.read_at) {
                            handleMarkMessageRead(msg.id);
                          }
                        }
                      }}
                    >
                      <div className="cal-body">
                        <div className="cal-title">{msg.title || "Message"}</div>
                        <div className="cal-note muted small">{msg.body}</div>
                        {msg.created_at && (
                          <div className="cal-meta muted small">{formatDateTime(msg.created_at)}</div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">No messages yet.</p>
              )
            )}
          </div>
        ) : showCalls ? (
          <div className="settings-panel">
            <header className="main-header">
              <div>
                <p className="eyebrow">Calls</p>
                <h2>Call sessions</h2>
              </div>
              <div className="main-actions">
                <button
                  className="ghost"
                  onClick={() => {
                    setShowCalls(false);
                    setShowSettings(false);
                    setShowStudy(false);
                    setShowCalendar(false);
                    setShowScheduler(false);
                    setShowMessages(false);
                  }}
                >
                  Back to chat
                </button>
                <button className="ghost" onClick={refreshCallSessions} disabled={callsLoading}>
                  {callsLoading ? "Refreshing…" : "Refresh"}
                </button>
              </div>
            </header>
            {callsError && <div className="alert">{callsError}</div>}
            {callsLoading && <div className="muted">Loading calls…</div>}
            {!callsLoading && (
              callSessions.length ? (
                <div className="calendar-list">
                  {callSessions.map((session) => (
                    <div key={session.id} className="cal-row">
                      <div className="cal-body">
                        <div className="cal-title">{session.goal}</div>
                        <div className="cal-meta muted small">Status: {session.status}</div>
                        {session.scheduled_for && (
                          <div className="cal-meta muted small">
                            Scheduled: {formatDateTime(session.scheduled_for)}
                          </div>
                        )}
                        {session.summary && (
                          <div className="cal-note muted small">TL;DR: {session.summary}</div>
                        )}
                        {session.status === "ringing" && (
                          <div className="cal-actions">
                            <button
                              type="button"
                              className="ghost pill-action"
                              onClick={async () => {
                                try {
                                  await updateCallSession(session.id, { status: "in_call" });
                                  await refreshCallSessions();
                                } catch (err: any) {
                                  if (handleAuthError(err)) return;
                                  setCallsError(err.message || "Failed to answer call");
                                }
                              }}
                            >
                              Answer
                            </button>
                            <button
                              type="button"
                              className="ghost pill-action"
                              onClick={async () => {
                                try {
                                  await updateCallSession(session.id, { status: "missed" });
                                  await refreshCallSessions();
                                } catch (err: any) {
                                  if (handleAuthError(err)) return;
                                  setCallsError(err.message || "Failed to decline call");
                                }
                              }}
                            >
                              Decline
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">No call sessions yet.</p>
              )
            )}
            <div className="actions-row">
              <button
                className="primary"
                onClick={async () => {
                  try {
                    await createCallSession({ goal: "Quick check-in call" });
                    await refreshCallSessions();
                  } catch (err: any) {
                    if (handleAuthError(err)) return;
                    setCallsError(err.message || "Failed to create call session");
                  }
                }}
              >
                Start test call
              </button>
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
                    setShowStudy(false);
                    setShowCalendar(true);
                    setShowScheduler(false);
                    setShowMessages(false);
                    setShowCalls(false);
                  }}
                >
                  Calendar
                </button>
                <button
                  className="ghost"
                  onClick={() => {
                    setShowCalendar(false);
                    setShowSettings(false);
                    setShowStudy(false);
                    setShowScheduler(true);
                    setShowMessages(false);
                    setShowCalls(false);
                  }}
                >
                  Scheduler
                </button>
                <button
                  className="ghost"
                  onClick={() => {
                    setShowCalendar(false);
                    setShowSettings(false);
                    setShowStudy(false);
                    setShowScheduler(false);
                    setShowMessages(true);
                    setShowCalls(false);
                  }}
                >
                  Messages
                </button>
                <button
                  className="ghost"
                  onClick={() => {
                    setShowCalendar(false);
                    setShowSettings(false);
                    setShowStudy(false);
                    setShowScheduler(false);
                    setShowMessages(false);
                    setShowCalls(true);
                  }}
                >
                  Calls
                </button>
                <button
                  className="ghost"
                  onClick={() => {
                    setShowCalendar(false);
                    setShowSettings(false);
                    setShowStudy(true);
                    setShowScheduler(false);
                    setShowMessages(false);
                    setShowCalls(false);
                  }}
                >
                  Study
                </button>
                <button
                  className="ghost"
                  onClick={() => {
                    setShowCalendar(false);
                    setShowStudy(false);
                    setShowSettings(true);
                    setShowScheduler(false);
                    setShowMessages(false);
                    setShowCalls(false);
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
        {showCreateCourseModal && (
          <div className="modal-backdrop" onClick={() => !studySaving && setShowCreateCourseModal(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Course</p>
                  <h3>Create course</h3>
                </div>
                <button className="ghost" onClick={() => !studySaving && setShowCreateCourseModal(false)}>Close</button>
              </div>
              <form onSubmit={handleCreateStudyCourse} className="modal-body">
                <label className="field">
                  <span>Title</span>
                  <input
                    value={studyCourseTitle}
                    onChange={(e) => setStudyCourseTitle(e.target.value)}
                    placeholder="Calculus II"
                  />
                </label>
                <label className="field">
                  <span>Code</span>
                  <input
                    value={studyCourseCode}
                    onChange={(e) => setStudyCourseCode(e.target.value)}
                    placeholder="MATH-202"
                  />
                </label>
                <label className="field">
                  <span>Description</span>
                  <textarea
                    rows={4}
                    value={studyCourseDescription}
                    onChange={(e) => setStudyCourseDescription(e.target.value)}
                    placeholder="Exam window, professor emphasis, grading structure..."
                  />
                </label>
                <div className="modal-actions">
                  <button type="button" className="ghost" onClick={() => !studySaving && setShowCreateCourseModal(false)}>Cancel</button>
                  <button className="primary" type="submit" disabled={studySaving}>
                    {studySaving ? "Saving…" : "Create course"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {showCreateLessonModal && (
          <div className="modal-backdrop" onClick={() => !studySaving && setShowCreateLessonModal(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Lesson</p>
                  <h3>Create lesson</h3>
                </div>
                <button className="ghost" onClick={() => !studySaving && setShowCreateLessonModal(false)}>Close</button>
              </div>
              <form onSubmit={handleCreateStudyLesson} className="modal-body">
                <div className="form-grid">
                  <label className="field">
                    <span>Lesson title</span>
                    <input
                      value={studyLessonTitle}
                      onChange={(e) => setStudyLessonTitle(e.target.value)}
                      placeholder="Chain rule"
                    />
                  </label>
                  <label className="field">
                    <span>Estimated effort</span>
                    <input
                      type="number"
                      min={1}
                      step={5}
                      value={studyLessonEffort}
                      onChange={(e) => setStudyLessonEffort(e.target.value)}
                      placeholder="60"
                    />
                  </label>
                  <label className="field">
                    <span>Weight</span>
                    <input
                      type="number"
                      min={0.1}
                      step={0.1}
                      value={studyLessonWeight}
                      onChange={(e) => setStudyLessonWeight(e.target.value)}
                      placeholder="1.0"
                    />
                  </label>
                </div>
                <label className="field">
                  <span>Description</span>
                  <textarea
                    rows={3}
                    value={studyLessonDescription}
                    onChange={(e) => setStudyLessonDescription(e.target.value)}
                    placeholder="What this lesson covers and what success looks like..."
                  />
                </label>
                <div className="modal-actions">
                  <button type="button" className="ghost" onClick={() => !studySaving && setShowCreateLessonModal(false)}>Cancel</button>
                  <button className="primary" type="submit" disabled={studySaving || !studySelectedCourseId}>
                    {studySaving ? "Saving…" : "Add lesson"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {showCreateExamModal && (
          <div className="modal-backdrop" onClick={() => !studySaving && setShowCreateExamModal(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Exam</p>
                  <h3>Create exam</h3>
                </div>
                <button className="ghost" onClick={() => !studySaving && setShowCreateExamModal(false)}>Close</button>
              </div>
              <form onSubmit={handleCreateStudyExam} className="modal-body">
                <div className="form-grid">
                  <label className="field">
                    <span>Exam title</span>
                    <input
                      value={studyExamTitle}
                      onChange={(e) => setStudyExamTitle(e.target.value)}
                      placeholder="Midterm 1"
                    />
                  </label>
                  <label className="field">
                    <span>Kind</span>
                    <select value={studyExamKind} onChange={(e) => setStudyExamKind(e.target.value)}>
                      <option value="midterm">Midterm</option>
                      <option value="final">Final</option>
                      <option value="quiz">Quiz</option>
                      <option value="practical">Practical</option>
                      <option value="other">Other</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>Scheduled at</span>
                    <input
                      type="datetime-local"
                      value={studyExamDate}
                      onChange={(e) => setStudyExamDate(e.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>Weight</span>
                    <input
                      type="number"
                      min={0.1}
                      step={0.1}
                      value={studyExamWeight}
                      onChange={(e) => setStudyExamWeight(e.target.value)}
                    />
                  </label>
                </div>
                <div className="modal-actions">
                  <button type="button" className="ghost" onClick={() => !studySaving && setShowCreateExamModal(false)}>Cancel</button>
                  <button className="primary" type="submit" disabled={studySaving || !studySelectedCourseId}>
                    {studySaving ? "Saving…" : "Add exam"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {showCreateMaterialModal && (
          <div className="modal-backdrop" onClick={() => !studySaving && setShowCreateMaterialModal(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Material</p>
                  <h3>Add study material</h3>
                </div>
                <button className="ghost" onClick={() => !studySaving && setShowCreateMaterialModal(false)}>Close</button>
              </div>
              <form onSubmit={handleUploadStudyMaterial} className="modal-body">
                <div className="form-grid">
                  <label className="field">
                    <span>Input type</span>
                    <select
                      value={studyMaterialInputMode}
                      onChange={(e) => setStudyMaterialInputMode(e.target.value as StudyMaterialInputMode)}
                    >
                      <option value="file">File</option>
                      <option value="text">Text</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>Material title</span>
                    <input
                      value={studyMaterialTitle}
                      onChange={(e) => setStudyMaterialTitle(e.target.value)}
                      placeholder="Week 4 practice set"
                    />
                  </label>
                  <label className="field">
                    <span>Kind</span>
                    <select
                      value={studyMaterialKind}
                      onChange={(e) => setStudyMaterialKind(e.target.value as StudyMaterialKind)}
                    >
                      <option value="lecture">Lecture</option>
                      <option value="worksheet">Worksheet</option>
                      <option value="assignment">Assignment</option>
                      <option value="exam">Exam</option>
                      <option value="other">Other</option>
                    </select>
                  </label>
                  {studyMaterialInputMode === "file" ? (
                    <label className="field">
                      <span>File</span>
                      <input
                        ref={studyFileInputRef}
                        className="visually-hidden"
                        type="file"
                        accept=".pdf,image/*"
                        onChange={handleStudyFileChange}
                      />
                      <div
                        className={`study-file-dropzone${studyFileDragOver ? " active" : ""}`}
                        onDragOver={handleStudyFileDragOver}
                        onDragLeave={handleStudyFileDragLeave}
                        onDrop={handleStudyFileDrop}
                        onClick={openStudyFilePicker}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            openStudyFilePicker();
                          }
                        }}
                      >
                        <div className="study-file-dropzone-title">
                          {studyMaterialFile ? "Drop to replace file" : "Drag and drop file here"}
                        </div>
                        <div className="study-file-dropzone-sub muted small">
                          Supports PDF and images. You can also click to browse.
                        </div>
                        <button
                          type="button"
                          className="ghost study-file-picker-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            openStudyFilePicker();
                          }}
                        >
                          {studyMaterialFile ? "Change file" : "Choose file"}
                        </button>
                      </div>
                    </label>
                  ) : (
                    <label className="field full">
                      <span>Paste text</span>
                      <textarea
                        rows={8}
                        value={studyMaterialText}
                        onChange={(e) => setStudyMaterialText(e.target.value)}
                        placeholder="Paste the full notes, worksheet, or study text here..."
                      />
                    </label>
                  )}
                </div>
                <label className="field">
                  <span>Notes</span>
                  <textarea
                    rows={3}
                    value={studyMaterialNotes}
                    onChange={(e) => setStudyMaterialNotes(e.target.value)}
                    placeholder="Anything Corv should keep in mind about this material..."
                  />
                </label>
                {studyMaterialFile && (
                  <div className="study-file-chip">
                    <span>{studyMaterialFile.name}</span>
                    <span className="muted small">{Math.max(1, Math.round(studyMaterialFile.size / 1024))} KB</span>
                  </div>
                )}
                <div className="modal-actions">
                  <button type="button" className="ghost" onClick={() => !studySaving && setShowCreateMaterialModal(false)}>Cancel</button>
                  <button className="primary" type="submit" disabled={studySaving || !studySelectedCourseId}>
                    {studySaving ? "Uploading…" : "Upload and queue"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {studyLessonDetailId && selectedStudyLesson && (
          <div
            className="modal-backdrop"
            onClick={() => setStudyLessonDetailId(null)}
          >
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Lesson detail</p>
                  <h3>{selectedStudyLesson.name}</h3>
                </div>
                <button className="ghost" onClick={() => setStudyLessonDetailId(null)}>
                  Close
                </button>
              </div>
              <div className="modal-body">
                <div className="study-lesson-meta-grid">
                  <div className="study-lesson-chip">Status: {formatTopicStatus(selectedStudyLesson.status)}</div>
                  <div className="study-lesson-chip">Effort: {selectedStudyLesson.estimated_effort_minutes} min</div>
                  <div className="study-lesson-chip">Weight: {selectedStudyLesson.weight}</div>
                </div>

                <section className="study-lesson-section">
                  <h4>Description</h4>
                  <div className="study-output-body">
                    {selectedStudyLesson.description || "No detailed description saved yet."}
                  </div>
                </section>

                {selectedStudyLesson.metadata && (
                  <>
                    {(() => {
                      const why = String((selectedStudyLesson.metadata as Record<string, unknown>).why_it_matters || "").trim();
                      const prereqs = asStringList((selectedStudyLesson.metadata as Record<string, unknown>).prerequisite_assumptions);
                      const toKnow = asStringList((selectedStudyLesson.metadata as Record<string, unknown>).what_to_know);
                      const checks = asStringList((selectedStudyLesson.metadata as Record<string, unknown>).mastery_checks);
                      const pitfalls = asStringList((selectedStudyLesson.metadata as Record<string, unknown>).common_pitfalls);

                      return (
                        <>
                          {why && (
                            <section className="study-lesson-section">
                              <h4>Why this matters</h4>
                              <div className="study-output-body">{why}</div>
                            </section>
                          )}

                          {prereqs.length > 0 && (
                            <section className="study-lesson-section">
                              <h4>Prerequisites</h4>
                              <ul className="study-lesson-list">
                                {prereqs.map((item) => (
                                  <li key={`prereq-${item}`}>{item}</li>
                                ))}
                              </ul>
                            </section>
                          )}

                          {toKnow.length > 0 && (
                            <section className="study-lesson-section">
                              <h4>What to know</h4>
                              <ul className="study-lesson-list">
                                {toKnow.map((item) => (
                                  <li key={`know-${item}`}>{item}</li>
                                ))}
                              </ul>
                            </section>
                          )}

                          {checks.length > 0 && (
                            <section className="study-lesson-section">
                              <h4>Mastery checks</h4>
                              <ul className="study-lesson-list">
                                {checks.map((item) => (
                                  <li key={`check-${item}`}>{item}</li>
                                ))}
                              </ul>
                            </section>
                          )}

                          {pitfalls.length > 0 && (
                            <section className="study-lesson-section">
                              <h4>Common pitfalls</h4>
                              <ul className="study-lesson-list">
                                {pitfalls.map((item) => (
                                  <li key={`pitfall-${item}`}>{item}</li>
                                ))}
                              </ul>
                            </section>
                          )}
                        </>
                      );
                    })()}
                  </>
                )}

                <section className="study-lesson-section">
                  <h4>Raw metadata</h4>
                  <pre className="study-log-dump">
                    {JSON.stringify(selectedStudyLesson.metadata || {}, null, 2)}
                  </pre>
                </section>
              </div>
            </div>
          </div>
        )}
        {studyOutputModalKind && selectedStudyMaterial && selectedStudyOutput && (
          <div className="modal-backdrop" onClick={() => setStudyOutputModalKind(null)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Material output</p>
                  <h3>{selectedStudyOutput.title}</h3>
                  <p className="muted small">{selectedStudyMaterial.title}</p>
                </div>
                <button className="ghost" onClick={() => setStudyOutputModalKind(null)}>
                  Close
                </button>
              </div>
              <div className="modal-body">
                <div className="study-output-body">{selectedStudyOutput.body}</div>
              </div>
            </div>
          </div>
        )}
        {softEventModalOpen && softEventDraft && (
          <div
            className="modal-backdrop"
            onClick={() => {
              if (!softEventLoading) {
                setSoftEventModalOpen(false);
                setSoftEventDraft(null);
              }
            }}
          >
            <div
              className="modal-card"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="modal-header">
                <div>
                  <p className="eyebrow">{softEventMode === "create" ? "New" : "Edit"}</p>
                  <h3>Soft event</h3>
                </div>
                <button
                  className="ghost"
                  onClick={() => {
                    if (softEventLoading) return;
                    setSoftEventModalOpen(false);
                    setSoftEventDraft(null);
                  }}
                >
                  Close
                </button>
              </div>
              {softEventError && <div className="error-banner">{softEventError}</div>}
              <div className="modal-body">
                <label className="field">
                  <span>Title</span>
                  <input
                    value={softEventDraft.title}
                    onChange={(e) => updateSoftEventDraftField("title", e.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Description</span>
                  <textarea
                    rows={3}
                    value={softEventDraft.description}
                    onChange={(e) => updateSoftEventDraftField("description", e.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Notes</span>
                  <textarea
                    rows={2}
                    value={softEventDraft.notes}
                    onChange={(e) => updateSoftEventDraftField("notes", e.target.value)}
                  />
                </label>
                <div className="form-grid">
                  <label className="field">
                    <span>Preferred Duration (minutes)</span>
                    <input
                      type="number"
                      min={5}
                      step={5}
                      value={softEventDraft.preferred_duration_minutes}
                      onChange={(e) => updateSoftEventDraftField("preferred_duration_minutes", e.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>Minimum Duration (minutes)</span>
                    <input
                      type="number"
                      min={5}
                      step={5}
                      value={softEventDraft.min_duration_minutes}
                      onChange={(e) => updateSoftEventDraftField("min_duration_minutes", e.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>Priority</span>
                    <input
                      type="number"
                      min={0}
                      step={1}
                      value={softEventDraft.priority}
                      onChange={(e) => updateSoftEventDraftField("priority", e.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>Deferral limit</span>
                    <input
                      type="number"
                      min={0}
                      step={1}
                      value={softEventDraft.deferral_limit}
                      onChange={(e) => updateSoftEventDraftField("deferral_limit", e.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>Status</span>
                    <select
                      value={softEventDraft.status}
                      onChange={(e) => updateSoftEventDraftField("status", e.target.value)}
                    >
                      <option value="active">active</option>
                      <option value="paused">paused</option>
                      <option value="archived">archived</option>
                    </select>
                  </label>
                </div>
                <div className="form-grid">
                  <label className="field">
                    <span>Soft deadline</span>
                    <input
                      type="datetime-local"
                      value={softEventDraft.soft_deadline}
                      onChange={(e) => updateSoftEventDraftField("soft_deadline", e.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>Hard deadline</span>
                    <input
                      type="datetime-local"
                      value={softEventDraft.hard_deadline}
                      onChange={(e) => updateSoftEventDraftField("hard_deadline", e.target.value)}
                    />
                  </label>
                </div>
                <label className="field">
                  <span>Frequency</span>
                  <input
                    value={softEventDraft.frequency}
                    onChange={(e) => updateSoftEventDraftField("frequency", e.target.value)}
                    placeholder="weekly, monthly, etc."
                  />
                </label>
              </div>
              <div className="modal-actions">
                <button
                  className="ghost"
                  onClick={() => {
                    if (softEventLoading) return;
                    setSoftEventModalOpen(false);
                    setSoftEventDraft(null);
                  }}
                >
                  Cancel
                </button>
                <button className="primary" onClick={saveSoftEventDraft} disabled={softEventLoading}>
                  {softEventLoading ? "Saving…" : "Save"}
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
