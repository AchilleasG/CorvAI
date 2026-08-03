import { registerRootComponent } from "expo";
import messaging from "@react-native-firebase/messaging";
import notifee, { EventType } from "@notifee/react-native";

import App from "./App";
import { handleIncomingCallMessage } from "./src/push";
import { answerCallFromNotification, declineCallFromNotification } from "./src/call_actions";

// registerRootComponent calls AppRegistry.registerComponent('main', () => App);
// It also ensures that whether you load the app in Expo Go or in a native build,
// the environment is set up appropriately
registerRootComponent(App);

messaging().setBackgroundMessageHandler(async (remoteMessage) => {
  await handleIncomingCallMessage(remoteMessage?.data);
});

notifee.onBackgroundEvent(async ({ type, detail }) => {
  if (detail?.notification?.data?.type !== "call_incoming") return;
  if (type === EventType.ACTION_PRESS && detail.pressAction?.id === "answer") {
    const sessionId = detail.notification?.data?.call_session_id;
    if (sessionId) {
      await answerCallFromNotification(String(sessionId));
    }
    return;
  }
  if (type === EventType.ACTION_PRESS && detail.pressAction?.id === "decline") {
    const sessionId = detail.notification?.data?.call_session_id;
    if (sessionId) {
      await declineCallFromNotification(String(sessionId));
    }
    return;
  }
});
