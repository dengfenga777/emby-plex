import type { RequestStatus } from "../lib/types";

const LABELS: Record<RequestStatus, string> = {
  pending: "待处理",
  approved: "已批准",
  rejected: "已拒绝",
  submitted_to_moviepilot: "已提交",
  downloading: "下载中",
  organizing: "整理中",
  finished: "已完成",
  failed: "失败",
};

export function StatusBadge({ status }: { status: RequestStatus }) {
  return <span className={`status-badge status-${status}`}>{LABELS[status]}</span>;
}

