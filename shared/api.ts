import {
  ChatListItem,
  Message,
  SendTextResponse,
  Job,
  UsageEvent,
  UsageSummary,
  CalendarReplanResult,
  CombinedCalendar,
  SoftEventDetail,
  ScheduledTask,
  ScheduledTaskRun,
  UserMessage,
  CallSession,
  CallTranscriptEntry,
} from "./types";

type TokenGetter = () => string | null | Promise<string | null>;

export type ApiConfig = {
  baseUrl: string;
  getToken?: TokenGetter;
};

async function resolveToken(getToken?: TokenGetter): Promise<string | null> {
  if (!getToken) return null;
  return await getToken();
}

async function request<T>(
  config: ApiConfig,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const token = await resolveToken(config.getToken);
  const headers: Record<string, string> = {
    ...(token ? { "X-App-Token": token } : {}),
    ...(init?.headers ? (init.headers as Record<string, string>) : {}),
  };
  if (!headers["Content-Type"] && !(init?.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${config.baseUrl}${path}`, {
    ...init,
    headers,
  });

  if (!res.ok) {
    const text = await res.text();
    const err: any = new Error(text || `Request failed with ${res.status}`);
    err.status = res.status;
    throw err;
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

export function createApi(config: ApiConfig) {
  return {
    fetchChats() {
      return request<ChatListItem[]>(config, "/chats/");
    },
    createChat(chat_nickname?: string | null) {
      return request<{ chat_id: string }>(config, "/chats/", {
        method: "POST",
        body: JSON.stringify({ chat_nickname }),
      });
    },
    renameChat(chat_id: string, payload: { nickname?: string | null; archived?: boolean }) {
      return request<{ chat_id: string; chat_nickname?: string | null; archived?: boolean }>(
        config,
        `/chats/${chat_id}`,
        {
          method: "PATCH",
          body: JSON.stringify(payload),
        },
      );
    },
    deleteChat(chat_id: string) {
      return request<void>(config, `/chats/${chat_id}`, {
        method: "DELETE",
      });
    },
    fetchMessages(chat_id: string, visible_only: boolean = true) {
      const suffix = visible_only ? "?visible_only=true" : "";
      return request<Message[]>(config, `/chats/${chat_id}/messages${suffix}`);
    },
    fetchJobMessages(chat_id: string, job_id: string) {
      const qs = `?visible_only=false&job_id=${encodeURIComponent(job_id)}`;
      return request<Message[]>(config, `/chats/${chat_id}/messages${qs}`);
    },
    fetchJobMessagesDirect(job_id: string) {
      return request<Message[]>(config, `/orchestration/jobs/${job_id}/messages`);
    },
    sendText(chat_id: string, text: string) {
      return request<SendTextResponse>(config, "/input/text/", {
        method: "POST",
        body: JSON.stringify({ chat_id, text }),
      });
    },
    async sendVoice(chat_id: string, file: Blob) {
      const formData = new FormData();
      formData.append("chat_id", chat_id);
      formData.append("file", file, "voice.webm");

      const token = await resolveToken(config.getToken);
      const res = await fetch(`${config.baseUrl}/input/voice/`, {
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

      return (await res.json()) as SendTextResponse;
    },
    fetchJobs(chat_id?: string) {
      const qs = chat_id ? `?chat_id=${encodeURIComponent(chat_id)}` : "";
      return request<Job[]>(config, `/orchestration/jobs${qs}`);
    },
    cancelJob(job_id: string) {
      return request<Job>(config, `/orchestration/jobs/${job_id}/cancel`, {
        method: "POST",
      });
    },
    fetchUsageRecent(limit = 50) {
      return request<UsageEvent[]>(config, `/orchestration/usage/recent?limit=${limit}`);
    },
    fetchUsageSummary(days = 7) {
      return request<UsageSummary>(config, `/orchestration/usage/summary?days=${days}`);
    },
    fetchSettings() {
      return request<{
        frontman_model: string;
        caller_model: string;
        cache_mode: string;
        max_function_result_chars: number;
      }>(config, "/orchestration/settings");
    },
    updateSettings(payload: {
      frontman_model?: string;
      caller_model?: string;
      cache_mode?: string;
      max_function_result_chars?: number;
    }) {
      return request<{
        frontman_model: string;
        caller_model: string;
        cache_mode: string;
        max_function_result_chars: number;
      }>(config, "/orchestration/settings", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    fetchCalendarCombined(params: { days?: number } = {}) {
      const qs = params.days ? `?days=${params.days}` : "";
      return request<CombinedCalendar>(config, `/orchestration/calendar/combined${qs}`);
    },
    createSoftEvent(payload: Partial<SoftEventDetail> & { title: string }) {
      return request<SoftEventDetail>(config, "/orchestration/soft_events", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    replanCalendar(payload: { days?: number; note?: string } = {}) {
      const params = new URLSearchParams();
      if (payload.days) {
        params.set("days", String(payload.days));
      }
      if (payload.note) {
        params.set("note", payload.note);
      }
      const suffix = params.toString() ? `?${params.toString()}` : "";
      return request<CalendarReplanResult>(config, `/orchestration/calendar/replan${suffix}`, {
        method: "POST",
      });
    },
    fetchSoftEvent(soft_event_id: string) {
      return request<SoftEventDetail>(config, `/orchestration/soft_events/${soft_event_id}`);
    },
    updateSoftEvent(
      soft_event_id: string,
      payload: Partial<SoftEventDetail> & {
        soft_deadline?: string | null;
        hard_deadline?: string | null;
      },
    ) {
      return request<SoftEventDetail>(config, `/orchestration/soft_events/${soft_event_id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    },
    promoteSoftSlot(slot_id: string) {
      return request<{ updated: number }>(config, `/orchestration/soft_slots/${slot_id}/promote`, {
        method: "POST",
      });
    },
    fetchScheduledTasks() {
      return request<ScheduledTask[]>(config, `/orchestration/scheduled_tasks`);
    },
    createScheduledTask(payload: { prompt: string; start_at?: string; recurrence?: string }) {
      return request<ScheduledTask>(config, `/orchestration/scheduled_tasks`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    updateScheduledTask(
      task_id: string,
      payload: { prompt?: string; start_at?: string; recurrence?: string; status?: string },
    ) {
      return request<ScheduledTask>(config, `/orchestration/scheduled_tasks/${task_id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    },
    fetchScheduledTaskRuns(task_id: string) {
      return request<ScheduledTaskRun[]>(
        config,
        `/orchestration/scheduled_tasks/${task_id}/runs`,
      );
    },
    registerPushToken(payload: { token: string; platform?: string }) {
      const params = new URLSearchParams({ token: payload.token });
      if (payload.platform) {
        params.set("platform", payload.platform);
      }
      return request<{ id: string; token: string; platform: string }>(
        config,
        `/orchestration/push_tokens?${params.toString()}`,
        { method: "POST" },
      );
    },
    fetchInboxMessages(params: { unread_only?: boolean } = {}) {
      const qs = params.unread_only ? "?unread_only=true" : "";
      return request<UserMessage[]>(config, `/orchestration/messages${qs}`);
    },
    markMessageRead(message_id: string) {
      return request<UserMessage>(config, `/orchestration/messages/${message_id}/read`, {
        method: "PATCH",
      });
    },
    fetchCallSessions(status?: string) {
      const qs = status ? `?status=${encodeURIComponent(status)}` : "";
      return request<CallSession[]>(config, `/orchestration/call_sessions${qs}`);
    },
    createCallSession(payload: { goal: string; scheduled_for?: string }) {
      const params = new URLSearchParams({ goal: payload.goal });
      if (payload.scheduled_for) {
        params.set("scheduled_for", payload.scheduled_for);
      }
      return request<CallSession>(config, `/orchestration/call_sessions?${params.toString()}`, {
        method: "POST",
      });
    },
    updateCallSession(session_id: string, payload: { status?: string }) {
      const params = new URLSearchParams();
      if (payload.status) {
        params.set("status", payload.status);
      }
      const suffix = params.toString() ? `?${params.toString()}` : "";
      return request<CallSession>(config, `/orchestration/call_sessions/${session_id}${suffix}`, {
        method: "PATCH",
      });
    },
    addCallTranscriptEntry(session_id: string, payload: { role: string; content: string }) {
      const params = new URLSearchParams({
        role: payload.role,
        content: payload.content,
      });
      return request<CallTranscriptEntry>(
        config,
        `/orchestration/call_sessions/${session_id}/transcript?${params.toString()}`,
        {
          method: "POST",
        },
      );
    },
    createRealtimeToken(session_id: string) {
      return request<any>(config, `/orchestration/call_sessions/${session_id}/realtime_token`, {
        method: "POST",
      });
    },
  };
}
