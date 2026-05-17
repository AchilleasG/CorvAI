export type ChatListItem = {
  chat_id: string;
  chat_nickname?: string | null;
  last_activity_at?: string | null;
  archived?: boolean;
};

export type Message = {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  text: string;
  created_at?: string | null;
  message_type?: "user_visible" | "tool_only" | "system_note" | "error";
  audience?: "user" | "ai_stack";
  trace_id?: string | null;
  call_id?: string | null;
  job_id?: string | null;
};

export type SendTextResponse = {
  success: boolean;
  message: string;
  chat_id: string;
};

export type Job = {
  id: string;
  status: string;
  user_visible_summary: string;
  progress: number;
  module_slug?: string | null;
  active_function?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
  cancel_requested?: boolean | null;
  error_summary?: string | null;
};

export type JobEvent = {
  id: string;
  role: string;
  event_type: string;
  visibility: string;
  message: string;
  payload?: Record<string, unknown>;
  call_id?: string | null;
  created_at?: string | null;
};

export type UsageEvent = {
  id: string;
  created_at: string;
  source: string;
  model: string;
  cache_mode: string;
  prompt_tokens: number;
  cached_prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
};

export type UsageSummary = {
  since: string;
  by_source: Record<
    string,
    {
      source: string;
      prompt_tokens: number | null;
      cached_prompt_tokens: number | null;
      completion_tokens: number | null;
      total_tokens: number | null;
    }
  >;
  totals: {
    prompt_tokens: number | null;
    cached_prompt_tokens: number | null;
    completion_tokens: number | null;
    total_tokens: number | null;
  };
};

export type SettingsPayload = {
  frontman_model?: string;
  caller_model?: string;
  study_model?: string;
  cache_mode?: string;
  max_function_result_chars?: number;
};

export type StudyCourse = {
  id: string;
  title: string;
  code: string;
  description: string;
  term_start_date?: string | null;
  term_end_date?: string | null;
  status: "active" | "completed" | "archived";
  chat_id?: string | null;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
};

export type StudyMaterial = {
  id: string;
  course_id: string;
  topic_id?: string | null;
  exam_id?: string | null;
  kind: string;
  title: string;
  source_url: string;
  uploaded_file_url?: string | null;
  uploaded_file_name?: string | null;
  file_path: string;
  raw_text: string;
  parsed_text: string;
  ingestion_status: "pending" | "processing" | "processed" | "failed";
  page_count: number;
  converted_markdown: string;
  solved_markdown: string;
  theory_markdown: string;
  extracted_data?: Record<string, unknown>;
  processed_at?: string | null;
  processing_error: string;
  notes: string;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
};

export type StudyMaterialProcessResponse = {
  material: StudyMaterial;
  job?: Job | null;
};

export type StudyExam = {
  id: string;
  course_id: string;
  course_title?: string | null;
  title: string;
  kind: string;
  scheduled_at?: string | null;
  weight: number;
  notes: string;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
};

export type StudyTopic = {
  id: string;
  course_id: string;
  name: string;
  description: string;
  summary: string;
  order_index: number;
  estimated_effort_minutes: number;
  weight: number;
  status: string;
  passed: boolean;
  passed_at?: string | null;
  grade?: number | null;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
};

export type HardCalendarEvent = {
  id: string;
  title: string;
  description?: string;
  start: string;
  end: string;
  all_day?: boolean;
  source: "hard";
};

export type SoftSlot = {
  id: string;
  soft_event_id: string;
  title: string;
  start: string;
  end: string;
  status: string;
  rationale?: string;
  deferral_count: number;
  promoted: boolean;
  soft_deadline?: string | null;
  hard_deadline?: string | null;
};

export type SoftEventUnscheduled = {
  id: string;
  title: string;
  notes?: string;
  priority: number;
  soft_deadline?: string | null;
  hard_deadline?: string | null;
};

export type SoftEventDetail = {
  id: string;
  title: string;
  description: string;
  notes: string;
  preferred_duration_minutes: number;
  min_duration_minutes: number;
  soft_deadline?: string | null;
  hard_deadline?: string | null;
  frequency: string;
  deferral_limit: number;
  priority: number;
  status: "active" | "paused" | "archived";
};

export type CalendarReplanResult = {
  actions: number;
  created: number;
  updated: number;
  trace_id: string;
};

export type CombinedCalendar = {
  window_start: string;
  window_end: string;
  hard_events: HardCalendarEvent[];
  soft_slots: SoftSlot[];
  soft_events_unscheduled: SoftEventUnscheduled[];
};

export type ScheduledTask = {
  id: string;
  prompt: string;
  recurrence: "once" | "daily" | "weekly" | "monthly";
  start_at?: string | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
  status: "active" | "paused" | "completed";
  is_running: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ScheduledTaskLogEntry = {
  id: string;
  role: string;
  level: string;
  message: string;
  created_at?: string | null;
};

export type ScheduledTaskRun = {
  id: string;
  status: "running" | "completed" | "failed";
  started_at?: string | null;
  finished_at?: string | null;
  summary: string;
  error_summary: string;
  log_entries: ScheduledTaskLogEntry[];
};

export type UserMessage = {
  id: string;
  title: string;
  body: string;
  kind: "info" | "call_missed" | "call_text";
  read_at?: string | null;
  created_at?: string | null;
};

export type CallTranscriptEntry = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string | null;
  end_call?: boolean | null;
};

export type CallSession = {
  id: string;
  goal: string;
  status: "scheduled" | "ringing" | "in_call" | "missed" | "completed" | "canceled";
  scheduled_for?: string | null;
  ringing_started_at?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  summary: string;
  created_at?: string | null;
  updated_at?: string | null;
};
