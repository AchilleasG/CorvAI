import { createApi } from "../../shared/api";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

const api = createApi({
  baseUrl: API_BASE,
  getToken: () => localStorage.getItem("appAccessToken"),
});

export const {
  fetchChats,
  createChat,
  renameChat,
  deleteChat,
  fetchMessages,
  fetchJobMessages,
  fetchJobMessagesDirect,
  sendText,
  sendVoice,
  fetchJobs,
  cancelJob,
  fetchUsageRecent,
  fetchUsageSummary,
  fetchSettings,
  updateSettings,
  fetchCalendarCombined,
  fetchScheduledTasks,
  createScheduledTask,
  updateScheduledTask,
  fetchScheduledTaskRuns,
  registerPushToken,
  fetchMessages,
  markMessageRead,
  fetchCallSessions,
  createCallSession,
  updateCallSession,
  addCallTranscriptEntry,
  createRealtimeToken,
} = api;
