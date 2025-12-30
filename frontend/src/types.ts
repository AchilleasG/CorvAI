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
