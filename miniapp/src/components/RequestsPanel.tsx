import { useDeferredValue, useEffect, useState } from "react";

import { getStatusLabel } from "../lib/requestStatus";
import { StatusBadge } from "./StatusBadge";
import type { AdminRequestSummary, RequestSummary } from "../lib/types";

interface RequestsPanelProps {
  requests: RequestSummary[];
  adminQueue: AdminRequestSummary[];
  selectedRequestId: string | null;
  isAdmin: boolean;
  isBusy: boolean;
  onSelect: (requestId: string) => void;
  onOpenAdmin: (requestId: string) => void;
  onReject: (requestId: string) => Promise<void>;
  onBulkSubscribe: (requestIds: string[]) => Promise<void>;
  onBulkReject: (requestIds: string[]) => Promise<void>;
}

type ViewMode = "all" | "active" | "finished" | "attention";
type SortMode = "updated_desc" | "created_desc" | "title_asc";

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function matchesViewMode(item: RequestSummary, viewMode: ViewMode) {
  if (viewMode === "active") {
    return ["pending", "approved", "submitted_to_moviepilot", "downloading", "organizing"].includes(item.status);
  }
  if (viewMode === "finished") {
    return item.status === "finished";
  }
  if (viewMode === "attention") {
    return item.status === "failed" || item.status === "rejected";
  }
  return true;
}

function sortRequests(items: RequestSummary[], sortMode: SortMode) {
  const nextItems = [...items];
  nextItems.sort((left, right) => {
    if (sortMode === "created_desc") {
      return Date.parse(right.created_at) - Date.parse(left.created_at);
    }
    if (sortMode === "title_asc") {
      return left.title.localeCompare(right.title, "zh-CN");
    }
    return Date.parse(right.updated_at) - Date.parse(left.updated_at);
  });
  return nextItems;
}

export function RequestsPanel({
  requests,
  adminQueue,
  selectedRequestId,
  isAdmin,
  isBusy,
  onSelect,
  onOpenAdmin,
  onReject,
  onBulkSubscribe,
  onBulkReject,
}: RequestsPanelProps) {
  const [viewMode, setViewMode] = useState<ViewMode>("all");
  const [sortMode, setSortMode] = useState<SortMode>("updated_desc");
  const [searchText, setSearchText] = useState("");
  const [selectedAdminIds, setSelectedAdminIds] = useState<string[]>([]);
  const deferredSearchText = useDeferredValue(searchText.trim().toLowerCase());

  const selectableAdminIds = adminQueue.map((item) => item.id);
  const selectedCount = selectedAdminIds.length;

  useEffect(() => {
    setSelectedAdminIds((current) => current.filter((item) => selectableAdminIds.includes(item)));
  }, [adminQueue]);

  function toggleAdminSelection(requestId: string) {
    setSelectedAdminIds((current) =>
      current.includes(requestId) ? current.filter((item) => item !== requestId) : [...current, requestId],
    );
  }

  function selectAllAdminQueue() {
    setSelectedAdminIds(selectableAdminIds);
  }

  function clearAdminSelection() {
    setSelectedAdminIds([]);
  }

  const filteredRequests = sortRequests(
    requests.filter((item) => {
      if (!matchesViewMode(item, viewMode)) {
        return false;
      }

      if (!deferredSearchText) {
        return true;
      }

      const searchCorpus = [item.title, item.overview, item.source, getStatusLabel(item.status)]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return searchCorpus.includes(deferredSearchText);
    }),
    sortMode,
  );

  const activeCount = requests.filter((item) =>
    ["pending", "approved", "submitted_to_moviepilot", "downloading", "organizing"].includes(item.status),
  ).length;
  const finishedCount = requests.filter((item) => item.status === "finished").length;
  const attentionCount = requests.filter((item) => item.status === "failed" || item.status === "rejected").length;

  return (
    <section className="panel request-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Queue</p>
          <h2>我的请求</h2>
        </div>
        <span className="panel-meta">{requests.length} 条记录</span>
      </div>

      <div className="queue-summary-grid">
        <article className="mini-stat-card">
          <span>进行中</span>
          <strong>{activeCount}</strong>
        </article>
        <article className="mini-stat-card">
          <span>已完成</span>
          <strong>{finishedCount}</strong>
        </article>
        <article className="mini-stat-card">
          <span>需关注</span>
          <strong>{attentionCount}</strong>
        </article>
      </div>

      <div className="queue-toolbar">
        <div className="filter-chip-row">
          <button
            type="button"
            className={`filter-chip ${viewMode === "all" ? "active" : ""}`}
            onClick={() => setViewMode("all")}
          >
            全部
          </button>
          <button
            type="button"
            className={`filter-chip ${viewMode === "active" ? "active" : ""}`}
            onClick={() => setViewMode("active")}
          >
            处理中
          </button>
          <button
            type="button"
            className={`filter-chip ${viewMode === "finished" ? "active" : ""}`}
            onClick={() => setViewMode("finished")}
          >
            已完成
          </button>
          <button
            type="button"
            className={`filter-chip ${viewMode === "attention" ? "active" : ""}`}
            onClick={() => setViewMode("attention")}
          >
            需关注
          </button>
        </div>

        <div className="queue-toolbar-grid">
          <input
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            placeholder="按标题、状态或来源过滤"
          />
          <select value={sortMode} onChange={(event) => setSortMode(event.target.value as SortMode)}>
            <option value="updated_desc">最近更新</option>
            <option value="created_desc">最近创建</option>
            <option value="title_asc">按标题排序</option>
          </select>
        </div>
      </div>

      <div className="request-stack">
        {filteredRequests.map((item) => (
          <button
            key={item.id}
            className={`request-row ${selectedRequestId === item.id ? "selected" : ""}`}
            onClick={() => onSelect(item.id)}
            type="button"
          >
            <div className="request-row-copy">
              <div className="request-row-topline">
                <strong>{item.title}</strong>
                <span className="request-source-tag">{item.media_type}</span>
              </div>
              <p>
                #{item.public_id} · {item.year ?? "年份待定"} · {formatTime(item.updated_at)}
              </p>
              <small>{item.admin_note ?? item.overview ?? `来源：${item.source}`}</small>
            </div>
            <StatusBadge status={item.status} />
          </button>
        ))}

        {!filteredRequests.length ? (
          <div className="empty-state">
            <p>当前筛选条件下没有请求记录。</p>
            <small>可以切换视图、清空搜索，或者先从左侧发起一个新请求。</small>
          </div>
        ) : null}
      </div>

      {isAdmin ? (
        <div className="admin-queue">
          <div className="panel-header tight">
            <div>
              <p className="eyebrow">Admin</p>
              <h3>待审批队列</h3>
            </div>
            <span className="panel-meta">{adminQueue.length} 条</span>
          </div>

          <div className="admin-bulk-toolbar">
            <div className="filter-chip-row">
              <button
                type="button"
                className="filter-chip"
                onClick={selectAllAdminQueue}
                disabled={!adminQueue.length || selectedCount === adminQueue.length}
              >
                全选
              </button>
              <button
                type="button"
                className="filter-chip"
                onClick={clearAdminSelection}
                disabled={!selectedCount}
              >
                清空
              </button>
              <span className="panel-meta">已选 {selectedCount} 条</span>
            </div>

            <div className="admin-actions">
              <button
                type="button"
                disabled={!selectedCount || isBusy}
                onClick={() => void onBulkSubscribe(selectedAdminIds)}
              >
                批量通过
              </button>
              <button
                type="button"
                className="secondary"
                disabled={!selectedCount || isBusy}
                onClick={() => void onBulkReject(selectedAdminIds)}
              >
                批量拒绝
              </button>
            </div>
          </div>

          <div className="request-stack">
            {adminQueue.map((item) => (
              <article key={item.id} className="admin-card">
                <div className="admin-copy">
                  <label className="admin-select-row">
                    <input
                      type="checkbox"
                      checked={selectedAdminIds.includes(item.id)}
                      onChange={() => toggleAdminSelection(item.id)}
                    />
                    <span>加入批量处理</span>
                  </label>
                  <div className="request-row-topline">
                    <strong>{item.title}</strong>
                    <StatusBadge status={item.status} />
                  </div>
                  <p>
                    #{item.public_id} · {item.user.nickname} · {item.media_type} · {formatTime(item.created_at)}
                  </p>
                  <small>{item.overview ?? `来源：${item.source}`}</small>
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
                <small>新提交的请求会在这里集中出现，方便管理员快速处理。</small>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
