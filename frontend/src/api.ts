import { fetchAuthSession } from "aws-amplify/auth";

const API_URL = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

export type Status = "PENDING_UPLOAD" | "PROCESSING" | "READY" | "FAILED";

export interface Syllabus {
  syllabusId: string;
  filename: string;
  status: Status;
  error?: string;
  courseCode?: string;
  courseTitle?: string;
  termStart?: string;
  deadlineCount?: number;
  pageCount?: number;
  warnings?: string[];
  createdAt: string;
}

export const DEADLINE_TYPES = [
  "assignment", "quiz", "midterm", "final_exam", "project", "lab", "presentation", "participation", "other",
] as const;

/** The fields a user can set on a deadline. Empty strings clear optional fields. */
export interface DeadlineInput {
  title: string;
  type: string;
  dueDate: string;
  dueTime: string;
  weightPercent: string;
}

export interface Settings {
  emailEnabled: boolean;
  daysAhead: number;
  email?: string;
  available: boolean;
  verificationSent?: boolean;
}

export interface Deadline {
  syllabusId: string;
  deadlineId: string;
  source?: "manual" | "edited";
  courseCode?: string;
  title: string;
  type: string;
  dueDate?: string;
  dueTime?: string;
  weightPercent?: number;
  dateApproximate?: boolean;
  week?: number;
  sourceText?: string;
  page?: number;
}

export interface Citation {
  id: string;
  kind: "deadline" | "passage";
  courseCode?: string;
  title?: string;
  dueDate?: string;
  weightPercent?: number;
  filename?: string;
  page?: number;
  text?: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  // The JWT authorizer checks the token's audience against the app client, so send the ID token.
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString();
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.error ?? `Request failed (${res.status})`);
  return data as T;
}

export const localToday = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export const api = {
  listSyllabi: () => request<{ syllabi: Syllabus[] }>("GET", "/syllabi"),
  getSyllabus: (id: string) =>
    request<{ syllabus: Syllabus; deadlines: Deadline[] }>("GET", `/syllabi/${encodeURIComponent(id)}`),
  deleteSyllabus: (id: string) => request<{ deleted: string }>("DELETE", `/syllabi/${encodeURIComponent(id)}`),
  listDeadlines: (days?: number) =>
    request<{ deadlines: Deadline[] }>(
      "GET",
      days ? `/deadlines?days=${days}&today=${localToday()}` : "/deadlines",
    ),
  addDeadline: (syllabusId: string, input: DeadlineInput) =>
    request<{ deadline: Deadline }>("POST", `/syllabi/${encodeURIComponent(syllabusId)}/deadlines`, input),
  updateDeadline: (d: Deadline, input: DeadlineInput) =>
    request<{ deadline: Deadline }>(
      "PATCH",
      `/syllabi/${encodeURIComponent(d.syllabusId)}/deadlines/${d.deadlineId}`,
      input,
    ),
  deleteDeadline: (d: Deadline) =>
    request<{ deleted: string }>("DELETE", `/syllabi/${encodeURIComponent(d.syllabusId)}/deadlines/${d.deadlineId}`),

  getSettings: () => request<Settings>("GET", "/settings"),
  saveSettings: (emailEnabled: boolean, daysAhead: number) =>
    request<Settings>("PUT", "/settings", { emailEnabled, daysAhead }),
  sendTestEmail: () => request<{ sentTo: string; deadlineCount: number }>("POST", "/settings/test-email"),

  ask: (question: string, history: ChatTurn[]) =>
    request<{ answer: string; citations: Citation[]; toolCalls: string[] }>("POST", "/ask", {
      question,
      history,
      today: localToday(),
    }),

  /** Register the file, then PUT it straight to S3 with the presigned URL (never through Lambda). */
  async upload(file: File, termStart?: string) {
    const { syllabusId, uploadUrl } = await request<{ syllabusId: string; uploadUrl: string }>(
      "POST",
      "/uploads",
      { filename: file.name, ...(termStart ? { termStart } : {}) },
    );
    const put = await fetch(uploadUrl, {
      method: "PUT",
      headers: { "Content-Type": "application/pdf" },
      body: file,
    });
    if (!put.ok) throw new ApiError(put.status, "Upload to storage failed");
    return syllabusId;
  },
};
