import type { ContentPlan, CustomSourcePayload, Project, WorkflowStep } from "./types";

const REQUEST_TIMEOUT_MS = 15 * 60 * 1000;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      ...init,
      signal: init?.signal || controller.signal,
      headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers }
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${response.status}`);
    }
    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求超时，请刷新状态后重试。");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function requestBlob(url: string, init?: RequestInit): Promise<Blob> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      ...init,
      signal: init?.signal || controller.signal
    });
    if (!response.ok) {
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed: ${response.status}`);
      }
      const text = await response.text().catch(() => "");
      throw new Error(text || `Request failed: ${response.status}`);
    }
    return response.blob();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求超时，请刷新状态后重试。");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
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
    request<{ job_id?: string; project: Project }>(`/api/projects/${projectId}/materials/parse`, { method: "POST" }),
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
  confirmBreakthroughKeywords: (projectId: string, keywords: string[]) =>
    request<{ project: Project }>(`/api/projects/${projectId}/planning/breakthrough-keywords`, {
      method: "POST",
      body: JSON.stringify({ keywords })
    }),
  createCustomSource: (projectId: string, payload: CustomSourcePayload) =>
    request<{ project: Project }>(`/api/projects/${projectId}/custom-sources`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateCustomSource: (projectId: string, sourceId: string, payload: CustomSourcePayload) =>
    request<{ project: Project }>(`/api/projects/${projectId}/custom-sources/${encodeURIComponent(sourceId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  deleteCustomSource: (projectId: string, sourceId: string) =>
    request<{ project: Project }>(`/api/projects/${projectId}/custom-sources/${encodeURIComponent(sourceId)}`, {
      method: "DELETE"
    }),
  updateItem: (projectId: string, step: WorkflowStep, itemId: string, payload: Record<string, unknown>) =>
    request<{ project: Project }>(`/api/projects/${projectId}/steps/${step}/items/${encodeURIComponent(itemId)}`, {
      method: "PATCH",
      body: JSON.stringify({ payload })
    }),
  getLogs: (projectId: string) => request<{ logs: string }>(`/api/projects/${projectId}/logs`),
  getOutputs: (projectId: string) => request<{ files: string[] }>(`/api/projects/${projectId}/outputs`),
  getContentPlan: (projectId: string) => request<ContentPlan>(`/api/projects/${projectId}/content-plan`),
  exportContentPlanPdf: (projectId: string) => requestBlob(`/api/projects/${projectId}/export/content-plan.pdf`)
};
