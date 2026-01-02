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
