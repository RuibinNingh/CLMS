export type Language = "zh" | "en";
export interface Category {
  id: string;
  name: string;
  description: string;
  language_scope: Language | "all";
  sort_order: number;
  revision: number;
  archived_at: string | null;
}
export interface PageRef {
  page_id: string;
  rotation: number;
  asset_id?: string;
  asset_sha256?: string;
  source_page?: number;
  order?: number;
  width?: number;
  height?: number;
}
export interface Asset {
  id: string;
  sha256: string;
  mime: string;
  original_name: string;
  byte_size: number;
  page_count: number;
  created_at: string;
  pages: PageRef[];
}
export interface Rubric {
  max_score: number;
  criteria: string;
  aggregation: "none" | "sum";
  dimensions: { name: string; max_score: number }[];
}
export interface Prompt {
  id: string;
  title: string;
  language: Language;
  instructions: string;
  requirements: string;
  source_note: string;
  category_ids: string[];
  rubric: Rubric | null;
  materials: PageRef[];
  revision: number;
  created_at: string;
  attempts?: Attempt[];
  attempt_count?: number;
  latest_written_at?: string | null;
  status?: string;
}
export interface Attempt {
  id: string;
  prompt_id: string;
  prompt_snapshot: Prompt;
  snapshot_hash: string;
  written_at: string | null;
  duration_minutes: number | null;
  reflection: string;
  selected_version_id: string | null;
  revision: number;
  versions: Version[];
}
export interface Version {
  id: string;
  attempt_id: string;
  version_no: number;
  parent_version_id: string | null;
  manifest: PageRef[];
  manifest_hash: string;
  change_note: string;
  voided_at: string | null;
  created_at: string;
  evaluations: Evaluation[];
  status: "pending" | "evaluated";
  prompt_snapshot?: Prompt;
  prompt_snapshot_hash?: string;
  prompt_id?: string;
}
export type IssueKind = "error" | "improvement" | "uncertain";
export interface Issue {
  kind: IssueKind;
  dimension: string;
  location: { page_id: string; description: string; bbox: number[] | null };
  quote: string | null;
  reason: string;
  suggestion: string;
}
export interface EvaluationPayload {
  schema_version: number;
  version_id: string;
  expected_manifest_hash: string;
  expected_prompt_snapshot_hash: string;
  coverage: {
    reviewed_page_ids: string[];
    scope: "full" | "partial";
    limitations: string[];
  };
  summary: string;
  strengths: string[];
  score: {
    value: number;
    max_value: number;
    rubric_snapshot: Rubric;
    dimensions: { name: string; value: number; max_value: number }[];
  } | null;
  issues: Issue[];
  next_actions: string[];
  commentary_markdown: string;
  declared_model: string | null;
  compared_version_ids?: string[];
}
export interface Evaluation {
  id: string;
  version_id: string;
  payload: EvaluationPayload;
  source: string;
  created_at: string;
  supersedes_id: string | null;
  voided_at: string | null;
}
export type ReviewKind =
  | "category"
  | "prompt"
  | "submission"
  | "revision"
  | "evaluation"
  | "reflection";
export interface Review {
  id: string;
  kind: ReviewKind;
  source_actor: string;
  request_id: string;
  revision: number;
  original_payload: Record<string, unknown>;
  payload: Record<string, unknown>;
  original_digest: string;
  effective_digest: string;
  target_snapshot: Record<string, unknown>;
  status: string;
  result: Record<string, unknown> | null;
  created_at: string;
  revisions?: unknown[];
  decisions?: unknown[];
}
export interface Paged<T> {
  items: T[];
  next_cursor: string | null;
  total?: number;
}
export interface Auth {
  initialized: boolean;
  authenticated: boolean;
  csrf_token?: string;
  username?: string;
}
export interface Settings {
  version: string;
  limits: Record<string, number>;
  mcp_endpoint: string;
  scopes: string[];
  data_storage: string;
  theme_options: string[];
}
export interface Credential {
  id: string;
  name: string;
  scopes: string[];
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  created_at?: string;
}
