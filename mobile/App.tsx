import { StatusBar } from "expo-status-bar";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  Modal,
  Platform,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { SafeAreaProvider, useSafeAreaInsets } from "react-native-safe-area-context";
import * as DocumentPicker from "expo-document-picker";
import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import Constants from "expo-constants";
import messaging from "@react-native-firebase/messaging";
import notifee, { EventType } from "@notifee/react-native";
import DateTimePicker from "@react-native-community/datetimepicker";
import {
  RTCPeerConnection,
  RTCSessionDescription,
  mediaDevices,
} from "react-native-webrtc";
import {
  cancelJob,
  createChat,
  deleteChat,
  fetchChats,
  fetchJobs,
  fetchMessages,
  fetchJobMessagesDirect,
  fetchSettings,
  fetchUsageRecent,
  fetchUsageSummary,
  fetchCalendarCombined,
  fetchStudyCourses,
  fetchStudyMaterials,
  createSoftEvent,
  promoteSoftSlot,
  replanCalendar,
  fetchSoftEvent,
  createStudyCourse,
  uploadStudyMaterial,
  renameChat,
  sendText,
  sendVoice,
  updateSettings,
  fetchScheduledTasks,
  createScheduledTask,
  updateScheduledTask,
  fetchScheduledTaskRuns,
  updateSoftEvent,
  registerPushToken,
  fetchInboxMessages,
  markMessageRead,
  fetchCallSessions,
  createCallSession,
  updateCallSession,
  addCallTranscriptEntry,
  createRealtimeToken,
} from "./src/api";
import { registerFcmPushToken } from "./src/push";
import {
  cancelIncomingCallNotification,
  showIncomingCallNotification,
  showMessageNotification,
} from "./src/notifications";
import { consumePendingAnswerSession, fetchCallById } from "./src/call_actions";
import {
  ChatListItem,
  CombinedCalendar,
  StudyCourse,
  StudyMaterial,
  SoftEventDetail,
  Job,
  Message,
  SettingsPayload,
  UsageEvent,
  UsageSummary,
  ScheduledTask,
  ScheduledTaskRun,
  UserMessage,
  CallSession,
} from "./src/types";
import { Audio } from "expo-av";
import { Ionicons } from "@expo/vector-icons";

type TabKey = "chat" | "settings" | "study" | "calendar" | "scheduler" | "messages" | "calls";

type SoftEventDraft = {
  id: string;
  title: string;
  description: string;
  notes: string;
  preferred_duration_minutes: string;
  min_duration_minutes: string;
  soft_deadline: string;
  hard_deadline: string;
  frequency: string;
  deferral_limit: string;
  priority: string;
  status: SoftEventDetail["status"];
};

type SoftEventMode = "create" | "edit";

type StudyFileDraft = {
  uri: string;
  name: string;
  type?: string | null;
};

function formatChatLabel(chat: ChatListItem) {
  if (chat.chat_nickname && chat.chat_nickname.trim()) {
    return chat.chat_nickname.trim();
  }
  return `Chat ${chat.chat_id.slice(0, 6)}`;
}

function formatTime(value?: string | null) {
  if (!value) return "";
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(value?: string | null) {
  if (!value) return "";
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function RoleBadge({ role }: { role: Message["role"] }) {
  const label = role === "assistant" ? "Corv" : role === "user" ? "You" : "System";
  return (
    <View style={[styles.badge, role === "assistant" ? styles.badgeAssistant : styles.badgeUser]}>
      <Text style={[styles.badgeText, role === "assistant" ? styles.badgeTextLight : styles.badgeTextDark]}>
        {label}
      </Text>
    </View>
  );
}

type MessageBubbleProps = {
  msg: Message;
  isLastJobMessage: boolean;
  onShowJobLog: (jobId: string) => void;
};

function MessageBubble({ msg, isLastJobMessage, onShowJobLog }: MessageBubbleProps) {
  const isUser = msg.role === "user";
  return (
    <View style={[styles.messageRow, isUser ? styles.messageRowUser : styles.messageRowAssistant]}>
      <RoleBadge role={msg.role} />
      <View style={[styles.messageBubble, isUser ? styles.messageBubbleUser : styles.messageBubbleAssistant]}>
        <Text style={isUser ? styles.messageTextUser : styles.messageTextAssistant}>{msg.text}</Text>
        {!!msg.created_at && (
          <Text style={isUser ? styles.messageTimeUser : styles.messageTimeAssistant}>
            {formatTime(msg.created_at)}
          </Text>
        )}
        {msg.job_id && isLastJobMessage && (
          <TouchableOpacity
            style={styles.jobLogButton}
            onPress={() => onShowJobLog(msg.job_id!)}
          >
            <Text style={styles.jobLogButtonText}>View job log</Text>
          </TouchableOpacity>
        )}
      </View>
    </View>
  );
}

function InnerApp() {
  const insets = useSafeAreaInsets();
  const [authed, setAuthed] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);
  const [passwordInput, setPasswordInput] = useState("");
  const [activeTab, setActiveTab] = useState<TabKey>("chat");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [chats, setChats] = useState<ChatListItem[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [usageRecent, setUsageRecent] = useState<UsageEvent[]>([]);
  const [usageSummary, setUsageSummary] = useState<UsageSummary | null>(null);
  const [settings, setSettings] = useState<SettingsPayload>({});
  const [settingsDraft, setSettingsDraft] = useState<SettingsPayload>({});
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [studyCourses, setStudyCourses] = useState<StudyCourse[]>([]);
  const [studyMaterials, setStudyMaterials] = useState<StudyMaterial[]>([]);
  const [studyLoading, setStudyLoading] = useState(false);
  const [studySaving, setStudySaving] = useState(false);
  const [studyError, setStudyError] = useState<string | null>(null);
  const [studyCourseTitle, setStudyCourseTitle] = useState("");
  const [studyCourseCode, setStudyCourseCode] = useState("");
  const [studyCourseDescription, setStudyCourseDescription] = useState("");
  const [studyMaterialTitle, setStudyMaterialTitle] = useState("");
  const [studyMaterialKind, setStudyMaterialKind] = useState("lecture");
  const [studyMaterialNotes, setStudyMaterialNotes] = useState("");
  const [studyMaterialFile, setStudyMaterialFile] = useState<StudyFileDraft | null>(null);
  const [studySelectedCourseId, setStudySelectedCourseId] = useState<string | null>(null);
  const [scheduledTasks, setScheduledTasks] = useState<ScheduledTask[]>([]);
  const [schedulerError, setSchedulerError] = useState<string | null>(null);
  const [schedulerLoading, setSchedulerLoading] = useState(false);
  const [schedulerPrompt, setSchedulerPrompt] = useState("");
  const [schedulerStartAt, setSchedulerStartAt] = useState("");
  const [schedulerRecurrence, setSchedulerRecurrence] = useState<"once" | "daily" | "weekly" | "monthly">("once");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [taskRuns, setTaskRuns] = useState<ScheduledTaskRun[]>([]);
  const [taskRunsLoading, setTaskRunsLoading] = useState(false);
  const [messagesInbox, setMessagesInbox] = useState<UserMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [callSessions, setCallSessions] = useState<CallSession[]>([]);
  const [callsLoading, setCallsLoading] = useState(false);
  const [incomingCall, setIncomingCall] = useState<CallSession | null>(null);
  const [activeCall, setActiveCall] = useState<CallSession | null>(null);
  const [callConnecting, setCallConnecting] = useState(false);
  const [callLiveTranscript, setCallLiveTranscript] = useState<string[]>([]);
  const [callTranscriptError, setCallTranscriptError] = useState<string | null>(null);
  const appStateRef = useRef<string>(AppState.currentState);
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<any>(null);
  const localStreamRef = useRef<any>(null);
  const endCallRef = useRef(false);
  const endSignalReceivedRef = useRef(false);
  const endSignalPromptedRef = useRef(false);
  const outputTextBufferRef = useRef("");
  const lastAssistantTextRef = useRef("");
  const [summaryModalVisible, setSummaryModalVisible] = useState(false);
  const [summaryModalText, setSummaryModalText] = useState("");
  const [calendarData, setCalendarData] = useState<CombinedCalendar | null>(null);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [selectedDayKey, setSelectedDayKey] = useState<string | null>(null);
  const [replanLoading, setReplanLoading] = useState(false);
  const [replanNoteVisible, setReplanNoteVisible] = useState(false);
  const [replanNote, setReplanNote] = useState("");
  const [promoteLoadingId, setPromoteLoadingId] = useState<string | null>(null);
  const [softEventModalVisible, setSoftEventModalVisible] = useState(false);
  const [softEventLoading, setSoftEventLoading] = useState(false);
  const [softEventError, setSoftEventError] = useState<string | null>(null);
  const [softEventDraft, setSoftEventDraft] = useState<SoftEventDraft | null>(null);
  const [softEventMode, setSoftEventMode] = useState<SoftEventMode>("edit");
  const [datePickerField, setDatePickerField] = useState<"soft_deadline" | "hard_deadline" | null>(
    null,
  );
  const [datePickerValue, setDatePickerValue] = useState<Date>(new Date());
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [voiceSending, setVoiceSending] = useState(false);
  const [keyboardVisible, setKeyboardVisible] = useState(false);
  const [renameVisible, setRenameVisible] = useState(false);
  const [renameChatId, setRenameChatId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [headerHeight, setHeaderHeight] = useState(0);
  const [jobLogMessages, setJobLogMessages] = useState<Message[]>([]);
  const [jobLogVisible, setJobLogVisible] = useState(false);
  const [jobLogAnchorId, setJobLogAnchorId] = useState<string | null>(null);
  const messagesListRef = useRef<FlatList<Message> | null>(null);
  const recordingRef = useRef<Audio.Recording | null>(null);
  const callSeqRef = useRef(0);

  const selectedStudyCourse = useMemo(
    () => studyCourses.find((course) => course.id === studySelectedCourseId) || null,
    [studyCourses, studySelectedCourseId],
  );

  function handleAuthError(err: any): boolean {
    const status = err?.status;
    const msg = (err?.message || "").toString().toLowerCase();
    if (status === 401 || msg.includes("unauthorized")) {
      AsyncStorage.removeItem("appAccessToken").catch(() => undefined);
      setAuthed(false);
      setAuthError("Access password required or invalid. Please sign in again.");
      return true;
    }
    return false;
  }

  useEffect(() => {
    AsyncStorage.getItem("appAccessToken")
      .then((token) => {
        setAuthed(!!token);
      })
      .finally(() => setAuthLoading(false));
  }, []);

  useEffect(() => {
    Notifications.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowAlert: true,
        shouldPlaySound: true,
        shouldSetBadge: true,
      }),
    });
  }, []);

  useEffect(() => {
    if (!authed) return;
    const receivedSub = Notifications.addNotificationReceivedListener((notification) => {
      const data = notification.request.content.data as { type?: string } | undefined;
      if (data?.type === "call_incoming") {
        void refreshCallSessions();
      }
      if (data?.type === "user_message") {
        void refreshMessages();
      }
    });
    const responseSub = Notifications.addNotificationResponseReceivedListener((response) => {
      const data = response.notification.request.content.data as { type?: string } | undefined;
      if (data?.type === "call_incoming") {
        void refreshCallSessions();
      }
      if (data?.type === "user_message") {
        void refreshMessages();
      }
    });
    return () => {
      receivedSub.remove();
      responseSub.remove();
    };
  }, [authed]);

  useEffect(() => {
    if (!authed) return;
    (async () => {
      if (!Device.isDevice) return;
      try {
        const { status: existingStatus } = await Notifications.getPermissionsAsync();
        let finalStatus = existingStatus;
        if (existingStatus !== "granted") {
          const { status } = await Notifications.requestPermissionsAsync();
          finalStatus = status;
        }
        if (finalStatus === "granted") {
          const projectId =
            Constants.easConfig?.projectId || Constants.expoConfig?.extra?.eas?.projectId;
          if (projectId) {
            const token = await Notifications.getExpoPushTokenAsync({ projectId });
            await registerPushToken({
              token: token.data,
              platform: Platform.OS,
            });
          }
        }
      } catch (err) {
        // ignore expo push registration errors
      }
      try {
        await registerFcmPushToken();
      } catch {
        // ignore fcm registration errors
      }
    })();
  }, [authed]);

  useEffect(() => {
    if (!authed) return;
    let mounted = true;
    const appStateSub = AppState.addEventListener("change", (state) => {
      appStateRef.current = state;
    });

    const unsubscribeMessage = messaging().onMessage(async (remoteMessage) => {
      const messageType = remoteMessage?.data?.type;
      if (messageType === "call_incoming" && mounted) {
        await showIncomingCallNotification(remoteMessage?.data);
        await refreshCallSessions();
      }
      if (messageType === "user_message" && mounted) {
        const title =
          remoteMessage?.notification?.title ||
          remoteMessage?.data?.title ||
          "New message";
        const body =
          remoteMessage?.notification?.body ||
          remoteMessage?.data?.body ||
          "You have a new message.";
        await showMessageNotification({
          message_id: remoteMessage?.data?.message_id,
          title,
          body,
          type: "user_message",
        });
        await refreshMessages();
      }
    });

    const unsubscribeOpened = messaging().onNotificationOpenedApp(async (remoteMessage) => {
      if (remoteMessage?.data?.type === "call_incoming") {
        await refreshCallSessions();
      }
      if (remoteMessage?.data?.type === "user_message") {
        await refreshMessages();
      }
    });

    messaging()
      .getInitialNotification()
      .then((remoteMessage) => {
        if (!mounted) return;
        if (remoteMessage?.data?.type === "call_incoming") {
          void refreshCallSessions();
        }
        if (remoteMessage?.data?.type === "user_message") {
          void refreshMessages();
        }
      });

    const unsubscribeNotifee = notifee.onForegroundEvent(async ({ type, detail }) => {
      const dataType = detail?.notification?.data?.type;
      if (!dataType) return;
      if (type === EventType.DISMISSED) {
        return;
      }
      if (dataType === "call_incoming") {
        if (type === EventType.PRESS) {
          await refreshCallSessions();
        }
        if (type === EventType.ACTION_PRESS && detail.pressAction?.id === "answer") {
          const sessionId = detail.notification?.data?.call_session_id;
          if (sessionId) {
            await answerCallSession(sessionId);
          }
        }
        if (type === EventType.ACTION_PRESS && detail.pressAction?.id === "decline") {
          const sessionId = detail.notification?.data?.call_session_id;
          if (sessionId) {
            await declineCallSession(sessionId);
          }
        }
        return;
      }
      if (dataType === "user_message") {
        if (type === EventType.PRESS) {
          await refreshMessages();
        }
      }
    });

    return () => {
      mounted = false;
      unsubscribeMessage();
      unsubscribeOpened();
      unsubscribeNotifee();
      appStateSub.remove();
    };
  }, [authed, activeCall]);

  useEffect(() => {
    if (!authed) return;
    let canceled = false;
    (async () => {
      const pendingId = await consumePendingAnswerSession();
      if (!pendingId || canceled) return;
      const session = await fetchCallById(pendingId);
      if (session) {
        setActiveCall(session);
        await startRealtimeCall(session);
      }
    })();
    return () => {
      canceled = true;
    };
  }, [authed]);

  useEffect(() => {
    if (!authed) return;
    (async () => {
      await refreshChats();
      try {
        const [recent, summary, settingsResp] = await Promise.all([
          fetchUsageRecent(20),
          fetchUsageSummary(7),
          fetchSettings(),
        ]);
        setUsageRecent(recent);
        setUsageSummary(summary);
        setSettings(settingsResp);
        setSettingsDraft(settingsResp);
      } catch (err) {
        if (handleAuthError(err)) return;
      }
    })();
  }, [authed]);

  useEffect(() => {
    if (!authed) return;
    if (!activeChatId) {
      setMessages([]);
      setJobs([]);
      return;
    }
    setLoadingMessages(true);
    Promise.all([fetchMessages(activeChatId, true), fetchJobs(activeChatId)])
      .then(([msgs, jobsData]) => {
        setMessages(msgs);
        setJobs(jobsData);
      })
      .catch((err) => {
        if (handleAuthError(err)) return;
        setError(err.message || "Failed to load messages");
      })
      .finally(() => setLoadingMessages(false));
  }, [activeChatId, authed]);

  useEffect(() => {
    if (!authed) return;
    if (activeTab !== "calendar") return;
    refreshCalendar();
  }, [activeTab, authed]);

  useEffect(() => {
    if (!authed) return;
    if (activeTab !== "scheduler") return;
    refreshScheduledTasks();
  }, [activeTab, authed]);

  useEffect(() => {
    if (!authed) return;
    if (activeTab !== "messages") return;
    refreshMessages();
  }, [activeTab, authed]);

  useEffect(() => {
    if (!authed) return;
    if (activeTab !== "calls") return;
    refreshCallSessions();
  }, [activeTab, authed]);

  useEffect(() => {
    if (!authed) return;
    if (activeTab !== "study") return;
    refreshStudyData();
  }, [activeTab, authed, studySelectedCourseId]);

  useEffect(() => {
    if (!authed) return;
    const id = setInterval(() => {
      refreshCallSessions();
    }, 15000);
    return () => clearInterval(id);
  }, [authed]);

  useEffect(() => {
    if (!authed) return;
    if (!activeChatId) return;
    const id = setInterval(() => {
      fetchMessages(activeChatId, true)
        .then((msgs) => setMessages(msgs))
        .catch((err) => {
          handleAuthError(err);
        });
    }, 3000);
    return () => clearInterval(id);
  }, [activeChatId, authed]);

  useEffect(() => {
    if (messages.length === 0) return;
    setTimeout(() => {
      messagesListRef.current?.scrollToEnd({ animated: true });
    }, 0);
  }, [messages.length]);

  useEffect(() => {
    const showSub = Keyboard.addListener("keyboardDidShow", () => setKeyboardVisible(true));
    const hideSub = Keyboard.addListener("keyboardDidHide", () => setKeyboardVisible(false));
    return () => {
      showSub.remove();
      hideSub.remove();
    };
  }, []);

  const sortedChats = useMemo(() => {
    return [...chats].sort((a, b) => {
      const aTime = a.last_activity_at ? new Date(a.last_activity_at).getTime() : 0;
      const bTime = b.last_activity_at ? new Date(b.last_activity_at).getTime() : 0;
      return bTime - aTime;
    });
  }, [chats]);

  const lastJobMessageIndex = useMemo(() => {
    const map = new Map<string, number>();
    messages.forEach((msg, index) => {
      if (msg.job_id) {
        map.set(msg.job_id, index);
      }
    });
    return map;
  }, [messages]);

  const calendarDays = useMemo(() => {
    if (!calendarData) return [];
    const start = new Date(calendarData.window_start);
    const end = new Date(calendarData.window_end);
    const days: {
      key: string;
      date: Date;
      label: string;
      hard: CombinedCalendar["hard_events"];
      soft: CombinedCalendar["soft_slots"];
      hasSoftWarning: boolean;
      hasSoftWarningRed: boolean;
      hasSoftWarningOrange: boolean;
      isPlaceholder?: boolean;
    }[] = [];
    const cursor = new Date(start);
    cursor.setHours(0, 0, 0, 0);
    const endDay = new Date(end);
    endDay.setHours(23, 59, 59, 999);
    const firstDayIndex = (cursor.getDay() + 6) % 7;
    for (let i = 0; i < firstDayIndex; i += 1) {
      days.push({
        key: `pad-${i}`,
        date: new Date(cursor),
        label: "",
        hard: [],
        soft: [],
        hasSoftWarning: false,
        hasSoftWarningRed: false,
        hasSoftWarningOrange: false,
        isPlaceholder: true,
      });
    }
    while (cursor <= endDay) {
      const dayStart = new Date(cursor);
      const dayEnd = new Date(cursor);
      dayEnd.setHours(23, 59, 59, 999);
      const hard = calendarData.hard_events.filter((event) => {
        const evStart = new Date(event.start);
        const evEnd = new Date(event.end);
        return evStart <= dayEnd && evEnd >= dayStart;
      });
      const soft = calendarData.soft_slots.filter((slot) => {
        const evStart = new Date(slot.start);
        const evEnd = new Date(slot.end);
        return evStart <= dayEnd && evEnd >= dayStart;
      });
      let hasSoftWarningRed = false;
      let hasSoftWarningOrange = false;
      soft.forEach((slot) => {
        const slotEnd = new Date(slot.end).getTime();
        const hardDeadline = slot.hard_deadline ? new Date(slot.hard_deadline).getTime() : null;
        const softDeadline = slot.soft_deadline ? new Date(slot.soft_deadline).getTime() : null;
        if (hardDeadline && slotEnd > hardDeadline) {
          hasSoftWarningRed = true;
          return;
        }
        if (softDeadline && slotEnd > softDeadline) {
          hasSoftWarningOrange = true;
        }
      });
      days.push({
        key: dayStart.toISOString().slice(0, 10),
        date: dayStart,
        label: dayStart.toLocaleDateString([], { weekday: "short", day: "2-digit" }),
        hard,
        soft,
        hasSoftWarning: hasSoftWarningRed || hasSoftWarningOrange,
        hasSoftWarningRed,
        hasSoftWarningOrange,
      });
      cursor.setDate(cursor.getDate() + 1);
    }
    return days;
  }, [calendarData]);

  useEffect(() => {
    if (!calendarData) return;
    if (!calendarDays.length) return;
    if (!selectedDayKey) {
      const firstRealDay = calendarDays.find((day) => !day.isPlaceholder);
      if (firstRealDay) setSelectedDayKey(firstRealDay.key);
    }
  }, [calendarData, calendarDays, selectedDayKey]);

  async function refreshChats(preferredActiveId?: string | null) {
    try {
      const data = await fetchChats();
      setChats(data);
      if (preferredActiveId && data.some((c) => c.chat_id === preferredActiveId)) {
        setActiveChatId(preferredActiveId);
        return data;
      }
      if (!activeChatId && data.length) {
        setActiveChatId(data[0].chat_id);
      } else if (activeChatId && !data.some((c) => c.chat_id === activeChatId)) {
        const fallbackId = data[0]?.chat_id || null;
        setActiveChatId(fallbackId);
        if (!fallbackId) {
          setMessages([]);
          setJobs([]);
        }
      } else if (!data.length) {
        setActiveChatId(null);
        setMessages([]);
        setJobs([]);
      }
      return data;
    } catch (err: any) {
      if (handleAuthError(err)) return [];
      setError(err.message || "Failed to load chats");
      return [];
    }
  }

  async function ensureChat(): Promise<string> {
    if (activeChatId) return activeChatId;
    const created = await createChat("");
    await refreshChats(created.chat_id);
    return created.chat_id;
  }

  async function handleNewChat() {
    try {
      const created = await createChat("");
      await refreshChats(created.chat_id);
      setMessages([]);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setError(err.message || "Could not create chat");
    }
  }

  async function handleSend() {
    if (!input.trim()) return;
    try {
      setSending(true);
      setError(null);
      const chatId = await ensureChat();
      await sendText(chatId, input.trim());
      setInput("");
      const [msgs, jobsData] = await Promise.all([
        fetchMessages(chatId, true),
        fetchJobs(chatId),
      ]);
      await refreshChats(chatId);
      setMessages(msgs);
      setJobs(jobsData);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setError(err.message || "Failed to send");
    } finally {
      setSending(false);
    }
  }

  async function startVoiceRecording() {
    if (recording || voiceSending) return;
    try {
      const permission = await Audio.requestPermissionsAsync();
      if (!permission.granted) {
        setError("Microphone permission denied");
        return;
      }
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });
      const { recording: newRecording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
      );
      recordingRef.current = newRecording;
      setRecording(true);
    } catch (err: any) {
      setError(err.message || "Failed to start recording");
    }
  }

  async function stopVoiceRecording() {
    if (!recordingRef.current) return;
    try {
      setVoiceSending(true);
      setRecording(false);
      await recordingRef.current.stopAndUnloadAsync();
      const uri = recordingRef.current.getURI();
      recordingRef.current = null;
      if (!uri) {
        setError("No audio captured");
        return;
      }
      const chatId = await ensureChat();
      await sendVoice(chatId, uri);
      const [msgs, jobsData] = await Promise.all([
        fetchMessages(chatId, true),
        fetchJobs(chatId),
      ]);
      await refreshChats(chatId);
      setMessages(msgs);
      setJobs(jobsData);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setError(err.message || "Failed to send voice message");
    } finally {
      setVoiceSending(false);
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: false,
      });
    }
  }

  async function handleSaveSettings() {
    setSavingSettings(true);
    setSettingsError(null);
    try {
      const payload: SettingsPayload = {
        frontman_model: settingsDraft.frontman_model?.trim() || undefined,
        caller_model: settingsDraft.caller_model?.trim() || undefined,
        soft_planner_model: settingsDraft.soft_planner_model?.trim() || undefined,
        cache_mode: settingsDraft.cache_mode?.trim() || undefined,
        max_function_result_chars: settingsDraft.max_function_result_chars || undefined,
      };
      const updated = await updateSettings(payload);
      setSettings(updated);
      setSettingsDraft(updated);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSettingsError(err.message || "Failed to save settings");
    } finally {
      setSavingSettings(false);
    }
  }

  async function refreshScheduledTasks() {
    try {
      setSchedulerLoading(true);
      setSchedulerError(null);
      const tasks = await fetchScheduledTasks();
      setScheduledTasks(tasks);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSchedulerError(err.message || "Failed to load scheduled tasks");
    } finally {
      setSchedulerLoading(false);
    }
  }

  async function refreshStudyData() {
    try {
      setStudyLoading(true);
      setStudyError(null);
      const [{ courses }, materialsResp] = await Promise.all([
        fetchStudyCourses(),
        studySelectedCourseId ? fetchStudyMaterials(studySelectedCourseId) : Promise.resolve({ materials: [] as StudyMaterial[] }),
      ]);
      setStudyCourses(courses);
      if (!studySelectedCourseId && courses.length) {
        setStudySelectedCourseId(courses[0].id);
      }
      setStudyMaterials(materialsResp.materials || []);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to load study data");
    } finally {
      setStudyLoading(false);
    }
  }

  async function handlePickStudyFile() {
    try {
      const result: any = await DocumentPicker.getDocumentAsync({
        copyToCacheDirectory: true,
        multiple: false,
      } as any);
      if (result?.canceled || result?.cancelled) return;
      const asset = (result?.assets && result.assets[0]) || result;
      if (!asset?.uri) return;
      setStudyMaterialFile({
        uri: asset.uri,
        name: asset.name || "study-material",
        type: asset.mimeType || asset.type || "application/octet-stream",
      });
    } catch (err: any) {
      setStudyError(err.message || "Failed to pick file");
    }
  }

  async function handleCreateStudyCourse() {
    if (!studyCourseTitle.trim()) {
      setStudyError("Course title is required");
      return;
    }
    try {
      setStudySaving(true);
      setStudyError(null);
      const created = await createStudyCourse({
        title: studyCourseTitle.trim(),
        code: studyCourseCode.trim() || undefined,
        description: studyCourseDescription.trim() || undefined,
      });
      setStudyCourseTitle("");
      setStudyCourseCode("");
      setStudyCourseDescription("");
      setStudySelectedCourseId(created.id);
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to create course");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleUploadStudyMaterial() {
    if (!studySelectedCourseId) {
      setStudyError("Select or create a course first");
      return;
    }
    if (!studyMaterialTitle.trim()) {
      setStudyError("Material title is required");
      return;
    }
    if (!studyMaterialFile) {
      setStudyError("Pick a file first");
      return;
    }
    try {
      setStudySaving(true);
      setStudyError(null);
      const created = await uploadStudyMaterial({
        course_id: studySelectedCourseId,
        title: studyMaterialTitle.trim(),
        kind: studyMaterialKind,
        notes: studyMaterialNotes.trim(),
        file: studyMaterialFile,
        process_now: true,
      });
      setStudyMaterialTitle("");
      setStudyMaterialNotes("");
      setStudyMaterialFile(null);
      if (created?.job?.user_visible_summary) {
        setStudyError(`Queued: ${created.job.user_visible_summary}`);
      }
      await refreshStudyData();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setStudyError(err.message || "Failed to upload material");
    } finally {
      setStudySaving(false);
    }
  }

  async function handleCreateScheduledTask() {
    if (!schedulerPrompt.trim()) {
      setSchedulerError("Prompt is required");
      return;
    }
    try {
      setSchedulerError(null);
      const payload: { prompt: string; recurrence: string; start_at?: string } = {
        prompt: schedulerPrompt.trim(),
        recurrence: schedulerRecurrence,
      };
      if (schedulerStartAt.trim()) {
        payload.start_at = new Date(schedulerStartAt.trim()).toISOString();
      }
      await createScheduledTask(payload);
      setSchedulerPrompt("");
      setSchedulerStartAt("");
      await refreshScheduledTasks();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSchedulerError(err.message || "Failed to create scheduled task");
    }
  }

  useEffect(() => {
    return () => {
      stopRealtimeCall();
    };
  }, []);

  async function handleToggleScheduledTask(task: ScheduledTask) {
    const nextStatus = task.status === "paused" ? "active" : "paused";
    try {
      await updateScheduledTask(task.id, { status: nextStatus });
      await refreshScheduledTasks();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSchedulerError(err.message || "Failed to update scheduled task");
    }
  }

  async function handleLoadRuns(taskId: string) {
    try {
      setTaskRunsLoading(true);
      setTaskRuns([]);
      setSelectedTaskId(taskId);
      const runs = await fetchScheduledTaskRuns(taskId);
      setTaskRuns(runs);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSchedulerError(err.message || "Failed to load task runs");
    } finally {
      setTaskRunsLoading(false);
    }
  }

  async function refreshMessages() {
    try {
      setMessagesLoading(true);
      const msgs = await fetchInboxMessages();
      setMessagesInbox(msgs);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setError(err.message || "Failed to load messages");
    } finally {
      setMessagesLoading(false);
    }
  }

  async function refreshCalendar() {
    try {
      setCalendarLoading(true);
      setCalendarError(null);
      const data = await fetchCalendarCombined({ days: 14 });
      setCalendarData(data);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to load calendar");
    } finally {
      setCalendarLoading(false);
    }
  }

  function toSoftEventDraft(detail: SoftEventDetail): SoftEventDraft {
    return {
      id: detail.id,
      title: detail.title || "",
      description: detail.description || "",
      notes: detail.notes || "",
      preferred_duration_minutes: String(detail.preferred_duration_minutes ?? ""),
      min_duration_minutes: String(detail.min_duration_minutes ?? ""),
      soft_deadline: detail.soft_deadline || "",
      hard_deadline: detail.hard_deadline || "",
      frequency: detail.frequency || "",
      deferral_limit: String(detail.deferral_limit ?? ""),
      priority: String(detail.priority ?? ""),
      status: detail.status,
    };
  }

  function newSoftEventDraft(): SoftEventDraft {
    return {
      id: "",
      title: "",
      description: "",
      notes: "",
      preferred_duration_minutes: "60",
      min_duration_minutes: "30",
      soft_deadline: "",
      hard_deadline: "",
      frequency: "",
      deferral_limit: "3",
      priority: "0",
      status: "active",
    };
  }

  async function openSoftEventEditor(softEventId: string) {
    try {
      setSoftEventError(null);
      setSoftEventLoading(true);
      setSoftEventMode("edit");
      setSoftEventModalVisible(true);
      const detail = await fetchSoftEvent(softEventId);
      setSoftEventDraft(toSoftEventDraft(detail));
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSoftEventError(err.message || "Failed to load soft event");
    } finally {
      setSoftEventLoading(false);
    }
  }

  function openSoftEventCreator() {
    setSoftEventError(null);
    setSoftEventMode("create");
    setSoftEventDraft(newSoftEventDraft());
    setSoftEventModalVisible(true);
  }

  async function saveSoftEventDraft() {
    if (!softEventDraft) return;
    try {
      if (!softEventDraft.title.trim()) {
        setSoftEventError("Title is required");
        return;
      }
      setSoftEventLoading(true);
      const preferredDuration = parseInt(softEventDraft.preferred_duration_minutes, 10);
      const minDuration = parseInt(softEventDraft.min_duration_minutes, 10);
      const deferral = parseInt(softEventDraft.deferral_limit, 10);
      const priority = parseInt(softEventDraft.priority, 10);
      const preferred = Number.isFinite(preferredDuration) ? preferredDuration : undefined;
      const minimum = Number.isFinite(minDuration) ? minDuration : undefined;
      const payload = {
        title: softEventDraft.title,
        description: softEventDraft.description,
        notes: softEventDraft.notes,
        preferred_duration_minutes: preferred,
        min_duration_minutes:
          minimum !== undefined && preferred !== undefined
            ? Math.min(minimum, preferred)
            : minimum,
        soft_deadline: softEventDraft.soft_deadline.trim() ? softEventDraft.soft_deadline.trim() : null,
        hard_deadline: softEventDraft.hard_deadline.trim() ? softEventDraft.hard_deadline.trim() : null,
        frequency: softEventDraft.frequency,
        deferral_limit: Number.isFinite(deferral) ? deferral : undefined,
        priority: Number.isFinite(priority) ? priority : undefined,
        status: softEventDraft.status,
      };
      if (softEventMode === "create") {
        await createSoftEvent(payload);
      } else {
        await updateSoftEvent(softEventDraft.id, payload);
      }
      setSoftEventModalVisible(false);
      setSoftEventDraft(null);
      await refreshCalendar();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setSoftEventError(err.message || "Failed to save soft event");
    } finally {
      setSoftEventLoading(false);
    }
  }

  async function handlePromoteSoftSlot(slotId: string) {
    try {
      setPromoteLoadingId(slotId);
      await promoteSoftSlot(slotId);
      await refreshCalendar();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to promote soft slot");
    } finally {
      setPromoteLoadingId(null);
    }
  }

  async function handleReplanCalendar() {
    try {
      setReplanLoading(true);
      const note = replanNote.trim();
      await replanCalendar({ days: 14, note: note || undefined });
      await refreshCalendar();
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setCalendarError(err.message || "Failed to replan calendar");
    } finally {
      setReplanLoading(false);
    }
  }

  function openReplanPrompt() {
    setReplanNote("");
    setReplanNoteVisible(true);
  }

  function openDatePicker(field: "soft_deadline" | "hard_deadline") {
    if (!softEventDraft) return;
    const raw = softEventDraft[field];
    const parsed = raw ? new Date(raw) : null;
    setDatePickerValue(parsed && !isNaN(parsed.getTime()) ? parsed : new Date());
    setDatePickerField(field);
  }

  async function refreshCallSessions() {
    try {
      setCallsLoading(true);
      const sessions = await fetchCallSessions();
      setCallSessions(sessions);
      const ringing = sessions.find((s) => s.status === "ringing");
      if (ringing) {
        setIncomingCall(ringing);
      } else {
        setIncomingCall(null);
      }
      if (activeCall && !sessions.find((s) => s.id === activeCall.id && s.status === "in_call")) {
        setActiveCall(null);
        await stopRealtimeCall();
      }
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setError(err.message || "Failed to load call sessions");
    } finally {
      setCallsLoading(false);
    }
  }

  async function answerCallSession(sessionId: string) {
    await updateCallSession(sessionId, { status: "in_call" });
    const sessions = await fetchCallSessions();
    const target = sessions.find((s) => s.id === sessionId);
    if (target) {
      setActiveCall(target);
      await startRealtimeCall(target);
    }
    setIncomingCall(null);
    await cancelIncomingCallNotification();
    await refreshCallSessions();
  }

  async function declineCallSession(sessionId: string) {
    await updateCallSession(sessionId, { status: "missed" });
    setIncomingCall(null);
    await cancelIncomingCallNotification();
    await refreshCallSessions();
  }

  async function stopRealtimeCall() {
    callSeqRef.current += 1;
    dataChannelRef.current?.close?.();
    dataChannelRef.current = null;
    if (peerConnectionRef.current) {
      peerConnectionRef.current.getSenders?.().forEach((sender: any) => {
        sender.track?.stop?.();
      });
      peerConnectionRef.current.close();
      peerConnectionRef.current = null;
    }
    if (localStreamRef.current) {
      localStreamRef.current.getTracks?.().forEach((track: any) => track.stop());
      localStreamRef.current = null;
    }
  }

  function endCallNow(sessionId: string) {
    if (endCallRef.current) return;
    endCallRef.current = true;
    endSignalReceivedRef.current = true;
    setActiveCall(null);
    setCallConnecting(false);
    void stopRealtimeCall();
    void updateCallSession(sessionId, { status: "completed" }).catch((err: any) =>
      setError(err?.message || "Failed to end call"),
    );
    void refreshCallSessions();
    setTimeout(() => {
      endCallRef.current = false;
    }, 1000);
  }

  function appendLiveTranscript(line: string) {
    setCallLiveTranscript((prev) => {
      const next = [...prev, line];
      if (next.length > 20) {
        return next.slice(next.length - 20);
      }
      return next;
    });
  }

  function recordTranscriptError(err: any) {
    if (!err) return;
    const status = err?.status ? ` (status ${err.status})` : "";
    const message = err?.message || "Transcript post failed";
    setCallTranscriptError(`${message}${status}`);
  }

  function handleRealtimeMessage(sessionId: string, raw: string) {
    try {
      const evt = JSON.parse(raw);
      const type = evt?.type || "";
      const transcript =
        evt?.transcript ||
        evt?.text ||
        evt?.delta ||
        evt?.response?.text ||
        evt?.response?.output_text;
      const outputText =
        evt?.response?.output_text ||
        evt?.response?.text ||
        evt?.output_text ||
        evt?.text ||
        evt?.delta;
      const endSignal = (() => {
        const candidates: string[] = [];
        if (typeof outputText === "string") candidates.push(outputText);
        if (typeof transcript === "string") candidates.push(transcript);
        if (typeof evt?.message === "string") candidates.push(evt.message);
        if (typeof evt?.response?.message === "string") candidates.push(evt.response.message);
        const outputs = evt?.response?.output || evt?.output;
        if (Array.isArray(outputs)) {
          outputs.forEach((item: any) => {
            if (typeof item?.text === "string") candidates.push(item.text);
            const content = item?.content;
            if (Array.isArray(content)) {
              content.forEach((chunk: any) => {
                if (typeof chunk?.text === "string") candidates.push(chunk.text);
                if (typeof chunk?.transcript === "string") candidates.push(chunk.transcript);
              });
            }
          });
        }
        return candidates.some((text) => text.includes("[END_CALL]"));
      })();
      if (type.includes("transcript") && transcript) {
        const text = String(transcript);
        const cleaned = text.replace(/\[END_CALL\]/g, "").trim();
        if (cleaned) {
          appendLiveTranscript(`assistant: ${cleaned}`);
          addCallTranscriptEntry(sessionId, { role: "assistant", content: cleaned })
            .then((resp) => {
              if (resp?.end_call) {
                endCallNow(sessionId);
              }
            })
            .catch(recordTranscriptError);
        }
      }
      const isOutputDelta = type.includes("output_text.delta");
      const isOutputDone =
        type.includes("output_text.done") ||
        type.includes("response.completed") ||
        type.includes("response.done");
      if (isOutputDelta && typeof outputText === "string") {
        outputTextBufferRef.current += outputText;
      }
      if (isOutputDone) {
        const buffered = outputTextBufferRef.current;
        const text = (buffered || (typeof outputText === "string" ? outputText : "")).trim();
        outputTextBufferRef.current = "";
        if (text && text !== lastAssistantTextRef.current) {
          lastAssistantTextRef.current = text;
          const cleaned = text.replace(/\[END_CALL\]/g, "").trim();
          if (cleaned) {
            appendLiveTranscript(`assistant: ${cleaned}`);
            addCallTranscriptEntry(sessionId, { role: "assistant", content: cleaned })
              .then((resp) => {
                if (resp?.end_call) {
                  endCallNow(sessionId);
                }
              })
              .catch(recordTranscriptError);
          }
        }
      }
      if (endSignal) {
        endSignalReceivedRef.current = true;
        endCallNow(sessionId);
        return;
      }
      if (type.includes("input_audio_transcription") && transcript) {
        const text = String(transcript).trim();
        if (text) {
          appendLiveTranscript(`user: ${text}`);
        }
        addCallTranscriptEntry(sessionId, { role: "user", content: String(transcript) }).catch(
          recordTranscriptError,
        );
      }
      if (
        (type.includes("response.completed") || type.includes("response.done")) &&
        !endSignalReceivedRef.current &&
        !endSignalPromptedRef.current
      ) {
        endSignalPromptedRef.current = true;
        dataChannelRef.current?.send?.(
          JSON.stringify({
            type: "response.create",
            response: {
              modalities: ["text"],
              instructions: "Send [END_CALL] now. Do not add any other text.",
            },
          }),
        );
      }
    } catch {
      // ignore parse errors
    }
  }

  async function startRealtimeCall(session: CallSession) {
    const callSeq = ++callSeqRef.current;
    try {
      setCallConnecting(true);
      endSignalReceivedRef.current = false;
      endSignalPromptedRef.current = false;
      outputTextBufferRef.current = "";
      lastAssistantTextRef.current = "";
      setCallLiveTranscript([]);
      setCallTranscriptError(null);
      const tokenResp = await createRealtimeToken(session.id);
      if (callSeq !== callSeqRef.current) return;
      const clientSecret =
        tokenResp?.client_secret?.value ||
        tokenResp?.client_secret ||
        tokenResp?.client_secret?.client_secret ||
        tokenResp?.ephemeral_key ||
        tokenResp?.token;
      if (!clientSecret) {
        throw new Error("Realtime token missing");
      }

      const pc = new RTCPeerConnection();
      peerConnectionRef.current = pc;

      pc.ondatachannel = (event: any) => {
        dataChannelRef.current = event.channel;
        event.channel.onmessage = (msg: any) => handleRealtimeMessage(session.id, msg.data);
      };

      const localStream = await mediaDevices.getUserMedia({ audio: true, video: false });
      if (callSeq !== callSeqRef.current) {
        localStream.getTracks().forEach((track: any) => track.stop?.());
        return;
      }
      localStreamRef.current = localStream;
      localStream.getTracks().forEach((track: any) => {
        pc.addTrack(track, localStream);
      });

      const dataChannel = pc.createDataChannel("oai-events");
      dataChannelRef.current = dataChannel;
      dataChannel.onmessage = (msg: any) => handleRealtimeMessage(session.id, msg.data);

      const offer = await pc.createOffer({ offerToReceiveAudio: true });
      if (callSeq !== callSeqRef.current) return;
      await pc.setLocalDescription(offer);

      const sdpResp = await fetch(
        `https://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${clientSecret}`,
            "Content-Type": "application/sdp",
          },
          body: offer.sdp,
        },
      );
      if (callSeq !== callSeqRef.current) return;
      if (!sdpResp.ok) {
        throw new Error(`Realtime SDP failed (${sdpResp.status})`);
      }
      const answerSdp = await sdpResp.text();
      if (callSeq !== callSeqRef.current) return;
      if (peerConnectionRef.current !== pc || pc.signalingState === "closed") {
        return;
      }
      await pc.setRemoteDescription(new RTCSessionDescription({ type: "answer", sdp: answerSdp }));

      dataChannel.onopen = () => {
        dataChannel.send(
          JSON.stringify({
            type: "response.create",
            response: {
              modalities: ["audio", "text"],
              instructions:
                `Call goal: ${session.goal}. Be concise and helpful.` +
                " When the goal is achieved and it sounds like the conversation can end, " +
                "you must send a final message that includes [END_CALL].",
            },
          }),
        );
      };
    } catch (err: any) {
      setError(err.message || "Failed to start call");
      await stopRealtimeCall();
    } finally {
      setCallConnecting(false);
    }
  }

  async function handleCancelJob(jobId: string) {
    try {
      await cancelJob(jobId);
      const jobsData = await fetchJobs(activeChatId || undefined);
      setJobs(jobsData);
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setError(err.message || "Failed to cancel job");
    }
  }

  async function handleShowJobLog(jobId: string) {
    try {
      const log = await fetchJobMessagesDirect(jobId);
      setJobLogMessages(log);
      setJobLogAnchorId(jobId);
      setJobLogVisible(true);
    } catch {
      // ignore log fetch errors
    }
  }

  function openChatActions(chat: ChatListItem) {
    Alert.alert(formatChatLabel(chat), "Chat actions", [
      {
        text: "Rename",
        onPress: () => {
          setRenameChatId(chat.chat_id);
          setRenameValue(chat.chat_nickname || "");
          setRenameVisible(true);
        },
      },
      {
        text: "Archive",
        onPress: () => confirmArchiveChat(chat.chat_id),
      },
      {
        text: "Delete",
        style: "destructive",
        onPress: () => confirmDeleteChat(chat.chat_id),
      },
      { text: "Cancel", style: "cancel" },
    ]);
  }

  function confirmArchiveChat(chatId: string) {
    Alert.alert("Archive chat?", "It will disappear from the list.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Archive",
        style: "destructive",
        onPress: async () => {
          try {
            await renameChat(chatId, { archived: true });
            await refreshChats(activeChatId === chatId ? null : activeChatId);
          } catch (err: any) {
            if (handleAuthError(err)) return;
            setError(err.message || "Failed to archive chat");
          }
        },
      },
    ]);
  }

  function confirmDeleteChat(chatId: string) {
    Alert.alert("Delete chat?", "This cannot be undone.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: async () => {
          try {
            await deleteChat(chatId);
            await refreshChats(activeChatId === chatId ? null : activeChatId);
          } catch (err: any) {
            if (handleAuthError(err)) return;
            setError(err.message || "Failed to delete chat");
          }
        },
      },
    ]);
  }

  async function handleRenameChat() {
    if (!renameChatId) return;
    try {
      await renameChat(renameChatId, { nickname: renameValue.trim() });
      await refreshChats(activeChatId === renameChatId ? renameChatId : undefined);
      setRenameVisible(false);
      setRenameChatId(null);
      setRenameValue("");
    } catch (err: any) {
      if (handleAuthError(err)) return;
      setError(err.message || "Failed to rename chat");
    }
  }

  return authLoading ? (
    <SafeAreaView style={styles.centered}>
      <ActivityIndicator size="large" />
      <StatusBar style="auto" />
    </SafeAreaView>
  ) : !authed ? (
    <SafeAreaView style={styles.authContainer}>
      <View style={styles.authCard}>
        <Text style={styles.title}>Corv Access</Text>
        <Text style={styles.muted}>Enter the shared access password to continue.</Text>
        {authError && <Text style={styles.errorText}>{authError}</Text>}
        <TextInput
          value={passwordInput}
          onChangeText={setPasswordInput}
          placeholder="Password"
          secureTextEntry
          style={styles.authInput}
        />
        <TouchableOpacity
          style={styles.primaryButton}
          onPress={async () => {
            if (!passwordInput.trim()) {
              setAuthError("Password required");
              return;
            }
            await AsyncStorage.setItem("appAccessToken", passwordInput.trim());
            setPasswordInput("");
            setAuthError(null);
            setAuthed(true);
          }}
        >
          <Text style={styles.primaryButtonText}>Enter</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  ) : (
    <SafeAreaView style={styles.container}>
      <View
        style={styles.header}
        onLayout={(event) => setHeaderHeight(event.nativeEvent.layout.height)}
      >
        <Text style={styles.headerTitle}>Corv</Text>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.headerTabs}
          contentContainerStyle={styles.headerTabsContent}
        >
          <TouchableOpacity
            style={[styles.tabButton, activeTab === "chat" && styles.tabButtonActive]}
            onPress={() => setActiveTab("chat")}
          >
            <Text style={[styles.tabButtonText, activeTab === "chat" && styles.tabButtonTextActive]}>
              Chat
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tabButton, activeTab === "settings" && styles.tabButtonActive]}
            onPress={() => setActiveTab("settings")}
          >
            <Text
              style={[styles.tabButtonText, activeTab === "settings" && styles.tabButtonTextActive]}
            >
              Settings
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tabButton, activeTab === "study" && styles.tabButtonActive]}
            onPress={() => setActiveTab("study")}
          >
            <Text style={[styles.tabButtonText, activeTab === "study" && styles.tabButtonTextActive]}>
              Study
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tabButton, activeTab === "calendar" && styles.tabButtonActive]}
            onPress={() => setActiveTab("calendar")}
          >
            <Text
              style={[styles.tabButtonText, activeTab === "calendar" && styles.tabButtonTextActive]}
            >
              Calendar
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tabButton, activeTab === "scheduler" && styles.tabButtonActive]}
            onPress={() => setActiveTab("scheduler")}
          >
            <Text
              style={[styles.tabButtonText, activeTab === "scheduler" && styles.tabButtonTextActive]}
            >
              Scheduler
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tabButton, activeTab === "messages" && styles.tabButtonActive]}
            onPress={() => setActiveTab("messages")}
          >
            <Text
              style={[styles.tabButtonText, activeTab === "messages" && styles.tabButtonTextActive]}
            >
              Messages
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tabButton, activeTab === "calls" && styles.tabButtonActive]}
            onPress={() => setActiveTab("calls")}
          >
            <Text
              style={[styles.tabButtonText, activeTab === "calls" && styles.tabButtonTextActive]}
            >
              Calls
            </Text>
          </TouchableOpacity>
        </ScrollView>
      </View>

      {activeTab === "chat" ? (
        <KeyboardAvoidingView
          style={styles.flex}
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          keyboardVerticalOffset={Platform.OS === "ios" ? headerHeight + insets.top : 0}
        >
          <View style={styles.chatLayout}>
            {sidebarOpen ? (
              <View style={styles.sidebar}>
                <View style={styles.sidebarHeader}>
                  <View style={styles.sidebarHeaderLeft}>
                    <Text style={styles.sidebarTitle}>Chats</Text>
                    <TouchableOpacity style={styles.newChatButton} onPress={handleNewChat}>
                      <Text style={styles.newChatButtonText}>+ New</Text>
                    </TouchableOpacity>
                  </View>
                  <TouchableOpacity
                    style={styles.sidebarToggle}
                    onPress={() => setSidebarOpen(false)}
                    accessibilityLabel="Collapse sidebar"
                  >
                    <Ionicons name="chevron-back" size={16} color="#e5e7eb" />
                  </TouchableOpacity>
                </View>
                <ScrollView contentContainerStyle={styles.sidebarList}>
                  {sortedChats.map((chat) => {
                    const isActive = chat.chat_id === activeChatId;
                    return (
                      <TouchableOpacity
                        key={chat.chat_id}
                        style={[styles.chatPill, isActive && styles.chatPillActive]}
                        onPress={() => setActiveChatId(chat.chat_id)}
                        onLongPress={() => openChatActions(chat)}
                      >
                        <Text style={[styles.chatPillText, isActive && styles.chatPillTextActive]}>
                          {formatChatLabel(chat)}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                  {!sortedChats.length && <Text style={styles.muted}>No chats yet.</Text>}
                </ScrollView>
                <TouchableOpacity
                  style={styles.logoutButton}
                  onPress={async () => {
                    await AsyncStorage.removeItem("appAccessToken");
                    setAuthed(false);
                    setAuthError(null);
                  }}
                >
                  <Text style={styles.logoutButtonText}>Log out</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <TouchableOpacity
                style={styles.sidebarToggleFloating}
                onPress={() => setSidebarOpen(true)}
                accessibilityLabel="Expand sidebar"
              >
                <Ionicons name="chevron-forward" size={16} color="#e5e7eb" />
              </TouchableOpacity>
            )}

            <View style={styles.chatMain}>
              {error && <Text style={styles.errorText}>{error}</Text>}
              {loadingMessages ? (
                <View style={styles.centered}>
                  <ActivityIndicator />
                </View>
              ) : (
                <FlatList
                  ref={(ref) => {
                    messagesListRef.current = ref;
                  }}
                  data={messages}
                  keyExtractor={(item) => item.id}
                  contentContainerStyle={styles.messagesList}
                  ItemSeparatorComponent={() => <View style={styles.messageSeparator} />}
                  renderItem={({ item, index }) => (
                    <MessageBubble
                      msg={item}
                      isLastJobMessage={
                        !!item.job_id && lastJobMessageIndex.get(item.job_id) === index
                      }
                      onShowJobLog={handleShowJobLog}
                    />
                  )}
                  ListEmptyComponent={
                    <Text style={styles.muted}>No messages yet. Send one to begin.</Text>
                  }
                />
              )}

              <View style={[styles.inputRow, { paddingBottom: Math.max(12, insets.bottom) }]}>
                <TouchableOpacity
                  style={[
                    styles.micButton,
                    recording && styles.micButtonActive,
                    voiceSending && styles.buttonDisabled,
                  ]}
                  onPress={recording ? stopVoiceRecording : startVoiceRecording}
                  disabled={voiceSending}
                  accessibilityLabel={recording ? "Stop recording" : "Start recording"}
                >
                  <Ionicons
                    name={recording ? "stop" : "mic"}
                    size={18}
                    color={recording ? "#b91c1c" : "#e5e7eb"}
                  />
                </TouchableOpacity>
                <TextInput
                  style={styles.input}
                  value={input}
                  onChangeText={setInput}
                  placeholder="Send a message"
                  placeholderTextColor="#e5e7eb"
                  multiline
                />
                <TouchableOpacity
                  style={[styles.primaryButton, styles.sendButton, sending && styles.buttonDisabled]}
                  onPress={handleSend}
                  disabled={sending}
                >
                  <Text style={styles.primaryButtonText}>{sending ? "Sending" : "Send"}</Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </KeyboardAvoidingView>
      ) : activeTab === "settings" ? (
        <ScrollView contentContainerStyle={styles.scrollContent}>
          <Text style={styles.sectionTitle}>Models</Text>
          {settingsError && <Text style={styles.errorText}>{settingsError}</Text>}
          <Text style={styles.label}>Frontman model</Text>
          <TextInput
            style={styles.input}
            value={settingsDraft.frontman_model || ""}
            onChangeText={(value) =>
              setSettingsDraft((prev) => ({ ...prev, frontman_model: value }))
            }
            placeholder="gpt-5-mini"
          />
          <Text style={styles.label}>Caller model</Text>
          <TextInput
            style={styles.input}
            value={settingsDraft.caller_model || ""}
            onChangeText={(value) =>
              setSettingsDraft((prev) => ({ ...prev, caller_model: value }))
            }
            placeholder="gpt-5-mini"
          />
          <Text style={styles.label}>Soft planner model</Text>
          <TextInput
            style={styles.input}
            value={settingsDraft.soft_planner_model || ""}
            onChangeText={(value) =>
              setSettingsDraft((prev) => ({ ...prev, soft_planner_model: value }))
            }
            placeholder={settingsDraft.caller_model || "gpt-5-mini"}
          />
          <Text style={styles.label}>Cache mode</Text>
          <View style={styles.cacheRow}>
            {["off", "frontman", "caller", "all"].map((mode) => (
              <TouchableOpacity
                key={mode}
                style={[
                  styles.cachePill,
                  settingsDraft.cache_mode === mode && styles.cachePillActive,
                ]}
                onPress={() => setSettingsDraft((prev) => ({ ...prev, cache_mode: mode }))}
              >
                <Text
                  style={[
                    styles.cachePillText,
                    settingsDraft.cache_mode === mode && styles.cachePillTextActive,
                  ]}
                >
                  {mode}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          <Text style={styles.label}>Max function result chars</Text>
          <TextInput
            style={styles.input}
            value={
              settingsDraft.max_function_result_chars
                ? String(settingsDraft.max_function_result_chars)
                : ""
            }
            onChangeText={(value) =>
              setSettingsDraft((prev) => ({
                ...prev,
                max_function_result_chars: Number(value) || undefined,
              }))
            }
            keyboardType="number-pad"
            placeholder="6000"
          />
          <TouchableOpacity
            style={[styles.primaryButton, savingSettings && styles.buttonDisabled]}
            onPress={handleSaveSettings}
            disabled={savingSettings}
          >
            <Text style={styles.primaryButtonText}>
              {savingSettings ? "Saving" : "Save settings"}
            </Text>
          </TouchableOpacity>

          <Text style={styles.sectionTitle}>Usage</Text>
          {usageSummary ? (
            <View style={styles.usageCard}>
              <Text style={styles.muted}>Since {formatDateTime(usageSummary.since)}</Text>
              <Text style={styles.usageStat}>
                Total tokens: {usageSummary.totals.total_tokens ?? 0}
              </Text>
              <Text style={styles.usageStat}>
                Prompt tokens: {usageSummary.totals.prompt_tokens ?? 0}
              </Text>
              <Text style={styles.usageStat}>
                Completion tokens: {usageSummary.totals.completion_tokens ?? 0}
              </Text>
            </View>
          ) : (
            <Text style={styles.muted}>No usage summary yet.</Text>
          )}

          {usageRecent.length > 0 && (
            <>
              <Text style={styles.sectionTitle}>Recent usage</Text>
              {usageRecent.slice(0, 6).map((event) => (
                <View key={event.id} style={styles.usageRow}>
                  <Text style={styles.usageRowTitle}>{event.model}</Text>
                  <Text style={styles.muted}>
                    {formatDateTime(event.created_at)} - {event.total_tokens} tokens
                  </Text>
                </View>
              ))}
            </>
          )}
        </ScrollView>
      ) : activeTab === "study" ? (
        <ScrollView contentContainerStyle={styles.scrollContent}>
          <Text style={styles.sectionTitle}>Study</Text>
          {studyError && <Text style={styles.errorText}>{studyError}</Text>}

          <View style={styles.calendarRow}>
            <Text style={styles.calendarTitle}>Create course</Text>
            <Text style={styles.muted}>Add a course before uploading materials.</Text>
            <Text style={styles.label}>Title</Text>
            <TextInput
              style={styles.input}
              value={studyCourseTitle}
              onChangeText={setStudyCourseTitle}
              placeholder="Calculus I"
              placeholderTextColor="#94a3b8"
            />
            <Text style={styles.label}>Code</Text>
            <TextInput
              style={styles.input}
              value={studyCourseCode}
              onChangeText={setStudyCourseCode}
              placeholder="MATH101"
              placeholderTextColor="#94a3b8"
            />
            <Text style={styles.label}>Description</Text>
            <TextInput
              style={[styles.input, styles.textarea]}
              value={studyCourseDescription}
              onChangeText={setStudyCourseDescription}
              placeholder="Course notes"
              placeholderTextColor="#94a3b8"
              multiline
            />
            <TouchableOpacity
              style={[styles.primaryButton, studySaving && styles.buttonDisabled]}
              onPress={handleCreateStudyCourse}
              disabled={studySaving}
            >
              <Text style={styles.primaryButtonText}>{studySaving ? "Saving" : "Create course"}</Text>
            </TouchableOpacity>
          </View>

          <Text style={styles.sectionTitle}>Courses</Text>
          {studyLoading && !studyCourses.length ? (
            <ActivityIndicator />
          ) : studyCourses.length ? (
            <View style={styles.cacheRow}>
              {studyCourses.map((course) => (
                <TouchableOpacity
                  key={course.id}
                  style={[
                    styles.cachePill,
                    studySelectedCourseId === course.id && styles.cachePillActive,
                  ]}
                  onPress={() => setStudySelectedCourseId(course.id)}
                >
                  <Text
                    style={[
                      styles.cachePillText,
                      studySelectedCourseId === course.id && styles.cachePillTextActive,
                    ]}
                  >
                    {course.code ? `${course.code} · ` : ""}
                    {course.title}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          ) : (
            <Text style={styles.muted}>No study courses yet.</Text>
          )}

          <Text style={styles.sectionTitle}>Upload material</Text>
          <View style={styles.calendarRow}>
            <Text style={styles.calendarTitle}>Selected course</Text>
            <Text style={styles.muted}>{selectedStudyCourse ? selectedStudyCourse.title : "None"}</Text>
            <Text style={styles.label}>Material title</Text>
            <TextInput
              style={styles.input}
              value={studyMaterialTitle}
              onChangeText={setStudyMaterialTitle}
              placeholder="Lecture 3 - Chain Rule"
              placeholderTextColor="#94a3b8"
            />
            <Text style={styles.label}>Kind</Text>
            <View style={styles.cacheRow}>
              {[
                ["lecture", "Lecture"],
                ["slides", "Slides"],
                ["past_exam", "Past Exam"],
                ["notes", "Notes"],
                ["link", "Link"],
                ["other", "Other"],
              ].map(([value, label]) => (
                <TouchableOpacity
                  key={value}
                  style={[
                    styles.cachePill,
                    studyMaterialKind === value && styles.cachePillActive,
                  ]}
                  onPress={() => setStudyMaterialKind(value)}
                >
                  <Text
                    style={[
                      styles.cachePillText,
                      studyMaterialKind === value && styles.cachePillTextActive,
                    ]}
                  >
                    {label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
            <Text style={styles.label}>Notes</Text>
            <TextInput
              style={[styles.input, styles.textarea]}
              value={studyMaterialNotes}
              onChangeText={setStudyMaterialNotes}
              placeholder="Anything Corv should know about this file"
              placeholderTextColor="#94a3b8"
              multiline
            />
            <TouchableOpacity style={styles.secondaryButton} onPress={handlePickStudyFile}>
              <Text style={styles.secondaryButtonText}>
                {studyMaterialFile ? `Picked: ${studyMaterialFile.name}` : "Pick file"}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.primaryButton, studySaving && styles.buttonDisabled]}
              onPress={handleUploadStudyMaterial}
              disabled={studySaving}
            >
              <Text style={styles.primaryButtonText}>{studySaving ? "Uploading" : "Upload & process"}</Text>
            </TouchableOpacity>
          </View>

          <Text style={styles.sectionTitle}>Materials</Text>
          {studyMaterials.length ? (
            studyMaterials.map((material) => (
              <View key={material.id} style={styles.calendarRow}>
                <Text style={styles.calendarTitle}>{material.title}</Text>
                <Text style={styles.muted}>{material.kind} · {material.ingestion_status}</Text>
                <Text style={styles.muted}>Pages: {material.page_count}</Text>
                {!!material.processing_error && (
                  <Text style={styles.errorText}>{material.processing_error}</Text>
                )}
              </View>
            ))
          ) : (
            <Text style={styles.muted}>No uploaded materials yet.</Text>
          )}
        </ScrollView>
      ) : activeTab === "scheduler" ? (
        <ScrollView contentContainerStyle={styles.scrollContent}>
          <Text style={styles.sectionTitle}>Scheduler</Text>
          {schedulerError && <Text style={styles.errorText}>{schedulerError}</Text>}
          <Text style={styles.label}>Prompt</Text>
          <TextInput
            style={[styles.input, styles.textarea]}
            value={schedulerPrompt}
            onChangeText={setSchedulerPrompt}
            placeholder="Describe the task..."
            placeholderTextColor="#94a3b8"
            multiline
          />
          <Text style={styles.label}>Start time (local ISO)</Text>
          <TextInput
            style={styles.input}
            value={schedulerStartAt}
            onChangeText={setSchedulerStartAt}
            placeholder="2025-01-30T15:00"
            placeholderTextColor="#94a3b8"
          />
          <Text style={styles.label}>Recurrence</Text>
          <View style={styles.cacheRow}>
            {["once", "daily", "weekly", "monthly"].map((mode) => (
              <TouchableOpacity
                key={mode}
                style={[
                  styles.cachePill,
                  schedulerRecurrence === mode && styles.cachePillActive,
                ]}
                onPress={() => setSchedulerRecurrence(mode as typeof schedulerRecurrence)}
              >
                <Text
                  style={[
                    styles.cachePillText,
                    schedulerRecurrence === mode && styles.cachePillTextActive,
                  ]}
                >
                  {mode}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          <TouchableOpacity style={styles.primaryButton} onPress={handleCreateScheduledTask}>
            <Text style={styles.primaryButtonText}>Schedule</Text>
          </TouchableOpacity>

          <Text style={styles.sectionTitle}>Tasks</Text>
          {schedulerLoading ? (
            <ActivityIndicator />
          ) : scheduledTasks.length ? (
            scheduledTasks.map((task) => (
              <View key={task.id} style={styles.calendarRow}>
                <Text style={styles.calendarTitle}>{task.prompt}</Text>
                <Text style={styles.muted}>
                  Next: {task.next_run_at ? formatDateTime(task.next_run_at) : "—"}
                </Text>
                <Text style={styles.muted}>Recurrence: {task.recurrence}</Text>
                <View style={styles.rowActions}>
                  <TouchableOpacity
                    style={[styles.secondaryButton, styles.rowActionButton]}
                    onPress={() => handleLoadRuns(task.id)}
                  >
                    <Text style={styles.secondaryButtonText}>Logs</Text>
                  </TouchableOpacity>
                  {task.status !== "completed" && (
                    <TouchableOpacity
                      style={styles.secondaryButton}
                      onPress={() => handleToggleScheduledTask(task)}
                    >
                      <Text style={styles.secondaryButtonText}>
                        {task.status === "paused" ? "Resume" : "Pause"}
                      </Text>
                    </TouchableOpacity>
                  )}
                </View>
              </View>
            ))
          ) : (
            <Text style={styles.muted}>No scheduled tasks yet.</Text>
          )}

          <Text style={styles.sectionTitle}>Runs</Text>
          {taskRunsLoading ? (
            <ActivityIndicator />
          ) : selectedTaskId ? (
            taskRuns.length ? (
              taskRuns.map((run) => (
                <View key={run.id} style={styles.calendarRow}>
                  <Text style={styles.calendarTitle}>{run.status.toUpperCase()}</Text>
                  {run.started_at && (
                    <Text style={styles.muted}>{formatDateTime(run.started_at)}</Text>
                  )}
                  {run.summary ? (
                    <View style={styles.rowActions}>
                      <TouchableOpacity
                        style={[styles.secondaryButton, styles.rowActionButton]}
                        onPress={() => {
                          setSummaryModalText(run.summary);
                          setSummaryModalVisible(true);
                        }}
                      >
                        <Text style={styles.secondaryButtonText}>TL;DR</Text>
                      </TouchableOpacity>
                    </View>
                  ) : null}
                  {run.log_entries?.length ? (
                    run.log_entries.map((entry) => (
                      <View key={entry.id} style={styles.jobLogRow}>
                        <Text style={styles.jobLogText}>{entry.message}</Text>
                      </View>
                    ))
                  ) : (
                    <Text style={styles.muted}>No log entries yet.</Text>
                  )}
                </View>
              ))
            ) : (
              <Text style={styles.muted}>No runs yet.</Text>
            )
          ) : (
            <Text style={styles.muted}>Select a task to view logs.</Text>
          )}
        </ScrollView>
      ) : activeTab === "messages" ? (
        <ScrollView contentContainerStyle={styles.scrollContent}>
          <Text style={styles.sectionTitle}>Messages</Text>
          {messagesLoading ? (
            <ActivityIndicator />
          ) : messagesInbox.length ? (
            messagesInbox.map((msg) => (
              <TouchableOpacity
                key={msg.id}
                style={[
                  styles.calendarRow,
                  !msg.read_at && styles.unreadCard,
                ]}
                onPress={async () => {
                  if (!msg.read_at) {
                    await markMessageRead(msg.id);
                    await refreshMessages();
                  }
                }}
              >
                <Text style={styles.calendarTitle}>
                  {msg.title || "Message"}
                </Text>
                <Text style={styles.muted}>{msg.body}</Text>
                {msg.created_at && (
                  <Text style={styles.muted}>{formatDateTime(msg.created_at)}</Text>
                )}
              </TouchableOpacity>
            ))
          ) : (
            <Text style={styles.muted}>No messages yet.</Text>
          )}
        </ScrollView>
      ) : activeTab === "calls" ? (
        <ScrollView contentContainerStyle={styles.scrollContent}>
          <Text style={styles.sectionTitle}>Calls</Text>
          {callsLoading ? (
            <ActivityIndicator />
          ) : callSessions.length ? (
            callSessions.map((session) => (
              <View key={session.id} style={styles.calendarRow}>
                <Text style={styles.calendarTitle}>{session.goal}</Text>
                <Text style={styles.muted}>Status: {session.status}</Text>
                {session.scheduled_for && (
                  <Text style={styles.muted}>
                    Scheduled: {formatDateTime(session.scheduled_for)}
                  </Text>
                )}
                {session.summary ? (
                  <Text style={styles.muted}>TL;DR: {session.summary}</Text>
                ) : null}
                <View style={styles.rowActions}>
                  {session.status === "ringing" && (
                    <>
                      <TouchableOpacity
                        style={[styles.secondaryButton, styles.rowActionButton]}
                        onPress={async () => {
                          await updateCallSession(session.id, { status: "in_call" });
                          setActiveCall(session);
                          await startRealtimeCall(session);
                          await refreshCallSessions();
                        }}
                      >
                        <Text style={styles.secondaryButtonText}>Answer</Text>
                      </TouchableOpacity>
                      <TouchableOpacity
                        style={styles.secondaryButton}
                        onPress={async () => {
                          await updateCallSession(session.id, { status: "missed" });
                          await refreshCallSessions();
                        }}
                      >
                        <Text style={styles.secondaryButtonText}>Decline</Text>
                      </TouchableOpacity>
                    </>
                  )}
                </View>
              </View>
            ))
          ) : (
            <Text style={styles.muted}>No call sessions yet.</Text>
          )}
              <TouchableOpacity
                style={styles.primaryButton}
                onPress={async () => {
                  try {
                    await createCallSession({ goal: "Quick check-in call" });
                    await refreshCallSessions();
                  } catch (error: any) {
                    Alert.alert("Call failed", error?.message || "Unable to create call session.");
                  }
                }}
              >
                <Text style={styles.primaryButtonText}>Start test call</Text>
              </TouchableOpacity>
        </ScrollView>
      ) : (
        <ScrollView contentContainerStyle={styles.scrollContent}>
          <Text style={styles.sectionTitle}>Calendar</Text>
          {calendarLoading && <ActivityIndicator />}
          {calendarError && <Text style={styles.errorText}>{calendarError}</Text>}
          {calendarData ? (
            <>
              <Text style={styles.muted}>
                Window: {formatDateTime(calendarData.window_start)} -{" "}
                {formatDateTime(calendarData.window_end)}
              </Text>
              <View style={styles.rowActions}>
                <TouchableOpacity
                  style={styles.secondaryButton}
                  onPress={openReplanPrompt}
                  disabled={replanLoading}
                >
                  <Text style={styles.secondaryButtonText}>
                    {replanLoading ? "Replanning…" : "Replan next 2 weeks"}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.secondaryButton}
                  onPress={openSoftEventCreator}
                >
                  <Text style={styles.secondaryButtonText}>Add soft event</Text>
                </TouchableOpacity>
              </View>
              <View style={styles.calendarLegend}>
                <View style={styles.calendarLegendItem}>
                  <View style={[styles.calendarLegendDot, styles.calendarLegendHard]} />
                  <Text style={styles.muted}>Hard</Text>
                </View>
                <View style={styles.calendarLegendItem}>
                  <View style={[styles.calendarLegendDot, styles.calendarLegendSoft]} />
                  <Text style={styles.muted}>Soft</Text>
                </View>
              </View>
              <View style={styles.calendarWeekHeader}>
                {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => (
                  <Text key={day} style={styles.calendarWeekHeaderLabel}>{day}</Text>
                ))}
              </View>
              <View style={styles.calendarGrid}>
                {calendarDays.map((day) => {
                  if (day.isPlaceholder) {
                    return <View key={day.key} style={[styles.calendarCell, styles.calendarCellPlaceholder]} />;
                  }
                  const isActive = day.key === selectedDayKey;
                  const dayWarningStyle = day.hasSoftWarningRed
                    ? styles.calendarCellWarningRed
                    : day.hasSoftWarningOrange
                      ? styles.calendarCellWarningOrange
                      : null;
                  return (
                    <TouchableOpacity
                      key={day.key}
                      style={[
                        styles.calendarCell,
                        dayWarningStyle,
                        isActive && styles.calendarCellActive,
                      ]}
                      onPress={() => setSelectedDayKey(day.key)}
                    >
                      <Text style={styles.calendarCellLabel}>{day.label}</Text>
                      {day.hasSoftWarning && (
                        <View style={styles.calendarCellWarningDot} />
                      )}
                      {!!day.hard.length && (
                        <Text style={styles.calendarCellBadgeHard}>{day.hard.length} hard</Text>
                      )}
                      {!!day.soft.length && (
                        <Text style={styles.calendarCellBadgeSoft}>{day.soft.length} soft</Text>
                      )}
                    </TouchableOpacity>
                  );
                })}
              </View>
              {selectedDayKey && (
                <>
                  <Text style={styles.sectionTitle}>Selected day</Text>
                  {(() => {
                    const selected = calendarDays.find((day) => day.key === selectedDayKey);
                    if (!selected) return null;
                    return (
                      <>
                        {!!selected.hard.length && (
                          <>
                            <Text style={styles.calendarSubTitle}>Hard events</Text>
                            {selected.hard.map((event) => (
                              <View key={event.id} style={styles.calendarRow}>
                                <Text style={styles.calendarTitle}>{event.title}</Text>
                                {event.all_day ? (
                                  <Text style={styles.muted}>All day</Text>
                                ) : (
                                  <Text style={styles.muted}>
                                    {formatDateTime(event.start)} - {formatDateTime(event.end)}
                                  </Text>
                                )}
                              </View>
                            ))}
                          </>
                        )}
                        {!!selected.soft.length && (
                          <>
                            <Text style={styles.calendarSubTitle}>Soft slots</Text>
                            {selected.soft.map((slot) => (
                              <TouchableOpacity
                                key={slot.id}
                                style={styles.calendarRow}
                                onPress={() => openSoftEventEditor(slot.soft_event_id)}
                              >
                                <View style={styles.rowBetween}>
                                  <Text style={styles.calendarTitle}>{slot.title}</Text>
                                  {(() => {
                                    const slotEnd = new Date(slot.end).getTime();
                                    const hardDeadline = slot.hard_deadline
                                      ? new Date(slot.hard_deadline).getTime()
                                      : null;
                                    const softDeadline = slot.soft_deadline
                                      ? new Date(slot.soft_deadline).getTime()
                                      : null;
                                    if (hardDeadline && slotEnd > hardDeadline) {
                                      return (
                                        <Ionicons
                                          name="alert-circle"
                                          size={18}
                                          color="#ef4444"
                                        />
                                      );
                                    }
                                    if (softDeadline && slotEnd > softDeadline) {
                                      return (
                                        <Ionicons
                                          name="alert-circle-outline"
                                          size={18}
                                          color="#f59e0b"
                                        />
                                      );
                                    }
                                    return null;
                                  })()}
                                </View>
                                <Text style={styles.muted}>
                                  {formatDateTime(slot.start)} - {formatDateTime(slot.end)}
                                </Text>
                                <Text style={styles.muted}>Status: {slot.status}</Text>
                                <View style={styles.rowActions}>
                                  <TouchableOpacity
                                    style={styles.secondaryButton}
                                    onPress={() => handlePromoteSoftSlot(slot.id)}
                                    disabled={promoteLoadingId === slot.id}
                                  >
                                    <Text style={styles.secondaryButtonText}>
                                      {promoteLoadingId === slot.id ? "Promoting…" : "Promote"}
                                    </Text>
                                  </TouchableOpacity>
                                </View>
                              </TouchableOpacity>
                            ))}
                          </>
                        )}
                        {!selected.hard.length && !selected.soft.length && (
                          <Text style={styles.muted}>No events on this day.</Text>
                        )}
                      </>
                    );
                  })()}
                </>
              )}

              <Text style={styles.sectionTitle}>Unscheduled soft events</Text>
              {calendarData.soft_events_unscheduled.length ? (
                calendarData.soft_events_unscheduled.map((event) => (
                  <TouchableOpacity
                    key={event.id}
                    style={styles.calendarRow}
                    onPress={() => openSoftEventEditor(event.id)}
                  >
                    <Text style={styles.calendarTitle}>{event.title}</Text>
                    <Text style={styles.muted}>Priority: {event.priority}</Text>
                    {event.soft_deadline && (
                      <Text style={styles.muted}>
                        Soft deadline: {formatDateTime(event.soft_deadline)}
                      </Text>
                    )}
                    {event.hard_deadline && (
                      <Text style={styles.muted}>
                        Hard deadline: {formatDateTime(event.hard_deadline)}
                      </Text>
                    )}
                  </TouchableOpacity>
                ))
              ) : (
                <Text style={styles.muted}>No unscheduled soft events.</Text>
              )}
            </>
          ) : (
            !calendarLoading && <Text style={styles.muted}>No calendar data.</Text>
          )}
        </ScrollView>
      )}

      <Modal visible={renameVisible} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.sectionTitle}>Rename chat</Text>
            <TextInput
              style={styles.input}
              value={renameValue}
              onChangeText={setRenameValue}
              placeholder="Chat name"
              autoFocus
            />
            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={() => {
                  setRenameVisible(false);
                  setRenameChatId(null);
                  setRenameValue("");
                }}
              >
                <Text style={styles.secondaryButtonText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.primaryButton, styles.modalPrimary]}
                onPress={handleRenameChat}
              >
                <Text style={styles.primaryButtonText}>Save</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <Modal visible={jobLogVisible} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.sectionTitle}>Job log</Text>
            <ScrollView style={styles.jobLogList}>
              {jobLogMessages.length ? (
                jobLogMessages.map((entry) => (
                  <View key={entry.id} style={styles.jobLogRow}>
                    <View style={styles.jobLogMeta}>
                      <Text style={styles.jobLogRole}>{entry.role}</Text>
                      {!!entry.created_at && (
                        <Text style={styles.jobLogTime}>{formatTime(entry.created_at)}</Text>
                      )}
                      {entry.message_type && (
                        <Text style={styles.jobLogType}>{entry.message_type}</Text>
                      )}
                    </View>
                    <Text style={styles.jobLogText}>{entry.text}</Text>
                  </View>
                ))
              ) : (
                <Text style={styles.muted}>No log entries yet.</Text>
              )}
            </ScrollView>
            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={() => {
                  setJobLogVisible(false);
                  setJobLogAnchorId(null);
                  setJobLogMessages([]);
                }}
              >
                <Text style={styles.secondaryButtonText}>Close</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <Modal visible={softEventModalVisible} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.sectionTitle}>
              {softEventMode === "create" ? "Add soft event" : "Edit soft event"}
            </Text>
            {softEventLoading && <ActivityIndicator />}
            {softEventError && <Text style={styles.errorText}>{softEventError}</Text>}
            {softEventDraft && (
              <ScrollView style={styles.jobLogList}>
                <TextInput
                  style={styles.input}
                  value={softEventDraft.title}
                  onChangeText={(value) =>
                    setSoftEventDraft((prev) => (prev ? { ...prev, title: value } : prev))
                  }
                  placeholder="Title"
                />
                <TextInput
                  style={[styles.input, styles.textarea]}
                  value={softEventDraft.description}
                  onChangeText={(value) =>
                    setSoftEventDraft((prev) => (prev ? { ...prev, description: value } : prev))
                  }
                  placeholder="Description"
                  multiline
                />
                <TextInput
                  style={[styles.input, styles.textarea]}
                  value={softEventDraft.notes}
                  onChangeText={(value) =>
                    setSoftEventDraft((prev) => (prev ? { ...prev, notes: value } : prev))
                  }
                  placeholder="Notes"
                  multiline
                />
                <TextInput
                  style={styles.input}
                  value={softEventDraft.preferred_duration_minutes}
                  onChangeText={(value) =>
                    setSoftEventDraft((prev) => (prev ? { ...prev, preferred_duration_minutes: value } : prev))
                  }
                  placeholder="Preferred duration minutes"
                  keyboardType="numeric"
                />
                <TextInput
                  style={styles.input}
                  value={softEventDraft.min_duration_minutes}
                  onChangeText={(value) =>
                    setSoftEventDraft((prev) => (prev ? { ...prev, min_duration_minutes: value } : prev))
                  }
                  placeholder="Minimum duration minutes"
                  keyboardType="numeric"
                />
                <TouchableOpacity
                  style={styles.inputButton}
                  onPress={() => openDatePicker("soft_deadline")}
                >
                  <Text style={styles.inputButtonText}>
                    {softEventDraft.soft_deadline
                      ? formatDateTime(softEventDraft.soft_deadline)
                      : "Soft deadline (tap to pick)"}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.inputButton}
                  onPress={() => openDatePicker("hard_deadline")}
                >
                  <Text style={styles.inputButtonText}>
                    {softEventDraft.hard_deadline
                      ? formatDateTime(softEventDraft.hard_deadline)
                      : "Hard deadline (tap to pick)"}
                  </Text>
                </TouchableOpacity>
                <TextInput
                  style={styles.input}
                  value={softEventDraft.frequency}
                  onChangeText={(value) =>
                    setSoftEventDraft((prev) => (prev ? { ...prev, frequency: value } : prev))
                  }
                  placeholder="Frequency"
                />
                <TextInput
                  style={styles.input}
                  value={softEventDraft.deferral_limit}
                  onChangeText={(value) =>
                    setSoftEventDraft((prev) => (prev ? { ...prev, deferral_limit: value } : prev))
                  }
                  placeholder="Deferral limit"
                  keyboardType="numeric"
                />
                <TextInput
                  style={styles.input}
                  value={softEventDraft.priority}
                  onChangeText={(value) =>
                    setSoftEventDraft((prev) => (prev ? { ...prev, priority: value } : prev))
                  }
                  placeholder="Priority"
                  keyboardType="numeric"
                />
                <Text style={styles.label}>Status</Text>
                <View style={styles.rowActions}>
                  {(["active", "paused", "archived"] as const).map((status) => (
                    <TouchableOpacity
                      key={status}
                      style={[
                        styles.secondaryButton,
                        softEventDraft.status === status && styles.secondaryButtonActive,
                      ]}
                      onPress={() =>
                        setSoftEventDraft((prev) =>
                          prev ? { ...prev, status } : prev
                        )
                      }
                    >
                      <Text
                        style={[
                          styles.secondaryButtonText,
                          softEventDraft.status === status && styles.secondaryButtonTextActive,
                        ]}
                      >
                        {status}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </ScrollView>
            )}
            {datePickerField && (
              <DateTimePicker
                value={datePickerValue}
                mode="datetime"
                display="default"
                onChange={(_, selectedDate) => {
                  if (!selectedDate || !softEventDraft) {
                    setDatePickerField(null);
                    return;
                  }
                  const iso = selectedDate.toISOString();
                  setSoftEventDraft({
                    ...softEventDraft,
                    [datePickerField]: iso,
                  });
                  setDatePickerField(null);
                }}
              />
            )}
            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={() => {
                  setSoftEventModalVisible(false);
                  setSoftEventDraft(null);
                  setSoftEventError(null);
                }}
              >
                <Text style={styles.secondaryButtonText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.primaryButton, styles.modalPrimary]}
                onPress={saveSoftEventDraft}
                disabled={softEventLoading || !softEventDraft}
              >
                <Text style={styles.primaryButtonText}>
                  {softEventMode === "create" ? "Create" : "Save"}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <Modal visible={summaryModalVisible} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.sectionTitle}>TL;DR</Text>
            <Text style={styles.muted}>{summaryModalText || "No summary yet."}</Text>
            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={() => {
                  setSummaryModalVisible(false);
                  setSummaryModalText("");
                }}
              >
                <Text style={styles.secondaryButtonText}>Close</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <Modal visible={replanNoteVisible} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.sectionTitle}>Replan notes</Text>
            <TextInput
              style={[styles.input, styles.textarea]}
              value={replanNote}
              onChangeText={setReplanNote}
              placeholder="Any special requests for the next 2 weeks?"
              multiline
            />
            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={() => {
                  setReplanNoteVisible(false);
                  setReplanNote("");
                }}
              >
                <Text style={styles.secondaryButtonText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.primaryButton, styles.modalPrimary]}
                onPress={async () => {
                  setReplanNoteVisible(false);
                  await handleReplanCalendar();
                  setReplanNote("");
                }}
                disabled={replanLoading}
              >
                <Text style={styles.primaryButtonText}>
                  {replanLoading ? "Replanning…" : "Replan"}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <Modal visible={!!incomingCall} transparent animationType="fade">
        <View style={styles.callScreen}>
          <View style={styles.callOrb} />
          <Text style={styles.callTitle}>Incoming call</Text>
          <Text style={styles.callSubtitle}>{incomingCall?.goal || "Call from Corv"}</Text>
          <View style={styles.callButtonRow}>
            <TouchableOpacity
              style={styles.callDeclineButton}
              onPress={async () => {
                if (!incomingCall) return;
                await declineCallSession(incomingCall.id);
              }}
            >
              <Text style={styles.callDeclineText}>Decline</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.callAnswerButton}
              onPress={async () => {
                if (!incomingCall) return;
                await answerCallSession(incomingCall.id);
              }}
            >
              <Text style={styles.callAnswerText}>Answer</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      <Modal visible={!!activeCall} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.sectionTitle}>Call in progress</Text>
            <Text style={styles.muted}>{activeCall?.goal || ""}</Text>
            {callConnecting && <Text style={styles.muted}>Connecting…</Text>}
            {callTranscriptError && (
              <Text style={styles.errorText}>Transcript error: {callTranscriptError}</Text>
            )}
            {callLiveTranscript.length > 0 && (
              <View style={styles.callTranscriptBox}>
                <ScrollView>
                  {callLiveTranscript.map((line, idx) => (
                    <Text key={`${line}-${idx}`} style={styles.callTranscriptLine}>
                      {line}
                    </Text>
                  ))}
                </ScrollView>
              </View>
            )}
            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={() => {
                  if (!activeCall) return;
                  const sessionId = activeCall.id;
                  setActiveCall(null);
                  setCallConnecting(false);
                  void stopRealtimeCall();
                  void updateCallSession(sessionId, { status: "completed" }).catch((err: any) =>
                    setError(err?.message || "Failed to end call"),
                  );
                  void refreshCallSessions();
                }}
              >
                <Text style={styles.secondaryButtonText}>End call</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <StatusBar style="auto" />
    </SafeAreaView>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <InnerApp />
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
  },
  container: {
    flex: 1,
    backgroundColor: "#0b1220",
  },
  centered: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#0b1220",
  },
  authContainer: {
    flex: 1,
    justifyContent: "center",
    padding: 24,
    backgroundColor: "#0b1220",
  },
  authCard: {
    backgroundColor: "#0f172a",
    padding: 24,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#1f2937",
  },
  authInput: {
    backgroundColor: "#0c1829",
    color: "#e5e7eb",
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#1f2937",
    marginTop: 12,
  },
  header: {
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: "#1f2937",
    backgroundColor: "#0f172a",
  },
  headerTitle: {
    color: "#e5e7eb",
    fontSize: 22,
    fontWeight: "600",
    marginBottom: 12,
  },
  headerTabs: {
    maxHeight: 42,
  },
  headerTabsContent: {
    flexDirection: "row",
    paddingRight: 8,
  },
  tabButton: {
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: 999,
    backgroundColor: "#0c1829",
    borderWidth: 1,
    borderColor: "#1f2937",
    marginRight: 8,
  },
  tabButtonActive: {
    backgroundColor: "#2ad1a3",
    borderColor: "#2ad1a3",
  },
  tabButtonText: {
    color: "#e5e7eb",
    fontWeight: "600",
  },
  tabButtonTextActive: {
    color: "#041316",
  },
  chatListRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  chatLayout: {
    flex: 1,
    flexDirection: "row",
  },
  sidebar: {
    width: 160,
    backgroundColor: "#0f172a",
    borderRightWidth: 1,
    borderRightColor: "#1f2937",
    padding: 12,
  },
  sidebarHeader: {
    marginBottom: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  sidebarHeaderLeft: {
    flex: 1,
  },
  sidebarTitle: {
    color: "#e5e7eb",
    fontWeight: "700",
    marginBottom: 8,
  },
  sidebarToggle: {
    padding: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#1f2937",
    backgroundColor: "#0c1829",
  },
  sidebarToggleFloating: {
    position: "absolute",
    left: 6,
    top: 10,
    zIndex: 10,
    padding: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#1f2937",
    backgroundColor: "#0c1829",
  },
  sidebarList: {
    paddingBottom: 12,
  },
  chatMain: {
    flex: 1,
  },
  chatPill: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: "#0c1829",
    borderWidth: 1,
    borderColor: "#1f2937",
    marginRight: 8,
  },
  chatPillActive: {
    borderColor: "#2ad1a3",
    shadowColor: "#2ad1a3",
    shadowOpacity: 0.25,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 1 },
  },
  chatPillText: {
    color: "#e5e7eb",
    fontSize: 12,
  },
  chatPillTextActive: {
    fontWeight: "600",
  },
  newChatButton: {
    backgroundColor: "#2ad1a3",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    marginRight: 8,
  },
  newChatButtonText: {
    color: "#041316",
    fontWeight: "700",
  },
  logoutButton: {
    marginLeft: "auto",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#1f2937",
  },
  logoutButtonText: {
    color: "#e5e7eb",
    fontSize: 12,
  },
  messagesList: {
    padding: 16,
  },
  messageSeparator: {
    height: 12,
  },
  messageRow: {
  },
  messageRowUser: {
    alignItems: "flex-end",
  },
  messageRowAssistant: {
    alignItems: "flex-start",
  },
  messageBubble: {
    maxWidth: "85%",
    padding: 12,
    borderRadius: 16,
    marginTop: 6,
    borderWidth: 1,
    borderColor: "#1f2937",
    backgroundColor: "rgba(255, 255, 255, 0.02)",
  },
  messageBubbleUser: {
    borderColor: "rgba(247, 194, 102, 0.6)",
  },
  messageBubbleAssistant: {
    borderColor: "rgba(42, 209, 163, 0.6)",
  },
  messageTextUser: {
    color: "#e5e7eb",
  },
  messageTextAssistant: {
    color: "#e5e7eb",
  },
  messageTimeUser: {
    marginTop: 6,
    fontSize: 10,
    color: "#94a3b8",
    opacity: 0.6,
  },
  messageTimeAssistant: {
    marginTop: 6,
    fontSize: 10,
    color: "#94a3b8",
    opacity: 0.8,
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 999,
  },
  badgeAssistant: {
    backgroundColor: "rgba(42, 209, 163, 0.15)",
  },
  badgeUser: {
    backgroundColor: "rgba(247, 194, 102, 0.15)",
  },
  badgeText: {
    fontSize: 10,
    fontWeight: "700",
  },
  badgeTextDark: {
    color: "#f7c266",
  },
  badgeTextLight: {
    color: "#2ad1a3",
  },
  jobLogButton: {
    marginTop: 10,
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#1f2937",
    alignSelf: "flex-start",
  },
  jobLogButtonText: {
    color: "#e5e7eb",
    fontSize: 12,
    fontWeight: "600",
  },
  inputRow: {
    flexDirection: "row",
    alignItems: "center",
    padding: 12,
    borderTopWidth: 1,
    borderTopColor: "#1f2937",
    backgroundColor: "#0f172a",
  },
  input: {
    flex: 1,
    backgroundColor: "#0c1829",
    color: "#e5e7eb",
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#1f2937",
  },
  inputButton: {
    backgroundColor: "#0c1829",
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#1f2937",
  },
  inputButtonText: {
    color: "#e5e7eb",
  },
  primaryButton: {
    backgroundColor: "#2ad1a3",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 12,
  },
  sendButton: {
    marginLeft: 10,
  },
  micButton: {
    backgroundColor: "#0f172a",
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#1f2937",
    marginRight: 10,
  },
  micButtonActive: {
    borderColor: "#b91c1c",
  },
  micButtonText: {
    color: "#e5e7eb",
    fontWeight: "600",
  },
  primaryButtonText: {
    color: "#041316",
    fontWeight: "700",
  },
  secondaryButton: {
    borderWidth: 1,
    borderColor: "#1f2937",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
    backgroundColor: "rgba(255, 255, 255, 0.02)",
  },
  secondaryButtonActive: {
    backgroundColor: "#2ad1a3",
    borderColor: "#2ad1a3",
  },
  secondaryButtonText: {
    color: "#e5e7eb",
    fontWeight: "600",
  },
  secondaryButtonTextActive: {
    color: "#041316",
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  label: {
    color: "#e5e7eb",
    marginTop: 12,
    marginBottom: 6,
  },
  muted: {
    color: "#94a3b8",
  },
  errorText: {
    color: "#ff8277",
    marginVertical: 8,
  },
  scrollContent: {
    padding: 16,
  },
  sectionTitle: {
    color: "#e5e7eb",
    fontSize: 18,
    fontWeight: "600",
    marginTop: 12,
  },
  usageCard: {
    padding: 12,
    borderRadius: 12,
    backgroundColor: "#0f172a",
    borderWidth: 1,
    borderColor: "#1f2937",
    marginTop: 8,
  },
  usageStat: {
    color: "#e5e7eb",
    marginTop: 4,
  },
  usageRow: {
    padding: 12,
    borderRadius: 12,
    backgroundColor: "rgba(255, 255, 255, 0.02)",
    borderWidth: 1,
    borderColor: "#1f2937",
    marginTop: 8,
  },
  usageRowTitle: {
    color: "#e5e7eb",
    fontWeight: "600",
  },
  cacheRow: {
    flexDirection: "row",
    flexWrap: "wrap",
  },
  cachePill: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: "#0c1829",
    borderWidth: 1,
    borderColor: "#1f2937",
    marginRight: 8,
    marginBottom: 8,
  },
  cachePillActive: {
    backgroundColor: "#2ad1a3",
    borderColor: "#2ad1a3",
  },
  cachePillText: {
    color: "#e5e7eb",
  },
  cachePillTextActive: {
    color: "#041316",
    fontWeight: "600",
  },
  rowActions: {
    flexDirection: "row",
    marginTop: 8,
  },
  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  rowActionButton: {
    marginRight: 8,
  },
  textarea: {
    minHeight: 110,
    textAlignVertical: "top",
  },
  calendarRow: {
    padding: 12,
    borderRadius: 12,
    backgroundColor: "rgba(255, 255, 255, 0.02)",
    borderWidth: 1,
    borderColor: "#1f2937",
    marginTop: 8,
  },
  unreadCard: {
    borderColor: "#2ad1a3",
  },
  calendarLegend: {
    flexDirection: "row",
    gap: 12,
    marginTop: 8,
    marginBottom: 6,
  },
  calendarLegendItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  calendarLegendDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  calendarLegendHard: {
    backgroundColor: "#f7c266",
  },
  calendarLegendSoft: {
    backgroundColor: "#2ad1a3",
  },
  calendarGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginTop: 8,
    marginBottom: 12,
  },
  calendarWeekHeader: {
    flexDirection: "row",
    marginTop: 8,
  },
  calendarWeekHeaderLabel: {
    width: "14.28%",
    textAlign: "center",
    color: "#94a3b8",
    fontSize: 11,
    fontWeight: "700",
  },
  calendarCell: {
    width: "14.28%",
    padding: 6,
    borderWidth: 1,
    borderColor: "#1f2937",
    backgroundColor: "#0c1829",
    position: "relative",
  },
  calendarCellPlaceholder: {
    backgroundColor: "transparent",
    borderColor: "transparent",
  },
  calendarCellActive: {
    borderColor: "#2ad1a3",
  },
  calendarCellWarningRed: {
    borderColor: "#ef4444",
  },
  calendarCellWarningOrange: {
    borderColor: "#f59e0b",
  },
  calendarCellWarningDot: {
    position: "absolute",
    top: 4,
    right: 4,
    width: 6,
    height: 6,
    borderRadius: 999,
    backgroundColor: "#ef4444",
  },
  calendarCellLabel: {
    color: "#e5e7eb",
    fontSize: 11,
    fontWeight: "700",
  },
  calendarCellBadgeHard: {
    color: "#f7c266",
    fontSize: 10,
    marginTop: 4,
  },
  calendarCellBadgeSoft: {
    color: "#2ad1a3",
    fontSize: 10,
    marginTop: 2,
  },
  calendarSubTitle: {
    color: "#e5e7eb",
    fontSize: 14,
    fontWeight: "600",
    marginTop: 8,
  },
  calendarTitle: {
    color: "#e5e7eb",
    fontWeight: "600",
  },
  jobsPanel: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: "#1f2531",
  },
  jobRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 8,
  },
  jobInfo: {
    flex: 1,
    marginRight: 12,
  },
  jobTitle: {
    color: "#e5e7eb",
    fontWeight: "600",
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0, 0, 0, 0.6)",
    justifyContent: "center",
    padding: 24,
  },
  modalCard: {
    backgroundColor: "#0f172a",
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: "#1f2937",
  },
  callScreen: {
    flex: 1,
    backgroundColor: "#0b1018",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 32,
  },
  callOrb: {
    width: 180,
    height: 180,
    borderRadius: 90,
    backgroundColor: "#132033",
    borderWidth: 2,
    borderColor: "#2ad1a3",
    shadowColor: "#2ad1a3",
    shadowOpacity: 0.35,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 6 },
  },
  callTitle: {
    color: "#e5e7eb",
    fontSize: 28,
    fontWeight: "700",
    marginTop: 24,
  },
  callSubtitle: {
    color: "#9fb0c3",
    fontSize: 16,
    textAlign: "center",
    marginTop: 8,
    marginBottom: 40,
  },
  callButtonRow: {
    flexDirection: "row",
    alignItems: "center",
  },
  callDeclineButton: {
    paddingVertical: 14,
    paddingHorizontal: 24,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#d14b4b",
    backgroundColor: "#241517",
    marginRight: 14,
  },
  callAnswerButton: {
    paddingVertical: 14,
    paddingHorizontal: 28,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#2ad1a3",
    backgroundColor: "#14392f",
  },
  callDeclineText: {
    color: "#f6b5b5",
    fontWeight: "600",
  },
  callAnswerText: {
    color: "#d9fdf1",
    fontWeight: "700",
  },
  callTranscriptBox: {
    marginTop: 12,
    maxHeight: 160,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#1f2937",
    padding: 10,
    backgroundColor: "#0b1220",
  },
  callTranscriptLine: {
    color: "#d7ddea",
    fontSize: 12,
    marginBottom: 6,
  },
  jobLogList: {
    marginTop: 10,
    maxHeight: 320,
  },
  jobLogRow: {
    paddingVertical: 8,
  },
  jobLogMeta: {
    flexDirection: "row",
    alignItems: "center",
  },
  jobLogRole: {
    color: "#e5e7eb",
    fontWeight: "700",
    marginRight: 8,
  },
  jobLogTime: {
    color: "#94a3b8",
    marginRight: 8,
  },
  jobLogType: {
    color: "#f7c266",
  },
  jobLogText: {
    color: "#e5e7eb",
    marginTop: 4,
  },
  modalActions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    marginTop: 12,
  },
  modalPrimary: {
    marginLeft: 12,
  },
  title: {
    color: "#e5e7eb",
    fontSize: 22,
    fontWeight: "700",
    marginBottom: 8,
  },
});
