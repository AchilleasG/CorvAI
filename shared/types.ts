export type UserNote = {
  id: string;
  content: string;
  source: string;
  tags: string[];
  created_at?: string | null;
  updated_at?: string | null;
  expires_at?: string | null;
  is_timed?: boolean;
};

export type KnowledgeEntityType = "location" | "person";
export type KnowledgeEntity = {
  id: string;
  knowledge_type: KnowledgeEntityType;
  name: string;
  description: string;
  data: Record<string, unknown> & { latitude?: number; longitude?: number; relationship?: string; facts?: string[] };
  source: string;
  tags: string[];
  created_at?: string | null;
  updated_at?: string | null;
  distance?: number;
};
export type KnowledgeSearchResult = KnowledgeEntity | (UserNote & { knowledge_type: "note"; distance?: number });
export type LocationSearchResult = { display_name:string; name:string; latitude:number; longitude:number; category:string; place_type:string; importance:number };

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
  metadata?: {
    attachments?: ManagedFile[];
    sources?: MessageSource[];
    [key: string]: unknown;
  };
};

export type MessageSource = { title: string; url: string; site_name?: string };

export type ManagedFile = {
  id: string; filename: string; content_type: string; size: number; checksum_sha256: string;
  metadata: Record<string, unknown>; tags: string[]; session_id?: string | null;
  turn_id?: string | null; delegation_id?: string | null; assistant_message_id?: string | null; download_url: string;
  created_at: string; updated_at: string;
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
  soft_planner_model?: string;
  study_model?: string;
  cache_mode?: string;
  max_function_result_chars?: number;
  call_voice?: string;
  call_voice_options?: string[];
  codex_auth_mode?: "profile" | "api_key";
  codex_api_key?: string;
  codex_api_key_configured?: boolean;
  codex_api_key_hint?: string;
};

export type StudyCourse = {
  id: string;
  objective_id?: string | null;
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
  objective_id?: string | null;
  name: string;
  description: string;
  summary: string;
  homework?: Array<Record<string, unknown>>;
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

export type StudyTopicAudiobookVersion = {
  id: string;
  topic_id: string;
  version_number: number;
  status: "pending" | "processing" | "ready" | "failed";
  job_id?: string | null;
  generation_notes: string;
  script_markdown: string;
  audio_url?: string | null;
  audio_file_name?: string | null;
  audio_mime_type: string;
  tts_voice: string;
  tts_model: string;
  processing_error: string;
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
  location?: string;
  source: "hard";
  task_links?: HardEventTaskLink[];
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
  metadata?: Record<string, unknown>;
};

export type SoftSlotOutcomeResult = {
  slot_id: string;
  soft_event_id: string;
  status: string;
  linked_task_ids: string[];
  completed_task_ids: string[];
};

export type CalendarReplanResult = {
  actions: number;
  created: number;
  updated: number;
  trace_id: string;
  planner_summary?: string;
  model_calls?: number;
  objective_sync?: {
    purged_soft_events?: number;
    canceled_slots?: number;
    scanned_objectives: number;
    relevant_objectives: number;
    planned_soft_events: number;
    archived_soft_events: number;
  };
  coverage?: ObjectiveCoverageSnapshot;
};

export type CombinedCalendar = {
  window_start: string;
  window_end: string;
  hard_events: HardCalendarEvent[];
  soft_slots: SoftSlot[];
  soft_events_unscheduled: SoftEventUnscheduled[];
  objective_coverage?: ObjectiveCoverageSnapshot;
};

export type ObjectiveTask = {
  id: string;
  objective_id: string;
  title: string;
  description: string;
  status: string;
  estimated_effort_minutes?: number | null;
  remaining_effort_minutes?: number | null;
  due_at?: string | null;
  sort_order: number;
  metadata?: Record<string, unknown>;
  completed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ObjectiveTaskPicker = {
  id: string;
  objective_id: string;
  objective_title: string;
  title: string;
  status: string;
  due_at?: string | null;
  remaining_effort_minutes?: number | null;
  estimated_effort_minutes?: number | null;
};

export type HardEventTaskLink = {
  id: string;
  task_id: string;
  objective_id: string;
  objective_title: string;
  task_title: string;
  due_at?: string | null;
  event_id: string;
  event_title: string;
  event_start_raw: string;
  event_end_raw: string;
};

export type ObjectiveLog = {
  id: string;
  objective_id: string;
  task_id?: string | null;
  kind: string;
  text: string;
  minutes_spent?: number | null;
  logged_at?: string | null;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
};

export type Objective = {
  id: string;
  parent_id?: string | null;
  title: string;
  description: string;
  status: string;
  deadline_at?: string | null;
  estimated_effort_minutes?: number | null;
  remaining_effort_minutes?: number | null;
  priority: number;
  notes: string;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
  tasks: ObjectiveTask[];
  logs: ObjectiveLog[];
  children: Objective[];
};

export type ObjectiveCoverageItem = {
  task_id: string;
  objective_id: string;
  objective_title: string;
  task_title: string;
  due_at?: string | null;
  required_minutes?: number | null;
  scheduled_minutes: number;
  missing_minutes?: number | null;
  coverage_state: "covered" | "partial" | "uncovered";
  slot_ids: string[];
  hard_event_refs?: Array<{
    event_id: string;
    title: string;
    start?: string | null;
    end?: string | null;
  }>;
};

export type ObjectiveCoverageSnapshot = {
  summary: {
    total: number;
    covered: number;
    partial: number;
    uncovered: number;
  };
  items: ObjectiveCoverageItem[];
};

export type ScheduledTask = {
  id: string;
  prompt: string;
  recurrence: "once" | "daily" | "weekly" | "monthly";
  start_at?: string | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
  status: "active" | "paused" | "completed" | "failed" | "canceled";
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

export type StudyAssignmentChecklistItem = {
  step_number: number;
  title: string;
  description: string;
};

export type StudyAssignment = {
  id: string;
  course_id: string;
  objective_id: string;
  title: string;
  description: string;
  due_at: string;
  material_text?: string | null;
  plan?: string | null;
  checklist: StudyAssignmentChecklistItem[];
  session_count: number;
  soft_event_refs: string[];
  has_uploaded_file?: boolean;
  uploaded_file_name?: string | null;
  status: "draft" | "processing" | "ready" | "in_progress" | "submitted" | "graded";
  created_at?: string | null;
  updated_at?: string | null;
};

export type SshMachine = {
  id: string;
  name: string;
  host: string;
  port: number;
  username: string;
  auth_type: "password" | "private_key" | "agent";
  has_credentials: boolean;
  allow_ai_commands: boolean;
  is_default: boolean;
  connect_timeout_seconds: number;
  command_timeout_seconds: number;
  keepalive_seconds: number;
  notes: string;
  host_key_fingerprint?: string | null;
  connected: boolean;
  connected_for_seconds?: number | null;
  last_connected_at?: string | null;
  last_error: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type SshMachineInput = {
  name: string;
  host: string;
  port?: number;
  username: string;
  auth_type?: "password" | "private_key" | "agent";
  password?: string;
  private_key?: string;
  passphrase?: string;
  allow_ai_commands?: boolean;
  is_default?: boolean;
  connect_timeout_seconds?: number;
  command_timeout_seconds?: number;
  keepalive_seconds?: number;
  notes?: string;
};

export type SshCommandResult = {
  machine_id: string;
  machine_name: string;
  terminal_session_id?: string;
  terminal_session_name?: string;
  cwd?: string;
  command: string;
  stdout: string;
  stderr: string;
  exit_status: number;
  duration_ms: number;
  truncated: boolean;
  connected: boolean;
};

export type SshTerminalSession = {
  id: string;
  name: string;
  connected: boolean;
  cwd?: string | null;
  created_at: number;
  last_used_at: number;
};

export type SshCommandRecord = {
  id: string;
  command: string;
  source: "api" | "assistant";
  exit_status?: number | null;
  duration_ms: number;
  succeeded: boolean;
  error_summary: string;
  created_at: string;
};

export type CodexUsageWindow = {
  used_percent: number;
  remaining_percent: number;
  resets_at?: number | null;
  window_minutes?: number | null;
};

export type CodexProfileUsage = {
  available: boolean;
  reason?: string;
  plan_type?: string | null;
  limit_name?: string | null;
  primary?: CodexUsageWindow | null;
  secondary?: CodexUsageWindow | null;
  credits?: { has_credits: boolean; unlimited: boolean; balance?: string | null } | null;
};

export type CodingCliStatus = {
  installed: boolean;
  authenticated: boolean;
  version: string;
  auth_message: string;
  auth_mode: "profile" | "api_key";
  usage?: CodexProfileUsage | null;
  tmux_available: boolean;
  ssh_available: boolean;
  password_ssh_available: boolean;
  browser_qa_available: boolean;
};

export type CodingDeviceAuth = {
  active: boolean;
  id?: string | null;
  status: "idle" | "starting" | "waiting" | "succeeded" | "failed" | "cancelled" | "expired";
  verification_url: string;
  user_code: string;
  message: string;
  created_at?: string | null;
  expires_at?: string | null;
};

export type CodingTurn = {
  id: string;
  source: "corv" | "ui" | "decision" | "feature";
  prompt: string;
  status: "queued" | "running" | "completed" | "needs_input" | "failed" | "cancelled";
  codex_thread_id?: string | null;
  summary: string;
  question: string;
  options: string[];
  error: string;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
};

export type CodingSession = {
  id: string;
  name: string;
  machine_id: string;
  machine_name: string;
  machine_target: string;
  remote_working_directory: string;
  status: "ready" | "running" | "needs_input" | "direct" | "failed" | "stopped";
  permission_mode: "danger-full-access";
  codex_thread_id?: string | null;
  direct_terminal_running: boolean;
  last_summary: string;
  pending_question: string;
  pending_options: string[];
  last_error: string;
  turns: CodingTurn[];
  created_at: string;
  updated_at: string;
  stopped_at?: string | null;
};

export type CodingTerminal = {
  running: boolean;
  output: string;
  thread_id?: string | null;
};

export type CodingLiveLogs = {
  session_id: string;
  active: boolean;
  content: string;
  updated_at: string;
};

export type FeatureQaRun = {
  id: string;
  iteration: number;
  status: "running" | "passed" | "failed" | "blocked" | "error";
  summary: string;
  failures: string[];
  evidence: string[];
  question: string;
  options: string[];
  error: string;
  started_at: string;
  completed_at?: string | null;
};

export type FeatureDelegation = {
  id: string;
  session_id: string;
  session_name: string;
  machine_name: string;
  title: string;
  description: string;
  acceptance_criteria: string[];
  qa_enabled: boolean;
  max_iterations: number;
  current_iteration: number;
  status: "queued" | "coding" | "qa" | "fixing" | "needs_input" | "completed" | "failed" | "stopped";
  implementation_summary: string;
  qa_summary: string;
  pending_question: string;
  pending_options: string[];
  last_error: string;
  can_retry_qa: boolean;
  artifact_upload_url: string;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  stopped_at?: string | null;
  coding_turns: CodingTurn[];
  qa_runs: FeatureQaRun[];
};


export type WorkoutExercise = { id:string; name:string; aliases:string[]; category:string; muscle_group:string; equipment:string; instructions:string; metadata:Record<string,unknown> };
export type WorkoutExerciseSpec = { name:string; sets?:number|null; reps?:number|string|null; weight_kg?:number|null; duration_seconds?:number|null; distance_km?:number|null; rest_seconds?:number|null; rpe?:number|null; notes?:string; category?:string; muscle_group?:string; equipment?:string; metadata?:Record<string,unknown> };
export type WorkoutPlanExercise = { id:string; exercise:WorkoutExercise; order_index:number; sets?:number|null; reps:string; weight_kg?:number|null; duration_seconds?:number|null; distance_km?:number|null; rest_seconds?:number|null; notes:string; metadata:Record<string,unknown> };
export type WorkoutPlan = { id:string; title:string; description:string; goal:string; source:"manual"|"import"|"corv"; schedule:Record<string,unknown>; active:boolean; metadata:Record<string,unknown>; created_at:string; updated_at:string; exercises:WorkoutPlanExercise[]; created_exercises?:string[] };
export type WorkoutExerciseLog = { id:string; exercise:WorkoutExercise; order_index:number; sets?:number|null; reps?:number|null; weight_kg?:number|null; duration_seconds?:number|null; distance_km?:number|null; rpe?:number|null; notes:string; metadata:Record<string,unknown>; completed:boolean; completed_at?:string|null };
export type WorkoutSession = { id:string; plan_id?:string|null; plan_title?:string|null; title:string; status:"active"|"completed"; started_at:string; ended_at?:string|null; duration_seconds:number; notes:string; metadata:Record<string,unknown>; exercises:WorkoutExerciseLog[]; created_exercises?:string[] };
export type WorkoutGoal = { id:string; title:string; metric:"sessions_per_week"|"minutes_per_week"|"exercise_weight_kg"; target_value:number; unit:string; exercise_id?:string|null; exercise_name?:string|null; start_date?:string|null; end_date?:string|null; active:boolean; metadata:Record<string,unknown>; current_value:number; progress_percent:number };
export type WorkoutDashboard = { days:number; session_count:number; current_streak_days:number; trained_days:number; current_week_sessions:number; daily:Array<{date:string;sessions:number;duration_minutes:number;volume_kg:number}>; weekly:Array<{week_start:string;sessions:number}>; exercise_trend:Array<{date:string;exercise:string;weight_kg?:number|null;volume_kg:number;reps?:number|null;sets?:number|null}>; goals:WorkoutGoal[] };
