import {
  ChatListItem,
  Message,
  SendTextResponse,
  Job,
  JobEvent,
  UsageEvent,
  UsageSummary,
  CalendarReplanResult,
  CombinedCalendar,
  StudyCourse,
  StudyMaterial,
  StudyMaterialProcessResponse,
  StudyExam,
  StudyTopic,
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

type NativeUploadFile = {
  uri: string;
  name: string;
  type?: string | null;
};

function isNativeUploadFile(value: unknown): value is NativeUploadFile {
  return !!value && typeof value === "object" && "uri" in value && "name" in value;
}

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
    fetchJobEvents(job_id: string) {
      return request<{ job_id: string; events: JobEvent[] }>(
        config,
        `/orchestration/jobs/${job_id}/events`,
      );
    },
    restartStudyJob(job_id: string, force = false) {
      const formData = new FormData();
      formData.append("force", force ? "true" : "false");
      return request<{ job: Job }>(config, `/study/jobs/${job_id}/restart`, {
        method: "POST",
        body: formData,
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
        study_model: string;
        cache_mode: string;
        max_function_result_chars: number;
      }>(config, "/orchestration/settings");
    },
    updateSettings(payload: {
      frontman_model?: string;
      caller_model?: string;
      study_model?: string;
      cache_mode?: string;
      max_function_result_chars?: number;
    }) {
      return request<{
        frontman_model: string;
        caller_model: string;
        study_model: string;
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
    fetchStudyCourses(status?: string) {
      const qs = status ? `?status=${encodeURIComponent(status)}` : "";
      return request<{ courses: StudyCourse[] }>(config, `/study/courses${qs}`);
    },
    createStudyCourse(payload: {
      title: string;
      code?: string;
      description?: string;
      term_start_date?: string;
      term_end_date?: string;
      status?: string;
    }) {
      const formData = new FormData();
      formData.append("title", payload.title);
      if (payload.code) formData.append("code", payload.code);
      if (payload.description) formData.append("description", payload.description);
      if (payload.term_start_date) formData.append("term_start_date", payload.term_start_date);
      if (payload.term_end_date) formData.append("term_end_date", payload.term_end_date);
      if (payload.status) formData.append("status", payload.status);
      return request<StudyCourse>(config, `/study/courses`, {
        method: "POST",
        body: formData,
      });
    },
    updateStudyCourse(
      course_id: string,
      payload: Partial<Pick<StudyCourse, "title" | "code" | "description" | "term_start_date" | "term_end_date" | "status">>,
    ) {
      const formData = new FormData();
      if (payload.title !== undefined) formData.append("title", payload.title);
      if (payload.code !== undefined) formData.append("code", payload.code);
      if (payload.description !== undefined) formData.append("description", payload.description);
      if (payload.term_start_date !== undefined) formData.append("term_start_date", payload.term_start_date || "");
      if (payload.term_end_date !== undefined) formData.append("term_end_date", payload.term_end_date || "");
      if (payload.status !== undefined) formData.append("status", payload.status);
      return request<StudyCourse>(config, `/study/courses/${course_id}`, { method: "PATCH", body: formData });
    },
    deleteStudyCourse(course_id: string) {
      return request<{ ok: boolean }>(config, `/study/courses/${course_id}`, { method: "DELETE" });
    },
    fetchStudyMaterials(course_id?: string) {
      const qs = course_id ? `?course_id=${encodeURIComponent(course_id)}` : "";
      return request<{ materials: StudyMaterial[] }>(config, `/study/materials${qs}`);
    },
    fetchStudyTopics(course_id: string) {
      return request<{ topics: StudyTopic[] }>(config, `/study/topics?course_id=${encodeURIComponent(course_id)}`);
    },
    fetchStudyExams(course_id: string) {
      return request<{ exams: StudyExam[] }>(config, `/study/exams?course_id=${encodeURIComponent(course_id)}`);
    },
    createStudyTopic(payload: {
      course_id: string;
      name: string;
      description?: string;
      order_index?: number;
      estimated_effort_minutes?: number;
      weight?: number;
    }) {
      const formData = new FormData();
      formData.append("course_id", payload.course_id);
      formData.append("name", payload.name);
      if (payload.description) formData.append("description", payload.description);
      if (payload.order_index !== undefined) formData.append("order_index", String(payload.order_index));
      if (payload.estimated_effort_minutes !== undefined) {
        formData.append("estimated_effort_minutes", String(payload.estimated_effort_minutes));
      }
      if (payload.weight !== undefined) formData.append("weight", String(payload.weight));
      return request<StudyTopic>(config, `/study/topics`, { method: "POST", body: formData });
    },
    createStudyExam(payload: {
      course_id: string;
      title: string;
      kind?: string;
      scheduled_at?: string;
      weight?: number;
      notes?: string;
    }) {
      const formData = new FormData();
      formData.append("course_id", payload.course_id);
      formData.append("title", payload.title);
      if (payload.kind) formData.append("kind", payload.kind);
      if (payload.scheduled_at) formData.append("scheduled_at", payload.scheduled_at);
      if (payload.weight !== undefined) formData.append("weight", String(payload.weight));
      if (payload.notes) formData.append("notes", payload.notes);
      return request<StudyExam>(config, `/study/exams`, { method: "POST", body: formData });
    },
    updateStudyExam(
      exam_id: string,
      payload: Partial<Pick<StudyExam, "title" | "kind" | "scheduled_at" | "weight" | "notes">>,
    ) {
      const formData = new FormData();
      if (payload.title !== undefined) formData.append("title", payload.title);
      if (payload.kind !== undefined) formData.append("kind", payload.kind);
      if (payload.scheduled_at !== undefined) formData.append("scheduled_at", payload.scheduled_at || "");
      if (payload.weight !== undefined) formData.append("weight", String(payload.weight));
      if (payload.notes !== undefined) formData.append("notes", payload.notes);
      return request<StudyExam>(config, `/study/exams/${exam_id}`, { method: "PATCH", body: formData });
    },
    deleteStudyExam(exam_id: string) {
      return request<{ ok: boolean }>(config, `/study/exams/${exam_id}`, { method: "DELETE" });
    },
    updateStudyTopic(
      topic_id: string,
      payload: Partial<Pick<StudyTopic, "name" | "description" | "order_index" | "estimated_effort_minutes" | "weight" | "status" | "passed" | "grade">>,
    ) {
      const formData = new FormData();
      if (payload.name !== undefined) formData.append("name", payload.name);
      if (payload.description !== undefined) formData.append("description", payload.description);
      if (payload.order_index !== undefined) formData.append("order_index", String(payload.order_index));
      if (payload.estimated_effort_minutes !== undefined) {
        formData.append("estimated_effort_minutes", String(payload.estimated_effort_minutes));
      }
      if (payload.weight !== undefined) formData.append("weight", String(payload.weight));
      if (payload.status !== undefined) formData.append("status", payload.status);
      if (payload.passed !== undefined) formData.append("passed", payload.passed ? "true" : "false");
      if (payload.grade !== undefined && payload.grade !== null) formData.append("grade", String(payload.grade));
      return request<StudyTopic>(config, `/study/topics/${topic_id}`, { method: "PATCH", body: formData });
    },
    deleteStudyTopic(topic_id: string) {
      return request<{ ok: boolean }>(config, `/study/topics/${topic_id}`, { method: "DELETE" });
    },
    uploadStudyMaterial(payload: {
      course_id: string;
      title: string;
      kind?: string;
      notes?: string;
      source_text?: string;
      topic_id?: string;
      exam_id?: string;
      source_url?: string;
      process_now?: boolean;
      file?: NativeUploadFile | File | Blob | null;
    }) {
      const formData = new FormData();
      formData.append("course_id", payload.course_id);
      formData.append("title", payload.title);
      if (payload.kind) formData.append("kind", payload.kind);
      if (payload.notes) formData.append("notes", payload.notes);
      if (payload.source_text) formData.append("source_text", payload.source_text);
      if (payload.topic_id) formData.append("topic_id", payload.topic_id);
      if (payload.exam_id) formData.append("exam_id", payload.exam_id);
      if (payload.source_url) formData.append("source_url", payload.source_url);
      if (typeof payload.process_now === "boolean") {
        formData.append("process_now", payload.process_now ? "true" : "false");
      }
      if (payload.file && isNativeUploadFile(payload.file)) {
        formData.append(
          "file",
          {
            uri: payload.file.uri,
            name: payload.file.name,
            type: payload.file.type || "application/octet-stream",
          } as any,
        );
      } else if (payload.file) {
        const fileName = payload.file instanceof File ? payload.file.name : "study-material";
        formData.append("file", payload.file, fileName);
      }
      return request<StudyMaterialProcessResponse>(config, "/study/materials/upload", {
        method: "POST",
        body: formData,
      });
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
