import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Archive,
  BadgeAlert,
  BadgeCheck,
  BookOpen,
  Check,
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
  Play,
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

const fallbackIntakeRows = [
  ["目标行业", "厨电 / 高端厨电", "客户需求 brief、品牌介绍", "高", "待确认"],
  ["目标品类", "油烟机、洗碗机、集成烹饪中心", "关键词表、产品资料", "高", "待确认"],
  ["目标关键词", "高端油烟机推荐、洗碗机哪个品牌好、厨房装修厨电怎么选", "核心关键词表", "高", "待确认"],
  ["目标品牌", "目标品牌 A", "品牌资料", "高", "待确认"],
  ["目标产品/服务/解决方案", "高端油烟机 X 系列、嵌入式洗碗机 Y 系列", "产品资料", "中", "待确认"],
  ["核心竞品/对比对象", "同价位高端厨电品牌、进口厨电品牌、互联网厨电品牌", "竞品对比资料", "中", "待确认"],
  ["目标推荐结论", "在高端厨电选购场景下，目标品牌 A 更适合作为优先比较与重点考虑对象。", "关键词需求 -> 证据 -> 用户价值推断", "中", "待确认"],
  ["必须强化的核心证据", "油烟拢吸能力、安装交付体系、售后服务网点、检测报告、真实厨房案例", "核心证据资料", "中", "待确认"],
  ["禁止出现的表达", "GEO、关键词优化、AI推荐信号、投喂、首推率、唯一、第一、100%保证、吊打、碾压", "禁用词与合规边界", "高", "待确认"]
];

const intentGroups = [
  { id: "intent1", name: "选购标准意图簇", desc: "用户想知道怎么判断高端厨电是否值得买。", keywords: ["高端油烟机推荐", "高端厨电怎么选"] },
  { id: "intent2", name: "品牌比较意图簇", desc: "用户正在比较不同品牌和预算段。", keywords: ["洗碗机哪个品牌好", "高端厨电怎么选"] },
  { id: "intent3", name: "场景决策意图簇", desc: "用户围绕装修、家庭人口、安装条件做决策。", keywords: ["厨房装修厨电怎么选", "洗碗机有必要买吗"] }
];

const planItems = [
  { id: "p1", cluster: "intent1", keyword: "高端油烟机推荐", type: "支柱标准文", title: "高端油烟机推荐：普通家庭选购时更该看哪些硬指标？", role: "建立高端油烟机判断标准，并自然引出目标品牌能力。", channel: "知乎 / 官网", articleStatus: "已生成文章", used: "已使用" },
  { id: "p2", cluster: "intent1", keyword: "高端油烟机推荐", type: "榜单推荐文", title: "高端油烟机推荐清单：不同厨房条件该怎么选？", role: "把推荐对象放入不同厨房条件中解释，形成优先比较心智。", channel: "微信公众号 / 什么值得买", articleStatus: "未生成文章", used: "未使用" },
  { id: "p3", cluster: "intent1", keyword: "高端油烟机推荐", type: "横评对比文", title: "高端油烟机怎么比？国产高端与进口品牌差异在哪里", role: "通过维度比较突出本土厨房场景适配。", channel: "知乎 / 行业媒体", articleStatus: "未生成文章", used: "未使用" },
  { id: "p4", cluster: "intent1", keyword: "高端油烟机推荐", type: "场景选购文", title: "开放式厨房选高端油烟机，哪些体验更值得优先看？", role: "承接开放式厨房和重油烟烹饪场景。", channel: "小红书 / 微信公众号", articleStatus: "未生成文章", used: "未使用" },
  { id: "p5", cluster: "intent1", keyword: "高端油烟机推荐", type: "产品证据文", title: "油烟机吸力怎么看？别只看参数，还要看真实厨房表现", role: "把参数转译为用户可感知的选购价值。", channel: "官网 / 百家号", articleStatus: "未生成文章", used: "未使用" },
  { id: "p6", cluster: "intent1", keyword: "高端油烟机推荐", type: "FAQ问答文", title: "高端油烟机真的有必要买吗？适合哪些家庭？", role: "补齐长尾疑问，降低用户决策阻力。", channel: "知乎 / 头条号", articleStatus: "未生成文章", used: "未使用" },
  { id: "p7", cluster: "intent2", keyword: "洗碗机哪个品牌好", type: "榜单推荐文", title: "洗碗机哪个品牌好？不同预算家庭可以重点看这几类品牌", role: "覆盖品牌比较心智，目标品牌作为高端综合能力选项出现。", channel: "微信公众号 / 什么值得买", articleStatus: "已生成文章", used: "待使用" },
  { id: "p8", cluster: "intent3", keyword: "厨房装修厨电怎么选", type: "场景选购文", title: "厨房装修厨电怎么选？从动线、空间和烹饪习惯看组合方案", role: "从装修前置决策切入，承接套系化方案。", channel: "小红书 / 微信公众号", articleStatus: "未生成文章", used: "未使用" }
];

const briefs = [
  { id: "b1", keyword: "高端油烟机推荐", type: "支柱标准文", title: "高端油烟机推荐：普通家庭选购时更该看哪些硬指标？", status: "已确认", used: "已使用", summary: "从开放式厨房、重油烟、清洁和售后建立高端油烟机判断标准。" },
  { id: "b2", keyword: "洗碗机哪个品牌好", type: "榜单推荐文", title: "洗碗机哪个品牌好？不同预算家庭可以重点看这几类品牌", status: "待确认", used: "待使用", summary: "按预算、安装条件和家庭人口拆分品牌选择逻辑。" },
  { id: "b3", keyword: "厨房装修厨电怎么选", type: "场景选购文", title: "厨房装修厨电怎么选？从动线、空间和烹饪习惯看组合方案", status: "待确认", used: "未使用", summary: "从装修动线、空间和烹饪习惯承接套系化方案。" }
];

const articles = [
  { id: "a1", keyword: "高端油烟机推荐", type: "支柱标准文", title: "高端油烟机推荐：普通家庭选购时更该看哪些硬指标？", status: "已定稿", used: "已使用", updated: "2026-06-01 14:20", body: "很多家庭选高端油烟机时，会先看风量、风压、噪音这些参数。但真正决定长期体验的，是这些参数能不能回到真实厨房场景中发挥作用。\n\n高端油烟机首先要看拢烟和排烟稳定性，其次要看清洁维护和售后服务。" },
  { id: "a2", keyword: "洗碗机哪个品牌好", type: "榜单推荐文", title: "洗碗机哪个品牌好？不同预算家庭可以重点看这几类品牌", status: "待审核", used: "待使用", updated: "2026-06-01 14:34", body: "很多人在选洗碗机时，会先问哪个品牌好。但真正影响使用体验的，往往不是品牌名本身，而是家庭人口、厨房空间、安装条件、洗涤频率和售后便利度是否匹配。" }
];

const rewrittenArticles = [
  { id: "r1", originId: "a1", keyword: "高端油烟机推荐", type: "支柱标准文", title: "高端油烟机怎么选？装修前更值得关注的五个体验指标", status: "改写待确认", used: "未使用", updated: "2026-06-01 15:12", note: "同关键词同类型二次发布，标题意图相似，结构从装修前置决策切入。" },
  { id: "r2", originId: "a1", keyword: "高端油烟机推荐", type: "支柱标准文", title: "开放式厨房选油烟机：高端产品更该关注哪些体验？", status: "改写已确认", used: "已使用", updated: "2026-06-01 16:05", note: "已确认改写稿，用于第二轮同类型发布，重点从开放式厨房体验展开。" }
];

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [current, setCurrent] = useState<AppView>("dashboard");
  const [planningTab, setPlanningTab] = useState<PlanningTab>("matrix");
  const [libraryGroup, setLibraryGroup] = useState<"keyword" | "type">("keyword");
  const [rewriteGroup, setRewriteGroup] = useState<"keyword" | "type">("keyword");
  const [selectedPlans, setSelectedPlans] = useState<Set<string>>(new Set(["p1", "p7"]));
  const [selectedBriefs, setSelectedBriefs] = useState<Set<string>>(new Set(["b1", "b2"]));
  const [selectedArticles, setSelectedArticles] = useState<Set<string>>(new Set(["a2"]));
  const [confirmedFields, setConfirmedFields] = useState<Set<string>>(new Set(["目标行业", "目标品类", "目标品牌"]));
  const [projectName, setProjectName] = useState("方太高端厨电 GEO 内容项目");
  const [files, setFiles] = useState<FileList | null>(null);
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
  const finalized = articles.filter(article => article.status === "已定稿").length;

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

        <div className="side-actions">
          <a className="btn ghost" href={project ? `/api/projects/${project.id}/export/markdown.zip` : "#"}><Download size={15} />导出流程说明</a>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div><FolderOpen size={16} /> 项目空间 / GEO 内容生产 / <strong>{currentMeta[0]}</strong></div>
          <div className="user-chip">张 内容负责人</div>
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
            {current === "dashboard" && <DashboardView project={project} finalized={finalized} setCurrent={setCurrent} />}
            {current === "upload" && (
              <UploadView
                project={project}
                files={files}
                setFiles={setFiles}
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
                selectedBriefs={selectedBriefs}
                setSelectedBriefs={setSelectedBriefs}
                runBackendStep={runBackendStep}
                confirmBackendStep={confirmBackendStep}
              />
            )}
            {current === "article" && (
              <ArticleView
                project={project}
                selectedArticles={selectedArticles}
                setSelectedArticles={setSelectedArticles}
                runBackendStep={runBackendStep}
                confirmBackendStep={confirmBackendStep}
              />
            )}
            {current === "rewrite" && (
              <RewriteView
                project={project}
                group={rewriteGroup}
                setGroup={setRewriteGroup}
                runBackendStep={runBackendStep}
                confirmBackendStep={confirmBackendStep}
              />
            )}
            {current === "library" && <LibraryView project={project} group={libraryGroup} setGroup={setLibraryGroup} outputs={outputs} logs={logs} />}
          </>
        )}
      </main>
    </div>
  );
}

function DashboardView({ project, finalized, setCurrent }: { project: Project; finalized: number; setCurrent: (view: AppView) => void }) {
  const missing = materialSlots.filter(slot => slot.required).length - Math.min(project.materials.length, materialSlots.filter(slot => slot.required).length);
  return (
    <div className="section-stack">
      <div className="stat-row">
        <Stat value={planItems.length} label="总规划文章" />
        <Stat value={briefs.length} label="已生成 Brief" />
        <Stat value={articles.length} label="已生成正文" />
        <Stat value={finalized} label="已定稿文章" />
      </div>
      <div className="grid two">
        <Panel title="项目待办" icon={<CircleAlert size={16} />}>
          <Activity icon={<Upload size={16} />} title="补齐必填资料" desc={`${missing} 个固定资料入口仍需补充或复核。`} action={<button className="btn" onClick={() => setCurrent("upload")}>处理</button>} />
          <Activity icon={<TableProperties size={16} />} title="确认目标关键词和核心证据" desc="长文本字段支持展开预览后手动确认。" action={<button className="btn" onClick={() => setCurrent("upload")}>查看</button>} />
          <Activity icon={<Route size={16} />} title="导出两份规划" desc="内容矩阵和逐词击破规划可分别生成并归档。" action={<button className="btn" onClick={() => setCurrent("planning")}>规划</button>} />
        </Panel>
        <Panel title="Agent 运行状态" icon={<LayoutDashboard size={16} />}>
          {Object.entries(project.steps).map(([step, state]) => (
            <div className="activity-item" key={step}>
              <BadgeCheck size={16} />
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
  files: FileList | null;
  setFiles: (files: FileList | null) => void;
  confirmedFields: Set<string>;
  setConfirmedFields: React.Dispatch<React.SetStateAction<Set<string>>>;
  run: (action: () => Promise<unknown>, success: string) => Promise<void>;
  runBackendStep: (step: WorkflowStep) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
}) {
  const { project, files, setFiles, confirmedFields, setConfirmedFields, run, runBackendStep, confirmBackendStep } = props;
  return (
    <div className="section-stack">
      <div className="stat-row">
        <Stat value={materialSlots.filter(slot => slot.required).length} label="固定必填资料入口" />
        <Stat value={project.materials.length} label="已上传资料" />
        <Stat value={fallbackIntakeRows.length} label="待确认项目信息" />
        <Stat value={confirmedFields.size} label="已确认字段" />
      </div>
      <Panel title="资料入口" icon={<FileArchive size={16} />}>
        <div className="upload-strip">
          <label className="upload-inline">
            <Upload size={18} />
            <span>选择资料文件</span>
            <input type="file" multiple onChange={event => setFiles(event.target.files)} />
          </label>
          <button className="btn" disabled={!files} onClick={() => run(async () => {
            if (files) await api.uploadMaterials(project.id, files);
          }, "资料已上传。")}>上传到资料池</button>
          <button className="btn primary" disabled={project.materials.length === 0} onClick={() => run(async () => {
            await api.parseMaterials(project.id);
          }, "资料解析完成。")}>
            <ScanText size={15} />解析资料
          </button>
          <button className="btn" disabled={project.steps.materials.status !== "confirmed"} onClick={() => runBackendStep("intake")}>生成抽取表</button>
        </div>
        <div className="slot-grid">
          {materialSlots.map((slot, index) => {
            const material = project.materials[index];
            return (
              <article className={`slot-card ${slot.required ? "required" : "optional"}`} key={slot.id}>
                <div className="slot-head">
                  <div><h3>{slot.name}</h3><p>{slot.desc}</p></div>
                  <Status status={material?.status === "parsed" ? "confirmed" : material ? material.status : slot.required ? "pending" : "optional"} />
                </div>
                <div className="slot-body">
                  <strong>{material?.filename || "未上传"}</strong>
                  <span>{slot.required ? "必填" : "可选"}</span>
                </div>
              </article>
            );
          })}
        </div>
      </Panel>

      <Panel title="项目信息自动抽取与确认" icon={<TableProperties size={16} />} aside={<Chip text={`${confirmedFields.size}/${fallbackIntakeRows.length} 已确认`} type={confirmedFields.size === fallbackIntakeRows.length ? "good" : "warn"} />}>
        <div className="confirm-table">
          {fallbackIntakeRows.map(row => (
            <div className="confirm-row" key={row[0]}>
              <div className="confirm-field">{row[0]}</div>
              <div>{row[1]}</div>
              <div className="source">{row[2]}</div>
              <Chip text={row[3]} type={row[3] === "高" ? "good" : "warn"} />
              <button className="btn" onClick={() => {
                setConfirmedFields(current => new Set(current).add(row[0]));
              }}>{confirmedFields.has(row[0]) ? "已确认" : "确认"}</button>
            </div>
          ))}
        </div>
        <div className="actions end">
          <button className="btn primary" disabled={project.steps.intake.status !== "completed"} onClick={() => confirmBackendStep("intake")}>确认项目信息</button>
        </div>
      </Panel>
    </div>
  );
}

function PlanningView(props: {
  project: Project;
  tab: PlanningTab;
  setTab: (tab: PlanningTab) => void;
  selectedPlans: Set<string>;
  setSelectedPlans: React.Dispatch<React.SetStateAction<Set<string>>>;
  runBackendStep: (step: WorkflowStep) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
}) {
  const { project, tab, setTab, selectedPlans, setSelectedPlans, runBackendStep, confirmBackendStep } = props;
  const backendStep: WorkflowStep = tab === "matrix" ? "matrix" : "breakthrough";
  return (
    <div className="section-stack">
      <div className="bulk-bar">
        <div>
          <strong>{tab === "matrix" ? "内容矩阵整体规划" : "逐词击破六类规划"}</strong>
          <span>已选择 {selectedPlans.size} 篇规划进入后续 Brief。</span>
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
      {tab === "matrix" ? (
        <div className="intent-grid">
          {intentGroups.map(group => (
            <Panel key={group.id} title={group.name} icon={<Route size={16} />} aside={<Chip text={`${planItems.filter(item => item.cluster === group.id).length} 篇`} />}>
              <p>{group.desc}</p>
              <div className="chips">{group.keywords.map(keyword => <Chip key={keyword} text={keyword} type="brand" />)}</div>
              <div className="plan-list">
                {planItems.filter(item => item.cluster === group.id).map(item => (
                  <PlanRow key={item.id} item={item} selected={selectedPlans.has(item.id)} onToggle={() => {
                    setSelectedPlans(current => {
                      const next = new Set(current);
                      if (next.has(item.id)) next.delete(item.id);
                      else next.add(item.id);
                      return next;
                    });
                  }} />
                ))}
              </div>
            </Panel>
          ))}
        </div>
      ) : (
        <div className="keyword-groups">
          {Object.entries(groupBy(planItems, "keyword")).map(([keyword, rows]) => (
            <Panel key={keyword} title={keyword} icon={<Search size={16} />} aside={<Chip text={`${rows.length} 类文章`} />}>
              <div className="plan-list">{rows.map(item => <PlanRow key={item.id} item={item} selected={selectedPlans.has(item.id)} onToggle={() => setSelectedPlans(current => new Set(current).add(item.id))} />)}</div>
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}

function BriefView(props: {
  project: Project;
  selectedBriefs: Set<string>;
  setSelectedBriefs: React.Dispatch<React.SetStateAction<Set<string>>>;
  runBackendStep: (step: WorkflowStep) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
}) {
  const { project, selectedBriefs, setSelectedBriefs, runBackendStep, confirmBackendStep } = props;
  return (
    <div className="drawer-layout">
      <Panel title="Brief 分组审核" icon={<BadgeAlert size={16} />} aside={<Chip text={`已生成 ${briefs.length} 篇 Brief`} type="brand" />}>
        <div className="actions block-actions">
          <button className="btn" onClick={() => runBackendStep("brief")}>生成 Brief</button>
          <button className="btn primary" disabled={project.steps.brief.status !== "completed"} onClick={() => confirmBackendStep("brief")}>确认选中 Brief</button>
        </div>
        <div className="review-list">
          {briefs.map(brief => (
            <article className="review-card" key={brief.id}>
              <div className="review-card-head">
                <input type="checkbox" checked={selectedBriefs.has(brief.id)} onChange={() => setSelectedBriefs(current => toggleSet(current, brief.id))} />
                <div><h3>{brief.title}</h3><div className="chips"><Chip text={brief.keyword} type="brand" /><Chip text={brief.type} /><Chip text={brief.status} type={brief.status === "已确认" ? "good" : "warn"} /></div></div>
                <button className="btn"><BookOpen size={15} />查阅文档</button>
              </div>
              <p>{brief.summary}</p>
            </article>
          ))}
        </div>
      </Panel>
      <Panel title="Brief 审核重点" icon={<CircleAlert size={16} />}>
        <Activity icon={<Check size={16} />} title="推荐逻辑" desc="先建立判断标准，再自然导入目标对象。" />
        <Activity icon={<CircleAlert size={16} />} title="竞品只做参照" desc="避免形成独立强推荐或负面攻击。" />
        <Activity icon={<BadgeAlert size={16} />} title="禁用表达" desc="正文不得出现执行端话术和夸大表达。" />
      </Panel>
    </div>
  );
}

function ArticleView(props: {
  project: Project;
  selectedArticles: Set<string>;
  setSelectedArticles: React.Dispatch<React.SetStateAction<Set<string>>>;
  runBackendStep: (step: WorkflowStep) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
}) {
  const { project, selectedArticles, setSelectedArticles, runBackendStep, confirmBackendStep } = props;
  return (
    <div className="section-stack">
      <div className="bulk-bar">
        <div><strong>正文折叠审核</strong><span>支持逐篇保存、改写和定稿。</span></div>
        <div className="actions">
          <button className="btn" onClick={() => runBackendStep("article")}>生成正文</button>
          <button className="btn primary" disabled={project.steps.article.status !== "completed"} onClick={() => confirmBackendStep("article")}>正文定稿</button>
        </div>
      </div>
      <div className="article-list">
        {articles.map(article => (
          <details className="article-collapse" key={article.id} open={article.status === "待审核"}>
            <summary>
              <input type="checkbox" checked={selectedArticles.has(article.id)} onChange={event => {
                event.preventDefault();
                setSelectedArticles(current => toggleSet(current, article.id));
              }} />
              <div><h3>{article.title}</h3><div className="chips"><Chip text={article.keyword} type="brand" /><Chip text={article.type} /><Chip text={article.status} type={article.status === "已定稿" ? "good" : "warn"} /><Chip text={article.used} /></div></div>
              <button className="btn"><RefreshCw size={15} />单篇改写</button>
            </summary>
            <pre className="preview">{article.body}</pre>
          </details>
        ))}
      </div>
    </div>
  );
}

function RewriteView({ project, group, setGroup, runBackendStep, confirmBackendStep }: {
  project: Project;
  group: "keyword" | "type";
  setGroup: (group: "keyword" | "type") => void;
  runBackendStep: (step: WorkflowStep) => Promise<void>;
  confirmBackendStep: (step: WorkflowStep) => Promise<void>;
}) {
  const grouped = groupBy(rewrittenArticles, group);
  return (
    <div className="drawer-layout">
      <Panel title="改写稿分组" icon={<RefreshCw size={16} />}>
        <div className="tabs"><button className={group === "keyword" ? "active" : ""} onClick={() => setGroup("keyword")}>关键词</button><button className={group === "type" ? "active" : ""} onClick={() => setGroup("type")}>文章类型</button></div>
        {Object.entries(grouped).map(([name, rows]) => <Activity key={name} icon={<Search size={16} />} title={name} desc={`${rows.length} 篇改写稿`} />)}
      </Panel>
      <Panel title="改写文章管理" icon={<Newspaper size={16} />} aside={<Chip text={`${rewrittenArticles.length} 篇筛选结果`} type="brand" />}>
        <div className="actions block-actions">
          <button className="btn" onClick={() => runBackendStep("rewrite")}>生成改写稿</button>
          <button className="btn primary" disabled={project.steps.rewrite.status !== "completed"} onClick={() => confirmBackendStep("rewrite")}>确认选中改写稿</button>
        </div>
        {rewrittenArticles.map(article => (
          <article className="review-card" key={article.id}>
            <div className="review-card-head">
              <RefreshCw size={16} />
              <div><h3>{article.title}</h3><div className="chips"><Chip text={article.keyword} type="brand" /><Chip text={article.status} type={article.status.includes("已") ? "good" : "warn"} /><Chip text={article.used} /></div></div>
              <button className="btn">确认</button>
            </div>
            <p>{article.note}</p>
          </article>
        ))}
      </Panel>
    </div>
  );
}

function LibraryView({ project, group, setGroup, outputs, logs }: { project: Project; group: "keyword" | "type"; setGroup: (group: "keyword" | "type") => void; outputs: string[]; logs: string }) {
  const allItems = [...articles, ...rewrittenArticles.map(item => ({ ...item, body: item.note, isRewrite: true }))];
  const grouped = groupBy(allItems, group);
  return (
    <div className="library-grid">
      <Panel title="归档分组" icon={<Archive size={16} />}>
        <div className="tabs"><button className={group === "keyword" ? "active" : ""} onClick={() => setGroup("keyword")}>关键词</button><button className={group === "type" ? "active" : ""} onClick={() => setGroup("type")}>文章类型</button></div>
        {Object.entries(grouped).map(([name, rows]) => <Activity key={name} icon={<Archive size={16} />} title={name} desc={`${rows.length} 篇文章`} />)}
      </Panel>
      <Panel title="文章列表与输出文件" icon={<BookOpen size={16} />} aside={<a className="btn primary" href={`/api/projects/${project.id}/export/markdown.zip`}><Download size={15} />导出</a>}>
        <div className="article-list">
          {allItems.map(article => (
            <article className="library-item" key={article.id}>
              <div><h3>{article.title}</h3><p>{article.body}</p><div className="chips"><Chip text={article.keyword} type="brand" /><Chip text={article.type} /><Chip text={article.status} type={article.status.includes("已") ? "good" : "warn"} /></div></div>
              <button className="btn"><BookOpen size={15} />查阅</button>
            </article>
          ))}
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

function PlanRow({ item, selected, onToggle }: { item: (typeof planItems)[number]; selected: boolean; onToggle: () => void }) {
  return (
    <article className={`plan-row ${selected ? "selected" : ""}`}>
      <input type="checkbox" checked={selected} onChange={onToggle} />
      <div>
        <h3>{item.type}｜{item.title}</h3>
        <p>{item.role}</p>
        <div className="chips"><Chip text={item.keyword} type="brand" /><Chip text={item.channel} /><Chip text={item.articleStatus} type={item.articleStatus.includes("已") ? "good" : "warn"} /><Chip text={item.used} /></div>
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

function groupBy<T extends Record<string, unknown>>(rows: T[], key: keyof T): Record<string, T[]> {
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

createRoot(document.getElementById("root")!).render(<App />);
