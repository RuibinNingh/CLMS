import { useEffect, useState } from "react";
import { api, errorText, setAuth } from "../shared/api";
import type { Auth } from "../shared/types";
import { applyTheme } from "../shared/theme";
import { ErrorNotice, Field, Loading } from "../shared/ui";
import { Brand, BrandMark } from "../shared/Brand";
import { Icon, type IconName } from "../shared/Icon";
import { Archive } from "../features/archive/Archive";
import { PromptDetail } from "../features/archive/PromptDetail";
import { Submission } from "../features/submission/Submission";
import { ReviewCenter } from "../features/review-center/ReviewCenter";
import { PendingReviewBadge } from "../features/review-center/PendingReviewBadge";
import { Categories } from "../features/categories/Categories";
import { SettingsPage } from "../features/settings/Settings";

const navigation = [
  { path: "archive", title: "作文档案", icon: "archive" },
  { path: "reviews", title: "审核中心", icon: "review" },
  { path: "categories", title: "分类管理", icon: "tags" },
  { path: "settings", title: "设置", icon: "settings" },
] satisfies { path: string; title: string; icon: IconName }[];
export function go(path: string) {
  window.location.hash = `/${path}`;
}
export function App() {
  const [auth, updateAuth] = useState<Auth>();
  const [error, setError] = useState("");
  const [route, setRoute] = useState(
    window.location.hash.slice(2) || "archive",
  );
  useEffect(() => {
    const change = () => {
      setRoute(window.location.hash.slice(2) || "archive");
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  const refreshAuth = async () => {
    try {
      const state = await api<Auth>("/auth/status");
      setAuth(state);
      updateAuth(state);
    } catch (reason) {
      setError(errorText(reason));
    }
  };
  useEffect(() => {
    void refreshAuth();
  }, []);
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const sync = () =>
      applyTheme(localStorage.getItem("clms-theme") || "system");
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);
  if (!auth)
    return (
      <main className="auth">
        <ErrorNotice message={error} retry={refreshAuth} />
        <Loading />
      </main>
    );
  if (!auth.authenticated) return <Login auth={auth} onLogin={refreshAuth} />;
  const [path, search = ""] = route.split("?");
  const query = new URLSearchParams(search);
  const active =
    path.startsWith("prompt/") || path === "submit" ? "archive" : path;
  let content;
  if (path.startsWith("prompt/"))
    content = (
      <PromptDetail
        key={`${path}-${query.get("version") || ""}`}
        id={path.slice(7)}
        selectedVersionId={query.get("version")}
      />
    );
  else if (path === "submit")
    content = (
      <Submission
        key={route}
        promptId={query.get("prompt")}
        attemptId={query.get("attempt")}
        parentId={query.get("parent")}
      />
    );
  else if (path === "reviews")
    content = <ReviewCenter selectedId={query.get("id")} />;
  else if (path === "categories") content = <Categories />;
  else if (path === "settings") content = <SettingsPage />;
  else content = <Archive />;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#/archive" aria-label="CLMS 作文档案馆">
          <Brand />
        </a>
        <nav aria-label="主导航">
          {navigation.map((item) => (
            <a
              key={item.path}
              href={`#/${item.path}`}
              className={active === item.path ? "active" : ""}
              aria-current={active === item.path ? "page" : undefined}
              aria-label={item.title}
              title={item.title}
            >
              <Icon name={item.icon} />
              <span className="nav-label">{item.title}</span>
              {item.path === "reviews" && <PendingReviewBadge route={route} />}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <small className="muted">原稿与每一次修改，都有迹可循。</small>
          <button
            className="quiet"
            aria-label="退出登录"
            title="退出登录"
            onClick={async () => {
              try {
                await api("/auth/logout", {});
                await refreshAuth();
              } catch (reason) {
                setError(errorText(reason));
              }
            }}
          >
            <Icon name="logout" />
            <span className="nav-label">退出登录</span>
          </button>
        </div>
      </aside>
      <main className="main-content" id="main-content">
        <ErrorNotice message={error} />
        {content}
      </main>
    </div>
  );
}
function Login({
  auth,
  onLogin,
}: {
  auth: Auth;
  onLogin: () => Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <main className="auth">
      <form
        className="panel auth-card"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api(auth.initialized ? "/auth/login" : "/auth/bootstrap", {
              username,
              password,
              ...(!auth.initialized ? { bootstrap_token: token } : {}),
            });
            await onLogin();
          } catch (reason) {
            setError(errorText(reason));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="auth-brand">
          <BrandMark className="auth-icon" />
          <span className="eyebrow">CLMS · 作文档案馆</span>
        </div>
        <h1>{auth.initialized ? "欢迎回来" : "建立你的作文档案馆"}</h1>
        <p className="muted">保留原稿，记录评价，回看写作的每一步。</p>
        <Field label="用户名">
          <input
            autoComplete="username"
            autoCapitalize="none"
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </Field>
        <Field
          label="密码"
          hint={!auth.initialized ? "至少 12 个字符。" : undefined}
        >
          <input
            type="password"
            autoComplete={
              auth.initialized ? "current-password" : "new-password"
            }
            minLength={auth.initialized ? 1 : 12}
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>
        {!auth.initialized && (
          <Field label="初始化令牌" hint="从本机初始化命令取得，仅首次使用。">
            <input
              autoComplete="off"
              required
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
          </Field>
        )}
        <ErrorNotice message={error} />
        <button className="primary" disabled={busy}>
          {busy ? "请稍候…" : auth.initialized ? "登录" : "创建管理员"}
        </button>
      </form>
    </main>
  );
}
