// k6 并发压测（标准版，适合打 staging / 灰度；本地快速压测用 loadtest.py 更省事）
// 跑法：
//   k6 run -e BASE_URL=http://localhost:8000 -e TOKEN=<jwt> scripts/loadtest/k6-loadtest.js
import http from 'k6/http';
import { sleep } from 'k6';

const BASE = __ENV.BASE_URL || 'http://localhost:8000';
const TOKEN = __ENV.TOKEN || '';

if (!TOKEN) {
  throw new Error('缺 TOKEN：-e TOKEN=<jwt>（用 scripts/loadtest/mint_token.py 造）');
}

export const options = {
  scenarios: {
    load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 50 }, // 爬坡到 50 并发
        { duration: '60s', target: 50 }, // 保持
        { duration: '30s', target: 0 },  // 回落到 0
      ],
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<1000'], // p95 延迟 < 1s
    http_req_failed: ['rate<0.01'],    // 错误率 < 1%
  },
};

const PATHS = [
  '/api/work-orders',
  '/api/work-orders?page=1&page_size=50',
  '/api/work-orders/dashboard/summary',
  '/api/dashboard/stats',
  '/api/dashboard/trends',
];

export default function () {
  const path = PATHS[Math.floor(Math.random() * PATHS.length)];
  http.get(`${BASE}${path}`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  });
  sleep(0.2);
}