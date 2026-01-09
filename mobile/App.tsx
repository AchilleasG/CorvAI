import { StatusBar } from "expo-status-bar";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
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
import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import Constants from "expo-constants";
import {
  RTCPeerConnection,
  RTCSessionDescription,
  mediaDevices,
} from "react-native-webrtc";
import {
  cancelJob,
  createChat,
  deleteChat,
  fetchCalendarCombined,
  fetchChats,
  fetchJobs,
  fetchMessages,
  fetchJobMessagesDirect,
  fetchSettings,
  fetchUsageRecent,
  fetchUsageSummary,
  renameChat,
  sendText,
  sendVoice,
  updateSettings,
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
} from "./src/api";
import {
  ChatListItem,
  CombinedCalendar,
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

type TabKey = "chat" | "settings" | "calendar" | "scheduler" | "messages" | "calls";

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
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<any>(null);
  const localStreamRef = useRef<any>(null);
  const [summaryModalVisible, setSummaryModalVisible] = useState(false);
  const [summaryModalText, setSummaryModalText] = useState("");
  const [calendarData, setCalendarData] = useState<CombinedCalendar | null>(null);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [selectedDayKey, setSelectedDayKey] = useState<string | null>(null);
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
    (async () => {
      try {
        if (!Device.isDevice) return;
        const { status: existingStatus } = await Notifications.getPermissionsAsync();
        let finalStatus = existingStatus;
        if (existingStatus !== "granted") {
          const { status } = await Notifications.requestPermissionsAsync();
          finalStatus = status;
        }
        if (finalStatus !== "granted") return;
        const projectId =
          Constants.easConfig?.projectId || Constants.expoConfig?.extra?.eas?.projectId;
        const token = await Notifications.getExpoPushTokenAsync({
          projectId,
        });
        await registerPushToken({
          token: token.data,
          platform: Platform.OS,
        });
      } catch (err) {
        // ignore push registration errors
      }
    })();
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
    setCalendarLoading(true);
    setCalendarError(null);
    fetchCalendarCombined({ days: 14 })
      .then((data) => setCalendarData(data))
      .catch((err: any) => setCalendarError(err.message || "Failed to load calendar"))
      .finally(() => setCalendarLoading(false));
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
      days.push({
        key: dayStart.toISOString().slice(0, 10),
        date: dayStart,
        label: dayStart.toLocaleDateString([], { weekday: "short", day: "2-digit" }),
        hard,
        soft,
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

  async function stopRealtimeCall() {
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
      if (type.includes("transcript") && transcript) {
        addCallTranscriptEntry(sessionId, { role: "assistant", content: String(transcript) }).catch(() => undefined);
      }
      if (type.includes("input_audio_transcription") && transcript) {
        addCallTranscriptEntry(sessionId, { role: "user", content: String(transcript) }).catch(() => undefined);
      }
    } catch {
      // ignore parse errors
    }
  }

  async function startRealtimeCall(session: CallSession) {
    try {
      setCallConnecting(true);
      const tokenResp = await createRealtimeToken(session.id);
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
      localStreamRef.current = localStream;
      localStream.getTracks().forEach((track: any) => {
        pc.addTrack(track, localStream);
      });

      const dataChannel = pc.createDataChannel("oai-events");
      dataChannelRef.current = dataChannel;
      dataChannel.onmessage = (msg: any) => handleRealtimeMessage(session.id, msg.data);

      const offer = await pc.createOffer({ offerToReceiveAudio: true });
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
      const answerSdp = await sdpResp.text();
      await pc.setRemoteDescription(new RTCSessionDescription({ type: "answer", sdp: answerSdp }));

      dataChannel.onopen = () => {
        dataChannel.send(
          JSON.stringify({
            type: "response.create",
            response: {
              modalities: ["audio", "text"],
              instructions: `Call goal: ${session.goal}. Be concise and helpful.`,
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
            placeholder="gpt-5.2"
          />
          <Text style={styles.label}>Caller model</Text>
          <TextInput
            style={styles.input}
            value={settingsDraft.caller_model || ""}
            onChangeText={(value) =>
              setSettingsDraft((prev) => ({ ...prev, caller_model: value }))
            }
            placeholder="gpt-5.2"
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
                  return (
                    <TouchableOpacity
                      key={day.key}
                      style={[styles.calendarCell, isActive && styles.calendarCellActive]}
                      onPress={() => setSelectedDayKey(day.key)}
                    >
                      <Text style={styles.calendarCellLabel}>{day.label}</Text>
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
                                <Text style={styles.muted}>
                                  {formatDateTime(event.start)} - {formatDateTime(event.end)}
                                </Text>
                              </View>
                            ))}
                          </>
                        )}
                        {!!selected.soft.length && (
                          <>
                            <Text style={styles.calendarSubTitle}>Soft slots</Text>
                            {selected.soft.map((slot) => (
                              <View key={slot.id} style={styles.calendarRow}>
                                <Text style={styles.calendarTitle}>{slot.title}</Text>
                                <Text style={styles.muted}>
                                  {formatDateTime(slot.start)} - {formatDateTime(slot.end)}
                                </Text>
                                <Text style={styles.muted}>Status: {slot.status}</Text>
                              </View>
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
                  <View key={event.id} style={styles.calendarRow}>
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
                  </View>
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

      <Modal visible={!!incomingCall} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.sectionTitle}>Incoming call</Text>
            <Text style={styles.muted}>{incomingCall?.goal || "Call from Corv"}</Text>
            <View style={styles.modalActions}>
              <TouchableOpacity
                style={[styles.secondaryButton, styles.rowActionButton]}
                onPress={async () => {
                  if (!incomingCall) return;
                  await updateCallSession(incomingCall.id, { status: "missed" });
                  setIncomingCall(null);
                  await refreshCallSessions();
                }}
              >
                <Text style={styles.secondaryButtonText}>Decline</Text>
              </TouchableOpacity>
                <TouchableOpacity
                  style={styles.primaryButton}
                  onPress={async () => {
                    if (!incomingCall) return;
                    await updateCallSession(incomingCall.id, { status: "in_call" });
                    setActiveCall(incomingCall);
                    await startRealtimeCall(incomingCall);
                    setIncomingCall(null);
                    await refreshCallSessions();
                  }}
                >
                <Text style={styles.primaryButtonText}>Answer</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <Modal visible={!!activeCall} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.sectionTitle}>Call in progress</Text>
            <Text style={styles.muted}>{activeCall?.goal || ""}</Text>
            {callConnecting && <Text style={styles.muted}>Connecting…</Text>}
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
  secondaryButtonText: {
    color: "#e5e7eb",
    fontWeight: "600",
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
  },
  calendarCellPlaceholder: {
    backgroundColor: "transparent",
    borderColor: "transparent",
  },
  calendarCellActive: {
    borderColor: "#2ad1a3",
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
