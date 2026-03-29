import type { RequestStatus } from "../lib/types";
import { getStatusLabel } from "../lib/requestStatus";

export function StatusBadge({ status }: { status: RequestStatus }) {
  return <span className={`status-badge status-${status}`}>{getStatusLabel(status)}</span>;
}
