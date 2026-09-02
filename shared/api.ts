import {
  UserNote,
  KnowledgeEntity,
  KnowledgeEntityType,
  KnowledgeSearchResult,
  LocationSearchResult,
  ChatListItem,
  Message,
  SendTextResponse,
  Job,
  JobEvent,
  UsageEvent,
  UsageSummary,
  CombinedCalendar,
  Objective,
  ObjectiveLog,
  ObjectiveTask,
  ObjectiveTaskPicker,
  HardEventTaskLink,
  SoftSlotOutcomeResult,
  StudyCourse,
  StudyMaterial,
  StudyMaterialProcessResponse,
  StudyExam,
  StudyTopic,
  StudyTopicAudiobookVersion,
  StudyAssignment,
  SoftEventDetail,
  ScheduledTask,
  ScheduledTaskRun,
  UserMessage,
  CallSession,
  CallTranscriptEntry,
  SshMachine,
  SshMachineInput,
  SshCommandResult,
  SshCommandRecord,
  SshTerminalSession,
  CodingCliStatus,
  CodingDeviceAuth,
  CodingSession,
  CodingTurn,
  CodingTerminal,
  CodingLiveLogs,
  FeatureDelegation,
  ManagedFile,
  WorkoutExercise,
  WorkoutExerciseSpec,
  WorkoutPlan,
  WorkoutSession,
  WorkoutExerciseLog,
  WorkoutGoal,
  WorkoutDashboard,
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

async function requestBlob(config: ApiConfig, path: string): Promise<Blob> {
  const token = await resolveToken(config.getToken);
  const res = await fetch(`${config.baseUrl}${path}`, {
    headers: token ? { "X-App-Token": token } : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed with ${res.status}`);
  }
  return await res.blob();
}

export function createApi(config: ApiConfig) {
  return {
    fetchNotes(filters: { query?: string; tags?: string[] } = {}) {
      const params = new URLSearchParams();
      if (filters.query?.trim()) params.set("query", filters.query.trim());
      if (filters.tags?.length) params.set("tags", filters.tags.join(","));
      const suffix = params.size ? `?${params.toString()}` : "";
      return request<{ notes: UserNote[]; tags: string[]; count: number }>(config, `/orchestration/notes${suffix}`);
    },
    createNote(payload: { content: string; tags?: string[]; expires_at?: string | null }) {
      return request<UserNote>(config, "/orchestration/notes", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    updateNote(note_id: string, payload: { content: string; tags?: string[]; expires_at?: string | null }) {
      return request<UserNote>(config, `/orchestration/notes/${note_id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    },
    deleteNote(note_id: string) {
      return request<{ deleted: boolean; id: string }>(config, `/orchestration/notes/${note_id}`, {
        method: "DELETE",
      });
    },
    fetchKnowledgeEntities(entityType:KnowledgeEntityType, filters:{query?:string;tags?:string[]}={}) {
      const params=new URLSearchParams(); if(filters.query?.trim())params.set("query",filters.query.trim()); if(filters.tags?.length)params.set("tags",filters.tags.join(","));
      return request<{entity_type:string;entities:KnowledgeEntity[]}>(config,`/orchestration/knowledge/${entityType}${params.size?`?${params}`:""}`);
    },
    createKnowledgeEntity(entityType:KnowledgeEntityType,payload:Record<string,unknown>) { return request<KnowledgeEntity>(config,`/orchestration/knowledge/${entityType}`,{method:"POST",body:JSON.stringify(payload)}); },
    updateKnowledgeEntity(entityType:KnowledgeEntityType,entityId:string,payload:Record<string,unknown>) { return request<KnowledgeEntity>(config,`/orchestration/knowledge/${entityType}/${entityId}`,{method:"PATCH",body:JSON.stringify(payload)}); },
    deleteKnowledgeEntity(entityType:KnowledgeEntityType,entityId:string) { return request<{deleted:boolean;id:string}>(config,`/orchestration/knowledge/${entityType}/${entityId}`,{method:"DELETE"}); },
    searchKnowledge(query:string,tags:string[]=[],limit=20) { const params=new URLSearchParams({query,limit:String(limit)});if(tags.length)params.set("tags",tags.join(","));return request<{query:string;preferred_types:KnowledgeEntityType[];results:KnowledgeSearchResult[]}>(config,`/orchestration/knowledge/search?${params}`); },
    fetchKnowledgeTags() { return request<{tags:string[]}>(config,"/orchestration/knowledge/tags"); },
    searchLocations(query:string,limit=6) { const params=new URLSearchParams({query,limit:String(limit)});return request<{query:string;results:LocationSearchResult[];attribution:string}>(config,`/orchestration/knowledge/location-search?${params}`); },
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
    fetchFiles(filters?: { session_id?: string; turn_id?: string; delegation_id?: string; tag?: string }) {
      const params = new URLSearchParams();
      if (filters?.session_id) params.set("session_id", filters.session_id);
      if (filters?.turn_id) params.set("turn_id", filters.turn_id);
      if (filters?.delegation_id) params.set("delegation_id", filters.delegation_id);
      if (filters?.tag) params.set("tag", filters.tag);
      const query = params.toString();
      return request<{ files: ManagedFile[] }>(config, `/files${query ? `?${query}` : ""}`);
    },
    uploadFile(file: Blob, options?: { filename?: string; metadata?: Record<string, unknown>; tags?: string[]; session_id?: string; turn_id?: string }) {
      const formData = new FormData();
      formData.append("file", file, options?.filename || (file as File).name || "file");
      formData.append("metadata", JSON.stringify(options?.metadata || {}));
      formData.append("tags", JSON.stringify(options?.tags || []));
      if (options?.session_id) formData.append("session_id", options.session_id);
      if (options?.turn_id) formData.append("turn_id", options.turn_id);
      return request<ManagedFile>(config, "/files/upload", { method: "POST", body: formData });
    },
    updateFile(file_id: string, payload: { filename?: string; content_type?: string; metadata?: Record<string, unknown>; tags?: string[] }) {
      return request<ManagedFile>(config, `/files/${file_id}`, { method: "PATCH", body: JSON.stringify(payload) });
    },
    deleteFile(file_id: string) { return request<{ ok: boolean }>(config, `/files/${file_id}`, { method: "DELETE" }); },
    fetchFileContent(file_id: string, download = false) { return requestBlob(config, `/files/${file_id}/content${download ? "?download=true" : ""}`); },
    fetchJobMessages(chat_id: string, job_id: string) {
      const qs = `?visible_only=false&job_id=${encodeURIComponent(job_id)}`;
      return request<Message[]>(config, `/chats/${chat_id}/messages${qs}`);
    },
    fetchJobMessagesDirect(job_id: string) {
      return request<Message[]>(config, `/orchestration/jobs/${job_id}/messages`);
    },
    updatePresence(payload: Record<string, unknown>) {
      return request<Record<string, unknown>>(config, "/orchestration/presence", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    sendText(chat_id: string, text: string, metadata: Record<string, unknown> = {}, file_ids: string[] = []) {
      return request<SendTextResponse>(config, "/input/text/", {
        method: "POST",
        body: JSON.stringify({ chat_id, text, metadata, file_ids }),
      });
    },
    async sendVoice(chat_id: string, file: Blob, language?: string, metadata: Record<string, unknown> = {}) {
      const formData = new FormData();
      formData.append("chat_id", chat_id);
      const mime = (file.type || "").toLowerCase();
      const extension = mime.includes("mp4") || mime.includes("m4a")
        ? "m4a"
        : mime.includes("ogg")
          ? "ogg"
          : mime.includes("wav")
            ? "wav"
            : mime.includes("mpeg") || mime.includes("mp3")
              ? "mp3"
              : "webm";
      formData.append("file", file, `voice.${extension}`);
      if (language) formData.append("language", language);
      formData.append("metadata", JSON.stringify(metadata));

      const token = await resolveToken(config.getToken);
      const res = await fetch(`${config.baseUrl}/input/voice/`, {
        method: "POST",
        body: formData,
        headers: token ? { "X-App-Token": token } : undefined,
      });

      if (!res.ok) {
        const text = await res.text();
        let message = text;
        try {
          const body = JSON.parse(text) as { message?: string; detail?: string };
          message = body.message || body.detail || text;
        } catch {
          // Keep a non-JSON response as-is.
        }
        const err: any = new Error(message || `Request failed with ${res.status}`);
        err.status = res.status;
        throw err;
      }

      return (await res.json()) as SendTextResponse;
    },
    fetchJobs(chat_id?: string) {
      const qs = chat_id ? `?chat_id=${encodeURIComponent(chat_id)}` : "";
      return request<Job[]>(config, `/orchestration/jobs${qs}`);
    },
    fetchJob(job_id: string) {
      return request<Job>(config, `/orchestration/jobs/${job_id}`);
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
        soft_planner_model: string;
        study_model: string;
        cache_mode: string;
        max_function_result_chars: number;
        call_voice: string;
        call_voice_options: string[];
        codex_auth_mode: "profile" | "api_key";
        codex_api_key_configured: boolean;
        codex_api_key_hint: string;
      }>(config, "/orchestration/settings");
    },
    updateSettings(payload: {
      frontman_model?: string;
      caller_model?: string;
      soft_planner_model?: string;
      study_model?: string;
      cache_mode?: string;
      max_function_result_chars?: number;
      call_voice?: string;
      codex_auth_mode?: "profile" | "api_key";
      codex_api_key?: string;
    }) {
      return request<{
        frontman_model: string;
        caller_model: string;
        soft_planner_model: string;
        study_model: string;
        cache_mode: string;
        max_function_result_chars: number;
        call_voice: string;
        call_voice_options: string[];
        codex_auth_mode: "profile" | "api_key";
        codex_api_key_configured: boolean;
        codex_api_key_hint: string;
      }>(config, "/orchestration/settings", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    previewCallVoice(voice: string) {
      return request<{ voice: string; content_type: string; audio_base64: string }>(
        config,
        `/orchestration/settings/call_voice_preview?voice=${encodeURIComponent(voice)}`,
      );
    },
    fetchCalendarCombined(params: { days?: number } = {}) {
      const qs = params.days ? `?days=${params.days}` : "";
      return request<CombinedCalendar>(config, `/orchestration/calendar/combined${qs}`);
    },
    fetchObjectiveRoots() {
      return request<Objective[]>(config, `/orchestration/objectives/roots`);
    },
    fetchObjectiveTree(objective_id: string) {
      return request<Objective>(config, `/orchestration/objectives/tree/${objective_id}`);
    },
    fetchObjective(objective_id: string) {
      return request<Objective>(config, `/orchestration/objectives/${objective_id}`);
    },
    fetchObjectiveTasks(params: { include_completed?: boolean; due_within_days?: number } = {}) {
      const query = new URLSearchParams();
      if (params.include_completed) query.set("include_completed", "true");
      if (params.due_within_days) query.set("due_within_days", String(params.due_within_days));
      const suffix = query.toString() ? `?${query.toString()}` : "";
      return request<ObjectiveTaskPicker[]>(config, `/orchestration/objective_tasks${suffix}`);
    },
    createObjective(payload: Record<string, unknown>) {
      return request<Objective>(config, `/orchestration/objectives`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    updateObjective(objective_id: string, payload: Record<string, unknown>) {
      return request<Objective>(config, `/orchestration/objectives/${objective_id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    },
    deleteObjective(objective_id: string) {
      return request<{ ok: boolean }>(config, `/orchestration/objectives/${objective_id}`, {
        method: "DELETE",
      });
    },
    createObjectiveTask(objective_id: string, payload: Record<string, unknown>) {
      return request<ObjectiveTask>(config, `/orchestration/objectives/${objective_id}/tasks`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    updateObjectiveTask(task_id: string, payload: Record<string, unknown>) {
      return request<ObjectiveTask>(config, `/orchestration/objective_tasks/${task_id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    },
    deleteObjectiveTask(task_id: string) {
      return request<{ ok: boolean }>(config, `/orchestration/objective_tasks/${task_id}`, {
        method: "DELETE",
      });
    },
    fetchObjectiveLogs(objective_id: string) {
      return request<ObjectiveLog[]>(config, `/orchestration/objectives/${objective_id}/logs`);
    },
    createObjectiveLog(objective_id: string, payload: Record<string, unknown>) {
      return request<ObjectiveLog>(config, `/orchestration/objectives/${objective_id}/logs`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    updateObjectiveLog(log_id: string, payload: Record<string, unknown>) {
      return request<ObjectiveLog>(config, `/orchestration/objective_logs/${log_id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    },
    deleteObjectiveLog(log_id: string) {
      return request<{ ok: boolean }>(config, `/orchestration/objective_logs/${log_id}`, {
        method: "DELETE",
      });
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
      payload: Partial<Pick<StudyTopic, "name" | "description" | "homework" | "order_index" | "estimated_effort_minutes" | "weight" | "status" | "passed" | "grade">>,
    ) {
      return request<StudyTopic>(config, `/study/topics/${topic_id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    },
    deleteStudyTopic(topic_id: string) {
      return request<{ ok: boolean }>(config, `/study/topics/${topic_id}`, { method: "DELETE" });
    },
    fetchTopicAudiobookVersions(topic_id: string) {
      return request<{ versions: StudyTopicAudiobookVersion[] }>(config, `/study/topics/${topic_id}/audiobooks`);
    },
    createTopicAudiobookVersion(payload: {
      topic_id: string;
      generation_notes?: string;
      voice?: string;
      model?: string;
    }) {
      const formData = new FormData();
      if (payload.generation_notes !== undefined) formData.append("generation_notes", payload.generation_notes);
      if (payload.voice) formData.append("voice", payload.voice);
      if (payload.model) formData.append("model", payload.model);
      return request<{ version: StudyTopicAudiobookVersion; job: Job }>(
        config,
        `/study/topics/${payload.topic_id}/audiobooks`,
        { method: "POST", body: formData },
      );
    },
    async previewTopicAudiobookVoice(payload: {
      topic_id: string;
      voice?: string;
      text?: string;
    }) {
      const formData = new FormData();
      if (payload.voice) formData.append("voice", payload.voice);
      if (payload.text) formData.append("text", payload.text);

      const token = await resolveToken(config.getToken);
      const res = await fetch(`${config.baseUrl}/study/topics/${payload.topic_id}/audiobooks/preview`, {
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
      return await res.blob();
    },
    getTopicAudiobookDownloadUrl(topic_id: string, version_id: string) {
      return `${config.baseUrl}/study/topics/${topic_id}/audiobooks/${version_id}/download`;
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
      return request<Job>(config, `/orchestration/calendar/replan${suffix}`, {
        method: "POST",
      });
    },
    createHardEventTaskLink(payload: {
      task_id: string;
      event: Record<string, unknown>;
      metadata?: Record<string, unknown>;
    }) {
      return request<HardEventTaskLink>(config, `/orchestration/calendar/hard_event_task_links`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    deleteHardEventTaskLink(link_id: string) {
      return request<{ ok: boolean }>(config, `/orchestration/calendar/hard_event_task_links/${link_id}`, {
        method: "DELETE",
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
    deleteSoftEvent(soft_event_id: string) {
      return request<{ deleted: number; canceled_slots: number }>(config, `/orchestration/soft_events/${soft_event_id}`, {
        method: "DELETE",
      });
    },
    promoteSoftSlot(slot_id: string) {
      return request<{ updated: number }>(config, `/orchestration/soft_slots/${slot_id}/promote`, {
        method: "POST",
      });
    },
    markSoftSlotOutcome(
      slot_id: string,
      payload: {
        outcome: string;
        reason?: string;
        minutes_spent?: number;
        completed_task_ids?: string[];
      },
    ) {
      return request<SoftSlotOutcomeResult>(config, `/orchestration/soft_slots/${slot_id}/outcome`, {
        method: "POST",
        body: JSON.stringify(payload),
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
    fetchCallSessions(options: { status?: string; platform?: "web" | "mobile" } = {}) {
      const params = new URLSearchParams();
      if (options.status) params.set("status", options.status);
      if (options.platform) params.set("platform", options.platform);
      const qs = params.toString() ? `?${params.toString()}` : "";
      return request<CallSession[]>(config, `/orchestration/call_sessions${qs}`);
    },
    createCallSession(payload: { goal: string; scheduled_for?: string; origin?: "web" | "mobile" | "corv" }) {
      const params = new URLSearchParams({ goal: payload.goal });
      if (payload.origin) params.set("origin", payload.origin);
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
    createRealtimeToken(session_id: string, manualTurnDetection = false) {
      const suffix = manualTurnDetection ? "?manual_turn_detection=true" : "";
      return request<any>(config, `/orchestration/call_sessions/${session_id}/realtime_token${suffix}`, {
        method: "POST",
      });
    },
    fetchCallDelegationState(session_id: string, after = "") {
      const params = after ? `?${new URLSearchParams({ after })}` : "";
      return request<{ waiting: boolean; active_count: number; delegations: any[]; updates: Array<{ id: string; content: string; created_at: string }>; cursor: string }>(config, `/orchestration/call_sessions/${session_id}/delegations${params}`);
    },
    runCallAction(session_id: string, instruction: string) {
      const params = new URLSearchParams({ instruction });
      return request<{ result: string }>(config, `/orchestration/call_sessions/${session_id}/action?${params}`, {
        method: "POST",
      });
    },
    fetchStudyAssignments(course_id?: string, status?: string) {
      const params = new URLSearchParams();
      if (course_id) params.set("course_id", course_id);
      if (status) params.set("status", status);
      const qs = params.toString() ? `?${params.toString()}` : "";
      return request<StudyAssignment[]>(config, `/study/assignments${qs}`);
    },
    getStudyAssignment(assignment_id: string) {
      return request<StudyAssignment>(config, `/study/assignments/${assignment_id}`);
    },
    getStudyAssignmentOriginalUrl(assignment_id: string) {
      return `${config.baseUrl}/study/assignments/${assignment_id}/original`;
    },
    createStudyAssignment(payload: {
      course_id: string;
      title: string;
      description?: string;
      due_at: string;
      material_text?: string;
      session_count?: number;
      file?: NativeUploadFile | File | Blob | null;
    }) {
      if (payload.file) {
        const formData = new FormData();
        formData.append("course_id", payload.course_id);
        formData.append("title", payload.title);
        formData.append("due_at", payload.due_at);
        if (payload.description) formData.append("description", payload.description);
        if (payload.material_text) formData.append("material_text", payload.material_text);
        if (payload.session_count !== undefined) {
          formData.append("session_count", String(payload.session_count));
        }
        if (isNativeUploadFile(payload.file)) {
          formData.append(
            "file",
            {
              uri: payload.file.uri,
              name: payload.file.name,
              type: payload.file.type || "application/octet-stream",
            } as any,
          );
        } else {
          const fileName = payload.file instanceof File ? payload.file.name : "assignment-material";
          formData.append("file", payload.file, fileName);
        }
        return request<StudyAssignment>(config, "/study/assignments", {
          method: "POST",
          body: formData,
        });
      }
      return request<StudyAssignment>(config, "/study/assignments", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    updateStudyAssignmentStatus(assignment_id: string, status: string) {
      const params = new URLSearchParams({ status });
      return request<StudyAssignment>(config, `/study/assignments/${assignment_id}?${params.toString()}`, {
        method: "PATCH",
      });
    },
    deleteStudyAssignment(assignment_id: string) {
      return request<{ ok: boolean }>(config, `/study/assignments/${assignment_id}`, {
        method: "DELETE",
      });
    },
    fetchSshMachines() {
      return request<{ machines: SshMachine[] }>(config, "/ssh/machines");
    },
    createSshMachine(payload: SshMachineInput) {
      return request<SshMachine>(config, "/ssh/machines", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    updateSshMachine(machine_id: string, payload: Partial<SshMachineInput> & { reset_host_key?: boolean }) {
      return request<SshMachine>(config, `/ssh/machines/${machine_id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    },
    deleteSshMachine(machine_id: string) {
      return request<{ ok: boolean }>(config, `/ssh/machines/${machine_id}`, {
        method: "DELETE",
      });
    },
    connectSshMachine(machine_id: string) {
      return request<SshMachine>(config, `/ssh/machines/${machine_id}/connect`, {
        method: "POST",
      });
    },
    disconnectSshMachine(machine_id: string) {
      return request<SshMachine>(config, `/ssh/machines/${machine_id}/disconnect`, {
        method: "POST",
      });
    },
    runSshCommand(machine_id: string, command: string, timeout_seconds?: number) {
      return request<SshCommandResult>(config, `/ssh/machines/${machine_id}/commands`, {
        method: "POST",
        body: JSON.stringify({ command, timeout_seconds }),
      });
    },
    fetchSshCommandHistory(machine_id: string, limit = 50) {
      return request<{ commands: SshCommandRecord[] }>(
        config,
        `/ssh/machines/${machine_id}/history?limit=${limit}`,
      );
    },
    fetchSshTerminalSessions(machine_id: string) {
      return request<{ sessions: SshTerminalSession[] }>(config, `/ssh/machines/${machine_id}/sessions`);
    },
    createSshTerminalSession(machine_id: string, name: string) {
      return request<SshTerminalSession>(config, `/ssh/machines/${machine_id}/sessions`, {
        method: "POST",
        body: JSON.stringify({ name }),
      });
    },
    closeSshTerminalSession(machine_id: string, session_id: string) {
      return request<{ id: string; closed: boolean }>(config, `/ssh/machines/${machine_id}/sessions/${session_id}`, {
        method: "DELETE",
      });
    },
    runSshTerminalCommand(machine_id: string, session_id: string, command: string, timeout_seconds?: number) {
      return request<SshCommandResult>(config, `/ssh/machines/${machine_id}/sessions/${session_id}/commands`, {
        method: "POST",
        body: JSON.stringify({ command, timeout_seconds }),
      });
    },
    fetchCodingStatus() {
      return request<CodingCliStatus>(config, "/coding/status");
    },
    fetchCodingDeviceAuth() {
      return request<CodingDeviceAuth>(config, "/coding/auth/device");
    },
    startCodingDeviceAuth() {
      return request<CodingDeviceAuth>(config, "/coding/auth/device", { method: "POST" });
    },
    cancelCodingDeviceAuth() {
      return request<CodingDeviceAuth>(config, "/coding/auth/device/cancel", { method: "POST" });
    },
    logoutCodingCodex() {
      return request<{ authenticated: boolean; message: string }>(config, "/coding/auth/logout", { method: "POST" });
    },
    fetchCodingSessions() {
      return request<{ sessions: CodingSession[] }>(config, "/coding/sessions");
    },
    fetchCodingSession(session_id: string) {
      return request<CodingSession>(config, `/coding/sessions/${session_id}`);
    },
    fetchCodingSessionLogs(session_id: string) {
      return request<CodingLiveLogs>(config, `/coding/sessions/${session_id}/logs`);
    },
    createCodingSession(payload: { name: string; machine_id: string; remote_working_directory: string }) {
      return request<CodingSession>(config, "/coding/sessions", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    deleteCodingSession(session_id: string) {
      return request<{ ok: boolean }>(config, `/coding/sessions/${session_id}`, { method: "DELETE" });
    },
    startCodingTask(session_id: string, prompt: string, file_ids: string[] = []) {
      return request<CodingTurn>(config, `/coding/sessions/${session_id}/tasks`, {
        method: "POST",
        body: JSON.stringify({ prompt, source: "ui", file_ids }),
      });
    },
    answerCodingDecision(session_id: string, prompt: string) {
      return request<CodingTurn>(config, `/coding/sessions/${session_id}/decisions`, {
        method: "POST",
        body: JSON.stringify({ prompt, source: "decision" }),
      });
    },
    startCodingTerminal(session_id: string) {
      return request<CodingTerminal>(config, `/coding/sessions/${session_id}/terminal/start`, { method: "POST" });
    },
    fetchCodingTerminal(session_id: string) {
      return request<CodingTerminal>(config, `/coding/sessions/${session_id}/terminal`);
    },
    sendCodingTerminalInput(session_id: string, payload: { text?: string; key?: "Enter" | "Up" | "Down" | "Left" | "Right" | "Tab" | "Escape" | "C-c" | "C-d" }) {
      return request<CodingTerminal>(config, `/coding/sessions/${session_id}/terminal/input`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    closeCodingTerminal(session_id: string) {
      return request<{ closed: boolean; session_id: string; thread_id?: string | null }>(
        config,
        `/coding/sessions/${session_id}/terminal/close`,
        { method: "POST" },
      );
    },
    stopCodingSession(session_id: string) {
      return request<CodingSession>(config, `/coding/sessions/${session_id}/stop`, { method: "POST" });
    },
    abortCodingDelegation(session_id: string) {
      return request<CodingSession>(config, `/coding/sessions/${session_id}/abort`, { method: "POST" });
    },
    resumeCodingSession(session_id: string) {
      return request<CodingSession>(config, `/coding/sessions/${session_id}/resume`, { method: "POST" });
    },
    fetchFeatureDelegations(session_id?: string) {
      const query = session_id ? `?session_id=${encodeURIComponent(session_id)}` : "";
      return request<{ delegations: FeatureDelegation[] }>(config, `/coding/delegations${query}`);
    },
    fetchFeatureDelegation(delegation_id: string) {
      return request<FeatureDelegation>(config, `/coding/delegations/${delegation_id}`);
    },
    createFeatureDelegation(session_id: string, payload: {
      title: string;
      description: string;
      acceptance_criteria: string[];
      qa_enabled: boolean;
      max_iterations?: number;
      file_ids?: string[];
    }) {
      return request<FeatureDelegation>(config, `/coding/sessions/${session_id}/delegations`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    resumeFeatureDelegation(
      delegation_id: string,
      decision = "",
      mode: "auto" | "qa" | "coding" = "auto",
    ) {
      return request<FeatureDelegation>(config, `/coding/delegations/${delegation_id}/resume`, {
        method: "POST",
        body: JSON.stringify({ decision, mode }),
      });
    },
    stopFeatureDelegation(delegation_id: string) {
      return request<FeatureDelegation>(config, `/coding/delegations/${delegation_id}/stop`, {
        method: "POST",
      });
    },
    fetchFeatureQaEvidence(qa_run_id: string, evidence_index: number) {
      return requestBlob(config, `/coding/qa-runs/${qa_run_id}/evidence/${evidence_index}`);
    },
    fetchWorkoutExercises(query = "") {
      return request<{ exercises: WorkoutExercise[] }>(config, `/workout/exercises${query ? `?query=${encodeURIComponent(query)}` : ""}`);
    },
    createWorkoutExercise(payload: Partial<WorkoutExercise> & { name: string }) {
      return request<WorkoutExercise & { created: boolean }>(config, "/workout/exercises", { method: "POST", body: JSON.stringify(payload) });
    },
    deleteWorkoutExercise(exerciseId:string, force=false) { return request<{deleted:boolean;exercise:WorkoutExercise;deleted_plan_entries:number;deleted_log_entries:number}>(config, `/workout/exercises/${exerciseId}?force=${force}`, {method:"DELETE"}); },
    fetchWorkoutPlans() { return request<{ plans: WorkoutPlan[] }>(config, "/workout/plans"); },
    createWorkoutPlan(payload: { title:string; description?:string; goal?:string; source?:"manual"|"import"|"corv"; schedule?:Record<string,unknown>; exercises:WorkoutExerciseSpec[]; metadata?:Record<string,unknown> }) {
      return request<WorkoutPlan>(config, "/workout/plans", { method: "POST", body: JSON.stringify(payload) });
    },
    deleteWorkoutPlan(planId:string) { return request<{deleted:boolean;plan:WorkoutPlan;preserved_sessions:number}>(config, `/workout/plans/${planId}`, {method:"DELETE"}); },
    fetchWorkoutSessions(params: { start_date?:string; end_date?:string; exercise?:string; limit?:number } = {}) {
      const query = new URLSearchParams(Object.entries(params).filter(([,value]) => value !== undefined && value !== "").map(([key,value]) => [key,String(value)]));
      return request<{ sessions: WorkoutSession[] }>(config, `/workout/sessions${query.size ? `?${query}` : ""}`);
    },
    createWorkoutSession(payload: { title?:string; plan?:string; started_at?:string; ended_at?:string; notes?:string; exercises:WorkoutExerciseSpec[]; metadata?:Record<string,unknown> }) {
      return request<WorkoutSession>(config, "/workout/sessions", { method: "POST", body: JSON.stringify(payload) });
    },
    deleteWorkoutSession(sessionId:string) { return request<{ deleted:boolean; session:WorkoutSession }>(config, `/workout/sessions/${sessionId}`, { method:"DELETE" }); },
    fetchActiveWorkoutSessions() { return request<{ sessions:WorkoutSession[] }>(config, "/workout/sessions/active"); },
    startWorkoutSession(payload: { title?:string; plan?:string; started_at?:string; notes?:string; exercises?:WorkoutExerciseSpec[]; metadata?:Record<string,unknown> }) { return request<WorkoutSession>(config, "/workout/sessions/start", { method:"POST", body:JSON.stringify(payload) }); },
    updateWorkoutSessionItem(logId:string, payload: { completed?:boolean; sets?:number; reps?:number; weight_kg?:number; duration_seconds?:number; distance_km?:number; rpe?:number; notes?:string; metadata?:Record<string,unknown> }) { return request<WorkoutExerciseLog>(config, `/workout/sessions/items/${logId}`, { method:"PATCH", body:JSON.stringify(payload) }); },
    finishWorkoutSession(sessionId:string, payload: { ended_at?:string; notes?:string } = {}) { return request<WorkoutSession>(config, `/workout/sessions/${sessionId}/finish`, { method:"POST", body:JSON.stringify(payload) }); },
    fetchWorkoutGoals() { return request<{ goals: WorkoutGoal[] }>(config, "/workout/goals"); },
    createWorkoutGoal(payload: { title:string; metric:string; target_value:number; unit?:string; exercise?:string; start_date?:string; end_date?:string; active?:boolean; metadata?:Record<string,unknown> }) {
      return request<WorkoutGoal>(config, "/workout/goals", { method: "POST", body: JSON.stringify(payload) });
    },
    updateWorkoutGoal(goal_id:string, active:boolean) { return request<WorkoutGoal>(config, `/workout/goals/${goal_id}?active=${active}`, { method:"PATCH" }); },
    fetchWorkoutDashboard(days=90, exercise="") { return request<WorkoutDashboard>(config, `/workout/dashboard?days=${days}${exercise ? `&exercise=${encodeURIComponent(exercise)}` : ""}`); },
  };
}
