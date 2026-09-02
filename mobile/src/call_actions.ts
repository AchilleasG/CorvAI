import AsyncStorage from "@react-native-async-storage/async-storage";

import { updateCallSession, fetchCallSessions } from "./api";
import { cancelIncomingCallNotification } from "./notifications";

const PENDING_ANSWER_KEY = "pendingAnswerSessionId";

export async function setPendingAnswerSession(sessionId: string) {
  await AsyncStorage.setItem(PENDING_ANSWER_KEY, sessionId);
}

export async function consumePendingAnswerSession(): Promise<string | null> {
  const sessionId = await AsyncStorage.getItem(PENDING_ANSWER_KEY);
  if (sessionId) {
    await AsyncStorage.removeItem(PENDING_ANSWER_KEY);
    return sessionId;
  }
  return null;
}

export async function answerCallFromNotification(sessionId: string) {
  await updateCallSession(sessionId, { status: "in_call" });
  await setPendingAnswerSession(sessionId);
  await cancelIncomingCallNotification();
}

export async function declineCallFromNotification(sessionId: string) {
  await updateCallSession(sessionId, { status: "missed" });
  await cancelIncomingCallNotification();
}

export async function fetchCallById(sessionId: string) {
  const sessions = await fetchCallSessions({ platform: "mobile" });
  return sessions.find((s) => s.id === sessionId) || null;
}
