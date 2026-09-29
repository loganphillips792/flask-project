import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, scenarioFor, COMMON_THRESHOLDS } from './helpers.js';

export const options = {
  scenarios: {
    public_endpoints: scenarioFor(),
  },
  thresholds: {
    ...COMMON_THRESHOLDS,
    'http_req_duration{endpoint:health}': ['p(95)<100'],
    'http_req_duration{endpoint:loans_list}': ['p(95)<500'],
  },
};

export default function () {
  const health = http.get(`${BASE_URL}/health`, { tags: { endpoint: 'health' } });
  check(health, {
    'health is 200': (r) => r.status === 200,
    'health status ok': (r) => r.json('status') === 'ok',
  });

  const loans = http.get(`${BASE_URL}/api/loans`, { tags: { endpoint: 'loans_list' } });
  check(loans, {
    'loans list is 200': (r) => r.status === 200,
    'loans list is array': (r) => Array.isArray(r.json()),
  });

  // 404 is a valid outcome on a fresh database (no loans yet); without the
  // responseCallback it would count toward http_req_failed.
  const loan = http.get(`${BASE_URL}/api/loans/1`, {
    tags: { endpoint: 'loan_get' },
    responseCallback: http.expectedStatuses(200, 404),
  });
  check(loan, {
    'loan get is 200 or 404': (r) => r.status === 200 || r.status === 404,
  });

  sleep(1);
}
