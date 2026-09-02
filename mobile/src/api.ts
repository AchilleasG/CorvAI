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
  updatePresence,
  fetchMessages,
  uploadFile,
  fetchJobMessages,
  fetchJobMessagesDirect,
  sendText,
  fetchJobs,
  cancelJob,
  fetchUsageRecent,
  fetchUsageSummary,
  fetchSettings,
  updateSettings,
  previewCallVoice,
  fetchCalendarCombined,
  fetchObjectiveRoots,
  fetchObjectiveTree,
  fetchObjective,
  createObjective,
  updateObjective,
  deleteObjective,
  createObjectiveTask,
  updateObjectiveTask,
  deleteObjectiveTask,
  fetchObjectiveLogs,
  createObjectiveLog,
  updateObjectiveLog,
  deleteObjectiveLog,
  fetchStudyCourses,
  fetchStudyTopics,
  fetchStudyExams,
  createStudyCourse,
  createStudyTopic,
  createStudyExam,
  updateStudyTopic,
  fetchStudyMaterials,
  uploadStudyMaterial,
  createSoftEvent,
  promoteSoftSlot,
  markSoftSlotOutcome,
  replanCalendar,
  fetchSoftEvent,
  updateSoftEvent,
  deleteSoftEvent,
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
  runCallAction,
  fetchSshMachines,
  createSshMachine,
  updateSshMachine,
  deleteSshMachine,
  connectSshMachine,
  disconnectSshMachine,
  fetchSshTerminalSessions,
  createSshTerminalSession,
  closeSshTerminalSession,
  runSshTerminalCommand,
  fetchCodingStatus,
  fetchCodingDeviceAuth,
  startCodingDeviceAuth,
  cancelCodingDeviceAuth,
  logoutCodingCodex,
  fetchCodingSessions,
  fetchCodingSession,
  createCodingSession,
  deleteCodingSession,
  startCodingTask,
  answerCodingDecision,
  startCodingTerminal,
  fetchCodingTerminal,
  sendCodingTerminalInput,
  closeCodingTerminal,
  stopCodingSession,
  resumeCodingSession,
  fetchCodingSessionLogs,
  fetchFeatureDelegations,
  fetchFeatureDelegation,
  createFeatureDelegation,
  resumeFeatureDelegation,
  stopFeatureDelegation,
} = api;

export async function sendVoice(chat_id: string, uri: string, metadata: Record<string, unknown> = {}) {
  const formData = new FormData();
  formData.append("chat_id", chat_id);
  formData.append("metadata", JSON.stringify(metadata));
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
