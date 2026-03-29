/// <reference types="vite/client" />

interface TelegramWebAppUser {
  id: number;
  username?: string;
  first_name?: string;
  last_name?: string;
}

interface TelegramWebApp {
  initData: string;
  initDataUnsafe?: {
    user?: TelegramWebAppUser;
  };
  ready?: () => void;
  expand?: () => void;
}

interface Window {
  Telegram?: {
    WebApp?: TelegramWebApp;
  };
}

