import notifee, {
  AndroidCategory,
  AndroidImportance,
  AndroidVisibility,
} from "@notifee/react-native";

const CALL_CHANNEL_ID = "corv_calls";

export type CallNotificationPayload = {
  call_session_id?: string;
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
