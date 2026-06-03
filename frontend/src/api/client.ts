import type { Project, WorkflowStep } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; model: string; skill_available: boolean }>("/api/agent/health"),
  listProjects: () => request<Project[]>("/api/projects"),
  createProject: (name: string) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name }) }),
  getProject: (projectId: string) => request<Project>(`/api/projects/${projectId}`),
  uploadMaterials: (projectId: string, files: FileList) => {
    const form = new FormData();
    Array.from(files).forEach(file => form.append("files", file));
    return request<{ materials: unknown[] }>(`/api/projects/${projectId}/materials`, { method: "POST", body: form });
  },
  parseMaterials: (projectId: string) =>
    request<{ project: Project }>(`/api/projects/${projectId}/materials/parse`, { method: "POST" }),
  runStep: (projectId: string, step: WorkflowStep, payload: Record<string, unknown>) =>
    request<{ job_id: string; project: Project }>(`/api/projects/${projectId}/run/${step}`, {
      method: "POST",
      body: JSON.stringify({ payload })
    }),
  confirmStep: (projectId: string, step: WorkflowStep, notes?: string) =>
    request<{ project: Project }>(`/api/projects/${projectId}/confirm/${step}`, {
      method: "POST",
      body: JSON.stringify({ notes })
    }),
  getLogs: (projectId: string) => request<{ logs: string }>(`/api/projects/${projectId}/logs`),
  getOutputs: (projectId: string) => request<{ files: string[] }>(`/api/projects/${projectId}/outputs`)
};
