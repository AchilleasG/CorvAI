import { registerRootComponent } from "expo";
import messaging from "@react-native-firebase/messaging";
import notifee, { EventType } from "@notifee/react-native";

import App from "./App";
import { handleIncomingCallMessage } from "./src/push";

// registerRootComponent calls AppRegistry.registerComponent('main', () => App);
// It also ensures that whether you load the app in Expo Go or in a native build,
// the environment is set up appropriately
registerRootComponent(App);

messaging().setBackgroundMessageHandler(async (remoteMessage) => {
  await handleIncomingCallMessage(remoteMessage?.data);
});

notifee.onBackgroundEvent(async ({ type, detail }) => {
  if (detail?.notification?.data?.type !== "call_incoming") return;
  if (type === EventType.PRESS || type === EventType.ACTION_PRESS) {
    await handleIncomingCallMessage(detail.notification.data);
  }
});
