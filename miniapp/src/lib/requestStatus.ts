import type { RequestStatus } from "./types";

export const STATUS_LABELS: Record<RequestStatus, string> = {
  pending: "待处理",
  approved: "已批准",
  rejected: "已拒绝",
  submitted_to_moviepilot: "已提交",
  downloading: "下载中",
  organizing: "整理中",
  finished: "已完成",
  failed: "失败",
};

export const ACTIVE_REQUEST_STATUSES: RequestStatus[] = [
  "pending",
  "approved",
  "submitted_to_moviepilot",
  "downloading",
  "organizing",
];

export function getStatusLabel(status: RequestStatus) {
  return STATUS_LABELS[status];
}
