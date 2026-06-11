/* Read-only client for the Maverick dashboard REST API.
 *
 * Every function here is a GET against an endpoint that exists today in
 * packages/maverick-dashboard/maverick_dashboard/api.py:
 *
 *   GET /api/v1/goals?limit=&status=          listGoals()
 *   GET /api/v1/goals/{id}                    getGoal()
 *   GET /api/v1/goals/{id}/events?since=&limit=  getGoalEvents()
 *   GET /api/v1/oversight/active              getActive()
 *   GET /api/v1/spend                         getSpend()
 *   GET /api/v1/offline/bundle                getOfflineBundle()  (optional —
 *       served once the integrator adds the maverick.offline_bundle endpoint;
 *       404 from older dashboards is handled by the caller)
 *
 * This app is READ-ONLY by design: no POST/DELETE/PUT anywhere.
 */

export type Settings = { baseUrl: string; token: string };

export type Goal = {
  id: number;
  status: string;
  title: string;
  description?: string | null;
  result?: string | null;
};

export type GoalEvent = {
  id: number;
  agent: string;
  kind: string;
  content: string;
  ts: number;
};

export type GoalEventsResponse = {
  status: string;
  result: string | null;
  next_id: number;
  events: GoalEvent[];
};

export type ActiveGoal = {
  id: number;
  title: string;
  status: string;
  updated_at: number;
  activity: string;
};

export type SpendTotal = {
  dollars: number;
  input_tokens: number;
  output_tokens: number;
  runs: number;
};

export type Glance = {
  as_of: number;
  active: { id: number; title: string; status: string; updated_at: number }[];
  counts: { active: number; pending_approvals: number; open_questions: number };
  spend: { dollars: number; runs: number };
};

export type BundleGoal = {
  id: number;
  title: string;
  status: string;
  created_at: number;
  updated_at: number;
  result: string | null;
};

export type OfflineBundle = {
  schema: string; // "maverick-offline/1"
  as_of: number;
  glance: Glance;
  goals: BundleGoal[];
  recent_events: (GoalEvent & { goal_id: number })[];
};

async function apiGet<T>(cfg: Settings, path: string): Promise<T> {
  const base = cfg.baseUrl.replace(/\/+$/, "");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (cfg.token) headers.Authorization = `Bearer ${cfg.token}`;
  const res = await fetch(`${base}${path}`, { method: "GET", headers });
  if (!res.ok) throw new Error(`GET ${path} -> HTTP ${res.status}`);
  return (await res.json()) as T;
}

export function listGoals(cfg: Settings, limit = 50): Promise<Goal[]> {
  return apiGet<Goal[]>(cfg, `/api/v1/goals?limit=${limit}`);
}

export function getGoal(cfg: Settings, id: number): Promise<Goal> {
  return apiGet<Goal>(cfg, `/api/v1/goals/${id}`);
}

export function getGoalEvents(
  cfg: Settings, id: number, since = 0, limit = 200,
): Promise<GoalEventsResponse> {
  return apiGet<GoalEventsResponse>(
    cfg, `/api/v1/goals/${id}/events?since=${since}&limit=${limit}`,
  );
}

export function getActive(cfg: Settings): Promise<{ goals: ActiveGoal[] }> {
  return apiGet<{ goals: ActiveGoal[] }>(cfg, "/api/v1/oversight/active");
}

export function getSpend(cfg: Settings): Promise<{ total: SpendTotal }> {
  return apiGet<{ total: SpendTotal }>(cfg, "/api/v1/spend");
}

export function getOfflineBundle(cfg: Settings): Promise<OfflineBundle> {
  return apiGet<OfflineBundle>(cfg, "/api/v1/offline/bundle");
}
