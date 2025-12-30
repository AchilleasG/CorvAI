import { ChatListItem, Message, SendTextResponse, Job } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    ...init,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed with ${res.status}`);
  }

  // Some endpoints may return empty; guard accordingly
  if (res.status === 204) {
    // @ts-expect-error allow void
    return undefined;
  }

  return (await res.json()) as T;
}

export function fetchChats() {
  return request<ChatListItem[]>("/chats/");
}

export function createChat(chat_nickname?: string | null) {
  return request<{ chat_id: string }>("/chats/", {
    method: "POST",
    body: JSON.stringify({ chat_nickname }),
  });
}

type UpdateChatPayload = {
  nickname?: string | null;
  archived?: boolean;
};

export function renameChat(chat_id: string, payload: UpdateChatPayload) {
  return request<{ chat_id: string; chat_nickname?: string | null; archived?: boolean }>(
    `/chats/${chat_id}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function deleteChat(chat_id: string) {
  return request(`/chats/${chat_id}`, {
    method: "DELETE",
  });
}

export function fetchMessages(chat_id: string, visible_only: boolean = true) {
  const suffix = visible_only ? "?visible_only=true" : "";
  return request<Message[]>(`/chats/${chat_id}/messages${suffix}`);
}

export function fetchJobMessages(chat_id: string, job_id: string) {
  const qs = `?visible_only=false&job_id=${encodeURIComponent(job_id)}`;
  return request<Message[]>(`/chats/${chat_id}/messages${qs}`);
}

export function fetchJobMessagesDirect(job_id: string) {
  return request<Message[]>(`/orchestration/jobs/${job_id}/messages`);
}

export function sendText(chat_id: string, text: string) {
  return request<SendTextResponse>("/input/text/", {
    method: "POST",
    body: JSON.stringify({ chat_id, text }),
  });
}

export async function sendVoice(chat_id: string, file: Blob) {
  const formData = new FormData();
  formData.append("chat_id", chat_id);
  formData.append("file", file, "voice.webm");

  const res = await fetch(`${API_BASE}/input/voice/`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed with ${res.status}`);
  }

  return (await res.json()) as SendTextResponse;
}

export function fetchJobs(chat_id?: string) {
  const qs = chat_id ? `?chat_id=${encodeURIComponent(chat_id)}` : "";
  return request<Job[]>(`/orchestration/jobs${qs}`);
}

export function cancelJob(job_id: string) {
  return request<Job>(`/orchestration/jobs/${job_id}/cancel`, {
    method: "POST",
  });
}
