import type {
  AdminRequestSummary,
  AdminResourceCandidate,
  RequestDetail,
  RequestSummary,
  SearchResult,
  SessionResponse,
  TelegramProfile,
  User,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

async function apiRequest<T>(path: string, init?: RequestInit, token?: string): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = payload.detail ?? detail;
    } catch {
      detail = response.statusText;
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

export function authenticateWithTelegram(initData: string) {
  return apiRequest<SessionResponse>("/auth/telegram", {
    method: "POST",
    body: JSON.stringify({ init_data: initData }),
  });
}

export function authenticateWithDevProfile(profile: TelegramProfile) {
  return apiRequest<SessionResponse>("/auth/telegram", {
    method: "POST",
    body: JSON.stringify({ profile }),
  });
}

export function getMe(token: string) {
  return apiRequest<User>("/auth/me", undefined, token);
}

export async function searchMedia(token: string, query: string) {
  const params = new URLSearchParams({ q: query });
  return apiRequest<{ items: SearchResult[] }>(`/search?${params.toString()}`, undefined, token);
}

export function createRequest(token: string, item: SearchResult) {
  return apiRequest<RequestDetail>(
    "/requests",
    {
      method: "POST",
      body: JSON.stringify(item),
    },
    token,
  );
}

export function listMyRequests(token: string) {
  return apiRequest<RequestSummary[]>("/my/requests", undefined, token);
}

export function getRequest(token: string, requestId: string) {
  return apiRequest<RequestDetail>(`/requests/${requestId}`, undefined, token);
}

export function listPendingRequests(token: string) {
  return apiRequest<AdminRequestSummary[]>("/admin/requests?status=pending", undefined, token);
}

export function searchAdminResources(token: string, requestId: string) {
  return apiRequest<AdminResourceCandidate[]>(`/admin/requests/${requestId}/resources`, undefined, token);
}

export function approveRequest(token: string, requestId: string, note?: string) {
  return apiRequest<RequestDetail>(
    `/admin/requests/${requestId}/approve`,
    {
      method: "POST",
      body: JSON.stringify({ note }),
    },
    token,
  );
}

export function subscribeRequest(token: string, requestId: string, note?: string) {
  return apiRequest<RequestDetail>(
    `/admin/requests/${requestId}/subscribe`,
    {
      method: "POST",
      body: JSON.stringify({ note }),
    },
    token,
  );
}

export function directDownloadRequest(
  token: string,
  requestId: string,
  candidate: AdminResourceCandidate,
  note?: string,
) {
  return apiRequest<RequestDetail>(
    `/admin/requests/${requestId}/download`,
    {
      method: "POST",
      body: JSON.stringify({
        note,
        media_payload: candidate.media_payload,
        torrent_payload: candidate.torrent_payload,
      }),
    },
    token,
  );
}

export function rejectRequest(token: string, requestId: string, note?: string) {
  return apiRequest<RequestDetail>(
    `/admin/requests/${requestId}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ note }),
    },
    token,
  );
}
