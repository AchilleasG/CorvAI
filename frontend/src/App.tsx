import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import SshPanel from "./SshPanel";
import CodingPanel from "./CodingPanel";
import WorkspaceNavigation, { type WorkspaceSection } from "./WorkspaceNavigation";
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
  fetchJob,
  cancelJob,
  fetchJobEvents,
  fetchJobMessagesDirect,
  fetchUsageRecent,
  fetchUsageSummary,
  fetchSettings,
  updateSettings,
  fetchCalendarCombined,
  fetchObjective,
  fetchObjectiveRoots,
  fetchObjectiveTasks,
  fetchObjectiveTree,
  createSoftEvent,
  createHardEventTaskLink,
  updateSoftEvent,
  fetchSoftEvent,
  deleteHardEventTaskLink,
  deleteSoftEvent,
  promoteSoftSlot,
  markSoftSlotOutcome,
  replanCalendar,
  createStudyTopic,
  createStudyExam,
  updateStudyExam,
  deleteStudyExam,
  updateStudyTopic,
  deleteStudyTopic,
  fetchTopicAudiobookVersions,
  createTopicAudiobookVersion,
  previewTopicAudiobookVoice,
  getTopicAudiobookDownloadUrl,
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
  fetchStudyAssignments,
  getStudyAssignment,
  getStudyAssignmentOriginalUrl,
  createStudyAssignment,
  updateStudyAssignmentStatus,
  deleteStudyAssignment,
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
  HardEventTaskLink,
  Objective,
  ObjectiveTaskPicker,
  SoftEventDetail,
  ScheduledTask,
  ScheduledTaskRun,
  StudyCourse,
  StudyExam,
  StudyMaterial,
  StudyTopic,
  StudyTopicAudiobookVersion,
  StudyAssignment,
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
type SoftEventModalTab = "details" | "metadata";
type StudyOutputModalKind = "converted" | "solved" | "theory";
type StudyLessonDetailTab = "overview" | "audiobooks";

type StudyMaterialKind = "lecture" | "worksheet" | "assignment" | "past_exam" | "other";
type StudyMaterialInputMode = "file" | "text";
type StudyDeleteTarget = {
  kind: "course" | "lesson" | "exam";
  id: string;
  label: string;
};
type LessonHomeworkItem = {
  assignment_id: string;
  text: string;
  done: boolean;
  source_material_id?: string;
  source_material_title?: string;
  source_exercise_label?: string;
  question_index?: number;
};
const STUDY_PREVIEW_COUNT = 3;
const STUDY_TOPIC_STATUS_OPTIONS = ["not_started", "in_progress", "review", "mastered"] as const;
const MOBILE_BREAKPOINT_PX = 900;
const STUDY_AUDIOBOOK_VOICE_OPTIONS = [
  { value: "en-US-EmmaMultilingualNeural", label: "Emma (US, multilingual)" },
  { value: "en-US-AriaNeural", label: "Aria (US, natural)" },
  { value: "en-US-GuyNeural", label: "Guy (US, deep)" },
  { value: "en-GB-SoniaNeural", label: "Sonia (UK)" },
  { value: "en-GB-RyanNeural", label: "Ryan (UK)" },
  { value: "en-AU-NatashaNeural", label: "Natasha (AU)" },
] as const;
const VOICE_INPUT_LANGUAGES = [
  { value: "", label: "Automatic" },
  { value: "en", label: "English" },
  { value: "el", label: "Greek" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "it", label: "Italian" },
  { value: "pt", label: "Portuguese" },
  { value: "tr", label: "Turkish" },
] as const;

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

function assignmentStatusTone(status: string): "pending" | "processing" | "processed" | "failed" {
  if (status === "graded") return "processed";
  if (status === "submitted" || status === "in_progress" || status === "ready") return "processing";
  if (status === "processing") return "processing";
  if (status === "draft") return "pending";
  return "failed";
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

function startOfLocalDay(value: Date) {
  const next = new Date(value);
  next.setHours(0, 0, 0, 0);
  return next;
}

function addLocalDays(value: Date, days: number) {
  const next = new Date(value);
  next.setDate(next.getDate() + days);
  return next;
}

function dayKey(value: Date) {
  return startOfLocalDay(value).toISOString().slice(0, 10);
}

function minutesSinceMidnight(value: Date) {
  return value.getHours() * 60 + value.getMinutes();
}

function formatCalendarDayHeader(value: Date) {
  return value.toLocaleDateString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function formatHourLabel(hour: number) {
  const normalized = ((hour % 24) + 24) % 24;
  const suffix = normalized >= 12 ? "PM" : "AM";
  const display = normalized % 12 || 12;
  return `${display} ${suffix}`;
}

function formatWeekRangeLabel(start: Date, endExclusive: Date) {
  const end = addLocalDays(endExclusive, -1);
  return `${start.toLocaleDateString([], { month: "short", day: "numeric" })} – ${end.toLocaleDateString([], {
    month: "short",
    day: "numeric",
  })}`;
}

function isActiveJob(job: Job | null | undefined) {
  if (!job) return false;
  if (job.status === "completed" || job.status === "failed" || job.status === "canceled") {
    return false;
  }
  return (
    job.cancel_requested === true ||
    job.status === "pending" ||
    job.status === "running" ||
    job.status === "waiting_on_user"
  );
}

function isCalendarReplanJob(job: Job | null | undefined) {
  return ((job?.metadata as Record<string, unknown> | undefined)?.job_kind || "") === "calendar_replan";
}

function latestJobByUpdatedAt<T extends { updated_at?: string | null; created_at?: string | null }>(items: T[]) {
  return [...items].sort((a, b) => {
    const at = a.updated_at ? new Date(a.updated_at).getTime() : a.created_at ? new Date(a.created_at).getTime() : 0;
    const bt = b.updated_at ? new Date(b.updated_at).getTime() : b.created_at ? new Date(b.created_at).getTime() : 0;
    return bt - at;
  })[0] || null;
}

function formatJobStatusLabel(job: Job | null | undefined) {
  if (!job) return "Idle";
  switch (job.status) {
    case "canceled":
      return "Canceled";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "pending":
      return "Queued";
    case "running":
      return job.cancel_requested ? "Cancel requested" : "Running";
    case "waiting_on_user":
      return "Waiting on input";
    default:
      return job.status || "Unknown";
  }
}

function clampNumber(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
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

function formatObjectiveStatus(status: string) {
  return status
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

function normalizeLessonHomework(value: unknown): LessonHomeworkItem[] {
  if (!Array.isArray(value)) return [];
  const items: LessonHomeworkItem[] = [];
  value.forEach((entry, idx) => {
    if (typeof entry === "string") {
      const text = entry.trim();
      if (!text) return;
      items.push({ assignment_id: `manual:${idx + 1}`, text, done: false });
      return;
    }
    if (!entry || typeof entry !== "object") return;
    const obj = entry as Record<string, unknown>;
    const raw = obj.raw && typeof obj.raw === "object" ? (obj.raw as Record<string, unknown>) : undefined;
    const text = String(obj.text ?? obj.question ?? "").trim();
    if (!text) return;
    items.push({
      assignment_id: String(obj.assignment_id ?? `manual:${idx + 1}`),
      text,
      done: Boolean(obj.done),
      source_material_id: obj.source_material_id ? String(obj.source_material_id) : undefined,
      source_material_title: obj.source_material_title ? String(obj.source_material_title) : undefined,
      source_exercise_label: obj.source_exercise_label
        ? String(obj.source_exercise_label)
        : raw?.label
          ? String(raw.label)
          : raw?.question_number
            ? String(raw.question_number)
            : raw?.exercise
              ? String(raw.exercise)
              : undefined,
      question_index:
        typeof obj.question_index === "number"
          ? obj.question_index
          : typeof raw?.question_index === "number"
            ? raw.question_index
            : undefined,
    });
  });
  return items;
}

function formatHomeworkReference(item: LessonHomeworkItem): string {
  const source = item.source_material_title || "Past exam";
  const exercise = item.source_exercise_label?.trim();
  if (exercise) return `${source} - ${exercise}`;
  if (typeof item.question_index === "number") return `${source} - Q${item.question_index}`;
  return source;
}

function homeworkProgress(items: LessonHomeworkItem[]) {
  const total = items.length;
  const done = items.filter((item) => item.done).length;
  const percent = total ? Math.round((done / total) * 100) : 0;
  return { total, done, percent };
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
  const [currentSection, setCurrentSection] = useState<WorkspaceSection>("chat");
  const showSettings = currentSection === "settings";
  const showStudy = currentSection === "study";
  const showCalendar = currentSection === "calendar";
  const showScheduler = currentSection === "scheduler";
  const showMessages = currentSection === "messages";
  const showCalls = currentSection === "calls";
  const showSsh = currentSection === "ssh";
  const showCoding = currentSection === "coding";
  const [settings, setSettings] = useState<SettingsPayload>({});
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isMobileViewport, setIsMobileViewport] = useState<boolean>(() =>
    typeof window !== "undefined" ? window.innerWidth <= MOBILE_BREAKPOINT_PX : false,
  );
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [voiceSending, setVoiceSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [micReady, setMicReady] = useState(false);
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [selectedMicId, setSelectedMicId] = useState<string>("");
  const [voiceInputLanguage, setVoiceInputLanguage] = useState<string>(() => {
    const saved = localStorage.getItem("voiceInputLanguage");
    if (saved !== null) return saved;
    const browserLanguage = (navigator.language || "").slice(0, 2).toLowerCase();
    return VOICE_INPUT_LANGUAGES.some((item) => item.value === browserLanguage) ? browserLanguage : "";
  });
  const [openChatActionsId, setOpenChatActionsId] = useState<string | null>(null);
  const [jobLogMessages, setJobLogMessages] = useState<Message[]>([]);
  const [showJobLog, setShowJobLog] = useState(false);
  const [jobLogAnchorId, setJobLogAnchorId] = useState<string | null>(null);
  const [authed, setAuthed] = useState<boolean>(() => !!localStorage.getItem("appAccessToken"));
  const [authError, setAuthError] = useState<string | null>(null);
  const [passwordInput, setPasswordInput] = useState("");
  const [showMicSettings, setShowMicSettings] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recorderMimeTypeRef = useRef<string>("");
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioLevelFrameRef = useRef<number | null>(null);
  const audioLevelMonitoringAvailableRef = useRef(false);
  const voicedAudioDurationRef = useRef(0);
  const lastAudioLevelTimeRef = useRef(0);
  const studyFileInputRef = useRef<HTMLInputElement | null>(null);
  const assignmentFileInputRef = useRef<HTMLInputElement | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const [calendarData, setCalendarData] = useState<CombinedCalendar | null>(null);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [calendarReplanJob, setCalendarReplanJob] = useState<Job | null>(null);
  const [calendarReplanEvents, setCalendarReplanEvents] = useState<JobEvent[]>([]);
  const [calendarReplanEventsLoading, setCalendarReplanEventsLoading] = useState(false);
  const [calendarReplanLogsOpen, setCalendarReplanLogsOpen] = useState(false);
  const [hardEventTaskOptions, setHardEventTaskOptions] = useState<ObjectiveTaskPicker[]>([]);
  const [hardEventTaskOptionsLoading, setHardEventTaskOptionsLoading] = useState(false);
  const [selectedHardEventTaskId, setSelectedHardEventTaskId] = useState("");
  const [hardEventTaskLinkLoading, setHardEventTaskLinkLoading] = useState(false);
  const [selectedCalendarWeekStart, setSelectedCalendarWeekStart] = useState<string | null>(null);
  const [objectiveRoots, setObjectiveRoots] = useState<Objective[]>([]);
  const [selectedObjectiveRootId, setSelectedObjectiveRootId] = useState<string | null>(null);
  const [objectiveTree, setObjectiveTree] = useState<Objective | null>(null);
  const [selectedObjectiveId, setSelectedObjectiveId] = useState<string | null>(null);
  const [selectedObjectiveDetail, setSelectedObjectiveDetail] = useState<Objective | null>(null);
  const [objectiveLoading, setObjectiveLoading] = useState(false);
  const [objectiveError, setObjectiveError] = useState<string | null>(null);
  const [replanLoading, setReplanLoading] = useState(false);
  const [promoteLoadingId, setPromoteLoadingId] = useState<string | null>(null);
  const [calendarDetailEntry, setCalendarDetailEntry] = useState<null | {
    kind: "hard" | "soft";
    id: string;
    title: string;
    description?: string;
    location?: string;
    all_day?: boolean;
    source?: "hard";
    task_links?: HardEventTaskLink[];
    rawStart?: string;
    rawEnd?: string;
    segmentStart: Date;
    segmentEnd: Date;
    soft_event_id?: string;
    status?: string;
    rationale?: string;
    deferral_count?: number;
    promoted?: boolean;
    soft_deadline?: string | null;
    hard_deadline?: string | null;
  }>(null);
  const [softEventModalOpen, setSoftEventModalOpen] = useState(false);
  const [softEventLoading, setSoftEventLoading] = useState(false);
  const [softEventError, setSoftEventError] = useState<string | null>(null);
  const [softEventDraft, setSoftEventDraft] = useState<SoftEventDraft | null>(null);
  const [softEventMetadata, setSoftEventMetadata] = useState<Record<string, unknown> | null>(null);
  const [softEventModalTab, setSoftEventModalTab] = useState<SoftEventModalTab>("details");
  const [softEventMode, setSoftEventMode] = useState<SoftEventMode>("edit");
  const [scheduledTasks, setScheduledTasks] = useState<ScheduledTask[]>([]);
  const [schedulerError, setSchedulerError] = useState<string | null>(null);
  const [schedulerLoading, setSchedulerLoading] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [taskRuns, setTaskRuns] = useState<ScheduledTaskRun[]>([]);
  const [taskRunsLoading, setTaskRunsLoading] = useState(false);
  const [showSchedulerCreateModal, setShowSchedulerCreateModal] = useState(false);
  const [showSchedulerDetailModal, setShowSchedulerDetailModal] = useState(false);
  const [selectedSchedulerTask, setSelectedSchedulerTask] = useState<ScheduledTask | null>(null);
  const [schedulerSaving, setSchedulerSaving] = useState(false);
  const [messagesInbox, setMessagesInbox] = useState<UserMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [callSessions, setCallSessions] = useState<CallSession[]>([]);
  const [callsLoading, setCallsLoading] = useState(false);
  const [callsError, setCallsError] = useState<string | null>(null);
  const [studyCourses, setStudyCourses] = useState<StudyCourse[]>([]);
  const [studyTopics, setStudyTopics] = useState<StudyTopic[]>([]);
  const [studyExams, setStudyExams] = useState<StudyExam[]>([]);
  const [studyMaterials, setStudyMaterials] = useState<StudyMaterial[]>([]);
  const [studyAssignments, setStudyAssignments] = useState<StudyAssignment[]>([]);
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
  const [studyExamNotes, setStudyExamNotes] = useState("");
  const [studyMaterialTitle, setStudyMaterialTitle] = useState("");
  const [studyMaterialKind, setStudyMaterialKind] = useState<StudyMaterialKind>("lecture");
  const [studyMaterialInputMode, setStudyMaterialInputMode] = useState<StudyMaterialInputMode>("file");
  const [studyMaterialNotes, setStudyMaterialNotes] = useState("");
  const [studyMaterialFile, setStudyMaterialFile] = useState<File | null>(null);
  const [studyFileDragOver, setStudyFileDragOver] = useState(false);
  const [studyMaterialText, setStudyMaterialText] = useState("");
  const [studyLessonDetailId, setStudyLessonDetailId] = useState<string | null>(null);
  const [studyLastViewedLessonId, setStudyLastViewedLessonId] = useState<string | null>(null);
  const [studyLessonDetailTab, setStudyLessonDetailTab] = useState<StudyLessonDetailTab>("overview");
  const [topicAudiobookVersions, setTopicAudiobookVersions] = useState<Record<string, StudyTopicAudiobookVersion[]>>({});
  const [topicAudiobookLoadingByTopic, setTopicAudiobookLoadingByTopic] = useState<Record<string, boolean>>({});
  const [topicAudiobookNotesByTopic, setTopicAudiobookNotesByTopic] = useState<Record<string, string>>({});
  const [topicAudiobookVoiceByTopic, setTopicAudiobookVoiceByTopic] = useState<Record<string, string>>({});
  const [topicAudiobookPreviewLoadingByTopic, setTopicAudiobookPreviewLoadingByTopic] = useState<Record<string, boolean>>({});
  const [topicAudiobookPreviewUrlByTopic, setTopicAudiobookPreviewUrlByTopic] = useState<Record<string, string>>({});
  const [studyOutputModalKind, setStudyOutputModalKind] = useState<StudyOutputModalKind | null>(null);
  const [showCreateCourseModal, setShowCreateCourseModal] = useState(false);
  const [showCreateLessonModal, setShowCreateLessonModal] = useState(false);
  const [showCreateExamModal, setShowCreateExamModal] = useState(false);
  const [showCreateMaterialModal, setShowCreateMaterialModal] = useState(false);
  const [showCreateAssignmentModal, setShowCreateAssignmentModal] = useState(false);
  const [showAssignmentDetailModal, setShowAssignmentDetailModal] = useState(false);
  const [selectedStudyAssignment, setSelectedStudyAssignment] = useState<StudyAssignment | null>(null);
  const [showEditCourseModal, setShowEditCourseModal] = useState(false);
  const [showEditLessonModal, setShowEditLessonModal] = useState(false);
  const [showEditExamModal, setShowEditExamModal] = useState(false);
  const [studyEditingCourseId, setStudyEditingCourseId] = useState<string | null>(null);
  const [studyEditingLessonId, setStudyEditingLessonId] = useState<string | null>(null);
  const [studyEditingExamId, setStudyEditingExamId] = useState<string | null>(null);
  const [studyDeleteTarget, setStudyDeleteTarget] = useState<StudyDeleteTarget | null>(null);
  const [studyShowAllCourses, setStudyShowAllCourses] = useState(false);
  const [studyShowAllLessons, setStudyShowAllLessons] = useState(false);
  const [studyShowAllExams, setStudyShowAllExams] = useState(false);
  const [studyShowAllMaterials, setStudyShowAllMaterials] = useState(false);
  const [studyShowAllJobs, setStudyShowAllJobs] = useState(false);
  const [studyShowAllAssignments, setStudyShowAllAssignments] = useState(false);
  const [studyAssignmentTitle, setStudyAssignmentTitle] = useState("");
  const [studyAssignmentDescription, setStudyAssignmentDescription] = useState("");
  const [studyAssignmentDueAt, setStudyAssignmentDueAt] = useState("");
  const [studyAssignmentMaterialText, setStudyAssignmentMaterialText] = useState("");
  const [studyAssignmentSessionCount, setStudyAssignmentSessionCount] = useState("");
  const [studyAssignmentFile, setStudyAssignmentFile] = useState<File | null>(null);
  const [studyAssignmentFileDragOver, setStudyAssignmentFileDragOver] = useState(false);

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
    const onResize = () => {
      const mobile = window.innerWidth <= MOBILE_BREAKPOINT_PX;
      setIsMobileViewport(mobile);
      if (!mobile) {
        setSidebarOpen(true);
      }
    };

    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

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
    refreshObjectives();
    refreshCalendarReplanJob();
    refreshHardEventTaskOptions();
  }, [authed, showCalendar]);

  useEffect(() => {
    if (!authed) return;
    if (!showCalendar) return;
    if (!calendarReplanJob || !isActiveJob(calendarReplanJob)) return;
    const jobId = calendarReplanJob.id;
    let canceled = false;
    const tick = async () => {
      try {
        const [nextJob, payload] = await Promise.all([fetchJob(jobId), fetchJobEvents(jobId)]);
        if (canceled) return;
        setCalendarReplanJob(nextJob);
        setCalendarReplanEvents(payload.events || []);
        if (!isActiveJob(nextJob)) {
          await Promise.all([
            refreshCalendar(),
            refreshObjectives(selectedObjectiveRootId, selectedObjectiveId),
          ]);
        }
      } catch (err: any) {
        if (canceled) return;
        if (handleAuthError(err)) return;
        setCalendarError(err.message || "Failed to refresh calendar replan job");
      }
    };
    tick();
    const id = window.setInterval(tick, 4000);
    return () => {
      canceled = true;
      window.clearInterval(id);
    };
  }, [
    authed,
    showCalendar,
    calendarReplanJob?.id,
    calendarReplanJob?.status,
    calendarReplanJob?.cancel_requested,
    selectedObjectiveId,
    selectedObjectiveRootId,
  ]);

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
    if (calendarDetailEntry?.kind === "hard") {
      setSelectedHardEventTaskId("");
    }
  }, [calendarDetailEntry?.id, calendarDetailEntry?.kind]);

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
      const updatedJob = await cancelJob(jobId);
      const jobsData = await fetchJobs(activeChatId || undefined);
      setJobs(jobsData);
      if (calendarReplanJob?.id === jobId) {
        setCalendarReplanJob(updatedJob);
        await refreshCalendarReplanJob(jobId);
      }
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
  const selectedStudyCourseJobs = useMemo(() => {
    if (!studySelectedCourseId) return studyJobs;
    return studyJobs.filter(
      (job) => (job.metadata as Record<string, unknown> | undefined)?.study_course_id === studySelectedCourseId,
    );
  }, [studyJobs, studySelectedCourseId]);
  const selectedStudyJob = useMemo(
    () => selectedStudyCourseJobs.find((job) => job.id === studySelectedJobId) || null,
    [selectedStudyCourseJobs, studySelectedJobId],
  );
  const selectedStudyLesson = useMemo(
    () => studyTopics.find((topic) => topic.id === studyLessonDetailId) || null,
    [studyTopics, studyLessonDetailId],
  );

  useEffect(() => {
    if (studyLessonDetailId) {
      setStudyLessonDetailTab("overview");
      setStudyLastViewedLessonId(studyLessonDetailId);
    }
  }, [studyLessonDetailId]);
  const selectedCourseTopics = useMemo(
    () => studyTopics.filter((topic) => topic.course_id === studySelectedCourseId),
    [studyTopics, studySelectedCourseId],
  );
  const selectedCourseHomeworkProgress = useMemo(() => {
    const totals = selectedCourseTopics
      .map((topic) => homeworkProgress(normalizeLessonHomework(topic.homework)))
      .reduce(
        (acc, value) => ({ total: acc.total + value.total, done: acc.done + value.done }),
        { total: 0, done: 0 },
      );
    const percent = totals.total ? Math.round((totals.done / totals.total) * 100) : 0;
    return { ...totals, percent };
  }, [selectedCourseTopics]);
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
    () => (studyShowAllJobs ? selectedStudyCourseJobs : selectedStudyCourseJobs.slice(0, STUDY_PREVIEW_COUNT)),
    [selectedStudyCourseJobs, studyShowAllJobs],
  );
  const visibleStudyAssignments = useMemo(
    () => (studyShowAllAssignments ? studyAssignments : studyAssignments.slice(0, STUDY_PREVIEW_COUNT)),
    [studyAssignments, studyShowAllAssignments],
  );
  const selectedObjectiveRoot = useMemo(
    () => objectiveRoots.find((objective) => objective.id === selectedObjectiveRootId) || null,
    [objectiveRoots, selectedObjectiveRootId],
  );
  const objectiveCoverage = calendarData?.objective_coverage || null;
  const objectiveCoverageSummary = objectiveCoverage?.summary || null;
  const objectiveCoveragePartialCount = objectiveCoverageSummary?.partial || 0;
  const availableHardEventTaskOptions = useMemo(() => {
    const linkedTaskIds = new Set((calendarDetailEntry?.task_links || []).map((item) => item.task_id));
    return hardEventTaskOptions.filter((task) => !linkedTaskIds.has(task.id));
  }, [calendarDetailEntry?.task_links, hardEventTaskOptions]);
  const urgentCoverageItems = useMemo(
    () =>
      (objectiveCoverage?.items || []).filter(
        (item) => item.coverage_state === "partial" || item.coverage_state === "uncovered",
      ),
    [objectiveCoverage],
  );
  const calendarWeekOptions = useMemo(() => {
    if (!calendarData) return [] as Array<{ key: string; start: Date; endExclusive: Date }>;
    const windowStart = startOfLocalDay(new Date(calendarData.window_start));
    const windowEndExclusive = addLocalDays(startOfLocalDay(new Date(calendarData.window_end)), 1);
    const options: Array<{ key: string; start: Date; endExclusive: Date }> = [];
    let cursor = new Date(windowStart);
    while (cursor < windowEndExclusive) {
      const next = addLocalDays(cursor, 7);
      options.push({ key: cursor.toISOString(), start: new Date(cursor), endExclusive: next < windowEndExclusive ? next : windowEndExclusive });
      cursor = next;
    }
    return options;
  }, [calendarData]);
  const calendarEntries = useMemo(() => {
    if (!calendarData) return [] as Array<
      | (HardCalendarEvent & { kind: "hard"; startDate: Date; endDate: Date })
      | (SoftSlot & { kind: "soft"; startDate: Date; endDate: Date })
    >;
    return [
      ...calendarData.hard_events.map((event) => ({
        ...event,
        kind: "hard" as const,
        startDate: new Date(event.start),
        endDate: new Date(event.end),
      })),
      ...calendarData.soft_slots.map((slot) => ({
        ...slot,
        kind: "soft" as const,
        startDate: new Date(slot.start),
        endDate: new Date(slot.end),
      })),
    ]
      .filter((item) => !Number.isNaN(item.startDate.getTime()) && !Number.isNaN(item.endDate.getTime()))
      .sort((a, b) => a.startDate.getTime() - b.startDate.getTime());
  }, [calendarData]);
  const selectedCalendarWeek = useMemo(() => {
    if (!calendarWeekOptions.length) return null;
    return (
      calendarWeekOptions.find((option) => option.key === selectedCalendarWeekStart) || calendarWeekOptions[0]
    );
  }, [calendarWeekOptions, selectedCalendarWeekStart]);
  const calendarGridModel = useMemo(() => {
    if (!selectedCalendarWeek) return null;
    const dayDates = Array.from({ length: Math.max(Math.ceil((selectedCalendarWeek.endExclusive.getTime() - selectedCalendarWeek.start.getTime()) / (24 * 60 * 60 * 1000)), 1) }, (_, index) =>
      addLocalDays(selectedCalendarWeek.start, index),
    );
    const dayKeys = dayDates.map((day) => dayKey(day));
    const dayMap = new Map(
      dayKeys.map((key, index) => [
        key,
        {
          date: dayDates[index],
          allDay: [] as Array<(typeof calendarEntries)[number]>,
          timed: [] as Array<
            (typeof calendarEntries)[number] & {
              segmentStart: Date;
              segmentEnd: Date;
              startMinutes: number;
              endMinutes: number;
              lane?: number;
              laneCount?: number;
            }
          >,
        },
      ]),
    );
    for (const entry of calendarEntries) {
      if (entry.endDate <= selectedCalendarWeek.start || entry.startDate >= selectedCalendarWeek.endExclusive) continue;
      let cursor = startOfLocalDay(entry.startDate > selectedCalendarWeek.start ? entry.startDate : selectedCalendarWeek.start);
      const lastMoment = new Date(Math.min(entry.endDate.getTime() - 1, selectedCalendarWeek.endExclusive.getTime() - 1));
      const lastDay = startOfLocalDay(lastMoment);
      while (cursor <= lastDay) {
        const key = dayKey(cursor);
        const bucket = dayMap.get(key);
        if (!bucket) {
          cursor = addLocalDays(cursor, 1);
          continue;
        }
        const dayStart = new Date(cursor);
        const dayEnd = addLocalDays(dayStart, 1);
        const segmentStart = entry.startDate > dayStart ? entry.startDate : dayStart;
        const segmentEnd = entry.endDate < dayEnd ? entry.endDate : dayEnd;
        const isAllDay =
          entry.kind === "hard" &&
          ("all_day" in entry ? Boolean(entry.all_day) : false || minutesSinceMidnight(segmentStart) === 0 && minutesSinceMidnight(segmentEnd) === 0);
        if (isAllDay) {
          bucket.allDay.push(entry);
        } else {
          bucket.timed.push({
            ...entry,
            segmentStart,
            segmentEnd,
            startMinutes: minutesSinceMidnight(segmentStart),
            endMinutes: Math.max(minutesSinceMidnight(segmentEnd), minutesSinceMidnight(segmentStart) + 30),
          });
        }
        cursor = addLocalDays(cursor, 1);
      }
    }
    const timedSegments = Array.from(dayMap.values()).flatMap((bucket) => bucket.timed);
    const hourStart = 6;
    const hourEnd = 24;
    for (const bucket of dayMap.values()) {
      const active: Array<{ lane: number; endMinutes: number }> = [];
      bucket.timed.sort((a, b) => a.startMinutes - b.startMinutes || a.endMinutes - b.endMinutes);
      bucket.timed.forEach((entry, index) => {
        for (let cursor = active.length - 1; cursor >= 0; cursor -= 1) {
          if (active[cursor].endMinutes <= entry.startMinutes) {
            active.splice(cursor, 1);
          }
        }
        const used = new Set(active.map((item) => item.lane));
        let lane = 0;
        while (used.has(lane)) lane += 1;
        entry.lane = lane;
        active.push({ lane, endMinutes: entry.endMinutes });
        const overlapping = bucket.timed.filter(
          (other, otherIndex) =>
            otherIndex !== index &&
            other.startMinutes < entry.endMinutes &&
            other.endMinutes > entry.startMinutes,
        );
        entry.laneCount = Math.max(lane + 1, ...overlapping.map((other) => (other.lane ?? 0) + 1), 1);
      });
    }
    return { dayDates, dayMap, hourStart, hourEnd };
  }, [calendarEntries, selectedCalendarWeek]);
  useEffect(() => {
    if (!calendarWeekOptions.length) {
      if (selectedCalendarWeekStart !== null) setSelectedCalendarWeekStart(null);
      return;
    }
    if (!selectedCalendarWeekStart || !calendarWeekOptions.some((option) => option.key === selectedCalendarWeekStart)) {
      setSelectedCalendarWeekStart(calendarWeekOptions[0].key);
    }
  }, [calendarWeekOptions, selectedCalendarWeekStart]);
  useEffect(() => {
    setStudySelectedJobId((prev) => {
      if (!studySelectedCourseId || !selectedStudyCourseJobs.length) {
        return null;
      }
      if (prev && selectedStudyCourseJobs.some((job) => job.id === prev)) {
        return prev;
      }
      return selectedStudyCourseJobs[0].id;
    });
  }, [studySelectedCourseId, selectedStudyCourseJobs]);
  const sortedChats = useMemo(() => {
    return [...chats].sort((a, b) => {
      const aTime = a.last_activity_at ? new Date(a.last_activity_at).getTime() : 0;
      const bTime = b.last_activity_at ? new Date(b.last_activity_at).getTime() : 0;
      return bTime - aTime;
    });
  }, [chats]);

  function navigateToSection(section: WorkspaceSection) {
    setCurrentSection(section);
    if (isMobileViewport) {
      setSidebarOpen(false);
    }
  }

  function renderObjectiveNode(objective: Objective, depth = 0): JSX.Element {
    const isSelected = objective.id === selectedObjectiveId;
    const incompleteTasks = objective.tasks.filter((task) => task.status !== "done" && task.status !== "canceled");
    return (
      <div key={objective.id} className="objective-tree-branch">
        <button
          type="button"
          className={`objective-tree-node ${isSelected ? "selected" : ""}`}
          style={{ paddingLeft: `${0.8 + depth * 1}rem` }}
          onClick={() => loadObjectiveDetail(objective.id).catch((err: any) => {
            if (handleAuthError(err)) return;
            setObjectiveError(err.message || "Failed to load objective detail");
          })}
        >
          <span className="objective-tree-title">{objective.title}</span>
          <span className="objective-tree-meta">
            {objective.deadline_at ? formatDateTime(objective.deadline_at) : "No deadline"}
            {incompleteTasks.length ? ` · ${incompleteTasks.length} open task${incompleteTasks.length === 1 ? "" : "s"}` : ""}
          </span>
        </button>
        {objective.children.length > 0 && (
          <div className="objective-tree-children">
            {objective.children.map((child) => renderObjectiveNode(child, depth + 1))}
          </div>
        )}
      </div>
    );
  }

  async function handleSaveSettings(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSavingSettings(true);
    setSettingsError(null);
    try {
      const formData = new FormData(e.currentTarget);
      const payload: SettingsPayload = {
        frontman_model: formData.get("frontman_model") as string,
        caller_model: formData.get("caller_model") as string,
        soft_planner_model: formData.get("soft_planner_model") as string,
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
      return data;
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to load calendar");
    } finally {
      setCalendarLoading(false);
    }
  }

  async function refreshHardEventTaskOptions() {
    try {
      setHardEventTaskOptionsLoading(true);
      const tasks = await fetchObjectiveTasks();
      setHardEventTaskOptions(tasks);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to load objective tasks");
    } finally {
      setHardEventTaskOptionsLoading(false);
    }
  }

  async function refreshCalendarReplanJob(preferredJobId?: string | null) {
    try {
      setCalendarReplanEventsLoading(true);
      let job: Job | null = null;
      if (preferredJobId) {
        try {
          job = await fetchJob(preferredJobId);
        } catch {
          job = null;
        }
      }
      if (!job) {
        const allJobs = await fetchJobs();
        const replanJobs = allJobs.filter((item) => isCalendarReplanJob(item));
        job = latestJobByUpdatedAt(replanJobs);
      }
      setCalendarReplanJob(job);
      if (!job) {
        setCalendarReplanEvents([]);
        return;
      }
      const payload = await fetchJobEvents(job.id);
      setCalendarReplanEvents(payload.events || []);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to load calendar replan job");
    } finally {
      setCalendarReplanEventsLoading(false);
    }
  }

  async function loadObjectiveDetail(objectiveId: string) {
    const detail = await fetchObjective(objectiveId);
    setSelectedObjectiveId(detail.id);
    setSelectedObjectiveDetail(detail);
  }

  async function refreshObjectives(preferredRootId?: string | null, preferredObjectiveId?: string | null) {
    try {
      setObjectiveLoading(true);
      setObjectiveError(null);
      const roots = await fetchObjectiveRoots();
      setObjectiveRoots(roots);
      const nextRootId =
        preferredRootId ||
        selectedObjectiveRootId ||
        roots.find((root) => root.id === selectedObjectiveRootId)?.id ||
        roots[0]?.id ||
        null;
      setSelectedObjectiveRootId(nextRootId);
      if (!nextRootId) {
        setObjectiveTree(null);
        setSelectedObjectiveId(null);
        setSelectedObjectiveDetail(null);
        return;
      }
      const tree = await fetchObjectiveTree(nextRootId);
      setObjectiveTree(tree);
      const nextObjectiveId = preferredObjectiveId || selectedObjectiveId || tree.id;
      await loadObjectiveDetail(nextObjectiveId);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setObjectiveError(err.message || "Failed to load objectives");
    } finally {
      setObjectiveLoading(false);
    }
  }

  async function refreshStudyData() {
    try {
      setStudyLoading(true);
      setStudyError(null);
      const [{ courses }, materialsResp, topicsResp, examsResp, assignmentsResp, jobsResp] = await Promise.all([
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
        studySelectedCourseId
          ? fetchStudyAssignments(studySelectedCourseId)
          : Promise.resolve([] as StudyAssignment[]),
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
      const assignments = assignmentsResp || [];
      setStudyMaterials((prev) =>
        JSON.stringify(prev) !== JSON.stringify(materials) ? materials : prev
      );
      setStudyTopics((prev) =>
        JSON.stringify(prev) !== JSON.stringify(topics) ? topics : prev
      );
      setStudyExams((prev) =>
        JSON.stringify(prev) !== JSON.stringify(exams) ? exams : prev
      );
      setStudyAssignments((prev) =>
        JSON.stringify(prev) !== JSON.stringify(assignments) ? assignments : prev
      );
      setStudyTopicStatusDrafts(
        Object.fromEntries(topics.map((topic) => [topic.id, topic.status || "not_started"])),
      );

      if (topics.length) {
        const versionResults = await Promise.all(
          topics.map(async (topic) => {
            try {
              const response = await fetchTopicAudiobookVersions(topic.id);
              return [topic.id, response.versions || []] as const;
            } catch {
              return [topic.id, [] as StudyTopicAudiobookVersion[]] as const;
            }
          }),
        );
        setTopicAudiobookVersions(Object.fromEntries(versionResults));
      } else {
        setTopicAudiobookVersions({});
      }

      setStudyJobs((prev) => {
        const filtered = (jobsResp || []).filter((job) => job.module_slug === "study");
        return JSON.stringify(prev) !== JSON.stringify(filtered) ? filtered : prev;
      });
      setStudySelectedJobId((prev) => {
        const studyOnly = (jobsResp || []).filter((job) => job.module_slug === "study");
        const jobsForCourse = studySelectedCourseId
          ? studyOnly.filter(
              (job) => (job.metadata as Record<string, unknown> | undefined)?.study_course_id === studySelectedCourseId,
            )
          : studyOnly;
        if (prev && jobsForCourse.some((job) => job.id === prev)) return prev;
        return jobsForCourse[0]?.id || prev;
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

  async function handleToggleLessonHomework(topic: StudyTopic, itemAssignmentId: string, done: boolean) {
    const currentHomework = normalizeLessonHomework(topic.homework);
    const nextHomework = currentHomework.map((item) =>
      item.assignment_id === itemAssignmentId ? { ...item, done } : item,
    );
    let persisted = false;

    setStudyTopics((prev) =>
      prev.map((row) => (row.id === topic.id ? { ...row, homework: nextHomework } : row)),
    );

    try {
      setStudySaving(true);
      setStudyError(null);
      await updateStudyTopic(topic.id, {
        homework: nextHomework as unknown as StudyTopic["homework"],
      });
      persisted = true;
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      if (!persisted) {
        setStudyTopics((prev) =>
          prev.map((row) => (row.id === topic.id ? { ...row, homework: currentHomework } : row)),
        );
      }
      setStudyError(err.message || "Failed to update homework item");
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

  function handleAssignmentFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const nextFile = e.target.files?.[0] || null;
    setStudyAssignmentFile(nextFile);
  }

  function handleAssignmentFileDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setStudyAssignmentFileDragOver(true);
  }

  function handleAssignmentFileDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setStudyAssignmentFileDragOver(false);
  }

  function handleAssignmentFileDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setStudyAssignmentFileDragOver(false);
    const droppedFile = e.dataTransfer.files?.[0] || null;
    if (!droppedFile) return;
    setStudyAssignmentFile(droppedFile);
  }

  function openAssignmentFilePicker() {
    assignmentFileInputRef.current?.click();
  }

  async function handleEditStudyCourse(course: StudyCourse) {
    setStudyCourseTitle(course.title || "");
    setStudyCourseCode(course.code || "");
    setStudyCourseDescription(course.description || "");
    setStudyEditingCourseId(course.id);
    setShowEditCourseModal(true);
  }

  async function handleSubmitEditStudyCourse(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!studyEditingCourseId) return;
    if (!studyCourseTitle.trim()) {
      setStudyError("Course title is required");
      return;
    }
    try {
      setStudySaving(true);
      setStudyError(null);
      await updateStudyCourse(studyEditingCourseId, {
        title: studyCourseTitle.trim(),
        code: studyCourseCode.trim(),
        description: studyCourseDescription.trim(),
      });
      await refreshStudyData();
      setShowEditCourseModal(false);
      setStudyEditingCourseId(null);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to update course");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleEditStudyLesson(topic: StudyTopic) {
    setStudyLessonTitle(topic.name || "");
    setStudyLessonDescription(topic.description || "");
    setStudyLessonEffort(String(topic.estimated_effort_minutes || 60));
    setStudyLessonWeight(String(topic.weight || 1));
    setStudyEditingLessonId(topic.id);
    setShowEditLessonModal(true);
  }

  async function handleSubmitEditStudyLesson(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!studyEditingLessonId) return;
    if (!studyLessonTitle.trim()) {
      setStudyError("Lesson title is required");
      return;
    }
    try {
      setStudySaving(true);
      setStudyError(null);
      await updateStudyTopic(studyEditingLessonId, {
        name: studyLessonTitle.trim(),
        description: studyLessonDescription.trim(),
        estimated_effort_minutes: Math.max(1, Number(studyLessonEffort) || 60),
        weight: Number(studyLessonWeight) || 1,
      });
      await refreshStudyData();
      setShowEditLessonModal(false);
      setStudyEditingLessonId(null);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to update lesson");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleEditStudyExam(exam: StudyExam) {
    setStudyExamTitle(exam.title || "");
    setStudyExamKind(exam.kind || "other");
    setStudyExamDate(toLocalInputValue(exam.scheduled_at));
    setStudyExamWeight(String(exam.weight || 1));
    setStudyExamNotes(exam.notes || "");
    setStudyEditingExamId(exam.id);
    setShowEditExamModal(true);
  }

  async function handleSubmitEditStudyExam(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!studyEditingExamId) return;
    if (!studyExamTitle.trim()) {
      setStudyError("Exam title is required");
      return;
    }
    try {
      setStudySaving(true);
      setStudyError(null);
      await updateStudyExam(studyEditingExamId, {
        title: studyExamTitle.trim(),
        kind: (studyExamKind || "other").trim(),
        scheduled_at: toIsoValue(studyExamDate) || undefined,
        weight: Number(studyExamWeight) || 1,
        notes: studyExamNotes.trim(),
      });
      await refreshStudyData();
      setShowEditExamModal(false);
      setStudyEditingExamId(null);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to update exam");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleConfirmStudyDelete() {
    if (!studyDeleteTarget) return;
    try {
      setStudySaving(true);
      setStudyError(null);
      if (studyDeleteTarget.kind === "course") {
        await deleteStudyCourse(studyDeleteTarget.id);
        if (studySelectedCourseId === studyDeleteTarget.id) {
          setStudySelectedCourseId(null);
        }
      } else if (studyDeleteTarget.kind === "lesson") {
        await deleteStudyTopic(studyDeleteTarget.id);
      } else {
        await deleteStudyExam(studyDeleteTarget.id);
      }
      await refreshStudyData();
      setStudyDeleteTarget(null);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to delete item");
    } finally {
      setStudySaving(false);
    }
  }

  function handleDeleteStudyCourse(course: StudyCourse) {
    setStudyDeleteTarget({ kind: "course", id: course.id, label: course.title });
  }

  function handleDeleteStudyLesson(topic: StudyTopic) {
    setStudyDeleteTarget({ kind: "lesson", id: topic.id, label: topic.name });
  }

  function handleDeleteStudyExam(exam: StudyExam) {
    setStudyDeleteTarget({ kind: "exam", id: exam.id, label: exam.title });
  }

  async function loadTopicAudiobooks(topicId: string) {
    try {
      setTopicAudiobookLoadingByTopic((prev) => ({ ...prev, [topicId]: true }));
      const response = await fetchTopicAudiobookVersions(topicId);
      setTopicAudiobookVersions((prev) => ({ ...prev, [topicId]: response.versions || [] }));
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to load lesson audiobooks");
    } finally {
      setTopicAudiobookLoadingByTopic((prev) => ({ ...prev, [topicId]: false }));
    }
  }

  async function handleGenerateTopicAudiobook(topic: StudyTopic) {
    try {
      setTopicAudiobookLoadingByTopic((prev) => ({ ...prev, [topic.id]: true }));
      setStudyError(null);
      const notes = (topicAudiobookNotesByTopic[topic.id] || "").trim();
      const voice = (topicAudiobookVoiceByTopic[topic.id] || "").trim();
      await createTopicAudiobookVersion({
        topic_id: topic.id,
        generation_notes: notes || undefined,
        voice: voice || undefined,
      });
      const [_, jobsData] = await Promise.all([
        loadTopicAudiobooks(topic.id),
        fetchJobs(activeChatId || undefined),
      ]);
      setJobs(jobsData);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to queue lesson audiobook generation");
    } finally {
      setTopicAudiobookLoadingByTopic((prev) => ({ ...prev, [topic.id]: false }));
    }
  }

  async function handlePreviewTopicAudiobookVoice(topic: StudyTopic) {
    try {
      setStudyError(null);
      setTopicAudiobookPreviewLoadingByTopic((prev) => ({ ...prev, [topic.id]: true }));
      const voice = (topicAudiobookVoiceByTopic[topic.id] || STUDY_AUDIOBOOK_VOICE_OPTIONS[0].value).trim();
      const existingUrl = topicAudiobookPreviewUrlByTopic[topic.id];
      if (existingUrl) {
        URL.revokeObjectURL(existingUrl);
      }
      const blob = await previewTopicAudiobookVoice({
        topic_id: topic.id,
        voice,
      });
      const nextUrl = URL.createObjectURL(blob);
      setTopicAudiobookPreviewUrlByTopic((prev) => ({ ...prev, [topic.id]: nextUrl }));
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to preview lesson voice");
    } finally {
      setTopicAudiobookPreviewLoadingByTopic((prev) => ({ ...prev, [topic.id]: false }));
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

  async function handleCreateStudyAssignment(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!studySelectedCourseId) {
      setStudyError("Select or create a course first");
      return;
    }
    if (!studyAssignmentTitle.trim()) {
      setStudyError("Assignment title is required");
      return;
    }
    const dueAtIso = toIsoValue(studyAssignmentDueAt);
    if (!dueAtIso) {
      setStudyError("Assignment due date is required");
      return;
    }
    try {
      setStudySaving(true);
      setStudyError(null);
      await createStudyAssignment({
        course_id: studySelectedCourseId,
        title: studyAssignmentTitle.trim(),
        description: studyAssignmentDescription.trim() || undefined,
        due_at: dueAtIso,
        material_text: studyAssignmentMaterialText.trim() || undefined,
        session_count: studyAssignmentSessionCount.trim() ? Math.max(1, Number(studyAssignmentSessionCount)) : undefined,
        file: studyAssignmentFile || undefined,
      });
      setStudyAssignmentTitle("");
      setStudyAssignmentDescription("");
      setStudyAssignmentDueAt("");
      setStudyAssignmentMaterialText("");
      setStudyAssignmentSessionCount("");
      setStudyAssignmentFile(null);
      await refreshStudyData();
      setShowCreateAssignmentModal(false);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to create assignment");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleUpdateAssignmentStatus(assignment: StudyAssignment, status: StudyAssignment["status"]) {
    try {
      setStudySaving(true);
      setStudyError(null);
      await updateStudyAssignmentStatus(assignment.id, status);
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to update assignment status");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleOpenAssignmentDetail(assignment: StudyAssignment) {
    try {
      const full = await getStudyAssignment(assignment.id);
      setSelectedStudyAssignment(full);
      setShowAssignmentDetailModal(true);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to load assignment details");
    }
  }

  async function handleDeleteAssignment(assignment: StudyAssignment) {
    if (!window.confirm(`Delete assignment \"${assignment.title}\"? This also removes related soft events.`)) return;
    try {
      setStudySaving(true);
      setStudyError(null);
      await deleteStudyAssignment(assignment.id);
      if (selectedStudyAssignment?.id === assignment.id) {
        setSelectedStudyAssignment(null);
        setShowAssignmentDetailModal(false);
      }
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to delete assignment");
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
      setSchedulerSaving(true);
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
      setShowSchedulerCreateModal(false);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSchedulerError(err.message || "Failed to create scheduled task");
    } finally {
      setSchedulerSaving(false);
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

  function handleOpenSchedulerDetail(task: ScheduledTask) {
    setSelectedSchedulerTask(task);
    setShowSchedulerDetailModal(true);
  }

  async function handleCancelSchedulerTask() {
    if (!selectedSchedulerTask) return;
    if (!window.confirm("Are you sure you want to cancel this task?")) return;
    try {
      setSchedulerSaving(true);
      await updateScheduledTask(selectedSchedulerTask.id, { status: "canceled" });
      await refreshScheduledTasks();
      setShowSchedulerDetailModal(false);
      setSelectedSchedulerTask(null);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSchedulerError(err.message || "Failed to cancel task");
    } finally {
      setSchedulerSaving(false);
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
      setSoftEventModalTab("details");
      setSoftEventMode("edit");
      setSoftEventModalOpen(true);
      const detail = await fetchSoftEvent(softEventId);
      setSoftEventDraft(toSoftEventDraft(detail));
      setSoftEventMetadata(detail.metadata || {});
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSoftEventError(err.message || "Failed to load soft event");
    } finally {
      setSoftEventLoading(false);
    }
  }

  function openSoftEventCreator() {
    setSoftEventError(null);
    setSoftEventModalTab("details");
    setSoftEventMode("create");
    setSoftEventDraft(newSoftEventDraft());
    setSoftEventMetadata({});
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
      setSoftEventMetadata(null);
      await refreshCalendar();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSoftEventError(err.message || "Failed to save soft event");
    } finally {
      setSoftEventLoading(false);
    }
  }

  async function handleDeleteSoftEvent() {
    if (!softEventDraft?.id || softEventMode !== "edit") return;
    if (!window.confirm(`Delete soft event "${softEventDraft.title}"?`)) return;
    try {
      setSoftEventLoading(true);
      await deleteSoftEvent(softEventDraft.id);
      setSoftEventModalOpen(false);
      setSoftEventDraft(null);
      setSoftEventMetadata(null);
      await refreshCalendar();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSoftEventError(err.message || "Failed to delete soft event");
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

  async function handleMarkSoftSlotOutcome(slotId: string, outcome: "completed" | "not_performed") {
    const reasonPrompt =
      outcome === "completed"
        ? "Optional note about what happened in this session"
        : "Why was this session not actually performed?";
    const reason = window.prompt(reasonPrompt, "") || "";
    const minutesRaw =
      outcome === "completed"
        ? window.prompt("Minutes actually spent? Leave blank if unknown.", "")
        : "";
    const parsedMinutes = minutesRaw && minutesRaw.trim() ? parseInt(minutesRaw, 10) : undefined;
    try {
      setPromoteLoadingId(slotId);
      await markSoftSlotOutcome(slotId, {
        outcome,
        reason: reason.trim() || undefined,
        minutes_spent: Number.isFinite(parsedMinutes) ? parsedMinutes : undefined,
      });
      await Promise.all([refreshCalendar(), refreshObjectives(selectedObjectiveRootId, selectedObjectiveId)]);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to mark session outcome");
    } finally {
      setPromoteLoadingId(null);
    }
  }

  async function handleReplanCalendar() {
    const note = window.prompt("Optional note for replanning", "");
    try {
      setReplanLoading(true);
      setCalendarError(null);
      const job = await replanCalendar({ days: 14, note: note?.trim() || undefined });
      setCalendarReplanJob(job);
      setCalendarReplanEvents([]);
      setCalendarReplanLogsOpen(false);
      await refreshCalendarReplanJob(job.id);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to replan calendar");
    } finally {
      setReplanLoading(false);
    }
  }

  async function handleCreateHardEventTaskLink() {
    if (!calendarDetailEntry || calendarDetailEntry.kind !== "hard") return;
    if (!selectedHardEventTaskId) return;
    try {
      setHardEventTaskLinkLoading(true);
      const link = await createHardEventTaskLink({
        task_id: selectedHardEventTaskId,
        event: {
          id: calendarDetailEntry.id,
          title: calendarDetailEntry.title,
          description: calendarDetailEntry.description,
          location: calendarDetailEntry.location,
          start: calendarDetailEntry.rawStart,
          end: calendarDetailEntry.rawEnd,
          all_day: calendarDetailEntry.all_day,
          source: "google_calendar",
        },
      });
      setCalendarDetailEntry((prev) => {
        if (!prev || prev.kind !== "hard") return prev;
        return {
          ...prev,
          task_links: [...(prev.task_links || []), link],
        };
      });
      setSelectedHardEventTaskId("");
      await refreshCalendar();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to link hard event to objective task");
    } finally {
      setHardEventTaskLinkLoading(false);
    }
  }

  async function handleDeleteHardEventTaskLink(linkId: string) {
    try {
      setHardEventTaskLinkLoading(true);
      await deleteHardEventTaskLink(linkId);
      setCalendarDetailEntry((prev) => {
        if (!prev || prev.kind !== "hard") return prev;
        return {
          ...prev,
          task_links: (prev.task_links || []).filter((item) => item.id !== linkId),
        };
      });
      await refreshCalendar();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to unlink hard event task");
    } finally {
      setHardEventTaskLinkLoading(false);
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
      navigateToSection("chat");
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
    if (audioLevelFrameRef.current !== null) {
      cancelAnimationFrame(audioLevelFrameRef.current);
      audioLevelFrameRef.current = null;
    }
    if (audioContextRef.current) {
      void audioContextRef.current.close();
      audioContextRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  async function monitorSpeechLevels(stream: MediaStream) {
    const AudioContextClass = window.AudioContext;
    audioLevelMonitoringAvailableRef.current = false;
    voicedAudioDurationRef.current = 0;
    lastAudioLevelTimeRef.current = performance.now();
    if (!AudioContextClass) return;

    try {
      const audioContext = new AudioContextClass();
      audioContextRef.current = audioContext;
      if (audioContext.state === "suspended") await audioContext.resume();
      if (audioContext.state !== "running") return;
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.2;
      audioContext.createMediaStreamSource(stream).connect(analyser);
      audioLevelMonitoringAvailableRef.current = true;
      const samples = new Float32Array(analyser.fftSize);

      const sampleLevel = (now: number) => {
        analyser.getFloatTimeDomainData(samples);
        let sumSquares = 0;
        for (const sample of samples) sumSquares += sample * sample;
        const rms = Math.sqrt(sumSquares / samples.length);
        const elapsed = Math.min(now - lastAudioLevelTimeRef.current, 100);
        if (rms >= 0.012) voicedAudioDurationRef.current += elapsed;
        lastAudioLevelTimeRef.current = now;
        audioLevelFrameRef.current = requestAnimationFrame(sampleLevel);
      };

      audioLevelFrameRef.current = requestAnimationFrame(sampleLevel);
    } catch {
      audioLevelMonitoringAvailableRef.current = false;
      if (audioContextRef.current) {
        void audioContextRef.current.close();
        audioContextRef.current = null;
      }
    }
  }

  async function sendVoiceMessage(blob: Blob) {
    try {
      setVoiceSending(true);
      setError(null);
      const chatId = await ensureChat();
      await sendVoice(chatId, blob, voiceInputLanguage || undefined);
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
      await monitorSpeechLevels(stream);
      const supportedMimeType = typeof MediaRecorder.isTypeSupported === "function"
        ? (mimeType: string) => MediaRecorder.isTypeSupported(mimeType)
        : () => false;
      const preferredMimeType = [
        "audio/webm;codecs=opus",
        "audio/mp4;codecs=mp4a.40.2",
        "audio/mp4",
        "audio/webm",
        "audio/ogg;codecs=opus",
      ].find(supportedMimeType);
      const recorder = preferredMimeType
        ? new MediaRecorder(stream, { mimeType: preferredMimeType })
        : new MediaRecorder(stream);
      recorderMimeTypeRef.current = recorder.mimeType || preferredMimeType || "audio/webm";
      recorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        setRecording(false);
        const hasSpeech = !audioLevelMonitoringAvailableRef.current
          || voicedAudioDurationRef.current >= 180;
        cleanupStream();
        const chunkMimeType = audioChunksRef.current.find((chunk) => chunk.type)?.type;
        const blob = new Blob(audioChunksRef.current, {
          type: recorder.mimeType || chunkMimeType || recorderMimeTypeRef.current,
        });
        audioChunksRef.current = [];
        if (!blob.size) {
          setError("No audio captured");
          return;
        }
        if (!hasSpeech) {
          setError("No speech detected — recording discarded");
          return;
        }
        await sendVoiceMessage(blob);
      };

      recorder.start(250);
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
    <div
      className={`page ${!sidebarOpen ? "sidebar-collapsed" : ""} ${
        isMobileViewport && sidebarOpen ? "mobile-sidebar-open" : ""
      }`}
    >
      {isMobileViewport && sidebarOpen && (
        <button
          type="button"
          className="sidebar-overlay"
          aria-label="Close navigation"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside className={`sidebar ${sidebarOpen ? "open" : "closed"}`}>
        <div className="sidebar-header">
          <h1>Corv</h1>
          <button className="ghost" onClick={() => setSidebarOpen(!sidebarOpen)}>
            {isMobileViewport ? "Close" : sidebarOpen ? "Hide" : "Show"}
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
                        navigateToSection("chat");
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
        <WorkspaceNavigation
          activeSection={currentSection}
          sidebarOpen={sidebarOpen}
          isMobileViewport={isMobileViewport}
          onNavigate={navigateToSection}
          onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
          onNewChat={handleNewChat}
        />
        {showSettings ? (
          <div className="settings-panel">
            <header className="main-header">
              <div>
                <p className="eyebrow">Settings</p>
                <h2>Models & Usage</h2>
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
                    <span className="pill">Planner: {settings.soft_planner_model || settings.caller_model || "gpt-5-mini"}</span>
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
                      <span>Soft planner model</span>
                      <input
                        name="soft_planner_model"
                        defaultValue={settings.soft_planner_model || settings.caller_model || "gpt-5-mini"}
                      />
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
                    <div className="study-progress-block">
                      <div className="study-progress-label muted small">
                        Course homework progress: {selectedCourseHomeworkProgress.done}/{selectedCourseHomeworkProgress.total}
                      </div>
                      <div className="study-progress-track" aria-label="Course homework progress">
                        <div
                          className="study-progress-fill"
                          style={{ width: `${selectedCourseHomeworkProgress.percent}%` }}
                        />
                      </div>
                    </div>
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
                      const lessonHomework = normalizeLessonHomework(topic.homework);
                      const lessonHomeworkStats = homeworkProgress(lessonHomework);
                      return (
                        <div
                          key={topic.id}
                          className={`study-topic-card ${topic.id === (studyLessonDetailId || studyLastViewedLessonId) ? "active" : ""}`}
                        >
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
                          <div className="study-progress-block">
                            <div className="study-progress-label muted small">
                              Homework: {lessonHomeworkStats.done}/{lessonHomeworkStats.total}
                            </div>
                            <div className="study-progress-track" aria-label={`Homework progress for ${topic.name}`}>
                              <div
                                className="study-progress-fill"
                                style={{ width: `${lessonHomeworkStats.percent}%` }}
                              />
                            </div>
                          </div>
                          {lessonHomework.length > 0 && (
                            <div className="study-homework-list">
                              {lessonHomework.slice(0, 3).map((item) => (
                                <label key={`${topic.id}-${item.assignment_id}`} className="study-homework-item">
                                  <input
                                    type="checkbox"
                                    checked={item.done}
                                    onChange={(e) =>
                                      handleToggleLessonHomework(topic, item.assignment_id, e.target.checked)
                                    }
                                    disabled={studySaving}
                                  />
                                  <span>
                                    {item.text}
                                    <span className="study-homework-source muted small">
                                      {formatHomeworkReference(item)}
                                    </span>
                                  </span>
                                </label>
                              ))}
                              {lessonHomework.length > 3 && (
                                <p className="muted small">
                                  {lessonHomework.length - 3} more item(s) in lesson details.
                                </p>
                              )}
                            </div>
                          )}
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
              <div className="card full">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Assignments</p>
                    <h3>Coursework planner</h3>
                    <p className="muted small">
                      Create assignments with due dates and optional source text. Corv will generate a plan, checklist, and session split.
                    </p>
                  </div>
                  <div className="card-head-actions">
                    <span className="pill">{studyAssignments.length} assignments</span>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setShowCreateAssignmentModal(true)}
                    >
                      +
                    </button>
                  </div>
                </div>
                <p className="muted small">
                  Use the <code>+</code> button to create a new assignment.
                </p>

                {studyAssignments.length ? (
                  <div className="study-assignment-list">
                    {visibleStudyAssignments.map((assignment) => (
                      <div
                        key={assignment.id}
                        className="study-assignment-card"
                        role="button"
                        tabIndex={0}
                        onClick={() => handleOpenAssignmentDetail(assignment)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            handleOpenAssignmentDetail(assignment);
                          }
                        }}
                      >
                        <div className="study-topic-header">
                          <div>
                            <div className="study-material-title">{assignment.title}</div>
                            <div className="study-topic-meta">
                              Due {formatDateTime(assignment.due_at)} · {assignment.session_count} session{assignment.session_count === 1 ? "" : "s"}
                              {assignment.soft_event_refs?.length ? ` · ${assignment.soft_event_refs.length} planned events` : ""}
                            </div>
                          </div>
                          <span className={`pill study-status ${assignmentStatusTone(assignment.status)}`}>
                            {assignment.status.replace("_", " ")}
                          </span>
                        </div>
                        {assignment.plan && (
                          <p className="study-topic-meta study-assignment-plan">{assignment.plan}</p>
                        )}
                        {assignment.checklist?.length > 0 && (
                          <ol className="study-assignment-checklist">
                            {assignment.checklist.slice(0, 4).map((step) => (
                              <li key={`${assignment.id}-${step.step_number}`}>
                                <strong>{step.title || `Step ${step.step_number}`}</strong>
                                {step.description ? ` - ${step.description}` : ""}
                              </li>
                            ))}
                            {assignment.checklist.length > 4 && (
                              <li className="muted small">+{assignment.checklist.length - 4} more step(s)</li>
                            )}
                          </ol>
                        )}
                        <div className="actions-row" onClick={(e) => e.stopPropagation()}>
                          {assignment.status === "ready" && (
                            <button
                              type="button"
                              className="ghost"
                              onClick={() => handleUpdateAssignmentStatus(assignment, "in_progress")}
                              disabled={studySaving}
                            >
                              Start sessions
                            </button>
                          )}
                          {assignment.status === "in_progress" && (
                            <button
                              type="button"
                              className="ghost"
                              onClick={() => handleUpdateAssignmentStatus(assignment, "submitted")}
                              disabled={studySaving}
                            >
                              Mark submitted
                            </button>
                          )}
                          {assignment.status === "submitted" && (
                            <button
                              type="button"
                              className="ghost"
                              onClick={() => handleUpdateAssignmentStatus(assignment, "graded")}
                              disabled={studySaving}
                            >
                              Mark graded
                            </button>
                          )}
                          {(assignment.status === "processing" || assignment.status === "draft") && (
                            <span className="muted small">Plan generation in progress.</span>
                          )}
                          <button
                            type="button"
                            className="ghost"
                            onClick={() => handleDeleteAssignment(assignment)}
                            disabled={studySaving}
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No assignments for this course yet.</p>
                )}
                {studyAssignments.length > STUDY_PREVIEW_COUNT && (
                  <div className="actions-row">
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setStudyShowAllAssignments((prev) => !prev)}
                    >
                      {studyShowAllAssignments ? "Show less" : `Show all (${studyAssignments.length})`}
                    </button>
                  </div>
                )}
              </div>
              <div className="card">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Jobs</p>
                    <h3>Study processing</h3>
                    <p className="muted small">Recent queued and completed study jobs.</p>
                  </div>
                </div>
                {selectedStudyCourseJobs.length ? (
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
                {selectedStudyCourseJobs.length > STUDY_PREVIEW_COUNT && (
                  <div className="actions-row">
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setStudyShowAllJobs((prev) => !prev)}
                    >
                      {studyShowAllJobs ? "Show less" : `Show all (${selectedStudyCourseJobs.length})`}
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
                  onClick={refreshCalendar}
                >
                  Refresh
                </button>
                <button
                  className="ghost"
                  onClick={handleReplanCalendar}
                  disabled={replanLoading || isActiveJob(calendarReplanJob)}
                >
                  {replanLoading ? "Queueing…" : isActiveJob(calendarReplanJob) ? "Replan running…" : "Replan"}
                </button>
                <button className="ghost" onClick={openSoftEventCreator}>
                  Add soft event
                </button>
              </div>
            </header>
            {calendarError && <div className="alert">{calendarError}</div>}
            {calendarLoading && <div className="muted">Loading calendar…</div>}
            {calendarReplanJob && (
              <div className="card full calendar-replan-card">
                <div className="card-head">
                  <div>
                    <p className="eyebrow">Replan job</p>
                    <h3>{calendarReplanJob.user_visible_summary || "Calendar replan"}</h3>
                    <p className="muted small">
                      Status {formatJobStatusLabel(calendarReplanJob)}
                      {calendarReplanJob.updated_at ? ` · Updated ${formatDateTime(calendarReplanJob.updated_at)}` : ""}
                    </p>
                  </div>
                  <div className="card-head-actions">
                    <span className={`pill ${isActiveJob(calendarReplanJob) ? "coverage-pill-warning" : ""}`}>
                      {Math.round((calendarReplanJob.progress || 0) * 100)}%
                    </span>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => refreshCalendarReplanJob(calendarReplanJob.id)}
                      disabled={calendarReplanEventsLoading}
                    >
                      {calendarReplanEventsLoading ? "Refreshing logs…" : "Refresh logs"}
                    </button>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => handleCancelJob(calendarReplanJob.id)}
                      disabled={!isActiveJob(calendarReplanJob)}
                    >
                      {calendarReplanJob.status === "canceled"
                        ? "Canceled"
                        : calendarReplanJob.cancel_requested
                          ? "Canceling…"
                          : "Cancel"}
                    </button>
                  </div>
                </div>
                <div className="study-progress-track calendar-replan-progress">
                  <div
                    className="study-progress-fill"
                    style={{ width: `${Math.round((calendarReplanJob.progress || 0) * 100)}%` }}
                  />
                </div>
                {calendarReplanJob.error_summary && (
                  <div className="alert">{calendarReplanJob.error_summary}</div>
                )}
                <div className="calendar-replan-log-toggle">
                  <div className="muted small">
                    {calendarReplanEvents.length
                      ? `${calendarReplanEvents.length} log event${calendarReplanEvents.length === 1 ? "" : "s"}`
                      : calendarReplanEventsLoading
                        ? "Loading logs…"
                        : "No logs yet for this replan job."}
                  </div>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => setCalendarReplanLogsOpen((prev) => !prev)}
                  >
                    {calendarReplanLogsOpen ? "Hide logs" : "Show logs"}
                  </button>
                </div>
                {calendarReplanLogsOpen && (
                  <div className="calendar-list">
                    {calendarReplanEvents.length ? (
                      calendarReplanEvents.map((event) => (
                        <div key={event.id} className="cal-row">
                          <div className="cal-badge soft">{event.event_type}</div>
                          <div className="cal-body">
                            <div className="cal-title">{event.message}</div>
                            <div className="cal-meta muted small">
                              {event.created_at ? formatDateTime(event.created_at) : "Waiting for timestamp"}
                              {event.role ? ` · ${event.role}` : ""}
                            </div>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="muted small calendar-replan-empty">
                        {calendarReplanEventsLoading ? "Loading logs…" : "No logs yet for this replan job."}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
            {!calendarLoading && calendarData && (
              <div className="calendar-grid">
                <div className="card full">
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
                  {calendarGridModel ? (
                    <>
                      <div className="calendar-week-switcher">
                        {calendarWeekOptions.map((option, index) => (
                          <button
                            key={option.key}
                            type="button"
                            className={`ghost week-chip ${selectedCalendarWeek?.key === option.key ? "active" : ""}`}
                            onClick={() => setSelectedCalendarWeekStart(option.key)}
                          >
                            Week {index + 1}: {formatWeekRangeLabel(option.start, option.endExclusive)}
                          </button>
                        ))}
                      </div>
                      <div
                        className="calendar-time-shell"
                        style={{
                          ["--calendar-hours" as string]: String(calendarGridModel.hourEnd - calendarGridModel.hourStart),
                          ["--calendar-days" as string]: String(calendarGridModel.dayDates.length),
                        }}
                      >
                        <div className="calendar-time-header">
                          <div className="calendar-time-axis-spacer">All day</div>
                          {calendarGridModel.dayDates.map((day) => {
                            const bucket = calendarGridModel.dayMap.get(dayKey(day));
                            return (
                              <div key={day.toISOString()} className="calendar-day-header">
                                <div className="calendar-day-label">{formatCalendarDayHeader(day)}</div>
                                <div className="calendar-all-day-lane">
                                  {bucket?.allDay.length ? (
                                    bucket.allDay.map((entry) => (
                                      <div key={`${entry.kind}-${entry.id}-${day.toISOString()}`} className={`calendar-chip ${entry.kind}`}>
                                        {entry.title}
                                      </div>
                                    ))
                                  ) : (
                                    <span className="calendar-chip-empty">No all-day events</span>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                        <div className="calendar-time-body">
                        <div className="calendar-time-grid">
                          <div className="calendar-time-axis">
                            {Array.from({ length: calendarGridModel.hourEnd - calendarGridModel.hourStart }, (_, offset) => {
                              const hour = calendarGridModel.hourStart + offset;
                              return (
                                <div key={hour} className="calendar-hour-label">
                                  {formatHourLabel(hour)}
                                </div>
                              );
                            })}
                          </div>
                          {calendarGridModel.dayDates.map((day) => {
                            const key = dayKey(day);
                            const bucket = calendarGridModel.dayMap.get(key);
                            return (
                              <div key={day.toISOString()} className="calendar-day-column">
                                {Array.from({ length: calendarGridModel.hourEnd - calendarGridModel.hourStart }, (_, offset) => (
                                  <div key={`${key}-${offset}`} className="calendar-hour-cell" />
                                ))}
                                {bucket?.timed.map((entry) => {
                                  const rawTop = ((entry.startMinutes - calendarGridModel.hourStart * 60) / 60) * 72;
                                  const top = Math.max(rawTop, 0);
                                  const rawHeight = ((entry.endMinutes - entry.startMinutes) / 60) * 72;
                                  const height = Math.max(rawHeight - (top - rawTop), 16);
                                  const laneCount = Math.max(entry.laneCount || 1, 1);
                                  const lane = entry.lane || 0;
                                  const width = `calc((100% - ${(laneCount - 1) * 6}px) / ${laneCount})`;
                                  const left = `calc(${lane} * (${width} + 6px))`;
                                  const isSoft = entry.kind === "soft";
                                  return (
                                    <button
                                      key={`${entry.kind}-${entry.id}-${entry.segmentStart.toISOString()}`}
                                      type="button"
                                      className={`calendar-block ${entry.kind}`}
                                      style={{ top: `${top}px`, height: `${height}px`, width, left }}
                                      onClick={() => {
                                        setCalendarDetailEntry({
                                          kind: entry.kind,
                                          id: entry.id,
                                          title: entry.title,
                                          description: "description" in entry ? entry.description : undefined,
                                          location: "location" in entry ? entry.location : undefined,
                                          all_day: "all_day" in entry ? entry.all_day : undefined,
                                          source: entry.kind === "hard" ? "hard" : undefined,
                                          task_links: "task_links" in entry ? entry.task_links : undefined,
                                          rawStart: "start" in entry ? entry.start : undefined,
                                          rawEnd: "end" in entry ? entry.end : undefined,
                                          segmentStart: entry.segmentStart,
                                          segmentEnd: entry.segmentEnd,
                                          soft_event_id: "soft_event_id" in entry ? entry.soft_event_id : undefined,
                                          status: "status" in entry ? entry.status : undefined,
                                          rationale: "rationale" in entry ? entry.rationale : undefined,
                                          deferral_count: "deferral_count" in entry ? entry.deferral_count : undefined,
                                          promoted: "promoted" in entry ? entry.promoted : undefined,
                                          soft_deadline: "soft_deadline" in entry ? entry.soft_deadline : undefined,
                                          hard_deadline: "hard_deadline" in entry ? entry.hard_deadline : undefined,
                                        });
                                      }}
                                    >
                                      <span className="calendar-block-time">
                                        {entry.segmentStart.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                                      </span>
                                      <span className="calendar-block-title">{entry.title}</span>
                                      {isSoft && entry.promoted && <span className="calendar-block-meta">Promoted</span>}
                                    </button>
                                  );
                                })}
                              </div>
                            );
                          })}
                        </div>
                        </div>
                      </div>
                      <div className="calendar-agenda-header">
                        <h4>Agenda for this week</h4>
                        <p className="muted small">Click any event block above to view details.</p>
                      </div>
                      <div className="calendar-list">
                        {calendarEntries
                          .filter(
                            (item) =>
                              selectedCalendarWeek &&
                              item.startDate < selectedCalendarWeek.endExclusive &&
                              item.endDate > selectedCalendarWeek.start,
                          )
                          .map((item) => {
                            const start = item.startDate.toLocaleString();
                            const end = item.endDate.toLocaleString();
                            const isSoft = item.kind === "soft";
                            const softEventId = "soft_event_id" in item ? item.soft_event_id : "";
                            return (
                              <div
                                key={`${item.kind}-${item.id}`}
                                className={`cal-row ${isSoft ? "clickable" : ""}`}
                                onClick={isSoft ? () => openSoftEventEditor(softEventId) : undefined}
                                role={isSoft ? "button" : undefined}
                                tabIndex={isSoft ? 0 : undefined}
                                onKeyDown={
                                  isSoft
                                    ? (e) => {
                                        if (e.key === "Enter" || e.key === " ") {
                                          e.preventDefault();
                                          openSoftEventEditor(softEventId);
                                        }
                                      }
                                    : undefined
                                }
                              >
                                <div className={`cal-badge ${isSoft ? "soft" : "hard"}`}>{isSoft ? "Soft" : "Hard"}</div>
                                <div className="cal-body">
                                  <div className="cal-title">
                                    {item.title}
                                    {isSoft && item.promoted && <span className="pill" style={{ marginLeft: "0.5rem" }}>Promoted</span>}
                                  </div>
                                  <div className="cal-time">
                                    {start} → {end}
                                  </div>
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
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          openSoftEventEditor(softEventId);
                                        }}
                                      >
                                        Edit
                                      </button>
                                      {item.status !== "completed" && item.status !== "skipped" && (
                                        <>
                                          <button
                                            type="button"
                                            className="ghost pill-action"
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              handleMarkSoftSlotOutcome(item.id, "completed");
                                            }}
                                            disabled={promoteLoadingId === item.id}
                                          >
                                            Done
                                          </button>
                                          <button
                                            type="button"
                                            className="ghost pill-action"
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              handleMarkSoftSlotOutcome(item.id, "not_performed");
                                            }}
                                            disabled={promoteLoadingId === item.id}
                                          >
                                            Didn't happen
                                          </button>
                                        </>
                                      )}
                                      <button
                                        type="button"
                                        className="ghost pill-action"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          handlePromoteSoftSlot(item.id);
                                        }}
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
                        {!calendarEntries.filter(
                          (item) =>
                            selectedCalendarWeek &&
                            item.startDate < selectedCalendarWeek.endExclusive &&
                            item.endDate > selectedCalendarWeek.start,
                        ).length && <div className="muted">No events scheduled for this week.</div>}
                      </div>
                    </>
                  ) : (
                    <div className="muted">No events scheduled.</div>
                  )}
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
                <div className="card full">
                  <div className="card-head">
                    <div>
                      <p className="eyebrow">Coverage audit</p>
                      <h3>Deadline-bound tasks in the next 2 weeks</h3>
                    </div>
                    {objectiveCoverage && (
                      <div className="pill-stack">
                        <span className="pill">Total {objectiveCoverageSummary?.total || 0}</span>
                        <span className="pill">Covered {objectiveCoverageSummary?.covered || 0}</span>
                        <span className={`pill ${objectiveCoveragePartialCount ? "coverage-pill-warning" : ""}`}>
                          Partial {objectiveCoveragePartialCount}
                        </span>
                        <span className={`pill ${(objectiveCoverageSummary?.uncovered || 0) ? "coverage-pill-danger" : ""}`}>
                          Uncovered {objectiveCoverageSummary?.uncovered || 0}
                        </span>
                      </div>
                    )}
                  </div>
                  {!objectiveCoverage ? (
                    <p className="muted">No objective coverage data yet.</p>
                  ) : urgentCoverageItems.length ? (
                    <div className="calendar-list">
                      {urgentCoverageItems.map((item) => (
                        <div key={item.task_id} className={`cal-row coverage-row ${item.coverage_state}`}>
                          <div className={`cal-badge ${item.coverage_state === "uncovered" ? "hard" : "soft"}`}>
                            {item.coverage_state}
                          </div>
                          <div className="cal-body">
                            <div className="cal-title">{item.task_title}</div>
                            <div className="cal-meta muted small">
                              {item.objective_title}
                              {item.due_at ? ` · Due ${formatDateTime(item.due_at)}` : ""}
                            </div>
                            <div className="cal-note muted small">
                              Required {item.required_minutes ?? 0} min · Scheduled {item.scheduled_minutes} min
                              {typeof item.missing_minutes === "number" ? ` · Missing ${item.missing_minutes} min` : ""}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">Every deadline-bound task in the window currently has slot coverage.</p>
                  )}
                </div>
                <div className="card full">
                  <div className="card-head">
                    <div>
                      <p className="eyebrow">Objectives</p>
                      <h3>Objective tree</h3>
                      <p className="muted small">Pick a root and inspect the full subtree that feeds the planner.</p>
                    </div>
                    <div className="card-head-actions">
                      <label className="field objective-root-field">
                        <span>Root objective</span>
                        <select
                          value={selectedObjectiveRootId || ""}
                          onChange={(e) => {
                            const nextRootId = e.target.value || null;
                            setSelectedObjectiveRootId(nextRootId);
                            refreshObjectives(nextRootId, nextRootId);
                          }}
                        >
                          {objectiveRoots.map((root) => (
                            <option key={root.id} value={root.id}>
                              {root.title}
                            </option>
                          ))}
                        </select>
                      </label>
                      <button className="ghost" onClick={() => refreshObjectives()} disabled={objectiveLoading}>
                        {objectiveLoading ? "Refreshing…" : "Refresh objectives"}
                      </button>
                    </div>
                  </div>
                  {objectiveError && <div className="alert">{objectiveError}</div>}
                  {objectiveLoading && !objectiveTree ? (
                    <p className="muted">Loading objectives…</p>
                  ) : objectiveTree ? (
                    <div className="objective-layout">
                      <div className="objective-column">
                        <div className="objective-panel-title">
                          {selectedObjectiveRoot?.title || objectiveTree.title}
                        </div>
                        <div className="objective-tree">
                          {renderObjectiveNode(objectiveTree)}
                        </div>
                      </div>
                      <div className="objective-column">
                        {selectedObjectiveDetail ? (
                          <div className="objective-detail">
                            <div className="objective-detail-header">
                              <div>
                                <div className="cal-title">{selectedObjectiveDetail.title}</div>
                                <div className="cal-meta muted small">
                                  {formatObjectiveStatus(selectedObjectiveDetail.status)}
                                  {selectedObjectiveDetail.deadline_at ? ` · Deadline ${formatDateTime(selectedObjectiveDetail.deadline_at)}` : ""}
                                  {typeof selectedObjectiveDetail.remaining_effort_minutes === "number"
                                    ? ` · Remaining ${selectedObjectiveDetail.remaining_effort_minutes} min`
                                    : ""}
                                </div>
                              </div>
                              <div className="pill-stack">
                                <span className="pill">Priority {selectedObjectiveDetail.priority}</span>
                                <span className="pill">{selectedObjectiveDetail.children.length} child node{selectedObjectiveDetail.children.length === 1 ? "" : "s"}</span>
                              </div>
                            </div>
                            {selectedObjectiveDetail.description && (
                              <p className="objective-copy">{selectedObjectiveDetail.description}</p>
                            )}
                            {selectedObjectiveDetail.notes && (
                              <div className="objective-notes">
                                <div className="objective-panel-title">Notes</div>
                                <p className="objective-copy">{selectedObjectiveDetail.notes}</p>
                              </div>
                            )}
                            <div className="objective-detail-grid">
                              <div>
                                <div className="objective-panel-title">Tasks</div>
                                {selectedObjectiveDetail.tasks.length ? (
                                  <div className="calendar-list">
                                    {selectedObjectiveDetail.tasks.map((task) => (
                                      <div key={task.id} className="cal-row">
                                        <div className="cal-badge soft">{task.status}</div>
                                        <div className="cal-body">
                                          <div className="cal-title">{task.title}</div>
                                          {task.description && <div className="cal-note muted small">{task.description}</div>}
                                          <div className="cal-meta muted small">
                                            {task.due_at ? `Due ${formatDateTime(task.due_at)}` : "No due date"}
                                            {typeof task.remaining_effort_minutes === "number"
                                              ? ` · Remaining ${task.remaining_effort_minutes} min`
                                              : typeof task.estimated_effort_minutes === "number"
                                                ? ` · Estimate ${task.estimated_effort_minutes} min`
                                                : ""}
                                          </div>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <p className="muted">No tasks on this objective yet.</p>
                                )}
                              </div>
                              <div>
                                <div className="objective-panel-title">Recent logs</div>
                                {selectedObjectiveDetail.logs.length ? (
                                  <div className="calendar-list">
                                    {selectedObjectiveDetail.logs.map((log) => (
                                      <div key={log.id} className="cal-row">
                                        <div className="cal-badge hard">{log.kind}</div>
                                        <div className="cal-body">
                                          <div className="cal-note">{log.text}</div>
                                          <div className="cal-meta muted small">
                                            {log.logged_at ? formatDateTime(log.logged_at) : "No timestamp"}
                                            {typeof log.minutes_spent === "number" ? ` · ${log.minutes_spent} min` : ""}
                                          </div>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <p className="muted">No logs on this objective yet.</p>
                                )}
                              </div>
                            </div>
                          </div>
                        ) : (
                          <p className="muted">Select an objective node to inspect it.</p>
                        )}
                      </div>
                    </div>
                  ) : (
                    <p className="muted">No objective roots exist yet.</p>
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
                <button className="primary" onClick={() => setShowSchedulerCreateModal(true)}>
                  Create task
                </button>
              </div>
            </header>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1.5fr", gap: "1rem", marginTop: "1rem" }}>
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
                      <div key={task.id} className="cal-row clickable" onClick={() => handleOpenSchedulerDetail(task)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleOpenSchedulerDetail(task); } }}>
                        <div style={{ flex: 1 }}>
                          <div className="cal-title">{task.prompt.slice(0, 100)}</div>
                          <div className="cal-time muted">
                            Next: {task.next_run_at ? new Date(task.next_run_at).toLocaleString() : "—"}
                          </div>
                          <div className="muted small">Recurrence: {task.recurrence} · Status: {task.status}</div>
                        </div>
                        <div className="chat-actions" onClick={(e) => e.stopPropagation()}>
                          <button className="ghost pill-action" onClick={() => handleLoadRuns(task.id)}>
                            Logs
                          </button>
                          {task.status !== "completed" && task.status !== "canceled" && (
                            <>
                              <button className="ghost pill-action" onClick={() => handleToggleScheduledTask(task)}>
                                {task.status === "paused" ? "Resume" : "Pause"}
                              </button>
                              <button className="ghost pill-action" onClick={() => { setSelectedSchedulerTask(task); handleCancelSchedulerTask(); }} style={{ color: "var(--alert)" }}>
                                Cancel
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No scheduled tasks yet.</p>
                )}
              </div>
              <div className="card">
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
                    <div className="calendar-list" style={{ maxHeight: "600px", overflowY: "auto" }}>
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
        ) : showSsh ? (
          <SshPanel />
        ) : showCoding ? (
          <CodingPanel />
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
              {showMicSettings && (
                <div className="muted mic-row">
                  {mics.length > 0 && <>
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
                  </>}
                  <span>Voice language:</span>
                  <select
                    className="mic-select"
                    value={voiceInputLanguage}
                    onChange={(e) => {
                      setVoiceInputLanguage(e.target.value);
                      localStorage.setItem("voiceInputLanguage", e.target.value);
                    }}
                    disabled={recording}
                  >
                    {VOICE_INPUT_LANGUAGES.map((language) => (
                      <option key={language.value || "auto"} value={language.value}>{language.label}</option>
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

        {showEditCourseModal && (
          <div className="modal-backdrop" onClick={() => !studySaving && setShowEditCourseModal(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Course</p>
                  <h3>Edit course</h3>
                </div>
                <button className="ghost" onClick={() => !studySaving && setShowEditCourseModal(false)}>Close</button>
              </div>
              <form onSubmit={handleSubmitEditStudyCourse} className="modal-body">
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
                  <button type="button" className="ghost" onClick={() => !studySaving && setShowEditCourseModal(false)}>Cancel</button>
                  <button className="primary" type="submit" disabled={studySaving || !studyEditingCourseId}>
                    {studySaving ? "Saving…" : "Save changes"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {showEditLessonModal && (
          <div className="modal-backdrop" onClick={() => !studySaving && setShowEditLessonModal(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Lesson</p>
                  <h3>Edit lesson</h3>
                </div>
                <button className="ghost" onClick={() => !studySaving && setShowEditLessonModal(false)}>Close</button>
              </div>
              <form onSubmit={handleSubmitEditStudyLesson} className="modal-body">
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
                  <button type="button" className="ghost" onClick={() => !studySaving && setShowEditLessonModal(false)}>Cancel</button>
                  <button className="primary" type="submit" disabled={studySaving || !studyEditingLessonId}>
                    {studySaving ? "Saving…" : "Save changes"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {showEditExamModal && (
          <div className="modal-backdrop" onClick={() => !studySaving && setShowEditExamModal(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Exam</p>
                  <h3>Edit exam</h3>
                </div>
                <button className="ghost" onClick={() => !studySaving && setShowEditExamModal(false)}>Close</button>
              </div>
              <form onSubmit={handleSubmitEditStudyExam} className="modal-body">
                <div className="form-grid">
                  <label className="field">
                    <span>Exam title</span>
                    <input
                      value={studyExamTitle}
                      onChange={(e) => setStudyExamTitle(e.target.value)}
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
                <label className="field">
                  <span>Notes</span>
                  <textarea
                    rows={3}
                    value={studyExamNotes}
                    onChange={(e) => setStudyExamNotes(e.target.value)}
                    placeholder="Optional exam notes"
                  />
                </label>
                <div className="modal-actions">
                  <button type="button" className="ghost" onClick={() => !studySaving && setShowEditExamModal(false)}>Cancel</button>
                  <button className="primary" type="submit" disabled={studySaving || !studyEditingExamId}>
                    {studySaving ? "Saving…" : "Save changes"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {studyDeleteTarget && (
          <div className="modal-backdrop" onClick={() => !studySaving && setStudyDeleteTarget(null)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Confirm delete</p>
                  <h3>Delete {studyDeleteTarget.kind}</h3>
                </div>
                <button className="ghost" onClick={() => !studySaving && setStudyDeleteTarget(null)}>Close</button>
              </div>
              <div className="modal-body">
                <p>
                  Are you sure you want to delete <strong>{studyDeleteTarget.label}</strong>?
                </p>
                <p className="muted small">This action cannot be undone.</p>
              </div>
              <div className="modal-actions">
                <button type="button" className="ghost" onClick={() => !studySaving && setStudyDeleteTarget(null)}>
                  Cancel
                </button>
                <button type="button" className="primary" onClick={handleConfirmStudyDelete} disabled={studySaving}>
                  {studySaving ? "Deleting…" : "Delete"}
                </button>
              </div>
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
                      <option value="past_exam">Past exam</option>
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

        {showCreateAssignmentModal && (
          <div
            className="modal-backdrop"
            onClick={() => {
              if (studySaving) return;
              setShowCreateAssignmentModal(false);
              setStudyAssignmentFile(null);
              setStudyAssignmentFileDragOver(false);
            }}
          >
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Assignment</p>
                  <h3>Create assignment</h3>
                </div>
                <button
                  className="ghost"
                  onClick={() => {
                    if (studySaving) return;
                    setShowCreateAssignmentModal(false);
                    setStudyAssignmentFile(null);
                    setStudyAssignmentFileDragOver(false);
                  }}
                >
                  Close
                </button>
              </div>
              <form onSubmit={handleCreateStudyAssignment} className="modal-body">
                <div className="form-grid">
                  <label className="field">
                    <span>Title</span>
                    <input
                      value={studyAssignmentTitle}
                      onChange={(e) => setStudyAssignmentTitle(e.target.value)}
                      placeholder="Assignment title"
                      required
                    />
                  </label>
                  <label className="field">
                    <span>Due date</span>
                    <input
                      type="datetime-local"
                      value={studyAssignmentDueAt}
                      onChange={(e) => setStudyAssignmentDueAt(e.target.value)}
                      required
                    />
                  </label>
                  <label className="field">
                    <span>Session count (optional)</span>
                    <input
                      type="number"
                      min={1}
                      max={5}
                      value={studyAssignmentSessionCount}
                      onChange={(e) => setStudyAssignmentSessionCount(e.target.value)}
                      placeholder="Auto"
                    />
                  </label>
                  <label className="field full">
                    <span>Description</span>
                    <textarea
                      rows={2}
                      value={studyAssignmentDescription}
                      onChange={(e) => setStudyAssignmentDescription(e.target.value)}
                      placeholder="What is expected in this assignment?"
                    />
                  </label>
                  <label className="field full">
                    <span>Material text (optional)</span>
                    <textarea
                      rows={4}
                      value={studyAssignmentMaterialText}
                      onChange={(e) => setStudyAssignmentMaterialText(e.target.value)}
                      placeholder="Paste assignment instructions, rubric, or key excerpts"
                    />
                  </label>
                  <label className="field full">
                    <span>Upload file (optional)</span>
                    <input
                      ref={assignmentFileInputRef}
                      className="visually-hidden"
                      type="file"
                      accept=".pdf,.txt,.md,.markdown"
                      onChange={handleAssignmentFileChange}
                    />
                    <div
                      className={`study-file-dropzone${studyAssignmentFileDragOver ? " active" : ""}`}
                      onDragOver={handleAssignmentFileDragOver}
                      onDragLeave={handleAssignmentFileDragLeave}
                      onDrop={handleAssignmentFileDrop}
                      onClick={openAssignmentFilePicker}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          openAssignmentFilePicker();
                        }
                      }}
                    >
                      <div className="study-file-dropzone-title">
                        {studyAssignmentFile ? "Drop to replace file" : "Drag and drop assignment file here"}
                      </div>
                      <div className="study-file-dropzone-sub muted small">
                        Supports PDF, TXT, and Markdown. You can also click to browse.
                      </div>
                      <button
                        type="button"
                        className="ghost study-file-picker-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          openAssignmentFilePicker();
                        }}
                      >
                        {studyAssignmentFile ? "Change file" : "Choose file"}
                      </button>
                    </div>
                  </label>
                </div>
                {studyAssignmentFile && (
                  <div className="study-file-chip">
                    <span>{studyAssignmentFile.name}</span>
                    <span className="muted small">{Math.max(1, Math.round(studyAssignmentFile.size / 1024))} KB</span>
                  </div>
                )}
                <div className="modal-actions">
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => {
                      if (studySaving) return;
                      setShowCreateAssignmentModal(false);
                      setStudyAssignmentFile(null);
                      setStudyAssignmentFileDragOver(false);
                    }}
                  >
                    Cancel
                  </button>
                  <button className="primary" type="submit" disabled={studySaving || !studySelectedCourseId}>
                    {studySaving ? "Creating…" : "Create assignment"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {showAssignmentDetailModal && selectedStudyAssignment && (
          <div className="modal-backdrop" onClick={() => !studySaving && setShowAssignmentDetailModal(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Assignment detail</p>
                  <h3>{selectedStudyAssignment.title}</h3>
                </div>
                <button className="ghost" onClick={() => !studySaving && setShowAssignmentDetailModal(false)}>Close</button>
              </div>
              <div className="modal-body">
                <div className="study-topic-meta">
                  Due {formatDateTime(selectedStudyAssignment.due_at)} · {selectedStudyAssignment.session_count} session{selectedStudyAssignment.session_count === 1 ? "" : "s"}
                </div>
                <div className="study-topic-meta">
                  Status: {selectedStudyAssignment.status.replace("_", " ")}
                </div>
                {selectedStudyAssignment.description && (
                  <div className="study-lesson-section">
                    <h4>Description</h4>
                    <p className="study-topic-meta">{selectedStudyAssignment.description}</p>
                  </div>
                )}
                {selectedStudyAssignment.plan && (
                  <div className="study-lesson-section">
                    <h4>Plan</h4>
                    <p className="study-topic-meta study-assignment-plan">{selectedStudyAssignment.plan}</p>
                  </div>
                )}
                {selectedStudyAssignment.checklist?.length > 0 && (
                  <div className="study-lesson-section">
                    <h4>Checklist</h4>
                    <ol className="study-assignment-checklist">
                      {selectedStudyAssignment.checklist.map((step) => (
                        <li key={`${selectedStudyAssignment.id}-${step.step_number}`}>
                          <strong>{step.title || `Step ${step.step_number}`}</strong>
                          {step.description ? ` - ${step.description}` : ""}
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
                {selectedStudyAssignment.material_text && (
                  <div className="study-lesson-section">
                    <h4>Material text</h4>
                    <pre className="study-log-dump">{selectedStudyAssignment.material_text}</pre>
                  </div>
                )}
                {selectedStudyAssignment.has_uploaded_file && (
                  <div className="study-lesson-section">
                    <h4>Uploaded file</h4>
                    <a
                      className="ghost"
                      href={getStudyAssignmentOriginalUrl(selectedStudyAssignment.id)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {selectedStudyAssignment.uploaded_file_name || "Download original file"}
                    </a>
                  </div>
                )}
              </div>
              <div className="modal-actions">
                <button
                  type="button"
                  className="ghost"
                  onClick={() => handleDeleteAssignment(selectedStudyAssignment)}
                  disabled={studySaving}
                >
                  {studySaving ? "Deleting…" : "Delete assignment"}
                </button>
                <button type="button" className="ghost" onClick={() => !studySaving && setShowAssignmentDetailModal(false)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        )}

        {showSchedulerCreateModal && (
          <div className="modal-backdrop" onClick={() => !schedulerSaving && setShowSchedulerCreateModal(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Scheduler</p>
                  <h3>Create task</h3>
                </div>
                <button className="ghost" onClick={() => !schedulerSaving && setShowSchedulerCreateModal(false)}>Close</button>
              </div>
              <form onSubmit={handleCreateScheduledTask} className="modal-body">
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
                <div className="modal-actions">
                  <button type="button" className="ghost" onClick={() => !schedulerSaving && setShowSchedulerCreateModal(false)}>Cancel</button>
                  <button className="primary" type="submit" disabled={schedulerSaving}>
                    {schedulerSaving ? "Scheduling…" : "Create task"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {showSchedulerDetailModal && selectedSchedulerTask && (
          <div className="modal-backdrop" onClick={() => !schedulerSaving && setShowSchedulerDetailModal(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">Task detail</p>
                  <h3>{selectedSchedulerTask.prompt.slice(0, 60)}</h3>
                </div>
                <button className="ghost" onClick={() => !schedulerSaving && setShowSchedulerDetailModal(false)}>Close</button>
              </div>
              <div className="modal-body">
                {schedulerError && <div className="error-banner">{schedulerError}</div>}
                <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                  <div className="field">
                    <span className="eyebrow">Full prompt</span>
                    <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "0.75rem", borderRadius: "8px", fontSize: "0.9rem", lineHeight: "1.5" }}>{selectedSchedulerTask.prompt}</div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                    <div className="field">
                      <span className="eyebrow">Status</span>
                      <div style={{ fontSize: "0.95rem", color: "var(--text)" }}><strong>{selectedSchedulerTask.status}</strong></div>
                    </div>
                    <div className="field">
                      <span className="eyebrow">Recurrence</span>
                      <div style={{ fontSize: "0.95rem", color: "var(--text)" }}><strong>{selectedSchedulerTask.recurrence}</strong></div>
                    </div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                    <div className="field">
                      <span className="eyebrow">Next run</span>
                      <div style={{ fontSize: "0.95rem", color: "var(--muted)" }}>{selectedSchedulerTask.next_run_at ? new Date(selectedSchedulerTask.next_run_at).toLocaleString() : "—"}</div>
                    </div>
                    <div className="field">
                      <span className="eyebrow">Last run</span>
                      <div style={{ fontSize: "0.95rem", color: "var(--muted)" }}>{selectedSchedulerTask.last_run_at ? new Date(selectedSchedulerTask.last_run_at).toLocaleString() : "—"}</div>
                    </div>
                  </div>
                </div>
                <div className="modal-actions">
                  <button type="button" className="ghost" onClick={() => handleCancelSchedulerTask()} disabled={schedulerSaving || selectedSchedulerTask.status === "canceled"}>
                    {schedulerSaving ? "Canceling…" : "Cancel task"}
                  </button>
                  <button type="button" className="ghost" onClick={() => !schedulerSaving && setShowSchedulerDetailModal(false)}>Close</button>
                </div>
              </div>
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
                {(() => {
                  const lessonHomework = normalizeLessonHomework(selectedStudyLesson.homework);
                  const lessonHomeworkStats = homeworkProgress(lessonHomework);
                  const versions = topicAudiobookVersions[selectedStudyLesson.id] || [];
                  const isLoading = topicAudiobookLoadingByTopic[selectedStudyLesson.id] || false;
                  const isPreviewLoading = topicAudiobookPreviewLoadingByTopic[selectedStudyLesson.id] || false;
                  const notes = topicAudiobookNotesByTopic[selectedStudyLesson.id] || "";
                  const voice = topicAudiobookVoiceByTopic[selectedStudyLesson.id] || STUDY_AUDIOBOOK_VOICE_OPTIONS[0].value;
                  const previewUrl = topicAudiobookPreviewUrlByTopic[selectedStudyLesson.id] || "";
                  const why = String((selectedStudyLesson.metadata as Record<string, unknown> | undefined)?.why_it_matters || "").trim();
                  const prereqs = asStringList((selectedStudyLesson.metadata as Record<string, unknown> | undefined)?.prerequisite_assumptions);
                  const toKnow = asStringList((selectedStudyLesson.metadata as Record<string, unknown> | undefined)?.what_to_know);
                  const checks = asStringList((selectedStudyLesson.metadata as Record<string, unknown> | undefined)?.mastery_checks);
                  const pitfalls = asStringList((selectedStudyLesson.metadata as Record<string, unknown> | undefined)?.common_pitfalls);

                  return (
                    <>
                      <div className="study-lesson-tabs" role="tablist" aria-label="Lesson detail sections">
                        <button
                          className={`study-lesson-tab ${studyLessonDetailTab === "overview" ? "active" : ""}`}
                          onClick={() => setStudyLessonDetailTab("overview")}
                          role="tab"
                          aria-selected={studyLessonDetailTab === "overview"}
                        >
                          Overview
                        </button>
                        <button
                          className={`study-lesson-tab ${studyLessonDetailTab === "audiobooks" ? "active" : ""}`}
                          onClick={() => setStudyLessonDetailTab("audiobooks")}
                          role="tab"
                          aria-selected={studyLessonDetailTab === "audiobooks"}
                        >
                          Audiobooks
                        </button>
                      </div>

                      {studyLessonDetailTab === "overview" && (
                        <>
                          <section className="study-lesson-section">
                            <h4>Homework checklist</h4>
                            <div className="study-progress-block">
                              <div className="study-progress-label muted small">
                                Completed {lessonHomeworkStats.done}/{lessonHomeworkStats.total}
                              </div>
                              <div className="study-progress-track" aria-label="Lesson homework progress">
                                <div className="study-progress-fill" style={{ width: `${lessonHomeworkStats.percent}%` }} />
                              </div>
                            </div>
                            {lessonHomework.length ? (
                              <div className="study-homework-list">
                                {lessonHomework.map((item) => (
                                  <label key={item.assignment_id} className="study-homework-item">
                                    <input
                                      type="checkbox"
                                      checked={item.done}
                                      onChange={(e) =>
                                        handleToggleLessonHomework(
                                          selectedStudyLesson,
                                          item.assignment_id,
                                          e.target.checked,
                                        )
                                      }
                                      disabled={studySaving}
                                    />
                                    <span>
                                      {item.text}
                                      <span className="study-homework-source muted small">{formatHomeworkReference(item)}</span>
                                    </span>
                                  </label>
                                ))}
                              </div>
                            ) : (
                              <p className="muted small">No homework assigned to this lesson yet.</p>
                            )}
                          </section>

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

                          <section className="study-lesson-section">
                            <h4>Raw metadata</h4>
                            <pre className="study-log-dump">{JSON.stringify(selectedStudyLesson.metadata || {}, null, 2)}</pre>
                          </section>
                        </>
                      )}

                      {studyLessonDetailTab === "audiobooks" && (
                        <>
                          <section className="study-lesson-section">
                            <h4>Generate new version</h4>
                            <div className="study-audiobook-generate">
                              <select
                                className="study-audiobook-voice"
                                value={voice}
                                onChange={(e) =>
                                  setTopicAudiobookVoiceByTopic((prev) => ({
                                    ...prev,
                                    [selectedStudyLesson.id]: e.target.value,
                                  }))
                                }
                                disabled={isLoading || isPreviewLoading}
                              >
                                {STUDY_AUDIOBOOK_VOICE_OPTIONS.map((option) => (
                                  <option key={option.value} value={option.value}>
                                    {option.label}
                                  </option>
                                ))}
                              </select>
                              <textarea
                                className="study-audiobook-notes"
                                placeholder="Optional notes for generation (focus level, tone, examples, pacing)..."
                                value={notes}
                                rows={3}
                                onChange={(e) =>
                                  setTopicAudiobookNotesByTopic((prev) => ({
                                    ...prev,
                                    [selectedStudyLesson.id]: e.target.value,
                                  }))
                                }
                                disabled={isLoading || isPreviewLoading}
                              />
                              <div className="study-audiobook-actions">
                                <button
                                  className="ghost"
                                  onClick={() => handlePreviewTopicAudiobookVoice(selectedStudyLesson)}
                                  disabled={isLoading || isPreviewLoading}
                                >
                                  {isPreviewLoading ? "Previewing..." : "Preview voice"}
                                </button>
                                <button
                                  className="primary"
                                  onClick={() => handleGenerateTopicAudiobook(selectedStudyLesson)}
                                  disabled={isLoading || isPreviewLoading}
                                >
                                  {isLoading ? "Queuing..." : "Generate audiobook"}
                                </button>
                              </div>
                              {previewUrl && (
                                <audio controls src={previewUrl} className="study-audiobook-player study-audiobook-preview" />
                              )}
                            </div>
                          </section>

                          <section className="study-lesson-section">
                            <h4>Versions</h4>
                            {versions.length === 0 && <p className="muted small">No audiobook versions yet.</p>}
                            {versions.length > 0 && (
                              <div className="study-audiobook-list">
                                {versions.map((v) => (
                                  <div key={v.id} className="study-audiobook-item">
                                    <div className="study-audiobook-item-header">
                                      <span className="study-audiobook-version">Version {v.version_number}</span>
                                      <span className={`study-audiobook-status status-${v.status}`}>{v.status}</span>
                                      <span className="muted small">{v.created_at ? new Date(v.created_at).toLocaleString() : ""}</span>
                                    </div>
                                    <div className="study-audiobook-meta-grid">
                                      <span className="muted small">Voice: {v.tts_voice || "n/a"}</span>
                                      <span className="muted small">Engine: {v.tts_model || "n/a"}</span>
                                      <span className="muted small">Format: {v.audio_mime_type || "n/a"}</span>
                                    </div>
                                    {v.generation_notes && <p className="muted small">Prompt notes: {v.generation_notes}</p>}
                                    {v.status === "ready" && (
                                      <>
                                        <audio
                                          controls
                                          src={getTopicAudiobookDownloadUrl(selectedStudyLesson.id, v.id)}
                                          className="study-audiobook-player"
                                        />
                                        <a
                                          className="study-audiobook-link"
                                          href={getTopicAudiobookDownloadUrl(selectedStudyLesson.id, v.id)}
                                          target="_blank"
                                          rel="noreferrer"
                                        >
                                          Open or download audio
                                        </a>
                                      </>
                                    )}
                                    {v.status === "failed" && v.processing_error && (
                                      <p className="muted small study-audiobook-error">{v.processing_error}</p>
                                    )}
                                    {v.script_markdown && (
                                      <details className="study-audiobook-script">
                                        <summary>Show generated script</summary>
                                        <div className="study-output-body study-output-markdown">
                                          <ReactMarkdown>{v.script_markdown}</ReactMarkdown>
                                        </div>
                                      </details>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}
                          </section>
                        </>
                      )}
                    </>
                  );
                })()}
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
                <div className="study-output-body study-output-markdown">
                  <ReactMarkdown>{selectedStudyOutput.body}</ReactMarkdown>
                </div>
              </div>
            </div>
          </div>
        )}
        {calendarDetailEntry && (
          <div
            className="modal-backdrop"
            onClick={() => setCalendarDetailEntry(null)}
          >
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <p className="eyebrow">{calendarDetailEntry.kind === "soft" ? "Soft event slot" : "Calendar event"}</p>
                  <h3>{calendarDetailEntry.title}</h3>
                </div>
                <button className="ghost" onClick={() => setCalendarDetailEntry(null)}>Close</button>
              </div>
              <div className="modal-body">
                <div className="cal-detail-grid">
                  <div className="cal-detail-row">
                    <span className="cal-detail-label">Time</span>
                    <span>
                      {calendarDetailEntry.segmentStart.toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                      {" → "}
                      {calendarDetailEntry.segmentEnd.toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                  {calendarDetailEntry.description && (
                    <div className="cal-detail-row">
                      <span className="cal-detail-label">Description</span>
                      <span>{calendarDetailEntry.description}</span>
                    </div>
                  )}
                  {calendarDetailEntry.location && (
                    <div className="cal-detail-row">
                      <span className="cal-detail-label">Location</span>
                      <span>{calendarDetailEntry.location}</span>
                    </div>
                  )}
                  {calendarDetailEntry.kind === "soft" && (
                    <>
                      {calendarDetailEntry.status && (
                        <div className="cal-detail-row">
                          <span className="cal-detail-label">Status</span>
                          <span>{calendarDetailEntry.status}</span>
                        </div>
                      )}
                      {calendarDetailEntry.rationale && (
                        <div className="cal-detail-row">
                          <span className="cal-detail-label">Rationale</span>
                          <span>{calendarDetailEntry.rationale}</span>
                        </div>
                      )}
                      {typeof calendarDetailEntry.deferral_count === "number" && calendarDetailEntry.deferral_count > 0 && (
                        <div className="cal-detail-row">
                          <span className="cal-detail-label">Deferrals</span>
                          <span>{calendarDetailEntry.deferral_count}</span>
                        </div>
                      )}
                      {calendarDetailEntry.promoted && (
                        <div className="cal-detail-row">
                          <span className="cal-detail-label">Promoted</span>
                          <span>Yes — added to hard calendar</span>
                        </div>
                      )}
                      {calendarDetailEntry.soft_deadline && (
                        <div className="cal-detail-row">
                          <span className="cal-detail-label">Soft deadline</span>
                          <span>{formatDateTime(calendarDetailEntry.soft_deadline)}</span>
                        </div>
                      )}
                      {calendarDetailEntry.hard_deadline && (
                        <div className="cal-detail-row">
                          <span className="cal-detail-label">Hard deadline</span>
                          <span>{formatDateTime(calendarDetailEntry.hard_deadline)}</span>
                        </div>
                      )}
                    </>
                  )}
                </div>
                {calendarDetailEntry.kind === "hard" && (
                  <div className="hard-event-task-panel">
                    <div className="card-head" style={{ padding: 0, marginTop: "0.75rem" }}>
                      <div>
                        <p className="eyebrow">Objective tasks</p>
                        <h3>Count this hard event as planned work</h3>
                        <p className="muted small">Linked tasks are treated as already scheduled, and Corv will avoid rescheduling them.</p>
                      </div>
                    </div>
                    {calendarDetailEntry.task_links?.length ? (
                      <div className="calendar-list">
                        {calendarDetailEntry.task_links.map((link) => (
                          <div key={link.id} className="cal-row">
                            <div className="cal-badge soft">Task</div>
                            <div className="cal-body">
                              <div className="cal-title">{link.task_title}</div>
                              <div className="cal-meta muted small">
                                {link.objective_title}
                                {link.due_at ? ` · Due ${formatDateTime(link.due_at)}` : ""}
                              </div>
                            </div>
                            <button
                              type="button"
                              className="ghost pill-action"
                              onClick={() => handleDeleteHardEventTaskLink(link.id)}
                              disabled={hardEventTaskLinkLoading}
                            >
                              Remove
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="muted small">No objective tasks linked to this hard event yet.</p>
                    )}
                    <div className="hard-event-task-actions">
                      <label className="field">
                        <span>Add task</span>
                        <select
                          value={selectedHardEventTaskId}
                          onChange={(e) => setSelectedHardEventTaskId(e.target.value)}
                          disabled={hardEventTaskOptionsLoading || hardEventTaskLinkLoading}
                        >
                          <option value="">Select an objective task</option>
                          {availableHardEventTaskOptions.map((task) => (
                            <option key={task.id} value={task.id}>
                              {task.objective_title} - {task.title}
                              {task.due_at ? ` (due ${new Date(task.due_at).toLocaleDateString()})` : ""}
                            </option>
                          ))}
                        </select>
                      </label>
                      <button
                        type="button"
                        className="primary"
                        onClick={handleCreateHardEventTaskLink}
                        disabled={!selectedHardEventTaskId || hardEventTaskOptionsLoading || hardEventTaskLinkLoading}
                      >
                        {hardEventTaskLinkLoading ? "Saving…" : "Link task"}
                      </button>
                    </div>
                  </div>
                )}
                {calendarDetailEntry.kind === "soft" && calendarDetailEntry.soft_event_id && (
                  <div className="modal-actions" style={{ marginTop: "1.25rem" }}>
                    <div />
                    <div className="modal-actions-right">
                      <button className="ghost" onClick={() => setCalendarDetailEntry(null)}>Close</button>
                      <button
                        className="primary"
                        onClick={() => {
                          openSoftEventEditor(calendarDetailEntry.soft_event_id!);
                          setCalendarDetailEntry(null);
                        }}
                      >
                        Edit soft event
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
        {softEventModalOpen && (
          <div
            className="modal-backdrop"
            onClick={() => {
              if (!softEventLoading) {
                setSoftEventModalOpen(false);
                setSoftEventDraft(null);
                setSoftEventMetadata(null);
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
                    setSoftEventMetadata(null);
                  }}
                >
                  Close
                </button>
              </div>
              {softEventError && <div className="error-banner">{softEventError}</div>}
              <div className="modal-tabs" role="tablist" aria-label="Soft event detail tabs">
                <button
                  type="button"
                  className={`modal-tab ${softEventModalTab === "details" ? "active" : ""}`}
                  onClick={() => setSoftEventModalTab("details")}
                >
                  Details
                </button>
                <button
                  type="button"
                  className={`modal-tab ${softEventModalTab === "metadata" ? "active" : ""}`}
                  onClick={() => setSoftEventModalTab("metadata")}
                >
                  Raw metadata
                </button>
              </div>
              {softEventDraft ? (
                softEventModalTab === "details" ? (
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
                ) : (
                <div className="modal-body">
                  <pre className="study-log-dump">{JSON.stringify(softEventMetadata || {}, null, 2)}</pre>
                </div>
                )
              ) : (
                <div className="modal-body">
                  <p className="muted">Loading soft event details...</p>
                </div>
              )}
              <div className="modal-actions">
                {softEventMode === "edit" && softEventDraft?.id ? (
                  <button
                    type="button"
                    className="ghost pill-action danger"
                    onClick={handleDeleteSoftEvent}
                    disabled={softEventLoading}
                  >
                    {softEventLoading ? "Deleting…" : "Delete"}
                  </button>
                ) : (
                  <span />
                )}
                <div className="modal-actions-right">
                  <button
                    className="ghost"
                    onClick={() => {
                      if (softEventLoading) return;
                      setSoftEventModalOpen(false);
                      setSoftEventDraft(null);
                      setSoftEventMetadata(null);
                    }}
                  >
                    Cancel
                  </button>
                  <button className="primary" onClick={saveSoftEventDraft} disabled={softEventLoading || !softEventDraft}>
                    {softEventLoading ? "Saving…" : "Save"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
