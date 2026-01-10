/**
 * API Logger Wrapper
 * Logs all HTTP requests and surfaces errors with request_id
 */

/**
 * Logged fetch wrapper that tracks all API calls
 * @param {string} url - The URL to fetch
 * @param {RequestInit} options - Fetch options
 * @returns {Promise<Response>}
 */
export async function loggedFetch(url, options = {}) {
  const method = options.method || 'GET';
  const startTime = performance.now();

  console.log(`[API] ${method} ${url} - Starting...`);

  try {
    const response = await fetch(url, options);
    const duration = Math.round(performance.now() - startTime);

    if (!response.ok) {
      // Non-2xx response
      const statusText = response.statusText || 'Error';
      console.error(`[API] ${method} ${url} ${response.status} ${statusText} ${duration}ms`);

      // Try to extract error details
      let errorBody = null;
      let requestId = response.headers.get('X-Request-Id');

      const contentType = response.headers.get('content-type');
      if (contentType?.includes('application/json')) {
        try {
          errorBody = await response.clone().json();
          console.error(`[API] Error body:`, errorBody);

          // Extract request_id from error body if available
          if (errorBody.request_id) {
            requestId = errorBody.request_id;
          }
        } catch (e) {
          // Failed to parse JSON
          console.error(`[API] Failed to parse error JSON:`, e);
        }
      } else {
        try {
          const textBody = await response.clone().text();
          console.error(`[API] Error text:`, textBody.substring(0, 500));
        } catch (e) {
          // Failed to read text
        }
      }

      // Show error banner/toast with request_id
      showErrorNotification(response.status, errorBody, requestId);

      return response;
    }

    // Success
    console.log(`[API] ${method} ${url} ${response.status} ${duration}ms`);

    // Add request_id to console for correlation
    const requestId = response.headers.get('X-Request-Id');
    if (requestId) {
      console.log(`[API] Request ID: ${requestId}`);
    }

    return response;
  } catch (error) {
    // Network error or other exception
    const duration = Math.round(performance.now() - startTime);
    console.error(`[API] ${method} ${url} NETWORK_ERROR ${duration}ms`, error);

    // Show error notification
    showErrorNotification(0, {
      error_code: 'NETWORK_ERROR',
      message: `Failed to reach server: ${error.message}`,
    }, null);

    throw error;
  }
}

/**
 * Show error notification to user
 * @param {number} status - HTTP status code
 * @param {object} errorBody - Error response body
 * @param {string|null} requestId - Request ID for correlation
 */
function showErrorNotification(status, errorBody, requestId) {
  const errorCode = errorBody?.error_code || 'UNKNOWN_ERROR';
  const message = errorBody?.message || errorBody?.detail || 'An error occurred';

  let notificationMessage = `Error: ${message}`;
  if (requestId) {
    notificationMessage += `\n\nRequest ID: ${requestId}`;
  }
  if (errorCode) {
    notificationMessage += `\nError Code: ${errorCode}`;
  }

  // Dispatch custom event for UI to listen to
  window.dispatchEvent(new CustomEvent('api-error', {
    detail: {
      status,
      errorCode,
      message,
      requestId,
      timestamp: new Date().toISOString(),
    }
  }));

  console.error(`[API] Error notification:`, {
    status,
    errorCode,
    message,
    requestId,
  });
}

/**
 * Logged JSON fetch wrapper
 * @param {string} url - The URL to fetch
 * @param {RequestInit} options - Fetch options
 * @returns {Promise<any>} - Parsed JSON response
 */
export async function loggedFetchJson(url, options = {}) {
  const response = await loggedFetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}: ${response.statusText}`);
    error.response = response;
    throw error;
  }

  return response.json();
}

/**
 * Logged POST JSON wrapper
 * @param {string} url - The URL to POST to
 * @param {object} data - Data to send
 * @param {RequestInit} options - Additional fetch options
 * @returns {Promise<any>} - Parsed JSON response
 */
export async function loggedPost(url, data, options = {}) {
  return loggedFetchJson(url, {
    ...options,
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * Logged PUT JSON wrapper
 * @param {string} url - The URL to PUT to
 * @param {object} data - Data to send
 * @param {RequestInit} options - Additional fetch options
 * @returns {Promise<any>} - Parsed JSON response
 */
export async function loggedPut(url, data, options = {}) {
  return loggedFetchJson(url, {
    ...options,
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

/**
 * Logged DELETE wrapper
 * @param {string} url - The URL to DELETE
 * @param {RequestInit} options - Additional fetch options
 * @returns {Promise<any>} - Parsed JSON response
 */
export async function loggedDelete(url, options = {}) {
  return loggedFetchJson(url, {
    ...options,
    method: 'DELETE',
  });
}
