import { StatusBadge } from "./StatusBadge";
import type { AdminRequestSummary, RequestSummary } from "../lib/types";

interface RequestsPanelProps {
  requests: RequestSummary[];
  adminQueue: AdminRequestSummary[];
  selectedRequestId: string | null;
  isAdmin: boolean;
  onSelect: (requestId: string) => void;
  onOpenAdmin: (requestId: string) => void;
  onReject: (requestId: string) => Promise<void>;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function RequestsPanel({
  requests,
  adminQueue,
  selectedRequestId,
  isAdmin,
  onSelect,
  onOpenAdmin,
  onReject,
}: RequestsPanelProps) {
  return (
    <section className="panel request-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Queue</p>
          <h2>我的请求</h2>
        </div>
        <span className="panel-meta">{requests.length} 条记录</span>
      </div>

      <div className="request-stack">
        {requests.map((item) => (
          <button
            key={item.id}
            className={`request-row ${selectedRequestId === item.id ? "selected" : ""}`}
            onClick={() => onSelect(item.id)}
            type="button"
          >
            <div>
              <strong>{item.title}</strong>
              <p>#{item.public_id} · {item.year ?? "年份待定"} · {formatTime(item.updated_at)}</p>
            </div>
            <StatusBadge status={item.status} />
          </button>
        ))}

        {!requests.length ? (
          <div className="empty-state">
            <p>还没有请求记录。先从左侧搜一部你想看的作品。</p>
          </div>
        ) : null}
      </div>

      {isAdmin ? (
        <div className="admin-queue">
          <div className="panel-header tight">
            <div>
              <p className="eyebrow">Admin</p>
              <h3>待审批</h3>
            </div>
            <span className="panel-meta">{adminQueue.length} 条</span>
          </div>

          <div className="request-stack">
            {adminQueue.map((item) => (
              <article key={item.id} className="admin-card">
                <div className="admin-copy">
                  <strong>{item.title}</strong>
                  <p>
                    #{item.public_id} · {item.user.nickname} · {item.media_type} · {formatTime(item.created_at)}
                  </p>
                </div>
                <div className="admin-actions">
                  <button type="button" onClick={() => onOpenAdmin(item.id)}>
                    处理
                  </button>
                  <button type="button" className="secondary" onClick={() => void onReject(item.id)}>
                    拒绝
                  </button>
                </div>
              </article>
            ))}

            {!adminQueue.length ? (
              <div className="empty-state compact">
                <p>审批队列目前很安静。</p>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
