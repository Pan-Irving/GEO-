const API_BASE = import.meta.env.VITE_PUBLISHING_API_BASE || "";

export type Role = "admin" | "manager" | "employee";

export interface User {
  id: string;
  username: string;
  display_name: string;
  role: Role;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProjectSummary {
  project_id: string;
  project_name: string;
  article_count: number;
  synced_at: string;
}

export interface WritingProject {
  id: string;
  name: string;
  updated_at: string;
  synced: boolean;
}

export interface ArticleSnapshot {
  article_id: string;
  project_id: string;
  project_name: string;
  intent_group_id?: string;
  intent_group: string;
  keyword: string;
  article_type: string;
  title: string;
  markdown: string;
  content_hash: string;
  article_audited_at: string;
  writing_updated_at: string;
  synced_at: string;
  inventory_status?: string;
  published_count?: number;
  purchasing_count?: number;
  records?: PublicationRecord[];
}

export interface MatrixCell {
  intent_group_id?: string;
  intent_group: string;
  keyword: string;
  article_type: string;
  total: number;
  available: number;
  published: number;
  purchasing: number;
}

export interface InventoryResponse {
  project_id: string;
  articles: ArticleSnapshot[];
  records: PublicationRecord[];
  matrix: MatrixCell[];
  totals: { articles: number; available: number; published: number; purchasing: number };
}

export interface PublicationRecord {
  id: string;
  article_id: string;
  employee_id: string;
  employee_name?: string;
  channel_type: string;
  media_kind: string;
  media_category: string;
  media_name: string;
  target_ai_platforms: string[];
  reference_url: string;
  publish_url: string;
  published_at: string;
  order_id: string;
  actual_cost: number;
  order_status: string;
  note: string;
  article_content_hash: string;
  created_at: string;
  keyword?: string;
  intent_group?: string;
  article_type?: string;
  title?: string;
}

export interface Assignment {
  id: string;
  user_id: string;
  username?: string;
  display_name?: string;
  project_id: string;
  keywords: string[];
  intent_group_ids?: string[];
  intent_groups?: string[];
  article_types: string[];
}

function authHeaders(): HeadersInit {
  const token = sessionStorage.getItem("publishing_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    ...init,
    headers: init.body instanceof FormData
      ? { ...authHeaders(), ...init.headers }
      : { "Content-Type": "application/json", ...authHeaders(), ...init.headers }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  login: (payload: { username: string; password: string }) =>
    request<{ token: string; user: User; expires_at: string }>("/api/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  me: () => request<{ user: User }>("/api/auth/me"),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  options: () => request<{ ai_platforms: string[]; self_media: string[]; web_categories: string[] }>("/api/meta/options"),
  projects: () => request<{ projects: ProjectSummary[] }>("/api/projects"),
  writingProjects: () => request<{ projects: WritingProject[] }>("/api/writing/projects"),
  inventory: (projectId: string) => request<InventoryResponse>(`/api/projects/${encodeURIComponent(projectId)}/inventory`),
  projectRecords: (projectId: string) => request<{ records: PublicationRecord[] }>(`/api/projects/${encodeURIComponent(projectId)}/records`),
  article: (articleId: string) => request<{ article: ArticleSnapshot }>(`/api/articles/${encodeURIComponent(articleId)}`),
  createSelf: (payload: Record<string, unknown>) =>
    request<{ record: PublicationRecord }>("/api/publications/self", { method: "POST", body: JSON.stringify(payload) }),
  createWeb: (payload: Record<string, unknown>) =>
    request<{ record: PublicationRecord }>("/api/publications/web", { method: "POST", body: JSON.stringify(payload) }),
  updatePublication: (recordId: string, payload: Record<string, unknown>) =>
    request<{ record: PublicationRecord }>(`/api/publications/${encodeURIComponent(recordId)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deletePublication: (recordId: string) =>
    request<{ deleted: boolean }>(`/api/publications/${encodeURIComponent(recordId)}`, { method: "DELETE" }),
  syncProject: (projectId: string) => request<{ sync: { created: number; updated: number; deactivated: number; total: number }; message: string }>(`/api/sync/projects/${encodeURIComponent(projectId)}`, { method: "POST" }),
  users: () => request<{ users: User[] }>("/api/admin/users"),
  createUser: (payload: Record<string, unknown>) =>
    request<{ user: User }>("/api/admin/users", { method: "POST", body: JSON.stringify(payload) }),
  updateUser: (userId: string, payload: Record<string, unknown>) =>
    request<{ user: User }>(`/api/admin/users/${encodeURIComponent(userId)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  assignments: () => request<{ assignments: Assignment[] }>("/api/admin/assignments"),
  createAssignment: (payload: Record<string, unknown>) =>
    request<{ assignment: Assignment }>("/api/admin/assignments", { method: "POST", body: JSON.stringify(payload) }),
  deleteAssignment: (assignmentId: string) => request<{ deleted: boolean }>(`/api/admin/assignments/${encodeURIComponent(assignmentId)}`, { method: "DELETE" })
};
