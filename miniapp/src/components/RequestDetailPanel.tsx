import { useEffect, useState } from "react";

import { StatusBadge } from "./StatusBadge";
import type { AdminResourceCandidate, RequestDetail, RequestStatus } from "../lib/types";

interface RequestDetailPanelProps {
  item: RequestDetail | null;
  isAdmin: boolean;
  isBusy: boolean;
  resourceCandidates: AdminResourceCandidate[];
  resourceRequestId: string | null;
  onSearchResources: (requestId: string) => Promise<void>;
  onSubscribe: (requestId: string) => Promise<void>;
  onDirectDownload: (requestId: string, candidate: AdminResourceCandidate) => Promise<void>;
}

const ACTIONABLE_STATUSES: RequestStatus[] = ["pending", "approved", "failed"];
type ResourceSortMode =
  | "score_desc"
  | "seeders_desc"
  | "pubdate_desc"
  | "size_asc"
  | "size_desc";

function buildStatusSummary(item: RequestDetail, isAdmin: boolean) {
  switch (item.status) {
    case "pending":
      return {
        title: isAdmin ? "等待管理员处理" : "请求已进入审批队列",
        description: isAdmin
          ? "建议先搜资源站结果，再决定直接下载还是走订阅。"
          : "管理员确认后会继续进入订阅或下载流程。",
      };
    case "approved":
      return {
        title: "已经批准，等待进入执行链路",
        description: isAdmin
          ? "这条请求已经获批，现在可以直接订阅，或者从资源站结果里挑一条直接下载。"
          : "请求已经通过审批，马上会进入 MoviePilot 执行链路。",
      };
    case "submitted_to_moviepilot":
      return {
        title: "订阅已发给 MoviePilot",
        description: "后续下载、整理、入库状态会自动同步回来，不需要重复处理。",
      };
    case "downloading":
      return {
        title: "正在下载",
        description: "资源已经进入下载器，等下载完成后会继续进入整理和入库。",
      };
    case "organizing":
      return {
        title: "正在整理入库",
        description: "MoviePilot 正在做转移、刮削或媒体库整理，通常离入库已经很近了。",
      };
    case "finished":
      return {
        title: "已经入库",
        description: "这条内容已经被 MoviePilot 判定为在库，可直接通知群里或让用户去媒体库查看。",
      };
    case "failed":
      return {
        title: "处理失败，需要重新介入",
        description: isAdmin
          ? "可以先搜资源重新挑一条直接下载，或者改走订阅。"
          : "管理员会根据失败原因重新处理这条请求。",
      };
    case "rejected":
      return {
        title: "请求已拒绝",
        description: item.admin_note ?? "这条请求已经终止，不会再进入下载链路。",
      };
    default:
      return {
        title: "状态待同步",
        description: "系统正在刷新这条请求的最新处理结果。",
      };
  }
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatBytes(value: number | null) {
  if (!value || value <= 0) {
    return "大小未知";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 100 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function canAdminHandle(status: RequestStatus) {
  return ACTIONABLE_STATUSES.includes(status);
}

function normalizeText(value: string | null | undefined) {
  return (value ?? "").trim().toLowerCase();
}

function buildCandidateSearchText(candidate: AdminResourceCandidate) {
  return [
    candidate.title,
    candidate.subtitle,
    candidate.description,
    candidate.site_name,
    candidate.resource_type,
    candidate.resource_pix,
    candidate.resource_effect,
    candidate.video_encode,
    candidate.audio_encode,
    candidate.season_episode,
    candidate.volume_factor,
    ...candidate.labels,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function isFreeCandidate(candidate: AdminResourceCandidate) {
  if (candidate.download_volume_factor === 0) {
    return true;
  }

  const volumeFactor = normalizeText(candidate.volume_factor);
  return (
    volumeFactor.includes("free") ||
    volumeFactor.includes("免费") ||
    volumeFactor === "0" ||
    volumeFactor === "0.0" ||
    volumeFactor === "0.00"
  );
}

function isFourKCandidate(candidate: AdminResourceCandidate) {
  const pix = normalizeText(candidate.resource_pix);
  if (pix.includes("2160") || pix.includes("4k")) {
    return true;
  }
  return candidate.labels.some((label) => {
    const normalized = normalizeText(label);
    return normalized.includes("4k") || normalized.includes("2160");
  });
}

function hasChineseSubtitle(candidate: AdminResourceCandidate) {
  const searchText = buildCandidateSearchText(candidate);
  return searchText.includes("中字") || searchText.includes("中文字幕");
}

function parsePubdate(value: string | null) {
  if (!value) {
    return 0;
  }
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function sortResourceCandidates(items: AdminResourceCandidate[], sortMode: ResourceSortMode) {
  const nextItems = [...items];
  nextItems.sort((left, right) => {
    if (sortMode === "seeders_desc") {
      return (right.seeders ?? 0) - (left.seeders ?? 0) || right.score - left.score;
    }
    if (sortMode === "pubdate_desc") {
      return parsePubdate(right.pubdate) - parsePubdate(left.pubdate) || right.score - left.score;
    }
    if (sortMode === "size_asc") {
      return (left.size ?? Number.MAX_SAFE_INTEGER) - (right.size ?? Number.MAX_SAFE_INTEGER) || right.score - left.score;
    }
    if (sortMode === "size_desc") {
      return (right.size ?? -1) - (left.size ?? -1) || right.score - left.score;
    }

    return (
      right.score - left.score ||
      (right.seeders ?? 0) - (left.seeders ?? 0) ||
      (right.grabs ?? 0) - (left.grabs ?? 0) ||
      (left.size ?? Number.MAX_SAFE_INTEGER) - (right.size ?? Number.MAX_SAFE_INTEGER)
    );
  });
  return nextItems;
}

export function RequestDetailPanel({
  item,
  isAdmin,
  isBusy,
  resourceCandidates,
  resourceRequestId,
  onSearchResources,
  onSubscribe,
  onDirectDownload,
}: RequestDetailPanelProps) {
  const [resourceKeyword, setResourceKeyword] = useState("");
  const [episodeFilter, setEpisodeFilter] = useState("");
  const [sortMode, setSortMode] = useState<ResourceSortMode>("score_desc");
  const [freeOnly, setFreeOnly] = useState(false);
  const [onlyFourK, setOnlyFourK] = useState(false);
  const [subtitleOnly, setSubtitleOnly] = useState(false);
  const [excludeHr, setExcludeHr] = useState(false);

  useEffect(() => {
    setResourceKeyword("");
    setEpisodeFilter("");
    setSortMode("score_desc");
    setFreeOnly(false);
    setOnlyFourK(false);
    setSubtitleOnly(false);
    setExcludeHr(false);
  }, [item?.id, resourceRequestId]);

  if (!item) {
    return (
      <section className="panel detail-panel">
        <div className="empty-state">
          <p>选择一条请求后，这里会显示完整状态流和处理日志。</p>
        </div>
      </section>
    );
  }

  const showAdminTools = isAdmin && canAdminHandle(item.status);
  const isResourceSearchLoaded = resourceRequestId === item.id;
  const keyword = normalizeText(resourceKeyword);
  const episodeKeyword = normalizeText(episodeFilter);
  const activeResourceCandidates = isResourceSearchLoaded ? resourceCandidates : [];
  const hasLoadedResources = isResourceSearchLoaded && activeResourceCandidates.length > 0;
  const filteredResourceCandidates = sortResourceCandidates(
    activeResourceCandidates.filter((candidate) => {
      if (keyword && !buildCandidateSearchText(candidate).includes(keyword)) {
        return false;
      }

      if (episodeKeyword) {
        const episodeText = [candidate.season_episode, candidate.title, candidate.subtitle]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!episodeText.includes(episodeKeyword)) {
          return false;
        }
      }

      if (freeOnly && !isFreeCandidate(candidate)) {
        return false;
      }
      if (onlyFourK && !isFourKCandidate(candidate)) {
        return false;
      }
      if (subtitleOnly && !hasChineseSubtitle(candidate)) {
        return false;
      }
      if (excludeHr && candidate.hit_and_run) {
        return false;
      }

      return true;
    }),
    sortMode,
  );
  const showResourceCandidates = hasLoadedResources && filteredResourceCandidates.length > 0;
  const hasActiveResourceFilters = Boolean(
    resourceKeyword || episodeFilter || freeOnly || onlyFourK || subtitleOnly || excludeHr || sortMode !== "score_desc",
  );
  const statusSummary = buildStatusSummary(item, isAdmin);

  return (
    <section className="panel detail-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Timeline</p>
          <h2>{item.title}</h2>
        </div>
        <StatusBadge status={item.status} />
      </div>

      <div className="detail-meta">
        <span>请求 #{item.public_id}</span>
        <span>{item.media_type}</span>
        <span>{item.year ?? "年份待定"}</span>
        <span>{item.source}</span>
        <span>请求人：{item.user.nickname}</span>
      </div>

      <p className="detail-copy">
        {item.overview ?? "暂无剧情简介，当前请求由系统保留了标题和来源信息。"}
      </p>

      <section className={`status-card status-${item.status}`}>
        <div>
          <p className="eyebrow">Status Insight</p>
          <h3>{statusSummary.title}</h3>
        </div>
        <p className="detail-copy">{statusSummary.description}</p>
        <div className="detail-meta">
          {item.moviepilot_task_id ? <span>任务：{item.moviepilot_task_id}</span> : null}
          {item.admin_note ? <span>备注：{item.admin_note}</span> : null}
        </div>
      </section>

      {showAdminTools ? (
        <section className="admin-toolbox">
          <div className="panel-header tight">
            <div>
              <p className="eyebrow">Admin Actions</p>
              <h3>资源站处理</h3>
            </div>
          </div>

          <div className="tool-actions">
            <button type="button" className="secondary" disabled={isBusy} onClick={() => void onSearchResources(item.id)}>
              搜资源
            </button>
            <button type="button" disabled={isBusy} onClick={() => void onSubscribe(item.id)}>
              订阅
            </button>
          </div>

          {hasLoadedResources ? (
            <div className="resource-list">
              <div className="resource-list-header">
                <p className="detail-copy">
                  资源先全量拉回来，再在当前页面本地筛选。现在显示 {filteredResourceCandidates.length} / {activeResourceCandidates.length} 条。
                </p>
              </div>

              <div className="resource-filter-shell">
                <div className="resource-filter-grid">
                  <label className="filter-field">
                    <span>关键词</span>
                    <input
                      value={resourceKeyword}
                      onChange={(event) => setResourceKeyword(event.target.value)}
                      placeholder="站点、标题、分辨率、标签"
                    />
                  </label>

                  <label className="filter-field">
                    <span>集数筛选</span>
                    <input
                      value={episodeFilter}
                      onChange={(event) => setEpisodeFilter(event.target.value)}
                      placeholder="如 E01、E01-E12、全集"
                    />
                  </label>

                  <label className="filter-field">
                    <span>排序</span>
                    <select value={sortMode} onChange={(event) => setSortMode(event.target.value as ResourceSortMode)}>
                      <option value="score_desc">推荐优先</option>
                      <option value="seeders_desc">做种最多</option>
                      <option value="pubdate_desc">最新发布</option>
                      <option value="size_asc">体积从小到大</option>
                      <option value="size_desc">体积从大到小</option>
                    </select>
                  </label>
                </div>

                <div className="filter-chip-row">
                  <button
                    type="button"
                    className={`filter-chip ${freeOnly ? "active" : ""}`}
                    onClick={() => setFreeOnly((value) => !value)}
                  >
                    仅免流
                  </button>
                  <button
                    type="button"
                    className={`filter-chip ${onlyFourK ? "active" : ""}`}
                    onClick={() => setOnlyFourK((value) => !value)}
                  >
                    仅 4K
                  </button>
                  <button
                    type="button"
                    className={`filter-chip ${subtitleOnly ? "active" : ""}`}
                    onClick={() => setSubtitleOnly((value) => !value)}
                  >
                    仅中字
                  </button>
                  <button
                    type="button"
                    className={`filter-chip ${excludeHr ? "active" : ""}`}
                    onClick={() => setExcludeHr((value) => !value)}
                  >
                    排除 H&R
                  </button>
                  {hasActiveResourceFilters ? (
                    <button
                      type="button"
                      className="filter-chip clear"
                      onClick={() => {
                        setResourceKeyword("");
                        setEpisodeFilter("");
                        setSortMode("score_desc");
                        setFreeOnly(false);
                        setOnlyFourK(false);
                        setSubtitleOnly(false);
                        setExcludeHr(false);
                      }}
                    >
                      清空筛选
                    </button>
                  ) : null}
                </div>
              </div>

              {showResourceCandidates ? (
                filteredResourceCandidates.map((candidate, index) => (
                  <article key={`${candidate.page_url ?? candidate.title}-${index}`} className="resource-card">
                    <div className="resource-copy">
                      <div className="resource-title-row">
                        {sortMode === "score_desc" && index === 0 ? <span className="resource-rank">推荐</span> : null}
                        {candidate.recommendation ? <span className="resource-rank subtle">{candidate.recommendation}</span> : null}
                      </div>
                      <strong>{candidate.title}</strong>
                      {candidate.subtitle ? <p>{candidate.subtitle}</p> : null}
                    </div>

                    <div className="detail-meta resource-pills">
                      {candidate.site_name ? <span>{candidate.site_name}</span> : null}
                      {candidate.resource_type ? <span>{candidate.resource_type}</span> : null}
                      {candidate.resource_pix ? <span>{candidate.resource_pix}</span> : null}
                      {candidate.resource_effect ? <span>{candidate.resource_effect}</span> : null}
                      {candidate.video_encode ? <span>{candidate.video_encode}</span> : null}
                      {candidate.audio_encode ? <span>{candidate.audio_encode}</span> : null}
                      {candidate.season_episode ? <span>{candidate.season_episode}</span> : null}
                      {candidate.volume_factor ? <span>{candidate.volume_factor}</span> : null}
                      {candidate.hit_and_run ? <span>H&R</span> : null}
                    </div>

                    <div className="resource-stats">
                      <span>{formatBytes(candidate.size)}</span>
                      <span>做种 {candidate.seeders ?? 0}</span>
                      <span>下载 {candidate.grabs ?? 0}</span>
                      <span>优先级 {candidate.score}</span>
                      {candidate.pubdate ? <span>{candidate.pubdate}</span> : null}
                    </div>

                    {candidate.description ? <p className="detail-copy">{candidate.description}</p> : null}

                    {candidate.labels.length ? (
                      <div className="detail-meta resource-pills">
                        {candidate.labels.map((label) => (
                          <span key={label}>{label}</span>
                        ))}
                      </div>
                    ) : null}

                    <div className="resource-actions">
                      {candidate.page_url ? (
                        <a href={candidate.page_url} target="_blank" rel="noreferrer" className="resource-link">
                          查看源页面
                        </a>
                      ) : null}
                      <button type="button" disabled={isBusy} onClick={() => void onDirectDownload(item.id, candidate)}>
                        直接下载
                      </button>
                    </div>
                  </article>
                ))
              ) : (
                <div className="empty-state compact">
                  <p>当前筛选后没有可见资源，可以调一下排序、集数或快速筛选条件。</p>
                </div>
              )}
            </div>
          ) : isResourceSearchLoaded ? (
            <div className="empty-state compact">
              <p>这次没有搜到可用资源站结果。</p>
            </div>
          ) : (
            <div className="empty-state compact">
              <p>先点“搜资源”，再从结果里挑一条直接下载；如果不挑资源，也可以直接订阅。</p>
            </div>
          )}
        </section>
      ) : null}

      <div className="log-list">
        {item.logs.map((log) => (
          <div key={log.id} className="log-card">
            <div className="log-heading">
              <strong>{log.to_status}</strong>
              <span>{formatTime(log.created_at)}</span>
            </div>
            <p>{log.note ?? "没有额外备注。"}</p>
            <small>{log.operator}</small>
          </div>
        ))}
      </div>
    </section>
  );
}
