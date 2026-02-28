// src/types.ts
export interface ChatMessage {
  id: number;
  room_id: string;
  sender: string;
  content: string;
  message_type: "message" | "system";
  created_at: string;
  metadata: string | null;
}

export interface ChatroomInfo {
  id: string;
  name: string;
  project: string;
  branch: string | null;
  description: string | null;
  status: "live" | "archived";
  created_at: string;
  archived_at: string | null;
  metadata: string | null;
  messageCount?: number;
  lastMessage?: string;
  lastMessageTs?: string;
  roleCounts?: Record<string, number>;
  unreadCount?: number;
}

export interface ChatroomsResponse {
  active: ChatroomInfo[];
  archived: ChatroomInfo[];
}

export interface SearchResult {
  rooms: ChatroomInfo[];
  message_rooms: Array<{ room_id: string; match_count: number }>;
}
