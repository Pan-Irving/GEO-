import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Archive,
  BookOpen,
  CheckCircle2,
  Download,
  FileText,
  FolderOpen,
  Loader2,
  Play,
  RefreshCw,
  Upload
} from "lucide-react";
import { api } from "./api/client";
import type { Project, WorkflowStep } from "./api/types";
import "./styles/app.css";

const steps: Array<{ id: WorkflowStep; title: string; desc: string }> = [
  { id: "materials", title: "资料", desc: "上传与解析" },
  { id: "intake", title: "信息抽取", desc: "字段、来源、置信度" },
  { id: "matrix", title: "内容矩阵", desc: "意图分组与规划" },
  { id: "breakthrough", title: "逐词击破", desc: "六类文章" },
  { id: "brief", title: "Brief", desc: "单篇执行文件" },
  { id: "article", title: "正文", desc: "Markdown 正文" },
  { id: "rewrite", title: "改写", desc: "复用与再发布" },
  { id: "archive", title: "归档", desc: "导出文件" }
];

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [activeStep, setActiveStep] = useState<WorkflowStep>("materials");
  const [projectName, setProjectName] = useState("GEO 内容项目");
  const [logs, setLogs] = useState("");
  const [outputs, setOutputs] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<{ model: string; skill_available: boolean } | null>(null);

  useEffect(() => {
    void refreshAll();
    void api.health().then(setHealth).catch(error => setMessage(error.message));
  }, []);

  useEffect(() => {
    if (!project) return;
    const timer = window.setInterval(() => void refreshProject(project.id), 2500);
    return () => window.clearInterval(timer);
  }, [project?.id]);

  const activeState = project?.steps[activeStep];
  const canRun = useMemo(() => {
    if (!project || activeStep === "materials" || activeStep === "archive") return false;
    const index = steps.findIndex(step => step.id === activeStep);
    const previous = steps[index - 1]?.id;
    return previous ? project.steps[previous].status === "confirmed" : false;
  }, [project, activeStep]);

  async function refreshAll() {
    const list = await api.listProjects();
    setProjects(list);
    if (list[0]) {
      setProject(list[0]);
      await refreshProject(list[0].id);
    }
  }

  async function refreshProject(projectId: string) {
    const next = await api.getProject(projectId);
    setProject(next);
    setProjects(current => current.map(item => (item.id === next.id ? next : item)));
    const [logResult, outputResult] = await Promise.all([api.getLogs(projectId), api.getOutputs(projectId)]);
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
      else await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="mark"><FileText size={18} /></span>
          <div>
            <strong>GEO 撰文 Agent</strong>
            <span>Python 后台 + Skill 工作流</span>
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
            <button onClick={() => run(async () => {
              const created = await api.createProject(projectName);
              setProject(created);
              setProjects([created, ...projects]);
            }, "项目已创建")}>新建</button>
          </div>
        </div>

        <nav className="steps">
          {steps.map((step, index) => {
            const state = project?.steps[step.id]?.status || "pending";
            return (
              <button key={step.id} className={`step ${activeStep === step.id ? "active" : ""} ${state}`} onClick={() => setActiveStep(step.id)}>
                <span>{state === "confirmed" ? <CheckCircle2 size={15} /> : index + 1}</span>
                <div><strong>{step.title}</strong><small>{step.desc}</small></div>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="main">
        <header className="topbar">
          <div><FolderOpen size={16} /> 项目空间 / GEO 内容生产 / <strong>{steps.find(step => step.id === activeStep)?.title}</strong></div>
          <span className="pill">{health ? `${health.model} / Skill ${health.skill_available ? "已识别" : "缺失"}` : "检查中"}</span>
        </header>

        <section className="hero">
          <div>
            <h1>{steps.find(step => step.id === activeStep)?.title}</h1>
            <p>后台 Agent 负责读取资料、加载 skill 规则、调用 OpenAI API 并写入输出文件；控制台只负责操作和确认。</p>
          </div>
          <div className="actions">
            {project && <a className="btn" href={`/api/projects/${project.id}/export/project.json`}><Download size={15} />导出 JSON</a>}
            {project && <a className="btn primary" href={`/api/projects/${project.id}/export/markdown.zip`}><Download size={15} />导出 Markdown</a>}
          </div>
        </section>

        {message && <div className="notice">{message}</div>}
        {!project ? <EmptyState /> : (
          <div className="layout">
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>{steps.find(step => step.id === activeStep)?.title}阶段</h2>
                  <p>状态：<Status status={activeState?.status || "pending"} /></p>
                </div>
                {busy && <Loader2 className="spin" size={20} />}
              </div>
              <div className="panel-body">
                {activeStep === "materials" ? (
                  <Materials project={project} busy={busy} run={run} refreshProject={refreshProject} />
                ) : activeStep === "archive" ? (
                  <ArchiveView outputs={outputs} />
                ) : (
                  <WorkflowStepView
                    project={project}
                    step={activeStep}
                    canRun={canRun}
                    busy={busy}
                    run={run}
                  />
                )}
              </div>
            </section>

            <aside className="panel side-panel">
              <div className="panel-head"><h2>Agent 日志</h2><button className="icon-btn" onClick={() => refreshProject(project.id)}><RefreshCw size={15} /></button></div>
              <pre className="logs">{logs || "暂无日志"}</pre>
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

function Materials({ project, busy, run, refreshProject }: {
  project: Project;
  busy: boolean;
  run: (action: () => Promise<unknown>, success: string) => Promise<void>;
  refreshProject: (projectId: string) => Promise<void>;
}) {
  const [files, setFiles] = useState<FileList | null>(null);
  return (
    <div className="stack">
      <label className="upload-box">
        <Upload size={22} />
        <span>选择 md / txt / json / csv / xlsx 资料</span>
        <input type="file" multiple onChange={event => setFiles(event.target.files)} />
      </label>
      <div className="actions">
        <button className="btn" disabled={!files || busy} onClick={() => run(async () => {
          if (files) await api.uploadMaterials(project.id, files);
          await refreshProject(project.id);
        }, "资料已上传")}>上传资料</button>
        <button className="btn primary" disabled={busy || project.materials.length === 0} onClick={() => run(async () => {
          await api.parseMaterials(project.id);
        }, "资料解析完成，materials 已确认")}>解析资料</button>
      </div>
      <div className="list">
        {project.materials.map(item => (
          <article key={item.id} className="list-item">
            <FileText size={17} />
            <div><strong>{item.filename}</strong><span>{Math.round(item.size / 1024)} KB</span></div>
            <Status status={item.status === "parsed" ? "confirmed" : item.status === "failed" ? "failed" : "pending"} />
          </article>
        ))}
      </div>
    </div>
  );
}

function WorkflowStepView({ project, step, canRun, busy, run }: {
  project: Project;
  step: WorkflowStep;
  canRun: boolean;
  busy: boolean;
  run: (action: () => Promise<unknown>, success: string) => Promise<void>;
}) {
  const state = project.steps[step];
  return (
    <div className="stack">
      <div className="actions">
        <button className="btn primary" disabled={!canRun || busy || state.status === "running"} onClick={() => run(async () => {
          await api.runStep(project.id, step, {});
        }, "任务已提交，后台 Agent 正在运行")}>
          <Play size={15} />运行本步骤
        </button>
        <button className="btn" disabled={busy || state.status !== "completed"} onClick={() => run(async () => {
          await api.confirmStep(project.id, step);
        }, "该步骤已确认")}>
          <CheckCircle2 size={15} />确认结果
        </button>
      </div>
      {state.error && <div className="error">{state.error}</div>}
      <ResultPreview output={state.output} />
    </div>
  );
}

function ResultPreview({ output }: { output: Record<string, unknown> }) {
  if (!output || Object.keys(output).length === 0) return <p className="muted">暂无输出。运行本步骤后，Agent 会把结果写入这里和输出目录。</p>;
  const markdown = typeof output.markdown === "string" ? output.markdown : null;
  return markdown ? <pre className="preview">{markdown}</pre> : <pre className="preview">{JSON.stringify(output, null, 2)}</pre>;
}

function ArchiveView({ outputs }: { outputs: string[] }) {
  return (
    <div className="stack">
      <div className="archive-title"><Archive size={18} /> 已生成文件</div>
      {outputs.length === 0 ? <p className="muted">暂无输出文件。</p> : outputs.map(file => <div className="file-row" key={file}><BookOpen size={15} />{file}</div>)}
    </div>
  );
}

function Status({ status }: { status: string }) {
  return <span className={`status ${status}`}>{status}</span>;
}

function EmptyState() {
  return <div className="panel empty">请先创建项目，然后上传资料。</div>;
}

createRoot(document.getElementById("root")!).render(<App />);
