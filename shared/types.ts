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
  created_at?: string | null;
  updated_at?: string | null;
  cancel_requested?: boolean | null;
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
  cache_mode?: string;
  max_function_result_chars?: number;
};

export type HardCalendarEvent = {
  id: string;
  title: string;
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
  duration_minutes: number;
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
