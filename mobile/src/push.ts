import messaging from "@react-native-firebase/messaging";
import { Platform } from "react-native";

import { registerPushToken } from "./api";
import {
  createCallUUID,
  ensureCallKeepSetup,
  showIncomingCall,
  storeCallSessionMapping,
} from "./callkeep";

const CALL_TYPE = "call_incoming";

export async function registerFcmPushToken() {
  if (Platform.OS !== "android") return;
  try {
    await messaging().registerDeviceForRemoteMessages();
    const status = await messaging().requestPermission();
    const token = await messaging().getToken();
    if (!token) return;
    await registerPushToken({ token, platform: "android_fcm" });
    console.log("[push] registered fcm token", token, "status", status);
    return token;
  } catch (err) {
    console.warn("[push] failed to register fcm token", err);
  }
}

type IncomingCallPayload = {
  call_session_id?: string;
  title?: string;
  body?: string;
  type?: string;
};

export async function handleIncomingCallMessage(data: IncomingCallPayload | undefined | null) {
  if (!data || data.type !== CALL_TYPE) return;
  const sessionId = data.call_session_id;
  if (!sessionId) return;
  const callerName = data.title || "Incoming call";
  const callUUID = createCallUUID();
  await ensureCallKeepSetup();
  await storeCallSessionMapping(callUUID, sessionId);
  showIncomingCall(callUUID, callerName);
}
