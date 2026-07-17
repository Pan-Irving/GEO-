import type { ContentPlan, CustomSourceBatchPayload, CustomSourcePayload, IntentGroup, MarkdownArticleImportMeta, MatrixImportDraft, ParseMode, Project, PublishingUsageSummary, SkillCatalog, WorkflowStep } from "./types";

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

async function optionalPublishingRequest<T>(path: string): Promise<T | null> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(path, { signal: controller.signal });
    if (!response.ok) return null;
    return response.json() as Promise<T>;
  } catch {
    return null;
  } finally {
    window.clearTimeout(timeout);
  }
}

export const api = {
  health: () => request<{ status: string; model: string; writing_model?: string | null; planning_model?: string | null; skill_available: boolean; active_skill_name?: string; active_skill_id?: string; publishing_frontend_url: string }>("/api/agent/health"),
  getSkills: () => request<SkillCatalog>("/api/skills"),
  uploadSkillSlot: (articleType: string, stage: "brief" | "article", file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<SkillCatalog>(`/api/skills/slots/${encodeURIComponent(articleType)}/${stage}`, { method: "POST", body: form });
  },
  activateSkill: (articleType: string, stage: "brief" | "article", candidateId: string) => request<SkillCatalog>(`/api/skills/slots/${encodeURIComponent(articleType)}/${stage}/candidates/${encodeURIComponent(candidateId)}/activate`, { method: "POST" }),
  deleteSkill: (articleType: string, stage: "brief" | "article", candidateId: string) => request<SkillCatalog>(`/api/skills/slots/${encodeURIComponent(articleType)}/${stage}/candidates/${encodeURIComponent(candidateId)}`, { method: "DELETE" }),
  listProjects: () => request<Project[]>("/api/projects"),
  createProject: (name: string) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name }) }),
  deleteProject: (projectId: string) =>
    request<{ deleted: boolean; project_id: string }>(`/api/projects/${projectId}`, { method: "DELETE" }),
  getProject: (projectId: string) => request<Project>(`/api/projects/${projectId}`),
  listIntentGroups: (projectId: string) =>
    request<{ intent_groups: IntentGroup[] }>(`/api/projects/${projectId}/intent-groups`),
  rebuildIntentGroups: (projectId: string) =>
    request<{ project: Project }>(`/api/projects/${projectId}/intent-groups/rebuild-from-archive`, { method: "POST" }),
  createIntentGroup: (projectId: string, payload: Partial<Pick<IntentGroup, "name" | "aliases" | "keywords">>) =>
    request<{ project: Project }>(`/api/projects/${projectId}/intent-groups`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateIntentGroup: (projectId: string, groupId: string, payload: Partial<Pick<IntentGroup, "name" | "aliases" | "keywords">>) =>
    request<{ project: Project }>(`/api/projects/${projectId}/intent-groups/${encodeURIComponent(groupId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  mergeIntentGroup: (projectId: string, groupId: string, sourceGroupIds: string[]) =>
    request<{ project: Project }>(`/api/projects/${projectId}/intent-groups/${encodeURIComponent(groupId)}/merge`, {
      method: "POST",
      body: JSON.stringify({ source_group_ids: sourceGroupIds })
    }),
  uploadMaterials: (projectId: string, files: FileList) => {
    const form = new FormData();
    Array.from(files).forEach(file => form.append("files", file));
    return request<{ materials: unknown[] }>(`/api/projects/${projectId}/materials`, { method: "POST", body: form });
  },
  parseMaterials: (projectId: string, payload: { mode?: ParseMode; force?: boolean } = {}) =>
    request<{ job_id?: string; project: Project }>(`/api/projects/${projectId}/materials/parse`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  deleteMaterial: (projectId: string, materialId: string) =>
    request<{ project: Project }>(`/api/projects/${projectId}/materials/${encodeURIComponent(materialId)}`, { method: "DELETE" }),
  runStep: (projectId: string, step: WorkflowStep, payload: Record<string, unknown>) =>
    request<{ job_id: string; project: Project }>(`/api/projects/${projectId}/run/${step}`, {
      method: "POST",
      body: JSON.stringify({ payload })
    }),
  importMatrixPlan: (projectId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ job_id: string; draft_id: string; project: Project }>(`/api/projects/${projectId}/matrix/import-plan`, {
      method: "POST",
      body: form
    });
  },
  getMatrixImportPlan: (projectId: string, draftId: string) =>
    request<MatrixImportDraft>(`/api/projects/${projectId}/matrix/import-plan/${encodeURIComponent(draftId)}`),
  applyMatrixImportPlan: (projectId: string, draftId: string) =>
    request<{ project: Project; draft: MatrixImportDraft }>(`/api/projects/${projectId}/matrix/import-plan/${encodeURIComponent(draftId)}/apply`, {
      method: "POST",
      body: JSON.stringify({ overwrite: true })
    }),
  confirmStep: (projectId: string, step: WorkflowStep, notes?: string) =>
    request<{ project: Project }>(`/api/projects/${projectId}/confirm/${step}`, {
      method: "POST",
      body: JSON.stringify({ notes })
    }),
  createCustomSource: (projectId: string, payload: CustomSourcePayload) =>
    request<{ project: Project }>(`/api/projects/${projectId}/custom-sources`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  createCustomSources: (projectId: string, payload: CustomSourceBatchPayload) =>
    request<{ project: Project }>(`/api/projects/${projectId}/custom-sources/batch`, {
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
  importMarkdownArticles: (projectId: string, rows: Array<{ file: File; meta: MarkdownArticleImportMeta }>) => {
    const form = new FormData();
    rows.forEach(row => form.append("files", row.file));
    form.append("metadata", JSON.stringify(rows.map(row => row.meta)));
    return request<{ project: Project }>(`/api/projects/${projectId}/articles/import-md`, {
      method: "POST",
      body: form
    });
  },
  deleteArticle: (projectId: string, articleId: string) =>
    request<{ project: Project; publishing: { configured: boolean; deleted_records: number; deleted_articles: number } }>(
      `/api/projects/${projectId}/articles/${encodeURIComponent(articleId)}`,
      { method: "DELETE" }
    ),
  updateItem: (projectId: string, step: WorkflowStep, itemId: string, payload: Record<string, unknown>) =>
    request<{ project: Project }>(`/api/projects/${projectId}/steps/${step}/items/${encodeURIComponent(itemId)}`, {
      method: "PATCH",
      body: JSON.stringify({ payload })
    }),
  deleteStepItems: (projectId: string, step: WorkflowStep, ids: string[]) =>
    request<{ project: Project }>(`/api/projects/${projectId}/steps/${step}/items/delete`, {
      method: "POST",
      body: JSON.stringify({ ids })
    }),
  getLogs: (projectId: string) => request<{ logs: string }>(`/api/projects/${projectId}/logs`),
  cancelJob: (projectId: string, jobId: string) =>
    request<{ project: Project }>(`/api/projects/${projectId}/jobs/${jobId}/cancel`, { method: "POST" }),
  getOutputs: (projectId: string) => request<{ files: string[] }>(`/api/projects/${projectId}/outputs`),
  getContentPlan: (projectId: string, source = "matrix") =>
    request<ContentPlan>(`/api/projects/${projectId}/content-plan?source=${encodeURIComponent(source)}`),
  exportContentPlanPdf: (projectId: string, source = "matrix") =>
    requestBlob(`/api/projects/${projectId}/export/content-plan.pdf?source=${encodeURIComponent(source)}`),
  getPublishingUsageSummary: (projectId: string) =>
    optionalPublishingRequest<PublishingUsageSummary>(`/api/projects/${encodeURIComponent(projectId)}/publishing/usage-summary`)
};
