export type WorkflowStep =
  | "materials"
  | "intake"
  | "matrix"
  | "demand_matrix"
  | "breakthrough"
  | "brief"
  | "article"
  | "archive";

export type StepStatus = "pending" | "running" | "completed" | "confirmed" | "failed";
export type ParseMode = "smart" | "text_only" | "full_ocr";

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
  sha256?: string | null;
  parsed_path?: string | null;
  status: "uploaded" | "parsed" | "failed";
  error?: string | null;
  parse_mode?: ParseMode | null;
  parser_version?: string | null;
  parse_source?: "fresh" | "cache" | "skipped_existing" | null;
  parsed_chars?: number;
  ocr_pages?: number;
  parsed_at?: string | null;
}

export interface Job {
  id: string;
  step: WorkflowStep;
  status: "queued" | "running" | "cancelling" | "cancelled" | "completed" | "failed";
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

export interface CustomSourceBatchPayload {
  titles: string[];
  type: string;
  brief_focus?: string;
  channel?: string;
  channels?: string[];
  raw?: Record<string, unknown>;
}

export interface MarkdownArticleImportMeta {
  filename: string;
  title: string;
  keyword: string;
  type: string;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  allowed_keywords?: string[];
  materials: Material[];
  custom_sources: CustomSource[];
  steps: Record<WorkflowStep, StepState>;
  jobs: Job[];
}

export interface PublishingUsageSummary {
  project_id: string;
  totals: {
    articles: number;
    available: number;
    published: number;
    purchasing: number;
  };
  matrix: Array<{
    keyword: string;
    article_type: string;
    total: number;
    available: number;
    published: number;
    purchasing: number;
  }>;
  articles: Array<{
    article_id: string;
    keyword: string;
    article_type: string;
    published_count: number;
    purchasing_count: number;
    inventory_status: string;
  }>;
}

export interface ContentPlan {
  schema_version: string;
  source?: string;
  project_id: string;
  project_name: string;
  generated_at: string;
  markdown_report?: string;
  summary: Record<string, unknown>;
  project: Record<string, unknown>;
  keyword_intent_groups: Array<Record<string, unknown>>;
  article_type_pool: Array<Record<string, unknown>>;
  first_round_plans: Array<Record<string, unknown>>;
  demand_variables?: unknown[];
  keyword_variable_mapping?: unknown[];
  content_theme_clusters?: unknown[];
  title_angle_pool?: unknown[];
  weekly_publishing_mix?: unknown[];
  monthly_publishing_mix?: unknown[];
  daily_supplement_pool?: unknown[];
  ai_retest_rules?: unknown[];
  anti_homogenization_requirements?: unknown[];
  shared_supporting_articles: unknown[];
  unified_recommendation_language: unknown[];
  evidence_gaps: unknown[];
  publishing_plan: unknown[];
  schedule: unknown[];
  brief_requirements: unknown[];
  final_execution_advice: string;
  warnings: unknown[];
  display_sections?: Array<{
    id: string;
    title: string;
    items: Array<{
      fields: Array<{
        label: string;
        value: string;
      }>;
    }>;
  }>;
}

export interface MatrixImportDraft {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | "applied";
  filename: string;
  stored_name: string;
  content_type?: string | null;
  size: number;
  source_path: string;
  created_at: string;
  updated_at: string;
  job_id?: string | null;
  parsed_chars?: number;
  stats?: Record<string, unknown>;
  warnings?: unknown[];
  output?: Record<string, unknown>;
  error?: string | null;
  applied_at?: string | null;
}
