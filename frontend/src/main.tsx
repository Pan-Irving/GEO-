import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Archive,
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
import type { CustomSourcePayload, Project, WorkflowStep } from "./api/types";
import "./styles/app.css";

type AppView = "dashboard" | "upload" | "planning" | "brief" | "article" | "rewrite" | "library";
type PlanningTab = "matrix" | "breakthrough" | "custom";
type EditableStep = "matrix" | "breakthrough" | "brief" | "article" | "rewrite";
type BriefModifiedFilter = "all" | "modified" | "unmodified";
type BriefArticleFilter = "all" | "generated" | "not_generated" | "needs_update" | "failed";

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
}

interface BriefFilterState {
  keyword: string;
  articleType: string;
  briefModified: BriefModifiedFilter;
  articleStatus: BriefArticleFilter;
}

const emptyBriefFilters: BriefFilterState = {
  keyword: "all",
  articleType: "all",
  briefModified: "all",
  articleStatus: "all"
};

const appSteps: Array<{ id: AppView; title: string; desc: string; backendStep?: WorkflowStep }> = [
  { id: "dashboard", title: "项目看板", desc: "整体产出与进度" },
  { id: "upload", title: "资料与信息", desc: "必填资料 + 信息确认", backendStep: "intake" },
  { id: "planning", title: "规划确认", desc: "整体规划与逐词击破", backendStep: "matrix" },
  { id: "brief", title: "Brief 审核", desc: "按关键词分组", backendStep: "brief" },
  { id: "article", title: "正文审核", desc: "折叠查阅与定稿", backendStep: "article" },
  { id: "rewrite", title: "改写管理", desc: "改写稿确认与发布", backendStep: "rewrite" },
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
  { id: "other", name: "其他补充资料", required: false, desc: "访谈纪要、平台截图、历史文章、会议记录等可选补充。" }
];

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [project, setProject] = useState<Project | null>(null);
  const [current, setCurrent] = useState<AppView>("dashboard");
  const [planningTab, setPlanningTab] = useState<PlanningTab>("matrix");
  const [libraryGroup, setLibraryGroup] = useState<"keyword" | "type">("keyword");
  const [rewriteGroup, setRewriteGroup] = useState<"keyword" | "type">("keyword");
  const [selectedPlans, setSelectedPlans] = useState<Set<string>>(new Set());
  const [selectedBriefs, setSelectedBriefs] = useState<Set<string>>(new Set());
  const [selectedArticles, setSelectedArticles] = useState<Set<string>>(new Set());
  const [dismissedJobIds, setDismissedJobIds] = useState<Set<string>>(new Set());
  const [detail, setDetail] = useState<DetailState | null>(null);
  const [projectName, setProjectName] = useState("GEO 内容项目");
  const [logs, setLogs] = useState("");
  const [outputs, setOutputs] = useState<string[]>([]);
  const [health, setHealth] = useState<{ model: string; skill_available: boolean } | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const selectedProjectIdRef = useRef("");

  useEffect(() => {
    void loadProjects();
    void api.health().then(setHealth).catch(error => setMessage(error.message));
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
    brief: ["Brief 批量生成与审核", "按关键词分组审核 Brief，确认后进入正文生成。"],
    article: ["正文生成、审核与定稿", "折叠查阅正文，提交修改意见或确认定稿。"],
    rewrite: ["改写文章管理", "管理同关键词同类型文章的二次改写、确认和发布状态。"],
    library: ["定稿文章归档与查阅", "按关键词和文章类型分组查看归档、输出文件和导出包。"]
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
      setLogs("");
      setOutputs([]);
    }
  }

  async function refreshProject(projectId: string) {
    const next = await api.getProject(projectId);
    const [logResult, outputResult] = await Promise.all([api.getLogs(projectId), api.getOutputs(projectId)]);
    if (selectedProjectIdRef.current !== projectId) return;
    setProject(next);
    setProjects(currentProjects => currentProjects.map(item => (item.id === next.id ? next : item)));
    setLogs(logResult.logs);
    setOutputs(outputResult.files);
  }

  function selectProject(projectId: string) {
    selectedProjectIdRef.current = projectId;
    setSelectedProjectId(projectId);
    setSelectedPlans(new Set());
    setSelectedBriefs(new Set());
    setSelectedArticles(new Set());
    setDetail(null);
    setMessage("");
    if (!projectId) {
      setProject(null);
      setLogs("");
      setOutputs([]);
      return;
    }
    setProject(projects.find(item => item.id === projectId) || null);
    void refreshProject(projectId);
  }

  async function manualRefresh() {
    setBusy(false);
    setMessage("");
    if (selectedProjectIdRef.current) await refreshProject(selectedProjectIdRef.current);
    else await loadProjects();
  }

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setMessage("");
    try {
      await action();
      setMessage(success);
      if (selectedProjectIdRef.current) await refreshProject(selectedProjectIdRef.current);
      else await loadProjects();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
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
      setLogs("");
      setOutputs([]);
      setCurrent("upload");
    }, "项目已创建。");
  }

  async function runBackendStep(step: WorkflowStep, payload: Record<string, unknown> = {}) {
    if (!project) return;
    await run(async () => {
      await api.runStep(project.id, step, payload);
    }, "任务已提交，后台 Agent 正在更新状态。");
  }

  async function saveItem(step: EditableStep, item: ContentItem, payload: Record<string, unknown>) {
    if (!project) return;
    await run(async () => {
      await api.updateItem(project.id, step, item.id, {
        ...payload,
        source_id: item.sourceId,
        brief_id: item.briefId,
        source_step: item.sourceStep
      });
    }, "单篇修改已保存。");
    setDetail(null);
  }

  async function regenerateItem(step: EditableStep, item: ContentItem) {
    if (step === "brief") {
      await runBackendStep("brief", { force: true, selected_sources: [toSourcePayload(item)] });
      setDetail(null);
      return;
    }
    if (step === "article") {
      const sourceBrief = data.briefs.find(brief => brief.id === item.briefId) || item;
      await runBackendStep("article", { force: true, selected_briefs: [toBriefPayload(sourceBrief)] });
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
    }, "已确认逐词击破关键词；内容矩阵规划仍可直接生成 Brief。");
  }

  async function createCustomSource(payload: CustomSourcePayload) {
    if (!project) return;
    await run(async () => {
      await api.createCustomSource(project.id, payload);
    }, "自定义文章规划已新增。");
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

  const currentMeta = viewMeta[current];

  return (
    <div className="app prototype">
      <aside className="sidebar">
        <div className="brand">
          <span className="mark"><PenLine size={18} /></span>
          <div>
            <strong>GEO 撰文工作台</strong>
            <span>资料分析 → 规划 → Brief → 正文</span>
          </div>
        </div>

        <div className="project-card">
          <div className="project-switcher">
            <label htmlFor="project-select">当前项目</label>
            <select id="project-select" value={selectedProjectId} onChange={event => selectProject(event.target.value)}>
              <option value="">请选择项目</option>
              {projects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
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
            {health && <span className="pill">{health.model} / Skill {health.skill_available ? "已识别" : "缺失"}</span>}
            <button className="btn" onClick={() => void manualRefresh()}><RefreshCw size={15} />刷新状态</button>
            {project && <a className="btn primary" href={`/api/projects/${project.id}/export/markdown.zip`}><Download size={15} />导出 Markdown</a>}
          </div>
        </section>

        {message && <div className="notice">{message}</div>}
        {!project ? <EmptyState /> : (
          <>
            {current === "dashboard" && <DashboardView project={project} data={data} setCurrent={setCurrent} />}
            {current === "upload" && (
              <UploadView
                project={project}
                data={data}
                run={run}
                runBackendStep={runBackendStep}
                confirmBackendStep={confirmBackendStep}
                dismissedJobIds={dismissedJobIds}
                dismissJob={(jobId) => setDismissedJobIds(current => new Set([...current, jobId]))}
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
                confirmBackendStep={confirmBackendStep}
                confirmBreakthroughKeywords={confirmBreakthroughKeywords}
                createCustomSource={createCustomSource}
                updateCustomSource={updateCustomSource}
                deleteCustomSource={deleteCustomSource}
                setCurrent={setCurrent}
                openDetail={(step, item) => setDetail({ step, item })}
                dismissedJobIds={dismissedJobIds}
                dismissJob={(jobId) => setDismissedJobIds(current => new Set([...current, jobId]))}
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
                confirmBackendStep={confirmBackendStep}
                setCurrent={setCurrent}
                openDetail={(item) => setDetail({ step: "brief", item })}
                regenerateBrief={(item) => regenerateItem("brief", item)}
                dismissedJobIds={dismissedJobIds}
                dismissJob={(jobId) => setDismissedJobIds(current => new Set([...current, jobId]))}
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
                openBriefDetail={(item) => {
                  setCurrent("brief");
                  setSelectedBriefs(new Set([item.id]));
                  setDetail({ step: "brief", item });
                }}
                regenerateArticle={(item) => regenerateItem("article", item)}
                dismissedJobIds={dismissedJobIds}
                dismissJob={(jobId) => setDismissedJobIds(current => new Set([...current, jobId]))}
              />
            )}
            {current === "rewrite" && (
              <RewriteView
                project={project}
                items={data.rewrites}
                group={rewriteGroup}
                setGroup={setRewriteGroup}
                runBackendStep={runBackendStep}
                confirmBackendStep={confirmBackendStep}
              />
            )}
            {current === "library" && <LibraryView project={project} data={data} group={libraryGroup} setGroup={setLibraryGroup} outputs={outputs} logs={logs} openDetail={(step, item) => setDetail({ step, item })} />}
          </>
        )}
        {detail && (
          <ItemDetailModal
            detail={detail}
            canRegenerate={detail.step === "brief" || detail.step === "article"}
            onClose={() => setDetail(null)}
            onSave={(payload) => saveItem(detail.step, detail.item, payload)}
            onRegenerate={() => regenerateItem(detail.step, detail.item)}
          />
        )}
      </main>
    </div>
  );
}

function DashboardView({ project, data, setCurrent }: { project: Project; data: DerivedData; setCurrent: (view: AppView) => void }) {
  const missing = Math.max(materialSlots.filter(slot => slot.required).length - project.materials.length, 0);
  return (
    <div className="section-stack">
      <div className="stat-row">
        <Stat value={data.plans.length} label="总规划文章" />
        <Stat value={data.briefs.length} label="已生成 Brief" />
        <Stat value={data.articles.length} label="已生成正文" />
        <Stat value={data.archiveCount} label="已定稿/归档" />
      </div>
      <div className="grid two">
        <Panel title="项目待办" icon={<CircleAlert size={16} />}>
          <Activity icon={<Upload size={16} />} title="补齐必填资料" desc={`${missing} 个固定资料入口仍需补充或复核。`} action={<button className="btn" onClick={() => setCurrent("upload")}>处理</button>} />
          <Activity icon={<TableProperties size={16} />} title="确认项目信息" desc={project.steps.intake.status === "confirmed" ? "项目信息已确认。" : "生成抽取表后在资料页确认。"} action={<button className="btn" onClick={() => setCurrent("upload")}>查看</button>} />
          <Activity icon={<Route size={16} />} title="内容规划" desc={`${data.plans.length} 篇规划来自后台 Agent 输出。`} action={<button className="btn" onClick={() => setCurrent("planning")}>规划</button>} />
        </Panel>
        <Panel title="Agent 运行状态" icon={<LayoutDashboard size={16} />}>
          {Object.entries(project.steps).map(([step, state]) => (
            <div className="activity-item" key={step}>
              <CheckCircle2 size={16} />
              <div><strong>{step}</strong><span>{state.updated_at}</span></div>
              <Status status={state.status} />
            </div>
          ))}
        </Panel>
      </div>
    </div>
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
}) {
  const { project, data, run, runBackendStep, confirmBackendStep, dismissedJobIds, dismissJob } = props;
  const [confirmRegenerateIntake, setConfirmRegenerateIntake] = useState(false);
  const [editingIntakeRow, setEditingIntakeRow] = useState<IntakeRow | null>(null);
  const allMaterialsParsed = project.materials.length > 0 && project.materials.every(material => material.status === "parsed");
  const parseDisabled = project.materials.length === 0 || (allMaterialsParsed && project.steps.materials.status === "confirmed");
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
            <ScanText size={15} />{parseDisabled && allMaterialsParsed ? "已全部解析" : "解析资料"}
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
        <StepProgressPanel project={project} dismissedJobIds={dismissedJobIds} dismissJob={dismissJob} />
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
                        <strong key={material.id}>{stripSlotPrefix(material.filename)}</strong>
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
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
  confirmBreakthroughKeywords: (keywords: string[]) => Promise<void>;
  createCustomSource: (payload: CustomSourcePayload) => Promise<void>;
  updateCustomSource: (sourceId: string, payload: CustomSourcePayload) => Promise<void>;
  deleteCustomSource: (sourceId: string) => Promise<void>;
  setCurrent: (view: AppView) => void;
  openDetail: (step: EditableStep, item: ContentItem) => void;
  dismissedJobIds: Set<string>;
  dismissJob: (jobId: string) => void;
}) {
  const {
    project,
    data,
    tab,
    setTab,
    selectedPlans,
    setSelectedPlans,
    runBackendStep,
    confirmBackendStep,
    confirmBreakthroughKeywords,
    createCustomSource,
    updateCustomSource,
    deleteCustomSource,
    setCurrent,
    openDetail,
    dismissedJobIds,
    dismissJob
  } = props;
  const [regenerateStep, setRegenerateStep] = useState<WorkflowStep | null>(null);
  const [customModal, setCustomModal] = useState<{ mode: "create" | "edit" | "copy"; item?: ContentItem } | null>(null);
  const [deleteCustomItem, setDeleteCustomItem] = useState<ContentItem | null>(null);
  const [expandedPlanGroups, setExpandedPlanGroups] = useState<Set<string>>(new Set());
  const [selectedBreakthroughKeywords, setSelectedBreakthroughKeywords] = useState<Set<string>>(new Set(data.confirmedBreakthroughKeywords));
  const activeBackendStep: WorkflowStep | null = tab === "custom" ? null : tab === "matrix" ? "matrix" : "breakthrough";
  const stepState = activeBackendStep ? project.steps[activeBackendStep] : null;
  const rows = tab === "matrix" ? data.matrixPlans : tab === "breakthrough" ? data.breakthroughPlans : data.customPlans;
  const isRunning = stepState?.status === "running";
  const blockedMessage = stepState ? outputBlockerMessage(stepState.output) : "";
  const isBlocked = Boolean(blockedMessage);
  const hasRows = rows.length > 0;
  const hasStepOutput = Boolean(stepState && Object.keys(stepState.output || {}).length > 0);
  const planningLabel = tab === "matrix" ? "内容矩阵" : tab === "breakthrough" ? "逐词击破" : "自定义文章";
  const keywordOptions = uniqueStrings([...data.matrixKeywords, ...data.confirmedBreakthroughKeywords]);
  const selectedKeywordList = keywordOptions.filter(keyword => selectedBreakthroughKeywords.has(keyword));
  const confirmedKeywordList = data.confirmedBreakthroughKeywords;
  const matrixGroupMeta = new Map(data.matrixIntentGroups.map(group => [group.name, group]));
  const groupedRows = tab === "matrix" ? groupMatrixRowsByIntent(rows, data.matrixIntentGroups) : groupBy(rows, "keyword");
  const hasConfirmedBreakthroughKeywords = confirmedKeywordList.length > 0;
  const needsBreakthroughKeywords = activeBackendStep === "breakthrough" && !hasConfirmedBreakthroughKeywords;
  const canRegenerateCurrentStep = Boolean(activeBackendStep && hasStepOutput && !isRunning && !needsBreakthroughKeywords);
  const generationLocked = isRunning || needsBreakthroughKeywords;
  const canConfirm = Boolean(activeBackendStep && hasRows && stepState?.status === "completed" && !needsBreakthroughKeywords);
  const isConfirmed = stepState?.status === "confirmed";
  const selectedPlanItems = data.plans.filter(item => selectedPlans.has(item.id));
  const briefBySource = new Map(data.briefs.map(item => [item.sourceId, item]));
  const articleByBriefId = new Map(data.articles.map(item => [item.briefId || item.id, item]));
  const pendingBriefSources = selectedPlanItems.filter(item => !briefIsGenerated(briefBySource.get(item.sourceId)));
  const selectedCount = selectedPlanItems.length;
  const planningBriefJob = briefProgressForPlanning(project, activeBackendStep);
  const generationButtonText = selectedCount === 0
    ? "生成选中 Brief"
    : pendingBriefSources.length === 0
      ? "选中项均已有 Brief"
      : `生成选中 Brief（${pendingBriefSources.length} 篇）`;
  const confirmedKeywordSignature = confirmedKeywordList.join("\u0001");
  const emptyText = isRunning
    ? `后台 Agent 正在生成${tab === "matrix" ? "内容矩阵" : "逐词击破"}，可以点击“刷新状态”查看进度。`
    : needsBreakthroughKeywords
      ? "逐词击破是可选增强；如需生成逐词击破规划，请先回内容矩阵 Tab 勾选并确认关键词。"
    : isBlocked
      ? blockedMessage
      : stepState?.status === "failed"
        ? stepState.error || "任务失败，请调整后重新生成。"
        : tab === "custom"
          ? "可以手动添加文章标题，后台会自动补关键词和文章类型，再和矩阵/逐词击破规划一起勾选生成 Brief。"
          : `点击“生成${tab === "matrix" ? "内容矩阵" : "逐词击破"}”后，这里会展示后台 Agent 的真实输出。`;
  useEffect(() => {
    setSelectedBreakthroughKeywords(new Set(data.confirmedBreakthroughKeywords));
  }, [project.id, confirmedKeywordSignature]);
  async function confirmCurrentPlanning() {
    if (!activeBackendStep) return;
    await confirmBackendStep(activeBackendStep);
    if (activeBackendStep === "matrix") setTab("breakthrough");
  }
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
  async function submitCustomSource(payload: CustomSourcePayload) {
    if (customModal?.mode === "edit" && customModal.item) {
      await updateCustomSource(customModal.item.sourceId, payload);
    } else {
      await createCustomSource(payload);
    }
    setCustomModal(null);
  }
  async function confirmDeleteCustomSource() {
    if (!deleteCustomItem) return;
    const staleId = deleteCustomItem.id;
    await deleteCustomSource(deleteCustomItem.sourceId);
    setSelectedPlans(current => new Set([...current].filter(id => id !== staleId)));
    setDeleteCustomItem(null);
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
  const breakthroughRunPayload = activeBackendStep === "breakthrough" ? { confirmed_keywords: confirmedKeywordList } : undefined;
  return (
    <div className="section-stack">
      {activeBackendStep && (
        <div className="bulk-bar">
          <div>
            <strong>{tab === "matrix" ? "内容矩阵整体规划" : "逐词击破六类规划"}</strong>
            <span>
              {hasRows
                ? `后台 Agent 已生成 ${rows.length} 条规划。`
                : isRunning
                  ? "后台 Agent 正在生成，请稍等。"
                  : needsBreakthroughKeywords
                    ? "请先在内容矩阵中确认关键词后再生成逐词击破；内容矩阵规划可直接生成 Brief。"
                    : isBlocked
                      ? "需要先补充或确认关键词，暂未生成正式规划。"
                      : "暂无规划结果。"}
            </span>
          </div>
          <div className="actions">
            <button
              className="btn"
              disabled={generationLocked}
              onClick={() => {
                if (canRegenerateCurrentStep) setRegenerateStep(activeBackendStep);
                else void runBackendStep(activeBackendStep, breakthroughRunPayload);
              }}
            >
              {isRunning ? "生成中" : needsBreakthroughKeywords ? "先确认逐词击破关键词" : canRegenerateCurrentStep ? `重新生成${planningLabel}` : `生成${planningLabel}`}
            </button>
            {activeBackendStep === "breakthrough" && <button className="btn primary" disabled={!canConfirm} onClick={() => void confirmCurrentPlanning()}>{isConfirmed ? "已确认当前规划" : "确认当前规划"}</button>}
          </div>
        </div>
      )}
      {regenerateStep && (
        <div className="modal-backdrop" role="presentation">
          <div className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="regenerate-planning-title">
            <h2 id="regenerate-planning-title">重新生成{stepLabel(regenerateStep)}？</h2>
            <p>确认后会立即清空当前{stepLabel(regenerateStep)}结果或错误状态，并用后台 Agent 的新结果覆盖。取消则不会做任何更改。</p>
            <div className="actions end">
              <button className="btn" onClick={() => setRegenerateStep(null)}>取消</button>
              <button className="btn primary" onClick={() => {
                const step = regenerateStep;
                setRegenerateStep(null);
                setSelectedPlans(current => {
                  const staleIds = new Set((step === "matrix" ? data.matrixPlans : data.breakthroughPlans).map(item => item.id));
                  return new Set([...current].filter(id => !staleIds.has(id)));
                });
                void runBackendStep(step, step === "breakthrough" ? { force: true, confirmed_keywords: confirmedKeywordList } : { force: true });
              }}>确认重新生成</button>
            </div>
          </div>
        </div>
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
            <p>这只会删除规划页里的自定义文章项，不会删除已经生成的 Brief 或正文。取消则不会做任何更改。</p>
            <div className="actions end">
              <button className="btn" onClick={() => setDeleteCustomItem(null)}>取消</button>
              <button className="btn primary" onClick={() => void confirmDeleteCustomSource()}>确认删除</button>
            </div>
          </div>
        </div>
      )}
      {activeBackendStep && <StepProgressPanel project={project} steps={[activeBackendStep]} dismissedJobIds={dismissedJobIds} dismissJob={dismissJob} />}
      <JobProgress job={planningBriefJob} dismissedJobIds={dismissedJobIds} onDismiss={dismissJob} />
      <div className="tabs">
        <button className={tab === "matrix" ? "active" : ""} onClick={() => setTab("matrix")}>内容矩阵</button>
        <button className={tab === "breakthrough" ? "active" : ""} onClick={() => setTab("breakthrough")}>逐词击破</button>
        <button className={tab === "custom" ? "active" : ""} onClick={() => setTab("custom")}>自定义文章</button>
      </div>
      {tab === "matrix" && (
        <BreakthroughKeywordSelection
          keywords={keywordOptions}
          selectedKeywords={selectedBreakthroughKeywords}
          confirmedKeywords={confirmedKeywordList}
          onToggle={setKeywordSelection}
          onSelectAll={() => setSelectedBreakthroughKeywords(new Set(keywordOptions))}
          onClear={() => setSelectedBreakthroughKeywords(new Set())}
          onConfirm={() => void confirmKeywordsForBreakthrough()}
        />
      )}
      {tab === "breakthrough" && (
        <div className={`keyword-confirmation-summary ${hasConfirmedBreakthroughKeywords ? "confirmed" : "missing"}`}>
          <div>
            <strong>{hasConfirmedBreakthroughKeywords ? `已确认 ${confirmedKeywordList.length} 个逐词击破关键词` : "尚未确认逐词击破关键词"}</strong>
            <span>{hasConfirmedBreakthroughKeywords ? confirmedKeywordList.join("、") : "仅生成逐词击破时需要先回内容矩阵 Tab 勾选关键词；矩阵规划可直接生成 Brief。"}</span>
          </div>
          {!hasConfirmedBreakthroughKeywords && <button className="btn" onClick={() => setTab("matrix")}>去确认关键词</button>}
        </div>
      )}
      <div className="bulk-bar selection-bar">
        <div>
          <strong>已选 {selectedCount} 篇规划</strong>
          <span>{selectedCount ? `其中 ${pendingBriefSources.length} 篇尚未生成 Brief。` : "先勾选内容矩阵、逐词击破或自定义文章里的规划。"}</span>
        </div>
        <div className="actions">
          <button className="btn" disabled={!selectedCount} onClick={() => setSelectedPlans(new Set())}>清空选择</button>
          <button className="btn primary" disabled={!pendingBriefSources.length} onClick={() => void generateSelectedBriefs()}>{generationButtonText}</button>
        </div>
      </div>
      {tab === "custom" ? (
        <CustomPlanningPanel
          items={data.customPlans}
          selectedPlans={selectedPlans}
          briefBySource={briefBySource}
          articleByBriefId={articleByBriefId}
          onAdd={() => setCustomModal({ mode: "create" })}
          onEdit={(item) => setCustomModal({ mode: "edit", item })}
          onDelete={(item) => setDeleteCustomItem(item)}
          onSelectionChange={setGroupSelection}
          onToggle={(item) => setSelectedPlans(current => toggleSet(current, item.id))}
        />
      ) : rows.length ? (
        <div className="keyword-groups">
          {Object.entries(groupedRows).map(([groupName, groupRows]) => {
            const groupKey = `${activeBackendStep}:${groupName}`;
            const expanded = expandedPlanGroups.has(groupKey);
            const intentMeta = tab === "matrix" ? matrixGroupMeta.get(groupName) : undefined;
            const groupTitle = `${groupName}（${planGroupStatsText(groupRows, selectedPlans, briefBySource)}）`;
            const groupSubtitle = intentMeta
              ? matrixIntentSubtitle(intentMeta)
              : tab === "matrix"
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
                        brief={briefBySource.get(item.sourceId)}
                        article={articleForPlanItem(item, briefBySource, articleByBriefId)}
                        onToggle={() => setSelectedPlans(current => toggleSet(current, item.id))}
                        onOpen={() => openDetail(item.sourceStep === "breakthrough" ? "breakthrough" : "matrix", item)}
                        onCopy={() => setCustomModal({ mode: "copy", item })}
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
            <p className="muted">从内容矩阵中确认要逐词拆成固定六类文章的关键词。保存后，逐词击破只会围绕这些关键词生成。</p>
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
            <button className="btn primary" disabled={!selectedList.length} onClick={onConfirm}>确认关键词并进入逐词击破</button>
          </div>
        </div>
      ) : (
        <EmptyPanelText text="内容矩阵里暂未识别到可用于逐词击破的关键词。请先生成或重新生成内容矩阵。" />
      )}
    </Panel>
  );
}

function CustomPlanningPanel({
  items,
  selectedPlans,
  briefBySource,
  articleByBriefId,
  onAdd,
  onEdit,
  onDelete,
  onSelectionChange,
  onToggle
}: {
  items: ContentItem[];
  selectedPlans: Set<string>;
  briefBySource: Map<string, ContentItem>;
  articleByBriefId: Map<string, ContentItem>;
  onAdd: () => void;
  onEdit: (item: ContentItem) => void;
  onDelete: (item: ContentItem) => void;
  onSelectionChange: (rows: ContentItem[], selected: boolean) => void;
  onToggle: (item: ContentItem) => void;
}) {
  return (
    <Panel
      title="自定义文章"
      icon={<Plus size={16} />}
      aside={
        <div className="actions">
          {items.length > 0 && <GroupSelectAside rows={items} selectedPlans={selectedPlans} onChange={onSelectionChange} />}
          <button className="btn primary" onClick={onAdd}><Plus size={15} />新增自定义文章</button>
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
        <EmptyPanelText text="可以在这里手动添加文章标题，后台会自动补关键词和文章类型，再和矩阵/逐词击破规划一起勾选生成 Brief。" />
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
  const canSubmit = Boolean(title.trim());
  const modalTitle = mode === "edit" ? "编辑自定义文章" : mode === "copy" ? "复制为自定义文章" : "新增自定义文章";

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      title: title.trim(),
      raw: customSourceRawFor(mode, item)
    });
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form className="confirm-modal custom-source-modal" role="dialog" aria-modal="true" aria-labelledby="custom-source-title" onSubmit={submit}>
        <h2 id="custom-source-title">{modalTitle}</h2>
        <p>只需要输入文章标题；后台会根据项目资料和已有规划自动补齐关键词和文章类型。正文仍需要先经过 Brief 审核。</p>
        <div className="form-grid">
          <label className="field-block full">
            <span>标题</span>
            <input value={title} onChange={event => setTitle(event.target.value)} placeholder="例如：企业如何选择 GEO 内容生产工具" />
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

function BriefView(props: {
  project: Project;
  items: ContentItem[];
  articles: ContentItem[];
  selectedSourceItems: ContentItem[];
  selectedBriefItems: ContentItem[];
  selectedBriefs: Set<string>;
  setSelectedBriefs: React.Dispatch<React.SetStateAction<Set<string>>>;
  runBackendStep: (step: WorkflowStep, payload?: Record<string, unknown>) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
  setCurrent: (view: AppView) => void;
  openDetail: (item: ContentItem) => void;
  regenerateBrief: (item: ContentItem) => Promise<void>;
  dismissedJobIds: Set<string>;
  dismissJob: (jobId: string) => void;
}) {
  const { project, items, articles, selectedSourceItems, selectedBriefs, setSelectedBriefs, runBackendStep, confirmBackendStep, setCurrent, openDetail, regenerateBrief, dismissedJobIds, dismissJob } = props;
  const articleByBriefId = new Map(articles.map(item => [item.briefId || item.id, item]));
  const [draftFilters, setDraftFilters] = useState<BriefFilterState>(emptyBriefFilters);
  const [activeFilters, setActiveFilters] = useState<BriefFilterState>(emptyBriefFilters);
  const keywordOptions = uniqueStrings(items.map(item => item.keyword).filter(Boolean));
  const articleTypeOptions = uniqueStrings(items.map(item => item.type).filter(Boolean));
  const filteredItems = filterBriefItems(items, articleByBriefId, activeFilters);
  const selectedVisibleBriefItems = filteredItems.filter(item => selectedBriefs.has(item.id));
  const allBriefsSelected = filteredItems.length > 0 && filteredItems.every(item => selectedBriefs.has(item.id));
  const pendingArticleBriefs = selectedVisibleBriefItems.filter(brief => !articles.some(article => articleCurrentForBrief(article, brief)));
  const pendingUpdateCount = pendingArticleBriefs.filter(brief => {
    const article = articleByBriefId.get(brief.id);
    return article && !articleCurrentForBrief(article, brief);
  }).length;
  const articleButtonText = selectedVisibleBriefItems.length === 0
    ? "生成选中正文"
    : pendingArticleBriefs.length === 0
      ? "选中 Brief 均已有正文"
      : pendingUpdateCount
        ? `生成更新后的正文（${pendingArticleBriefs.length} 篇）`
        : `生成选中正文（${pendingArticleBriefs.length} 篇）`;
  useEffect(() => {
    setDraftFilters(emptyBriefFilters);
    setActiveFilters(emptyBriefFilters);
  }, [project.id]);
  async function generateSelectedArticles() {
    if (!pendingArticleBriefs.length) return;
    if (project.steps.brief.status !== "confirmed") {
      await confirmBackendStep("brief");
    }
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
        <JobProgress job={latestJob(project, "brief")} dismissedJobIds={dismissedJobIds} onDismiss={dismissJob} />
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
  openBriefDetail: (item: ContentItem) => void;
  regenerateArticle: (item: ContentItem) => Promise<void>;
  dismissedJobIds: Set<string>;
  dismissJob: (jobId: string) => void;
}) {
  const { project, items, briefs, selectedArticles, setSelectedArticles, openDetail, openBriefDetail, regenerateArticle, dismissedJobIds, dismissJob } = props;
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
                <option value="generated">已生成/已更新</option>
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
          <button className="btn" disabled>请在 Brief 页选择生成</button>
          <button className="btn" disabled={!filteredItems.length} onClick={toggleAllArticles}>{allSelected ? "取消全选" : "全选正文"}</button>
          <button className="btn primary" disabled={!selectedArticleItems.length} onClick={exportSelectedArticles}><Download size={15} />导出正文</button>
        </div>
      </div>
      <JobProgress job={latestJob(project, "article")} dismissedJobIds={dismissedJobIds} onDismiss={dismissJob} />
      {filteredItems.length ? (
        <div className="article-list">
          {filteredItems.map(item => (
            <article className={`article-collapse ${articleReviewCardClass(item)}`} key={item.id}>
              <div className="article-card-head">
                <input type="checkbox" checked={selectedArticles.has(item.id)} onChange={event => {
                  setSelectedArticles(current => toggleSet(current, item.id));
                }} />
                <div>
                  <h3>{item.title}</h3>
                  <div className="chips meta-chips review-meta-chips">
                    <Chip text={item.keyword} type="brand" className="keyword-chip" />
                    <Chip text={item.type} className="type-chip" />
                    {briefById.get(item.briefId || "") && (
                      <button type="button" className="chip good state-chip chip-button" onClick={() => openBriefDetail(briefById.get(item.briefId || "")!)}>
                        <span>已绑定 Brief</span>
                      </button>
                    )}
                    <ItemStatusChip status={item.status} className="state-chip" />
                  </div>
                </div>
                <div className="row-actions">
                  <button className="btn" onClick={() => openDetail(item)}><BookOpen size={15} />查阅/编辑</button>
                  <button className="btn" disabled={item.status === "running"} onClick={() => void regenerateArticle(item)}><RefreshCw size={15} />{item.status === "failed" ? "重试" : "重新生成"}</button>
                </div>
              </div>
              {(item.error || item.staleReason) && <p className={item.staleReason ? "item-warning" : "item-error"}>{item.error || item.staleReason}</p>}
            </article>
          ))}
        </div>
      ) : (
        <Panel title="暂无正文" icon={<Newspaper size={16} />}>
          <EmptyPanelText text={items.length ? "当前筛选条件下没有正文。" : "请先确认 Brief，然后点击“生成正文”。"} />
        </Panel>
      )}
    </div>
  );
}

function RewriteView({ project, items, group, setGroup, runBackendStep, confirmBackendStep }: {
  project: Project;
  items: ContentItem[];
  group: "keyword" | "type";
  setGroup: (group: "keyword" | "type") => void;
  runBackendStep: (step: WorkflowStep) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
}) {
  const grouped = groupBy(items, group);
  return (
    <div className="drawer-layout">
      <Panel title="改写稿分组" icon={<RefreshCw size={16} />}>
        <div className="tabs"><button className={group === "keyword" ? "active" : ""} onClick={() => setGroup("keyword")}>关键词</button><button className={group === "type" ? "active" : ""} onClick={() => setGroup("type")}>文章类型</button></div>
        {items.length ? Object.entries(grouped).map(([name, rows]) => <Activity key={name} icon={<Search size={16} />} title={name} desc={`${rows.length} 篇改写稿`} />) : <EmptyPanelText text="暂无改写稿。" />}
      </Panel>
      <Panel title="改写文章管理" icon={<Newspaper size={16} />} aside={<Chip text={`${items.length} 篇筛选结果`} type={items.length ? "brand" : "warn"} />}>
        <div className="actions block-actions">
          <button className="btn" onClick={() => runBackendStep("rewrite")}>生成改写稿</button>
          <button className="btn primary" disabled={project.steps.rewrite.status !== "completed"} onClick={() => confirmBackendStep("rewrite")}>确认改写稿</button>
        </div>
        {items.length ? items.map(item => (
          <article className="review-card" key={item.id}>
            <div className="review-card-head">
              <RefreshCw size={16} />
              <div>
                <h3>{item.title}</h3>
                <div className="chips meta-chips review-meta-chips">
                  <Chip text={item.keyword} type="brand" className="keyword-chip" />
                  <ItemStatusChip status={item.status} className="state-chip" />
                  <Chip text={item.used} className="state-chip" />
                </div>
              </div>
              <button className="btn">确认</button>
            </div>
            <p>{item.markdown || item.role}</p>
          </article>
        )) : <EmptyPanelText text="暂无改写稿。请先生成正文，再运行改写。" />}
      </Panel>
    </div>
  );
}

function LibraryView({ project, data, group, setGroup, outputs, logs, openDetail }: {
  project: Project;
  data: DerivedData;
  group: "keyword" | "type";
  setGroup: (group: "keyword" | "type") => void;
  outputs: string[];
  logs: string;
  openDetail: (step: EditableStep, item: ContentItem) => void;
}) {
  const allItems = [...data.articles, ...data.rewrites];
  const grouped = groupBy(allItems, group);
  return (
    <div className="library-grid">
      <Panel title="归档分组" icon={<Archive size={16} />}>
        <div className="tabs"><button className={group === "keyword" ? "active" : ""} onClick={() => setGroup("keyword")}>关键词</button><button className={group === "type" ? "active" : ""} onClick={() => setGroup("type")}>文章类型</button></div>
        {allItems.length ? Object.entries(grouped).map(([name, rows]) => <Activity key={name} icon={<Archive size={16} />} title={name} desc={`${rows.length} 篇文章`} />) : <EmptyPanelText text="暂无归档文章。" />}
      </Panel>
      <Panel title="文章列表与输出文件" icon={<BookOpen size={16} />} aside={<a className="btn primary" href={`/api/projects/${project.id}/export/markdown.zip`}><Download size={15} />导出</a>}>
        <div className="article-list">
          {allItems.length ? allItems.map(item => (
            <article className="library-item" key={item.id}>
              <div>
                <h3>{item.title}</h3>
                <p>{item.markdown || item.role}</p>
                <div className="chips meta-chips review-meta-chips">
                  <Chip text={item.keyword} type="brand" className="keyword-chip" />
                  <Chip text={item.type} className="type-chip" />
                  <ItemStatusChip status={item.status} className="state-chip" />
                </div>
              </div>
              <button className="btn" onClick={() => openDetail(data.articles.some(article => article.id === item.id) ? "article" : "rewrite", item)}><BookOpen size={15} />查阅</button>
            </article>
          )) : <EmptyPanelText text="暂无文章。生成正文或改写稿后会显示在这里。" />}
        </div>
        <div className="output-list">
          <h3>后台输出文件</h3>
          {outputs.length ? outputs.map(file => <div className="file-row" key={file}><FileText size={15} />{file}</div>) : <p className="muted">暂无输出文件。</p>}
        </div>
        <pre className="logs compact">{logs || "暂无日志"}</pre>
      </Panel>
    </div>
  );
}

function PlanGroupAside({
  rows,
  selectedPlans,
  expanded,
  onSelectionChange,
  onToggleExpanded
}: {
  rows: ContentItem[];
  selectedPlans: Set<string>;
  expanded: boolean;
  onSelectionChange: (rows: ContentItem[], selected: boolean) => void;
  onToggleExpanded: () => void;
}) {
  return (
    <div className="plan-group-actions">
      <GroupSelectAside rows={rows} selectedPlans={selectedPlans} onChange={onSelectionChange} />
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
      <input type="checkbox" checked={selected} onChange={onToggle} />
      <div>
        <h3>{item.type}｜{item.title}</h3>
        <p>{item.role}</p>
        <div className="chips meta-chips plan-meta-chips">
          <Chip text={item.keyword} type="brand" className="keyword-chip" />
          <Chip text={item.channel} className="channel-chip" />
          <PlanBriefStatusChip status={brief?.status} />
        </div>
      </div>
      <div className="row-actions">
        {onOpen && <button className="btn" onClick={onOpen}><BookOpen size={15} />查阅/编辑</button>}
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
  return !["failed", "running", "queued", "pending"].includes(brief.status);
}

function Status({ status }: { status: string }) {
  const type = status.includes("confirmed") || status.includes("已") || status.includes("parsed") ? "good" : status.includes("failed") ? "danger" : status.includes("running") || status.includes("completed") ? "warn" : "";
  return <Chip text={status} type={type} />;
}

function ItemStatusChip({ status, className = "" }: { status: string; className?: string }) {
  const type = status.includes("失败") || status.includes("failed")
    ? "danger"
    : status.includes("需更新") || status.includes("旧 Brief") || status.includes("待生成") || status.includes("已修改") || status.includes("modified") || status.includes("stale")
      ? "warn"
      : status.includes("生成中") || status.includes("running")
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
  dismissJob
}: {
  project: Project;
  steps?: WorkflowStep[];
  dismissedJobIds: Set<string>;
  dismissJob: (jobId: string) => void;
}) {
  const jobs = steps.map(step => latestJob(project, step)).filter((job): job is Project["jobs"][number] => Boolean(job));
  const activeJob = jobs.find(job => job.status === "running" || job.status === "queued");
  const blockedStep = steps.find(step => outputBlockerMessage(project.steps[step].output));
  const failedJob = jobs.find(job => job.status === "failed");
  const completedJobs = jobs.filter(job => job.status === "completed" && !dismissedJobIds.has(job.id));
  const visibleJobs = activeJob ? [activeJob] : failedJob ? [failedJob] : blockedStep ? [] : completedJobs;
  const fallbackFailures = steps.filter(step => step !== blockedStep && (project.steps[step].status === "failed" || outputBlockerMessage(project.steps[step].output)) && !jobs.some(job => job.step === step));

  if (!visibleJobs.length && !fallbackFailures.length && !blockedStep) return null;

  return (
    <div className="step-progress-panel">
      <div className="step-progress-title">
        {activeJob ? <Loader2 className="spin" size={16} /> : failedJob || fallbackFailures.length || blockedStep ? <CircleAlert size={16} /> : <CheckCircle2 size={16} />}
        <div>
          <strong>{activeJob ? progressTitle(activeJob.step, true) : failedJob || fallbackFailures.length || blockedStep ? "需要补充输入" : "执行完成"}</strong>
          <span>{blockedStep ? outputBlockerMessage(project.steps[blockedStep].output) : progressSubtitle(activeJob || failedJob || visibleJobs[0])}</span>
        </div>
      </div>
      {visibleJobs.map(job => <JobProgress job={job} dismissedJobIds={dismissedJobIds} onDismiss={dismissJob} key={job.id} />)}
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
            <strong>{outputBlockerMessage(project.steps[step].output) || project.steps[step].error || `${stepLabel(step)}失败，可重试。`}</strong>
            <ItemStatusChip status="failed" />
          </div>
          <div className="job-progress-bar"><span style={{ width: "100%" }} /></div>
          <p className="item-error">{outputBlockerMessage(project.steps[step].output) || project.steps[step].error || "后台任务未留下进度记录，请重新运行该步骤。"}</p>
        </div>
      ))}
    </div>
  );
}

function JobProgress({
  job,
  dismissedJobIds,
  onDismiss
}: {
  job?: Project["jobs"][number];
  dismissedJobIds: Set<string>;
  onDismiss: (jobId: string) => void;
}) {
  if (!job || (job.status === "completed" && dismissedJobIds.has(job.id)) || (!job.total_count && !job.message && job.status === "queued")) return null;
  const total = Math.max(job.total_count || 0, 1);
  const rawProcessed = (job.completed_count || 0) + (job.failed_count || 0) + (job.skipped_count || 0);
  const processed = job.status === "completed" && rawProcessed === 0 && !job.total_count ? total : Math.min(rawProcessed, total);
  const percent = Math.round((processed / total) * 100);
  const indeterminate = job.status === "running" && total <= 1 && processed === 0;
  const canDismiss = job.status === "completed";
  return (
    <div className={`job-progress ${job.status}`}>
      <div className="job-progress-head">
        <strong>{job.message || progressSubtitle(job)}</strong>
        <div className="job-progress-status">
          <ItemStatusChip status={job.status} />
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
      {job.error && <p className="item-error">{job.error}</p>}
    </div>
  );
}

function ItemDetailModal({
  detail,
  canRegenerate,
  onClose,
  onSave,
  onRegenerate
}: {
  detail: DetailState;
  canRegenerate: boolean;
  onClose: () => void;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onRegenerate: () => Promise<void>;
}) {
  const [title, setTitle] = useState(detail.item.title);
  const [markdown, setMarkdown] = useState(detail.item.markdown || "");
  const [reviewNotes, setReviewNotes] = useState(detail.item.reviewNotes || "");
  const [copied, setCopied] = useState(false);
  const canEditMarkdown = detail.step === "brief" || detail.step === "article" || detail.step === "rewrite";
  const fullText = markdown || JSON.stringify(detail.item.raw, null, 2);

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
      <div className="detail-modal" role="dialog" aria-modal="true" aria-labelledby="item-detail-title">
        <div className="detail-head">
          <div>
            <span className="detail-kicker">{stepLabel(detail.step)} / {detail.item.keyword}</span>
            <h2 id="item-detail-title">{detail.item.title}</h2>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="关闭"><X size={16} /></button>
        </div>
        <div className="detail-meta">
          <Chip text={detail.item.type} />
          <ItemStatusChip status={detail.item.status} />
          {detail.item.sourceStep && <Chip text={detail.item.sourceStep} />}
          {detail.item.briefId && <Chip text={`Brief ${detail.item.briefId}`} />}
        </div>
        {detail.item.error && <p className="item-error">{detail.item.error}</p>}
        <label className="field-block">
          <span>标题</span>
          <input value={title} onChange={event => setTitle(event.target.value)} />
        </label>
        <label className="field-block">
          <span>{canEditMarkdown ? "完整 Markdown" : "完整规划数据"}</span>
          <textarea
            value={fullText}
            readOnly={!canEditMarkdown}
            onChange={event => setMarkdown(event.target.value)}
          />
        </label>
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
          {canRegenerate && <button className="btn" disabled={detail.item.status === "running"} onClick={() => void onRegenerate()}><RefreshCw size={15} />{detail.item.status === "failed" ? "重试单篇" : "重新生成单篇"}</button>}
          <button className="btn primary" onClick={() => void onSave({
            title,
            markdown: canEditMarkdown ? markdown : detail.item.markdown || "",
            review_notes: reviewNotes
          })}><Save size={15} />保存</button>
        </div>
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
  breakthroughPlans: ContentItem[];
  customPlans: ContentItem[];
  matrixKeywords: string[];
  confirmedBreakthroughKeywords: string[];
  plans: ContentItem[];
  briefs: ContentItem[];
  articles: ContentItem[];
  rewrites: ContentItem[];
  archiveCount: number;
}

function emptyDerivedData(): DerivedData {
  return { intakeRows: [], matrixPlans: [], matrixIntentGroups: [], breakthroughPlans: [], customPlans: [], matrixKeywords: [], confirmedBreakthroughKeywords: [], plans: [], briefs: [], articles: [], rewrites: [], archiveCount: 0 };
}

function deriveProjectData(project: Project): DerivedData {
  const matrixPlans = normalizeItems(project.steps.matrix.output, "matrix");
  const matrixIntentGroups = normalizeMatrixIntentGroups(project.steps.matrix.output, matrixPlans);
  const matrixKeywordOptions = extractMatrixKeywordOptions(project.steps.matrix.output);
  const breakthroughPlans = normalizeItems(project.steps.breakthrough.output, "breakthrough");
  const customPlans = normalizeItems({ items: project.custom_sources || [] }, "custom");
  const briefs = sortBriefsNewestFirst(normalizeItems(project.steps.brief.output, "brief"));
  const articles = normalizeItems(project.steps.article.output, "article");
  const rewrites = normalizeItems(project.steps.rewrite.output, "rewrite");
  return {
    intakeRows: normalizeIntake(project.steps.intake.output),
    matrixPlans,
    matrixIntentGroups,
    breakthroughPlans,
    customPlans,
    matrixKeywords: matrixKeywordOptions.length ? matrixKeywordOptions : uniqueKeywords(matrixPlans),
    confirmedBreakthroughKeywords: readConfirmedBreakthroughKeywords(project.steps.matrix.output),
    plans: [...matrixPlans, ...breakthroughPlans, ...customPlans],
    briefs,
    articles,
    rewrites,
    archiveCount: [...articles, ...rewrites].filter(item => item.status.includes("已") || item.status === "completed").length
  };
}

function uniqueKeywords(items: ContentItem[]): string[] {
  return uniqueStrings(items.map(item => item.keyword).filter(keyword => keyword && keyword !== "未标注关键词"));
}

function readConfirmedBreakthroughKeywords(output: AnyRecord): string[] {
  const selection = output.breakthrough_keyword_selection;
  if (!isRecord(selection)) return [];
  const keywords = selection.keywords;
  return Array.isArray(keywords) ? uniqueStrings(keywords) : [];
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
    const sourceId = readString(row, ["source_id", "sourceId"], fallbackSourceId);
    const briefId = readString(row, ["brief_id", "briefId"], step === "article" ? readString(row, ["id"], "") : "");
    const fallbackId = step === "brief" ? `brief-${sourceId}` : step === "article" && briefId ? `article-${briefId}` : sourceId;
    const roleKeys = step === "brief"
      ? ["role", "summary", "main_role", "brief_focus", "core_recommendation_conclusion", "主要作用", "description"]
      : ["role", "summary", "main_role", "brief_focus", "core_recommendation", "core_recommendation_conclusion", "主要作用", "后续Brief要点", "brief", "description"];
    const item = {
      id: readString(row, ["id"], fallbackId),
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
      error: readString(row, ["error", "错误"], ""),
      revision: readNumber(row, ["revision"], 1),
      modifiedAt: readString(row, ["modified_at", "modifiedAt"], ""),
      briefRevision: readNumber(row, ["brief_revision", "briefRevision"], 1),
      staleReason: readString(row, ["stale_reason", "staleReason"], ""),
      raw: row
    };
    return applyItemOverride(item, overrides);
  });
}

function sortBriefsNewestFirst(items: ContentItem[]): ContentItem[] {
  return items
    .map((item, index) => ({ item, index, generatedAt: itemGeneratedAtMs(item) }))
    .sort((left, right) => right.generatedAt - left.generatedAt || right.index - left.index)
    .map(entry => entry.item);
}

function itemGeneratedAtMs(item: ContentItem): number {
  return timestampMs(readString(item.raw, ["generated_at", "generatedAt", "created_at", "createdAt", "updated_at", "updatedAt"], ""));
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
    if (filters.articleStatus !== "all" && articleFilterStatus(item, brief) !== filters.articleStatus) {
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

function articleFilterStatus(article: ContentItem, brief?: ContentItem): Exclude<BriefArticleFilter, "all" | "not_generated"> {
  if (article.status === "failed") return "failed";
  if (brief && !articleCurrentForBrief(article, brief)) return "needs_update";
  if (["running", "queued", "pending", "stale", "modified"].includes(article.status)) return "needs_update";
  return article.markdown || ["completed", "confirmed"].includes(article.status) ? "generated" : "needs_update";
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
    breakthrough: "逐词击破",
    custom: "自定义文章",
    brief: "Brief",
    article: "正文",
    rewrite: "改写稿"
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
  if (job.status === "failed") return job.error || "任务失败，可重试。";
  if (job.current_item) return `当前：${job.current_item}`;
  if (job.message) return job.message;
  return `${progressTitle(job.step, job.status === "running")}：${statusLabel(job.status)}`;
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
  if (briefJob.status === "queued" || briefJob.status === "running") return briefJob;
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

function articleReviewCardClass(article: ContentItem): string {
  if (article.status === "failed") return "review-danger";
  if (["running", "queued", "pending", "stale", "modified"].includes(article.status)) return "review-warn";
  return article.markdown || ["completed", "confirmed"].includes(article.status) ? "review-good" : "";
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

createRoot(document.getElementById("root")!).render(<App />);
