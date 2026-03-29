import { useState } from "react";
import type { FormEvent } from "react";

import type { SearchResult } from "../lib/types";

interface SearchPanelProps {
  items: SearchResult[];
  isBusy: boolean;
  onSearch: (query: string) => Promise<void>;
  onRequest: (item: SearchResult) => Promise<void>;
}

export function SearchPanel({ items, isBusy, onSearch, onRequest }: SearchPanelProps) {
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
        <span className="panel-meta">{items.length} 个结果</span>
      </div>

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
              <p className="media-kicker">
                {item.media_type.toUpperCase()}
                {item.year ? ` / ${item.year}` : ""}
              </p>
              <h3>{item.title}</h3>
              <p>{item.overview ?? "当前结果没有简介，可以直接提交后由管理员继续处理。"}</p>
            </div>

            <button className="ghost-button" onClick={() => void onRequest(item)}>
              求这部
            </button>
          </article>
        ))}

        {!items.length ? (
          <div className="empty-state">
            <p>先搜一部想看的作品，我们会把它送进审批和下载链路。</p>
          </div>
        ) : null}
      </div>
    </section>
  );
}
