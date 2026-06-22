import React, { useEffect, useRef, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Archive,
  BarChart3,
  CheckCircle2,
  Download,
  ExternalLink,
  KeyRound,
  LayoutDashboard,
  Library,
  Link2,
  Loader2,
  LogOut,
  Power,
  RadioTower,
  RefreshCw,
  Save,
  Search,
  Send,
  UserRound,
  UserPlus,
  Users,
  X
} from "lucide-react";
import { api, type ArticleSnapshot, type Assignment, type InventoryResponse, type MatrixCell, type ProjectSummary, type PublicationRecord, type Role, type User, type WritingProject } from "./api";
import "./styles.css";

type View = "dashboard" | "library" | "records" | "log" | "admin";
interface LibraryFocus {
  keyword: string;
  articleType: string;
}

interface AssignmentDraft {
  user_id: string;
  project_id: string;
  keywords: string[];
  article_types: string[];
}

interface AssignmentOptions {
  keywords: string[];
  articleTypes: string[];
}

type ModalState =
  | { type: "article"; article: ArticleSnapshot }
  | { type: "self"; article: ArticleSnapshot }
  | { type: "web"; article: ArticleSnapshot }
  | { type: "complete"; record: PublicationRecord }
  | { type: "editSelf"; record: PublicationRecord }
  | { type: "editWeb"; record: PublicationRecord }
  | { type: "deleteRecord"; record: PublicationRecord }
  | null;

interface Options {
  ai_platforms: string[];
  self_media: string[];
  web_categories: string[];
}

const defaultOptions: Options = { ai_platforms: [], self_media: [], web_categories: [] };
const AUTH_TOKEN_KEY = "publishing_token";

function migrateLegacyAuthToken() {
  if (sessionStorage.getItem(AUTH_TOKEN_KEY)) return;
  const legacyToken = localStorage.getItem(AUTH_TOKEN_KEY);
  if (!legacyToken) return;
  sessionStorage.setItem(AUTH_TOKEN_KEY, legacyToken);
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [view, setView] = useState<View>("dashboard");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [writingProjects, setWritingProjects] = useState<WritingProject[]>([]);
  const [activeProjectId, setActiveProjectId] = useState("");
  const [logProjectId, setLogProjectId] = useState("");
  const [logRecords, setLogRecords] = useState<PublicationRecord[]>([]);
  const [inventory, setInventory] = useState<InventoryResponse | null>(null);
  const [options, setOptions] = useState<Options>(defaultOptions);
  const [users, setUsers] = useState<User[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [modal, setModal] = useState<ModalState>(null);
  const [libraryFocus, setLibraryFocus] = useState<LibraryFocus | null>(null);
  const messageTimerRef = useRef<number | null>(null);

  const isAdmin = user?.role === "admin" || user?.role === "manager";
  const activeProject = projects.find(project => project.project_id === activeProjectId);

  useEffect(() => {
    migrateLegacyAuthToken();
    if (!sessionStorage.getItem(AUTH_TOKEN_KEY)) return;
    void bootstrap();
  }, []);

  useEffect(() => {
    if (!activeProjectId || !user) return;
    void loadInventory(activeProjectId);
  }, [activeProjectId, user?.id]);

  useEffect(() => {
    if (!isAdmin) return;
    if (!projects.length) {
      setLogProjectId("");
      setLogRecords([]);
      return;
    }
    const nextLogProjectId = logProjectId && projects.some(project => project.project_id === logProjectId)
      ? logProjectId
      : activeProjectId || projects[0].project_id;
    if (nextLogProjectId !== logProjectId) {
      setLogProjectId(nextLogProjectId);
    }
  }, [projects, activeProjectId, isAdmin]);

  useEffect(() => {
    if (!isAdmin || view !== "log" || !logProjectId) return;
    void loadLogRecords(logProjectId);
  }, [isAdmin, view, logProjectId]);

  useEffect(() => {
    return () => {
      if (messageTimerRef.current) window.clearTimeout(messageTimerRef.current);
    };
  }, []);

  async function bootstrap() {
    await run(async () => {
      const [{ user: currentUser }, optionResponse] = await Promise.all([api.me(), api.options()]);
      setUser(currentUser);
      setOptions(optionResponse);
      await loadProjects(currentUser);
      if (currentUser.role === "admin" || currentUser.role === "manager") {
        await loadAdminData();
      }
    }, "");
  }

  async function loadProjects(currentUser = user) {
    const response = await api.projects();
    setProjects(response.projects);
    const nextProjectId = activeProjectId && response.projects.some(project => project.project_id === activeProjectId)
      ? activeProjectId
      : response.projects[0]?.project_id || "";
    setActiveProjectId(nextProjectId);
    if (nextProjectId && currentUser) {
      await loadInventory(nextProjectId);
    } else {
      setInventory(null);
    }
  }

  async function loadInventory(projectId = activeProjectId) {
    if (!projectId) return;
    const response = await api.inventory(projectId);
    setInventory(response);
  }

  async function loadLogRecords(projectId: string) {
    await run(async () => {
      const response = await api.projectRecords(projectId);
      setLogRecords(response.records);
    }, "");
  }

  async function loadAdminData() {
    const [userResponse, assignmentResponse] = await Promise.all([api.users(), api.assignments()]);
    setUsers(userResponse.users);
    setAssignments(assignmentResponse.assignments);
    try {
      const writingProjectResponse = await api.writingProjects();
      setWritingProjects(writingProjectResponse.projects);
    } catch (error) {
      setWritingProjects([]);
      throw error;
    }
  }

  function showMessage(text: string) {
    if (messageTimerRef.current) window.clearTimeout(messageTimerRef.current);
    setMessage(text);
    if (!text) return;
    messageTimerRef.current = window.setTimeout(() => {
      setMessage("");
      messageTimerRef.current = null;
    }, 3000);
  }

  async function run(action: () => Promise<string | void>, success: string) {
    setLoading(true);
    showMessage("");
    try {
      const result = await action();
      const nextMessage = typeof result === "string" ? result : success;
      if (nextMessage) showMessage(nextMessage);
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "操作失败。");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogin(username: string, password: string) {
    await run(async () => {
      const result = await api.login({ username, password });
      sessionStorage.setItem(AUTH_TOKEN_KEY, result.token);
      localStorage.removeItem(AUTH_TOKEN_KEY);
      setUser(result.user);
      setOptions(await api.options());
      await loadProjects(result.user);
      if (result.user.role === "admin" || result.user.role === "manager") {
        await loadAdminData();
      }
    }, "登录成功。");
  }

  async function logout() {
    await api.logout().catch(() => undefined);
    sessionStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_TOKEN_KEY);
    setUser(null);
    setProjects([]);
    setWritingProjects([]);
    setLogProjectId("");
    setLogRecords([]);
    setInventory(null);
    setActiveProjectId("");
    setLibraryFocus(null);
  }

  async function refreshAll() {
    await run(async () => {
      await loadProjects();
      if (isAdmin) await loadAdminData();
      if (isAdmin && view === "log" && logProjectId) {
        const response = await api.projectRecords(logProjectId);
        setLogRecords(response.records);
      }
    }, "状态已刷新。");
  }

  async function afterPublication(messageText: string) {
    setModal(null);
    await loadInventory();
    setView("records");
    showMessage(messageText);
  }

  if (!user) {
    return <LoginScreen loading={loading} message={message} onLogin={handleLogin} />;
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img className="sidebar-logo" src="/mindsun-logo.png" alt="思阳集团" />
          <strong className="brand-title">GEO 发布工作台</strong>
          <span className="brand-subtitle">库存发布 · 链接回填 · 消耗统计</span>
        </div>

        <div className="project-card">
          <div className="user-box">
            <strong>{user.display_name}</strong>
            <span>{roleLabel(user.role)}</span>
          </div>

          <label className="project-select">
            <span>当前项目</span>
            <select value={activeProjectId} onChange={event => {
              setActiveProjectId(event.target.value);
              setLibraryFocus(null);
            }}>
              {projects.length ? projects.map(project => (
                <option key={project.project_id} value={project.project_id}>{project.project_name}</option>
              )) : <option value="">暂无已同步项目</option>}
            </select>
          </label>
        </div>

        <div className="section-label">发布流程</div>
        <nav className="nav steps">
          <NavButton active={view === "dashboard"} icon={<LayoutDashboard size={17} />} label="库存看板" desc="整体库存与低库存" onClick={() => setView("dashboard")} />
          <NavButton active={view === "library"} icon={<Library size={17} />} label="文章库" desc="领取定稿发布" onClick={() => {
            setLibraryFocus(null);
            setView("library");
          }} />
          <NavButton active={view === "records"} icon={<Link2 size={17} />} label="发布记录" desc="链接回填与撤销" onClick={() => setView("records")} />
          <NavButton active={view === "log"} icon={<BarChart3 size={17} />} label="工作日志" desc="员工消耗统计" onClick={() => setView("log")} />
          {isAdmin && <NavButton active={view === "admin"} icon={<Users size={17} />} label="管理设置" desc="人员与项目同步" onClick={() => setView("admin")} />}
        </nav>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <span>{activeProject?.project_name || "请选择项目"}</span>
            <strong>{viewTitle(view)}</strong>
          </div>
          <div className="top-actions">
            {loading && <span className="pill"><Loader2 className="spin" size={14} />处理中</span>}
            <button className="btn" onClick={() => void refreshAll()}><RefreshCw size={15} />刷新</button>
            <button className="btn" onClick={() => void logout()}><LogOut size={15} />退出</button>
          </div>
        </header>

        {message && <div className="notice">{message}</div>}

        {!inventory && view !== "admin" ? (
          <EmptyState isAdmin={isAdmin} onAdmin={() => setView("admin")} />
        ) : (
          <>
            {view === "dashboard" && inventory && (
              <Dashboard
                inventory={inventory}
                isAdmin={isAdmin}
                onOpenArticles={(focus) => {
                  setLibraryFocus(focus);
                  setView("library");
                }}
              />
            )}
            {view === "library" && inventory && (
              <ArticleLibrary
                inventory={inventory}
                focus={libraryFocus}
                onClearFocus={() => setLibraryFocus(null)}
                onPreview={article => setModal({ type: "article", article })}
                onSelf={article => setModal({ type: "self", article })}
                onWeb={article => setModal({ type: "web", article })}
              />
            )}
            {view === "records" && inventory && (
              <Records
                records={inventory.records}
                isAdmin={isAdmin}
                currentUser={user}
                onComplete={record => setModal({ type: "complete", record })}
                onEditSelf={record => setModal({ type: "editSelf", record })}
                onEditWeb={record => setModal({ type: "editWeb", record })}
                onDelete={record => setModal({ type: "deleteRecord", record })}
              />
            )}
            {view === "log" && inventory && (
              <WorkLog
                records={isAdmin ? logRecords : inventory.records}
                isAdmin={isAdmin}
                projects={projects}
                projectId={isAdmin ? logProjectId : activeProjectId}
                onProjectChange={projectId => setLogProjectId(projectId)}
              />
            )}
            {view === "admin" && isAdmin && (
              <AdminPanel
                currentUser={user}
                users={users}
                projects={projects}
                writingProjects={writingProjects}
                assignments={assignments}
                run={run}
                reload={async () => {
                  await loadProjects();
                  await loadAdminData();
                }}
              />
            )}
          </>
        )}
      </main>

      {modal?.type === "article" && <ArticleModal article={modal.article} onClose={() => setModal(null)} />}
      {modal?.type === "self" && (
        <SelfPublicationModal
          article={modal.article}
          options={options}
          onClose={() => setModal(null)}
          onSubmit={async payload => {
            await api.createSelf(payload);
            await afterPublication("自媒体发布记录已保存。");
          }}
        />
      )}
      {modal?.type === "web" && (
        <WebPublicationModal
          article={modal.article}
          options={options}
          onClose={() => setModal(null)}
          onSubmit={async payload => {
            await api.createWeb(payload);
            await afterPublication("网媒需求已登记为采购中。");
          }}
        />
      )}
      {modal?.type === "complete" && (
        <CompleteWebModal
          record={modal.record}
          options={options}
          onClose={() => setModal(null)}
          onSubmit={async payload => {
            await api.updatePublication(modal.record.id, payload);
            await afterPublication("网媒发布结果已回填。");
          }}
        />
      )}
      {modal?.type === "editSelf" && (
        <EditSelfPublicationModal
          record={modal.record}
          options={options}
          onClose={() => setModal(null)}
          onSubmit={async payload => {
            await api.updatePublication(modal.record.id, payload);
            await afterPublication("自营发布记录已修改。");
          }}
        />
      )}
      {modal?.type === "editWeb" && (
        <EditWebPublicationModal
          record={modal.record}
          options={options}
          onClose={() => setModal(null)}
          onSubmit={async payload => {
            await api.updatePublication(modal.record.id, payload);
            await afterPublication("网媒发布记录已修改。");
          }}
        />
      )}
      {modal?.type === "deleteRecord" && (
        <DeletePublicationModal
          record={modal.record}
          onClose={() => setModal(null)}
          onConfirm={async () => {
            await api.deletePublication(modal.record.id);
            await afterPublication("发布记录已撤销。");
          }}
        />
      )}
    </div>
  );
}

function LoginScreen({ loading, message, onLogin }: { loading: boolean; message: string; onLogin: (username: string, password: string) => Promise<void> }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  return (
    <div className="login-page">
      <section className="login-card">
        <div className="login-hero">
          <img className="login-logo" src="/mindsun-logo.png" alt="思阳集团" />
          <h1>思阳 GEO 发布工作台</h1>
          <p>员工按负责板块领取定稿文章，完成自媒体发布或网媒采购登记，发布消耗会反馈到撰文系统。</p>
        </div>
        <form className="login-form" autoComplete="off" onSubmit={event => {
          event.preventDefault();
          void onLogin(username, password);
        }}>
          <h2>账号登录</h2>
          <label>用户名<input value={username} placeholder="请输入用户名" autoComplete="off" required onChange={event => setUsername(event.target.value)} /></label>
          <label>密码<input type="password" value={password} placeholder="请输入密码" autoComplete="new-password" required onChange={event => setPassword(event.target.value)} /></label>
          <button className="btn primary" disabled={loading}>{loading ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}进入工作台</button>
          {message && <p className="form-message">{message}</p>}
        </form>
      </section>
    </div>
  );
}

function Dashboard({
  inventory,
  isAdmin,
  onOpenArticles
}: {
  inventory: InventoryResponse;
  isAdmin: boolean;
  onOpenArticles: (focus: LibraryFocus) => void;
}) {
  const lowCells = inventory.matrix.filter(cell => matrixCellRemaining(cell) < 2);
  return (
    <>
      <div className="metrics">
        <Metric label="定稿库存" value={inventory.totals.articles} caption="已同步到发布系统" />
        <Metric label="可使用" value={inventory.totals.available} caption="未发布且未采购中" tone="good" />
        <Metric label="采购中" value={inventory.totals.purchasing} caption="等待网媒回填" tone="warn" />
        <Metric label={isAdmin ? "已发布使用" : "我的已发布"} value={inventory.totals.published} caption={isAdmin ? "计入消耗反馈" : "本人已录入发布"} tone="brand" />
      </div>
      <section className="panel matrix-panel">
        <div className="panel-head">
          <div><h2>关键词 × 文章类型库存</h2><p>{isAdmin ? "按定稿、已使用和采购中统计；当定稿减已使用不足 2 篇时提示补产。" : "按本人可见文章统计定稿、已使用和采购中；当定稿减已使用不足 2 篇时提示补产。"}</p></div>
          <span className="badge warn">{lowCells.length} 个低库存位</span>
        </div>
        <MatrixTable cells={inventory.matrix} onOpenArticles={onOpenArticles} />
      </section>
      <section className="panel signal-panel">
        <div className="panel-head"><div><h2>补产信号</h2><p>定稿减已使用剩余 0 或 1 篇的关键词类型建议回到撰文系统补产。</p></div></div>
        <div className="signal-list">
          {lowCells.length ? lowCells.map(cell => (
            <div className="signal" key={`${cell.keyword}-${cell.article_type}`}>
              <strong>{cell.keyword}</strong>
              <span>{cell.article_type} · 定稿 {cell.total} · 已使用 {cell.published} · 采购中 {cell.purchasing}</span>
            </div>
          )) : <div className="empty-inline">暂无低库存信号</div>}
        </div>
      </section>
    </>
  );
}

function MatrixTable({
  cells,
  onOpenArticles
}: {
  cells: MatrixCell[];
  onOpenArticles: (focus: LibraryFocus) => void;
}) {
  const keywords = unique(cells.map(cell => cell.keyword));
  const types = unique(cells.map(cell => cell.article_type));
  const map = new Map(cells.map(cell => [`${cell.keyword}\u0001${cell.article_type}`, cell]));
  return (
    <div className="table-wrap">
      <table className="matrix">
        <thead><tr><th>关键词</th>{types.map(type => <th key={type}>{type}</th>)}</tr></thead>
        <tbody>
          {keywords.map(keyword => (
            <tr key={keyword}>
              <td className="keyword-cell">{keyword}</td>
              {types.map(type => {
                const cell = map.get(`${keyword}\u0001${type}`);
                return (
                  <td key={type}>
                    {cell ? (
                      <button
                        className={`stock stock-button ${matrixCellTone(cell)}`.trim()}
                        type="button"
                        title={`查看文章库：${keyword} / ${type}`}
                        onClick={() => onOpenArticles({ keyword, articleType: type })}
                      >
                        <strong>{cell.total} 定稿</strong>
                        <span>{cell.published} 已使用 · {cell.purchasing} 采购中</span>
                      </button>
                    ) : <span className="muted">暂无</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function matrixCellRemaining(cell: MatrixCell): number {
  return cell.total - cell.published;
}

function matrixCellTone(cell: MatrixCell): "danger" | "warn" | "" {
  const remaining = matrixCellRemaining(cell);
  if (remaining === 0) return "danger";
  if (remaining < 2) return "warn";
  return "";
}

function ArticleLibrary({
  inventory,
  focus,
  onClearFocus,
  onPreview,
  onSelf,
  onWeb
}: {
  inventory: InventoryResponse;
  focus: LibraryFocus | null;
  onClearFocus: () => void;
  onPreview: (article: ArticleSnapshot) => void;
  onSelf: (article: ArticleSnapshot) => void;
  onWeb: (article: ArticleSnapshot) => void;
}) {
  const [query, setQuery] = useState("");
  const [keywordFilter, setKeywordFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  useEffect(() => {
    if (!focus) return;
    setQuery("");
    setKeywordFilter(focus.keyword);
    setTypeFilter(focus.articleType);
    setStatusFilter("");
  }, [focus]);
  const keywordOptions = unique(inventory.articles.map(article => article.keyword || "未标注关键词"));
  const typeOptions = unique(inventory.articles.map(article => article.article_type || "未标注类型"));
  const statusOptions = unique(inventory.articles.map(article => article.inventory_status || "可使用"));
  const recordsByArticle = groupBy(inventory.records, record => record.article_id);
  const articlesById = new Set(inventory.articles.map(article => article.article_id));
  const usedArticleIds = new Set(
    inventory.records
      .filter(record => articlesById.has(record.article_id) && ["published", "purchasing"].includes(record.order_status))
      .map(record => record.article_id)
  );
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = inventory.articles.filter(article => {
    const articleKeyword = article.keyword || "未标注关键词";
    const articleType = article.article_type || "未标注类型";
    const articleStatus = article.inventory_status || "可使用";
    const articleRecords = recordsByArticle[article.article_id] || [];
    const mediaText = articleRecords.map(record => record.media_name).join("");
    const matchesQuery = !normalizedQuery || `${articleKeyword}${articleType}${article.title}${mediaText}`.toLowerCase().includes(normalizedQuery);
    return matchesQuery
      && (!keywordFilter || articleKeyword === keywordFilter)
      && (!typeFilter || articleType === typeFilter)
      && (!statusFilter || articleStatus === statusFilter);
  });
  const grouped = groupBy(filtered, article => article.keyword || "未标注关键词");
  const hasFilters = Boolean(query || keywordFilter || typeFilter || statusFilter);
  return (
    <div className="library-page">
      <div className="metrics library-metrics">
        <Metric label="文章库存" value={inventory.totals.articles} caption="负责板块全部文章" />
        <Metric label="可使用" value={inventory.totals.available} caption="未发布且未采购中" tone="good" />
        <Metric label="已使用" value={usedArticleIds.size} caption="已发布或已进入采购，仍可重复投放" tone="brand" />
        <Metric label="采购中" value={inventory.totals.purchasing} caption="等待网媒回填处理" tone="warn" />
      </div>

      <div className="panel library-filter-card">
        <div className="panel-body toolbar library-filters">
          <label className="search">
            <Search size={15} />
            <input value={query} placeholder="搜索文章标题、关键词、文章类型或媒体" onChange={event => setQuery(event.target.value)} />
          </label>
          <select className="filter-select" value={keywordFilter} onChange={event => setKeywordFilter(event.target.value)}>
            <option value="">全部关键词</option>
            {keywordOptions.map(keyword => <option key={keyword} value={keyword}>{keyword}</option>)}
          </select>
          <select className="filter-select" value={typeFilter} onChange={event => setTypeFilter(event.target.value)}>
            <option value="">全部文章类型</option>
            {typeOptions.map(type => <option key={type} value={type}>{type}</option>)}
          </select>
          <select className="filter-select compact" value={statusFilter} onChange={event => setStatusFilter(event.target.value)}>
            <option value="">全部状态</option>
            {statusOptions.map(status => <option key={status} value={status}>{status}</option>)}
          </select>
          <button className="btn reset-filter-btn" disabled={!hasFilters} onClick={() => {
            setQuery("");
            setKeywordFilter("");
            setTypeFilter("");
            setStatusFilter("");
            onClearFocus();
          }}><RefreshCw size={15} />重置</button>
          <span className="filter-summary">{filtered.length} / {inventory.articles.length} 篇</span>
        </div>
      </div>

      <div className="library">
        {Object.entries(grouped).map(([keyword, articles], index) => (
          <section className="library-group" key={keyword}>
            <header className="library-group-head">
              <div className="library-group-title">
                <span className="keyword-index">{String(index + 1).padStart(2, "0")}</span>
                <strong>{keyword}</strong>
              </div>
              <div className="library-group-stats">
                <span className="badge">{articles.length} 篇文章</span>
                <span className="badge good">{articles.filter(article => !usedArticleIds.has(article.article_id)).length} 篇可使用</span>
                {articles.some(article => usedArticleIds.has(article.article_id)) && (
                  <span className="badge accent">{articles.filter(article => usedArticleIds.has(article.article_id)).length} 篇已使用</span>
                )}
              </div>
            </header>
            <div className="library-group-body">
            {articles.map(article => (
              <article className={`article-card ${usedArticleIds.has(article.article_id) ? "is-used" : ""}`} key={article.article_id}>
                <div className="article-main">
                  <div className="article-meta">
                    <span className={`badge article-status-badge ${article.inventory_status === "可使用" ? "good" : article.inventory_status === "采购中" ? "warn" : "accent"} status-${article.inventory_status === "可使用" ? "available" : article.inventory_status === "采购中" ? "purchasing" : "used"}`}>{article.inventory_status}</span>
                    <span className="badge article-type-badge">{article.article_type}</span>
                    <span className="channel-inline"><RadioTower size={14} /><strong>建议渠道</strong>{suggestedChannels(article.article_type).join("、")}</span>
                    <button className="icon-btn icon-action article-download" onClick={() => downloadMarkdown(article)} title="下载 Markdown" aria-label="下载 Markdown"><Download size={15} /></button>
                  </div>
                  <button className="article-title" onClick={() => onPreview(article)}>{article.title}</button>
                  <PublishedSites records={recordsByArticle[article.article_id] || []} />
                </div>
                <div className="article-actions">
                  <span className="publish-action-label">继续发布到</span>
                  <div className="publish-actions">
                    <button className="publish-btn" onClick={() => onSelf(article)}><UserRound size={15} />自媒体</button>
                    <button className="publish-btn web" onClick={() => onWeb(article)}><Send size={15} />网媒</button>
                  </div>
                  <span className="repeat-note">{usedArticleIds.has(article.article_id) ? "已发布过，可投放至其他站点" : "选择渠道开始发布"}</span>
                </div>
              </article>
            ))}
            </div>
          </section>
        ))}
        {!filtered.length && <div className="empty-panel">没有符合条件的文章</div>}
      </div>
    </div>
  );
}

function PublishedSites({ records }: { records: PublicationRecord[] }) {
  const visibleRecords = records.filter(record => ["published", "purchasing"].includes(record.order_status));
  if (!visibleRecords.length) return null;
  return (
    <details className="published-sites">
      <summary><ExternalLink size={14} />发布站点与链接（{visibleRecords.length}）</summary>
      <div className="published-sites-list">
        {visibleRecords.map(record => (
          <div className="published-site" key={record.id}>
            <span>{record.media_name || "未填写媒体"} · {recordDateLabel(record)}</span>
            {record.publish_url ? (
              <a href={record.publish_url} target="_blank" rel="noreferrer">查阅链接</a>
            ) : (
              <span className="pending-link">链接待回传</span>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}

function AIPlatformChips({ platforms }: { platforms?: string[] }) {
  const visiblePlatforms = (platforms || []).filter(Boolean);
  if (!visiblePlatforms.length) return <>-</>;
  return (
    <div className="ai-chip-list">
      {visiblePlatforms.map(platform => <span className="ai-chip" key={platform}>{platform}</span>)}
    </div>
  );
}

function Records({
  records,
  isAdmin,
  currentUser,
  onComplete,
  onEditSelf,
  onEditWeb,
  onDelete
}: {
  records: PublicationRecord[];
  isAdmin: boolean;
  currentUser: User;
  onComplete: (record: PublicationRecord) => void;
  onEditSelf: (record: PublicationRecord) => void;
  onEditWeb: (record: PublicationRecord) => void;
  onDelete: (record: PublicationRecord) => void;
}) {
  const [query, setQuery] = useState("");
  const [keywordFilter, setKeywordFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [dateFilter, setDateFilter] = useState("");
  const [employeeFilter, setEmployeeFilter] = useState("");
  const keywordOptions = unique(records.map(record => record.keyword || "未标注关键词"));
  const typeOptions = unique(records.map(record => record.article_type || "未标注类型"));
  const employeeOptions = unique(records.map(record => record.employee_name || "未标注员工"));
  const publishedCount = records.filter(record => record.order_status === "published").length;
  const purchasingCount = records.filter(record => record.order_status === "purchasing").length;
  const selfPublishedCount = records.filter(record => record.order_status === "published" && isSelfChannel(record.channel_type)).length;
  const publishedWebCost = records
    .filter(record => record.order_status === "published" && !isSelfChannel(record.channel_type))
    .reduce((total, record) => total + (Number(record.actual_cost) || 0), 0);
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = records.filter(record => {
    const keyword = record.keyword || "未标注关键词";
    const articleType = record.article_type || "未标注类型";
    const employee = record.employee_name || "未标注员工";
    const recordDate = (record.published_at || record.created_at || "").slice(0, 10);
    const searchable = [
      record.title,
      record.keyword,
      record.article_type,
      record.media_name,
      record.channel_type,
      record.employee_name,
      record.publish_url,
      record.reference_url,
      ...(record.target_ai_platforms || []),
      statusLabel(record.order_status),
    ].join(" ").toLowerCase();
    return (!normalizedQuery || searchable.includes(normalizedQuery))
      && (!keywordFilter || keyword === keywordFilter)
      && (!typeFilter || articleType === typeFilter)
      && (!channelFilter || recordChannelGroup(record) === channelFilter)
      && (!statusFilter || record.order_status === statusFilter)
      && (!dateFilter || recordDate === dateFilter)
      && (!employeeFilter || employee === employeeFilter);
  });
  const grouped = groupBy(filtered, record => `${record.keyword || "未标注关键词"}\u0001${record.article_type || "未标注类型"}`);
  const hasFilters = Boolean(query || keywordFilter || typeFilter || channelFilter || statusFilter || dateFilter || employeeFilter);
  return (
    <div className="records-page">
      <div className="metrics record-metrics">
        <Metric label={isAdmin ? "已发布链接" : "我的已发布链接"} value={publishedCount} caption="一个站点一条记录" />
        <Metric label={isAdmin ? "采购中" : "我的采购中"} value={purchasingCount} caption="等待媒体采购系统回传" tone="warn" />
        <Metric label={isAdmin ? "自营发布" : "我的自营发布"} value={selfPublishedCount} caption={isAdmin ? "员工录入发布链接" : "本人录入发布链接"} tone="good" />
        <Metric label="已发布媒体成本" value={formatMoney(publishedWebCost)} caption="仅发布完成后产生" tone="brand" />
      </div>

      <section className={`record-filter-card ${isAdmin ? "admin-record-filter" : "user-record-filter"}`}>
        <div className="toolbar">
          <label className="search"><Search size={15} /><input value={query} placeholder={isAdmin ? "搜索文章、关键词、媒体或链接" : "搜索我的文章、关键词、媒体或链接"} onChange={event => setQuery(event.target.value)} /></label>
          <select className="filter-select" value={keywordFilter} onChange={event => setKeywordFilter(event.target.value)}>
            <option value="">全部关键词</option>
            {keywordOptions.map(keyword => <option key={keyword} value={keyword}>{keyword}</option>)}
          </select>
          <select className="filter-select" value={typeFilter} onChange={event => setTypeFilter(event.target.value)}>
            <option value="">全部文章类型</option>
            {typeOptions.map(articleType => <option key={articleType} value={articleType}>{articleType}</option>)}
          </select>
          <select className="filter-select" value={channelFilter} onChange={event => setChannelFilter(event.target.value)}>
            <option value="">全部渠道</option>
            <option value="self">自营</option>
            <option value="web">网媒</option>
          </select>
          <select className="filter-select" value={statusFilter} onChange={event => setStatusFilter(event.target.value)}>
            <option value="">全部状态</option>
            <option value="published">已发布</option>
            <option value="purchasing">采购中</option>
          </select>
          <input
            className="filter-select compact filter-date"
            type="date"
            aria-label="选择发布日期"
            value={dateFilter}
            onChange={event => setDateFilter(event.target.value)}
          />
          {isAdmin && (
            <select className="filter-select compact" value={employeeFilter} onChange={event => setEmployeeFilter(event.target.value)}>
              <option value="">全部员工</option>
              {employeeOptions.map(employee => <option key={employee} value={employee}>{employee}</option>)}
            </select>
          )}
          <button className="text-btn reset-filter-btn" aria-hidden={!hasFilters} tabIndex={hasFilters ? 0 : -1} onClick={() => {
            if (!hasFilters) return;
            setQuery("");
            setKeywordFilter("");
            setTypeFilter("");
            setChannelFilter("");
            setStatusFilter("");
            setDateFilter("");
            setEmployeeFilter("");
          }}>重置筛选</button>
          <span className="filter-summary">{filtered.length} / {records.length} 条</span>
        </div>
      </section>

      <div className="record-groups">
        {Object.entries(grouped).map(([groupKey, rows]) => {
          const [keyword, articleType] = groupKey.split("\u0001");
          return (
            <section className="record-group" key={groupKey}>
              <header><strong>{keyword} · {articleType}</strong><span>{rows.length} 条记录</span></header>
              <div className="table-wrap">
                <table className="record-table">
                  <colgroup>
                    <col className="record-col-date" />
                    <col className="record-col-title" />
                    <col className="record-col-channel" />
                    <col className="record-col-media" />
                    <col className="record-col-ai" />
                    <col className="record-col-status" />
                    <col className="record-col-cost" />
                    <col className="record-col-link" />
                    <col className="record-col-action" />
                  </colgroup>
                  <thead><tr><th>日期</th><th>文章</th><th>渠道</th><th>媒体</th><th>关联AI</th><th>状态</th><th>实际成本</th><th>发布链接</th><th>操作</th></tr></thead>
                  <tbody>
                    {rows.map(record => (
                      <tr key={record.id}>
                        <td>{recordDateLabel(record)}</td>
                        <td><strong>{record.title || record.article_id}</strong></td>
                        <td>{record.channel_type || "-"}</td>
                        <td>{record.media_name || "-"}</td>
                        <td><AIPlatformChips platforms={record.target_ai_platforms} /></td>
                        <td><span className={`badge ${record.order_status === "published" ? "good" : "warn"}`}>{statusLabel(record.order_status)}</span></td>
                        <td>{record.actual_cost ? formatMoney(record.actual_cost) : "-"}</td>
                        <td>{record.publish_url ? <a href={record.publish_url} target="_blank" rel="noreferrer">打开链接 <ExternalLink size={12} /></a> : "等待回填"}</td>
                        <td>
                          <RecordActions
                            record={record}
                            isAdmin={isAdmin}
                            currentUser={currentUser}
                            onComplete={onComplete}
                            onEditSelf={onEditSelf}
                            onEditWeb={onEditWeb}
                            onDelete={onDelete}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          );
        })}
        {!records.length && <div className="empty-panel">{isAdmin ? "暂无发布记录" : "暂无我的发布记录"}</div>}
        {Boolean(records.length) && !filtered.length && <div className="empty-panel">{isAdmin ? "没有符合条件的发布记录" : "没有符合条件的我的发布记录"}</div>}
      </div>
    </div>
  );
}

function RecordActions({
  record,
  isAdmin,
  currentUser,
  onComplete,
  onEditSelf,
  onEditWeb,
  onDelete
}: {
  record: PublicationRecord;
  isAdmin: boolean;
  currentUser: User;
  onComplete: (record: PublicationRecord) => void;
  onEditSelf: (record: PublicationRecord) => void;
  onEditWeb: (record: PublicationRecord) => void;
  onDelete: (record: PublicationRecord) => void;
}) {
  const canDelete = isAdmin || record.employee_id === currentUser.id;
  const selfChannel = isSelfChannel(record.channel_type);
  const canEditSelf = selfChannel && canDelete;
  const canEditWeb = isAdmin && !selfChannel && record.order_status === "published";
  const canComplete = isAdmin && !selfChannel && record.order_status === "purchasing";
  if (!canEditSelf && !canEditWeb && !canComplete && !canDelete) return <>-</>;
  return (
    <div className="record-actions">
      {canEditSelf && <button className="text-btn" onClick={() => onEditSelf(record)}>修改</button>}
      {canEditWeb && <button className="text-btn" onClick={() => onEditWeb(record)}>修改</button>}
      {canComplete && <button className="text-btn" onClick={() => onComplete(record)}>回填</button>}
      {canDelete && <button className="text-btn danger" onClick={() => onDelete(record)}>撤销</button>}
    </div>
  );
}

function WorkLog({
  records,
  isAdmin,
  projects,
  projectId,
  onProjectChange
}: {
  records: PublicationRecord[];
  isAdmin: boolean;
  projects: ProjectSummary[];
  projectId: string;
  onProjectChange: (projectId: string) => void;
}) {
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [query, setQuery] = useState("");
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [selectedDay, setSelectedDay] = useState("");
  const selectedProject = projects.find(project => project.project_id === projectId);
  const employeeOptions = unique(records.map(record => record.employee_name || "未标注员工"));
  const normalizedQuery = query.trim().toLowerCase();
  const monthFiltered = records.filter(record => {
    const employee = record.employee_name || "未标注员工";
    const recordDate = recordDateLabel(record);
    const searchable = [
      record.title,
      record.keyword,
      record.article_type,
      record.media_name,
      record.channel_type,
      record.employee_name,
      statusLabel(record.order_status),
    ].join(" ").toLowerCase();
    return (!normalizedQuery || searchable.includes(normalizedQuery))
      && recordDate.startsWith(month)
      && (!employeeFilter || employee === employeeFilter);
  });
  const filtered = selectedDay ? monthFiltered.filter(record => recordDateLabel(record) === selectedDay) : monthFiltered;
  const dayCount = new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0).getDate();
  const dayStats = Array.from({ length: dayCount }, (_, index) => {
    const day = `${month}-${String(index + 1).padStart(2, "0")}`;
    return {
      date: day,
      dayNumber: index + 1,
      count: monthFiltered.filter(record => recordDateLabel(record) === day).length
    };
  });
  const counts = dayStats.map(day => day.count);
  const max = Math.max(...counts, 1);
  const participantCount = unique(filtered.map(record => record.employee_name || "未标注员工")).length;
  const selfPublishedCount = filtered.filter(record => record.order_status === "published" && isSelfChannel(record.channel_type)).length;
  const webPublishedCount = filtered.filter(record => record.order_status === "published" && !isSelfChannel(record.channel_type)).length;
  const hasFilters = Boolean(query || employeeFilter || selectedDay || month !== new Date().toISOString().slice(0, 7));
  return (
    <div className="work-log-page">
      <div className="metrics record-metrics">
        <Metric label={isAdmin ? "发布记录数" : "我的发布记录数"} value={filtered.length} caption="当前筛选下的记录" />
        <Metric label={isAdmin ? "参与员工" : "记录员工"} value={isAdmin ? participantCount : Math.min(participantCount, filtered.length ? 1 : 0)} caption={isAdmin ? "涉及发布或采购的员工" : "仅显示当前账号"} tone="brand" />
        <Metric label={isAdmin ? "自营发布" : "我的自营发布"} value={selfPublishedCount} caption="已发布的自媒体记录" tone="good" />
        <Metric label={isAdmin ? "网媒发布" : "我的网媒发布"} value={webPublishedCount} caption="已发布的网媒记录" tone="warn" />
      </div>

      <section className="record-filter-card">
        <div className="work-log-filters">
          <div className="work-log-filter-row primary">
            <label className="search"><Search size={15} /><input value={query} placeholder={isAdmin ? "搜索文章、关键词、媒体或员工" : "搜索我的文章、关键词或媒体"} onChange={event => setQuery(event.target.value)} /></label>
            {isAdmin && (
              <select className="filter-select project-filter" value={projectId} onChange={event => onProjectChange(event.target.value)}>
                {projects.length ? projects.map(project => (
                  <option key={project.project_id} value={project.project_id}>{project.project_name}</option>
                )) : <option value="">暂无项目</option>}
              </select>
            )}
            <input className="filter-select month-filter" type="month" value={month} onChange={event => {
              setMonth(event.target.value);
              setSelectedDay("");
            }} />
            {isAdmin && (
              <select className="filter-select employee-filter" value={employeeFilter} onChange={event => setEmployeeFilter(event.target.value)}>
                <option value="">全部员工</option>
                {employeeOptions.map(employee => <option key={employee} value={employee}>{employee}</option>)}
              </select>
            )}
            <div className="work-log-filter-actions">
              <span className="filter-summary">{filtered.length} / {records.length} 条</span>
              {hasFilters && (
                <button className="text-btn" onClick={() => {
                  setMonth(new Date().toISOString().slice(0, 7));
                  setQuery("");
                  setEmployeeFilter("");
                  setSelectedDay("");
                }}>重置筛选</button>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div><h2>{isAdmin ? "月度文章发布数量" : "我的月度文章发布数量"}</h2><p>{selectedProject ? `日志项目：${selectedProject.project_name} · ` : ""}根据当前筛选条件统计 {month} 的工作量。</p></div>
        </div>
        <div className="month-chart">
          {dayStats.map(day => (
            <button
              className={`day ${selectedDay === day.date ? "is-selected" : ""}`}
              key={day.date}
              type="button"
              aria-pressed={selectedDay === day.date}
              aria-label={`${day.dayNumber} 日发布 ${day.count} 篇，点击查看当天明细`}
              onClick={() => setSelectedDay(current => current === day.date ? "" : day.date)}
            >
              <div className="day-bar">
                <span style={{ height: `${(day.count / max) * 100}%` }} />
                <em>{Number(month.slice(5, 7))}月{day.dayNumber}日 · {day.count} 篇发布</em>
              </div>
              <small>{day.dayNumber}</small>
            </button>
          ))}
        </div>
      </section>

      <section className="record-group">
        <header>
          <div className="record-group-title">
            <strong>{isAdmin ? "工作日志明细" : "我的工作日志明细"}</strong>
            {selectedDay && <small>已筛选：{selectedDay}</small>}
          </div>
          <div className="record-group-actions">
            {selectedDay && <button className="text-btn" type="button" onClick={() => setSelectedDay("")}>清除日期</button>}
            <span>{filtered.length} 条记录</span>
          </div>
        </header>
        <div className="table-wrap work-log-table-wrap">
          {filtered.length ? <table className="record-table work-log-table">
            <colgroup>
              <col className="log-col-date" />
              <col className="log-col-employee" />
              <col className="log-col-title" />
              <col className="log-col-keyword" />
              <col className="log-col-type" />
              <col className="log-col-channel" />
              <col className="log-col-media" />
              <col className="log-col-status" />
            </colgroup>
            <thead><tr><th>日期</th><th>员工</th><th>文章</th><th>关键词</th><th>文章类型</th><th>渠道</th><th>媒体</th><th>状态</th></tr></thead>
            <tbody>
              {filtered.map(record => (
                <tr key={record.id}>
                  <td>{recordDateLabel(record)}</td>
                  <td>{record.employee_name || "未标注员工"}</td>
                  <td><strong>{record.title || record.article_id}</strong></td>
                  <td>{record.keyword || "未标注关键词"}</td>
                  <td>{record.article_type || "未标注类型"}</td>
                  <td>{record.channel_type || "-"}</td>
                  <td>{record.media_name || "-"}</td>
                  <td><span className={`badge ${record.order_status === "published" ? "good" : "warn"}`}>{statusLabel(record.order_status)}</span></td>
                </tr>
              ))}
            </tbody>
          </table> : null}
        </div>
        {!records.length && <div className="empty-panel">{isAdmin ? "暂无工作日志记录" : "暂无我的工作日志记录"}</div>}
        {Boolean(records.length) && !filtered.length && <div className="empty-panel">{isAdmin ? "没有符合条件的工作日志" : "没有符合条件的我的工作日志"}</div>}
      </section>
    </div>
  );
}

function AdminPanel({
  currentUser,
  users,
  projects,
  writingProjects,
  assignments,
  run,
  reload
}: {
  currentUser: User;
  users: User[];
  projects: ProjectSummary[];
  writingProjects: WritingProject[];
  assignments: Assignment[];
  run: (action: () => Promise<string | void>, success: string) => Promise<void>;
  reload: () => Promise<void>;
}) {
  const [syncProjectId, setSyncProjectId] = useState(writingProjects[0]?.id || "");
  const [newUser, setNewUser] = useState<{ username: string; password: string; display_name: string; role: Role }>({ username: "", password: "", display_name: "", role: "employee" });
  const [showCreateUser, setShowCreateUser] = useState(false);
  const [assignment, setAssignment] = useState<AssignmentDraft>({ user_id: "", project_id: projects[0]?.project_id || "", keywords: [], article_types: [] });
  const [assignmentOptions, setAssignmentOptions] = useState<AssignmentOptions>({ keywords: [], articleTypes: [] });
  const [assignmentOptionsLoading, setAssignmentOptionsLoading] = useState(false);
  const [assignmentOptionsError, setAssignmentOptionsError] = useState("");
  const selectedWritingProject = writingProjects.find(project => project.id === syncProjectId);
  const syncedProjectById = new Map(projects.map(project => [project.project_id, project]));
  const syncedProjectNameById = new Map(projects.map(project => [project.project_id, project.project_name]));
  const selectedSyncedProject = selectedWritingProject ? syncedProjectById.get(selectedWritingProject.id) : undefined;
  const userById = new Map(users.map(item => [item.id, item]));

  useEffect(() => {
    if (!syncProjectId && writingProjects[0]) setSyncProjectId(writingProjects[0].id);
  }, [writingProjects]);

  useEffect(() => {
    if (!assignment.project_id && projects[0]) setAssignment(current => ({ ...current, project_id: projects[0].project_id }));
  }, [projects]);

  useEffect(() => {
    if (!assignment.project_id) {
      setAssignmentOptions({ keywords: [], articleTypes: [] });
      setAssignmentOptionsError("");
      return;
    }
    let cancelled = false;
    setAssignmentOptions({ keywords: [], articleTypes: [] });
    setAssignmentOptionsLoading(true);
    setAssignmentOptionsError("");
    void api.inventory(assignment.project_id)
      .then(response => {
        if (cancelled) return;
        setAssignmentOptions({
          keywords: unique(response.articles.map(article => article.keyword || "未标注关键词")),
          articleTypes: unique(response.articles.map(article => article.article_type || "未标注类型"))
        });
      })
      .catch(error => {
        if (cancelled) return;
        setAssignmentOptions({ keywords: [], articleTypes: [] });
        setAssignmentOptionsError(error instanceof Error ? error.message : "候选项加载失败，可手动输入。");
      })
      .finally(() => {
        if (!cancelled) setAssignmentOptionsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [assignment.project_id]);

  return (
    <div className="admin-grid">
      <section className="panel wide">
        <div className="panel-head">
          <div><h2>同步撰文项目</h2><p>选择撰文系统项目，拉取已审核定稿文章；已同步项目每 10 分钟自动同步一次。</p></div>
          <span className="badge accent">自动同步 10 分钟</span>
        </div>
        <div className="sync-project-box">
          <select value={syncProjectId} onChange={event => setSyncProjectId(event.target.value)}>
            {!writingProjects.length && <option value="">暂无可选撰文项目</option>}
            {writingProjects.map(project => (
              <option key={project.id} value={project.id}>
                {project.name} · {shortDate(project.updated_at)} · {project.synced ? "已同步" : "未同步"}
              </option>
            ))}
          </select>
          {selectedWritingProject ? (
            <div className="project-hint">
              <div>
                <strong>{selectedWritingProject.name}</strong>
                <span>ID: {selectedWritingProject.id}</span>
                <em>{selectedWritingProject.synced ? "已同步过库存" : "尚未同步库存"}</em>
              </div>
              <div className="sync-time">
                <span>上次同步时间</span>
                <strong>{selectedSyncedProject?.synced_at ? shortDate(selectedSyncedProject.synced_at) : "暂无同步记录"}</strong>
              </div>
              <button className="btn primary admin-action-btn sync-action-btn" onClick={() => void run(async () => {
                if (!syncProjectId) throw new Error("请选择要同步的撰文项目。");
                const response = await api.syncProject(syncProjectId);
                await reload();
                return response.message;
              }, "项目库存已同步。")}><RefreshCw size={15} />同步</button>
            </div>
          ) : <div className="empty-inline">未读取到撰文项目，请确认撰文后端已启动。</div>}
        </div>
      </section>

      <section className="panel wide">
        <div className="panel-head">
          <div><h2>员工管理</h2><p>维护姓名、角色、状态和登录密码。</p></div>
          <button className="btn primary admin-action-btn" onClick={() => {
            setNewUser({ username: "", password: "", display_name: "", role: "employee" });
            setShowCreateUser(true);
          }}><UserPlus size={15} />创建账号</button>
        </div>
        <UserManagementTable currentUser={currentUser} users={users} run={run} reload={reload} />
      </section>

      <section className="panel wide">
        <div className="panel-head"><div><h2>项目板块分配</h2><p>关键词和文章类型留空表示该项目内全部可见。</p></div></div>
        <div className="assignment-grid">
          <select value={assignment.user_id} onChange={event => setAssignment({ ...assignment, user_id: event.target.value })}>
            <option value="">选择员工</option>
            {users.filter(item => item.role === "employee" && item.active).map(item => <option key={item.id} value={item.id}>{item.display_name}</option>)}
          </select>
          <select value={assignment.project_id} onChange={event => setAssignment({ ...assignment, project_id: event.target.value })}>
            <option value="">选择已同步项目</option>
            {projects.map(project => <option key={project.project_id} value={project.project_id}>{project.project_name}</option>)}
          </select>
          <MultiValueInput
            value={assignment.keywords}
            options={assignmentOptions.keywords}
            placeholder={assignmentOptionsLoading ? "正在加载关键词候选..." : "选择或输入关键词"}
            emptyText={assignment.project_id ? "暂无关键词候选，可手动输入" : "请先选择项目"}
            onChange={keywords => setAssignment({ ...assignment, keywords })}
          />
          <MultiValueInput
            value={assignment.article_types}
            options={assignmentOptions.articleTypes}
            placeholder={assignmentOptionsLoading ? "正在加载文章类型候选..." : "选择或输入文章类型"}
            emptyText={assignment.project_id ? "暂无文章类型候选，可手动输入" : "请先选择项目"}
            onChange={articleTypes => setAssignment({ ...assignment, article_types: articleTypes })}
          />
          <button className="btn primary admin-action-btn" onClick={() => void run(async () => {
            await api.createAssignment({
              user_id: assignment.user_id,
              project_id: assignment.project_id,
              keywords: assignment.keywords,
              article_types: assignment.article_types
            });
            setAssignment({ ...assignment, keywords: [], article_types: [] });
            await reload();
          }, "负责板块已分配。")}>保存分配</button>
        </div>
        {assignmentOptionsError && <div className="assignment-options-error">{assignmentOptionsError}</div>}
        <div className="table-wrap">
          <table>
            <thead><tr><th>员工</th><th>项目</th><th>关键词</th><th>文章类型</th><th>操作</th></tr></thead>
            <tbody>{assignments.map(item => (
              <tr key={item.id}>
                <td>{item.display_name || item.username}<small>{userById.get(item.user_id)?.active === false ? "已停用" : roleLabel(userById.get(item.user_id)?.role || "employee")}</small></td>
                <td><strong>{syncedProjectNameById.get(item.project_id) || item.project_id}</strong><small>ID: {item.project_id}</small></td>
                <td>{item.keywords.length ? item.keywords.join("、") : "全部"}</td>
                <td>{item.article_types.length ? item.article_types.join("、") : "全部"}</td>
                <td><button className="text-btn" onClick={() => void run(async () => { await api.deleteAssignment(item.id); await reload(); }, "分配已删除。")}>删除</button></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
      {showCreateUser && (
        <CreateUserModal
          value={newUser}
          onChange={setNewUser}
          onClose={() => setShowCreateUser(false)}
          onSubmit={async () => {
            await api.createUser(newUser);
            setNewUser({ username: "", password: "", display_name: "", role: "employee" });
            setShowCreateUser(false);
            await reload();
          }}
          run={run}
        />
      )}
    </div>
  );
}

function MultiValueInput({
  value,
  options,
  placeholder,
  emptyText,
  onChange
}: {
  value: string[];
  options: string[];
  placeholder: string;
  emptyText: string;
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const selected = new Set(value);

  function addItems(raw: string) {
    const items = splitList(raw);
    if (!items.length) return;
    onChange(unique([...value, ...items]));
    setDraft("");
  }

  function removeItem(target: string) {
    onChange(value.filter(item => item !== target));
  }

  function toggleOption(option: string) {
    if (selected.has(option)) {
      removeItem(option);
      return;
    }
    onChange(unique([...value, option]));
    setDraft("");
  }

  return (
    <div
      className={`multi-value-input ${open ? "is-open" : ""}`}
      onBlur={event => {
        const nextTarget = event.relatedTarget as Node | null;
        if (nextTarget && event.currentTarget.contains(nextTarget)) return;
        addItems(draft);
        setOpen(false);
      }}
    >
      <div className="multi-value-box" onClick={() => {
        setOpen(true);
        inputRef.current?.focus();
      }}>
        {value.map(item => (
          <button className="multi-value-tag" type="button" key={item} onClick={() => removeItem(item)} title="点击移除">
            <span>{item}</span>
            <X size={12} />
          </button>
        ))}
        <input
          ref={inputRef}
          value={draft}
          placeholder={value.length ? "继续输入" : placeholder}
          onChange={event => setDraft(event.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={event => {
            if (["Enter", ",", "，"].includes(event.key)) {
              event.preventDefault();
              addItems(draft);
            }
            if (event.key === "Backspace" && !draft && value.length) {
              removeItem(value[value.length - 1]);
            }
          }}
          onPaste={event => {
            const text = event.clipboardData.getData("text");
            if (!/[,\n，、]/.test(text)) return;
            event.preventDefault();
            addItems(text);
          }}
        />
      </div>
      {open && (
        <div className="multi-value-dropdown">
          {options.length ? options.map(option => {
            const checked = selected.has(option);
            return (
              <button
                type="button"
                className={`multi-value-option ${checked ? "is-selected" : ""}`}
                key={option}
                onMouseDown={event => event.preventDefault()}
                onClick={() => toggleOption(option)}
                role="checkbox"
                aria-checked={checked}
              >
                <span className="multi-value-check">{checked && <CheckCircle2 size={13} />}</span>
                <span>{option}</span>
              </button>
            );
          }) : <span className="multi-value-empty">{emptyText}</span>}
        </div>
      )}
    </div>
  );
}

function CreateUserModal({
  value,
  onChange,
  onClose,
  onSubmit,
  run
}: {
  value: { username: string; password: string; display_name: string; role: Role };
  onChange: (value: { username: string; password: string; display_name: string; role: Role }) => void;
  onClose: () => void;
  onSubmit: () => Promise<void>;
  run: (action: () => Promise<string | void>, success: string) => Promise<void>;
}) {
  return (
    <Modal title="创建员工账号" subtitle="填写账号信息后，员工即可使用该账号登录发布工作台。" onClose={onClose}>
      <FormInput label="用户名" value={value.username} placeholder="请输入用户名" required onChange={username => onChange({ ...value, username })} />
      <FormInput label="姓名" value={value.display_name} placeholder="请输入员工姓名" required onChange={display_name => onChange({ ...value, display_name })} />
      <FormInput label="初始密码" type="password" value={value.password} placeholder="至少 6 位" required onChange={password => onChange({ ...value, password })} />
      <label className="field">
        <span>角色</span>
        <select value={value.role} onChange={event => onChange({ ...value, role: event.target.value as Role })}>
          <option value="employee">媒介员工</option>
          <option value="manager">内容负责人</option>
          <option value="admin">管理员</option>
        </select>
      </label>
      <div className="modal-actions sticky">
        <button className="btn" onClick={onClose}>取消</button>
        <button className="btn primary" onClick={() => void run(onSubmit, "员工账号已创建。")}><UserPlus size={15} />创建账号</button>
      </div>
    </Modal>
  );
}

function UserManagementTable({
  currentUser,
  users,
  run,
  reload
}: {
  currentUser: User;
  users: User[];
  run: (action: () => Promise<string | void>, success: string) => Promise<void>;
  reload: () => Promise<void>;
}) {
  const [drafts, setDrafts] = useState<Record<string, { display_name: string; role: Role }>>({});
  const [resetUserId, setResetUserId] = useState("");
  const [resetPassword, setResetPassword] = useState("");

  useEffect(() => {
    setDrafts(Object.fromEntries(users.map(item => [item.id, { display_name: item.display_name, role: item.role }])));
  }, [users]);

  function updateDraft(userId: string, patch: Partial<{ display_name: string; role: Role }>) {
    setDrafts(current => ({ ...current, [userId]: { ...(current[userId] || { display_name: "", role: "employee" }), ...patch } }));
  }

  return (
    <div className="user-management">
      <div className="table-wrap">
        <table className="user-table">
          <thead><tr><th>用户名</th><th>姓名</th><th>角色</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
          <tbody>
            {users.map(item => {
              const draft = drafts[item.id] || { display_name: item.display_name, role: item.role };
              const isSelf = item.id === currentUser.id;
              const profileChanged = draft.display_name !== item.display_name;
              const roleChanged = !isSelf && draft.role !== item.role;
              const changed = profileChanged || roleChanged;
              return (
                <tr key={item.id} className={!item.active ? "inactive-row" : ""}>
                  <td><strong>{item.username}</strong>{isSelf && <small>当前登录账号</small>}</td>
                  <td>
                    <input
                      className="table-input"
                      value={draft.display_name}
                      onChange={event => updateDraft(item.id, { display_name: event.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      className="table-select"
                      value={isSelf ? item.role : draft.role}
                      disabled={isSelf}
                      title={isSelf ? "不可修改当前登录账号的角色" : undefined}
                      onChange={event => updateDraft(item.id, { role: event.target.value as Role })}
                    >
                      <option value="employee">媒介员工</option>
                      <option value="manager">内容负责人</option>
                      <option value="admin">管理员</option>
                    </select>
                    {isSelf && <small>不可修改自己的角色</small>}
                  </td>
                  <td><span className={`badge ${item.active ? "good" : "warn"}`}>{item.active ? "启用中" : "已停用"}</span></td>
                  <td>{shortDate(item.created_at)}</td>
                  <td>
                    <div className="row-actions">
                      <button className="text-btn" disabled={!changed} onClick={() => void run(async () => {
                        await api.updateUser(item.id, isSelf ? { display_name: draft.display_name } : { display_name: draft.display_name, role: draft.role });
                        await reload();
                      }, "账号资料已更新。")}><Save size={13} />保存资料</button>
                      {item.active ? (
                        <button
                          className="text-btn danger"
                          disabled={isSelf}
                          title={isSelf ? "不可停用自己" : "停用后该员工不能登录"}
                          onClick={() => void run(async () => {
                            await api.updateUser(item.id, { active: false });
                            await reload();
                          }, "账号已停用。")}
                        ><Power size={13} />{isSelf ? "不可停用自己" : "停用"}</button>
                      ) : (
                        <button className="text-btn" onClick={() => void run(async () => {
                          await api.updateUser(item.id, { active: true });
                          await reload();
                        }, "账号已启用。")}><Power size={13} />启用</button>
                      )}
                      <button className="text-btn" onClick={() => {
                        setResetUserId(resetUserId === item.id ? "" : item.id);
                        setResetPassword("");
                      }}><KeyRound size={13} />重设密码</button>
                    </div>
                    {resetUserId === item.id && (
                      <div className="reset-inline">
                        <input
                          type="password"
                          value={resetPassword}
                          placeholder="新密码至少 6 位"
                          onChange={event => setResetPassword(event.target.value)}
                        />
                        <button className="btn primary" onClick={() => void run(async () => {
                          if (resetPassword.length < 6) throw new Error("密码至少 6 位。");
                          await api.updateUser(item.id, { password: resetPassword });
                          setResetUserId("");
                          setResetPassword("");
                          if (isSelf) {
                            sessionStorage.removeItem(AUTH_TOKEN_KEY);
                            localStorage.removeItem(AUTH_TOKEN_KEY);
                            window.location.reload();
                            return "密码已重设，请重新登录。";
                          }
                          await reload();
                          return "密码已重设，员工需要重新登录。";
                        }, "")}>保存</button>
                        <button className="btn" onClick={() => {
                          setResetUserId("");
                          setResetPassword("");
                        }}>取消</button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!users.length && <div className="empty-inline">暂无员工账号</div>}
    </div>
  );
}

function ArticleModal({ article, onClose }: { article: ArticleSnapshot; onClose: () => void }) {
  return (
    <Modal title="文章预览" subtitle={`${article.keyword} · ${article.article_type}`} onClose={onClose}>
      <pre className="markdown">{article.markdown}</pre>
    </Modal>
  );
}

function SelfPublicationModal({ article, options, onClose, onSubmit }: { article: ArticleSnapshot; options: Options; onClose: () => void; onSubmit: (payload: Record<string, unknown>) => Promise<void> }) {
  const [mediaName, setMediaName] = useState(options.self_media[0] || "");
  const [publishUrl, setPublishUrl] = useState("");
  const [publishedAt, setPublishedAt] = useState(new Date().toISOString().slice(0, 10));
  const [ai, setAi] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  async function submit() {
    setError("");
    setSubmitting(true);
    try {
      await onSubmit({ article_id: article.article_id, media_name: mediaName, target_ai_platforms: ai, publish_url: publishUrl, published_at: publishedAt });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "保存失败。");
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <Modal title="选择自媒体并录入发布结果" subtitle={article.title} onClose={onClose}>
      {error && <div className="modal-error">{error}</div>}
      <SectionTitle title="选择自营账号平台" />
      <RadioCardGrid options={options.self_media} value={mediaName} onChange={setMediaName} meta="自营" />
      <SectionTitle title="关联优化 AI 平台" />
      <CheckboxCardGrid options={options.ai_platforms} value={ai} onChange={setAi} />
      <SectionTitle title="录入发布结果" />
      <FormInput label="自媒体发布链接" value={publishUrl} onChange={setPublishUrl} placeholder="https://..." required />
      <FormInput label="发布日期" type="date" value={publishedAt} onChange={setPublishedAt} />
      <div className="modal-actions sticky">
        <button className="btn" onClick={onClose}>取消</button>
        <button className="btn primary" disabled={submitting} onClick={() => void submit()}>{submitting ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}保存自营发布记录</button>
      </div>
    </Modal>
  );
}

function WebPublicationModal({ article, options, onClose, onSubmit }: { article: ArticleSnapshot; options: Options; onClose: () => void; onSubmit: (payload: Record<string, unknown>) => Promise<void> }) {
  const [mediaCategory, setMediaCategory] = useState(options.web_categories[0] || "");
  const [mediaName, setMediaName] = useState("");
  const [publisher, setPublisher] = useState("");
  const [referenceUrl, setReferenceUrl] = useState("");
  const [ai, setAi] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  async function submit() {
    setError("");
    setSubmitting(true);
    try {
      await onSubmit({ article_id: article.article_id, media_category: mediaCategory, media_name: mediaName, publisher, reference_url: referenceUrl, target_ai_platforms: ai, note });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "发送失败。");
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <Modal title="登记网媒采购需求" subtitle={article.title} onClose={onClose}>
      {error && <div className="modal-error">{error}</div>}
      <div className="flow-note">网媒记录会先进入采购中；实际媒体、成本和发布链接由管理员回填后才计入发布量。</div>
      <FormSelect label="媒体分类" value={mediaCategory} onChange={setMediaCategory} options={options.web_categories} />
      <FormInput label="发布渠道" value={mediaName} onChange={setMediaName} placeholder="例如：家居行业垂直媒体" />
      <FormInput label="发稿方" value={publisher} onChange={setPublisher} placeholder="例如：供应商或发稿联系人" />
      <FormInput label="参考链接" value={referenceUrl} onChange={setReferenceUrl} placeholder="https://..." />
      <SectionTitle title="关联 AI 平台" />
      <CheckboxCardGrid options={options.ai_platforms} value={ai} onChange={setAi} />
      <FormInput label="备注" value={note} onChange={setNote} placeholder="可选" />
      <div className="modal-actions sticky">
        <button className="btn" onClick={onClose}>取消</button>
        <button className="btn primary" disabled={submitting} onClick={() => void submit()}>{submitting ? <Loader2 className="spin" size={15} /> : <Send size={15} />}发送采购</button>
      </div>
    </Modal>
  );
}

function CompleteWebModal({ record, options, onClose, onSubmit }: { record: PublicationRecord; options: Options; onClose: () => void; onSubmit: (payload: Record<string, unknown>) => Promise<void> }) {
  const [mediaName, setMediaName] = useState(record.media_name.replace(/^待采购确认：/, ""));
  const [publishUrl, setPublishUrl] = useState("");
  const [actualCost, setActualCost] = useState("0");
  const [orderId, setOrderId] = useState("");
  const [ai, setAi] = useState<string[]>(record.target_ai_platforms || []);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  async function submit() {
    setError("");
    setSubmitting(true);
    try {
      await onSubmit({ media_name: mediaName, publish_url: publishUrl, actual_cost: Number(actualCost), order_id: orderId, target_ai_platforms: ai, order_status: "published" });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "回填失败。");
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <Modal title="回填网媒发布结果" subtitle={record.title || record.article_id} onClose={onClose}>
      {error && <div className="modal-error">{error}</div>}
      <FormInput label="实际媒体名称" value={mediaName} onChange={setMediaName} />
      <FormInput label="发布链接" value={publishUrl} onChange={setPublishUrl} placeholder="https://..." />
      <FormInput label="实际成本" value={actualCost} onChange={setActualCost} placeholder="0" />
      <FormInput label="订单号" value={orderId} onChange={setOrderId} placeholder="可选" />
      <SectionTitle title="关联 AI 平台" />
      <CheckboxCardGrid options={options.ai_platforms} value={ai} onChange={setAi} />
      <div className="modal-actions">
        <button className="btn" onClick={onClose}>取消</button>
        <button className="btn primary" disabled={submitting} onClick={() => void submit()}>{submitting ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}确认发布</button>
      </div>
    </Modal>
  );
}

function EditSelfPublicationModal({
  record,
  options,
  onClose,
  onSubmit
}: {
  record: PublicationRecord;
  options: Options;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const [mediaName, setMediaName] = useState(record.media_name || options.self_media[0] || "");
  const [publishUrl, setPublishUrl] = useState(record.publish_url || "");
  const [publishedAt, setPublishedAt] = useState((record.published_at || record.created_at || new Date().toISOString()).slice(0, 10));
  const [ai, setAi] = useState<string[]>(record.target_ai_platforms || []);
  const [note, setNote] = useState(record.note || "");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  async function submit() {
    setError("");
    setSubmitting(true);
    try {
      await onSubmit({ media_name: mediaName, publish_url: publishUrl, published_at: publishedAt, target_ai_platforms: ai, note });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "修改失败。");
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <Modal title="修改自营发布记录" subtitle={record.title || record.article_id} onClose={onClose}>
      {error && <div className="modal-error">{error}</div>}
      <SectionTitle title="自营发布信息" />
      <RadioCardGrid options={options.self_media} value={mediaName} onChange={setMediaName} meta="自营" />
      <SectionTitle title="关联优化 AI 平台" />
      <CheckboxCardGrid options={options.ai_platforms} value={ai} onChange={setAi} />
      <FormInput label="发布链接" value={publishUrl} onChange={setPublishUrl} placeholder="https://..." required />
      <FormInput label="发布日期" type="date" value={publishedAt} onChange={setPublishedAt} />
      <FormInput label="备注" value={note} onChange={setNote} placeholder="可选" />
      <div className="modal-actions sticky">
        <button className="btn" onClick={onClose}>取消</button>
        <button className="btn primary" disabled={submitting} onClick={() => void submit()}>{submitting ? <Loader2 className="spin" size={15} /> : <Save size={15} />}保存修改</button>
      </div>
    </Modal>
  );
}

function EditWebPublicationModal({
  record,
  options,
  onClose,
  onSubmit
}: {
  record: PublicationRecord;
  options: Options;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const [mediaName, setMediaName] = useState(record.media_name || "");
  const [publishUrl, setPublishUrl] = useState(record.publish_url || "");
  const [actualCost, setActualCost] = useState(String(record.actual_cost || 0));
  const [orderId, setOrderId] = useState(record.order_id || "");
  const [publishedAt, setPublishedAt] = useState((record.published_at || record.created_at || new Date().toISOString()).slice(0, 10));
  const [ai, setAi] = useState<string[]>(record.target_ai_platforms || []);
  const [note, setNote] = useState(record.note || "");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  async function submit() {
    setError("");
    setSubmitting(true);
    try {
      await onSubmit({
        media_name: mediaName,
        publish_url: publishUrl,
        actual_cost: Number(actualCost),
        order_id: orderId,
        published_at: publishedAt,
        target_ai_platforms: ai,
        note,
        order_status: "published"
      });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "修改失败。");
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <Modal title="修改网媒发布记录" subtitle={record.title || record.article_id} onClose={onClose}>
      {error && <div className="modal-error">{error}</div>}
      <SectionTitle title="网媒发布信息" />
      <FormInput label="实际媒体名称" value={mediaName} onChange={setMediaName} required />
      <FormInput label="发布链接" value={publishUrl} onChange={setPublishUrl} placeholder="https://..." required />
      <FormInput label="实际成本" value={actualCost} onChange={setActualCost} placeholder="0" />
      <FormInput label="订单号" value={orderId} onChange={setOrderId} placeholder="可选" />
      <FormInput label="发布日期" type="date" value={publishedAt} onChange={setPublishedAt} />
      <SectionTitle title="关联 AI 平台" />
      <CheckboxCardGrid options={options.ai_platforms} value={ai} onChange={setAi} />
      <FormInput label="备注" value={note} onChange={setNote} placeholder="可选" />
      <div className="modal-actions sticky">
        <button className="btn" onClick={onClose}>取消</button>
        <button className="btn primary" disabled={submitting} onClick={() => void submit()}>{submitting ? <Loader2 className="spin" size={15} /> : <Save size={15} />}保存修改</button>
      </div>
    </Modal>
  );
}

function DeletePublicationModal({
  record,
  onClose,
  onConfirm
}: {
  record: PublicationRecord;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  async function submit() {
    setError("");
    setSubmitting(true);
    try {
      await onConfirm();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "撤销失败。");
      setSubmitting(false);
    }
  }
  return (
    <Modal title="确认撤销发布记录？" subtitle={record.title || record.article_id} onClose={onClose}>
      {error && <div className="modal-error">{error}</div>}
      <div className="confirm-summary">
        <strong>{record.media_name || "-"}</strong>
        <span>{record.channel_type || "-"} · {statusLabel(record.order_status)} · {recordDateLabel(record)}</span>
        {record.publish_url && <small>{record.publish_url}</small>}
      </div>
      <p className="danger-note">撤销后会删除这条发布记录，文章库存统计会重新计算。此操作不能在页面内恢复。</p>
      <div className="modal-actions">
        <button className="btn" disabled={submitting} onClick={onClose}>取消</button>
        <button className="btn danger" disabled={submitting} onClick={() => void submit()}>{submitting ? <Loader2 className="spin" size={15} /> : <X size={15} />}确认撤销</button>
      </div>
    </Modal>
  );
}

function Modal({ title, subtitle, children, onClose }: { title: string; subtitle?: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="modal-bg">
      <section className="modal">
        <header>
          <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </header>
        <div className="modal-body">{children}</div>
      </section>
    </div>
  );
}

function FormInput({ label, value, onChange, placeholder = "", type = "text", required = false }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string; required?: boolean }) {
  return <label className="field"><span>{label}{required && <em>*</em>}</span><input type={type} value={value} placeholder={placeholder} onChange={event => onChange(event.target.value)} /></label>;
}

function FormSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: string[] }) {
  return <label className="field"><span>{label}</span><select value={value} onChange={event => onChange(event.target.value)}>{options.map(option => <option key={option}>{option}</option>)}</select></label>;
}

function SectionTitle({ title }: { title: string }) {
  return <h3 className="drawer-section-title">{title}</h3>;
}

function RadioCardGrid({ options, value, onChange, meta }: { options: string[]; value: string; onChange: (value: string) => void; meta?: string }) {
  return (
    <div className="choice-grid">
      {options.map(option => (
        <label className={`choice-card ${value === option ? "selected" : ""}`} key={option}>
          <input type="radio" checked={value === option} onChange={() => onChange(option)} />
          <span>{option}</span>
          {meta && <em>{meta}</em>}
        </label>
      ))}
    </div>
  );
}

function CheckboxCardGrid({ options, value, onChange }: { options: string[]; value: string[]; onChange: (value: string[]) => void }) {
  return (
    <div className="choice-grid">
      {options.map(option => {
        const checked = value.includes(option);
        return (
          <label className={`choice-card ${checked ? "selected" : ""}`} key={option}>
            <input type="checkbox" checked={checked} onChange={() => onChange(checked ? value.filter(item => item !== option) : [...value, option])} />
            <span>{option}</span>
          </label>
        );
      })}
    </div>
  );
}

function NavButton({ active, icon, label, desc, onClick }: { active: boolean; icon: React.ReactNode; label: string; desc: string; onClick: () => void }) {
  return (
    <button className={active ? "active" : ""} onClick={onClick}>
      {icon}
      <span><strong>{label}</strong><small>{desc}</small></span>
    </button>
  );
}

function Metric({ label, value, caption, tone = "" }: { label: string; value: number | string; caption: string; tone?: string }) {
  return <div className={`metric ${tone}`}><span>{label}</span><strong>{value}</strong><small>{caption}</small></div>;
}

function EmptyState({ isAdmin, onAdmin }: { isAdmin: boolean; onAdmin: () => void }) {
  return (
    <section className="empty-state">
      <Archive size={32} />
      <h2>暂无可发布库存</h2>
      <p>{isAdmin ? "请先到管理设置同步撰文系统项目，并给员工分配负责板块。" : "当前账号还没有分配可见项目或文章。"}</p>
      {isAdmin && <button className="btn primary" onClick={onAdmin}>去同步项目</button>}
    </section>
  );
}

function roleLabel(role: string): string {
  if (role === "admin") return "管理员";
  if (role === "manager") return "内容负责人";
  return "媒介员工";
}

function viewTitle(view: View): string {
  return { dashboard: "库存看板", library: "文章库", records: "发布记录", log: "工作日志", admin: "管理设置" }[view];
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function groupBy<T>(items: T[], getKey: (item: T) => string): Record<string, T[]> {
  return items.reduce<Record<string, T[]>>((groups, item) => {
    const key = getKey(item);
    groups[key] = groups[key] || [];
    groups[key].push(item);
    return groups;
  }, {});
}

function shortDate(value: string): string {
  if (!value) return "-";
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  if (hasTimezone) {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) {
      const parts = new Intl.DateTimeFormat("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false
      }).formatToParts(parsed);
      const getPart = (type: Intl.DateTimeFormatPartTypes) => parts.find(part => part.type === type)?.value || "";
      return `${getPart("year")}-${getPart("month")}-${getPart("day")} ${getPart("hour")}:${getPart("minute")}`;
    }
  }
  return value.replace("T", " ").slice(0, 16);
}

function statusLabel(status: string): string {
  if (status === "published") return "已发布";
  if (status === "purchasing") return "采购中";
  return status;
}

function recordDateLabel(record: PublicationRecord): string {
  const value = record.published_at || record.created_at || "";
  return value.slice(0, 10) || "-";
}

function isSelfChannel(channel: string): boolean {
  return ["自营", "自媒体", "self"].includes(channel);
}

function recordChannelGroup(record: PublicationRecord): "self" | "web" {
  return isSelfChannel(record.channel_type) ? "self" : "web";
}

function formatMoney(value: number): string {
  return `¥${value.toLocaleString("zh-CN")}`;
}

function suggestedChannels(articleType: string): string[] {
  if (/榜单|推荐|清单/.test(articleType)) return ["自媒体", "垂直媒体", "大众媒体"];
  if (/横评|对比|测评|评测/.test(articleType)) return ["自媒体", "权威媒体", "垂直媒体", "大众媒体"];
  if (/场景|选购|指南/.test(articleType)) return ["自媒体", "垂直媒体", "大众媒体"];
  if (/产品|证据|案例/.test(articleType)) return ["自媒体", "权威媒体", "垂直媒体"];
  if (/FAQ|问答|问题/.test(articleType)) return ["自媒体", "大众媒体"];
  return ["自媒体", "垂直媒体"];
}

function splitList(value: string): string[] {
  return value.split(/[,\n，、]/).map(item => item.trim()).filter(Boolean);
}

function downloadMarkdown(article: ArticleSnapshot) {
  const blob = new Blob([article.markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${article.title || article.article_id}.md`;
  link.click();
  URL.revokeObjectURL(url);
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
