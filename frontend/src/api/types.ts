export type WorkflowStep =
  | "materials"
  | "intake"
  | "matrix"
  | "breakthrough"
  | "brief"
  | "article"
  | "rewrite"
  | "archive";

export type StepStatus = "pending" | "running" | "completed" | "confirmed" | "failed";

export interface StepState {
  status: StepStatus;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  error?: string | null;
  confirmed_at?: string | null;
  updated_at: string;
}

export interface Material {
  id: string;
  filename: string;
  stored_name: string;
  content_type?: string | null;
  size: number;
  parsed_path?: string | null;
  status: "uploaded" | "parsed" | "failed";
  error?: string | null;
}

export interface Job {
  id: string;
  step: WorkflowStep;
  status: "queued" | "running" | "completed" | "failed";
  error?: string | null;
  total_count: number;
  completed_count: number;
  failed_count: number;
  skipped_count: number;
  current_item?: string | null;
  message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CustomSource {
  id: string;
  source_id: string;
  source_step: "custom";
  keyword: string;
  type: string;
  title: string;
  role: string;
  brief_focus: string;
  channel: string;
  channels: string[];
  status: "ready" | "completed";
  created_at: string;
  updated_at: string;
  raw: Record<string, unknown>;
}

export interface CustomSourcePayload {
  title: string;
  keyword?: string;
  type?: string;
  brief_focus?: string;
  channel?: string;
  channels?: string[];
  raw?: Record<string, unknown>;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  materials: Material[];
  custom_sources: CustomSource[];
  steps: Record<WorkflowStep, StepState>;
  jobs: Job[];
}
