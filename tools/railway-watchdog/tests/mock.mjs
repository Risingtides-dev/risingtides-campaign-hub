// Local stand-in for the Railway GraphQL API, a health URL, and the GitHub issues API.
// Test-only: driven by tests/smoke.sh. Usage: node tests/mock.mjs <port>
//   POST /__set     merge JSON into the fake world (services, billing, failIds, health,
//                   billingError, railwayDown, pageSize, delayMs)
//   GET  /__log     {calls: [...railway mutations...], issues: [...], comments: [...], authFails}
import http from "node:http";

const port = Number(process.argv[2] || 18797);
const world = {
  billing: { over: false, usage: 12.5, hard: 100 },
  failIds: [],
  health: {},
  // env id -> project/env names and services
  envs: {
    e1: { project: "campaign-hub", name: "production" },
    e2: { project: "content-lab", name: "production" },
  },
  services: {
    pg: { env: "e1", name: "Postgres", image: true, cron: false, latest: "SUCCESS", active: [["pg-live", "SUCCESS"]], deployments: [["pg-old", "REMOVED"]] },
    app: { env: "e1", name: "app", image: false, cron: false, latest: "SUCCESS", active: [["app-live", "SUCCESS"]], deployments: [["f3", "FAILED"], ["f2", "FAILED"], ["app-old", "REMOVED"]] },
    bk: { env: "e1", name: "Backup CRON", image: false, cron: true, latest: "SUCCESS", active: [], deployments: [["bk-old", "REMOVED"]] },
    lab: { env: "e2", name: "lab", image: false, cron: false, latest: "SUCCESS", active: [["lab-live", "SUCCESS"]], deployments: [["lab-old", "REMOVED"]] },
  },
};
const log = { calls: [], issues: [], comments: [], authFails: 0 };
let nextIssue = 1;

const body = (req) =>
  new Promise((res) => {
    let b = "";
    req.on("data", (c) => (b += c));
    req.on("end", () => res(b));
  });
const send = (res, code, obj) => {
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(typeof obj === "string" ? obj : JSON.stringify(obj));
};

function projects(after) {
  const byProject = {};
  for (const [envId, e] of Object.entries(world.envs)) {
    const sis = Object.entries(world.services)
      .filter(([, s]) => s.env === envId)
      .map(([id, s]) => ({
        node: {
          serviceId: id,
          serviceName: s.name,
          cronSchedule: s.cron ? "0 0 * * *" : null,
          source: { image: s.image ? "ghcr.io/railwayapp-templates/postgres-ssl:17" : null },
          latestDeployment: s.latest ? { status: s.latest } : null,
          activeDeployments: s.active.map(([id, status]) => ({ id, status })),
        },
      }));
    (byProject[e.project] ||= []).push({
      node: { id: envId, name: e.name, serviceInstances: { pageInfo: { hasNextPage: false }, edges: sis } },
    });
  }
  // Pages of projects; the cursor is the index of the next project.
  const all = Object.entries(byProject).map(([name, envs]) => ({
    node: { name, environments: { pageInfo: { hasNextPage: false }, edges: envs } },
  }));
  const start = after ? Number(after) : 0;
  const size = world.pageSize || 100;
  const end = Math.min(start + size, all.length);
  return {
    projects: {
      pageInfo: { hasNextPage: end < all.length, endCursor: String(end) },
      edges: all.slice(start, end),
    },
  };
}

function graphql(q) {
  const arg = (name) => (q.match(new RegExp(`${name}: "([^"]+)"`)) || [])[1];
  if (q.includes("deploymentRedeploy")) {
    const id = arg("id");
    log.calls.push({ op: "redeploy", id, previousImage: q.includes("usePreviousImageTag: true") });
    if (world.failIds.includes(id)) return { errors: [{ message: "Deployment image no longer exists" }] };
    return { data: { deploymentRedeploy: { id: `new-${id}` } } };
  }
  if (q.includes("serviceInstanceDeployV2")) {
    log.calls.push({ op: "deploy", service: arg("serviceId"), env: arg("environmentId") });
    return { data: { serviceInstanceDeployV2: "new-build" } };
  }
  if (q.includes("deploymentRestart")) {
    log.calls.push({ op: "restart", id: arg("id") });
    return { data: { deploymentRestart: true } };
  }
  if (q.includes("deployments(")) {
    const s = world.services[arg("serviceId")];
    return { data: { deployments: { edges: (s?.deployments || []).map(([id, status]) => ({ node: { id, status } })) } } };
  }
  if (q.includes("workspace(")) {
    if (world.billingError) return { errors: [{ message: "Not Authorized" }] };
    const b = world.billing;
    return { data: { workspace: { customer: { currentUsage: b.usage, usageLimit: { softLimit: b.hard, hardLimit: b.hard, isOverLimit: b.over } } } } };
  }
  if (q.includes("projects(")) {
    log.projectPages = (log.projectPages || 0) + 1;
    if (world.railwayDown) return { errors: [{ message: "Internal server error" }] };
    return { data: projects(arg("after")) };
  }
  return { errors: [{ message: "mock: unknown query" }] };
}

http
  .createServer(async (req, res) => {
    const url = new URL(req.url, `http://127.0.0.1:${port}`);
    const raw = await body(req);
    const json = raw ? JSON.parse(raw) : null;
    const p = url.pathname;

    if (p === "/__set") {
      for (const [k, v] of Object.entries(json)) {
        if (k === "services") for (const [id, s] of Object.entries(v)) Object.assign(world.services[id], s);
        else world[k] = v;
      }
      return send(res, 200, { ok: true });
    }
    if (p === "/__log") return send(res, 200, log);
    if (p.startsWith("/health/")) {
      const code = world.health[p.slice(8)] ?? 200;
      return send(res, code, { ok: code === 200 });
    }
    if (p === "/graphql") {
      if (req.headers.authorization !== "Bearer fake-railway-token") {
        log.authFails++;
        return send(res, 401, { errors: [{ message: "Not Authorized" }] });
      }
      if (world.delayMs) await new Promise((r) => setTimeout(r, world.delayMs));
      return send(res, 200, graphql(json.query));
    }
    // GitHub issues API
    const gh = p.match(/^\/repos\/[^/]+\/[^/]+\/issues(?:\/(\d+)(\/comments)?)?$/);
    if (gh) {
      if (req.headers.authorization !== "Bearer fake-github-token") return send(res, 401, {});
      const [, num, comments] = gh;
      if (!num && req.method === "GET") return send(res, 200, log.issues.filter((i) => i.state === "open").slice().reverse());
      if (!num && req.method === "POST") {
        const i = { number: nextIssue++, title: json.title, body: json.body, state: "open" };
        log.issues.push(i);
        return send(res, 201, i);
      }
      const issue = log.issues.find((i) => i.number === Number(num));
      if (!issue) return send(res, 404, {});
      if (comments && req.method === "POST") {
        log.comments.push({ issue: issue.number, body: json.body });
        return send(res, 201, {});
      }
      if (req.method === "PATCH") {
        Object.assign(issue, json);
        return send(res, 200, issue);
      }
    }
    send(res, 404, { message: "mock: not found" });
  })
  .listen(port, "127.0.0.1");
