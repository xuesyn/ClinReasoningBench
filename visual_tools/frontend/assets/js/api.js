export async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  let payload = null;

  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const message = payload?.detail || `Request failed: ${response.status}`;
    throw new Error(message);
  }

  return payload;
}

