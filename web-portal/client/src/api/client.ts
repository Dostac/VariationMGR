import type {
  TemplateSummary,
  TemplateManifest,
  JobStatus,
  UsageInfo,
} from "../types";

const BASE = "/api";

function getApiKey(): string {
  return localStorage.getItem("vb_api_key") || "";
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${getApiKey()}`,
    ...(init?.headers as Record<string, string>),
  };

  const res = await fetch(`${BASE}${path}`, { ...init, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(body.error || `HTTP ${res.status}`);
  }

  return res.json();
}

// Auth
export async function validateKey(): Promise<UsageInfo> {
  return apiFetch<UsageInfo>("/usage");
}

// Templates
export async function listTemplates(): Promise<TemplateSummary[]> {
  const data = await apiFetch<{ templates: TemplateSummary[] }>("/templates");
  return data.templates;
}

export async function getTemplate(id: string): Promise<TemplateManifest> {
  return apiFetch<TemplateManifest>(`/templates/${id}`);
}

export function proxyUrl(templateId: string): string {
  return `${BASE}/templates/${templateId}/proxy`;
}

export function previewUrl(templateId: string, file: string): string {
  const filename = file.replace(/^previews\//, "");
  return `${BASE}/templates/${templateId}/previews/${filename}`;
}

// Jobs
export async function submitJob(params: {
  template_id: string;
  rows: string[][];
  render_preset: string;
  output_format: string;
}): Promise<{ job_id: string; status: string }> {
  return apiFetch("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  return apiFetch<JobStatus>(`/jobs/${jobId}`);
}

export async function getJobOutputs(
  jobId: string
): Promise<{ files: string[] }> {
  return apiFetch<{ files: string[] }>(`/jobs/${jobId}/outputs`);
}

export function outputImageUrl(jobId: string, filename: string): string {
  return `${BASE}/jobs/${jobId}/outputs/${filename}`;
}

// Usage
export async function getUsage(): Promise<UsageInfo> {
  return apiFetch<UsageInfo>("/usage");
}
