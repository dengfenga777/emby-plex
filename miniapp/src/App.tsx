import { startTransition, useEffect, useState } from "react";

import { AuthGate } from "./components/AuthGate";
import { RequestDetailPanel } from "./components/RequestDetailPanel";
import { RequestsPanel } from "./components/RequestsPanel";
import { SearchPanel } from "./components/SearchPanel";
import {
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
import type {
  AdminRequestSummary,
  AdminResourceCandidate,
  RequestDetail,
  RequestSummary,
  SearchResult,
  SessionResponse,
} from "./lib/types";

const STORAGE_KEY = "moviepilot-request-session";
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

export default function App() {
  const [session, setSession] = useState<StoredSession | null>(() => readStoredSession());
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

  useEffect(() => {
    if (!session) {
      return;
    }

    const activeSession = session;
    let cancelled = false;
    async function refreshDashboard() {
      try {
        const [requestItems, pendingItems] = await Promise.all([
          listMyRequests(activeSession.token),
          activeSession.user.role === "admin"
            ? listPendingRequests(activeSession.token)
            : Promise.resolve([] as AdminRequestSummary[]),
        ]);
        if (cancelled) {
          return;
        }

        startTransition(() => {
          setRequests(requestItems);
          setAdminQueue(pendingItems);
          if (!selectedRequestId && requestItems.length) {
            setSelectedRequestId(requestItems[0].id);
          }
        });
      } catch (error) {
        if (!cancelled) {
          setNotice(error instanceof Error ? error.message : "刷新数据失败。");
        }
      }
    }

    void refreshDashboard();
    const timer = window.setInterval(() => {
      void refreshDashboard();
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

    const [requestItems, pendingItems] = await Promise.all([
      listMyRequests(session.token),
      session.user.role === "admin" ? listPendingRequests(session.token) : Promise.resolve([]),
    ]);
    startTransition(() => {
      setRequests(requestItems);
      setAdminQueue(pendingItems);
      if (focusRequestId) {
        setSelectedRequestId(focusRequestId);
      } else if (!selectedRequestId && requestItems.length) {
        setSelectedRequestId(requestItems[0].id);
      }
    });
  }

  async function handleSearch(query: string) {
    if (!session) {
      return;
    }

    setBusyLabel("搜索中");
    try {
      const response = await searchMedia(session.token, query);
      startTransition(() => {
        setSearchResults(response.items);
      });
      setNotice(`找到 ${response.items.length} 个候选结果。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "搜索失败。");
    } finally {
      setBusyLabel(null);
    }
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
      setNotice(`已提交《${detail.title}》 #${detail.public_id}，当前状态：${detail.status}`);
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

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Telegram MiniApp</p>
          <h1>{APP_TITLE}</h1>
          <p className="hero-copy">
            以 Telegram 为入口，把搜索、求片、审批和状态同步收拢到一块轻前台里。
          </p>
        </div>

        <div className="hero-actions">
          <div className="user-pill">
            <strong>{session.user.nickname}</strong>
            <span>{session.user.role === "admin" ? "管理员" : "普通用户"}</span>
          </div>
          <button type="button" className="secondary" onClick={handleLogout}>
            退出
          </button>
        </div>
      </header>

      <div className="notice-bar">
        <span>{busyLabel ?? "状态"}</span>
        <p>{notice}</p>
      </div>

      <main className="dashboard">
        <SearchPanel
          items={searchResults}
          isBusy={Boolean(busyLabel)}
          onSearch={handleSearch}
          onRequest={handleCreateRequest}
        />
        <RequestsPanel
          requests={requests}
          adminQueue={adminQueue}
          selectedRequestId={selectedRequestId}
          isAdmin={session.user.role === "admin"}
          onSelect={setSelectedRequestId}
          onOpenAdmin={handleOpenAdminRequest}
          onReject={handleReject}
        />
        <RequestDetailPanel
          item={selectedRequest}
          isAdmin={session.user.role === "admin"}
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
