/**
 * API Client Module
 * Provides fetch wrapper with automatic CSRF header inclusion, credential passing,
 * and centralized session expiration redirect handling.
 */

(function () {
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
      return parts.pop().split(';').shift();
    }
    return null;
  }

  function getCsrfToken() {
    return getCookie('travel_crm_csrf') || '';
  }

  async function request(url, options = {}) {
    const defaultHeaders = {
      'Accept': 'application/json',
    };

    const method = (options.method || 'GET').toUpperCase();

    // Include CSRF token on state-modifying HTTP methods
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      const csrfToken = getCsrfToken();
      if (csrfToken) {
        defaultHeaders['X-CSRF-Token'] = csrfToken;
      }
    }

    // Set JSON content type if body is a plain object/string and not FormData
    if (options.body && !(options.body instanceof FormData) && typeof options.body === 'object') {
      defaultHeaders['Content-Type'] = 'application/json';
      options.body = JSON.stringify(options.body);
    }

    const config = {
      credentials: 'same-origin',
      ...options,
      headers: {
        ...defaultHeaders,
        ...(options.headers || {}),
      },
    };

    try {
      const response = await fetch(url, config);

      // Handle session expiration or unauthenticated access
      if (response.status === 401) {
        const isAuthEndpoint = url.includes('/api/auth/login') || url.includes('/api/auth/status');
        const isLoginPage = window.location.pathname === '/login';
        if (!isAuthEndpoint && !isLoginPage) {
          window.location.href = '/login?expired=1';
          return null;
        }
      }

      return response;
    } catch (error) {
      console.error('API Network Error:', error);
      throw error;
    }
  }

  window.API = {
    get: (url, options = {}) => request(url, { ...options, method: 'GET' }),
    post: (url, body, options = {}) => request(url, { ...options, method: 'POST', body }),
    patch: (url, body, options = {}) => request(url, { ...options, method: 'PATCH', body }),
    delete: (url, options = {}) => request(url, { ...options, method: 'DELETE' }),
    getCsrfToken,
    getCookie,
  };
})();
