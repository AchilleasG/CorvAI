import AsyncStorage from "@react-native-async-storage/async-storage";
import RNCallKeep from "react-native-callkeep";

const CALLKEEP_MAP_KEY = "callkeepSessionMap";
let callKeepReady = false;

const callKeepOptions = {
  ios: {
    appName: "Corv",
  },
  android: {
    alertTitle: "Phone permission required",
    alertDescription: "Corv needs permission to show incoming calls.",
    cancelButton: "Cancel",
    okButton: "Allow",
    foregroundService: {
      channelId: "corv_calls",
      channelName: "Corv Calls",
      notificationTitle: "Incoming call",
      notificationIcon: "ic_launcher",
    },
  },
};

export async function ensureCallKeepSetup() {
  if (callKeepReady) return;
  try {
    await RNCallKeep.setup(callKeepOptions);
    RNCallKeep.setAvailable(true);
    callKeepReady = true;
  } catch (err) {
    // ignore setup failures; app will fallback to in-app UI
  }
}

export function showIncomingCall(callUUID: string, callerName: string) {
  RNCallKeep.displayIncomingCall(callUUID, callerName, callerName, "number", true);
}

export function bringAppToForeground() {
  RNCallKeep.backToForeground();
}

export async function storeCallSessionMapping(callUUID: string, sessionId: string) {
  const raw = await AsyncStorage.getItem(CALLKEEP_MAP_KEY);
  const map = raw ? JSON.parse(raw) : {};
  map[callUUID] = sessionId;
  await AsyncStorage.setItem(CALLKEEP_MAP_KEY, JSON.stringify(map));
}

export async function getSessionIdForCallUUID(callUUID: string): Promise<string | null> {
  const raw = await AsyncStorage.getItem(CALLKEEP_MAP_KEY);
  if (!raw) return null;
  try {
    const map = JSON.parse(raw);
    return map[callUUID] || null;
  } catch {
    return null;
  }
}

export async function clearSessionIdForCallUUID(callUUID: string) {
  const raw = await AsyncStorage.getItem(CALLKEEP_MAP_KEY);
  if (!raw) return;
  try {
    const map = JSON.parse(raw);
    delete map[callUUID];
    await AsyncStorage.setItem(CALLKEEP_MAP_KEY, JSON.stringify(map));
  } catch {
    // ignore
  }
}

type CallKeepHandlers = {
  onAnswer: (callUUID: string) => void | Promise<void>;
  onEnd: (callUUID: string) => void | Promise<void>;
};

export function registerCallKeepHandlers(handlers: CallKeepHandlers) {
  const answerHandler = ({ callUUID }: { callUUID: string }) => {
    handlers.onAnswer(callUUID);
  };
  const endHandler = ({ callUUID }: { callUUID: string }) => {
    handlers.onEnd(callUUID);
  };
  RNCallKeep.addEventListener("answerCall", answerHandler);
  RNCallKeep.addEventListener("endCall", endHandler);
  return () => {
    RNCallKeep.removeEventListener("answerCall", answerHandler);
    RNCallKeep.removeEventListener("endCall", endHandler);
  };
}

export function createCallUUID() {
  const hex = () => Math.floor((1 + Math.random()) * 0x10000).toString(16).slice(1);
  return `${hex()}${hex()}-${hex()}-${hex()}-${hex()}-${hex()}${hex()}${hex()}`;
}
