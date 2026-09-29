import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, scenarioFor, COMMON_THRESHOLDS, ensureLoggedIn } from './helpers.js';

export const options = {
  // k6 wipes each VU's cookie jar between iterations by default, which would
  // silently turn every request after the first iteration into a redirect to
  // the login page; sessions must outlive iterations for login-once-per-VU.
  noCookiesReset: true,
  scenarios: {
    member_browse: { ...scenarioFor(), exec: 'memberBrowse' },
    admin_browse: { ...scenarioFor(5), exec: 'adminBrowse' },
  },
  thresholds: COMMON_THRESHOLDS,
};

export function memberBrowse() {
  ensureLoggedIn('ada@example.com', 'password');

  const dashboard = http.get(`${BASE_URL}/dashboard`, { tags: { endpoint: 'dashboard' } });
  check(dashboard, {
    'dashboard is 200': (r) => r.status === 200,
    'dashboard shows welcome': (r) => r.body.includes('Welcome,'),
  });
  sleep(1);

  const settings = http.get(`${BASE_URL}/settings`, { tags: { endpoint: 'settings' } });
  check(settings, {
    'settings is 200': (r) => r.status === 200,
    'settings shows heading': (r) => r.body.includes('<h1>Settings</h1>'),
  });
  sleep(1);
}

export function adminBrowse() {
  ensureLoggedIn('admin@example.com', 'password');

  const dashboard = http.get(`${BASE_URL}/dashboard`, { tags: { endpoint: 'dashboard' } });
  check(dashboard, {
    'dashboard is 200': (r) => r.status === 200,
  });
  sleep(1);

  const books = http.get(`${BASE_URL}/books`, { tags: { endpoint: 'books' } });
  check(books, {
    'books is 200': (r) => r.status === 200,
    'books shows heading': (r) => r.body.includes('<h1>Books</h1>'),
  });
  sleep(1);
}
