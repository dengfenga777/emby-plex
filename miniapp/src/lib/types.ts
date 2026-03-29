export type UserRole = "user" | "admin";
export type MediaType = "movie" | "series" | "anime";
export type RequestStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "submitted_to_moviepilot"
  | "downloading"
  | "organizing"
  | "finished"
  | "failed";

export interface TelegramProfile {
  id: number;
  username?: string;
  first_name?: string;
  last_name?: string;
}

export interface User {
  id: number;
  tg_user_id: number;
  username: string | null;
  nickname: string;
  role: UserRole;
  created_at: string;
}

export interface SessionResponse {
  token: string;
  auth_mode: string;
  user: User;
}

export interface SearchResult {
  source_id: string;
  source: string;
  title: string;
  media_type: MediaType;
  year: number | null;
  overview: string | null;
  poster_url: string | null;
}

export interface RequestLog {
  id: number;
  from_status: RequestStatus | null;
  to_status: RequestStatus;
  operator: string;
  note: string | null;
  created_at: string;
}

export interface RequestSummary {
  id: string;
  public_id: number;
  title: string;
  media_type: MediaType;
  source: string;
  source_id: string;
  overview: string | null;
  poster_url: string | null;
  year: number | null;
  status: RequestStatus;
  moviepilot_task_id: string | null;
  admin_note: string | null;
  created_at: string;
  updated_at: string;
  request_reused: boolean;
}

export interface RequestDetail extends RequestSummary {
  user: User;
  logs: RequestLog[];
}

export interface AdminRequestSummary extends RequestSummary {
  user: User;
}

export interface AdminResourceCandidate {
  title: string;
  subtitle: string | null;
  description: string | null;
  site_name: string | null;
  size: number | null;
  seeders: number | null;
  peers: number | null;
  grabs: number | null;
  pubdate: string | null;
  page_url: string | null;
  resource_type: string | null;
  resource_pix: string | null;
  resource_effect: string | null;
  video_encode: string | null;
  audio_encode: string | null;
  season_episode: string | null;
  volume_factor: string | null;
  download_volume_factor: number | null;
  upload_volume_factor: number | null;
  hit_and_run: boolean | null;
  recommendation: string | null;
  score: number;
  labels: string[];
  media_payload: Record<string, unknown>;
  torrent_payload: Record<string, unknown>;
}

export interface AdminBatchSkippedItem {
  request_id: string;
  detail: string;
}

export interface AdminBatchActionResult {
  processed_count: number;
  skipped_count: number;
  processed_ids: string[];
  skipped: AdminBatchSkippedItem[];
  items: RequestDetail[];
}

export interface ApiErrorPayload {
  detail?: string;
}
