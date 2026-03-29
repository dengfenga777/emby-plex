import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { authenticateWithDevProfile, authenticateWithTelegram } from "../lib/api";
import type { SessionResponse } from "../lib/types";

interface AuthGateProps {
  onAuthenticated: (session: SessionResponse) => void;
}

function splitDisplayName(displayName: string): { firstName?: string; lastName?: string } {
  const [firstName, ...rest] = displayName.trim().split(/\s+/);
  return {
    firstName: firstName || undefined,
    lastName: rest.length ? rest.join(" ") : undefined,
  };
}

export function AuthGate({ onAuthenticated }: AuthGateProps) {
  const allowDevLogin =
    import.meta.env.DEV ||
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";
  const [userId, setUserId] = useState("1");
  const [username, setUsername] = useState("demo_admin");
  const [displayName, setDisplayName] = useState("Demo Admin");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAutoAuthing, setIsAutoAuthing] = useState(true);

  useEffect(() => {
    const webApp = window.Telegram?.WebApp;
    webApp?.ready?.();
    webApp?.expand?.();

    const telegramUser = webApp?.initDataUnsafe?.user;
    if (telegramUser) {
      setUserId(String(telegramUser.id));
      setUsername(telegramUser.username ?? "");
      setDisplayName(
        [telegramUser.first_name, telegramUser.last_name].filter(Boolean).join(" ") ||
          telegramUser.username ||
          "Telegram User",
      );
    }

    if (!webApp?.initData) {
      if (!allowDevLogin) {
        setError("请从 Telegram 机器人菜单打开 MiniApp。");
      }
      setIsAutoAuthing(false);
      return;
    }

    void (async () => {
      try {
        const session = await authenticateWithTelegram(webApp.initData);
        onAuthenticated(session);
      } catch (authError) {
        setError(authError instanceof Error ? authError.message : "Telegram 登录失败。");
      } finally {
        setIsAutoAuthing(false);
      }
    })();
  }, [onAuthenticated]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsedUserId = Number(userId);
    if (!Number.isInteger(parsedUserId) || parsedUserId <= 0) {
      setError("请输入有效的 Telegram 用户 ID。");
      return;
    }

    setError(null);
    setIsSubmitting(true);
    try {
      const names = splitDisplayName(displayName);
      const session = await authenticateWithDevProfile({
        id: parsedUserId,
        username: username || undefined,
        first_name: names.firstName,
        last_name: names.lastName,
      });
      onAuthenticated(session);
    } catch (authError) {
      setError(authError instanceof Error ? authError.message : "开发登录失败。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="auth-shell">
      <section className="auth-panel">
        <p className="eyebrow">MoviePilot Request Deck</p>
        <h1>把 Telegram 求片系统先跑起来</h1>
        <p className="auth-copy">
          {allowDevLogin
            ? "当前页面支持 Telegram 自动登录，也保留了本地开发登录，方便我们先把流程跑通。"
            : "请从 Telegram Bot 菜单打开 MiniApp，页面会自动识别你的 Telegram 身份。"}
        </p>

        {isAutoAuthing ? <p className="auth-tip">正在尝试 Telegram 自动登录...</p> : null}
        {error ? <p className="auth-error">{error}</p> : null}

        {allowDevLogin ? (
          <form className="auth-form" onSubmit={handleSubmit}>
            <label>
              Telegram User ID
              <input value={userId} onChange={(event) => setUserId(event.target.value)} />
            </label>
            <label>
              Username
              <input value={username} onChange={(event) => setUsername(event.target.value)} />
            </label>
            <label>
              显示名称
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            </label>
            <button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "登录中..." : "使用开发身份进入"}
            </button>
          </form>
        ) : null}
      </section>
    </div>
  );
}
