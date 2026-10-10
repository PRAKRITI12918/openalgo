/**
 * Resolves the Socket.IO server URL based on VITE_API_URL or the current window location.
 */
export function getSocketUrl(): string {
  const envUrl = import.meta.env.VITE_API_URL
  if (envUrl && typeof envUrl === 'string' && envUrl.trim() !== '') {
    return envUrl.trim().replace(/\/$/, '')
  }

  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol
    const host = window.location.hostname
    const port = window.location.port
    return port ? `${protocol}//${host}:${port}` : `${protocol}//${host}`
  }

  return 'http://localhost:5000'
}
