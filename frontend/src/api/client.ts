import type { AuditResult, StageRecord } from "./types";

const BASE = "http://127.0.0.1:8000";

export async function health(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/api/health`);
  if (!res.ok) throw new Error("backend_unreachable");
  return res.json();
}

export async function checkConfig(): Promise<
  { ok: true; rpc_url: string; wallet: string; contract_address: string; chain_id: number } |
  { ok: false; error: string }
> {
  const res = await fetch(`${BASE}/api/check-config`);
  return res.json();
}

export async function audit(manifestPath: string): Promise<AuditResult> {
  const res = await fetch(
    `${BASE}/api/audit?manifest=${encodeURIComponent(manifestPath)}`,
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "audit_failed");
  }
  return res.json();
}

export interface StreamHandlers<TResult> {
  onStage?: (record: StageRecord) => void;
  onResult?: (result: TResult) => void;
  onError?: (detail: string) => void;
}

/**
 * Consumes one of the /stream (Server-Sent Events) endpoints. Each
 * "stage" event fires the instant the backend actually emits that
 * StageRecord -- there is no simulated timing on this side. Exactly
 * one of onResult/onError fires at the very end, carrying the real,
 * complete PipelineResult/DiscoveryResult -- same object the CLI
 * would have printed.
 */
async function streamPost<TResult>(
  path: string,
  formData: FormData,
  handlers: StreamHandlers<TResult>,
): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { method: "POST", body: formData });
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => "stream_request_failed");
    handlers.onError?.(detail);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      const eventLine = frame.split("\n").find((l) => l.startsWith("event: "));
      const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!eventLine || !dataLine) continue;

      const event = eventLine.slice("event: ".length);
      const data = JSON.parse(dataLine.slice("data: ".length));

      if (event === "stage") handlers.onStage?.(data as StageRecord);
      else if (event === "result") handlers.onResult?.(data as TResult);
      else if (event === "error") handlers.onError?.(data.detail as string);
    }
  }
}

export function streamDiscover<TResult>(
  image: File,
  handlers: StreamHandlers<TResult>,
): Promise<void> {
  const form = new FormData();
  form.append("image", image);
  return streamPost("/api/discover/stream", form, handlers);
}

export function streamVerify<TResult>(
  image: File,
  url: string,
  handlers: StreamHandlers<TResult>,
): Promise<void> {
  const form = new FormData();
  form.append("image", image);
  form.append("url", url);
  return streamPost("/api/verify/stream", form, handlers);
}

export function streamRegister<TResult>(
  image: File,
  url: string,
  handlers: StreamHandlers<TResult>,
): Promise<void> {
  const form = new FormData();
  form.append("image", image);
  form.append("url", url);
  form.append("confirm", "REGISTER"); // the one deliberate real write -- see api.py
  return streamPost("/api/register/stream", form, handlers);
}
