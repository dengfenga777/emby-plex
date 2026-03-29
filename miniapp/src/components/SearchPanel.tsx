import { useState } from "react";
import type { FormEvent } from "react";

import type { SearchResult } from "../lib/types";

interface SearchPanelProps {
  items: SearchResult[];
  isBusy: boolean;
  recentQueries: string[];
  onSearch: (query: string) => Promise<void>;
  onRequest: (item: SearchResult) => Promise<void>;
  onReuseQuery: (query: string) => Promise<void>;
  onClearResults: () => void;
}

const QUICK_QUERIES = ["流浪地球", "沙丘", "黑镜", "孤独摇滚"];

function formatMediaLabel(item: SearchResult) {
  const mediaTypeLabel =
    item.media_type === "movie" ? "电影" : item.media_type === "series" ? "剧集" : "动漫";
  return `${mediaTypeLabel}${item.year ? ` · ${item.year}` : ""}`;
}

export function SearchPanel({
  items,
  isBusy,
  recentQueries,
  onSearch,
  onRequest,
  onReuseQuery,
  onClearResults,
}: SearchPanelProps) {
  const [query, setQuery] = useState("流浪地球");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSearch(query);
  }

  return (
    <section className="panel search-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Search</p>
          <h2>搜索候选影片</h2>
        </div>
        <div className="panel-header-actions">
          <span className="panel-meta">{items.length} 个结果</span>
          {items.length ? (
            <button type="button" className="ghost-button" onClick={onClearResults}>
              清空结果
            </button>
          ) : null}
        </div>
      </div>

      <p className="panel-intro">
        搜索结果会尽量保留标题、来源、年份和简介，确认后可以一键发起求片，不需要再切到别的页面。
      </p>

      <form className="search-form" onSubmit={handleSubmit}>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="输入电影、剧集或动漫名称"
        />
        <button type="submit" disabled={isBusy}>
          {isBusy ? "搜索中..." : "搜索"}
        </button>
      </form>

      <div className="quick-query-block">
        <div className="quick-query-row">
          <span className="quick-query-label">快捷试搜</span>
          {QUICK_QUERIES.map((preset) => (
            <button
              key={preset}
              type="button"
              className="filter-chip"
              onClick={() => {
                setQuery(preset);
                void onReuseQuery(preset);
              }}
            >
              {preset}
            </button>
          ))}
        </div>

        {recentQueries.length ? (
          <div className="quick-query-row">
            <span className="quick-query-label">最近搜索</span>
            {recentQueries.map((recentQuery) => (
              <button
                key={recentQuery}
                type="button"
                className="filter-chip subtle"
                onClick={() => {
                  setQuery(recentQuery);
                  void onReuseQuery(recentQuery);
                }}
              >
                {recentQuery}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="result-grid">
        {items.map((item) => (
          <article key={`${item.source}-${item.source_id}`} className="result-card">
            <div className="poster-shell">
              {item.poster_url ? (
                <img src={item.poster_url} alt={item.title} className="poster" />
              ) : (
                <div className="poster-fallback">{item.title.slice(0, 2)}</div>
              )}
            </div>

            <div className="card-copy">
              <div className="result-meta-row">
                <p className="media-kicker">{formatMediaLabel(item)}</p>
                <span className="source-pill">{item.source}</span>
              </div>
              <h3>{item.title}</h3>
              <p>{item.overview ?? "当前结果没有简介，可以直接提交后由管理员继续处理。"}</p>
            </div>

            <div className="result-footer">
              <span className="result-hint">来源 ID: {item.source_id}</span>
              <button className="ghost-button" onClick={() => void onRequest(item)}>
                求这部
              </button>
            </div>
          </article>
        ))}

        {!items.length ? (
          <div className="empty-state">
            <p>先搜一部想看的作品，我们会把它送进审批和下载链路。</p>
            <small>可以从上面的快捷试搜开始，也可以直接输入片名、译名或系列名。</small>
          </div>
        ) : null}
      </div>
    </section>
  );
}
