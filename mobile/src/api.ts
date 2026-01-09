import AsyncStorage from "@react-native-async-storage/async-storage";
import { createApi } from "../../shared/api";

const API_BASE = process.env.EXPO_PUBLIC_API_BASE || "http://localhost:8000/api";

const api = createApi({
  baseUrl: API_BASE,
  getToken: () => AsyncStorage.getItem("appAccessToken"),
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
  fetchInboxMessages,
  markMessageRead,
  fetchCallSessions,
  createCallSession,
  updateCallSession,
  addCallTranscriptEntry,
  createRealtimeToken,
} = api;

export async function sendVoice(chat_id: string, uri: string) {
  const formData = new FormData();
  formData.append("chat_id", chat_id);
  formData.append("file", {
    uri,
    name: "voice.m4a",
    type: "audio/m4a",
  } as any);

  const token = await AsyncStorage.getItem("appAccessToken");
  const res = await fetch(`${API_BASE}/input/voice/`, {
    method: "POST",
    body: formData,
    headers: token ? { "X-App-Token": token } : undefined,
  });

  if (!res.ok) {
    const text = await res.text();
    const err: any = new Error(text || `Request failed with ${res.status}`);
    err.status = res.status;
    throw err;
  }

  return res.json();
}
