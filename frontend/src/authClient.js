export function notifySignedOut() {
  window.dispatchEvent(new Event('homesphere:signed-out'))
}

export async function authFetch(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options })
  if (response.status === 401 && !path.startsWith('/auth/')) notifySignedOut()
  return response
}
