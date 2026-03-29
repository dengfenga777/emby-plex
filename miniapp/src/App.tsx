import { startTransition, useEffect, useState } from "react";

import { AuthGate } from "./components/AuthGate";
import { RequestDetailPanel } from "./components/RequestDetailPanel";
import { RequestsPanel } from "./components/RequestsPanel";
import { SearchPanel } from "./components/SearchPanel";
import {
  bulkRejectRequests,
  bulkSubscribeRequests,
  createRequest,
  directDownloadRequest,
  getMe,
  getRequest,
  listMyRequests,
  listPendingRequests,
  rejectRequest,
  searchAdminResources,
  searchMedia,
  subscribeRequest,
} from "./lib/api";
import { ACTIVE_REQUEST_STATUSES, STATUS_LABELS } from "./lib/requestStatus";
import type {
  AdminRequestSummary,
  AdminResourceCandidate,
  RequestDetail,
  RequestSummary,
  RequestStatus,
  SearchResult,
  SessionResponse,
} from "./lib/types";

const STORAGE_KEY = "moviepilot-request-session";
const RECENT_SEARCHES_KEY = "moviepilot-request-recent-searches";
const APP_TITLE = import.meta.env.VITE_APP_TITLE ?? "MoviePilot Request Deck";

interface StoredSession {
  token: string;
  user: SessionResponse["user"];
}

function readStoredSession(): StoredSession | null {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as StoredSession;
  } catch {
    window.localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

function writeStoredSession(session: StoredSession | null) {
  if (!session) {
    window.localStorage.removeItem(STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

function readRecentQueries() {
  const raw = window.localStorage.getItem(RECENT_SEARCHES_KEY);
  if (!raw) {
    return [] as string[];
  }

  try {
    const items = JSON.parse(raw) as string[];
    return Array.isArray(items) ? items.filter((item) => typeof item === "string") : [];
  } catch {
    window.localStorage.removeItem(RECENT_SEARCHES_KEY);
    return [];
  }
}

function writeRecentQueries(queries: string[]) {
  window.localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(queries.slice(0, 6)));
}

function countByStatus(items: RequestSummary[], status: RequestStatus) {
  return items.filter((item) => item.status === status).length;
}

export default function App() {
  const [session, setSession] = useState<StoredSession | null>(() => readStoredSession());
  const [recentQueries, setRecentQueries] = useState<string[]>(() => readRecentQueries());
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [requests, setRequests] = useState<RequestSummary[]>([]);
  const [adminQueue, setAdminQueue] = useState<AdminRequestSummary[]>([]);
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);
  const [selectedRequest, setSelectedRequest] = useState<RequestDetail | null>(null);
  const [resourceCandidates, setResourceCandidates] = useState<AdminResourceCandidate[]>([]);
  const [resourceRequestId, setResourceRequestId] = useState<string | null>(null);
  const [notice, setNotice] = useState("连接就绪。");
  const [busyLabel, setBusyLabel] = useState<string | null>(null);

  useEffect(() => {
    if (!session) {
      return;
    }

    const activeSession = session;
    let cancelled = false;
    async function bootstrap() {
      try {
        const user = await getMe(activeSession.token);
        if (cancelled) {
          return;
        }
        const nextSession = { token: activeSession.token, user };
        setSession(nextSession);
        writeStoredSession(nextSession);
      } catch (error) {
        if (!cancelled) {
          writeStoredSession(null);
          setSession(null);
          setNotice(error instanceof Error ? error.message : "会话失效，请重新登录。");
        }
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [session?.token]);

  async function refreshDashboard(activeSession: StoredSession, focusRequestId?: string) {
    const [requestItems, pendingItems] = await Promise.all([
      listMyRequests(activeSession.token),
      activeSession.user.role === "admin"
        ? listPendingRequests(activeSession.token)
        : Promise.resolve([] as AdminRequestSummary[]),
    ]);

    startTransition(() => {
      setRequests(requestItems);
      setAdminQueue(pendingItems);

      if (focusRequestId) {
        setSelectedRequestId(focusRequestId);
        return;
      }

      if (selectedRequestId && requestItems.some((item) => item.id === selectedRequestId)) {
        return;
      }

      setSelectedRequestId(requestItems[0]?.id ?? null);
    });
  }

  useEffect(() => {
    if (!session) {
      return;
    }

    const activeSession = session;
    let cancelled = false;
    async function loadDashboard() {
      try {
        await refreshDashboard(activeSession);
      } catch (error) {
        if (!cancelled) {
          setNotice(error instanceof Error ? error.message : "刷新数据失败。");
        }
      }
    }

    void loadDashboard();
    const timer = window.setInterval(() => {
      void loadDashboard();
    }, 15000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [session, selectedRequestId]);

  useEffect(() => {
    if (!session || !selectedRequestId) {
      setSelectedRequest(null);
      return;
    }

    const activeSession = session;
    const requestId = selectedRequestId;
    let cancelled = false;
    async function loadDetail() {
      try {
        const detail = await getRequest(activeSession.token, requestId);
        if (!cancelled) {
          setSelectedRequest(detail);
        }
      } catch (error) {
        if (!cancelled) {
          setNotice(error instanceof Error ? error.message : "请求详情加载失败。");
        }
      }
    }

    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [session, selectedRequestId]);

  useEffect(() => {
    setResourceCandidates([]);
    setResourceRequestId(null);
  }, [selectedRequestId]);

  function handleAuthenticated(nextSession: SessionResponse) {
    const storedSession = { token: nextSession.token, user: nextSession.user };
    writeStoredSession(storedSession);
    setSession(storedSession);
    setNotice(`欢迎回来，${nextSession.user.nickname}。`);
  }

  async function refreshAfterMutation(focusRequestId?: string) {
    if (!session) {
      return;
    }

    await refreshDashboard(session, focusRequestId);
  }

  function rememberSearchQuery(query: string) {
    const nextQueries = [query, ...recentQueries.filter((item) => item !== query)].slice(0, 6);
    setRecentQueries(nextQueries);
    writeRecentQueries(nextQueries);
  }

  async function handleSearch(query: string) {
    if (!session) {
      return;
    }

    const normalizedQuery = query.trim();
    if (!normalizedQuery) {
      setNotice("先输入关键词，再开始搜索。");
      return;
    }

    setBusyLabel("搜索中");
    try {
      const response = await searchMedia(session.token, normalizedQuery);
      startTransition(() => {
        setSearchResults(response.items);
      });
      rememberSearchQuery(normalizedQuery);
      setNotice(
        response.items.length
          ? `找到 ${response.items.length} 个候选结果，可以直接发起求片。`
          : `没有搜到“${normalizedQuery}”，可以试试更短的片名或换个别名。`,
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "搜索失败。");
    } finally {
      setBusyLabel(null);
    }
  }

  function handleClearSearchResults() {
    setSearchResults([]);
    setNotice("已清空当前搜索结果。");
  }

  async function handleCreateRequest(item: SearchResult) {
    if (!session) {
      return;
    }

    setBusyLabel("提交中");
    try {
      const detail = await createRequest(session.token, item);
      setSelectedRequest(detail);
      await refreshAfterMutation(detail.id);
      if (detail.request_reused) {
        const ownerLabel =
          detail.user.id === session.user.id ? "你之前已经提过这条请求" : `这条请求已由 ${detail.user.nickname} 发起`;
        setNotice(
          `${ownerLabel}，已直接定位到现有记录 #${detail.public_id}，当前状态：${STATUS_LABELS[detail.status]}`,
        );
      } else if (detail.moviepilot_task_id?.startsWith("library:") && detail.status === "finished") {
        setNotice(`《${detail.title}》已经在 MoviePilot 库里，已直接记为完成状态。`);
      } else if (
        detail.moviepilot_task_id?.startsWith("subscribe:") &&
        detail.status === "submitted_to_moviepilot"
      ) {
        setNotice(`《${detail.title}》在 MoviePilot 已有订阅，已自动关联到现有处理链路。`);
      } else {
        setNotice(`已提交《${detail.title}》 #${detail.public_id}，当前状态：${STATUS_LABELS[detail.status]}`);
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "提交请求失败。");
    } finally {
      setBusyLabel(null);
    }
  }

  async function handleApprove(requestId: string) {
    await handleSubscribe(requestId);
  }

  async function handleSubscribe(requestId: string) {
    if (!session) {
      return;
    }

    const note = window.prompt("订阅备注（可选）", "Approved by admin.") ?? undefined;
    setBusyLabel("订阅中");
    try {
      const detail = await subscribeRequest(session.token, requestId, note);
      setSelectedRequest(detail);
      setResourceCandidates([]);
      setResourceRequestId(null);
      await refreshAfterMutation(detail.id);
      setNotice(`《${detail.title}》已提交订阅。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "订阅失败。");
    } finally {
      setBusyLabel(null);
    }
  }

  async function handleReject(requestId: string) {
    if (!session) {
      return;
    }

    const note = window.prompt("拒绝备注（可选）", "Rejected by admin.") ?? undefined;
    setBusyLabel("处理拒绝中");
    try {
      const detail = await rejectRequest(session.token, requestId, note);
      setSelectedRequest(detail);
      await refreshAfterMutation(detail.id);
      setNotice(`《${detail.title}》已拒绝。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "拒绝失败。");
    } finally {
      setBusyLabel(null);
    }
  }

  async function handleBulkSubscribe(requestIds: string[]) {
    if (!session || !requestIds.length) {
      return;
    }

    const note = window.prompt("批量通过备注（可选）", "Approved by admin in batch.") ?? undefined;
    setBusyLabel("批量通过中");
    try {
      const result = await bulkSubscribeRequests(session.token, requestIds, note);
      const focusRequestId = result.items[0]?.id;
      if (focusRequestId) {
        setSelectedRequest(result.items[0]);
      }
      await refreshAfterMutation(focusRequestId);
      const skippedHint = result.skipped_count ? `，跳过 ${result.skipped_count} 条` : "";
      setNotice(`已批量通过 ${result.processed_count} 条${skippedHint}。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "批量通过失败。");
    } finally {
      setBusyLabel(null);
    }
  }

  async function handleBulkReject(requestIds: string[]) {
    if (!session || !requestIds.length) {
      return;
    }

    const note = window.prompt("批量拒绝备注（可选）", "Rejected by admin in batch.") ?? undefined;
    setBusyLabel("批量拒绝中");
    try {
      const result = await bulkRejectRequests(session.token, requestIds, note);
      const focusRequestId = result.items[0]?.id;
      if (focusRequestId) {
        setSelectedRequest(result.items[0]);
      }
      await refreshAfterMutation(focusRequestId);
      const skippedHint = result.skipped_count ? `，跳过 ${result.skipped_count} 条` : "";
      setNotice(`已批量拒绝 ${result.processed_count} 条${skippedHint}。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "批量拒绝失败。");
    } finally {
      setBusyLabel(null);
    }
  }

  function handleLogout() {
    writeStoredSession(null);
    setSession(null);
    setSearchResults([]);
    setRequests([]);
    setAdminQueue([]);
    setResourceCandidates([]);
    setResourceRequestId(null);
    setSelectedRequest(null);
    setSelectedRequestId(null);
    setNotice("已退出当前会话。");
  }

  function handleOpenAdminRequest(requestId: string) {
    setSelectedRequestId(requestId);
    setNotice("已切换到管理员处理视图。");
  }

  async function handleRefresh() {
    if (!session) {
      return;
    }

    setBusyLabel("刷新中");
    try {
      await refreshDashboard(session, selectedRequestId ?? undefined);
      if (selectedRequestId) {
        const detail = await getRequest(session.token, selectedRequestId);
        setSelectedRequest(detail);
      }
      setNotice("面板数据已刷新。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "刷新失败。");
    } finally {
      setBusyLabel(null);
    }
  }

  async function handleSearchAdminResources(requestId: string) {
    if (!session) {
      return;
    }

    setBusyLabel("资源站搜索中");
    try {
      const items = await searchAdminResources(session.token, requestId);
      setResourceCandidates(items);
      setResourceRequestId(requestId);
      setNotice(
        items.length
          ? `找到 ${items.length} 条资源站结果，已经拉到前端，可以继续筛选和排序。`
          : "暂时没有搜到可用资源站结果。",
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "资源站搜索失败。");
    } finally {
      setBusyLabel(null);
    }
  }

  async function handleDirectDownload(requestId: string, candidate: AdminResourceCandidate) {
    if (!session) {
      return;
    }

    const note = window.prompt("下载备注（可选）", "Approved by admin for direct download.") ?? undefined;
    setBusyLabel("提交下载中");
    try {
      const detail = await directDownloadRequest(session.token, requestId, candidate, note);
      setSelectedRequest(detail);
      setResourceCandidates([]);
      setResourceRequestId(null);
      await refreshAfterMutation(detail.id);
      setNotice(`《${detail.title}》已加入下载链路。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "直接下载失败。");
    } finally {
      setBusyLabel(null);
    }
  }

  if (!session) {
    return <AuthGate onAuthenticated={handleAuthenticated} />;
  }

  const isAdmin = session.user.role === "admin";
  const activeRequestCount = requests.filter((item) => ACTIVE_REQUEST_STATUSES.includes(item.status)).length;
  const finishedRequestCount = countByStatus(requests, "finished");
  const attentionRequestCount = requests.filter(
    (item) => item.status === "failed" || item.status === "rejected",
  ).length;
  const pendingApprovalCount = countByStatus(requests, "pending");
  const latestRequest = requests[0] ?? null;
  const activeResourceCount = resourceRequestId === selectedRequest?.id ? resourceCandidates.length : 0;
  const statusOverview = (["pending", "approved", "submitted_to_moviepilot", "finished", "failed"] as RequestStatus[])
    .map((status) => ({
      status,
      label: STATUS_LABELS[status],
      count: countByStatus(requests, status),
    }))
    .filter((item) => item.count > 0 || item.status === "pending");

  return (
    <div className="app-shell">
      <header className="hero">
        <div className="hero-copy-block">
          <p className="eyebrow">Telegram MiniApp</p>
          <h1>{APP_TITLE}</h1>
          <p className="hero-copy">
            把搜索、求片、审批和状态同步收拢到一个更顺手的运营台里，用户提需求，管理员能更快决策。
          </p>
        </div>

        <div className="hero-actions">
          <div className="user-pill">
            <strong>{session.user.nickname}</strong>
            <span>{isAdmin ? "管理员" : "普通用户"}</span>
            <small>Auth: {session.user.username ? `@${session.user.username}` : `TG ${session.user.tg_user_id}`}</small>
          </div>
          <button type="button" className="secondary" onClick={handleRefresh} disabled={Boolean(busyLabel)}>
            刷新面板
          </button>
          <button type="button" className="secondary" onClick={handleLogout}>
            退出
          </button>
        </div>
      </header>

      <section className="overview-grid">
        <article className="overview-card accent">
          <p className="overview-label">总请求数</p>
          <strong>{requests.length}</strong>
          <span>{latestRequest ? `最近更新：#${latestRequest.public_id} ${latestRequest.title}` : "还没有记录"}</span>
        </article>
        <article className="overview-card">
          <p className="overview-label">处理中</p>
          <strong>{activeRequestCount}</strong>
          <span>待审批 {pendingApprovalCount} 条</span>
        </article>
        <article className="overview-card">
          <p className="overview-label">已完成</p>
          <strong>{finishedRequestCount}</strong>
          <span>{isAdmin ? `审批队列 ${adminQueue.length} 条` : "已入库内容会自动同步回来"}</span>
        </article>
        <article className="overview-card">
          <p className="overview-label">关注项</p>
          <strong>{attentionRequestCount}</strong>
          <span>{activeResourceCount ? `当前详情已拉取 ${activeResourceCount} 条资源站结果` : "失败或拒绝的请求会在这里体现"}</span>
        </article>
      </section>

      <div className="notice-bar">
        <span>{busyLabel ?? "状态"}</span>
        <p>{notice}</p>
      </div>

      <section className="status-strip" aria-label="请求状态概览">
        {statusOverview.map((item) => (
          <div key={item.status} className={`status-summary-card status-${item.status}`}>
            <strong>{item.count}</strong>
            <span>{item.label}</span>
          </div>
        ))}
      </section>

      <main className="dashboard">
        <SearchPanel
          items={searchResults}
          isBusy={Boolean(busyLabel)}
          recentQueries={recentQueries}
          onSearch={handleSearch}
          onRequest={handleCreateRequest}
          onReuseQuery={handleSearch}
          onClearResults={handleClearSearchResults}
        />
        <RequestsPanel
          requests={requests}
          adminQueue={adminQueue}
          selectedRequestId={selectedRequestId}
          isAdmin={isAdmin}
          isBusy={Boolean(busyLabel)}
          onSelect={setSelectedRequestId}
          onOpenAdmin={handleOpenAdminRequest}
          onReject={handleReject}
          onBulkSubscribe={handleBulkSubscribe}
          onBulkReject={handleBulkReject}
        />
        <RequestDetailPanel
          item={selectedRequest}
          isAdmin={isAdmin}
          isBusy={Boolean(busyLabel)}
          resourceCandidates={resourceCandidates}
          resourceRequestId={resourceRequestId}
          onSearchResources={handleSearchAdminResources}
          onSubscribe={handleApprove}
          onDirectDownload={handleDirectDownload}
        />
      </main>
    </div>
  );
}
