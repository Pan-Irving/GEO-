import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Archive,
  ArrowUpRight,
  BadgeAlert,
  BookOpen,
  ChevronDown,
  CheckCircle2,
  CircleAlert,
  Copy,
  Download,
  FileArchive,
  FileText,
  FolderOpen,
  LayoutDashboard,
  Loader2,
  Newspaper,
  PenLine,
  Plus,
  RefreshCw,
  Route,
  Save,
  ScanText,
  Search,
  TableProperties,
  Trash2,
  Upload,
  X
} from "lucide-react";
import { api } from "./api/client";
import type { ContentPlan, CustomSourceBatchPayload, CustomSourcePayload, MarkdownArticleImportMeta, MatrixImportDraft, Project, PublishingUsageSummary, WorkflowStep } from "./api/types";
import "./styles/app.css";

type AppView = "dashboard" | "upload" | "planning" | "custom" | "brief" | "article" | "import" | "library";
type PlanningTab = "matrix" | "demand_matrix" | "breakthrough";
type EditableStep = "matrix" | "demand_matrix" | "breakthrough" | "brief" | "article";
type BriefModifiedFilter = "all" | "modified" | "unmodified";
type BriefArticleFilter = "all" | "generated" | "not_generated" | "needs_update" | "failed" | "pending_review" | "approved";
type CustomBriefFilter = "all" | "generated" | "not_generated";
type DashboardProductionStage = "pending_plan" | "pending_brief" | "brief_done" | "article_pending" | "article_done" | "purchasing" | "used";

type AnyRecord = Record<string, unknown>;

interface ContentItem {
  id: string;
  sourceId: string;
  sourceStep: string;
  briefId?: string;
  keyword: string;
  type: string;
  title: string;
  role: string;
  channel: string;
  status: string;
  used: string;
  markdown?: string;
  reviewNotes?: string;
  articleAuditStatus?: string;
  articleAuditedAt?: string;
  error?: string;
  revision: number;
  modifiedAt?: string;
  briefRevision: number;
  staleReason?: string;
  raw: AnyRecord;
}

interface MatrixIntentGroup {
  id: string;
  name: string;
  keywords: string[];
  userQuestion: string;
  userStage: string;
  articleTypes: string[];
  raw: AnyRecord;
}

interface IntakeRow {
  id: string;
  field: string;
  value: string;
  source: string;
  confidence: string;
  status: string;
}

interface DetailState {
  step: EditableStep;
  item: ContentItem;
  mode?: "edit" | "audit" | "read";
}

interface BriefFilterState {
  keyword: string;
  articleType: string;
  briefModified: BriefModifiedFilter;
  articleStatus: BriefArticleFilter;
}

interface PlanningFilterState {
  keyword: string;
  articleType: string;
}

interface CustomFilterState {
  keyword: string;
  articleType: string;
  briefStatus: CustomBriefFilter;
}

interface DashboardDrilldown {
  view: "planning" | "brief" | "article";
  keyword?: string;
  articleType?: string;
  articleStatus?: BriefArticleFilter;
  briefModified?: BriefModifiedFilter;
  tab?: PlanningTab;
}

interface MarkdownImportDraft {
  id: string;
  file: File;
  filename: string;
  title: string;
  keyword: string;
  type: string;
  status: "ready" | "invalid";
  error: string;
}

interface DashboardSummary {
  title: string;
  brand: string;
  product: string;
  mainKeywords: string[];
  keywordCount: number;
  totalPlans: number;
  period: string;
}

interface DashboardProgressRow {
  id: string;
  label: string;
  plans: number;
  briefs: number;
  articles: number;
  completed: number;
  used: number;
  purchasing: number;
  percent: number;
  drilldown: DashboardDrilldown;
}

interface DashboardMatrixCell {
  id: string;
  keyword: string;
  type: string;
  plans: number;
  briefs: number;
  articles: number;
  completed: number;
  used: number;
  purchasing: number;
  stale: number;
  stage: DashboardProductionStage;
  label: string;
  drilldown: DashboardDrilldown;
}

interface DashboardData {
  summary: DashboardSummary;
  keywords: DashboardProgressRow[];
  articleTypes: DashboardProgressRow[];
  matrix: DashboardMatrixCell[];
  totals: {
    plans: number;
    briefs: number;
    articles: number;
    completed: number;
    used: number;
    purchasing: number;
    pendingBriefs: number;
    pendingArticles: number;
    staleArticles: number;
    pendingPlanCells: number;
  };
}

const emptyBriefFilters: BriefFilterState = {
  keyword: "all",
  articleType: "all",
  briefModified: "all",
  articleStatus: "all"
};

const emptyPlanningFilters: PlanningFilterState = {
  keyword: "all",
  articleType: "all"
};

const emptyCustomFilters: CustomFilterState = {
  keyword: "all",
  articleType: "all",
  briefStatus: "all"
};

const coreArticleTypes = ["支柱标准文", "榜单推荐文", "横评对比文", "场景选购文", "产品证据文", "FAQ问答文"];
const coreArticleTypeSet = new Set(coreArticleTypes);

const appSteps: Array<{ id: AppView; title: string; desc: string; backendStep?: WorkflowStep }> = [
  { id: "dashboard", title: "项目看板", desc: "整体产出与进度" },
  { id: "upload", title: "资料与信息", desc: "必填资料 + 信息确认", backendStep: "intake" },
  { id: "planning", title: "规划确认", desc: "整体规划与逐词击破", backendStep: "matrix" },
  { id: "custom", title: "自定义文章", desc: "批量添加选题" },
  { id: "brief", title: "Brief 审核", desc: "按关键词分组", backendStep: "brief" },
  { id: "article", title: "正文审核", desc: "折叠查阅与定稿", backendStep: "article" },
  { id: "import", title: "导入定稿", desc: "上传本地 Markdown" },
  { id: "library", title: "定稿归档", desc: "按关键词与类型分组", backendStep: "archive" }
];

const materialSlots = [
  { id: "brief", name: "客户需求 brief", required: true, desc: "项目背景、目标、关键词、竞品信息、推荐结论等。" },
  { id: "keywords", name: "核心关键词表", required: true, desc: "目标关键词、搜索问题、优先级、渠道建议等。" },
  { id: "brand", name: "品牌 / 产品资料", required: true, desc: "品牌介绍、产品卖点、服务方案、目标对象资料。" },
  { id: "evidence", name: "核心证据资料", required: true, desc: "认证、检测报告、专利、奖项、案例、服务体系等。" },
  { id: "competitor", name: "竞品对比资料", required: true, desc: "竞品品牌、替代方案、对比维度和不同时期版本。" },
  { id: "forbidden", name: "禁用词与合规边界", required: true, desc: "绝对化禁词、风险表达、内部执行话术和合规要求。" },
  { id: "expression", name: "客户表达规范", required: true, desc: "品牌标准叫法、产品标准表述、推荐语气和不允许改写的表达。" },
  { id: "demand_report", name: "用户需求挖掘报告", required: false, desc: "新需求驱动内容矩阵专用：场景、痛点、隐性变量、搜索问题和内容机会。" },
  { id: "other", name: "其他补充资料", required: false, desc: "访谈纪要、平台截图、历史文章、会议记录等可选补充。" }
];

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [project, setProject] = useState<Project | null>(null);
  const [current, setCurrent] = useState<AppView>("dashboard");
  const [planningTab, setPlanningTab] = useState<PlanningTab>("matrix");
  const [selectedPlans, setSelectedPlans] = useState<Set<string>>(new Set());
  const [selectedBriefs, setSelectedBriefs] = useState<Set<string>>(new Set());
  const [selectedArticles, setSelectedArticles] = useState<Set<string>>(new Set());
  const [selectedArchiveArticles, setSelectedArchiveArticles] = useState<Set<string>>(new Set());
  const [dismissedJobIds, setDismissedJobIds] = useState<Set<string>>(new Set());
  const [dashboardDrilldown, setDashboardDrilldown] = useState<DashboardDrilldown | null>(null);
  const [detail, setDetail] = useState<DetailState | null>(null);
  const [deleteProjectTarget, setDeleteProjectTarget] = useState<Project | null>(null);
  const [projectName, setProjectName] = useState("GEO 内容项目");
  const [health, setHealth] = useState<{ model: string; writing_model?: string | null; planning_model?: string | null; skill_available: boolean; publishing_frontend_url?: string } | null>(null);
  const [publishingUsage, setPublishingUsage] = useState<PublishingUsageSummary | null>(null);
  const [message, setMessage] = useState("");
  const messageTimerRef = useRef<number | null>(null);
  const [busy, setBusy] = useState(false);
  const selectedProjectIdRef = useRef("");

  useEffect(() => {
    void loadProjects();
    void api.health().then(setHealth).catch(error => showMessage(error.message));
  }, []);

  useEffect(() => {
    return () => {
      if (messageTimerRef.current) window.clearTimeout(messageTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!selectedProjectId) return;
    const timer = window.setInterval(() => void refreshProject(selectedProjectId), 2500);
    return () => window.clearInterval(timer);
  }, [selectedProjectId]);

  const data = useMemo(() => project ? deriveProjectData(project) : emptyDerivedData(), [project]);
  const selectedPlanItems = useMemo(
    () => data.plans.filter(item => selectedPlans.has(item.id)),
    [data.plans, selectedPlans]
  );
  const selectedBriefItems = useMemo(
    () => data.briefs.filter(item => selectedBriefs.has(item.id)),
    [data.briefs, selectedBriefs]
  );

  const viewMeta = useMemo(() => ({
    dashboard: ["项目看板", "查看 Agent 产出、确认状态、已生成文档和下一步待处理动作。"],
    upload: ["资料与项目信息", "按固定资料入口上传素材，解析后在同页确认项目信息抽取表。"],
    planning: ["内容矩阵与逐词击破规划", "先看整体内容矩阵，再看每个关键词固定六类文章规划。"],
    custom: ["自定义文章规划", "批量添加人工指定选题，选择文章类型后生成 Brief。"],
    brief: ["Brief 批量生成与审核", "按关键词分组审核 Brief，确认后进入正文生成。"],
    article: ["正文生成、审核与定稿", "折叠查阅正文，提交修改意见或确认定稿。"],
    import: ["导入本地定稿", "批量上传 Markdown 正文，补充关键词和文章类型后直接进入定稿归档。"],
    library: ["定稿文章归档与查阅", "查看已审核通过正文，筛选、查阅并批量导出。"]
  }), []);

  async function loadProjects() {
    const list = await api.listProjects();
    setProjects(list);
    const nextId = list.some(item => item.id === selectedProjectIdRef.current)
      ? selectedProjectIdRef.current
      : list[0]?.id || "";
    if (nextId) {
      selectedProjectIdRef.current = nextId;
      setSelectedProjectId(nextId);
      setProject(list.find(item => item.id === nextId) || null);
      await refreshProject(nextId);
    } else {
      selectedProjectIdRef.current = "";
      setSelectedProjectId("");
      setProject(null);
      setPublishingUsage(null);
    }
  }

  async function refreshProject(projectId: string) {
    const next = await api.getProject(projectId);
    if (selectedProjectIdRef.current !== projectId) return;
    updateProjectState(next);
    const usage = await api.getPublishingUsageSummary(projectId);
    if (selectedProjectIdRef.current === projectId) setPublishingUsage(usage);
  }

  function updateProjectState(next: Project) {
    setProject(next);
    setProjects(currentProjects => currentProjects.map(item => (item.id === next.id ? next : item)));
  }

  function selectProject(projectId: string) {
    selectedProjectIdRef.current = projectId;
    setSelectedProjectId(projectId);
    setSelectedPlans(new Set());
    setSelectedBriefs(new Set());
    setSelectedArticles(new Set());
    setSelectedArchiveArticles(new Set());
    setPublishingUsage(null);
    setDetail(null);
    showMessage("");
    if (!projectId) {
      setProject(null);
      return;
    }
    setProject(projects.find(item => item.id === projectId) || null);
    void refreshProject(projectId);
  }

  async function manualRefresh() {
    setBusy(false);
    showMessage("");
    if (selectedProjectIdRef.current) await refreshProject(selectedProjectIdRef.current);
    else await loadProjects();
  }

  function showMessage(text: string) {
    if (messageTimerRef.current) {
      window.clearTimeout(messageTimerRef.current);
      messageTimerRef.current = null;
    }
    setMessage(text);
    if (!text) return;
    messageTimerRef.current = window.setTimeout(() => {
      setMessage("");
      messageTimerRef.current = null;
    }, 3000);
  }

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    showMessage("");
    try {
      await action();
      showMessage(success);
      if (selectedProjectIdRef.current) await refreshProject(selectedProjectIdRef.current);
      else await loadProjects();
    } catch (error) {
      showMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function createProject() {
    await run(async () => {
      const created = await api.createProject(projectName);
      setProjects([created, ...projects]);
      selectedProjectIdRef.current = created.id;
      setSelectedProjectId(created.id);
      setProject(created);
      setCurrent("upload");
    }, "项目已创建。");
  }

  async function deleteProject(projectId: string) {
    setBusy(true);
    showMessage("");
    try {
      await api.deleteProject(projectId);
      const nextProjects = await api.listProjects();
      const nextProject = nextProjects[0] || null;
      setProjects(nextProjects);
      selectedProjectIdRef.current = nextProject?.id || "";
      setSelectedProjectId(nextProject?.id || "");
      setProject(nextProject);
      setCurrent("dashboard");
      setPlanningTab("matrix");
      setSelectedPlans(new Set());
      setSelectedBriefs(new Set());
      setSelectedArticles(new Set());
      setSelectedArchiveArticles(new Set());
      setDismissedJobIds(new Set());
      setDashboardDrilldown(null);
      setDetail(null);
      setDeleteProjectTarget(null);
      showMessage("项目已删除。");
      if (nextProject) await refreshProject(nextProject.id);
    } catch (error) {
      showMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function cancelJob(jobId: string) {
    if (!project) return;
    showMessage("");
    try {
      const response = await api.cancelJob(project.id, jobId);
      setProject(response.project);
      setProjects(currentProjects => currentProjects.map(item => (item.id === response.project.id ? response.project : item)));
      showMessage("已提交停止请求，当前正在执行的单个请求完成后会停止后续操作。");
    } catch (error) {
      showMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function runBackendStep(step: WorkflowStep, payload: Record<string, unknown> = {}) {
    if (!project) return;
    await run(async () => {
      await api.runStep(project.id, step, payload);
    }, "任务已提交，后台 Agent 正在更新状态。");
  }

  async function saveItem(step: EditableStep, item: ContentItem, payload: Record<string, unknown>) {
    if (!project) return;
    if (step === "demand_matrix") {
      setDetail(null);
      return;
    }
    const articleContentChanged = step === "article"
      && ((typeof payload.title === "string" && payload.title !== item.title)
        || (typeof payload.markdown === "string" && payload.markdown !== (item.markdown || "")));
    await run(async () => {
      await api.updateItem(project.id, step, item.id, {
        ...payload,
        ...(articleContentChanged ? { article_audit_status: "", article_audited_at: "" } : {}),
        source_id: item.sourceId,
        brief_id: item.briefId,
        source_step: item.sourceStep
      });
    }, "单篇修改已保存。");
    setDetail(null);
  }

  async function regenerateItem(step: EditableStep, item: ContentItem, payload: Record<string, unknown> = {}) {
    if (step === "demand_matrix") return;
    const reviewNotes = typeof payload.review_notes === "string" ? payload.review_notes : item.reviewNotes || "";
    if (step === "brief") {
      await runBackendStep("brief", {
        force: true,
        selected_sources: [{
          ...toSourcePayload(item),
          title: typeof payload.title === "string" ? payload.title : item.title,
          review_notes: reviewNotes,
          previous_brief_markdown: typeof payload.markdown === "string" ? payload.markdown : item.markdown || ""
        }]
      });
      setDetail(null);
      return;
    }
    if (step === "article") {
      const sourceBrief = data.briefs.find(brief => brief.id === item.briefId) || item;
      await runBackendStep("article", {
        force: true,
        selected_briefs: [{
          ...toBriefPayload(sourceBrief),
          review_notes: reviewNotes,
          requested_article_title: typeof payload.title === "string" ? payload.title : item.title,
          previous_article_markdown: typeof payload.markdown === "string" ? payload.markdown : item.markdown || ""
        }]
      });
      setDetail(null);
    }
  }

  async function confirmBackendStep(step: WorkflowStep) {
    if (!project) return;
    await run(async () => {
      await api.confirmStep(project.id, step);
    }, "该阶段已确认。");
  }

  async function confirmBreakthroughKeywords(keywords: string[]) {
    if (!project) return;
    await run(async () => {
      await api.confirmBreakthroughKeywords(project.id, keywords);
    }, "已保存逐词击破关键词；内容矩阵规划仍可直接生成 Brief。");
  }

  async function createCustomSources(payload: CustomSourceBatchPayload) {
    if (!project) return;
    await run(async () => {
      await api.createCustomSources(project.id, payload);
    }, "自定义文章规划已批量新增。");
  }

  async function updateCustomSource(sourceId: string, payload: CustomSourcePayload) {
    if (!project) return;
    await run(async () => {
      await api.updateCustomSource(project.id, sourceId, payload);
    }, "自定义文章规划已更新。");
  }

  async function deleteCustomSource(sourceId: string) {
    if (!project) return;
    await run(async () => {
      await api.deleteCustomSource(project.id, sourceId);
    }, "自定义文章规划已删除。");
  }

  async function importMarkdownArticles(rows: Array<{ file: File; meta: MarkdownArticleImportMeta }>) {
    if (!project) return;
    await run(async () => {
      await api.importMarkdownArticles(project.id, rows);
      setSelectedArchiveArticles(new Set());
    }, "Markdown 定稿已导入，可在定稿归档查看；发布平台同步后即可使用。");
  }

  function openDashboardDrilldown(target: DashboardDrilldown) {
    setDashboardDrilldown(target);
    if (target.tab) setPlanningTab(target.tab);
    setCurrent(target.view);
  }

  const currentMeta = viewMeta[current];

  return (
    <div className="app prototype">
      <aside className="sidebar">
        <div className="brand">
          <img className="sidebar-logo" src="/mindsun-logo.png" alt="思阳集团" />
          <strong className="brand-title">GEO 撰文工作台</strong>
          <span className="brand-subtitle">资料分析 → 规划 → Brief → 正文</span>
        </div>

        <div className="project-card">
          <div className="project-switcher">
            <label htmlFor="project-select">当前项目</label>
            <select id="project-select" value={selectedProjectId} onChange={event => selectProject(event.target.value)}>
              <option value="">请选择项目</option>
              {projects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            <button
              type="button"
              className="delete-project-button"
              disabled={!project || busy}
              onClick={() => project && setDeleteProjectTarget(project)}
            >
              <Trash2 size={15} />删除当前项目
            </button>
          </div>
          <div className="new-project">
            <span>新建项目</span>
            <div>
              <input value={projectName} placeholder="输入新项目名称" onChange={event => setProjectName(event.target.value)} />
              <button onClick={createProject}>新建</button>
            </div>
          </div>
        </div>

        <div className="section-label">生产流程</div>
        <nav className="steps">
          {appSteps.map((step, index) => {
            const status = step.backendStep && project ? project.steps[step.backendStep]?.status : index === 0 ? "confirmed" : "pending";
            return (
              <button key={step.id} className={`step ${current === step.id ? "active" : ""} ${status}`} onClick={() => setCurrent(step.id)}>
                <span>{status === "confirmed" ? <CheckCircle2 size={15} /> : index + 1}</span>
                <div><strong>{step.title}</strong><small>{step.desc}</small></div>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="main">
        <header className="topbar">
          <div><FolderOpen size={16} /> 项目空间 / GEO 内容生产 / <strong>{currentMeta[0]}</strong></div>
          <div className="user-chip">内容负责人</div>
        </header>

        <section className="page-head">
          <div>
            <h1>{currentMeta[0]}</h1>
            <p>{currentMeta[1]}</p>
          </div>
          <div className="actions">
            {busy && <span className="pill"><Loader2 className="spin" size={14} />运行中</span>}
            {health && <span className="pill">规划 {health.planning_model || health.model} / 写作 {health.writing_model || health.model} / Skill {health.skill_available ? "已识别" : "缺失"}</span>}
            <a className="btn" href={health?.publishing_frontend_url || "http://127.0.0.1:5174"} target="_blank" rel="noreferrer"><ArrowUpRight size={15} />发布工作台</a>
            <button className="btn" onClick={() => void manualRefresh()}><RefreshCw size={15} />刷新状态</button>
          </div>
        </section>

        {message && <div className="notice">{message}</div>}
        {!project ? <EmptyState /> : (
          <>
            {current === "dashboard" && <DashboardView project={project} data={data} publishingUsage={publishingUsage} setCurrent={setCurrent} openDrilldown={openDashboardDrilldown} />}
            {current === "upload" && (
              <UploadView
                project={project}
                data={data}
                run={run}
                runBackendStep={runBackendStep}
                confirmBackendStep={confirmBackendStep}
                dismissedJobIds={dismissedJobIds}
                dismissJob={(jobId) => setDismissedJobIds(current => new Set([...current, jobId]))}
                cancelJob={cancelJob}
              />
            )}
            {current === "planning" && (
              <PlanningView
                project={project}
                data={data}
                tab={planningTab}
                setTab={setPlanningTab}
                selectedPlans={selectedPlans}
                setSelectedPlans={setSelectedPlans}
                runBackendStep={runBackendStep}
                confirmBreakthroughKeywords={confirmBreakthroughKeywords}
                setCurrent={setCurrent}
                openDetail={(step, item) => setDetail({ step, item })}
                dismissedJobIds={dismissedJobIds}
                dismissJob={(jobId) => setDismissedJobIds(current => new Set([...current, jobId]))}
                cancelJob={cancelJob}
                dashboardDrilldown={dashboardDrilldown}
                clearDashboardDrilldown={() => setDashboardDrilldown(null)}
                onProjectUpdate={updateProjectState}
              />
            )}
            {current === "custom" && (
              <CustomView
                project={project}
                items={data.customPlans}
                briefs={data.briefs}
                articles={data.articles}
                selectedPlans={selectedPlans}
                setSelectedPlans={setSelectedPlans}
                createCustomSources={createCustomSources}
                updateCustomSource={updateCustomSource}
                deleteCustomSource={deleteCustomSource}
                runBackendStep={runBackendStep}
                setCurrent={setCurrent}
                dismissedJobIds={dismissedJobIds}
                dismissJob={(jobId) => setDismissedJobIds(current => new Set([...current, jobId]))}
                cancelJob={cancelJob}
              />
            )}
            {current === "brief" && (
              <BriefView
                project={project}
                items={data.briefs}
                articles={data.articles}
                selectedSourceItems={selectedPlanItems}
                selectedBriefItems={selectedBriefItems}
                selectedBriefs={selectedBriefs}
                setSelectedBriefs={setSelectedBriefs}
                runBackendStep={runBackendStep}
                setCurrent={setCurrent}
                openDetail={(item) => setDetail({ step: "brief", item })}
                regenerateBrief={(item) => regenerateItem("brief", item)}
                dismissedJobIds={dismissedJobIds}
                dismissJob={(jobId) => setDismissedJobIds(current => new Set([...current, jobId]))}
                cancelJob={cancelJob}
                dashboardDrilldown={dashboardDrilldown}
                clearDashboardDrilldown={() => setDashboardDrilldown(null)}
              />
            )}
            {current === "article" && (
              <ArticleView
                project={project}
                items={data.articles}
                briefs={data.briefs}
                selectedArticles={selectedArticles}
                setSelectedArticles={setSelectedArticles}
                confirmBackendStep={confirmBackendStep}
                openDetail={(item) => setDetail({ step: "article", item })}
                openAudit={(item) => setDetail({ step: "article", item, mode: "audit" })}
                openBriefDetail={(item) => {
                  setCurrent("brief");
                  setSelectedBriefs(new Set([item.id]));
                  setDetail({ step: "brief", item });
                }}
                regenerateArticle={(item) => regenerateItem("article", item)}
                dismissedJobIds={dismissedJobIds}
                dismissJob={(jobId) => setDismissedJobIds(current => new Set([...current, jobId]))}
                cancelJob={cancelJob}
                dashboardDrilldown={dashboardDrilldown}
                clearDashboardDrilldown={() => setDashboardDrilldown(null)}
              />
            )}
            {current === "import" && (
              <MarkdownImportView
                project={project}
                data={data}
                onImport={importMarkdownArticles}
                busy={busy}
                setCurrent={setCurrent}
                openDetail={(item) => setDetail({ step: "article", item, mode: "read" })}
              />
            )}
            {current === "library" && (
              <LibraryView
                project={project}
                data={data}
                selectedArticles={selectedArchiveArticles}
                setSelectedArticles={setSelectedArchiveArticles}
                openDetail={(item) => setDetail({ step: "article", item, mode: "read" })}
              />
            )}
          </>
        )}
        {detail && (
          <ItemDetailModal
            detail={detail}
            canRegenerate={(detail.step === "brief" || detail.step === "article") && detail.mode !== "read"}
            onClose={() => setDetail(null)}
            onSave={(payload) => saveItem(detail.step, detail.item, payload)}
            onAudit={(status, reviewNotes) => saveItem("article", detail.item, {
              article_audit_status: status,
              article_audited_at: new Date().toISOString(),
              review_notes: reviewNotes
            })}
            onRegenerate={(payload) => regenerateItem(detail.step, detail.item, payload)}
          />
        )}
        {deleteProjectTarget && (
          <div className="modal-backdrop" role="presentation">
            <div className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-project-title">
              <h2 id="delete-project-title">删除项目</h2>
              <p>
                确认删除「{deleteProjectTarget.name}」吗？该项目的上传资料、解析结果、生成内容、导出文件和日志都会被删除，此操作不可恢复。
              </p>
              <div className="actions end">
                <button className="btn" onClick={() => setDeleteProjectTarget(null)}>取消</button>
                <button className="btn danger" disabled={busy} onClick={() => void deleteProject(deleteProjectTarget.id)}>
                  <Trash2 size={15} />确认删除
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function DashboardView({ project, data, publishingUsage, setCurrent, openDrilldown }: {
  project: Project;
  data: DerivedData;
  publishingUsage: PublishingUsageSummary | null;
  setCurrent: (view: AppView) => void;
  openDrilldown: (target: DashboardDrilldown) => void;
}) {
  const dashboard = deriveDashboardData(project, data, publishingUsage);
  const [matrixSearch, setMatrixSearch] = useState("");
  const [selectedKeywordFilter, setSelectedKeywordFilter] = useState("");
  const normalizedSearch = matrixSearch.trim().toLowerCase();
  const matrixKeywords = dashboard.keywords.filter(row => {
    if (selectedKeywordFilter && row.label !== selectedKeywordFilter) return false;
    return !normalizedSearch || row.label.toLowerCase().includes(normalizedSearch);
  });
  const matrixTypes = dashboard.articleTypes;
  const cellByKey = new Map(dashboard.matrix.map(cell => [`${cell.keyword}\u0001${cell.type}`, cell]));
  const generatedArticles = dashboard.totals.articles;
  const finalNotUsed = Math.max(dashboard.totals.completed - dashboard.totals.used, 0);
  function toggleKeywordFilter(keyword: string) {
    setSelectedKeywordFilter(current => current === keyword ? "" : keyword);
    setMatrixSearch("");
  }
  function clearKeywordFilter() {
    setSelectedKeywordFilter("");
  }
  return (
    <div className="dashboard-workspace">
      <section className="dashboard-project-card">
        <div className="dashboard-project-copy">
          <span className="dashboard-kicker">当前项目</span>
          <h2>{dashboard.summary.title}</h2>
          <p>{dashboard.summary.brand || dashboard.summary.product ? `${dashboard.summary.brand}${dashboard.summary.brand && dashboard.summary.product ? " · " : ""}${dashboard.summary.product}` : "后台 Agent 已读取项目资料，等待生成完整摘要。"}</p>
        </div>
        <div className="dashboard-project-meta">
          <DashboardMeta label="项目周期" value={dashboard.summary.period} />
          <DashboardMeta label="目标关键词" value={`${dashboard.summary.keywordCount} 个`} />
          <DashboardMeta label="当前总规划" value={`${dashboard.summary.totalPlans} 篇`} />
          <button className="btn primary dashboard-cta" onClick={() => setCurrent("planning")}><Route size={15} />进入内容规划</button>
        </div>
        <div className="dashboard-tags">
          {dashboard.summary.mainKeywords.length
            ? dashboard.summary.mainKeywords.map((keyword, index) => (
              <button
                key={`${keyword}-${index}`}
                className={`chip chip-button dashboard-keyword-chip ${selectedKeywordFilter === keyword ? "is-active" : ""}`.trim()}
                title={`筛选关键词：${keyword}`}
                type="button"
                onClick={() => toggleKeywordFilter(keyword)}
              >
                <span>{keyword}</span>
              </button>
            ))
            : <span className="chip dashboard-keyword-chip is-empty"><span>暂无主要关键词</span></span>}
        </div>
      </section>

      <div className="dashboard-two-col">
        <DashboardProgressPanel
          title="关键词发稿统计"
          subtitle="查看每个目标关键词当前已经完成正文的文章数量。"
          badge={`${dashboard.keywords.length} 个关键词`}
          rows={dashboard.keywords}
          onOpen={openDrilldown}
        />
        <DashboardProgressPanel
          title="文章类型发稿统计"
          subtitle="查看六类文章的规划量与实际发稿数量。"
          badge={`${dashboard.articleTypes.length} 类文章`}
          rows={dashboard.articleTypes}
          onOpen={openDrilldown}
        />
      </div>

      <div className="dashboard-kpi-row">
        <DashboardKpiCard label="文章规划" value={dashboard.totals.plans} total={dashboard.totals.plans} caption={`${dashboard.totals.pendingPlanCells} 个关键词类型待补`} tone="blue" onClick={() => openDrilldown({ view: "planning", tab: "matrix" })} />
        <DashboardKpiCard label="Brief 产出" value={dashboard.totals.briefs} total={dashboard.totals.plans} caption={`${dashboard.totals.pendingBriefs} 篇规划待生成`} tone="cyan" onClick={() => openDrilldown({ view: "brief", articleStatus: "not_generated" })} />
        <DashboardKpiCard label="正文产出" value={generatedArticles} total={dashboard.totals.plans} caption={`${dashboard.totals.pendingArticles} 篇待继续推进`} tone="indigo" onClick={() => openDrilldown({ view: "article" })} />
        <DashboardKpiCard label="完成定稿" value={dashboard.totals.completed} total={dashboard.totals.plans} caption={`${finalNotUsed} 篇待发布使用`} tone="green" onClick={() => openDrilldown({ view: "article", articleStatus: "approved" })} />
        <DashboardKpiCard label="采购中" value={dashboard.totals.purchasing} total={dashboard.totals.plans} caption={publishingUsage ? "来自发布系统采购记录" : "未连接发布系统"} tone="orange" onClick={() => openDrilldown({ view: "article", articleStatus: "approved" })} />
        <DashboardKpiCard label="已经使用" value={dashboard.totals.used} total={dashboard.totals.plans} caption={publishingUsage ? "来自发布系统已发布记录" : dashboard.totals.used ? "已标记发布使用" : "暂无已使用标记"} tone="orange" onClick={() => openDrilldown({ view: "article", articleStatus: "generated" })} />
      </div>

      <section className="dashboard-panel dashboard-matrix-panel">
        <div className="dashboard-panel-head">
          <div>
            <h2>关键词 × 文章类型进度</h2>
            <p>点击任意状态，直接进入对应环节继续处理。</p>
          </div>
          <div className="dashboard-legend">
            <span className="stage-dot used" />已使用
            <span className="stage-dot purchasing" />采购中
            <span className="stage-dot article_done" />已定稿
            <span className="stage-dot article_pending" />正文待审
            <span className="stage-dot brief_done" />Brief完成
            <span className="stage-dot pending_plan" />待补规划
          </div>
        </div>
        <div className="dashboard-matrix-toolbar">
          <label className="dashboard-search">
            <Search size={15} />
            <input value={matrixSearch} placeholder="输入关键词检索" onChange={event => setMatrixSearch(event.target.value)} />
          </label>
          <div className="dashboard-matrix-filter-meta">
            {selectedKeywordFilter && (
              <button className="chip chip-button dashboard-filter-chip" type="button" onClick={clearKeywordFilter} title="清除关键词筛选">
                <span>已筛选：{selectedKeywordFilter}</span>
                <X size={13} />
              </button>
            )}
            <span>当前展示 {matrixKeywords.length} 个关键词 · {dashboard.totals.plans} 篇文章规划</span>
          </div>
        </div>
        <div className="dashboard-matrix-scroll">
          <table className="dashboard-matrix">
            <thead>
              <tr>
                <th>序号 / 目标关键词</th>
                {matrixTypes.map(type => <th key={type.id}>{type.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {matrixKeywords.length ? matrixKeywords.map((keyword, index) => (
                <tr key={keyword.id}>
                  <th>
                    <button className="matrix-keyword" onClick={() => openDrilldown(keyword.drilldown)}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <strong>{keyword.label}</strong>
                      <small>{keyword.plans} 篇规划 · {keyword.briefs} Brief · {keyword.articles} 正文</small>
                    </button>
                  </th>
                  {matrixTypes.map(type => {
                    const cell = cellByKey.get(`${keyword.label}\u0001${type.label}`);
                    if (!cell) return <td key={type.id} />;
                    return (
                      <td key={cell.id}>
                        <button className={`dashboard-matrix-cell ${cell.stage}`} onClick={() => openDrilldown(cell.drilldown)}>
                          <strong>{cell.label}</strong>
                          <span>{cell.plans} 规划 · {cell.briefs} Brief · {cell.articles} 正文</span>
                          <span>{cell.used} 已使用 · {cell.purchasing} 采购中</span>
                        </button>
                      </td>
                    );
                  })}
                </tr>
              )) : (
                <tr>
                  <td className="dashboard-matrix-empty" colSpan={matrixTypes.length + 1}>
                    暂无匹配关键词，请清除筛选或更换关键词。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <div className="dashboard-bottom-grid">
        <section className="dashboard-panel">
          <div className="dashboard-panel-head">
            <div>
              <h2>整体生产进度</h2>
              <p>以规划文章为基准，查看从 Brief 到发布使用的转化进度。</p>
            </div>
            <Chip text={dashboard.totals.pendingBriefs + dashboard.totals.pendingArticles + dashboard.totals.staleArticles ? "项目资料待处理" : "项目资料齐全"} type={dashboard.totals.pendingBriefs + dashboard.totals.pendingArticles + dashboard.totals.staleArticles ? "warn" : "good"} />
          </div>
          <div className="dashboard-stage-bars">
            <DashboardStageBar label="已完成规划" value={dashboard.totals.plans} total={dashboard.totals.plans} tone="blue" />
            <DashboardStageBar label="已生成 Brief" value={dashboard.totals.briefs} total={dashboard.totals.plans} tone="cyan" />
            <DashboardStageBar label="已生成正文" value={dashboard.totals.articles} total={dashboard.totals.plans} tone="indigo" />
            <DashboardStageBar label="已完成定稿" value={dashboard.totals.completed} total={dashboard.totals.plans} tone="green" />
            <DashboardStageBar label="已发布使用" value={dashboard.totals.used} total={dashboard.totals.plans} tone="orange" />
          </div>
        </section>
        <section className="dashboard-panel">
          <div className="dashboard-panel-head compact">
            <div>
              <h2>优先跟进</h2>
              <p>按当前缺口自动汇总下一步。</p>
            </div>
            <Chip text={`${dashboard.totals.pendingBriefs + dashboard.totals.pendingArticles + dashboard.totals.staleArticles + dashboard.totals.pendingPlanCells} 项`} type="warn" />
          </div>
          <div className="follow-list">
            <DashboardFollowItem icon={<TableProperties size={16} />} title="补齐文章规划" desc={`${dashboard.totals.pendingPlanCells} 个关键词类型尚无规划`} onClick={() => openDrilldown({ view: "planning", tab: "matrix" })} />
            <DashboardFollowItem icon={<FileText size={16} />} title="批量生成 Brief" desc={`${dashboard.totals.pendingBriefs} 篇已有规划，等待 Brief`} onClick={() => openDrilldown({ view: "planning", tab: "matrix" })} />
            <DashboardFollowItem icon={<BadgeAlert size={16} />} title="审核并继续产出" desc={`${dashboard.totals.pendingArticles + dashboard.totals.staleArticles} 篇 Brief / 正文等待确认`} onClick={() => openDrilldown({ view: "brief", articleStatus: "not_generated" })} />
            <DashboardFollowItem icon={<Archive size={16} />} title="发布已定稿文章" desc={`${finalNotUsed} 篇定稿文章尚未使用`} onClick={() => openDrilldown({ view: "article", articleStatus: "approved" })} />
          </div>
        </section>
      </div>
    </div>
  );
}

function DashboardMeta({ label, value }: { label: string; value: string }) {
  return <div className="dashboard-meta-item"><span>{label}</span><strong>{value}</strong></div>;
}

function DashboardProgressPanel({ title, subtitle, badge, rows, onOpen }: {
  title: string;
  subtitle: string;
  badge: string;
  rows: DashboardProgressRow[];
  onOpen: (target: DashboardDrilldown) => void;
}) {
  return (
    <section className="dashboard-panel">
      <div className="dashboard-panel-head">
        <div>
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
        <Chip text={badge} type={rows.length ? "brand" : "warn"} />
      </div>
      <div className="dashboard-progress-list">
        {rows.length ? rows.map(row => (
          <button className="dashboard-progress-row" key={row.id} onClick={() => onOpen(row.drilldown)}>
            <div>
              <strong>{row.label}</strong>
              <span>{row.completed} 篇已定稿 / {row.plans} 篇规划</span>
            </div>
            <ProgressMeter percent={row.percent} tone="green" />
            <b>{row.percent}%</b>
          </button>
        )) : <p className="muted">暂无可统计的规划。</p>}
      </div>
    </section>
  );
}

function DashboardKpiCard({ label, value, total, caption, tone, onClick }: {
  label: string;
  value: number;
  total: number;
  caption: string;
  tone: string;
  onClick: () => void;
}) {
  return (
    <button className="dashboard-kpi-card" onClick={onClick}>
      <span>{label}</span>
      <strong>{value}<small>/ {total || 0}</small></strong>
      <ProgressMeter percent={percentOf(value, total)} tone={tone} />
      <em>{caption}</em>
    </button>
  );
}

function DashboardStageBar({ label, value, total, tone }: { label: string; value: number; total: number; tone: string }) {
  return (
    <div className="dashboard-stage-bar">
      <span>{label}</span>
      <ProgressMeter percent={percentOf(value, total)} tone={tone} />
      <strong>{value}</strong>
    </div>
  );
}

function ProgressMeter({ percent, tone }: { percent: number; tone: string }) {
  return <span className={`progress-meter ${tone}`}><i style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} /></span>;
}

function DashboardFollowItem({ icon, title, desc, onClick }: { icon: React.ReactNode; title: string; desc: string; onClick: () => void }) {
  return (
    <button className="follow-item" onClick={onClick}>
      <span>{icon}</span>
      <div><strong>{title}</strong><small>{desc}</small></div>
      <ArrowUpRight size={15} />
    </button>
  );
}

function UploadView(props: {
  project: Project;
  data: DerivedData;
  run: (action: () => Promise<unknown>, success: string) => Promise<void>;
  runBackendStep: (step: WorkflowStep, payload?: Record<string, unknown>) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
  dismissedJobIds: Set<string>;
  dismissJob: (jobId: string) => void;
  cancelJob: (jobId: string) => Promise<void>;
}) {
  const { project, data, run, runBackendStep, confirmBackendStep, dismissedJobIds, dismissJob, cancelJob } = props;
  const [confirmRegenerateIntake, setConfirmRegenerateIntake] = useState(false);
  const [editingIntakeRow, setEditingIntakeRow] = useState<IntakeRow | null>(null);
  const allMaterialsParsed = project.materials.length > 0 && project.materials.every(material => material.status === "parsed");
  const materialsRunning = project.steps.materials.status === "running";
  const parseDisabled = materialsRunning || project.materials.length === 0 || (allMaterialsParsed && project.steps.materials.status === "confirmed");
  const intakeHasOutput = Object.keys(project.steps.intake.output || {}).length > 0;
  const intakeRunning = project.steps.intake.status === "running";
  const intakeButtonText = intakeRunning ? "生成中" : intakeHasOutput ? "重新生成抽取表" : "生成抽取表";
  const intakeOutputUnrecognized = project.steps.intake.status === "completed" && !data.intakeRows.length && Object.keys(project.steps.intake.output || {}).length > 0;
  const confirmedIntakeRows = data.intakeRows.filter(row => intakeRowPersisted(row)).length;
  async function confirmIntakeRow(row: IntakeRow) {
    await run(async () => {
      await api.updateItem(project.id, "intake", row.id, { status: "已确认" });
    }, `${row.field} 已确认。`);
  }
  async function saveIntakeRow(row: IntakeRow, value: string) {
    await run(async () => {
      await api.updateItem(project.id, "intake", row.id, { value });
    }, `${row.field} 已修改并同步输出文件。`);
    setEditingIntakeRow(null);
  }
  async function deleteMaterial(material: Project["materials"][number]) {
    await run(async () => {
      await api.deleteMaterial(project.id, material.id);
    }, `${stripSlotPrefix(material.filename)} 已删除，请重新解析资料。`);
  }
  return (
    <div className="section-stack">
      <div className="stat-row">
        <Stat value={materialSlots.filter(slot => slot.required).length} label="固定必填资料入口" />
        <Stat value={project.materials.length} label="已上传资料" />
        <Stat value={data.intakeRows.length} label="抽取字段" />
        <Stat value={confirmedIntakeRows} label="已确认字段" />
      </div>
      <Panel title="资料入口" icon={<FileArchive size={16} />}>
        <div className="upload-strip">
          <button className="btn primary" disabled={parseDisabled} onClick={() => run(async () => {
            await api.parseMaterials(project.id);
          }, "资料解析任务已提交，下面可查看进度。")}>
            <ScanText size={15} />{materialsRunning ? "解析中" : parseDisabled && allMaterialsParsed ? "已全部解析" : "解析资料"}
          </button>
          <button
            className="btn"
            disabled={project.steps.materials.status !== "confirmed" || intakeRunning}
            onClick={() => {
              if (intakeHasOutput) setConfirmRegenerateIntake(true);
              else void runBackendStep("intake");
            }}
          >
            {intakeButtonText}
          </button>
        </div>
        {confirmRegenerateIntake && (
          <div className="modal-backdrop" role="presentation">
            <div className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="regenerate-intake-title">
              <h2 id="regenerate-intake-title">重新生成抽取表？</h2>
              <p>确认后会清空并覆盖当前项目信息自动抽取结果。取消则不会做任何更改。</p>
              <div className="actions end">
                <button className="btn" onClick={() => setConfirmRegenerateIntake(false)}>取消</button>
                <button className="btn primary" onClick={() => {
                  setConfirmRegenerateIntake(false);
                  void runBackendStep("intake", { force: true });
                }}>确认重新生成</button>
              </div>
            </div>
          </div>
        )}
        <StepProgressPanel project={project} dismissedJobIds={dismissedJobIds} dismissJob={dismissJob} cancelJob={cancelJob} />
        <div className="slot-grid">
          {materialSlots.map((slot, index) => {
            const materials = project.materials.filter(material => material.filename.startsWith(`${slot.id}__`));
            const slotStatus = resolveSlotStatus(materials, slot.required);
            return (
              <article className={`slot-card ${slot.required ? "required" : "optional"}`} key={slot.id}>
                <div className="slot-head">
                  <div><h3>{slot.name}</h3><p>{slot.desc}</p></div>
                  <Status status={slotStatus} />
                </div>
                <div className="slot-body">
                  <div className="slot-file-state">
                    <div className={`slot-file-icon ${materials.length ? "filled" : ""}`}><FileText size={16} /></div>
                    <div className="slot-file-copy">
                      {materials.length ? materials.map(material => (
                        <div className="slot-file-row" key={material.id}>
                          <div className="slot-file-info">
                            <strong>{stripSlotPrefix(material.filename)}</strong>
                            <small>{materialParseMeta(material)}</small>
                          </div>
                          <button
                            className="icon-btn danger"
                            type="button"
                            disabled={project.steps.materials.status === "running"}
                            onClick={() => void deleteMaterial(material)}
                            aria-label={`删除 ${stripSlotPrefix(material.filename)}`}
                            title="删除资料"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      )) : <strong>未上传资料</strong>}
                      <span>{materials.length ? describeSlotFiles(materials) : slot.required ? "必填资料入口" : "可选补充入口"}</span>
                    </div>
                  </div>
                  <label className="slot-upload">
                    <Upload size={15} />
                    {materials.length ? "替换/追加" : "上传"}
                    <input type="file" multiple onChange={event => {
                      const selected = event.target.files;
                      if (!selected || selected.length === 0) return;
                      const renamed = renameFilesForSlot(selected, slot.id);
                      void run(async () => {
                        await api.uploadMaterials(project.id, renamed);
                      }, `${slot.name} 已上传。`);
                      event.target.value = "";
                    }} />
                  </label>
                </div>
              </article>
            );
          })}
        </div>
      </Panel>

      <Panel title="项目信息自动抽取与确认" icon={<TableProperties size={16} />} aside={<Chip text={`${data.intakeRows.length} 项`} type={data.intakeRows.length ? "brand" : "warn"} />}>
        {data.intakeRows.length ? (
          <>
            <div className="confirm-table">
              {data.intakeRows.map(row => (
                <div className="confirm-row" key={row.id}>
                  <div className="confirm-field">{row.field}</div>
                  <div>{row.value}</div>
                  <div className="source">{row.source}</div>
                  <Chip text={row.confidence || "未标注"} type={row.confidence === "高" ? "good" : "warn"} />
                  <Chip text={row.status || "待确认"} type={intakeRowPersisted(row) ? "good" : "warn"} />
                  <div className="row-actions">
                    <button className="btn" onClick={() => setEditingIntakeRow(row)}>修改</button>
                    <button className="btn" disabled={row.status === "已确认"} onClick={() => void confirmIntakeRow(row)}>{row.status === "已确认" ? "已确认" : "确认"}</button>
                  </div>
                </div>
              ))}
            </div>
            <div className="actions end">
              <button className="btn primary" disabled={project.steps.intake.status !== "completed"} onClick={() => confirmBackendStep("intake")}>确认项目信息</button>
            </div>
          </>
        ) : intakeOutputUnrecognized ? (
          <EmptyPanelText text="抽取表已生成，但当前输出格式未识别。请查看项目 JSON 原始输出，或重新生成抽取表。" />
        ) : (
          <EmptyPanelText text="暂无抽取结果。请先上传资料、解析资料，然后点击“生成抽取表”。" />
        )}
      </Panel>
      {editingIntakeRow && (
        <IntakeEditModal
          row={editingIntakeRow}
          onClose={() => setEditingIntakeRow(null)}
          onSave={(value) => void saveIntakeRow(editingIntakeRow, value)}
        />
      )}
    </div>
  );
}

function IntakeEditModal({
  row,
  onClose,
  onSave
}: {
  row: IntakeRow;
  onClose: () => void;
  onSave: (value: string) => void;
}) {
  const [value, setValue] = useState(row.value);
  const canSave = Boolean(value.trim()) && value !== row.value;

  useEffect(() => {
    setValue(row.value);
  }, [row]);

  return (
    <div className="modal-backdrop" role="presentation">
      <form
        className="confirm-modal intake-edit-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="intake-edit-title"
        onSubmit={event => {
          event.preventDefault();
          if (canSave) onSave(value.trim());
        }}
      >
        <h2 id="intake-edit-title">修改项目信息</h2>
        <p>{row.field}</p>
        <div className="detail-meta">
          <Chip text={row.confidence || "未标注"} type={row.confidence === "高" ? "good" : "warn"} />
          <Chip text={row.status || "待确认"} />
        </div>
        <label className="field-block">
          <span>推断值</span>
          <textarea className="notes-area" value={value} onChange={event => setValue(event.target.value)} />
        </label>
        <label className="field-block">
          <span>来源依据</span>
          <textarea className="notes-area" value={row.source} readOnly />
        </label>
        <div className="actions end">
          <button type="button" className="btn" onClick={onClose}>取消</button>
          <button type="submit" className="btn primary" disabled={!canSave}>保存修改</button>
        </div>
      </form>
    </div>
  );
}

function PlanningView(props: {
  project: Project;
  data: DerivedData;
  tab: PlanningTab;
  setTab: (tab: PlanningTab) => void;
  selectedPlans: Set<string>;
  setSelectedPlans: React.Dispatch<React.SetStateAction<Set<string>>>;
  runBackendStep: (step: WorkflowStep, payload?: Record<string, unknown>) => Promise<void>;
  confirmBreakthroughKeywords: (keywords: string[]) => Promise<void>;
  setCurrent: (view: AppView) => void;
  openDetail: (step: EditableStep, item: ContentItem) => void;
  dismissedJobIds: Set<string>;
  dismissJob: (jobId: string) => void;
  cancelJob: (jobId: string) => Promise<void>;
  dashboardDrilldown?: DashboardDrilldown | null;
  clearDashboardDrilldown?: () => void;
  onProjectUpdate: (project: Project) => void;
}) {
  const {
    project,
    data,
    tab,
    setTab,
    selectedPlans,
    setSelectedPlans,
    runBackendStep,
    confirmBreakthroughKeywords,
    setCurrent,
    openDetail,
    dismissedJobIds,
    dismissJob,
    cancelJob,
    dashboardDrilldown,
    clearDashboardDrilldown,
    onProjectUpdate
  } = props;
  const [regenerateStep, setRegenerateStep] = useState<WorkflowStep | null>(null);
  const [contentPlan, setContentPlan] = useState<ContentPlan | null>(null);
  const [contentPlanOpen, setContentPlanOpen] = useState(false);
  const [contentPlanLoading, setContentPlanLoading] = useState(false);
  const [contentPlanError, setContentPlanError] = useState("");
  const [matrixImportDraftId, setMatrixImportDraftId] = useState("");
  const [matrixImportDraft, setMatrixImportDraft] = useState<MatrixImportDraft | null>(null);
  const [matrixImportOpen, setMatrixImportOpen] = useState(false);
  const [matrixImportConfirmOpen, setMatrixImportConfirmOpen] = useState(false);
  const [matrixImportLoading, setMatrixImportLoading] = useState(false);
  const [matrixImportError, setMatrixImportError] = useState("");
  const [expandedPlanGroups, setExpandedPlanGroups] = useState<Set<string>>(new Set());
  const [selectedBreakthroughKeywords, setSelectedBreakthroughKeywords] = useState<Set<string>>(new Set());
  const [planningFilters, setPlanningFilters] = useState<PlanningFilterState>(emptyPlanningFilters);
  const activeBackendStep: WorkflowStep = tab === "matrix" ? "matrix" : tab === "demand_matrix" ? "demand_matrix" : "breakthrough";
  const stepState = project.steps[activeBackendStep];
  const allRows = tab === "matrix" ? data.matrixPlans : tab === "demand_matrix" ? data.demandMatrixPlans : data.breakthroughPlans;
  const rows = filterPlanningItems(allRows, planningFilters);
  const activeStepJobRunning = project.jobs.some(job => job.step === activeBackendStep && ["queued", "running", "cancelling"].includes(job.status));
  const isRunning = stepState?.status === "running" || activeStepJobRunning;
  const blockedMessage = stepState ? outputBlockerMessage(stepState.output) : "";
  const isBlocked = Boolean(blockedMessage);
  const hasRows = allRows.length > 0;
  const readOnlyPlanning = activeBackendStep === "demand_matrix";
  const hasStepOutput = Boolean(stepState && Object.keys(stepState.output || {}).length > 0);
  const planningLabel = tab === "matrix" ? "内容矩阵" : tab === "demand_matrix" ? "需求驱动矩阵" : "逐词击破";
  const keywordOptions = uniqueStrings([...data.matrixKeywords, ...data.confirmedBreakthroughKeywords]);
  const selectedKeywordList = keywordOptions.filter(keyword => selectedBreakthroughKeywords.has(keyword));
  const breakthroughScopeKeywordList = data.confirmedBreakthroughKeywords;
  const completedBreakthroughKeywordList = completeBreakthroughKeywords(data.breakthroughPlans);
  const matrixGroupMeta = new Map(data.matrixIntentGroups.map(group => [group.name, group]));
  const demandMatrixGroupMeta = new Map(data.demandMatrixIntentGroups.map(group => [group.name, group]));
  const planningKeywordOptions = projectAllowedKeywords(project).length ? projectAllowedKeywords(project) : uniqueStrings(allRows.map(item => item.keyword).filter(Boolean));
  const planningTypeOptions = orderedArticleTypes(allRows);
  const matrixContentPlanReady = project.steps.matrix.status === "completed" || project.steps.matrix.status === "confirmed";
  const demandMatrixContentPlanReady = project.steps.demand_matrix?.status === "completed" || project.steps.demand_matrix?.status === "confirmed";
  const matrixContentPlanStats = matrixContentPlanSummary(project, data);
  const demandMatrixContentPlanStats = demandMatrixContentPlanSummary(project, data);
  const demandMatrixReady = demandMatrixPrerequisitesReady(project);
  const demandMatrixDisabledReason = demandMatrixReady ? "" : demandMatrixPrerequisiteMessage(project);
  const matrixImportReady = matrixImportPrerequisitesReady(project);
  const matrixImportDisabledReason = matrixImportReady ? "" : "请先完成资料解析和项目信息抽取，再导入外部内容矩阵。";
  const groupedRows = tab === "matrix"
    ? groupMatrixRowsByIntent(rows, data.matrixIntentGroups)
    : tab === "demand_matrix"
      ? groupMatrixRowsByIntent(rows, data.demandMatrixIntentGroups)
      : groupBy(rows, "keyword");
  const hasBreakthroughScopeKeywords = breakthroughScopeKeywordList.length > 0;
  const needsBreakthroughKeywords = activeBackendStep === "breakthrough" && !hasBreakthroughScopeKeywords;
  const breakthroughMissingTypes = missingBreakthroughTypes(data.breakthroughPlans, breakthroughScopeKeywordList);
  const breakthroughMissingCount = Object.values(breakthroughMissingTypes).reduce((total, types) => total + types.length, 0);
  const breakthroughNewKeywordCount = Object.values(breakthroughMissingTypes).filter(types => types.length === coreArticleTypes.length).length;
  const breakthroughComplete = activeBackendStep === "breakthrough" && hasStepOutput && hasBreakthroughScopeKeywords && breakthroughMissingCount === 0;
  const canRegenerateCurrentStep = Boolean((activeBackendStep === "matrix" || activeBackendStep === "demand_matrix") && hasStepOutput && !isRunning);
  const canForceRegenerateBreakthrough = Boolean(activeBackendStep === "breakthrough" && hasStepOutput && !isRunning && !needsBreakthroughKeywords);
  const generationLocked = isRunning || needsBreakthroughKeywords || breakthroughComplete || (activeBackendStep === "demand_matrix" && !demandMatrixReady);
  const isConfirmed = stepState?.status === "confirmed";
  const planningSourceRows = [...data.matrixPlans, ...data.breakthroughPlans];
  const planningSourceIds = new Set(planningSourceRows.map(item => item.id));
  const selectedPlanItems = planningSourceRows.filter(item => selectedPlans.has(item.id));
  const briefBySource = new Map(data.briefs.map(item => [item.sourceId, item]));
  const articleByBriefId = new Map(data.articles.map(item => [item.briefId || item.id, item]));
  const pendingBriefSources = selectedPlanItems.filter(item => !briefIsGenerated(briefBySource.get(item.sourceId)));
  const selectedCount = selectedPlanItems.length;
  const planningBriefJob = activeBackendStep === "demand_matrix" ? undefined : briefProgressForPlanning(project, activeBackendStep);
  const selectedBriefButtonText = selectedCount === 0
    ? "生成选中 Brief"
    : pendingBriefSources.length === 0
      ? "选中项均已有 Brief"
      : `生成选中 Brief（${pendingBriefSources.length} 篇）`;
  const confirmedKeywordSignature = breakthroughScopeKeywordList.join("\u0001");
  const emptyText = isRunning
    ? `后台 Agent 正在生成${planningLabel}，可以点击“刷新状态”查看进度。`
    : activeBackendStep === "demand_matrix" && !demandMatrixReady
      ? demandMatrixDisabledReason
    : needsBreakthroughKeywords
      ? "逐词击破是可选增强；如需生成逐词击破规划，请先回内容矩阵 Tab 勾选并保存关键词。"
    : isBlocked
      ? blockedMessage
      : stepState?.status === "failed"
        ? stepState.error || "任务失败，请调整后重新生成。"
        : `点击“生成${planningLabel}”后，这里会展示后台 Agent 的真实输出。`;
  useEffect(() => {
    setSelectedBreakthroughKeywords(new Set());
  }, [project.id, confirmedKeywordSignature]);
  useEffect(() => {
    setPlanningFilters(emptyPlanningFilters);
  }, [project.id, tab]);
  useEffect(() => {
    if (dashboardDrilldown?.view !== "planning") return;
    setPlanningFilters({
      keyword: dashboardDrilldown.keyword || "all",
      articleType: dashboardDrilldown.articleType || "all"
    });
    if (dashboardDrilldown.tab) setTab(dashboardDrilldown.tab);
    clearDashboardDrilldown?.();
  }, [dashboardDrilldown, clearDashboardDrilldown, setTab]);
  useEffect(() => {
    setContentPlan(null);
    setContentPlanOpen(false);
    setContentPlanError("");
  }, [project.id, tab]);
  useEffect(() => {
    setMatrixImportDraftId("");
    setMatrixImportDraft(null);
    setMatrixImportOpen(false);
    setMatrixImportConfirmOpen(false);
    setMatrixImportError("");
  }, [project.id]);
  useEffect(() => {
    if (!matrixImportDraftId) return;
    let cancelled = false;
    void api.getMatrixImportPlan(project.id, matrixImportDraftId)
      .then(draft => {
        if (cancelled) return;
        setMatrixImportDraft(draft);
        if (draft.status === "completed") setMatrixImportOpen(true);
        if (draft.status === "failed" && draft.error) setMatrixImportError(draft.error);
      })
      .catch(error => {
        if (!cancelled) setMatrixImportError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      cancelled = true;
    };
  }, [project.id, project.updated_at, matrixImportDraftId]);
  async function confirmKeywordsForBreakthrough() {
    if (!selectedKeywordList.length) return;
    await confirmBreakthroughKeywords(selectedKeywordList);
    setTab("breakthrough");
  }
  async function generateSelectedBriefs() {
    if (!pendingBriefSources.length) return;
    await runBackendStep("brief", { selected_sources: pendingBriefSources.map(toSourcePayload) });
    setCurrent("brief");
  }
  async function openContentPlan() {
    const source = tab === "demand_matrix" ? "demand_matrix" : "matrix";
    const ready = source === "demand_matrix" ? demandMatrixContentPlanReady && data.demandMatrixPlans.length > 0 : matrixContentPlanReady && data.matrixPlans.length > 0;
    if (!ready) {
      setContentPlanError(source === "demand_matrix" ? "请先生成需求驱动矩阵。" : "请先生成内容矩阵。");
      return;
    }
    setContentPlanLoading(true);
    setContentPlanError("");
    try {
      const next = await api.getContentPlan(project.id, source);
      setContentPlan(next);
      setContentPlanOpen(true);
    } catch (error) {
      setContentPlanError(error instanceof Error ? error.message : String(error));
    } finally {
      setContentPlanLoading(false);
    }
  }
  async function exportContentPlan() {
    const source = tab === "demand_matrix" ? "demand_matrix" : "matrix";
    const ready = source === "demand_matrix" ? demandMatrixContentPlanReady && data.demandMatrixPlans.length > 0 : matrixContentPlanReady && data.matrixPlans.length > 0;
    if (!ready) {
      setContentPlanError(source === "demand_matrix" ? "请先生成需求驱动矩阵。" : "请先生成内容矩阵。");
      return;
    }
    setContentPlanLoading(true);
    setContentPlanError("");
    try {
      const blob = await api.exportContentPlanPdf(project.id, source);
      const prefix = source === "demand_matrix" ? "需求驱动内容规划" : "内容规划";
      downloadBlob(blob, `${prefix}-${slugValue(project.name, "content-plan")}-${new Date().toISOString().slice(0, 10)}.pdf`);
    } catch (error) {
      setContentPlanError(error instanceof Error ? error.message : String(error));
    } finally {
      setContentPlanLoading(false);
    }
  }
  async function importMatrixPlan(file: File) {
    if (!matrixImportReady) {
      setMatrixImportError(matrixImportDisabledReason);
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setMatrixImportError("请上传 PDF 格式的内容规划文件。");
      return;
    }
    setMatrixImportLoading(true);
    setMatrixImportError("");
    try {
      const response = await api.importMatrixPlan(project.id, file);
      onProjectUpdate(response.project);
      setMatrixImportDraftId(response.draft_id);
      setMatrixImportDraft(null);
      setMatrixImportOpen(false);
    } catch (error) {
      setMatrixImportError(error instanceof Error ? error.message : String(error));
    } finally {
      setMatrixImportLoading(false);
    }
  }
  async function applyMatrixImport() {
    if (!matrixImportDraft) return;
    setMatrixImportLoading(true);
    setMatrixImportError("");
    try {
      const response = await api.applyMatrixImportPlan(project.id, matrixImportDraft.id);
      onProjectUpdate(response.project);
      setSelectedPlans(new Set());
      setContentPlan(null);
      setContentPlanOpen(false);
      setMatrixImportDraft(response.draft);
      setMatrixImportOpen(false);
      setMatrixImportConfirmOpen(false);
    } catch (error) {
      setMatrixImportError(error instanceof Error ? error.message : String(error));
    } finally {
      setMatrixImportLoading(false);
    }
  }
  function setGroupSelection(groupedRows: ContentItem[], selected: boolean) {
    setSelectedPlans(current => {
      const next = new Set(current);
      groupedRows.forEach(item => {
        if (selected) next.add(item.id);
        else next.delete(item.id);
      });
      return next;
    });
  }
  function setKeywordSelection(keyword: string, selected: boolean) {
    setSelectedBreakthroughKeywords(current => {
      const next = new Set(current);
      if (selected) next.add(keyword);
      else next.delete(keyword);
      return next;
    });
  }
  function togglePlanGroup(groupKey: string) {
    setExpandedPlanGroups(current => toggleSet(current, groupKey));
  }
  const breakthroughRunPayload = activeBackendStep === "breakthrough" ? { confirmed_keywords: breakthroughScopeKeywordList } : undefined;
  const generationButtonText = planningGenerationButtonText({
    tab,
    isRunning,
    needsBreakthroughKeywords,
    canRegenerateCurrentStep,
    breakthroughComplete,
    hasBreakthroughOutput: activeBackendStep === "breakthrough" && hasStepOutput,
    breakthroughMissingCount,
    breakthroughNewKeywordCount,
    planningLabel
  });
  return (
    <div className="section-stack">
      <div className="bulk-bar">
        <div>
          <strong>{tab === "matrix" ? "内容矩阵整体规划" : tab === "demand_matrix" ? "需求驱动内容矩阵" : "逐词击破六类规划"}</strong>
          <span>
            {hasRows
              ? `后台 Agent 已生成 ${rows.length} 条规划。`
              : isRunning
                ? "后台 Agent 正在生成，请稍等。"
                : needsBreakthroughKeywords
                  ? "请先在内容矩阵中选择关键词后再生成逐词击破；内容矩阵规划可直接生成 Brief。"
                  : isBlocked
                    ? "需要先补充或确认关键词，暂未生成正式规划。"
                    : "暂无规划结果。"}
          </span>
        </div>
        <div className="actions">
          {activeBackendStep !== "breakthrough" && (
            <button
              className="btn"
              disabled={generationLocked}
              onClick={() => {
                if (canRegenerateCurrentStep) setRegenerateStep(activeBackendStep);
                else void runBackendStep(activeBackendStep, {});
              }}
            >
              {generationButtonText}
            </button>
          )}
          {canForceRegenerateBreakthrough && <button className="btn" onClick={() => setRegenerateStep("breakthrough")}>重新生成全部逐词击破</button>}
        </div>
      </div>
      {regenerateStep && (
        <div className="modal-backdrop" role="presentation">
          <div className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="regenerate-planning-title">
            <h2 id="regenerate-planning-title">重新生成{stepLabel(regenerateStep)}？</h2>
            <p>{regenerateStep === "breakthrough" ? "确认后会清空并覆盖当前全部逐词击破规划。取消则不会做任何更改。" : `确认后会立即清空当前${stepLabel(regenerateStep)}结果或错误状态，并用后台 Agent 的新结果覆盖。取消则不会做任何更改。`}</p>
            <div className="actions end">
              <button className="btn" onClick={() => setRegenerateStep(null)}>取消</button>
              <button className="btn primary" onClick={() => {
                const step = regenerateStep;
                setRegenerateStep(null);
                setSelectedPlans(current => {
                  const staleIds = new Set((step === "matrix" ? data.matrixPlans : step === "demand_matrix" ? data.demandMatrixPlans : data.breakthroughPlans).map(item => item.id));
                  return new Set([...current].filter(id => !staleIds.has(id)));
                });
                void runBackendStep(step, step === "breakthrough" ? { force: true, confirmed_keywords: breakthroughScopeKeywordList } : { force: true });
              }}>确认重新生成</button>
            </div>
          </div>
        </div>
      )}
      <StepProgressPanel project={project} steps={[activeBackendStep]} dismissedJobIds={dismissedJobIds} dismissJob={dismissJob} cancelJob={cancelJob} />
      <JobProgress job={planningBriefJob} dismissedJobIds={dismissedJobIds} onDismiss={dismissJob} onCancel={cancelJob} />
      <div className="tabs">
        <button className={tab === "matrix" ? "active" : ""} onClick={() => setTab("matrix")}>内容矩阵</button>
        <button className={tab === "demand_matrix" ? "active" : ""} onClick={() => setTab("demand_matrix")}>需求驱动矩阵</button>
        <button className={tab === "breakthrough" ? "active" : ""} onClick={() => setTab("breakthrough")}>逐词击破</button>
      </div>
      {tab === "matrix" && (
        <ContentPlanCard
          ready={matrixContentPlanReady && data.matrixPlans.length > 0}
          stats={matrixContentPlanStats}
          loading={contentPlanLoading}
          error={contentPlanError}
          importing={matrixImportLoading || matrixImportDraft?.status === "queued" || matrixImportDraft?.status === "running"}
          importError={matrixImportError}
          importDraft={matrixImportDraft}
          importReady={matrixImportReady}
          importDisabledReason={matrixImportDisabledReason}
          onImport={(file) => void importMatrixPlan(file)}
          onPreview={() => void openContentPlan()}
          onExport={() => void exportContentPlan()}
        />
      )}
      {tab === "demand_matrix" && (
        <DemandMatrixPlanCard
          ready={demandMatrixContentPlanReady && data.demandMatrixPlans.length > 0}
          stats={demandMatrixContentPlanStats}
          loading={contentPlanLoading}
          error={contentPlanError}
          canGenerate={demandMatrixReady}
          disabledReason={demandMatrixDisabledReason}
          onPreview={() => void openContentPlan()}
          onExport={() => void exportContentPlan()}
        />
      )}
      {matrixImportOpen && matrixImportDraft && (
        <MatrixImportPreviewModal
          draft={matrixImportDraft}
          loading={matrixImportLoading}
          error={matrixImportError}
          onClose={() => setMatrixImportOpen(false)}
          onApply={() => setMatrixImportConfirmOpen(true)}
        />
      )}
      {matrixImportConfirmOpen && matrixImportDraft && (
        <div className="modal-backdrop" role="presentation">
          <div className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="apply-matrix-import-title">
            <h2 id="apply-matrix-import-title">确认导入并覆盖内容矩阵？</h2>
            <p>确认后会用「{matrixImportDraft.filename}」识别出的内容规划覆盖当前内容矩阵。已有 Brief 和正文不会自动删除。</p>
            <div className="actions end">
              <button className="btn" disabled={matrixImportLoading} onClick={() => setMatrixImportConfirmOpen(false)}>取消</button>
              <button className="btn primary" disabled={matrixImportLoading} onClick={() => void applyMatrixImport()}>
                {matrixImportLoading ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}确认覆盖
              </button>
            </div>
            {matrixImportError && <p className="item-error">{matrixImportError}</p>}
          </div>
        </div>
      )}
      {contentPlanOpen && contentPlan && (
        <ContentPlanPreviewModal
          plan={contentPlan}
          loading={contentPlanLoading}
          onClose={() => setContentPlanOpen(false)}
          onExport={() => void exportContentPlan()}
        />
      )}
      <div className="planning-filter-strip">
        <div>
          <strong>规划筛选</strong>
          <span>{rows.length === allRows.length ? `当前显示全部 ${allRows.length} 条规划` : `当前显示 ${rows.length}/${allRows.length} 条规划`}</span>
        </div>
        <label>
          <span>关键词</span>
          <select value={planningFilters.keyword} onChange={event => setPlanningFilters(current => ({ ...current, keyword: event.target.value }))}>
            <option value="all">全部</option>
            {planningKeywordOptions.map(keyword => <option key={keyword} value={keyword}>{keyword}</option>)}
          </select>
        </label>
        <label>
          <span>文章类型</span>
          <select value={planningFilters.articleType} onChange={event => setPlanningFilters(current => ({ ...current, articleType: event.target.value }))}>
            <option value="all">全部</option>
            {planningTypeOptions.map(type => <option key={type} value={type}>{type}</option>)}
          </select>
        </label>
        <button className="btn" disabled={planningFilters.keyword === "all" && planningFilters.articleType === "all"} onClick={() => setPlanningFilters(emptyPlanningFilters)}>
          <RefreshCw size={15} />重置筛选
        </button>
      </div>
      {tab === "matrix" && (
        <BreakthroughKeywordSelection
          keywords={keywordOptions}
          selectedKeywords={selectedBreakthroughKeywords}
          confirmedKeywords={completedBreakthroughKeywordList}
          onToggle={setKeywordSelection}
          onSelectAll={() => setSelectedBreakthroughKeywords(new Set(keywordOptions))}
          onClear={() => setSelectedBreakthroughKeywords(new Set())}
          onConfirm={() => void confirmKeywordsForBreakthrough()}
        />
      )}
      {tab === "breakthrough" && (
        <div className={`keyword-confirmation-summary ${hasBreakthroughScopeKeywords ? "confirmed" : "missing"}`}>
          <div>
            <strong>{breakthroughKeywordSummaryTitle(breakthroughScopeKeywordList)}</strong>
            <span>{breakthroughKeywordSummaryText(breakthroughScopeKeywordList)}</span>
          </div>
          {hasBreakthroughScopeKeywords ? (
            <button className="btn primary" disabled={generationLocked} onClick={() => void runBackendStep("breakthrough", breakthroughRunPayload)}>
              {generationButtonText}
            </button>
          ) : (
            <button className="btn" onClick={() => setTab("matrix")}>去选择关键词</button>
          )}
        </div>
      )}
      {!readOnlyPlanning && (
        <div className="bulk-bar selection-bar">
          <div>
            <strong>已选 {selectedCount} 篇规划</strong>
            <span>{selectedCount ? `其中 ${pendingBriefSources.length} 篇尚未生成 Brief。` : "先勾选内容矩阵或逐词击破里的规划。"}</span>
          </div>
          <div className="actions">
            <button className="btn" disabled={!selectedCount} onClick={() => setSelectedPlans(current => new Set([...current].filter(id => !planningSourceIds.has(id))))}>清空选择</button>
            <button className="btn primary" disabled={!pendingBriefSources.length} onClick={() => void generateSelectedBriefs()}>{selectedBriefButtonText}</button>
          </div>
        </div>
      )}
      {rows.length ? (
        <div className="keyword-groups">
          {Object.entries(groupedRows).map(([groupName, groupRows]) => {
            const groupKey = `${activeBackendStep}:${groupName}`;
            const expanded = expandedPlanGroups.has(groupKey);
            const intentMeta = tab === "matrix" ? matrixGroupMeta.get(groupName) : tab === "demand_matrix" ? demandMatrixGroupMeta.get(groupName) : undefined;
            const groupTitle = readOnlyPlanning ? `${groupName}（${groupRows.length} 篇规划）` : `${groupName}（${planGroupStatsText(groupRows, selectedPlans, briefBySource)}）`;
            const groupSubtitle = intentMeta
              ? matrixIntentSubtitle(intentMeta)
              : tab === "matrix" || tab === "demand_matrix"
                ? matrixFallbackGroupSubtitle(groupRows)
                : "";
            return (
              <Panel
                key={groupName}
                title={groupTitle}
                subtitle={groupSubtitle}
                icon={<Search size={16} />}
                aside={
                  <PlanGroupAside
                    rows={groupRows}
                    selectedPlans={selectedPlans}
                    expanded={expanded}
                    readOnly={readOnlyPlanning}
                    onSelectionChange={setGroupSelection}
                    onToggleExpanded={() => togglePlanGroup(groupKey)}
                  />
                }
              >
                {expanded ? (
                  <div className="plan-list">
                    {groupRows.map(item => (
                      <PlanRow
                        key={item.id}
                        item={item}
                        selected={selectedPlans.has(item.id)}
                        readOnly={readOnlyPlanning}
                        brief={readOnlyPlanning ? undefined : briefBySource.get(item.sourceId)}
                        article={readOnlyPlanning ? undefined : articleForPlanItem(item, briefBySource, articleByBriefId)}
                        onToggle={() => setSelectedPlans(current => toggleSet(current, item.id))}
                        onOpen={() => openDetail(item.sourceStep === "breakthrough" ? "breakthrough" : item.sourceStep === "demand_matrix" ? "demand_matrix" : "matrix", item)}
                      />
                    ))}
                  </div>
                ) : null}
              </Panel>
            );
          })}
        </div>
      ) : (
        <Panel title={isRunning ? "正在生成规划" : isBlocked ? "需要确认关键词" : stepState?.status === "failed" ? "规划生成失败" : "暂无规划结果"} icon={isRunning ? <Loader2 className="spin" size={16} /> : isBlocked ? <CircleAlert size={16} /> : <Route size={16} />}>
          <EmptyPanelText text={emptyText} />
        </Panel>
      )}
    </div>
  );
}

function BreakthroughKeywordSelection({
  keywords,
  selectedKeywords,
  confirmedKeywords,
  onToggle,
  onSelectAll,
  onClear,
  onConfirm
}: {
  keywords: string[];
  selectedKeywords: Set<string>;
  confirmedKeywords: string[];
  onToggle: (keyword: string, selected: boolean) => void;
  onSelectAll: () => void;
  onClear: () => void;
  onConfirm: () => void;
}) {
  const selectedList = keywords.filter(keyword => selectedKeywords.has(keyword));
  const confirmedSet = new Set(confirmedKeywords);
  return (
    <Panel
      title="进入逐词击破的关键词"
      icon={<Search size={16} />}
      aside={<Chip text={`已选 ${selectedList.length}/${keywords.length}`} type={selectedList.length ? "brand" : "warn"} />}
    >
      {keywords.length ? (
        <div className="keyword-confirmation">
          <div className="keyword-confirmation-head">
            <p className="muted">从内容矩阵中选择要逐词拆成固定六类文章的关键词。保存后，逐词击破只会围绕这些关键词生成。</p>
            <div className="actions">
              <button className="btn compact" onClick={onSelectAll}>全选</button>
              <button className="btn compact" disabled={!selectedList.length} onClick={onClear}>清空</button>
            </div>
          </div>
          <div className="keyword-choice-grid">
            {keywords.map(keyword => {
              const checked = selectedKeywords.has(keyword);
              return (
                <label className={`keyword-choice ${checked ? "selected" : ""}`} key={keyword}>
                  <input type="checkbox" checked={checked} onChange={event => onToggle(keyword, event.target.checked)} />
                  <span>{keyword}</span>
                  {confirmedSet.has(keyword) && <Chip text="已确认" type="good" />}
                </label>
              );
            })}
          </div>
          <div className="actions end">
            <button className="btn primary" disabled={!selectedList.length} onClick={onConfirm}>保存关键词并进入逐词击破</button>
          </div>
        </div>
      ) : (
        <EmptyPanelText text="内容矩阵里暂未识别到可用于逐词击破的关键词。请先生成或重新生成内容矩阵。" />
      )}
    </Panel>
  );
}

function ContentPlanCard({
  ready,
  stats,
  loading,
  error,
  importing,
  importError,
  importDraft,
  importReady,
  importDisabledReason,
  onImport,
  onPreview,
  onExport
}: {
  ready: boolean;
  stats: ReturnType<typeof matrixContentPlanSummary>;
  loading: boolean;
  error: string;
  importing: boolean;
  importError: string;
  importDraft: MatrixImportDraft | null;
  importReady: boolean;
  importDisabledReason: string;
  onImport: (file: File) => void;
  onPreview: () => void;
  onExport: () => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const draftStatus = importDraft?.status;
  const draftStatusText = draftStatus === "completed"
    ? "识别完成，可预览导入"
    : draftStatus === "failed"
      ? "识别失败"
      : draftStatus === "applied"
        ? "已导入"
        : importing
          ? "正在识别 PDF"
          : importReady
            ? "可上传外部矩阵 PDF"
            : "需先完成资料与项目信息";
  const matrixSource = stats.source === "imported"
    ? `来源：外部导入${stats.importedFilename ? ` / ${stats.importedFilename}` : ""}`
    : ready
      ? "来源：系统生成"
      : "来源：未生成";
  return (
    <Panel
      title="内容规划报告"
      subtitle={ready ? "基于当前内容矩阵生成正式执行规划，可预览并导出 PDF。" : "可以生成内容矩阵，也可以导入你在本地生成好的外部内容矩阵；导入不会替代项目资料。"}
      icon={<FileText size={16} />}
      aside={<Chip text={stats.source === "imported" ? "外部导入" : ready ? "系统生成" : "未生成矩阵"} type={ready ? "good" : "warn"} />}
    >
      <div className="content-plan-card">
        <div className="content-plan-stats">
          <ContentPlanStat label="关键词" value={stats.keywordCount} />
          <ContentPlanStat label="文章规划" value={stats.planCount} />
          <ContentPlanStat label="文章类型" value={stats.articleTypeCount} />
          <ContentPlanStat label="证据缺口" value={stats.evidenceGapCount} />
          <ContentPlanStat label="执行排期" value={stats.hasSchedule ? "已生成" : "未生成"} />
        </div>
        <div className="actions">
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            hidden
            onChange={event => {
              const file = event.target.files?.[0];
              event.currentTarget.value = "";
              if (file) onImport(file);
            }}
          />
          <button className="btn" disabled={importing || !importReady} title={importReady ? "" : importDisabledReason} onClick={() => inputRef.current?.click()}>
            {importing ? <Loader2 className="spin" size={15} /> : <Upload size={15} />}导入外部内容矩阵 PDF
          </button>
          <button className="btn" disabled={!ready || loading} onClick={onPreview}>
            {loading ? <Loader2 className="spin" size={15} /> : <BookOpen size={15} />}查看内容规划
          </button>
          <button className="btn primary" disabled={!ready || loading} onClick={onExport}>
            {loading ? <Loader2 className="spin" size={15} /> : <Download size={15} />}导出内容规划 PDF
          </button>
        </div>
        <div className={`matrix-import-hint ${draftStatus === "failed" ? "failed" : importing ? "running" : draftStatus === "completed" || draftStatus === "applied" ? "completed" : ""}`}>
          <span>{draftStatusText} · {matrixSource}</span>
          <strong>{importDraft?.filename || (stats.boundMaterialCount ? `已绑定 ${stats.boundMaterialCount} 个资料` : importDisabledReason || "后续 Brief/正文仍读取资料与项目信息")}</strong>
        </div>
        {error && <p className="item-error">{error}</p>}
        {importError && <p className="item-error">{importError}</p>}
      </div>
    </Panel>
  );
}

function ContentPlanStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="content-plan-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DemandMatrixPlanCard({
  ready,
  stats,
  loading,
  error,
  canGenerate,
  disabledReason,
  onPreview,
  onExport
}: {
  ready: boolean;
  stats: ReturnType<typeof demandMatrixContentPlanSummary>;
  loading: boolean;
  error: string;
  canGenerate: boolean;
  disabledReason: string;
  onPreview: () => void;
  onExport: () => void;
}) {
  return (
    <Panel
      title="需求驱动内容规划报告"
      subtitle="用于查看和导出新版需求变量驱动矩阵；不进入 Brief 和正文生成。"
      icon={<FileText size={16} />}
      aside={<Chip text={ready ? "已生成" : canGenerate ? "可生成" : "缺需求报告"} type={ready ? "good" : "warn"} />}
    >
      <div className="content-plan-card">
        <div className="content-plan-stats">
          <ContentPlanStat label="关键词" value={stats.keywordCount} />
          <ContentPlanStat label="文章规划" value={stats.planCount} />
          <ContentPlanStat label="文章类型" value={stats.articleTypeCount} />
          <ContentPlanStat label="需求变量" value={stats.demandVariableCount} />
          <ContentPlanStat label="主题簇" value={stats.themeClusterCount} />
        </div>
        <div className="actions">
          <button className="btn" disabled={!ready || loading} onClick={onPreview}>
            {loading ? <Loader2 className="spin" size={15} /> : <BookOpen size={15} />}查看规划
          </button>
          <button className="btn primary" disabled={!ready || loading} onClick={onExport}>
            {loading ? <Loader2 className="spin" size={15} /> : <Download size={15} />}导出 PDF
          </button>
        </div>
        <div className={`matrix-import-hint ${ready ? "completed" : canGenerate ? "" : "failed"}`}>
          <span>{ready ? "需求驱动矩阵已生成" : canGenerate ? "可生成需求驱动矩阵" : "生成条件未满足"}</span>
          <strong>{ready ? "该矩阵仅用于查看和导出，不进入 Brief/正文链路。" : disabledReason}</strong>
        </div>
        {error && <p className="item-error">{error}</p>}
      </div>
    </Panel>
  );
}

function MatrixImportPreviewModal({
  draft,
  loading,
  error,
  onClose,
  onApply
}: {
  draft: MatrixImportDraft;
  loading: boolean;
  error: string;
  onClose: () => void;
  onApply: () => void;
}) {
  const output = isRecord(draft.output) ? draft.output : {};
  const items = normalizeItems(output, "matrix").filter(item => isCoreArticleType(item.type));
  const projectBlock = isRecord(output.project) ? output.project : {};
  const stats = isRecord(draft.stats) ? draft.stats : {};
  const warnings = readStringList({ warnings: draft.warnings || output.warnings || [] }, ["warnings"]);
  const itemCount = Number(stats.item_count || items.length || 0);
  const keywordCount = Number(stats.keyword_count || uniqueKeywords(items).length || 0);
  const articleTypeCount = Number(stats.article_type_count || orderedArticleTypes(items).length || 0);
  const intentGroupCount = Number(stats.intent_group_count || (Array.isArray(output.intent_groups) ? output.intent_groups.length : 0));
  return (
    <div className="modal-backdrop content-plan-backdrop" role="presentation">
      <div className="content-plan-modal matrix-import-modal" role="dialog" aria-modal="true" aria-labelledby="matrix-import-title">
        <div className="detail-head">
          <div>
            <span className="eyebrow">外部内容矩阵 PDF 导入预览</span>
            <h2 id="matrix-import-title">{draft.filename}</h2>
            <p>确认后会覆盖当前内容矩阵；已有 Brief 和正文不会自动删除。后续 Brief/正文仍会读取已解析资料与项目信息。</p>
          </div>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="content-plan-preview">
          <section className="content-plan-section">
            <div className="content-plan-section-head">
              <strong>识别摘要</strong>
              <span>{draft.parsed_chars?.toLocaleString("zh-CN") || 0} 字符</span>
            </div>
            <div className="content-plan-stats import-preview-stats">
              <ContentPlanStat label="关键词" value={keywordCount} />
              <ContentPlanStat label="文章规划" value={itemCount} />
              <ContentPlanStat label="文章类型" value={articleTypeCount} />
              <ContentPlanStat label="意图簇" value={intentGroupCount} />
              <ContentPlanStat label="导入状态" value={matrixImportStatusLabel(draft.status)} />
            </div>
          </section>
          <section className="content-plan-section">
            <div className="content-plan-section-head"><strong>项目口径</strong></div>
            <div className="content-plan-kv">
              <ContentPlanKv label="目标品牌" value={readString(projectBlock, ["target_brand"], "未识别")} />
              <ContentPlanKv label="目标产品" value={readString(projectBlock, ["target_product_or_solution"], "未识别")} />
              <ContentPlanKv label="目标品类" value={readString(projectBlock, ["target_category"], "未识别")} />
              <ContentPlanKv label="竞品" value={readStringList(projectBlock, ["competitors"]).join("、") || "未识别"} />
            </div>
          </section>
          {warnings.length > 0 && (
            <section className="content-plan-section import-warning-section">
              <div className="content-plan-section-head"><strong>识别提示</strong></div>
              <div className="content-plan-list">
                {warnings.map((warning, index) => <p key={`${warning}-${index}`}>{warning}</p>)}
              </div>
            </section>
          )}
          <section className="content-plan-section">
            <div className="content-plan-section-head">
              <strong>文章规划列表</strong>
              <span>{items.length} 篇</span>
            </div>
            <div className="content-plan-table-wrap matrix-import-table-wrap">
              <table className="content-plan-table content-plan-table-first-round-plans">
                <thead>
                  <tr>
                    <th>关键词</th>
                    <th>文章类型</th>
                    <th>意图簇</th>
                    <th>标题</th>
                    <th>核心作用</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map(item => (
                    <tr key={item.id}>
                      <td>{item.keyword}</td>
                      <td>{item.type}</td>
                      <td>{readString(item.raw, ["intent_group"], "")}</td>
                      <td>{item.title}</td>
                      <td>{item.role}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
        <div className="detail-actions">
          <button className="btn" disabled={loading} onClick={onClose}>取消</button>
          <button className="btn primary" disabled={loading || draft.status !== "completed" || !items.length} onClick={onApply}>
            {loading ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}确认导入并覆盖
          </button>
        </div>
        {error && <p className="item-error">{error}</p>}
      </div>
    </div>
  );
}

function matrixImportStatusLabel(status: MatrixImportDraft["status"]): string {
  if (status === "completed") return "可导入";
  if (status === "applied") return "已导入";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已停止";
  return "识别中";
}

function ContentPlanPreviewModal({
  plan,
  loading,
  onClose,
  onExport
}: {
  plan: ContentPlan;
  loading: boolean;
  onClose: () => void;
  onExport: () => void;
}) {
  const summary = plan.summary || {};
  const planSourceLabel = plan.source === "demand_matrix" ? "需求驱动矩阵" : "内容矩阵";
  const markdownReport = typeof plan.markdown_report === "string" ? plan.markdown_report.trim() : "";
  return (
    <div className="modal-backdrop content-plan-backdrop" role="presentation">
      <div className="content-plan-modal" role="dialog" aria-modal="true" aria-labelledby="content-plan-title">
        <div className="detail-head">
          <div>
            <span className="detail-kicker">{planSourceLabel} / 内容规划报告</span>
            <h2 id="content-plan-title">{plan.project_name}</h2>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        </div>
        <div className="content-plan-preview">
          {markdownReport ? (
            <section className="content-plan-section content-plan-markdown-section">
              <div className="content-plan-section-head">
                <strong>完整规划报告</strong>
                <span>生成时间：{plan.generated_at}</span>
              </div>
              <pre className="read-only-markdown content-plan-markdown-report">{markdownReport}</pre>
            </section>
          ) : (
            <>
              <section className="content-plan-section">
                <div className="content-plan-section-head">
                  <strong>项目摘要</strong>
                  <span>生成时间：{plan.generated_at}</span>
                </div>
                <div className="content-plan-kv">
                  <ContentPlanKv label="目标品牌" value={summary.target_brand} />
                  <ContentPlanKv label="产品/方案" value={summary.target_product_or_solution} />
                  <ContentPlanKv label="行业/品类" value={[summary.target_industry, summary.target_category].filter(Boolean).join(" / ")} />
                  <ContentPlanKv label="竞品" value={summary.competitors} />
                  <ContentPlanKv label="关键词" value={`${summary.target_keywords_count || 0} 个`} />
                  <ContentPlanKv label="文章规划" value={`${summary.total_plans || 0} 篇`} />
                  <ContentPlanKv label="文章类型" value={`${summary.article_type_count || 0} 类`} />
                  <ContentPlanKv label="全局证据缺口" value={`${summary.evidence_gap_count || 0} 项`} />
                </div>
              </section>
              <ContentPlanTable
                title="关键词意图簇"
                tableKey="intent-groups"
                rows={plan.keyword_intent_groups}
                columns={[
                  ["name", "意图簇"],
                  ["keywords", "关键词"],
                  ["user_stage", "用户阶段"],
                  ["user_question", "AI 需要回答的问题"],
                  ["recommendation_logic", "推荐逻辑/主攻类型"]
                ]}
              />
              <ContentPlanTable
                title="文章类型池"
                tableKey="article-type-pool"
                rows={plan.article_type_pool}
                columns={[
                  ["type", "文章类型"],
                  ["role", "核心作用"],
                  ["keywords", "覆盖关键词/意图簇"],
                  ["recommendation_strength", "推荐强度"],
                  ["count", "数量"]
                ]}
              />
              <ContentPlanTable
                title="首轮内容规划"
                tableKey="first-round-plans"
                rows={plan.first_round_plans}
                columns={[
                  ["intent_group", "意图簇"],
                  ["keyword", "关键词"],
                  ["type", "文章类型"],
                  ["title", "建议标题"],
                  ["role", "主要作用"],
                  ["required_evidence", "必备证据"],
                  ["priority", "优先级"]
                ]}
              />
              <ContentPlanDisplaySections sections={plan.display_sections?.filter(section => section.id !== "warnings") || []} />
              {plan.final_execution_advice && (
                <section className="content-plan-section">
                  <div className="content-plan-section-head"><strong>最终执行建议</strong></div>
                  <p>{plan.final_execution_advice}</p>
                </section>
              )}
              <ContentPlanDisplaySections sections={plan.display_sections?.filter(section => section.id === "warnings") || []} />
            </>
          )}
        </div>
        <div className="actions end">
          <button className="btn" onClick={onClose}>关闭</button>
          <button className="btn primary" disabled={loading} onClick={onExport}>
            {loading ? <Loader2 className="spin" size={15} /> : <Download size={15} />}导出 PDF
          </button>
        </div>
      </div>
    </div>
  );
}

function ContentPlanKv({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{contentPlanValue(value) || "未识别"}</strong>
    </div>
  );
}

function ContentPlanTable({
  title,
  rows,
  columns,
  tableKey
}: {
  title: string;
  rows: Array<Record<string, unknown>>;
  columns: Array<[string, string]>;
  tableKey?: string;
}) {
  if (!rows.length) return null;
  return (
    <section className="content-plan-section">
      <div className="content-plan-section-head">
        <strong>{title}</strong>
        <span>{rows.length} 条</span>
      </div>
      <div className="content-plan-table-wrap">
        <table className={`content-plan-table ${tableKey ? `content-plan-table-${tableKey}` : ""}`}>
          <thead>
            <tr>{columns.map(([, label]) => <th key={label}>{label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${title}-${index}`}>
                {columns.map(([key]) => <td key={key}>{contentPlanValue(row[key]) || "未标注"}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ContentPlanDisplaySections({ sections }: { sections: NonNullable<ContentPlan["display_sections"]> }) {
  if (!sections.length) return null;
  return (
    <>
      {sections.map(section => (
        <section className="content-plan-section" key={section.id}>
          <div className="content-plan-section-head">
            <strong>{section.title}</strong>
            <span>{section.items.length} 条</span>
          </div>
          <div className="content-plan-display-list">
            {section.items.map((item, itemIndex) => (
              <div className="content-plan-display-item" key={`${section.id}-${itemIndex}`}>
                {item.fields.map((field, fieldIndex) => (
                  <div key={`${field.label}-${fieldIndex}`}>
                    <span>{field.label}</span>
                    <strong>{field.value || "未标注"}</strong>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

function CustomView(props: {
  project: Project;
  items: ContentItem[];
  briefs: ContentItem[];
  articles: ContentItem[];
  selectedPlans: Set<string>;
  setSelectedPlans: React.Dispatch<React.SetStateAction<Set<string>>>;
  createCustomSources: (payload: CustomSourceBatchPayload) => Promise<void>;
  updateCustomSource: (sourceId: string, payload: CustomSourcePayload) => Promise<void>;
  deleteCustomSource: (sourceId: string) => Promise<void>;
  runBackendStep: (step: WorkflowStep, payload?: Record<string, unknown>) => Promise<void>;
  setCurrent: (view: AppView) => void;
  dismissedJobIds: Set<string>;
  dismissJob: (jobId: string) => void;
  cancelJob: (jobId: string) => Promise<void>;
}) {
  const {
    project,
    items,
    briefs,
    articles,
    selectedPlans,
    setSelectedPlans,
    createCustomSources,
    updateCustomSource,
    deleteCustomSource,
    runBackendStep,
    setCurrent,
    dismissedJobIds,
    dismissJob,
    cancelJob
  } = props;
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [customModal, setCustomModal] = useState<{ mode: "edit"; item: ContentItem } | null>(null);
  const [deleteCustomItem, setDeleteCustomItem] = useState<ContentItem | null>(null);
  const [draftFilters, setDraftFilters] = useState<CustomFilterState>(emptyCustomFilters);
  const [activeFilters, setActiveFilters] = useState<CustomFilterState>(emptyCustomFilters);
  const briefBySource = new Map(briefs.map(item => [item.sourceId, item]));
  const articleByBriefId = new Map(articles.map(item => [item.briefId || item.id, item]));
  const customIds = new Set(items.map(item => item.id));
  const keywordOptions = uniqueStrings(items.map(item => item.keyword).filter(Boolean));
  const articleTypeOptions = orderedArticleTypes(items);
  const filteredItems = filterCustomItems(items, briefBySource, activeFilters);
  const selectedCustomItems = filteredItems.filter(item => selectedPlans.has(item.id));
  const pendingBriefSources = selectedCustomItems.filter(item => !briefIsGenerated(briefBySource.get(item.sourceId)));
  const selectedCount = selectedCustomItems.length;
  const briefJob = briefProgressForPlanning(project, null);
  const selectedBriefButtonText = selectedCount === 0
    ? "生成选中 Brief"
    : pendingBriefSources.length === 0
      ? "选中项均已有 Brief"
      : `生成选中 Brief（${pendingBriefSources.length} 篇）`;

  useEffect(() => {
    setDraftFilters(emptyCustomFilters);
    setActiveFilters(emptyCustomFilters);
  }, [project.id]);

  async function submitBatch(payload: CustomSourceBatchPayload) {
    await createCustomSources(payload);
    setBatchModalOpen(false);
  }

  async function submitCustomSource(payload: CustomSourcePayload) {
    if (!customModal) return;
    await updateCustomSource(customModal.item.sourceId, payload);
    setCustomModal(null);
  }

  async function confirmDeleteCustomSource() {
    if (!deleteCustomItem) return;
    const staleId = deleteCustomItem.id;
    await deleteCustomSource(deleteCustomItem.sourceId);
    setSelectedPlans(current => new Set([...current].filter(id => id !== staleId)));
    setDeleteCustomItem(null);
  }

  async function generateSelectedBriefs() {
    if (!pendingBriefSources.length) return;
    await runBackendStep("brief", { selected_sources: pendingBriefSources.map(toSourcePayload) });
    setCurrent("brief");
  }

  function setCustomSelection(rows: ContentItem[], selected: boolean) {
    setSelectedPlans(current => {
      const next = new Set(current);
      rows.forEach(item => {
        if (selected) next.add(item.id);
        else next.delete(item.id);
      });
      return next;
    });
  }

  function applyFilters() {
    const nextFilters = { ...draftFilters };
    const nextItems = filterCustomItems(items, briefBySource, nextFilters);
    const nextVisibleIds = new Set(nextItems.map(item => item.id));
    setActiveFilters(nextFilters);
    setSelectedPlans(current => new Set([...current].filter(id => !customIds.has(id) || nextVisibleIds.has(id))));
  }

  function resetFilters() {
    setDraftFilters(emptyCustomFilters);
    setActiveFilters(emptyCustomFilters);
  }

  return (
    <div className="section-stack">
      <div className="bulk-bar">
        <div>
          <strong>自定义文章规划</strong>
          <span>{items.length ? `已添加 ${items.length} 篇自定义文章，可勾选后生成 Brief。` : "批量输入文章标题，选择文章类型后生成 Brief。"}</span>
        </div>
        <div className="actions">
          <button className="btn primary" onClick={() => setBatchModalOpen(true)}><Plus size={15} />批量新增自定义文章</button>
        </div>
      </div>

      <div className="planning-filter-strip custom-filter-strip">
        <div>
          <strong>自定义筛选</strong>
          <span>{filteredItems.length === items.length ? `当前显示全部 ${items.length} 篇自定义文章` : `当前显示 ${filteredItems.length}/${items.length} 篇自定义文章`}</span>
        </div>
        <label>
          <span>关键词</span>
          <select value={draftFilters.keyword} onChange={event => setDraftFilters(current => ({ ...current, keyword: event.target.value }))}>
            <option value="all">全部</option>
            {keywordOptions.map(keyword => <option key={keyword} value={keyword}>{keyword}</option>)}
          </select>
        </label>
        <label>
          <span>文章类型</span>
          <select value={draftFilters.articleType} onChange={event => setDraftFilters(current => ({ ...current, articleType: event.target.value }))}>
            <option value="all">全部</option>
            {articleTypeOptions.map(type => <option key={type} value={type}>{type}</option>)}
          </select>
        </label>
        <label>
          <span>Brief 状态</span>
          <select value={draftFilters.briefStatus} onChange={event => setDraftFilters(current => ({ ...current, briefStatus: event.target.value as CustomBriefFilter }))}>
            <option value="all">全部</option>
            <option value="generated">已生成 Brief</option>
            <option value="not_generated">未生成 Brief</option>
          </select>
        </label>
        <div className="actions custom-filter-actions">
          <button className="btn primary" disabled={!items.length} onClick={applyFilters}><Search size={15} />确认筛选</button>
          <button className="btn" disabled={!items.length} onClick={resetFilters}><RefreshCw size={15} />重置筛选</button>
        </div>
      </div>

      <JobProgress job={briefJob} dismissedJobIds={dismissedJobIds} onDismiss={dismissJob} onCancel={cancelJob} />

      <div className="bulk-bar selection-bar">
        <div>
          <strong>已选 {selectedCount} 篇自定义文章</strong>
          <span>{selectedCount ? `其中 ${pendingBriefSources.length} 篇尚未生成 Brief。` : "先勾选自定义文章规划。"}</span>
        </div>
        <div className="actions">
          <button className="btn" disabled={!selectedCount} onClick={() => setSelectedPlans(current => new Set([...current].filter(id => !customIds.has(id))))}>清空选择</button>
          <button className="btn primary" disabled={!pendingBriefSources.length} onClick={() => void generateSelectedBriefs()}>{selectedBriefButtonText}</button>
        </div>
      </div>

      <CustomPlanningPanel
        items={filteredItems}
        selectedPlans={selectedPlans}
        briefBySource={briefBySource}
        articleByBriefId={articleByBriefId}
        onEdit={(item) => setCustomModal({ mode: "edit", item })}
        onDelete={(item) => setDeleteCustomItem(item)}
        onSelectionChange={setCustomSelection}
        onToggle={(item) => setSelectedPlans(current => toggleSet(current, item.id))}
      />

      {batchModalOpen && (
        <BatchCustomSourceModal
          onClose={() => setBatchModalOpen(false)}
          onSubmit={(payload) => void submitBatch(payload)}
        />
      )}
      {customModal && (
        <CustomSourceModal
          mode={customModal.mode}
          item={customModal.item}
          onClose={() => setCustomModal(null)}
          onSubmit={(payload) => void submitCustomSource(payload)}
        />
      )}
      {deleteCustomItem && (
        <div className="modal-backdrop" role="presentation">
          <div className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-custom-title">
            <h2 id="delete-custom-title">删除自定义文章？</h2>
            <p>这只会删除自定义文章规划项，不会删除已经生成的 Brief 或正文。取消则不会做任何更改。</p>
            <div className="actions end">
              <button className="btn" onClick={() => setDeleteCustomItem(null)}>取消</button>
              <button className="btn primary" onClick={() => void confirmDeleteCustomSource()}>确认删除</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CustomPlanningPanel({
  items,
  selectedPlans,
  briefBySource,
  articleByBriefId,
  onEdit,
  onDelete,
  onSelectionChange,
  onToggle
}: {
  items: ContentItem[];
  selectedPlans: Set<string>;
  briefBySource: Map<string, ContentItem>;
  articleByBriefId: Map<string, ContentItem>;
  onEdit: (item: ContentItem) => void;
  onDelete: (item: ContentItem) => void;
  onSelectionChange: (rows: ContentItem[], selected: boolean) => void;
  onToggle: (item: ContentItem) => void;
}) {
  return (
    <Panel
      title={`自定义文章（${items.length} 篇）`}
      icon={<Plus size={16} />}
      aside={
        <div className="actions">
          {items.length > 0 && <GroupSelectAside rows={items} selectedPlans={selectedPlans} onChange={onSelectionChange} />}
        </div>
      }
    >
      {items.length ? (
        <div className="plan-list">
          {items.map(item => {
            const brief = briefBySource.get(item.sourceId);
            return (
              <PlanRow
                key={item.id}
                item={item}
                selected={selectedPlans.has(item.id)}
                brief={brief}
                article={articleForPlanItem(item, briefBySource, articleByBriefId)}
                onToggle={() => onToggle(item)}
                onEdit={() => onEdit(item)}
                onDelete={() => onDelete(item)}
                editDisabled={Boolean(brief?.status)}
              />
            );
          })}
        </div>
      ) : (
        <EmptyPanelText text="可以在这里批量添加文章标题，后台会结合项目上下文推断关键词；文章类型由你手动选择，生成 Brief 时不会覆盖已有结果。" />
      )}
    </Panel>
  );
}

function CustomSourceModal({
  mode,
  item,
  onClose,
  onSubmit
}: {
  mode: "create" | "edit" | "copy";
  item?: ContentItem;
  onClose: () => void;
  onSubmit: (payload: CustomSourcePayload) => void;
}) {
  const [title, setTitle] = useState(item?.title || "");
  const [articleType, setArticleType] = useState(item?.type && coreArticleTypes.includes(item.type) ? item.type : coreArticleTypes[0]);
  const canSubmit = Boolean(title.trim() && articleType);
  const modalTitle = mode === "edit" ? "编辑自定义文章" : mode === "copy" ? "复制为自定义文章" : "新增自定义文章";

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      title: title.trim(),
      type: articleType,
      raw: customSourceRawFor(mode, item)
    });
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form className="confirm-modal custom-source-modal" role="dialog" aria-modal="true" aria-labelledby="custom-source-title" onSubmit={submit}>
        <h2 id="custom-source-title">{modalTitle}</h2>
        <p>修改标题或文章类型后，已生成 Brief 的自定义文章仍不会被覆盖；需要重新生成时请在 Brief 页处理。</p>
        <div className="form-grid">
          <label className="field-block full">
            <span>标题</span>
            <input value={title} onChange={event => setTitle(event.target.value)} placeholder="例如：企业如何选择 GEO 内容生产工具" />
          </label>
          <label className="field-block full">
            <span>文章类型</span>
            <select value={articleType} onChange={event => setArticleType(event.target.value)}>
              {coreArticleTypes.map(type => <option key={type} value={type}>{type}</option>)}
            </select>
          </label>
        </div>
        <div className="actions end">
          <button type="button" className="btn" onClick={onClose}>取消</button>
          <button type="submit" className="btn primary" disabled={!canSubmit}>保存自定义文章</button>
        </div>
      </form>
    </div>
  );
}

function BatchCustomSourceModal({
  onClose,
  onSubmit
}: {
  onClose: () => void;
  onSubmit: (payload: CustomSourceBatchPayload) => void;
}) {
  const [titlesText, setTitlesText] = useState("");
  const [articleType, setArticleType] = useState(coreArticleTypes[0]);
  const titles = uniqueStrings(titlesText.split(/\r?\n/).map(title => title.trim()).filter(Boolean));
  const canSubmit = titles.length > 0 && Boolean(articleType);

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      titles,
      type: articleType
    });
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form className="confirm-modal custom-source-modal" role="dialog" aria-modal="true" aria-labelledby="batch-custom-source-title" onSubmit={submit}>
        <h2 id="batch-custom-source-title">批量新增自定义文章</h2>
        <p>一行一个标题，同一批标题共用一个文章类型；保存后可勾选生成 Brief。</p>
        <div className="form-grid">
          <label className="field-block full">
            <span>文章类型</span>
            <select value={articleType} onChange={event => setArticleType(event.target.value)}>
              {coreArticleTypes.map(type => <option key={type} value={type}>{type}</option>)}
            </select>
          </label>
          <label className="field-block full">
            <span>文章标题</span>
            <textarea
              className="batch-title-area"
              value={titlesText}
              onChange={event => setTitlesText(event.target.value)}
              placeholder={"万元预算厨电推荐清单\n别墅厨房厨电配置怎么选\n开放式厨房烟机灶具搭配方案"}
            />
          </label>
        </div>
        <div className="detail-meta">
          <Chip text={`将新增 ${titles.length} 篇`} type={titles.length ? "good" : "warn"} />
          <Chip text={articleType} />
        </div>
        <div className="actions end">
          <button type="button" className="btn" onClick={onClose}>取消</button>
          <button type="submit" className="btn primary" disabled={!canSubmit}>保存自定义文章</button>
        </div>
      </form>
    </div>
  );
}

function BriefView(props: {
  project: Project;
  items: ContentItem[];
  articles: ContentItem[];
  selectedSourceItems: ContentItem[];
  selectedBriefItems: ContentItem[];
  selectedBriefs: Set<string>;
  setSelectedBriefs: React.Dispatch<React.SetStateAction<Set<string>>>;
  runBackendStep: (step: WorkflowStep, payload?: Record<string, unknown>) => Promise<void>;
  setCurrent: (view: AppView) => void;
  openDetail: (item: ContentItem) => void;
  regenerateBrief: (item: ContentItem) => Promise<void>;
  dismissedJobIds: Set<string>;
  dismissJob: (jobId: string) => void;
  cancelJob: (jobId: string) => Promise<void>;
  dashboardDrilldown?: DashboardDrilldown | null;
  clearDashboardDrilldown?: () => void;
}) {
  const { project, items, articles, selectedSourceItems, selectedBriefs, setSelectedBriefs, runBackendStep, setCurrent, openDetail, regenerateBrief, dismissedJobIds, dismissJob, cancelJob, dashboardDrilldown, clearDashboardDrilldown } = props;
  const articleByBriefId = new Map(articles.map(item => [item.briefId || item.id, item]));
  const [draftFilters, setDraftFilters] = useState<BriefFilterState>(emptyBriefFilters);
  const [activeFilters, setActiveFilters] = useState<BriefFilterState>(emptyBriefFilters);
  const keywordOptions = uniqueStrings(items.map(item => item.keyword).filter(Boolean));
  const articleTypeOptions = uniqueStrings(items.map(item => item.type).filter(Boolean));
  const filteredItems = filterBriefItems(items, articleByBriefId, activeFilters);
  const selectedVisibleBriefItems = filteredItems.filter(item => selectedBriefs.has(item.id));
  const allBriefsSelected = filteredItems.length > 0 && filteredItems.every(item => selectedBriefs.has(item.id));
  const invalidSelectedBriefCount = selectedVisibleBriefItems.filter(brief => !briefIsGenerated(brief)).length;
  const generatedSelectedBriefItems = selectedVisibleBriefItems.filter(briefIsGenerated);
  const pendingArticleBriefs = generatedSelectedBriefItems.filter(brief => !articles.some(article => articleCurrentForBrief(article, brief)));
  const pendingUpdateCount = pendingArticleBriefs.filter(brief => {
    const article = articleByBriefId.get(brief.id);
    return article && !articleCurrentForBrief(article, brief);
  }).length;
  const articleButtonText = selectedVisibleBriefItems.length === 0
    ? "生成选中正文"
    : invalidSelectedBriefCount && pendingArticleBriefs.length === 0
      ? "选中 Brief 尚未生成完成"
    : pendingArticleBriefs.length === 0
      ? "选中 Brief 均已有正文"
      : pendingUpdateCount
        ? `生成更新后的正文（${pendingArticleBriefs.length} 篇）`
        : `生成选中正文（${pendingArticleBriefs.length} 篇）`;
  useEffect(() => {
    setDraftFilters(emptyBriefFilters);
    setActiveFilters(emptyBriefFilters);
  }, [project.id]);
  useEffect(() => {
    if (dashboardDrilldown?.view !== "brief") return;
    const nextFilters: BriefFilterState = {
      keyword: dashboardDrilldown.keyword || "all",
      articleType: dashboardDrilldown.articleType || "all",
      briefModified: dashboardDrilldown.briefModified || "all",
      articleStatus: dashboardDrilldown.articleStatus || "all"
    };
    setDraftFilters(nextFilters);
    setActiveFilters(nextFilters);
    setSelectedBriefs(new Set());
    clearDashboardDrilldown?.();
  }, [dashboardDrilldown, clearDashboardDrilldown, setSelectedBriefs]);
  async function generateSelectedArticles() {
    if (!pendingArticleBriefs.length) return;
    await runBackendStep("article", { selected_briefs: pendingArticleBriefs.map(toBriefPayload) });
    setCurrent("article");
  }
  function toggleAllBriefs() {
    setSelectedBriefs(current => {
      const visibleIds = new Set(filteredItems.map(item => item.id));
      if (allBriefsSelected) return new Set([...current].filter(id => !visibleIds.has(id)));
      return new Set([...current, ...visibleIds]);
    });
  }
  function applyFilters() {
    const nextFilters = { ...draftFilters };
    const nextItems = filterBriefItems(items, articleByBriefId, nextFilters);
    const nextVisibleIds = new Set(nextItems.map(item => item.id));
    setActiveFilters(nextFilters);
    setSelectedBriefs(current => new Set([...current].filter(id => nextVisibleIds.has(id))));
  }
  function resetFilters() {
    setDraftFilters(emptyBriefFilters);
    setActiveFilters(emptyBriefFilters);
  }
  return (
    <div className="section-stack">
      <Panel title="Brief 分组审核" icon={<BadgeAlert size={16} />} aside={<Chip text={`已生成 ${items.length} 篇 Brief`} type={items.length ? "brand" : "warn"} />}>
        <div className="brief-filter-panel">
          <div className="brief-filter-grid">
            <label className="field-block">
              <span>关键词</span>
              <select value={draftFilters.keyword} onChange={event => setDraftFilters(current => ({ ...current, keyword: event.target.value }))}>
                <option value="all">全部</option>
                {keywordOptions.map(keyword => <option key={keyword} value={keyword}>{keyword}</option>)}
              </select>
            </label>
            <label className="field-block">
              <span>文章类型</span>
              <select value={draftFilters.articleType} onChange={event => setDraftFilters(current => ({ ...current, articleType: event.target.value }))}>
                <option value="all">全部</option>
                {articleTypeOptions.map(type => <option key={type} value={type}>{type}</option>)}
              </select>
            </label>
            <label className="field-block">
              <span>Brief 是否修改</span>
              <select value={draftFilters.briefModified} onChange={event => setDraftFilters(current => ({ ...current, briefModified: event.target.value as BriefModifiedFilter }))}>
                <option value="all">全部</option>
                <option value="modified">已修改</option>
                <option value="unmodified">未修改</option>
              </select>
            </label>
            <label className="field-block">
              <span>是否生成正文</span>
              <select value={draftFilters.articleStatus} onChange={event => setDraftFilters(current => ({ ...current, articleStatus: event.target.value as BriefArticleFilter }))}>
                <option value="all">全部</option>
                <option value="generated">已生成正文</option>
                <option value="not_generated">未生成正文</option>
                <option value="needs_update">正文需更新</option>
              </select>
            </label>
          </div>
          <div className="actions brief-filter-actions">
            <button className="btn primary" disabled={!items.length} onClick={applyFilters}><Search size={15} />确认筛选</button>
            <button className="btn" disabled={!items.length} onClick={resetFilters}><RefreshCw size={15} />重置筛选</button>
          </div>
        </div>
        <div className="actions block-actions">
          <button className="btn" disabled={!filteredItems.length} onClick={toggleAllBriefs}>{allBriefsSelected ? "取消全选" : "全选 Brief"}</button>
          <button className="btn primary" disabled={!pendingArticleBriefs.length} onClick={() => void generateSelectedArticles()}>{articleButtonText}</button>
        </div>
        <p className="muted">
          {selectedVisibleBriefItems.length
            ? `已选 ${selectedVisibleBriefItems.length} 篇 Brief，其中 ${pendingArticleBriefs.length} 篇尚未生成正文。`
            : filteredItems.length !== items.length
              ? `当前筛选显示 ${filteredItems.length}/${items.length} 篇 Brief。`
            : selectedSourceItems.length
              ? `规划页当前已选 ${selectedSourceItems.length} 篇文章；请在规划页点击“生成选中 Brief”。`
              : "请先在规划确认页勾选文章并生成 Brief，再在这里选择 Brief 生成正文。"}
        </p>
        <JobProgress job={latestJob(project, "brief")} dismissedJobIds={dismissedJobIds} onDismiss={dismissJob} onCancel={cancelJob} />
        {filteredItems.length ? (
          <div className="review-list">
            {filteredItems.map(item => (
              <article className={`review-card ${briefReviewCardClass(item, articleByBriefId.get(item.id))}`} key={item.id}>
                <div className="review-card-head">
                  <input type="checkbox" checked={selectedBriefs.has(item.id)} onChange={() => setSelectedBriefs(current => toggleSet(current, item.id))} />
                  <div>
                    <h3>{item.title}</h3>
                    <div className="chips meta-chips review-meta-chips">
                      <Chip text={item.keyword} type="brand" className="keyword-chip" />
                      <Chip text={item.type} className="type-chip" />
                      <ItemStatusChip status={briefItemStatusLabel(item.status)} className="state-chip" />
                      {articleStatusForBrief(articleByBriefId.get(item.id), item) && <ItemStatusChip status={articleStatusForBrief(articleByBriefId.get(item.id), item)} className="state-chip" />}
                    </div>
                  </div>
                  <TimeStampChip label="Brief时间" value={itemGeneratedTimestampLabel(item)} />
                  <div className="row-actions">
                    <button className="btn" onClick={() => openDetail(item)}><BookOpen size={15} />查阅/编辑</button>
                    <button className="btn" disabled={item.status === "running"} onClick={() => void regenerateBrief(item)}>
                      <RefreshCw size={15} />{item.status === "failed" ? "重试" : "重新生成"}
                    </button>
                  </div>
                </div>
                <p className="card-excerpt">{item.role}</p>
                {item.error && <p className="item-error">{item.error}</p>}
              </article>
            ))}
          </div>
        ) : <EmptyPanelText text={items.length ? "当前筛选条件下没有 Brief。" : "暂无 Brief。请先确认规划，再生成 Brief。"} />}
      </Panel>
    </div>
  );
}

function ArticleView(props: {
  project: Project;
  items: ContentItem[];
  briefs: ContentItem[];
  selectedArticles: Set<string>;
  setSelectedArticles: React.Dispatch<React.SetStateAction<Set<string>>>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
  openDetail: (item: ContentItem) => void;
  openAudit: (item: ContentItem) => void;
  openBriefDetail: (item: ContentItem) => void;
  regenerateArticle: (item: ContentItem) => Promise<void>;
  dismissedJobIds: Set<string>;
  dismissJob: (jobId: string) => void;
  cancelJob: (jobId: string) => Promise<void>;
  dashboardDrilldown?: DashboardDrilldown | null;
  clearDashboardDrilldown?: () => void;
}) {
  const { project, items, briefs, selectedArticles, setSelectedArticles, openDetail, openAudit, openBriefDetail, dismissedJobIds, dismissJob, cancelJob, dashboardDrilldown, clearDashboardDrilldown } = props;
  const briefById = new Map(briefs.map(item => [item.id, item]));
  const [draftFilters, setDraftFilters] = useState<BriefFilterState>(emptyBriefFilters);
  const [activeFilters, setActiveFilters] = useState<BriefFilterState>(emptyBriefFilters);
  const keywordOptions = uniqueStrings(items.map(item => item.keyword).filter(Boolean));
  const articleTypeOptions = uniqueStrings(items.map(item => item.type).filter(Boolean));
  const filteredItems = filterArticleItems(items, briefById, activeFilters);
  const selectedArticleItems = filteredItems.filter(item => selectedArticles.has(item.id));
  const allSelected = filteredItems.length > 0 && selectedArticleItems.length === filteredItems.length;
  useEffect(() => {
    setDraftFilters(emptyBriefFilters);
    setActiveFilters(emptyBriefFilters);
  }, [project.id]);
  useEffect(() => {
    if (dashboardDrilldown?.view !== "article") return;
    const nextFilters: BriefFilterState = {
      keyword: dashboardDrilldown.keyword || "all",
      articleType: dashboardDrilldown.articleType || "all",
      briefModified: dashboardDrilldown.briefModified || "all",
      articleStatus: dashboardDrilldown.articleStatus || "all"
    };
    setDraftFilters(nextFilters);
    setActiveFilters(nextFilters);
    setSelectedArticles(new Set());
    clearDashboardDrilldown?.();
  }, [dashboardDrilldown, clearDashboardDrilldown, setSelectedArticles]);
  function toggleAllArticles() {
    setSelectedArticles(current => {
      const visibleIds = new Set(filteredItems.map(item => item.id));
      if (allSelected) return new Set([...current].filter(id => !visibleIds.has(id)));
      return new Set([...current, ...visibleIds]);
    });
  }
  function exportSelectedArticles() {
    if (!selectedArticleItems.length) return;
    downloadArticleMarkdown(selectedArticleItems);
  }
  function applyFilters() {
    const nextFilters = { ...draftFilters };
    const nextItems = filterArticleItems(items, briefById, nextFilters);
    const nextVisibleIds = new Set(nextItems.map(item => item.id));
    setActiveFilters(nextFilters);
    setSelectedArticles(current => new Set([...current].filter(id => nextVisibleIds.has(id))));
  }
  function resetFilters() {
    setDraftFilters(emptyBriefFilters);
    setActiveFilters(emptyBriefFilters);
  }
  return (
    <div className="section-stack">
      {items.length > 0 && (
        <div className="brief-filter-panel">
          <div className="brief-filter-grid">
            <label className="field-block">
              <span>关键词</span>
              <select value={draftFilters.keyword} onChange={event => setDraftFilters(current => ({ ...current, keyword: event.target.value }))}>
                <option value="all">全部</option>
                {keywordOptions.map(keyword => <option key={keyword} value={keyword}>{keyword}</option>)}
              </select>
            </label>
            <label className="field-block">
              <span>文章类型</span>
              <select value={draftFilters.articleType} onChange={event => setDraftFilters(current => ({ ...current, articleType: event.target.value }))}>
                <option value="all">全部</option>
                {articleTypeOptions.map(type => <option key={type} value={type}>{type}</option>)}
              </select>
            </label>
            <label className="field-block">
              <span>Brief 是否修改</span>
              <select value={draftFilters.briefModified} onChange={event => setDraftFilters(current => ({ ...current, briefModified: event.target.value as BriefModifiedFilter }))}>
                <option value="all">全部</option>
                <option value="modified">已修改</option>
                <option value="unmodified">未修改</option>
              </select>
            </label>
            <label className="field-block">
              <span>正文是否生成/更新</span>
              <select value={draftFilters.articleStatus} onChange={event => setDraftFilters(current => ({ ...current, articleStatus: event.target.value as BriefArticleFilter }))}>
                <option value="all">全部</option>
                <option value="pending_review">待审核 / 待处理正文</option>
                <option value="approved">已审核 / 已定稿</option>
                <option value="needs_update">需更新/基于旧 Brief</option>
                <option value="failed">生成失败</option>
              </select>
            </label>
          </div>
          <div className="actions brief-filter-actions">
            <button className="btn primary" onClick={applyFilters}><Search size={15} />确认筛选</button>
            <button className="btn" onClick={resetFilters}><RefreshCw size={15} />重置筛选</button>
          </div>
        </div>
      )}
      <div className="bulk-bar">
        <div><strong>正文折叠审核</strong><span>{items.length ? `已生成 ${items.length} 篇正文，当前显示 ${filteredItems.length} 篇，已选 ${selectedArticleItems.length} 篇。` : "暂无正文结果。"}</span></div>
        <div className="actions">
          <button className="btn" disabled={!filteredItems.length} onClick={toggleAllArticles}>{allSelected ? "取消全选" : "全选正文"}</button>
          <button className="btn primary" disabled={!selectedArticleItems.length} onClick={exportSelectedArticles}><Download size={15} />导出正文</button>
        </div>
      </div>
      <JobProgress job={latestJob(project, "article")} dismissedJobIds={dismissedJobIds} onDismiss={dismissJob} onCancel={cancelJob} />
      {filteredItems.length ? (
        <div className="article-list">
          {filteredItems.map(item => {
            const boundBrief = briefById.get(item.briefId || "");
            const boundBriefReady = briefIsGenerated(boundBrief);
            return (
              <article className={`article-collapse ${articleReviewCardClass(item, boundBrief)}`} key={item.id}>
                <div className="article-card-head">
                  <input type="checkbox" checked={selectedArticles.has(item.id)} onChange={() => {
                    setSelectedArticles(current => toggleSet(current, item.id));
                  }} />
                  <div>
                    <h3>{item.title}</h3>
                    <div className="chips meta-chips review-meta-chips">
                      <Chip text={item.keyword} type="brand" className="keyword-chip" />
                      <Chip text={item.type} className="type-chip" />
                      {boundBriefReady && boundBrief ? (
                        <button type="button" className="chip good state-chip chip-button" onClick={() => openBriefDetail(boundBrief)}>
                          <span>已绑定 Brief</span>
                        </button>
                      ) : boundBrief ? (
                        <Chip text="Brief 未完成" type="warn" className="state-chip" />
                      ) : null}
                      <ItemStatusChip status={item.status} className="state-chip" />
                    </div>
                  </div>
                  <TimeStampChip label="正文时间" value={itemGeneratedTimestampLabel(item)} />
                  <AuditStatusBlock item={item} />
                  <div className="row-actions">
                    <button className="btn" onClick={() => openDetail(item)}><BookOpen size={15} />查阅/编辑</button>
                    {articleAuditApproved(item) ? (
                      <button className="btn" disabled><CheckCircle2 size={15} />已审核</button>
                    ) : (
                      <button className="btn" disabled={item.status === "running" || !item.markdown || !boundBriefReady} onClick={() => openAudit(item)}><CheckCircle2 size={15} />进入审核</button>
                    )}
                  </div>
                </div>
                {(item.error || item.staleReason) && <p className={item.staleReason ? "item-warning" : "item-error"}>{item.error || item.staleReason}</p>}
              </article>
            );
          })}
        </div>
      ) : (
        <Panel title="暂无正文" icon={<Newspaper size={16} />}>
          <EmptyPanelText text={items.length ? "当前筛选条件下没有正文。" : "请先确认 Brief，然后点击“生成正文”。"} />
        </Panel>
      )}
    </div>
  );
}

function MarkdownImportView({
  project,
  data,
  onImport,
  busy,
  setCurrent,
  openDetail
}: {
  project: Project;
  data: DerivedData;
  onImport: (rows: Array<{ file: File; meta: MarkdownArticleImportMeta }>) => Promise<void>;
  busy: boolean;
  setCurrent: (view: AppView) => void;
  openDetail: (item: ContentItem) => void;
}) {
  const [drafts, setDrafts] = useState<MarkdownImportDraft[]>([]);
  const [error, setError] = useState("");
  const keywordOptions = uniqueStrings([...data.plans, ...data.briefs, ...data.articles].map(item => item.keyword).filter(Boolean));
  const typeOptions = coreArticleTypes;
  const importedArticles = data.articles.filter(articleIsImportedMarkdown);
  const validRows = drafts.filter(row => row.status === "ready" && row.title.trim() && row.keyword.trim() && row.type.trim());
  const canSubmit = drafts.length > 0 && validRows.length === drafts.length && !busy;

  async function handleFiles(files: FileList | null) {
    setError("");
    if (!files?.length) return;
    const nextRows: MarkdownImportDraft[] = [];
    for (const file of Array.from(files)) {
      const id = `${file.name}-${file.size}-${file.lastModified}`;
      if (!file.name.toLowerCase().endsWith(".md")) {
        nextRows.push({
          id,
          file,
          filename: file.name,
          title: fileNameTitle(file.name),
          keyword: "",
          type: "",
          status: "invalid",
          error: "仅支持 .md 文件"
        });
        continue;
      }
      const markdown = await file.text();
      const title = markdownH1Title(markdown) || fileNameTitle(file.name);
      nextRows.push({
        id,
        file,
        filename: file.name,
        title,
        keyword: "",
        type: "",
        status: markdown.trim() ? "ready" : "invalid",
        error: markdown.trim() ? "" : "文件内容为空"
      });
    }
    setDrafts(current => mergeImportDrafts(current, nextRows));
  }

  function updateDraft(id: string, patch: Partial<Pick<MarkdownImportDraft, "title" | "keyword" | "type">>) {
    setDrafts(current => current.map(row => row.id === id ? { ...row, ...patch } : row));
  }

  function removeDraft(id: string) {
    setDrafts(current => current.filter(row => row.id !== id));
  }

  async function submitImport() {
    const invalid = drafts.find(row => row.status !== "ready" || !row.title.trim() || !row.keyword.trim() || !row.type.trim());
    if (invalid) {
      setError(`请补齐导入信息：${invalid.filename}`);
      return;
    }
    setError("");
    await onImport(drafts.map(row => ({
      file: row.file,
      meta: {
        filename: row.filename,
        title: row.title.trim(),
        keyword: row.keyword.trim(),
        type: row.type.trim()
      }
    })));
    setDrafts([]);
    setCurrent("library");
  }

  return (
    <div className="section-stack">
      <div className="bulk-bar import-summary">
        <div>
          <strong>批量导入 Markdown 定稿</strong>
          <span>{drafts.length ? `已选择 ${drafts.length} 篇，${validRows.length} 篇信息完整。` : "选择本地 .md 文件后，逐篇补充关键词和文章类型。"}</span>
        </div>
        <div className="actions">
          <label className="btn import-file-button">
            <Upload size={15} />选择 Markdown
            <input type="file" accept=".md,text/markdown,text/plain" multiple onChange={event => void handleFiles(event.target.files)} />
          </label>
          <button className="btn primary" disabled={!canSubmit} onClick={() => void submitImport()}><CheckCircle2 size={15} />导入定稿</button>
        </div>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div><h2>待导入文章</h2><p>{project.name} · 导入后自动标记为已审核正文，发布平台同步后可发布。</p></div>
          {drafts.length > 0 && <button className="btn" onClick={() => setDrafts([])}><Trash2 size={15} />清空</button>}
        </div>
        <div className="panel-body">
          {drafts.length ? (
            <div className="table-wrap import-table-wrap">
              <table className="import-table">
                <colgroup>
                  <col className="import-col-file" />
                  <col className="import-col-title" />
                  <col className="import-col-keyword" />
                  <col className="import-col-type" />
                  <col className="import-col-status" />
                  <col className="import-col-action" />
                </colgroup>
                <thead><tr><th>文件名</th><th>标题</th><th>关键词</th><th>文章类型</th><th>状态</th><th>操作</th></tr></thead>
                <tbody>
                  {drafts.map(row => (
                    <tr key={row.id} className={row.status === "invalid" ? "import-row-invalid" : ""}>
                      <td><strong>{row.filename}</strong></td>
                      <td>
                        <input className="import-input" value={row.title} placeholder="文章标题" onChange={event => updateDraft(row.id, { title: event.target.value })} />
                      </td>
                      <td>
                        <input
                          className="import-input"
                          value={row.keyword}
                          list="markdown-import-keywords"
                          placeholder="输入关键词"
                          onChange={event => updateDraft(row.id, { keyword: event.target.value })}
                        />
                      </td>
                      <td>
                        <select
                          className="import-input"
                          value={row.type}
                          onChange={event => updateDraft(row.id, { type: event.target.value })}
                        >
                          <option value="">请选择文章类型</option>
                          {typeOptions.map(type => <option key={type} value={type}>{type}</option>)}
                        </select>
                      </td>
                      <td>
                        <span className={`chip ${row.status === "ready" && row.title && row.keyword && row.type ? "good" : "warn"}`}>
                          {row.status === "invalid" ? row.error : row.title && row.keyword && row.type ? "可导入" : "待补充"}
                        </span>
                      </td>
                      <td><button className="import-remove-btn" onClick={() => removeDraft(row.id)}>移除</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <datalist id="markdown-import-keywords">
                {keywordOptions.map(keyword => <option key={keyword} value={keyword} />)}
              </datalist>
            </div>
          ) : (
            <EmptyPanelText text="暂无待导入文章。请点击“选择 Markdown”上传本地 .md 文件。" />
          )}
          {error && <p className="item-error">{error}</p>}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div><h2>已导入文章</h2><p>{project.name} · 共 {importedArticles.length} 篇本地 Markdown 定稿。</p></div>
          <button className="btn" disabled={!importedArticles.length} onClick={() => setCurrent("library")}><Archive size={15} />查看归档</button>
        </div>
        <div className="panel-body">
          {importedArticles.length ? (
            <div className="table-wrap import-table-wrap">
              <table className="import-table imported-article-table">
                <colgroup>
                  <col className="imported-col-title" />
                  <col className="imported-col-keyword" />
                  <col className="imported-col-type" />
                  <col className="imported-col-file" />
                  <col className="imported-col-time" />
                  <col className="imported-col-status" />
                  <col className="imported-col-action" />
                </colgroup>
                <thead><tr><th>标题</th><th>关键词</th><th>文章类型</th><th>源文件</th><th>导入时间</th><th>状态</th><th>操作</th></tr></thead>
                <tbody>
                  {importedArticles.map(item => (
                    <tr key={item.id}>
                      <td><strong>{item.title}</strong></td>
                      <td><Chip text={item.keyword || "未填写"} type="brand" className="keyword-chip" /></td>
                      <td><Chip text={item.type || "未填写"} className="type-chip" /></td>
                      <td><span className="imported-source-file">{importedArticleFilename(item)}</span></td>
                      <td>{timestampLabel(importedArticleImportedAt(item)) || "-"}</td>
                      <td><span className="chip good">已入库</span></td>
                      <td><button className="btn compact" onClick={() => openDetail(item)}><BookOpen size={15} />查阅</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyPanelText text="暂无已导入文章。导入成功后会在这里展示，并同步出现在定稿归档。" />
          )}
        </div>
      </section>
    </div>
  );
}

function LibraryView({ project, data, selectedArticles, setSelectedArticles, openDetail }: {
  project: Project;
  data: DerivedData;
  selectedArticles: Set<string>;
  setSelectedArticles: React.Dispatch<React.SetStateAction<Set<string>>>;
  openDetail: (item: ContentItem) => void;
}) {
  const briefById = new Map(data.briefs.map(item => [item.id, item]));
  const finalItems = data.articles.filter(item => articleIsFinal(item, briefById));
  const [draftFilters, setDraftFilters] = useState<BriefFilterState>(emptyBriefFilters);
  const [activeFilters, setActiveFilters] = useState<BriefFilterState>(emptyBriefFilters);
  const keywordOptions = uniqueStrings(finalItems.map(item => item.keyword).filter(Boolean));
  const articleTypeOptions = uniqueStrings(finalItems.map(item => item.type).filter(Boolean));
  const filteredItems = filterArticleItems(finalItems, briefById, activeFilters);
  const selectedArticleItems = filteredItems.filter(item => selectedArticles.has(item.id));
  const allSelected = filteredItems.length > 0 && selectedArticleItems.length === filteredItems.length;

  useEffect(() => {
    setDraftFilters(emptyBriefFilters);
    setActiveFilters(emptyBriefFilters);
    setSelectedArticles(new Set());
  }, [project.id, setSelectedArticles]);

  function toggleAllArticles() {
    setSelectedArticles(current => {
      const visibleIds = new Set(filteredItems.map(item => item.id));
      if (allSelected) return new Set([...current].filter(id => !visibleIds.has(id)));
      return new Set([...current, ...visibleIds]);
    });
  }

  function applyFilters() {
    const nextFilters = { ...draftFilters };
    const nextItems = filterArticleItems(finalItems, briefById, nextFilters);
    const nextVisibleIds = new Set(nextItems.map(item => item.id));
    setActiveFilters(nextFilters);
    setSelectedArticles(current => new Set([...current].filter(id => nextVisibleIds.has(id))));
  }

  function resetFilters() {
    setDraftFilters(emptyBriefFilters);
    setActiveFilters(emptyBriefFilters);
  }

  return (
    <div className="section-stack">
      {finalItems.length > 0 && (
        <div className="brief-filter-panel">
          <div className="brief-filter-grid">
            <label className="field-block">
              <span>关键词</span>
              <select value={draftFilters.keyword} onChange={event => setDraftFilters(current => ({ ...current, keyword: event.target.value }))}>
                <option value="all">全部</option>
                {keywordOptions.map(keyword => <option key={keyword} value={keyword}>{keyword}</option>)}
              </select>
            </label>
            <label className="field-block">
              <span>文章类型</span>
              <select value={draftFilters.articleType} onChange={event => setDraftFilters(current => ({ ...current, articleType: event.target.value }))}>
                <option value="all">全部</option>
                {articleTypeOptions.map(type => <option key={type} value={type}>{type}</option>)}
              </select>
            </label>
            <label className="field-block">
              <span>Brief 是否修改</span>
              <select value={draftFilters.briefModified} onChange={event => setDraftFilters(current => ({ ...current, briefModified: event.target.value as BriefModifiedFilter }))}>
                <option value="all">全部</option>
                <option value="modified">已修改</option>
                <option value="unmodified">未修改</option>
              </select>
            </label>
            <label className="field-block">
              <span>正文是否审核</span>
              <select value={draftFilters.articleStatus} onChange={event => setDraftFilters(current => ({ ...current, articleStatus: event.target.value as BriefArticleFilter }))}>
                <option value="all">全部</option>
                <option value="approved">已审核正文</option>
              </select>
            </label>
          </div>
          <div className="actions brief-filter-actions">
            <button className="btn primary" onClick={applyFilters}><Search size={15} />确认筛选</button>
            <button className="btn" onClick={resetFilters}><RefreshCw size={15} />重置筛选</button>
          </div>
        </div>
      )}
      <div className="bulk-bar">
        <div><strong>定稿文章归档</strong><span>{finalItems.length ? `已归档 ${finalItems.length} 篇正文，当前显示 ${filteredItems.length} 篇，已选 ${selectedArticleItems.length} 篇。` : "暂无已审核通过正文。"}</span></div>
        <div className="actions">
          <button className="btn" disabled={!filteredItems.length} onClick={toggleAllArticles}>{allSelected ? "取消全选" : "全选正文"}</button>
          <button className="btn primary" disabled={!selectedArticleItems.length} onClick={() => downloadArticleMarkdown(selectedArticleItems)}><Download size={15} />导出正文</button>
        </div>
      </div>
      {filteredItems.length ? (
        <div className="article-list">
          {filteredItems.map(item => {
            const boundBrief = briefById.get(item.briefId || "");
            const importedArticle = articleIsImportedMarkdown(item);
            return (
              <article className={`article-collapse ${articleReviewCardClass(item, boundBrief)}`} key={item.id}>
                <div className="article-card-head">
                  <input type="checkbox" checked={selectedArticles.has(item.id)} onChange={() => {
                    setSelectedArticles(current => toggleSet(current, item.id));
                  }} />
                  <div>
                    <h3>{item.title}</h3>
                    <div className="chips meta-chips review-meta-chips">
                      <Chip text={item.keyword} type="brand" className="keyword-chip" />
                      <Chip text={item.type} className="type-chip" />
                      {importedArticle ? (
                        <Chip text="自定义导入" type="good" className="state-chip" />
                      ) : boundBrief ? (
                        <Chip text="已绑定 Brief" type="good" className="state-chip" />
                      ) : null}
                      <ItemStatusChip status={item.status} className="state-chip" />
                    </div>
                  </div>
                  <TimeStampChip label="定稿时间" value={timestampLabel(item.articleAuditedAt)} />
                  <AuditStatusBlock item={item} />
                  <div className="row-actions">
                    <button className="btn" onClick={() => openDetail(item)}><BookOpen size={15} />查阅</button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <Panel title="暂无定稿" icon={<Archive size={16} />}>
          <EmptyPanelText text={finalItems.length ? "当前筛选条件下没有已审核正文。" : "暂无已审核通过正文，请先在正文审核页完成审核。"} />
        </Panel>
      )}
    </div>
  );
}

function PlanGroupAside({
  rows,
  selectedPlans,
  expanded,
  readOnly = false,
  onSelectionChange,
  onToggleExpanded
}: {
  rows: ContentItem[];
  selectedPlans: Set<string>;
  expanded: boolean;
  readOnly?: boolean;
  onSelectionChange: (rows: ContentItem[], selected: boolean) => void;
  onToggleExpanded: () => void;
}) {
  return (
    <div className="plan-group-actions">
      {readOnly ? <Chip text={`${rows.length} 条`} /> : <GroupSelectAside rows={rows} selectedPlans={selectedPlans} onChange={onSelectionChange} />}
      <button className={`btn compact dropdown-toggle ${expanded ? "open" : ""}`} onClick={onToggleExpanded}>
        <ChevronDown size={15} />
        {expanded ? "收起" : "展开"}
      </button>
    </div>
  );
}

function planGroupStatsText(rows: ContentItem[], selectedPlans: Set<string>, briefBySource: Map<string, ContentItem>): string {
  const selectedCount = rows.filter(item => selectedPlans.has(item.id)).length;
  const briefCount = rows.filter(item => briefIsGenerated(briefBySource.get(item.sourceId))).length;
  return `${rows.length} 条规划，已选 ${selectedCount} 条，已生成 Brief ${briefCount} 条`;
}

function GroupSelectAside({
  rows,
  selectedPlans,
  onChange
}: {
  rows: ContentItem[];
  selectedPlans: Set<string>;
  onChange: (rows: ContentItem[], selected: boolean) => void;
}) {
  const allSelected = rows.length > 0 && rows.every(item => selectedPlans.has(item.id));
  const selectedCount = rows.filter(item => selectedPlans.has(item.id)).length;
  return (
    <div className="group-select">
      <Chip text={`${selectedCount}/${rows.length} 条`} />
      <button className="btn compact" onClick={() => onChange(rows, !allSelected)}>
        {allSelected ? "取消全选" : "全选"}
      </button>
    </div>
  );
}

function PlanRow({
  item,
  selected,
  readOnly = false,
  brief,
  article,
  onToggle,
  onOpen,
  onCopy,
  onEdit,
  onDelete,
  editDisabled = false
}: {
  item: ContentItem;
  selected: boolean;
  readOnly?: boolean;
  brief?: ContentItem;
  article?: ContentItem;
  onToggle: () => void;
  onOpen?: () => void;
  onCopy?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  editDisabled?: boolean;
}) {
  return (
    <article className={`plan-row ${planReviewCardClass(brief, article)} ${selected ? "selected" : ""}`}>
      {!readOnly && <input type="checkbox" checked={selected} onChange={onToggle} />}
      <div>
        <h3>{item.type}｜{item.title}</h3>
        <p>{item.role}</p>
        <div className="chips meta-chips plan-meta-chips">
          <Chip text={item.keyword} type="brand" className="keyword-chip" />
          <Chip text={item.channel} className="channel-chip" />
          {readOnly ? <Chip text="仅查看" /> : <PlanBriefStatusChip status={brief?.status} />}
        </div>
      </div>
      <div className="row-actions">
        {onOpen && <button className="btn" onClick={onOpen}><BookOpen size={15} />{readOnly ? "查阅" : "查阅/编辑"}</button>}
        {onCopy && <button className="btn" onClick={onCopy}><Copy size={15} />复制为自定义</button>}
        {onEdit && <button className="btn" disabled={editDisabled} title={editDisabled ? "已生成 Brief 后请在 Brief 审核页修改" : ""} onClick={onEdit}><PenLine size={15} />编辑</button>}
        {onDelete && <button className="btn" onClick={onDelete}><Trash2 size={15} />删除</button>}
      </div>
    </article>
  );
}

function Panel({ title, icon, children, aside, subtitle }: { title: string; icon: React.ReactNode; children: React.ReactNode; aside?: React.ReactNode; subtitle?: string }) {
  const hasBody = children !== null && children !== undefined && children !== false;
  return (
    <section className="panel">
      <div className="panel-head">
        <div className="panel-title-wrap">
          <div className="panel-title">{icon}<span>{title}</span></div>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {aside}
      </div>
      {hasBody && <div className="panel-body">{children}</div>}
    </section>
  );
}

function Activity({ icon, title, desc, action }: { icon: React.ReactNode; title: string; desc: string; action?: React.ReactNode }) {
  return <div className="activity-item">{icon}<div><strong>{title}</strong><span>{desc}</span></div>{action}</div>;
}

function Stat({ value, label }: { value: number; label: string }) {
  return <div className="stat"><strong>{value}</strong><span>{label}</span></div>;
}

function Chip({ text, type = "", className = "" }: { text: string | number; type?: string; className?: string }) {
  const label = String(text);
  return <span className={`chip ${type} ${className}`.trim()} title={label}><span>{label}</span></span>;
}

function TimeStampChip({ label, value }: { label: string; value?: string }) {
  if (!value) {
    return (
      <div className="timestamp-chip empty" aria-hidden="true">
        <span>{label}</span>
        <strong>00/00 00:00</strong>
      </div>
    );
  }
  return (
    <div className="timestamp-chip" title={`${label}：${value}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AuditStatusBlock({ item }: { item: ContentItem }) {
  const approved = articleAuditApproved(item);
  return (
    <div className={`audit-status-block ${approved ? "approved" : "pending"}`}>
      <strong>{articleAuditStatusLabel(item)}</strong>
    </div>
  );
}

function PlanBriefStatusChip({ status }: { status?: string }) {
  if (status === "running" || status === "queued") {
    return <Chip text="Brief 生成中" type="warn" className="state-chip" />;
  }
  if (status === "failed" || status === "pending") {
    return <Chip text="未生成 Brief" type="warn" className="state-chip" />;
  }
  if (status) {
    return <Chip text="已生成 Brief" type="good" className="state-chip" />;
  }
  return <Chip text="未生成 Brief" type="warn" className="state-chip" />;
}

function briefIsGenerated(brief?: ContentItem): boolean {
  if (!brief) return false;
  if (["failed", "running", "queued", "pending"].includes(brief.status)) return false;
  return Boolean((brief.markdown || "").trim());
}

function Status({ status }: { status: string }) {
  const type = status.includes("confirmed") || status.includes("已") || status.includes("parsed") ? "good" : status.includes("failed") ? "danger" : status.includes("running") || status.includes("completed") || status.includes("cancelling") || status.includes("cancelled") ? "warn" : "";
  return <Chip text={status} type={type} />;
}

function ItemStatusChip({ status, className = "" }: { status: string; className?: string }) {
  const type = status.includes("失败") || status.includes("failed")
    ? "danger"
    : status.includes("需更新") || status.includes("旧 Brief") || status.includes("待生成") || status.includes("已修改") || status.includes("modified") || status.includes("stale")
      ? "warn"
      : status.includes("生成中") || status.includes("running") || status.includes("cancelling") || status.includes("cancelled")
      ? "warn"
      : status.includes("完成") || status.includes("已生成") || status.includes("已更新") || status.includes("completed") || status.includes("generated")
        ? "good"
        : "";
  return <Chip text={statusLabel(status)} type={type} className={className} />;
}

function StepProgressPanel({
  project,
  steps = ["materials", "intake"],
  dismissedJobIds,
  dismissJob,
  cancelJob
}: {
  project: Project;
  steps?: WorkflowStep[];
  dismissedJobIds: Set<string>;
  dismissJob: (jobId: string) => void;
  cancelJob: (jobId: string) => Promise<void>;
}) {
  const jobs = steps.map(step => latestJob(project, step)).filter((job): job is Project["jobs"][number] => Boolean(job));
  const activeJob = jobs.find(job => job.status === "running" || job.status === "queued" || job.status === "cancelling");
  const blockedStep = steps.find(step => outputBlockerMessage(project.steps[step].output));
  const failedJob = jobs.find(job => job.status === "failed");
  const cancelledJob = jobs.find(job => job.status === "cancelled");
  const completedJobs = jobs.filter(job => job.status === "completed" && !dismissedJobIds.has(job.id));
  const visibleJobs = activeJob ? [activeJob] : failedJob ? [failedJob] : cancelledJob ? [cancelledJob] : blockedStep ? [] : completedJobs;
  const fallbackFailures = steps.filter(step => step !== blockedStep && (project.steps[step].status === "failed" || outputBlockerMessage(project.steps[step].output)) && !jobs.some(job => job.step === step));

  if (!visibleJobs.length && !fallbackFailures.length && !blockedStep) return null;

  return (
    <div className="step-progress-panel">
      <div className="step-progress-title">
        {activeJob ? <Loader2 className="spin" size={16} /> : failedJob || fallbackFailures.length || blockedStep ? <CircleAlert size={16} /> : cancelledJob ? <CircleAlert size={16} /> : <CheckCircle2 size={16} />}
        <div>
          <strong>{activeJob ? progressTitle(activeJob.step, true) : blockedStep ? "需要补充输入" : failedJob || fallbackFailures.length ? "任务失败" : cancelledJob ? "任务已停止" : "执行完成"}</strong>
          <span>{blockedStep ? outputBlockerMessage(project.steps[blockedStep].output) : progressSubtitle(activeJob || failedJob || cancelledJob || visibleJobs[0])}</span>
        </div>
      </div>
      {visibleJobs.map(job => <JobProgress job={job} dismissedJobIds={dismissedJobIds} onDismiss={dismissJob} onCancel={cancelJob} key={job.id} />)}
      {blockedStep && (
        <div className="job-progress failed">
          <div className="job-progress-head">
            <strong>{progressTitle(blockedStep, false)}需要补充输入</strong>
            <ItemStatusChip status="failed" />
          </div>
          <div className="job-progress-bar"><span style={{ width: "100%" }} /></div>
          <p className="item-error">{outputBlockerMessage(project.steps[blockedStep].output)}</p>
        </div>
      )}
      {fallbackFailures.map(step => (
        <div className="job-progress failed" key={step}>
          <div className="job-progress-head">
            <strong>{friendlyErrorText(outputBlockerMessage(project.steps[step].output) || project.steps[step].error || `${stepLabel(step)}失败，可重试。`)}</strong>
            <ItemStatusChip status="failed" />
          </div>
          <div className="job-progress-bar"><span style={{ width: "100%" }} /></div>
          <p className="item-error">{friendlyErrorText(outputBlockerMessage(project.steps[step].output) || project.steps[step].error || "后台任务未留下进度记录，请重新运行该步骤。")}</p>
        </div>
      ))}
    </div>
  );
}

function JobProgress({
  job,
  dismissedJobIds,
  onDismiss,
  onCancel
}: {
  job?: Project["jobs"][number];
  dismissedJobIds: Set<string>;
  onDismiss: (jobId: string) => void;
  onCancel?: (jobId: string) => Promise<void>;
}) {
  if (!job || (job.status === "completed" && dismissedJobIds.has(job.id)) || (!job.total_count && !job.message && job.status === "queued")) return null;
  const total = Math.max(job.total_count || 0, 1);
  const rawProcessed = (job.completed_count || 0) + (job.failed_count || 0) + (job.skipped_count || 0);
  const processed = (job.status === "completed" || job.status === "cancelled") && rawProcessed === 0 && !job.total_count ? total : Math.min(rawProcessed, total);
  const percent = Math.round((processed / total) * 100);
  const indeterminate = (job.status === "running" || job.status === "cancelling") && total <= 1 && processed === 0;
  const canDismiss = job.status === "completed";
  const canCancel = Boolean(onCancel) && (job.status === "queued" || job.status === "running");
  return (
    <div className={`job-progress ${job.status}`}>
      <div className="job-progress-head">
        <strong>{job.message || progressSubtitle(job)}</strong>
        <div className="job-progress-status">
          <ItemStatusChip status={job.status} />
          {canCancel && (
            <button type="button" className="btn danger compact job-cancel" title="停止当前任务" onClick={() => void onCancel?.(job.id)}>
              <X size={14} />停止
            </button>
          )}
          {canDismiss && (
            <button type="button" className="icon-btn job-dismiss" aria-label="关闭完成提示" title="关闭完成提示" onClick={() => onDismiss(job.id)}>
              <X size={14} />
            </button>
          )}
        </div>
      </div>
      <div className={`job-progress-bar ${indeterminate ? "indeterminate" : ""}`}>
        <span style={{ width: indeterminate ? "38%" : `${percent}%` }} />
      </div>
      <div className="job-progress-meta">
        <span>成功 {job.completed_count || 0}/{job.total_count || 0}</span>
        <span>跳过 {job.skipped_count || 0}</span>
        <span>失败 {job.failed_count || 0}</span>
        {job.current_item && <span>当前：{job.current_item}</span>}
      </div>
      {job.error && <p className="item-error">{friendlyErrorText(job.error)}</p>}
    </div>
  );
}

function ItemDetailModal({
  detail,
  canRegenerate,
  onClose,
  onSave,
  onAudit,
  onRegenerate
}: {
  detail: DetailState;
  canRegenerate: boolean;
  onClose: () => void;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onAudit: (status: "approved" | "rejected", reviewNotes: string) => Promise<void>;
  onRegenerate: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const [title, setTitle] = useState(detail.item.title);
  const [markdown, setMarkdown] = useState(detail.item.markdown || "");
  const [reviewNotes, setReviewNotes] = useState(detail.item.reviewNotes || "");
  const [copied, setCopied] = useState(false);
  const isAuditMode = detail.step === "article" && detail.mode === "audit";
  const isReadOnlyMode = detail.mode === "read" || detail.step === "demand_matrix";
  const canEditMarkdown = !isAuditMode && !isReadOnlyMode && (detail.step === "brief" || detail.step === "article");
  const fullText = markdown || JSON.stringify(detail.item.raw, null, 2);
  const readOnlyText = fullText.trim();

  useEffect(() => {
    setTitle(detail.item.title);
    setMarkdown(detail.item.markdown || "");
    setReviewNotes(detail.item.reviewNotes || "");
    setCopied(false);
  }, [detail]);

  async function copyFullText() {
    await navigator.clipboard.writeText(fullText);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div className="modal-backdrop detail-backdrop" role="presentation">
      <div className={`detail-modal ${isReadOnlyMode ? "read-only-detail" : ""}`} role="dialog" aria-modal="true" aria-labelledby="item-detail-title">
        <div className="detail-head">
          <div>
            <span className="detail-kicker">{isAuditMode ? "正文审核" : stepLabel(detail.step)} / {detail.item.keyword}</span>
            <h2 id="item-detail-title">{detail.item.title}</h2>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="关闭"><X size={16} /></button>
        </div>
        <div className="detail-meta">
          <Chip text={detail.item.type} />
          <ItemStatusChip status={detail.item.status} />
          {detail.step === "article" && <Chip text={`审核：${articleAuditStatusLabel(detail.item)}`} type={articleAuditApproved(detail.item) ? "good" : "warn"} />}
          {detail.item.sourceStep && <Chip text={detail.item.sourceStep} />}
          {detail.item.briefId && <Chip text={`Brief ${detail.item.briefId}`} />}
        </div>
        {detail.item.error && <p className="item-error">{detail.item.error}</p>}
        {!isReadOnlyMode && (
          <label className="field-block">
            <span>标题</span>
            <input value={title} readOnly={isAuditMode} onChange={event => setTitle(event.target.value)} />
          </label>
        )}
        {isReadOnlyMode ? (
          <section className="field-block read-only-markdown-block">
            <span>{detail.step === "brief" || detail.step === "article" ? "完整 Markdown" : "完整规划数据"}</span>
            <pre className="read-only-markdown">{readOnlyText}</pre>
          </section>
        ) : (
          <label className="field-block markdown-edit-block">
            <span>{detail.step === "brief" || detail.step === "article" ? "完整 Markdown" : "完整规划数据"}</span>
            <textarea
              value={fullText}
              readOnly={!canEditMarkdown}
              onChange={event => setMarkdown(event.target.value)}
            />
          </label>
        )}
        {!isReadOnlyMode && (
          <>
            <label className="field-block">
              <span>修改意见</span>
              <textarea
                className="notes-area"
                value={reviewNotes}
                onChange={event => setReviewNotes(event.target.value)}
                placeholder="记录人工审核意见、补充事实、标题调整方向或需要重跑的要求。"
              />
            </label>
            <div className="actions end">
              <button className="btn" onClick={() => void copyFullText()}><Copy size={15} />{copied ? "已复制" : "复制全文"}</button>
              {isAuditMode ? (
                <>
                  <button className="btn" onClick={() => void onAudit("rejected", reviewNotes)}><CircleAlert size={15} />审核不通过</button>
                  <button className="btn primary" onClick={() => void onAudit("approved", reviewNotes)}><CheckCircle2 size={15} />审核通过</button>
                </>
              ) : (
                <>
                  {canRegenerate && <button className="btn" disabled={detail.item.status === "running"} onClick={() => void onRegenerate({
                    title,
                    markdown: canEditMarkdown ? markdown : detail.item.markdown || "",
                    review_notes: reviewNotes
                  })}><RefreshCw size={15} />{detail.item.status === "failed" ? "重试单篇" : "重新生成单篇"}</button>}
                  <button className="btn primary" onClick={() => void onSave({
                    title,
                    markdown: canEditMarkdown ? markdown : detail.item.markdown || "",
                    review_notes: reviewNotes
                  })}><Save size={15} />保存</button>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return <div className="panel empty">请先创建或选择一个项目。</div>;
}

function EmptyPanelText({ text }: { text: string }) {
  return <p className="muted">{text}</p>;
}

interface DerivedData {
  intakeRows: IntakeRow[];
  matrixPlans: ContentItem[];
  matrixIntentGroups: MatrixIntentGroup[];
  demandMatrixPlans: ContentItem[];
  demandMatrixIntentGroups: MatrixIntentGroup[];
  breakthroughPlans: ContentItem[];
  customPlans: ContentItem[];
  matrixKeywords: string[];
  confirmedBreakthroughKeywords: string[];
  plans: ContentItem[];
  briefs: ContentItem[];
  articles: ContentItem[];
  archiveCount: number;
}

function emptyDerivedData(): DerivedData {
  return { intakeRows: [], matrixPlans: [], matrixIntentGroups: [], demandMatrixPlans: [], demandMatrixIntentGroups: [], breakthroughPlans: [], customPlans: [], matrixKeywords: [], confirmedBreakthroughKeywords: [], plans: [], briefs: [], articles: [], archiveCount: 0 };
}

function deriveProjectData(project: Project): DerivedData {
  const allowedKeywords = projectAllowedKeywords(project);
  const matrixPlans = canonicalizeItemsForAllowedKeywords(normalizeItems(project.steps.matrix.output, "matrix"), allowedKeywords).filter(item => isCoreArticleType(item.type));
  const matrixIntentGroups = normalizeMatrixIntentGroups(project.steps.matrix.output, matrixPlans);
  const demandMatrixPlans = canonicalizeItemsForAllowedKeywords(normalizeItems(project.steps.demand_matrix?.output || {}, "demand_matrix"), allowedKeywords).filter(item => isCoreArticleType(item.type));
  const demandMatrixIntentGroups = normalizeMatrixIntentGroups(project.steps.demand_matrix?.output || {}, demandMatrixPlans);
  const matrixKeywordOptions = extractMatrixKeywordOptions(project.steps.matrix.output);
  const breakthroughPlans = canonicalizeItemsForAllowedKeywords(normalizeItems(project.steps.breakthrough.output, "breakthrough"), allowedKeywords).filter(item => isCoreArticleType(item.type));
  const customPlans = canonicalizeItemsForAllowedKeywords(normalizeItems({ items: project.custom_sources || [] }, "custom"), allowedKeywords);
  const briefs = sortBriefsNewestFirst(canonicalizeItemsForAllowedKeywords(normalizeItems(project.steps.brief.output, "brief"), allowedKeywords));
  const articles = sortArticlesNewestFirst(canonicalizeItemsForAllowedKeywords(normalizeItems(project.steps.article.output, "article"), allowedKeywords));
  const briefById = new Map(briefs.map(item => [item.id, item]));
  return {
    intakeRows: normalizeIntake(project.steps.intake.output),
    matrixPlans,
    matrixIntentGroups,
    demandMatrixPlans,
    demandMatrixIntentGroups,
    breakthroughPlans,
    customPlans,
    matrixKeywords: allowedKeywords.length ? allowedKeywords : matrixKeywordOptions.length ? matrixKeywordOptions : uniqueKeywords(matrixPlans),
    confirmedBreakthroughKeywords: filterAllowedKeywords(readConfirmedBreakthroughKeywords(project.steps.matrix.output), allowedKeywords),
    plans: [...matrixPlans, ...breakthroughPlans, ...customPlans],
    briefs,
    articles,
    archiveCount: articles.filter(article => articleIsFinal(article, briefById)).length
  };
}

function deriveDashboardData(project: Project, data: DerivedData, publishingUsage: PublishingUsageSummary | null): DashboardData {
  const briefBySource = new Map(data.briefs.map(item => [item.sourceId, item]));
  const briefById = new Map(data.briefs.map(item => [item.id, item]));
  const articlesByBriefId = new Map(data.articles.map(item => [item.briefId || item.id, item]));
  const allContentItems = [...data.plans, ...data.briefs, ...data.articles];
  const allowedKeywords = projectAllowedKeywords(project);
  const keywords = allowedKeywords.length ? allowedKeywords : uniqueStrings([
    ...data.matrixKeywords,
    ...allContentItems.map(item => item.keyword)
  ]).filter(keyword => keyword && keyword !== "未标注关键词");
  const articleTypes = orderedArticleTypes(allContentItems, true, false);
  const articleFinalCount = data.articles.filter(article => articleIsFinal(article, briefById)).length;
  const articleUsedCount = data.articles.filter(article => articlePublishedCount(article, publishingUsage) > 0 || itemIsUsed(article)).length;
  const articlePurchasingCount = data.articles.filter(article => articlePurchasingCountFor(article, publishingUsage) > 0).length;
  const staleArticles = data.articles.filter(article => !articleIsFinal(article, briefById)).length;
  const pendingBriefs = data.plans.filter(plan => !briefIsGenerated(briefBySource.get(plan.sourceId))).length;
  const pendingArticles = data.briefs.filter(brief => {
    const article = articlesByBriefId.get(brief.id);
    return briefIsGenerated(brief) && (!article || !articleCurrentForBrief(article, brief));
  }).length;

  const keywordRows = keywords.map((keyword, index) => dashboardProgressRow(
    `keyword-${index}`,
    keyword,
    data.plans.filter(item => item.keyword === keyword),
    data.briefs.filter(item => item.keyword === keyword),
    data.articles.filter(item => item.keyword === keyword),
    briefById,
    publishingUsage,
    { view: "planning", tab: "matrix", keyword }
  ));

  const typeRows = articleTypes.map((type, index) => dashboardProgressRow(
    `type-${index}`,
    type,
    data.plans.filter(item => item.type === type),
    data.briefs.filter(item => item.type === type),
    data.articles.filter(item => item.type === type),
    briefById,
    publishingUsage,
    { view: "planning", tab: "matrix", articleType: type }
  ));

  const matrix = keywords.flatMap(keyword => articleTypes.map(type => {
    const plans = data.plans.filter(item => item.keyword === keyword && item.type === type);
    const briefs = data.briefs.filter(item => item.keyword === keyword && item.type === type);
    const articles = data.articles.filter(item => item.keyword === keyword && item.type === type);
    return dashboardMatrixCell(keyword, type, plans, briefs, articles, briefById, publishingUsage);
  }));

  return {
    summary: dashboardSummary(project, data, keywords.length),
    keywords: keywordRows,
    articleTypes: typeRows,
    matrix,
    totals: {
      plans: data.plans.length,
      briefs: data.briefs.length,
      articles: data.articles.length,
      completed: articleFinalCount,
      used: articleUsedCount,
      purchasing: articlePurchasingCount,
      pendingBriefs,
      pendingArticles,
      staleArticles,
      pendingPlanCells: matrix.filter(cell => cell.stage === "pending_plan").length
    }
  };
}

function dashboardSummary(project: Project, data: DerivedData, keywordCount: number): DashboardSummary {
  const profile = isRecord(project.steps.matrix.output.project) ? project.steps.matrix.output.project : {};
  const brand = readString(profile, ["target_brand", "brand", "目标品牌"], "");
  const product = readString(profile, ["target_product_or_solution", "target_product", "product", "目标产品", "解决方案"], "");
  const profileKeywords = readStringList(profile, [
    "main_keywords",
    "target_keywords",
    "keywords",
    "主要关键词",
    "目标关键词",
    "关键词"
  ]);
  return {
    title: project.name,
    brand,
    product,
    mainKeywords: dashboardMainKeywords(project, data, profileKeywords),
    keywordCount,
    totalPlans: data.plans.length,
    period: projectPeriodLabel(project, data.intakeRows)
  };
}

function dashboardMainKeywords(project: Project, data: DerivedData, profileKeywords: string[]): string[] {
  const allowedKeywords = projectAllowedKeywords(project);
  if (allowedKeywords.length) return allowedKeywords;
  const intakeKeywords = data.intakeRows
    .filter(row => /关键词/.test(row.field))
    .flatMap(row => row.value.split(/[、，,;；\n]/).map(item => item.trim()));
  return uniqueStrings([
    ...data.matrixKeywords,
    ...profileKeywords,
    ...intakeKeywords
  ]).filter(keyword => keyword && keyword !== "未标注关键词");
}

function projectAllowedKeywords(project: Project): string[] {
  return uniqueStrings(Array.isArray(project.allowed_keywords) ? project.allowed_keywords : []);
}

function filterAllowedKeywords(keywords: string[], allowedKeywords: string[]): string[] {
  if (!allowedKeywords.length) return keywords;
  const allowedSet = new Set(allowedKeywords);
  return uniqueStrings(keywords.map(keyword => normalizeKeywordToAllowed(keyword, allowedKeywords)).filter(keyword => allowedSet.has(keyword)));
}

function canonicalizeItemsForAllowedKeywords(items: ContentItem[], allowedKeywords: string[]): ContentItem[] {
  if (!allowedKeywords.length) return items;
  const allowedSet = new Set(allowedKeywords);
  return items.flatMap(item => {
    const keyword = normalizeKeywordToAllowed(item.keyword, allowedKeywords);
    if (!allowedSet.has(keyword)) return [];
    return [{ ...item, keyword }];
  });
}

function normalizeKeywordToAllowed(keyword: string, allowedKeywords: string[]): string {
  const text = `${keyword || ""}`.trim().replace(/\s+/g, " ");
  if (!allowedKeywords.length || !text || allowedKeywords.includes(text)) return text;
  const matches = allowedKeywords.filter(allowed => text.includes(allowed));
  if (!matches.length) return text;
  return [...matches].sort((left, right) => text.indexOf(left) - text.indexOf(right))[0];
}

function projectPeriodLabel(project: Project, intakeRows: IntakeRow[]): string {
  const periodRow = intakeRows.find(row => /周期|时间|日期|排期/.test(row.field) && row.value && row.value !== "未标注");
  if (periodRow) return periodRow.value;
  return `${shortDate(project.created_at)} - ${shortDate(project.updated_at)}`;
}

function shortDate(value: string): string {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "未记录";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date(parsed));
}

function dashboardProgressRow(
  id: string,
  label: string,
  plans: ContentItem[],
  briefs: ContentItem[],
  articles: ContentItem[],
  briefById: Map<string, ContentItem>,
  publishingUsage: PublishingUsageSummary | null,
  drilldown: DashboardDrilldown
): DashboardProgressRow {
  const completed = articles.filter(article => articleIsFinal(article, briefById)).length;
  const used = articles.filter(article => articlePublishedCount(article, publishingUsage) > 0 || itemIsUsed(article)).length;
  const purchasing = articles.filter(article => articlePurchasingCountFor(article, publishingUsage) > 0).length;
  const progressTotal = Math.max(plans.length, briefs.length, articles.length);
  return {
    id,
    label,
    plans: plans.length,
    briefs: briefs.length,
    articles: articles.length,
    completed,
    used,
    purchasing,
    percent: percentOf(completed, progressTotal),
    drilldown
  };
}

function dashboardMatrixCell(
  keyword: string,
  type: string,
  plans: ContentItem[],
  briefs: ContentItem[],
  articles: ContentItem[],
  briefById: Map<string, ContentItem>,
  publishingUsage: PublishingUsageSummary | null
): DashboardMatrixCell {
  const completed = articles.filter(article => articleIsFinal(article, briefById)).length;
  const used = articles.filter(article => articlePublishedCount(article, publishingUsage) > 0 || itemIsUsed(article)).length;
  const purchasing = articles.filter(article => articlePurchasingCountFor(article, publishingUsage) > 0).length;
  const stale = articles.filter(article => !articleIsFinal(article, briefById)).length;
  const stage = dashboardCellStage(plans.length, briefs.length, articles.length, completed, used, purchasing);
  return {
    id: stableContentId("dashboard", keyword, type, "", `${keyword}-${type}`),
    keyword,
    type,
    plans: plans.length,
    briefs: briefs.length,
    articles: articles.length,
    completed,
    used,
    purchasing,
    stale,
    stage,
    label: dashboardStageLabel(stage, briefs.length, completed, used, purchasing),
    drilldown: dashboardDrilldownForStage(stage, keyword, type)
  };
}

function dashboardCellStage(planCount: number, briefCount: number, articleCount: number, completedCount: number, usedCount: number, purchasingCount: number): DashboardProductionStage {
  if (!planCount && !briefCount && !articleCount) return "pending_plan";
  if (usedCount > 0) return "used";
  if (purchasingCount > 0) return "purchasing";
  if (completedCount > 0) return "article_done";
  if (articleCount > 0) return "article_pending";
  if (briefCount > 0) return "brief_done";
  return "pending_brief";
}

function dashboardStageLabel(stage: DashboardProductionStage, briefCount: number, completedCount: number, usedCount: number, purchasingCount: number): string {
  if (stage === "pending_plan") return "待补规划";
  if (stage === "pending_brief") return "待生成 Brief";
  if (stage === "brief_done") return `${briefCount} Brief完成`;
  if (stage === "article_pending") return "正文待审";
  if (stage === "article_done") return `${completedCount} 已定稿`;
  if (stage === "purchasing") return `${purchasingCount} 采购中`;
  return `${usedCount} 已使用`;
}

function dashboardDrilldownForStage(stage: DashboardProductionStage, keyword: string, articleType: string): DashboardDrilldown {
  const base = { keyword, articleType };
  if (stage === "pending_plan" || stage === "pending_brief") return { view: "planning", tab: "matrix", ...base };
  if (stage === "brief_done") return { view: "brief", articleStatus: "not_generated", ...base };
  if (stage === "article_pending") return { view: "article", articleStatus: "pending_review", ...base };
  if (stage === "article_done") return { view: "article", articleStatus: "approved", ...base };
  if (stage === "purchasing") return { view: "article", articleStatus: "approved", ...base };
  return { view: "article", articleStatus: "generated", ...base };
}

function articlePublishedCount(article: ContentItem, publishingUsage: PublishingUsageSummary | null): number {
  const usage = publishingUsage?.articles.find(item => item.article_id === article.id);
  return usage?.published_count || 0;
}

function articlePurchasingCountFor(article: ContentItem, publishingUsage: PublishingUsageSummary | null): number {
  const usage = publishingUsage?.articles.find(item => item.article_id === article.id);
  return usage?.purchasing_count || 0;
}

function orderedArticleTypes(items: ContentItem[], includeCore = false, includeDiscovered = true): string[] {
  const discovered = uniqueStrings(items.map(item => item.type).filter(Boolean));
  const base = includeCore ? coreArticleTypes : coreArticleTypes.filter(type => discovered.includes(type));
  if (!includeDiscovered) return base;
  return [...base, ...discovered.filter(type => !base.includes(type))];
}

function isCoreArticleType(value: string): boolean {
  return coreArticleTypeSet.has(value);
}

function completeBreakthroughKeywords(items: ContentItem[]): string[] {
  const present = new Map<string, Set<string>>();
  items.forEach(item => {
    if (!item.keyword || !item.type) return;
    if (!present.has(item.keyword)) present.set(item.keyword, new Set());
    present.get(item.keyword)?.add(item.type);
  });
  return uniqueKeywords(items).filter(keyword => coreArticleTypes.every(type => present.get(keyword)?.has(type)));
}

function missingBreakthroughTypes(items: ContentItem[], confirmedKeywords: string[]): Record<string, string[]> {
  const present = new Map<string, Set<string>>();
  items.forEach(item => {
    if (!item.keyword || !item.type) return;
    if (!present.has(item.keyword)) present.set(item.keyword, new Set());
    present.get(item.keyword)?.add(item.type);
  });
  return Object.fromEntries(confirmedKeywords.map(keyword => {
    const existing = present.get(keyword) || new Set<string>();
    return [keyword, coreArticleTypes.filter(type => !existing.has(type))];
  }).filter(([, types]) => types.length > 0));
}

function planningGenerationButtonText({
  tab,
  isRunning,
  needsBreakthroughKeywords,
  canRegenerateCurrentStep,
  breakthroughComplete,
  hasBreakthroughOutput,
  breakthroughMissingCount,
  breakthroughNewKeywordCount,
  planningLabel
}: {
  tab: PlanningTab;
  isRunning: boolean;
  needsBreakthroughKeywords: boolean;
  canRegenerateCurrentStep: boolean;
  breakthroughComplete: boolean;
  hasBreakthroughOutput: boolean;
  breakthroughMissingCount: number;
  breakthroughNewKeywordCount: number;
  planningLabel: string;
}): string {
  if (isRunning) return "生成中";
  if (needsBreakthroughKeywords) return "先选择逐词击破关键词";
  if (tab === "breakthrough") {
    if (breakthroughComplete) return "逐词击破已完整";
    if (breakthroughNewKeywordCount > 0) return "新增关键词规划";
    if (hasBreakthroughOutput && breakthroughMissingCount > 0) return "补齐缺失规划";
    return "新增关键词规划";
  }
  if (canRegenerateCurrentStep) return `重新生成${planningLabel}`;
  return `生成${planningLabel}`;
}

function breakthroughKeywordSummaryTitle(scopeKeywords: string[]): string {
  if (scopeKeywords.length) return "上一步选择要进行逐词击破的关键词";
  return "尚未选择要进行逐词击破的关键词";
}

function breakthroughKeywordSummaryText(scopeKeywords: string[]): string {
  if (scopeKeywords.length) return scopeKeywords.join("、");
  return "仅生成逐词击破时需要先回内容矩阵 Tab 勾选关键词；矩阵规划可直接生成 Brief。";
}

function filterPlanningItems(items: ContentItem[], filters: PlanningFilterState): ContentItem[] {
  return items.filter(item => {
    if (filters.keyword !== "all" && item.keyword !== filters.keyword) return false;
    if (filters.articleType !== "all" && item.type !== filters.articleType) return false;
    return true;
  });
}

function filterCustomItems(
  items: ContentItem[],
  briefBySource: Map<string, ContentItem>,
  filters: CustomFilterState
): ContentItem[] {
  return items.filter(item => {
    if (filters.keyword !== "all" && item.keyword !== filters.keyword) return false;
    if (filters.articleType !== "all" && item.type !== filters.articleType) return false;
    if (filters.briefStatus !== "all") {
      const generated = briefIsGenerated(briefBySource.get(item.sourceId));
      if (filters.briefStatus === "generated" && !generated) return false;
      if (filters.briefStatus === "not_generated" && generated) return false;
    }
    return true;
  });
}

function articleIsFinal(article: ContentItem, briefById: Map<string, ContentItem>): boolean {
  if (article.status === "failed" || article.status === "stale" || article.status === "running" || article.status === "queued") return false;
  const brief = article.briefId ? briefById.get(article.briefId) : undefined;
  if (brief && !articleCurrentForBrief(article, brief)) return false;
  return Boolean(article.markdown) && articleAuditApproved(article);
}

function articleAuditApproved(article: ContentItem): boolean {
  return (article.articleAuditStatus || readString(article.raw, ["article_audit_status", "articleAuditStatus"], "")).toLowerCase() === "approved";
}

function articleAuditStatusLabel(article: ContentItem): string {
  return articleAuditApproved(article) ? "已审核正文" : "暂未审核正文";
}

function articleIsImportedMarkdown(article: ContentItem): boolean {
  return article.sourceStep === "imported" || isRecord(article.raw.imported_from);
}

function importedArticleFilename(article: ContentItem): string {
  const importedFrom = article.raw.imported_from;
  if (!isRecord(importedFrom)) return "本地 Markdown";
  return readString(importedFrom, ["filename", "file_name", "name"], "本地 Markdown");
}

function importedArticleImportedAt(article: ContentItem): string {
  const importedFrom = article.raw.imported_from;
  if (isRecord(importedFrom)) {
    const importedAt = readString(importedFrom, ["imported_at", "importedAt"], "");
    if (importedAt) return importedAt;
  }
  return article.articleAuditedAt || readString(article.raw, ["article_audited_at", "articleAuditedAt"], "");
}

function itemIsUsed(item: ContentItem): boolean {
  const used = `${item.used || readString(item.raw, ["used", "使用状态"], "")}`.trim();
  if (!used || used === "未使用") return false;
  return used.includes("已") || used.toLowerCase().includes("used");
}

function percentOf(value: number, total: number): number {
  if (!total) return 0;
  return Math.min(100, Math.round((value / total) * 100));
}

function uniqueKeywords(items: ContentItem[]): string[] {
  return uniqueStrings(items.map(item => item.keyword).filter(keyword => keyword && keyword !== "未标注关键词"));
}

function matrixContentPlanSummary(project: Project, data: DerivedData) {
  const matrixOutput = project.steps.matrix.output || {};
  const source = readString(matrixOutput, ["matrix_generation_source", "import_source"], "") === "imported_content_plan_pdf"
    || readString(matrixOutput, ["import_source"], "") === "content_plan_pdf"
    ? "imported"
    : "generated";
  return {
    keywordCount: projectAllowedKeywords(project).length || contentPlanKeywordCount(data.matrixPlans, data.matrixIntentGroups),
    planCount: data.matrixPlans.length,
    articleTypeCount: orderedArticleTypes(data.matrixPlans).length,
    evidenceGapCount: contentPlanSectionCount(matrixOutput.evidence_gaps),
    hasSchedule: contentPlanSectionCount(matrixOutput.schedule) > 0,
    source,
    importedFilename: readString(matrixOutput, ["imported_filename"], ""),
    boundMaterialCount: readNumber(matrixOutput, ["bound_material_count"], 0)
  };
}

function demandMatrixContentPlanSummary(project: Project, data: DerivedData) {
  const output = project.steps.demand_matrix?.output || {};
  return {
    keywordCount: projectAllowedKeywords(project).length || contentPlanKeywordCount(data.demandMatrixPlans, data.demandMatrixIntentGroups),
    planCount: data.demandMatrixPlans.length,
    articleTypeCount: orderedArticleTypes(data.demandMatrixPlans).length,
    demandVariableCount: contentPlanSectionCount(output.demand_variables),
    themeClusterCount: contentPlanSectionCount(output.content_theme_clusters),
    evidenceGapCount: contentPlanSectionCount(output.evidence_gaps),
    hasSchedule: contentPlanSectionCount(output.weekly_publishing_mix) > 0 || contentPlanSectionCount(output.monthly_publishing_mix) > 0
  };
}

function contentPlanKeywordCount(items: ContentItem[], intentGroups: MatrixIntentGroup[]): number {
  return uniqueStrings([
    ...items.map(item => item.keyword),
    ...intentGroups.flatMap(group => group.keywords)
  ]).filter(keyword => keyword && keyword !== "未标注关键词").length;
}

function matrixImportPrerequisitesReady(project: Project): boolean {
  const materialStatus = project.steps.materials?.status;
  const intakeStatus = project.steps.intake?.status;
  const readyStatuses = new Set(["completed", "confirmed"]);
  return readyStatuses.has(materialStatus) && readyStatuses.has(intakeStatus);
}

function demandMatrixPrerequisitesReady(project: Project): boolean {
  const readyStatuses = new Set(["completed", "confirmed"]);
  return readyStatuses.has(project.steps.materials?.status)
    && readyStatuses.has(project.steps.intake?.status)
    && project.materials.some(material => material.filename.startsWith("demand_report__") && material.status === "parsed");
}

function demandMatrixPrerequisiteMessage(project: Project): string {
  const readyStatuses = new Set(["completed", "confirmed"]);
  if (!readyStatuses.has(project.steps.materials?.status)) return "请先上传并解析资料。";
  if (!readyStatuses.has(project.steps.intake?.status)) return "请先生成项目信息抽取表。";
  const hasReport = project.materials.some(material => material.filename.startsWith("demand_report__"));
  if (!hasReport) return "请先在“用户需求挖掘报告”入口上传报告并解析。";
  return "用户需求挖掘报告尚未解析完成，请先解析资料。";
}

function contentPlanSectionCount(value: unknown): number {
  if (Array.isArray(value)) return value.filter(item => contentPlanValue(item)).length;
  return contentPlanValue(value) ? 1 : 0;
}

function contentPlanValue(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(contentPlanValue).filter(Boolean).join("、");
  if (isRecord(value)) {
    return Object.entries(value)
      .filter(([key]) => key !== "raw")
      .map(([key, item]) => {
        const text = contentPlanValue(item);
        return text ? `${key}：${text}` : "";
      })
      .filter(Boolean)
      .join("；");
  }
  return "";
}

function readConfirmedBreakthroughKeywords(matrixOutput: AnyRecord): string[] {
  const selection = matrixOutput.breakthrough_keyword_selection;
  if (!isRecord(selection) || !Array.isArray(selection.keywords)) return [];
  return uniqueStrings(selection.keywords);
}

function uniqueStrings(values: unknown[]): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  values.forEach(value => {
    if (typeof value !== "string") return;
    const normalized = value.trim().replace(/\s+/g, " ");
    if (!normalized || seen.has(normalized)) return;
    result.push(normalized);
    seen.add(normalized);
  });
  return result;
}

function markdownH1Title(markdown: string): string {
  for (const line of markdown.split(/\r?\n/)) {
    const value = line.trim();
    if (value.startsWith("# ") && !value.startsWith("## ")) return value.slice(2).trim();
  }
  return "";
}

function fileNameTitle(filename: string): string {
  return filename.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").trim() || filename;
}

function mergeImportDrafts(current: MarkdownImportDraft[], nextRows: MarkdownImportDraft[]): MarkdownImportDraft[] {
  const byId = new Map(current.map(row => [row.id, row]));
  nextRows.forEach(row => byId.set(row.id, row));
  return Array.from(byId.values());
}

function normalizeIntake(output: AnyRecord): DerivedData["intakeRows"] {
  const rows = extractIntakeArray(output);
  return rows.map((row, index) => ({
    id: readString(row, ["id", "字段", "field"], `field-${index}`),
    field: readString(row, ["field", "字段", "name"], `字段 ${index + 1}`),
    value: readString(row, ["value", "推断值", "inferred_value", "answer"], JSON.stringify(row)),
    source: readString(row, ["source", "source_or_basis", "来源/依据", "依据", "basis"], "未标注"),
    confidence: readString(row, ["confidence", "置信度"], "未标注"),
    status: readString(row, ["status", "状态"], "待确认")
  }));
}

function extractIntakeArray(output: AnyRecord): AnyRecord[] {
  for (const key of ["project_intake_table", "intake_table", "items", "rows", "fields", "data"]) {
    const value = output[key];
    if (Array.isArray(value)) return value.filter(isRecord);
    if (isRecord(value)) {
      const nested = extractIntakeArray(value);
      if (nested.length) return nested;
    }
  }
  return extractArray(output);
}

function normalizeItems(output: AnyRecord, step: string): ContentItem[] {
  if (step === "breakthrough") {
    const canonicalRows = canonicalOutputItems(output);
    if (!canonicalRows.length) {
      const breakthroughRows = normalizeBreakthroughItems(output);
      if (breakthroughRows.length) return breakthroughRows;
    }
  }

  const rows = step === "matrix" ? extractMatrixArray(output) : extractArray(output);
  const overrides = itemOverrides(output);
  if (!rows.length && typeof output.markdown === "string") {
    rows.push(output);
  }
  return rows.map((row, index) => {
    const legacyBrief = step === "brief" ? extractLegacyBriefFields(row) : {};
    const rawKeyword = readString(row, ["keyword", "target_keyword", "main_keyword_or_cluster", "main_keyword", "keyword_or_cluster", "目标关键词", "主攻关键词", "关键词", "主攻关键词_意图簇"], legacyBrief.keyword || "未标注关键词");
    const keyword = rawKeyword.includes(" / ") ? rawKeyword.split(" / ")[0].trim() : rawKeyword;
    const type = readString(row, ["type", "article_type", "main_article_type", "文章类型", "类型"], legacyBrief.type || stepLabel(step));
    const title = readString(row, ["title", "suggested_title", "article_title", "建议标题", "文章标题", "标题"], legacyBrief.title || readString(output, ["title"], stepLabel(step)));
    const sourceStep = readString(row, ["source_step", "sourceStep"], step);
    const fallbackSourceId = stableContentId(sourceStep, keyword, type, title, index);
    const rawSourceId = readString(row, ["source_id", "sourceId"], fallbackSourceId);
    const sourceId = step === "matrix" ? fallbackSourceId : rawSourceId;
    const briefId = readString(row, ["brief_id", "briefId"], step === "article" ? readString(row, ["id"], "") : "");
    const fallbackId = step === "brief" ? `brief-${sourceId}` : step === "article" && briefId ? `article-${briefId}` : sourceId;
    const itemId = step === "matrix" ? sourceId : readString(row, ["id"], fallbackId);
    const roleKeys = step === "brief"
      ? ["role", "summary", "main_role", "brief_focus", "core_recommendation_conclusion", "主要作用", "description"]
      : ["role", "summary", "main_role", "brief_focus", "core_recommendation", "core_recommendation_conclusion", "主要作用", "后续Brief要点", "brief", "description"];
    const item = {
      id: itemId,
      sourceId,
      sourceStep,
      briefId,
      keyword,
      type,
      title,
      role: readString(row, roleKeys, legacyBrief.role || readString(output, ["summary"], "后台 Agent 已生成结果。")),
      channel: readString(row, ["channel", "channels", "recommendation_channel", "recommended_channels", "发布渠道", "推荐渠道"], legacyBrief.channel || "未标注渠道"),
      status: readString(row, ["status", "状态"], "completed"),
      used: readString(row, ["used", "使用状态"], "未使用"),
      markdown: readString(row, ["markdown", "body", "正文"], legacyBrief.markdown || readString(output, ["markdown"], "")),
      reviewNotes: readString(row, ["review_notes", "reviewNotes", "修改意见"], ""),
      articleAuditStatus: readString(row, ["article_audit_status", "articleAuditStatus"], ""),
      articleAuditedAt: readString(row, ["article_audited_at", "articleAuditedAt"], ""),
      error: readString(row, ["error", "错误"], ""),
      revision: readNumber(row, ["revision"], 1),
      modifiedAt: readString(row, ["modified_at", "modifiedAt"], ""),
      briefRevision: readNumber(row, ["brief_revision", "briefRevision"], 1),
      staleReason: readString(row, ["stale_reason", "staleReason"], ""),
      raw: isRecord(row.raw_generation) ? row.raw_generation : row
    };
    return applyItemOverride(item, overrides);
  });
}

function sortBriefsNewestFirst(items: ContentItem[]): ContentItem[] {
  return sortReviewItemsNewestFirst(items);
}

function sortArticlesNewestFirst(items: ContentItem[]): ContentItem[] {
  return sortReviewItemsNewestFirst(items);
}

function sortReviewItemsNewestFirst(items: ContentItem[]): ContentItem[] {
  return items
    .map((item, index) => ({
      item,
      index,
      runningRank: reviewItemRunningRank(item),
      generatedAt: itemGeneratedAtMs(item)
    }))
    .sort((left, right) =>
      right.runningRank - left.runningRank
      || right.generatedAt - left.generatedAt
      || right.index - left.index
    )
    .map(entry => entry.item);
}

function reviewItemRunningRank(item: ContentItem): number {
  return ["queued", "running", "cancelling", "pending"].includes(item.status) ? 1 : 0;
}

function itemGeneratedAtMs(item: ContentItem): number {
  return timestampMs(itemGeneratedAtValue(item));
}

function itemGeneratedTimestampLabel(item: ContentItem): string {
  return timestampLabel(itemGeneratedAtValue(item));
}

function itemGeneratedAtValue(item: ContentItem): string {
  return readString(item.raw, ["generated_at", "generatedAt", "created_at", "createdAt", "updated_at", "updatedAt"], "");
}

function timestampLabel(rawValue?: string): string {
  if (!rawValue) return "";
  const parsed = Date.parse(rawValue);
  if (!Number.isFinite(parsed)) return rawValue;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(parsed));
}

function filterBriefItems(
  items: ContentItem[],
  articleByBriefId: Map<string, ContentItem>,
  filters: BriefFilterState
): ContentItem[] {
  return items.filter(item => {
    if (filters.keyword !== "all" && item.keyword !== filters.keyword) return false;
    if (filters.articleType !== "all" && item.type !== filters.articleType) return false;
    if (filters.briefModified !== "all") {
      const modified = briefWasModified(item);
      if (filters.briefModified === "modified" && !modified) return false;
      if (filters.briefModified === "unmodified" && modified) return false;
    }
    if (filters.articleStatus !== "all" && briefArticleFilterStatus(articleByBriefId.get(item.id), item) !== filters.articleStatus) {
      return false;
    }
    return true;
  });
}

function filterArticleItems(
  items: ContentItem[],
  briefById: Map<string, ContentItem>,
  filters: BriefFilterState
): ContentItem[] {
  return items.filter(item => {
    const brief = briefById.get(item.briefId || "");
    if (filters.keyword !== "all" && item.keyword !== filters.keyword) return false;
    if (filters.articleType !== "all" && item.type !== filters.articleType) return false;
    if (filters.briefModified !== "all") {
      const modified = brief ? briefWasModified(brief) : false;
      if (filters.briefModified === "modified" && !modified) return false;
      if (filters.briefModified === "unmodified" && modified) return false;
    }
    if (!articleMatchesFilterStatus(item, brief, filters.articleStatus)) {
      return false;
    }
    return true;
  });
}

function briefWasModified(brief: ContentItem): boolean {
  return ["modified", "stale"].includes(brief.status);
}

function briefArticleFilterStatus(article: ContentItem | undefined, brief: ContentItem): Exclude<BriefArticleFilter, "all"> {
  if (!article) return "not_generated";
  return articleCurrentForBrief(article, brief) ? "generated" : "needs_update";
}

function articleMatchesFilterStatus(article: ContentItem, brief: ContentItem | undefined, filter: BriefArticleFilter): boolean {
  if (filter === "all") return true;
  const status = articleFilterStatus(article, brief);
  if (filter === "generated") return status === "pending_review" || status === "approved";
  if (filter === "pending_review") return status === "pending_review" || status === "needs_update" || status === "failed";
  if (filter === "not_generated") return false;
  return status === filter;
}

function articleFilterStatus(article: ContentItem, brief?: ContentItem): Exclude<BriefArticleFilter, "all" | "not_generated" | "generated"> {
  if (article.status === "failed") return "failed";
  if (brief && !articleCurrentForBrief(article, brief)) return "needs_update";
  if (["running", "queued", "pending", "stale", "modified"].includes(article.status)) return "needs_update";
  if (article.markdown || ["completed", "confirmed"].includes(article.status)) {
    return articleAuditApproved(article) ? "approved" : "pending_review";
  }
  return "needs_update";
}

function normalizeMatrixIntentGroups(output: AnyRecord, items: ContentItem[]): MatrixIntentGroup[] {
  const rows = extractArrayByKeys(output, ["intent_groups", "keyword_intent_groups", "关键词意图分组", "二_关键词意图分组"]);
  const groups = rows.map((row, index) => {
    const name = readString(row, ["intent_group", "name", "group", "意图簇", "关键词意图簇"], `意图簇 ${index + 1}`);
    return {
      id: stableContentId("intent", name, "", "", index),
      name,
      keywords: readStringList(row, ["keywords", "corresponding_keywords", "对应关键词", "关键词"]),
      userQuestion: readString(row, ["user_real_question", "ai_question", "用户真实问题", "AI需要回答的问题"]),
      userStage: readString(row, ["user_stage", "用户阶段"]),
      articleTypes: readStringList(row, ["main_article_types", "article_types", "主攻文章类型", "常见主攻文章类型"]),
      raw: row
    };
  }).filter(group => group.name && group.name !== "未分组");
  if (groups.length) return groups;

  return Object.entries(groupMatrixRowsByIntent(items, [])).map(([name, groupItems], index) => ({
    id: stableContentId("intent", name, "", "", index),
    name,
    keywords: uniqueKeywords(groupItems),
    userQuestion: "",
    userStage: "",
    articleTypes: uniqueStrings(groupItems.map(item => item.type)),
    raw: {}
  }));
}

function groupMatrixRowsByIntent(rows: ContentItem[], intentGroups: MatrixIntentGroup[]): Record<string, ContentItem[]> {
  const grouped = rows.reduce<Record<string, ContentItem[]>>((acc, row) => {
    const rawGroup = readString(row.raw, ["intent_group", "intentGroup", "intent_cluster", "main_intent_group", "意图簇", "关键词意图簇"], "");
    const groupName = rawGroup || intentGroupForKeyword(row.keyword, intentGroups) || "未识别意图簇";
    acc[groupName] ||= [];
    acc[groupName].push(row);
    return acc;
  }, {});
  const ordered: Record<string, ContentItem[]> = {};
  intentGroups.forEach(group => {
    if (grouped[group.name]) ordered[group.name] = grouped[group.name];
  });
  Object.entries(grouped).forEach(([groupName, groupRows]) => {
    if (!ordered[groupName]) ordered[groupName] = groupRows;
  });
  return ordered;
}

function intentGroupForKeyword(keyword: string, groups: MatrixIntentGroup[]): string {
  const normalized = keyword.trim();
  if (!normalized) return "";
  return groups.find(group => group.keywords.includes(normalized))?.name || "";
}

function matrixIntentSubtitle(group: MatrixIntentGroup): string {
  const parts = [
    group.userQuestion,
    group.keywords.length ? `关键词：${group.keywords.join("、")}` : "",
    group.userStage ? `用户阶段：${group.userStage}` : ""
  ].filter(Boolean);
  return parts.join(" · ");
}

function matrixFallbackGroupSubtitle(rows: ContentItem[]): string {
  const keywords = uniqueKeywords(rows);
  return keywords.length ? `关键词：${keywords.join("、")}` : "";
}

function extractMatrixArray(output: AnyRecord): AnyRecord[] {
  const canonicalRows = canonicalOutputItems(output);
  if (canonicalRows.length) return canonicalRows;

  const articleRows = extractArrayByKeys(output, [
    "first_round_article_list",
    "first_round_articles",
    "article_list",
    "matrix_articles",
    "六_首轮文章清单",
    "首轮文章清单",
    "articles",
    "plans",
    "rows"
  ]);
  if (articleRows.length) return articleRows;

  const keywordRows = extractArrayByKeys(output, [
    "keyword_individual_planning",
    "keyword_planning",
    "keyword_plans",
    "五_关键词逐个规划",
    "关键词逐个规划",
    "十二_优先级排序"
  ]);
  if (keywordRows.length) return keywordRows;

  return extractArray(output);
}

function extractMatrixKeywordOptions(output: AnyRecord): string[] {
  const canonicalRows = canonicalOutputItems(output);
  if (canonicalRows.length) {
    return uniqueStrings(canonicalRows.map(row => readString(row, ["keyword", "target_keyword", "目标关键词", "主攻关键词", "关键词", "main_keyword"])));
  }

  const rows = extractArrayByKeys(output, [
    "keyword_individual_planning",
    "keyword_planning",
    "keyword_plans",
    "五_关键词逐个规划",
    "关键词逐个规划",
    "priority_ranking",
    "十二_优先级排序"
  ]);
  return uniqueStrings(rows.map(row => readString(row, ["keyword", "target_keyword", "目标关键词", "主攻关键词", "关键词", "main_keyword"])));
}

function canonicalOutputItems(output: AnyRecord): AnyRecord[] {
  return Array.isArray(output.items) ? output.items.filter(isRecord) : [];
}

function normalizeBreakthroughItems(output: AnyRecord): ContentItem[] {
  const plans = output.plans;
  if (!Array.isArray(plans)) return [];
  const overrides = itemOverrides(output);

  return plans.filter(isRecord).flatMap((plan, planIndex) => {
    const keyword = readString(plan, ["keyword", "关键词", "target_keyword", "目标关键词"], `关键词 ${planIndex + 1}`);
    const articles = plan.articles;

    if (!Array.isArray(articles) || !articles.length) {
      const type = readString(plan, ["type", "article_type", "文章类型"], stepLabel("breakthrough"));
      const title = readString(plan, ["title", "suggested_title", "建议标题", "文章标题"], keyword);
      const sourceId = stableContentId("breakthrough", keyword, type, title, planIndex);
      const item = {
        id: readString(plan, ["id"], sourceId),
        sourceId,
        sourceStep: "breakthrough",
        briefId: "",
        keyword,
        type,
        title,
        role: readString(plan, ["role", "summary", "主要作用", "主攻意图", "重点强化方向", "brief", "description"], "后台 Agent 已生成结果。"),
        channel: readString(plan, ["channel", "recommendation_channel", "发布渠道"], "未标注渠道"),
        status: readString(plan, ["status", "状态"], output.status ? String(output.status) : "completed"),
        used: readString(plan, ["used", "使用状态"], "未使用"),
        markdown: readString(plan, ["markdown", "body", "正文"], ""),
        reviewNotes: readString(plan, ["review_notes", "reviewNotes", "修改意见"], ""),
        articleAuditStatus: readString(plan, ["article_audit_status", "articleAuditStatus"], ""),
        articleAuditedAt: readString(plan, ["article_audited_at", "articleAuditedAt"], ""),
        error: readString(plan, ["error", "错误"], ""),
        revision: readNumber(plan, ["revision"], 1),
        modifiedAt: readString(plan, ["modified_at", "modifiedAt"], ""),
        briefRevision: readNumber(plan, ["brief_revision", "briefRevision"], 1),
        staleReason: readString(plan, ["stale_reason", "staleReason"], ""),
        raw: plan
      };
      return [applyItemOverride(item, overrides)];
    }

    return articles.filter(isRecord).map((article, articleIndex) => {
      const type = readString(article, ["type", "article_type", "main_article_type", "文章类型"], "文章规划");
      const title = readString(article, ["title", "suggested_title", "建议标题", "文章标题"], `第 ${articleIndex + 1} 篇文章`);
      const sourceId = stableContentId("breakthrough", keyword, type, title, `${planIndex}-${articleIndex}`);
      const item = {
        id: readString(article, ["id"], sourceId),
        sourceId,
        sourceStep: "breakthrough",
        briefId: "",
        keyword,
        type,
        title,
        role: readString(article, ["role", "summary", "main_role", "core_recommendation_conclusion", "主要作用", "后续Brief要点", "brief", "description"], "后台 Agent 已生成结果。"),
        channel: readString(article, ["channel", "recommendation_channel", "发布渠道"], "未标注渠道"),
        status: readString(article, ["status", "状态"], output.status ? String(output.status) : "completed"),
        used: readString(article, ["used", "使用状态"], "未使用"),
        markdown: readString(article, ["markdown", "body", "正文"], ""),
        reviewNotes: readString(article, ["review_notes", "reviewNotes", "修改意见"], ""),
        articleAuditStatus: readString(article, ["article_audit_status", "articleAuditStatus"], ""),
        articleAuditedAt: readString(article, ["article_audited_at", "articleAuditedAt"], ""),
        error: readString(article, ["error", "错误"], ""),
        revision: readNumber(article, ["revision"], 1),
        modifiedAt: readString(article, ["modified_at", "modifiedAt"], ""),
        briefRevision: readNumber(article, ["brief_revision", "briefRevision"], 1),
        staleReason: readString(article, ["stale_reason", "staleReason"], ""),
        raw: { ...article, keyword }
      };
      return applyItemOverride(item, overrides);
    });
  });
}

function extractArray(output: AnyRecord): AnyRecord[] {
  for (const key of ["items", "rows", "fields", "project_intake_table", "intake_table", "plan", "keyword_planning", "first_round_articles", "plans", "articles", "briefs", "data"]) {
    const value = output[key];
    if (Array.isArray(value)) return value.filter(isRecord);
    if (isRecord(value)) {
      const nested = extractArray(value);
      if (nested.length) return nested;
    }
  }
  return [];
}

function extractArrayByKeys(output: AnyRecord, keys: string[]): AnyRecord[] {
  for (const key of keys) {
    const value = output[key];
    if (Array.isArray(value)) return value.filter(isRecord);
    if (isRecord(value)) {
      const nested = extractArrayByKeys(value, keys);
      if (nested.length) return nested;
    }
  }

  for (const value of Object.values(output)) {
    if (!isRecord(value)) continue;
    const nested = extractArrayByKeys(value, keys);
    if (nested.length) return nested;
  }
  return [];
}

function itemOverrides(output: AnyRecord): Record<string, AnyRecord> {
  const value = output.item_overrides;
  if (!isRecord(value)) return {};
  return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, AnyRecord] => isRecord(entry[1])));
}

function extractLegacyBriefFields(row: AnyRecord): Partial<Pick<ContentItem, "keyword" | "type" | "title" | "role" | "channel" | "markdown">> {
  const brief = row.brief;
  if (!isRecord(brief)) return {};

  const keywordBlock = readRecord(brief, "1_目标关键词");
  const typeBlock = readRecord(brief, "2_文章类型");
  const titleBlock = readRecord(brief, "3_建议标题");
  const channelBlock = readRecord(brief, "4_发布渠道");
  const roleBlock = readRecord(brief, "5_主要作用");

  const channels = channelNames(channelBlock["推荐渠道"]);
  const role = readString(roleBlock, ["承接用户问题", "建立判断标准", "强化推荐心智"], "后台 Agent 已生成完整 Brief，请点击“查阅/编辑”查看。");
  return {
    keyword: readString(keywordBlock, ["核心关键词", "目标关键词"]),
    type: readString(typeBlock, ["类型", "文章类型"]),
    title: readString(titleBlock, ["标题", "建议标题"]),
    role: clampText(role, 120),
    channel: channels || readString(channelBlock, ["渠道", "推荐渠道"]),
    markdown: readString(row, ["markdown"], "")
  };
}

function readRecord(row: AnyRecord, key: string): AnyRecord {
  const value = row[key];
  return isRecord(value) ? value : {};
}

function channelNames(value: unknown): string {
  if (!Array.isArray(value)) return "";
  return value
    .filter(isRecord)
    .map(item => readString(item, ["渠道", "channel"]))
    .filter(Boolean)
    .join("、");
}

function applyItemOverride(item: ContentItem, overrides: Record<string, AnyRecord>): ContentItem {
  const override = overrides[item.sourceId] || overrides[item.id] || (item.briefId ? overrides[item.briefId] : undefined);
  if (!override) return item;
  return {
    ...item,
    title: readString(override, ["title"], item.title),
    role: readString(override, ["role"], item.role),
    channel: readString(override, ["channel"], item.channel),
    status: readString(override, ["status"], item.status),
    used: readString(override, ["used"], item.used),
    markdown: readString(override, ["markdown"], item.markdown || ""),
    reviewNotes: readString(override, ["review_notes", "reviewNotes"], item.reviewNotes || ""),
    articleAuditStatus: readString(override, ["article_audit_status", "articleAuditStatus"], item.articleAuditStatus || ""),
    articleAuditedAt: readString(override, ["article_audited_at", "articleAuditedAt"], item.articleAuditedAt || ""),
    error: readString(override, ["error"], item.error || ""),
    revision: readNumber(override, ["revision"], item.revision),
    modifiedAt: readString(override, ["modified_at", "modifiedAt"], item.modifiedAt || ""),
    briefRevision: readNumber(override, ["brief_revision", "briefRevision"], item.briefRevision),
    staleReason: readString(override, ["stale_reason", "staleReason"], item.staleReason || ""),
    raw: { ...item.raw, override }
  };
}

function clampText(value: string, maxLength: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength)}...`;
}

function readString(row: AnyRecord, keys: string[], fallback = ""): string {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number") return String(value);
    if (Array.isArray(value) && value.length) return value.map(formatValue).join("、");
    if (isRecord(value)) return Object.entries(value).map(([name, item]) => `${name}: ${formatValue(item)}`).join("；");
  }
  return fallback;
}

function readStringList(row: AnyRecord, keys: string[]): string[] {
  for (const key of keys) {
    const value = row[key];
    if (Array.isArray(value)) return uniqueStrings(value.map(formatValue));
    if (typeof value === "string" && value.trim()) {
      const parts = value.split(/[、，,;；\n]/).map(item => item.trim());
      const normalized = uniqueStrings(parts);
      if (normalized.length) return normalized;
    }
  }
  return [];
}

function readNumber(row: AnyRecord, keys: string[], fallback = 0): number {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  }
  return fallback;
}

function formatValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(formatValue).join("、");
  if (isRecord(value)) return Object.entries(value).map(([name, item]) => `${name}: ${formatValue(item)}`).join("、");
  return String(value ?? "");
}

function isRecord(value: unknown): value is AnyRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stepLabel(step: string): string {
  const labels: Record<string, string> = {
    materials: "资料解析",
    intake: "抽取表",
    matrix: "内容矩阵",
    demand_matrix: "需求驱动矩阵",
    breakthrough: "逐词击破",
    custom: "自定义文章",
    brief: "Brief",
    article: "正文"
  };
  return labels[step] || step;
}

function progressTitle(step: WorkflowStep, active: boolean): string {
  if (step === "materials") return active ? "正在解析资料" : "资料解析";
  if (step === "intake") return active ? "正在生成抽取表" : "抽取表生成";
  return active ? `正在运行${stepLabel(step)}` : stepLabel(step);
}

function progressSubtitle(job?: Project["jobs"][number]): string {
  if (!job) return "等待后台状态更新";
  if (job.status === "cancelled") return job.message || "任务已停止。";
  if (job.status === "cancelling") return job.message || "正在停止任务。";
  if (job.status === "failed") return friendlyErrorText(job.error || "任务失败，可重试。");
  if (job.current_item) return `当前：${job.current_item}`;
  if (job.message) return job.message;
  return `${progressTitle(job.step, job.status === "running")}：${statusLabel(job.status)}`;
}

function friendlyErrorText(value?: string | null): string {
  const text = String(value || "").trim();
  if (!text) return "";
  const lowered = text.toLowerCase();
  if (
    lowered.includes("error code: 524") ||
    lowered.includes("status code: 524") ||
    lowered.includes('"code":524') ||
    lowered.includes("origin_response_timeout") ||
    lowered.includes("proxy read timeout") ||
    lowered.includes("a timeout occurred") ||
    lowered.includes("origin web server did not return a complete response")
  ) {
    return "中转站超时：模型 120 秒内未返回。系统已自动重试一次，仍未完成。请稍后重试或减少资料/关键词规模。";
  }
  if (lowered.includes("user_balance_insufficient") || text.includes("余额不足") || (lowered.includes("insufficient") && lowered.includes("balance"))) {
    return "中转站余额不足：请充值后重试，或切换到可用的模型/API Key。";
  }
  if (lowered.includes("cloudflare") || lowered.includes("origin web server")) {
    return "中转站请求失败：上游网关没有返回完整结果，请稍后重试。";
  }
  return text;
}

function outputBlockerMessage(output: AnyRecord): string {
  const status = readString(output, ["status"], "").toLowerCase();
  const blocked = status.includes("blocked") || status.includes("need_") || status.includes("缺失");
  if (!blocked) return "";
  const message = readString(output, ["reason", "next_action_required", "message", "error"], "");
  if (message) return message;
  const missing = output.missing_required_input;
  if (isRecord(missing)) {
    const fields = Object.keys(missing);
    if (fields.length) return `需要补充或确认：${fields.join("、")}`;
  }
  return "Agent 返回了需要补充输入的结果，请补充资料或确认关键词后重试。";
}

function groupBy<T>(rows: T[], key: keyof T): Record<string, T[]> {
  return rows.reduce<Record<string, T[]>>((acc, row) => {
    const value = String(row[key] || "未分组");
    acc[value] ||= [];
    acc[value].push(row);
    return acc;
  }, {});
}

function latestJob(project: Project, step: WorkflowStep): Project["jobs"][number] | undefined {
  return project.jobs
    .filter(job => job.step === step)
    .sort((left, right) => timestampMs(right.updated_at || right.created_at) - timestampMs(left.updated_at || left.created_at))[0];
}

function briefProgressForPlanning(project: Project, activeStep: WorkflowStep | null): Project["jobs"][number] | undefined {
  const briefJob = latestJob(project, "brief");
  if (!briefJob) return undefined;
  if (briefJob.status === "queued" || briefJob.status === "running" || briefJob.status === "cancelling") return briefJob;
  if (!activeStep) return briefJob;

  const activeJob = latestJob(project, activeStep);
  const planningUpdatedAt = Math.max(
    timestampMs(project.steps[activeStep].updated_at),
    activeJob ? timestampMs(activeJob.updated_at || activeJob.created_at) : 0
  );
  const briefUpdatedAt = timestampMs(briefJob.updated_at || briefJob.created_at);
  return briefUpdatedAt >= planningUpdatedAt ? briefJob : undefined;
}

function timestampMs(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function articleCurrentForBrief(article: ContentItem, brief: ContentItem): boolean {
  return article.briefId === brief.id
    && !["failed", "stale", "running"].includes(article.status)
    && article.briefRevision === brief.revision;
}

function articleStatusForBrief(article: ContentItem | undefined, brief: ContentItem): string {
  if (!article) {
    return briefIsGenerated(brief) ? "正文待生成" : "";
  }
  if (["modified", "stale"].includes(brief.status)) {
    return articleCurrentForBrief(article, brief) ? "正文已更新" : "正文需更新";
  }
  if (articleCurrentForBrief(article, brief)) return "正文已生成";
  if (article.status === "stale" || article.briefRevision < brief.revision) return "正文需更新";
  return `正文${statusLabel(article.status)}`;
}

function briefReviewCardClass(brief: ContentItem, article: ContentItem | undefined): string {
  if (brief.status === "failed") return "review-danger";
  if (["running", "queued", "pending"].includes(brief.status)) return "review-running";
  if (!article) return briefIsGenerated(brief) ? "review-warn" : "";
  if (article.status === "failed") return "review-danger";
  if (!articleCurrentForBrief(article, brief)) return "review-warn";
  return "review-good";
}

function planReviewCardClass(brief: ContentItem | undefined, _article: ContentItem | undefined): string {
  if (!brief) return "review-warn";
  if (brief.status === "failed") return "review-danger";
  if (["running", "queued", "pending"].includes(brief.status)) return "review-running";
  if (["modified", "stale"].includes(brief.status)) return "review-warn";
  return briefIsGenerated(brief) ? "review-good" : "review-warn";
}

function articleForPlanItem(
  item: ContentItem,
  briefBySource: Map<string, ContentItem>,
  articleByBriefId: Map<string, ContentItem>
): ContentItem | undefined {
  const brief = briefBySource.get(item.sourceId);
  return brief ? articleByBriefId.get(brief.id) : undefined;
}

function articleReviewCardClass(article: ContentItem, brief?: ContentItem): string {
  if (article.status === "failed") return "review-danger";
  if (["running", "queued", "pending", "stale", "modified"].includes(article.status)) return "review-warn";
  if (brief && !articleCurrentForBrief(article, brief)) return "review-warn";
  if (article.markdown || ["completed", "confirmed"].includes(article.status)) {
    return articleAuditApproved(article) ? "review-good" : "review-warn";
  }
  return "";
}

function briefItemStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: "Brief待处理",
    queued: "Brief排队中",
    running: "Brief生成中",
    completed: "Brief已生成",
    confirmed: "Brief已确认",
    modified: "Brief已修改",
    stale: "Brief需更新",
    failed: "Brief失败"
  };
  return labels[status] || `Brief${statusLabel(status)}`;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: "待生成 Brief",
    pending: "待处理",
    queued: "排队中",
    running: "生成中",
    cancelling: "停止中",
    cancelled: "已停止",
    completed: "已生成",
    confirmed: "已确认",
    modified: "已修改待生成正文",
    stale: "基于旧 Brief",
    failed: "失败",
    partial_failed: "部分失败",
    partial_stale: "部分正文需更新",
    generated_with_assumptions: "已生成（含假设）"
  };
  return labels[status] || status;
}

function intakeRowPersisted(row: IntakeRow): boolean {
  return row.status === "已确认" || row.status === "已人工修改";
}

function toggleSet(current: Set<string>, id: string): Set<string> {
  const next = new Set(current);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

function customSourceRawFor(mode: "create" | "edit" | "copy", item?: ContentItem): Record<string, unknown> | undefined {
  if (mode !== "copy" || !item) return undefined;
  return {
    copied_from: {
      source_id: item.sourceId,
      source_step: item.sourceStep,
      keyword: item.keyword,
      type: item.type,
      title: item.title,
      channel: item.channel,
      channels: itemChannels(item),
      brief_focus: readString(item.raw, ["brief_focus", "briefFocus"], item.role)
    }
  };
}

function itemChannels(item: ContentItem): string[] {
  const rawChannels = item.raw.channels;
  if (Array.isArray(rawChannels)) {
    return rawChannels.map(formatValue).filter(Boolean);
  }
  if (!item.channel || item.channel === "未标注渠道") return [];
  return item.channel.split("、").map(channel => channel.trim()).filter(Boolean);
}

function toSourcePayload(item: ContentItem): Record<string, unknown> {
  return {
    source_id: item.sourceId,
    source_step: item.sourceStep,
    keyword: item.keyword,
    type: item.type,
    title: item.title,
    role: item.role,
    channel: item.channel,
    channels: itemChannels(item),
    brief_focus: readString(item.raw, ["brief_focus", "briefFocus"], item.role),
    raw: item.raw
  };
}

function toBriefPayload(item: ContentItem): Record<string, unknown> {
  return {
    id: item.id,
    source_id: item.sourceId,
    keyword: item.keyword,
    type: item.type,
    title: item.title,
    markdown: item.markdown || "",
    revision: item.revision,
    modified_at: item.modifiedAt || "",
    review_notes: item.reviewNotes || "",
    raw: item.raw
  };
}

function downloadArticleMarkdown(items: ContentItem[]) {
  if (items.length === 1) {
    downloadBlob(
      new Blob([articleMarkdownBody(items[0])], { type: "text/markdown;charset=utf-8" }),
      `${slugValue(items[0].title, "article")}.md`
    );
    return;
  }
  const files = articleExportFiles(items);
  downloadBlob(createZipBlob(files), `selected-articles-${new Date().toISOString().slice(0, 10)}.zip`);
}

function articleExportFiles(items: ContentItem[]): Array<{ name: string; content: string }> {
  const used = new Set<string>();
  return items.map((item, index) => {
    const base = slugValue(item.title, `article-${index + 1}`);
    const uniqueBase = uniqueFileBase(base, used);
    return {
      name: `${String(index + 1).padStart(2, "0")}-${uniqueBase}.md`,
      content: articleMarkdownBody(item)
    };
  });
}

function uniqueFileBase(base: string, used: Set<string>): string {
  let candidate = base;
  let index = 2;
  while (used.has(candidate)) {
    candidate = `${base}-${index}`;
    index += 1;
  }
  used.add(candidate);
  return candidate;
}

function articleMarkdownBody(item: ContentItem): string {
  const markdown = (item.markdown || "").trim();
  if (markdown) return `${markdown}\n`;
  return [`# ${item.title}`, "", "```json", JSON.stringify(item.raw, null, 2), "```", ""].join("\n");
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function createZipBlob(files: Array<{ name: string; content: string }>): Blob {
  const encoder = new TextEncoder();
  const localParts: Uint8Array[] = [];
  const centralParts: Uint8Array[] = [];
  let offset = 0;
  files.forEach(file => {
    const nameBytes = encoder.encode(file.name);
    const data = encoder.encode(file.content);
    const crc = crc32(data);
    const localHeader = zipLocalHeader(nameBytes, data.length, crc);
    localParts.push(localHeader, nameBytes, data);
    centralParts.push(zipCentralHeader(nameBytes, data.length, crc, offset), nameBytes);
    offset += localHeader.length + nameBytes.length + data.length;
  });
  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);
  const end = zipEndRecord(files.length, centralSize, offset);
  return new Blob([...localParts, ...centralParts, end].map(zipBlobPart), { type: "application/zip" });
}

function zipBlobPart(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.length);
  copy.set(bytes);
  return copy.buffer;
}

function zipLocalHeader(nameBytes: Uint8Array, size: number, crc: number): Uint8Array {
  const header = new Uint8Array(30);
  writeZipUint32(header, 0, 0x04034b50);
  writeZipUint16(header, 4, 20);
  writeZipUint16(header, 6, 0x0800);
  writeZipUint16(header, 8, 0);
  writeZipUint16(header, 10, 0);
  writeZipUint16(header, 12, 0);
  writeZipUint32(header, 14, crc);
  writeZipUint32(header, 18, size);
  writeZipUint32(header, 22, size);
  writeZipUint16(header, 26, nameBytes.length);
  writeZipUint16(header, 28, 0);
  return header;
}

function zipCentralHeader(nameBytes: Uint8Array, size: number, crc: number, offset: number): Uint8Array {
  const header = new Uint8Array(46);
  writeZipUint32(header, 0, 0x02014b50);
  writeZipUint16(header, 4, 20);
  writeZipUint16(header, 6, 20);
  writeZipUint16(header, 8, 0x0800);
  writeZipUint16(header, 10, 0);
  writeZipUint16(header, 12, 0);
  writeZipUint16(header, 14, 0);
  writeZipUint32(header, 16, crc);
  writeZipUint32(header, 20, size);
  writeZipUint32(header, 24, size);
  writeZipUint16(header, 28, nameBytes.length);
  writeZipUint16(header, 30, 0);
  writeZipUint16(header, 32, 0);
  writeZipUint16(header, 34, 0);
  writeZipUint16(header, 36, 0);
  writeZipUint32(header, 38, 0);
  writeZipUint32(header, 42, offset);
  return header;
}

function zipEndRecord(fileCount: number, centralSize: number, centralOffset: number): Uint8Array {
  const end = new Uint8Array(22);
  writeZipUint32(end, 0, 0x06054b50);
  writeZipUint16(end, 4, 0);
  writeZipUint16(end, 6, 0);
  writeZipUint16(end, 8, fileCount);
  writeZipUint16(end, 10, fileCount);
  writeZipUint32(end, 12, centralSize);
  writeZipUint32(end, 16, centralOffset);
  writeZipUint16(end, 20, 0);
  return end;
}

function writeZipUint16(target: Uint8Array, offset: number, value: number) {
  target[offset] = value & 0xff;
  target[offset + 1] = (value >>> 8) & 0xff;
}

function writeZipUint32(target: Uint8Array, offset: number, value: number) {
  target[offset] = value & 0xff;
  target[offset + 1] = (value >>> 8) & 0xff;
  target[offset + 2] = (value >>> 16) & 0xff;
  target[offset + 3] = (value >>> 24) & 0xff;
}

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc = (crc >>> 8) ^ CRC32_TABLE[(crc ^ byte) & 0xff];
  }
  return (crc ^ 0xffffffff) >>> 0;
}

const CRC32_TABLE = Array.from({ length: 256 }, (_, index) => {
  let value = index;
  for (let bit = 0; bit < 8; bit += 1) {
    value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  }
  return value >>> 0;
});

function stableContentId(sourceStep: string, keyword: string, type: string, title: string, fallback: string | number): string {
  return slugValue([sourceStep, keyword, type, title].filter(Boolean).join("-"), `${sourceStep}-${fallback}`);
}

function slugValue(value: string, fallback: string): string {
  const normalized = value
    .trim()
    .replace(/[^\w\u4e00-\u9fff.-]+/gu, "-")
    .replace(/-+/g, "-")
    .replace(/^[-._]+|[-._]+$/g, "");
  return normalized.slice(0, 80) || fallback;
}

function renameFilesForSlot(files: FileList, slotId: string): FileList {
  const transfer = new DataTransfer();
  Array.from(files).forEach(file => {
    transfer.items.add(new File([file], `${slotId}__${file.name}`, { type: file.type, lastModified: file.lastModified }));
  });
  return transfer.files;
}

function stripSlotPrefix(filename: string): string {
  return filename.replace(/^[a-zA-Z0-9_-]+__/, "");
}

function resolveSlotStatus(materials: Project["materials"], required: boolean): string {
  if (!materials.length) return required ? "pending" : "optional";
  if (materials.some(material => material.status === "failed")) return "failed";
  if (materials.every(material => material.status === "parsed")) return "parsed";
  return "uploaded";
}

function describeSlotFiles(materials: Project["materials"]): string {
  const parsed = materials.filter(material => material.status === "parsed").length;
  const failed = materials.filter(material => material.status === "failed").length;
  const uploaded = materials.length - parsed - failed;
  const parts = [`${materials.length} 个文件`];
  if (parsed) parts.push(`${parsed} 个已解析`);
  if (uploaded) parts.push(`${uploaded} 个待解析`);
  if (failed) parts.push(`${failed} 个失败`);
  return parts.join("，");
}

function materialParseMeta(material: Project["materials"][number]): string {
  if (material.status === "failed") return material.error || "解析失败";
  if (material.status !== "parsed") return "待解析";
  const parts = [parseSourceLabel(material.parse_source), parseModeLabel(material.parse_mode)];
  if (material.ocr_pages) parts.push(`OCR ${material.ocr_pages} 页/图`);
  if (material.parsed_chars) parts.push(`${material.parsed_chars.toLocaleString("zh-CN")} 字符`);
  const parsedAt = timestampLabel(material.parsed_at || undefined);
  if (parsedAt) parts.push(parsedAt);
  return parts.filter(Boolean).join(" · ");
}

function parseSourceLabel(source?: Project["materials"][number]["parse_source"] | null): string {
  if (source === "cache") return "缓存命中";
  if (source === "skipped_existing") return "已解析跳过";
  if (source === "fresh") return "新解析";
  return "已解析";
}

function parseModeLabel(mode?: Project["materials"][number]["parse_mode"] | null): string {
  if (mode === "text_only") return "仅文本";
  if (mode === "full_ocr") return "完整OCR";
  if (mode === "smart") return "智能快速";
  return "";
}

createRoot(document.getElementById("root")!).render(<App />);
