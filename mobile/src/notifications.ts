import notifee, {
  AndroidCategory,
  AndroidImportance,
  AndroidVisibility,
} from "@notifee/react-native";

const CALL_CHANNEL_ID = "corv_calls";
const CALL_NOTIFICATION_ID = "corv_incoming_call";
const MESSAGE_CHANNEL_ID = "corv_messages";
const CODING_CHANNEL_ID = "corv_coding";

export type CallNotificationPayload = {
  call_session_id?: string;
  title?: string;
  body?: string;
  type?: string;
};

export type MessageNotificationPayload = {
  message_id?: string;
  title?: string;
  body?: string;
  type?: string;
};

export type CodingNotificationPayload = {
  session_id?: string;
  delegation_id?: string;
  event?: string;
  title?: string;
  body?: string;
  type?: string;
};

export async function ensureCallChannel() {
  return notifee.createChannel({
    id: CALL_CHANNEL_ID,
    name: "Corv Calls",
    sound: "corv_call",
    importance: AndroidImportance.HIGH,
    vibration: true,
  });
}

export async function showIncomingCallNotification(payload: CallNotificationPayload) {
  const channelId = await ensureCallChannel();
  const title = payload.title || "Incoming call";
  const body = payload.body || "Call from Corv";
  const data: Record<string, string> = {};
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      data[key] = String(value);
    }
  });
  await notifee.displayNotification({
    id: CALL_NOTIFICATION_ID,
    title,
    body,
    data,
    android: {
      channelId,
      sound: "corv_call",
      importance: AndroidImportance.HIGH,
      category: AndroidCategory.CALL,
      visibility: AndroidVisibility.PUBLIC,
      pressAction: { id: "default" },
      fullScreenAction: { id: "answer", launchActivity: "default" },
      ongoing: true,
      autoCancel: true,
      actions: [
        {
          title: "Answer",
          pressAction: { id: "answer", launchActivity: "default" },
        },
        {
          title: "Decline",
          pressAction: { id: "decline" },
        },
      ],
    },
  });
}

export async function ensureMessageChannel() {
  return notifee.createChannel({
    id: MESSAGE_CHANNEL_ID,
    name: "Corv Messages",
    importance: AndroidImportance.DEFAULT,
  });
}

export async function showMessageNotification(payload: MessageNotificationPayload) {
  const channelId = await ensureMessageChannel();
  const title = payload.title || "New message";
  const body = payload.body || "You have a new message.";
  const data: Record<string, string> = {};
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      data[key] = String(value);
    }
  });
  await notifee.displayNotification({
    title,
    body,
    data,
    android: {
      channelId,
      importance: AndroidImportance.DEFAULT,
      category: AndroidCategory.MESSAGE,
      visibility: AndroidVisibility.PRIVATE,
      pressAction: { id: "default" },
      autoCancel: true,
    },
  });
}

export async function showCodingNotification(payload: CodingNotificationPayload) {
  const channelId = await ensureCodingChannel();
  const data: Record<string, string> = {};
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null) data[key] = String(value);
  });
  await notifee.displayNotification({
    title: payload.title || "Coding session update",
    body: payload.body || "A coding session needs your attention.",
    data,
    android: {
      channelId,
      importance: AndroidImportance.HIGH,
      category: AndroidCategory.MESSAGE,
      visibility: AndroidVisibility.PRIVATE,
      pressAction: { id: "default" },
      autoCancel: true,
    },
  });
}

export async function ensureCodingChannel() {
  return notifee.createChannel({
    id: CODING_CHANNEL_ID,
    name: "Corv Coding",
    importance: AndroidImportance.HIGH,
    vibration: true,
  });
}

export async function cancelIncomingCallNotification() {
  try {
    await notifee.cancelNotification(CALL_NOTIFICATION_ID);
  } catch {
    // ignore cancel failures
  }
}
