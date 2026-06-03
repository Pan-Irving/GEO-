import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Archive,
  BadgeAlert,
  BookOpen,
  CheckCircle2,
  CircleAlert,
  Download,
  FileArchive,
  FileText,
  FolderOpen,
  LayoutDashboard,
  Loader2,
  Newspaper,
  PenLine,
  RefreshCw,
  Route,
  ScanText,
  Search,
  TableProperties,
  Upload
} from "lucide-react";
import { api } from "./api/client";
import type { Project, WorkflowStep } from "./api/types";
import "./styles/app.css";

type AppView = "dashboard" | "upload" | "planning" | "brief" | "article" | "rewrite" | "library";
type PlanningTab = "matrix" | "breakthrough";

type AnyRecord = Record<string, unknown>;

interface ContentItem {
  id: string;
  keyword: string;
  type: string;
  title: string;
  role: string;
  channel: string;
  status: string;
  used: string;
  markdown?: string;
  raw: AnyRecord;
}

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
  const [project, setProject] = useState<Project | null>(null);
  const [current, setCurrent] = useState<AppView>("dashboard");
  const [planningTab, setPlanningTab] = useState<PlanningTab>("matrix");
  const [libraryGroup, setLibraryGroup] = useState<"keyword" | "type">("keyword");
  const [rewriteGroup, setRewriteGroup] = useState<"keyword" | "type">("keyword");
  const [selectedPlans, setSelectedPlans] = useState<Set<string>>(new Set());
  const [selectedBriefs, setSelectedBriefs] = useState<Set<string>>(new Set());
  const [selectedArticles, setSelectedArticles] = useState<Set<string>>(new Set());
  const [confirmedFields, setConfirmedFields] = useState<Set<string>>(new Set());
  const [projectName, setProjectName] = useState("GEO 内容项目");
  const [logs, setLogs] = useState("");
  const [outputs, setOutputs] = useState<string[]>([]);
  const [health, setHealth] = useState<{ model: string; skill_available: boolean } | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void loadProjects();
    void api.health().then(setHealth).catch(error => setMessage(error.message));
  }, []);

  useEffect(() => {
    if (!project) return;
    const timer = window.setInterval(() => void refreshProject(project.id), 2500);
    return () => window.clearInterval(timer);
  }, [project?.id]);

  const data = useMemo(() => project ? deriveProjectData(project) : emptyDerivedData(), [project]);

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
    if (list[0]) {
      setProject(list[0]);
      await refreshProject(list[0].id);
    }
  }

  async function refreshProject(projectId: string) {
    const next = await api.getProject(projectId);
    const [logResult, outputResult] = await Promise.all([api.getLogs(projectId), api.getOutputs(projectId)]);
    setProject(next);
    setProjects(currentProjects => currentProjects.map(item => (item.id === next.id ? next : item)));
    setLogs(logResult.logs);
    setOutputs(outputResult.files);
  }

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setMessage("");
    try {
      await action();
      setMessage(success);
      if (project) await refreshProject(project.id);
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
      setProject(created);
      setCurrent("upload");
    }, "项目已创建。");
  }

  async function runBackendStep(step: WorkflowStep) {
    if (!project) return;
    await run(async () => {
      await api.runStep(project.id, step, {});
    }, "任务已提交，后台 Agent 正在运行。");
  }

  async function confirmBackendStep(step: WorkflowStep) {
    if (!project) return;
    await run(async () => {
      await api.confirmStep(project.id, step);
    }, "该阶段已确认。");
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
          <label>当前项目</label>
          <select value={project?.id || ""} onChange={event => {
            const next = projects.find(item => item.id === event.target.value) || null;
            setProject(next);
            if (next) void refreshProject(next.id);
          }}>
            <option value="">请选择项目</option>
            {projects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <div className="new-project">
            <input value={projectName} onChange={event => setProjectName(event.target.value)} />
            <button onClick={createProject}>新建</button>
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
                confirmedFields={confirmedFields}
                setConfirmedFields={setConfirmedFields}
                run={run}
                runBackendStep={runBackendStep}
                confirmBackendStep={confirmBackendStep}
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
              />
            )}
            {current === "brief" && (
              <BriefView
                project={project}
                items={data.briefs}
                selectedBriefs={selectedBriefs}
                setSelectedBriefs={setSelectedBriefs}
                runBackendStep={runBackendStep}
                confirmBackendStep={confirmBackendStep}
              />
            )}
            {current === "article" && (
              <ArticleView
                project={project}
                items={data.articles}
                selectedArticles={selectedArticles}
                setSelectedArticles={setSelectedArticles}
                runBackendStep={runBackendStep}
                confirmBackendStep={confirmBackendStep}
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
            {current === "library" && <LibraryView project={project} data={data} group={libraryGroup} setGroup={setLibraryGroup} outputs={outputs} logs={logs} />}
          </>
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
  confirmedFields: Set<string>;
  setConfirmedFields: React.Dispatch<React.SetStateAction<Set<string>>>;
  run: (action: () => Promise<unknown>, success: string) => Promise<void>;
  runBackendStep: (step: WorkflowStep) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
}) {
  const { project, data, confirmedFields, setConfirmedFields, run, runBackendStep, confirmBackendStep } = props;
  return (
    <div className="section-stack">
      <div className="stat-row">
        <Stat value={materialSlots.filter(slot => slot.required).length} label="固定必填资料入口" />
        <Stat value={project.materials.length} label="已上传资料" />
        <Stat value={data.intakeRows.length} label="抽取字段" />
        <Stat value={confirmedFields.size} label="前端确认字段" />
      </div>
      <Panel title="资料入口" icon={<FileArchive size={16} />}>
        <div className="upload-strip">
          <button className="btn primary" disabled={project.materials.length === 0} onClick={() => run(async () => {
            await api.parseMaterials(project.id);
          }, "资料解析完成。")}>
            <ScanText size={15} />解析资料
          </button>
          <button className="btn" disabled={project.steps.materials.status !== "confirmed"} onClick={() => runBackendStep("intake")}>生成抽取表</button>
        </div>
        <div className="slot-grid">
          {materialSlots.map((slot, index) => {
            const materials = project.materials.filter(material => material.filename.startsWith(`${slot.id}__`));
            const slotStatus = materials.some(material => material.status === "parsed") ? "parsed" : materials.length ? "uploaded" : slot.required ? "pending" : "optional";
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
                      <span>{materials.length ? `${materials.length} 个文件，${slotStatus === "parsed" ? "已解析" : "待解析"}` : slot.required ? "必填资料入口" : "可选补充入口"}</span>
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
                  <button className="btn" onClick={() => setConfirmedFields(current => new Set(current).add(row.id))}>{confirmedFields.has(row.id) ? "已确认" : "确认"}</button>
                </div>
              ))}
            </div>
            <div className="actions end">
              <button className="btn primary" disabled={project.steps.intake.status !== "completed"} onClick={() => confirmBackendStep("intake")}>确认项目信息</button>
            </div>
          </>
        ) : (
          <EmptyPanelText text="暂无抽取结果。请先上传资料、解析资料，然后点击“生成抽取表”。" />
        )}
      </Panel>
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
  runBackendStep: (step: WorkflowStep) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
}) {
  const { project, data, tab, setTab, selectedPlans, setSelectedPlans, runBackendStep, confirmBackendStep } = props;
  const backendStep: WorkflowStep = tab === "matrix" ? "matrix" : "breakthrough";
  const rows = tab === "matrix" ? data.matrixPlans : data.breakthroughPlans;
  return (
    <div className="section-stack">
      <div className="bulk-bar">
        <div>
          <strong>{tab === "matrix" ? "内容矩阵整体规划" : "逐词击破六类规划"}</strong>
          <span>{rows.length ? `后台 Agent 已生成 ${rows.length} 条规划。` : "暂无规划结果。"}</span>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => runBackendStep(backendStep)}>生成{tab === "matrix" ? "内容矩阵" : "逐词击破"}</button>
          <button className="btn primary" disabled={project.steps[backendStep].status !== "completed"} onClick={() => confirmBackendStep(backendStep)}>确认当前规划</button>
        </div>
      </div>
      <div className="tabs">
        <button className={tab === "matrix" ? "active" : ""} onClick={() => setTab("matrix")}>内容矩阵</button>
        <button className={tab === "breakthrough" ? "active" : ""} onClick={() => setTab("breakthrough")}>逐词击破</button>
      </div>
      {rows.length ? (
        <div className="keyword-groups">
          {Object.entries(groupBy(rows, "keyword")).map(([keyword, groupedRows]) => (
            <Panel key={keyword} title={keyword} icon={<Search size={16} />} aside={<Chip text={`${groupedRows.length} 条`} />}>
              <div className="plan-list">
                {groupedRows.map(item => (
                  <PlanRow key={item.id} item={item} selected={selectedPlans.has(item.id)} onToggle={() => setSelectedPlans(current => toggleSet(current, item.id))} />
                ))}
              </div>
            </Panel>
          ))}
        </div>
      ) : (
        <Panel title="暂无规划结果" icon={<Route size={16} />}>
          <EmptyPanelText text={`点击“生成${tab === "matrix" ? "内容矩阵" : "逐词击破"}”后，这里会展示后台 Agent 的真实输出。`} />
        </Panel>
      )}
    </div>
  );
}

function BriefView(props: {
  project: Project;
  items: ContentItem[];
  selectedBriefs: Set<string>;
  setSelectedBriefs: React.Dispatch<React.SetStateAction<Set<string>>>;
  runBackendStep: (step: WorkflowStep) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
}) {
  const { project, items, selectedBriefs, setSelectedBriefs, runBackendStep, confirmBackendStep } = props;
  return (
    <div className="drawer-layout">
      <Panel title="Brief 分组审核" icon={<BadgeAlert size={16} />} aside={<Chip text={`已生成 ${items.length} 篇 Brief`} type={items.length ? "brand" : "warn"} />}>
        <div className="actions block-actions">
          <button className="btn" onClick={() => runBackendStep("brief")}>生成 Brief</button>
          <button className="btn primary" disabled={project.steps.brief.status !== "completed"} onClick={() => confirmBackendStep("brief")}>确认 Brief</button>
        </div>
        {items.length ? (
          <div className="review-list">
            {items.map(item => (
              <article className="review-card" key={item.id}>
                <div className="review-card-head">
                  <input type="checkbox" checked={selectedBriefs.has(item.id)} onChange={() => setSelectedBriefs(current => toggleSet(current, item.id))} />
                  <div><h3>{item.title}</h3><div className="chips"><Chip text={item.keyword} type="brand" /><Chip text={item.type} /><Chip text={item.status} /></div></div>
                  <button className="btn"><BookOpen size={15} />查阅文档</button>
                </div>
                <p>{item.role}</p>
              </article>
            ))}
          </div>
        ) : <EmptyPanelText text="暂无 Brief。请先确认规划，再生成 Brief。" />}
      </Panel>
      <Panel title="Brief 审核重点" icon={<CircleAlert size={16} />}>
        <Activity icon={<CheckCircle2 size={16} />} title="来自后台输出" desc="这里不再展示示例 Brief，只展示 Agent 生成结果。" />
        <Activity icon={<CircleAlert size={16} />} title="确认后再进入正文" desc="后端状态机会阻止跳过确认直接进入下一步。" />
      </Panel>
    </div>
  );
}

function ArticleView(props: {
  project: Project;
  items: ContentItem[];
  selectedArticles: Set<string>;
  setSelectedArticles: React.Dispatch<React.SetStateAction<Set<string>>>;
  runBackendStep: (step: WorkflowStep) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
}) {
  const { project, items, selectedArticles, setSelectedArticles, runBackendStep, confirmBackendStep } = props;
  return (
    <div className="section-stack">
      <div className="bulk-bar">
        <div><strong>正文折叠审核</strong><span>{items.length ? `已生成 ${items.length} 篇正文。` : "暂无正文结果。"}</span></div>
        <div className="actions">
          <button className="btn" onClick={() => runBackendStep("article")}>生成正文</button>
          <button className="btn primary" disabled={project.steps.article.status !== "completed"} onClick={() => confirmBackendStep("article")}>正文定稿</button>
        </div>
      </div>
      {items.length ? (
        <div className="article-list">
          {items.map(item => (
            <details className="article-collapse" key={item.id} open>
              <summary>
                <input type="checkbox" checked={selectedArticles.has(item.id)} onChange={event => {
                  event.preventDefault();
                  setSelectedArticles(current => toggleSet(current, item.id));
                }} />
                <div><h3>{item.title}</h3><div className="chips"><Chip text={item.keyword} type="brand" /><Chip text={item.type} /><Chip text={item.status} /></div></div>
                <button className="btn"><RefreshCw size={15} />单篇改写</button>
              </summary>
              <pre className="preview">{item.markdown || JSON.stringify(item.raw, null, 2)}</pre>
            </details>
          ))}
        </div>
      ) : (
        <Panel title="暂无正文" icon={<Newspaper size={16} />}>
          <EmptyPanelText text="请先确认 Brief，然后点击“生成正文”。" />
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
              <div><h3>{item.title}</h3><div className="chips"><Chip text={item.keyword} type="brand" /><Chip text={item.status} /><Chip text={item.used} /></div></div>
              <button className="btn">确认</button>
            </div>
            <p>{item.markdown || item.role}</p>
          </article>
        )) : <EmptyPanelText text="暂无改写稿。请先生成正文，再运行改写。" />}
      </Panel>
    </div>
  );
}

function LibraryView({ project, data, group, setGroup, outputs, logs }: { project: Project; data: DerivedData; group: "keyword" | "type"; setGroup: (group: "keyword" | "type") => void; outputs: string[]; logs: string }) {
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
              <div><h3>{item.title}</h3><p>{item.markdown || item.role}</p><div className="chips"><Chip text={item.keyword} type="brand" /><Chip text={item.type} /><Chip text={item.status} /></div></div>
              <button className="btn"><BookOpen size={15} />查阅</button>
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

function PlanRow({ item, selected, onToggle }: { item: ContentItem; selected: boolean; onToggle: () => void }) {
  return (
    <article className={`plan-row ${selected ? "selected" : ""}`}>
      <input type="checkbox" checked={selected} onChange={onToggle} />
      <div>
        <h3>{item.type}｜{item.title}</h3>
        <p>{item.role}</p>
        <div className="chips"><Chip text={item.keyword} type="brand" /><Chip text={item.channel} /><Chip text={item.status} /><Chip text={item.used} /></div>
      </div>
      <button className="btn">调整</button>
    </article>
  );
}

function Panel({ title, icon, children, aside }: { title: string; icon: React.ReactNode; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-head"><div className="panel-title">{icon}{title}</div>{aside}</div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

function Activity({ icon, title, desc, action }: { icon: React.ReactNode; title: string; desc: string; action?: React.ReactNode }) {
  return <div className="activity-item">{icon}<div><strong>{title}</strong><span>{desc}</span></div>{action}</div>;
}

function Stat({ value, label }: { value: number; label: string }) {
  return <div className="stat"><strong>{value}</strong><span>{label}</span></div>;
}

function Chip({ text, type = "" }: { text: string | number; type?: string }) {
  return <span className={`chip ${type}`}>{text}</span>;
}

function Status({ status }: { status: string }) {
  const type = status.includes("confirmed") || status.includes("已") || status.includes("parsed") ? "good" : status.includes("failed") ? "danger" : status.includes("running") || status.includes("completed") ? "warn" : "";
  return <Chip text={status} type={type} />;
}

function EmptyState() {
  return <div className="panel empty">请先创建或选择一个项目。</div>;
}

function EmptyPanelText({ text }: { text: string }) {
  return <p className="muted">{text}</p>;
}

interface DerivedData {
  intakeRows: Array<{ id: string; field: string; value: string; source: string; confidence: string; status: string }>;
  matrixPlans: ContentItem[];
  breakthroughPlans: ContentItem[];
  plans: ContentItem[];
  briefs: ContentItem[];
  articles: ContentItem[];
  rewrites: ContentItem[];
  archiveCount: number;
}

function emptyDerivedData(): DerivedData {
  return { intakeRows: [], matrixPlans: [], breakthroughPlans: [], plans: [], briefs: [], articles: [], rewrites: [], archiveCount: 0 };
}

function deriveProjectData(project: Project): DerivedData {
  const matrixPlans = normalizeItems(project.steps.matrix.output, "matrix");
  const breakthroughPlans = normalizeItems(project.steps.breakthrough.output, "breakthrough");
  const briefs = normalizeItems(project.steps.brief.output, "brief");
  const articles = normalizeItems(project.steps.article.output, "article");
  const rewrites = normalizeItems(project.steps.rewrite.output, "rewrite");
  return {
    intakeRows: normalizeIntake(project.steps.intake.output),
    matrixPlans,
    breakthroughPlans,
    plans: [...matrixPlans, ...breakthroughPlans],
    briefs,
    articles,
    rewrites,
    archiveCount: [...articles, ...rewrites].filter(item => item.status.includes("已") || item.status === "completed").length
  };
}

function normalizeIntake(output: AnyRecord): DerivedData["intakeRows"] {
  const rows = extractArray(output);
  return rows.map((row, index) => ({
    id: readString(row, ["id", "字段", "field"], `field-${index}`),
    field: readString(row, ["field", "字段", "name"], `字段 ${index + 1}`),
    value: readString(row, ["value", "推断值", "inferred_value", "answer"], JSON.stringify(row)),
    source: readString(row, ["source", "来源/依据", "依据", "basis"], "未标注"),
    confidence: readString(row, ["confidence", "置信度"], "未标注"),
    status: readString(row, ["status", "状态"], "待确认")
  }));
}

function normalizeItems(output: AnyRecord, step: string): ContentItem[] {
  const rows = extractArray(output);
  if (!rows.length && typeof output.markdown === "string") {
    rows.push(output);
  }
  return rows.map((row, index) => ({
    id: readString(row, ["id"], `${step}-${index}`),
    keyword: readString(row, ["keyword", "target_keyword", "目标关键词", "主攻关键词"], "未标注关键词"),
    type: readString(row, ["type", "article_type", "文章类型"], stepLabel(step)),
    title: readString(row, ["title", "suggested_title", "建议标题", "文章标题"], readString(output, ["title"], stepLabel(step))),
    role: readString(row, ["role", "summary", "主要作用", "brief", "description"], readString(output, ["summary"], "后台 Agent 已生成结果。")),
    channel: readString(row, ["channel", "发布渠道"], "未标注渠道"),
    status: readString(row, ["status", "状态"], output.status ? String(output.status) : "completed"),
    used: readString(row, ["used", "使用状态"], "未使用"),
    markdown: readString(row, ["markdown", "body", "正文"], readString(output, ["markdown"], "")),
    raw: row
  }));
}

function extractArray(output: AnyRecord): AnyRecord[] {
  for (const key of ["items", "rows", "fields", "plans", "articles", "briefs", "data"]) {
    const value = output[key];
    if (Array.isArray(value)) return value.filter(isRecord);
  }
  return [];
}

function readString(row: AnyRecord, keys: string[], fallback = ""): string {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number") return String(value);
  }
  return fallback;
}

function isRecord(value: unknown): value is AnyRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stepLabel(step: string): string {
  const labels: Record<string, string> = {
    matrix: "内容矩阵",
    breakthrough: "逐词击破",
    brief: "Brief",
    article: "正文",
    rewrite: "改写稿"
  };
  return labels[step] || step;
}

function groupBy<T>(rows: T[], key: keyof T): Record<string, T[]> {
  return rows.reduce<Record<string, T[]>>((acc, row) => {
    const value = String(row[key] || "未分组");
    acc[value] ||= [];
    acc[value].push(row);
    return acc;
  }, {});
}

function toggleSet(current: Set<string>, id: string): Set<string> {
  const next = new Set(current);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
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

createRoot(document.getElementById("root")!).render(<App />);
