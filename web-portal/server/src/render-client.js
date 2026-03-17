/**
 * HTTP client for the VariationMGR render server.
 * Uses only built-in Node.js fetch (available in Node 18+).
 */

export async function submitToRenderServer(serverUrl, jobPayload) {
  const url = `${serverUrl.replace(/\/$/, "")}/submit`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(jobPayload),
    signal: AbortSignal.timeout(10_000),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`Render server error: HTTP ${response.status} — ${text}`);
  }

  return response.json();
}

export async function pollRenderServer(serverUrl, renderJobId) {
  const url = `${serverUrl.replace(/\/$/, "")}/jobs/${renderJobId}`;
  const response = await fetch(url, {
    signal: AbortSignal.timeout(5_000),
  });

  if (!response.ok) return null;
  return response.json();
}

export async function checkRenderServerHealth(serverUrl) {
  const url = `${serverUrl.replace(/\/$/, "")}/health`;
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(4_000) });
    if (!response.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}
