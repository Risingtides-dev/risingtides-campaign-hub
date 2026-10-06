//! railway-watchdog: brings stopped Railway services back on its own.
//! It runs on Cloudflare, outside Railway, because on 2026-10-06 Railway stopped every service
//! in the workspace at once; anything running inside Railway would have stopped too.
//! All decisions live in `core` (pure, unit-tested on the host). This file is only the
//! Cloudflare Worker glue: the Railway API, health checks, KV, and the GitHub alert issue.
//!
//! KV layout (binding WATCHDOG):
//!   state   JSON core::State   (written only when it changes)
//!   paused  any non-empty value pauses all actions (alerts still drain)

pub mod core;

#[cfg(target_arch = "wasm32")]
mod worker_glue {
    use crate::core::{self, Action, Billing, Inputs, Msg, MsgKind, State};
    use futures_util::future::{select, Either};
    use serde::Deserialize;
    use serde_json::{json, Value};
    use std::collections::BTreeMap;
    use std::time::Duration;
    use worker::*;

    const HTTP_TIMEOUT: Duration = Duration::from_secs(10);
    const UA: &str = "railway-watchdog/0.1";

    fn now_s() -> i64 {
        (Date::now().as_millis() / 1000) as i64
    }

    fn var(env: &Env, name: &str) -> Option<String> {
        env.var(name)
            .ok()
            .map(|v| v.to_string())
            .filter(|s| !s.is_empty())
    }

    fn secret(env: &Env, name: &str) -> Option<String> {
        env.secret(name)
            .ok()
            .map(|v| v.to_string())
            .filter(|s| !s.is_empty())
    }

    #[event(fetch)]
    async fn fetch(_req: Request, _env: Env, _ctx: Context) -> Result<Response> {
        // No HTTP surface on purpose: watch it with `wrangler tail` and the alert issues.
        Response::error("not found", 404)
    }

    #[event(scheduled)]
    async fn scheduled(_ev: ScheduledEvent, env: Env, _ctx: ScheduleContext) {
        if let Err(e) = tick(&env).await {
            console_error!("watchdog tick failed: {e}");
        }
    }

    async fn tick(env: &Env) -> Result<()> {
        let kv = env.kv("WATCHDOG")?;
        let old: State = kv
            .get("state")
            .json::<State>()
            .await
            .ok()
            .flatten()
            .unwrap_or_default();
        let mut st = old.clone();

        let paused = kv
            .get("paused")
            .text()
            .await
            .ok()
            .flatten()
            .map(|v| !v.trim().is_empty())
            .unwrap_or(false);
        if paused {
            console_log!("watchdog paused (KV key 'paused' is set): no actions");
        } else {
            st = check(env, st).await;
        }

        st = deliver(env, st).await;
        if st != old {
            kv.put("state", serde_json::to_string(&st)?)?
                .execute()
                .await?;
        }
        Ok(())
    }

    /// Look at Railway, decide, act. Any failure to read Railway leaves the state untouched.
    async fn check(env: &Env, st: State) -> State {
        let Some(ws) = var(env, "WORKSPACE_ID").filter(|w| core::is_id(w)) else {
            console_error!("watchdog: WORKSPACE_ID is missing or malformed");
            return st;
        };
        let watch = match core::parse_watch(&var(env, "WATCH").unwrap_or_default()) {
            Ok(w) => w,
            Err(e) => {
                console_error!("watchdog: {e}");
                return st;
            }
        };
        let rw = match Railway::new(env) {
            Some(r) => r,
            None => {
                console_warn!("watchdog: RAILWAY_TOKEN is not set; watching nothing");
                return st;
            }
        };
        let data = match rw.query(&services_query(&ws)).await {
            Ok(d) => d,
            Err(e) => {
                console_warn!("watchdog: could not read Railway: {e}");
                return st;
            }
        };
        let (services, missing) = core::collect(&data, &watch);
        if !missing.is_empty() {
            console_error!("watchdog: Railway does not list watched environment(s) {missing:?}");
        }

        let mut health = BTreeMap::new();
        for s in services
            .iter()
            .filter(|s| core::phase(s) == core::Phase::Up)
        {
            if let Some(url) = &s.health_url {
                let ok = matches!(
                    http(Method::Get, url, &[("User-Agent", UA)], None).await,
                    Some((200..=299, _))
                );
                if !ok {
                    console_warn!("watchdog: health check failed for {} ({})", s.name, s.place);
                }
                health.insert(s.key.clone(), ok);
            }
        }

        let billing = if core::needs_attention(&services, &health) {
            rw.billing(&ws).await
        } else {
            None
        };
        let limits = core::parse_limits(|k| var(env, k));
        let (st, actions) = core::decide(
            &Inputs {
                now: now_s(),
                services: &services,
                health: &health,
                billing,
            },
            &limits,
            st,
        );
        for a in &actions {
            let out = act(&rw, a).await;
            console_log!("watchdog action {a:?}: {out}");
        }
        st
    }

    async fn act(rw: &Railway, a: &Action) -> String {
        match a {
            Action::Restart { deployment_id, .. } => {
                let q = format!(r#"mutation {{ deploymentRestart(id: "{deployment_id}") }}"#);
                result(rw.query(&q).await)
            }
            Action::Revive {
                env_id,
                service_id,
                restore,
                ..
            } => {
                if *restore {
                    match rw.last_ran(env_id, service_id).await {
                        Some(id) => {
                            let q = format!(
                                r#"mutation {{ deploymentRedeploy(id: "{id}", usePreviousImageTag: true) {{ id }} }}"#
                            );
                            match rw.query(&q).await {
                                Ok(v) => return format!("restored deployment {id}: {v}"),
                                Err(e) => console_warn!("watchdog: restoring {id} failed ({e}); building latest instead"),
                            }
                        }
                        None => console_log!(
                            "watchdog: no earlier deployment to restore; building latest"
                        ),
                    }
                }
                let q = format!(
                    r#"mutation {{ serviceInstanceDeployV2(serviceId: "{service_id}", environmentId: "{env_id}") }}"#
                );
                result(rw.query(&q).await)
            }
        }
    }

    fn result(r: std::result::Result<Value, String>) -> String {
        match r {
            Ok(v) => format!("ok {v}"),
            Err(e) => format!("FAILED {e}"),
        }
    }

    fn services_query(ws: &str) -> String {
        format!(
            r#"{{ projects(workspaceId: "{ws}") {{ edges {{ node {{ name environments {{ edges {{ node {{ id name
            serviceInstances {{ edges {{ node {{ serviceId serviceName cronSchedule source {{ image }}
            latestDeployment {{ status }} activeDeployments {{ id status }} }} }} }} }} }} }} }} }} }} }}"#
        )
    }

    // ---------- Railway GraphQL ----------

    struct Railway {
        url: String,
        auth: String,
    }

    impl Railway {
        fn new(env: &Env) -> Option<Self> {
            let tok = secret(env, "RAILWAY_TOKEN")?;
            Some(Railway {
                url: var(env, "RAILWAY_API")
                    .unwrap_or_else(|| "https://backboard.railway.com/graphql/v2".into()),
                auth: format!("Bearer {tok}"),
            })
        }

        /// Returns `data`, or a short error. Never includes the token.
        async fn query(&self, q: &str) -> std::result::Result<Value, String> {
            let hdrs = [
                ("Authorization", self.auth.as_str()),
                ("Content-Type", "application/json"),
                ("User-Agent", UA),
            ];
            let body = json!({ "query": q }).to_string();
            let (code, text) = http(Method::Post, &self.url, &hdrs, Some(body))
                .await
                .ok_or("network error or timeout")?;
            let v: Value =
                serde_json::from_str(&text).map_err(|_| format!("HTTP {code}, not JSON"))?;
            if let Some(e) = v
                .get("errors")
                .and_then(Value::as_array)
                .and_then(|a| a.first())
            {
                let msg = e
                    .get("message")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown error");
                return Err(format!("HTTP {code}: {msg}"));
            }
            if code != 200 {
                return Err(format!("HTTP {code}"));
            }
            Ok(v.get("data").cloned().unwrap_or(Value::Null))
        }

        async fn billing(&self, ws: &str) -> Option<Billing> {
            let q = format!(
                r#"{{ workspace(workspaceId: "{ws}") {{ customer {{ currentUsage usageLimit {{ hardLimit isOverLimit }} }} }} }}"#
            );
            match self.query(&q).await {
                Ok(d) => core::parse_billing(&d),
                Err(e) => {
                    console_warn!(
                        "watchdog: could not read the spending cap ({e}); assuming not capped"
                    );
                    None
                }
            }
        }

        async fn last_ran(&self, env_id: &str, service_id: &str) -> Option<String> {
            let q = format!(
                r#"{{ deployments(first: 20, input: {{ serviceId: "{service_id}", environmentId: "{env_id}" }}) {{ edges {{ node {{ id status }} }} }} }}"#
            );
            let d = self.query(&q).await.ok()?;
            let list: Vec<(String, String)> = d["deployments"]["edges"]
                .as_array()?
                .iter()
                .filter_map(|e| {
                    Some((
                        e["node"]["id"].as_str()?.to_string(),
                        e["node"]["status"].as_str()?.to_string(),
                    ))
                })
                .collect();
            core::last_ran(&list)
        }
    }

    // ---------- HTTP helper with a timeout ----------

    async fn http(
        method: Method,
        url: &str,
        headers: &[(&str, &str)],
        body: Option<String>,
    ) -> Option<(u16, String)> {
        let h = Headers::new();
        for (k, v) in headers {
            h.set(k, v).ok()?;
        }
        let mut init = RequestInit::new();
        init.with_method(method).with_headers(h);
        if let Some(b) = body {
            init.with_body(Some(wasm_bindgen::JsValue::from_str(&b)));
        }
        let req = Request::new_with_init(url, &init).ok()?;
        let fut = async move {
            let mut resp = Fetch::Request(req).send().await.ok()?;
            let text = resp.text().await.unwrap_or_default();
            Some((resp.status_code(), text))
        };
        match select(Box::pin(fut), Delay::from(HTTP_TIMEOUT)).await {
            Either::Left((r, _)) => r,
            Either::Right(_) => None,
        }
    }

    // ---------- alerts: one GitHub issue per incident ----------

    #[derive(Deserialize)]
    struct Issue {
        number: u64,
        #[serde(default)]
        body: Option<String>,
        #[serde(default)]
        pull_request: Option<Value>,
    }

    struct Gh {
        base: String,
        repo: String,
        auth: String,
    }

    impl Gh {
        async fn call(
            &self,
            method: Method,
            path: &str,
            body: Option<Value>,
        ) -> Option<(u16, String)> {
            let url = format!("{}/repos/{}{}", self.base, self.repo, path);
            let hdrs = [
                ("Authorization", self.auth.as_str()),
                ("Accept", "application/vnd.github+json"),
                ("X-GitHub-Api-Version", "2022-11-28"),
                ("User-Agent", UA),
                ("Content-Type", "application/json"),
            ];
            http(method, &url, &hdrs, body.map(|b| b.to_string())).await
        }

        /// Open issues carrying the key line, newest first (up to 500 open issues scanned).
        async fn open_with_key(&self) -> Option<Vec<u64>> {
            let mut out = Vec::new();
            for page in 1..=5 {
                let (code, text) = self
                    .call(
                        Method::Get,
                        &format!("/issues?state=open&per_page=100&page={page}"),
                        None,
                    )
                    .await?;
                if code != 200 {
                    console_warn!("watchdog github: list HTTP {code}");
                    return None;
                }
                let issues: Vec<Issue> = serde_json::from_str(&text).ok()?;
                let n = issues.len();
                out.extend(
                    issues
                        .into_iter()
                        .filter(|i| i.pull_request.is_none())
                        .filter(|i| i.body.as_deref().map(core::body_has_key).unwrap_or(false))
                        .map(|i| i.number),
                );
                if n < 100 {
                    break;
                }
            }
            Some(out)
        }

        async fn create(&self, title: &str, text: &str) -> bool {
            let body = json!({ "title": title, "body": core::issue_body(text) });
            matches!(
                self.call(Method::Post, "/issues", Some(body)).await,
                Some((201, _))
            )
        }

        async fn comment(&self, n: u64, text: &str) -> bool {
            matches!(
                self.call(
                    Method::Post,
                    &format!("/issues/{n}/comments"),
                    Some(json!({ "body": text }))
                )
                .await,
                Some((201, _))
            )
        }

        async fn close(&self, n: u64) -> bool {
            let body = json!({ "state": "closed", "state_reason": "completed" });
            matches!(
                self.call(Method::Patch, &format!("/issues/{n}"), Some(body))
                    .await,
                Some((200, _))
            )
        }

        async fn send(&self, m: &Msg) -> bool {
            let Some(open) = self.open_with_key().await else {
                return false;
            };
            match m.kind {
                // Already open (a retry after a lost response, or an older incident): add to it.
                MsgKind::Open | MsgKind::Comment => match open.first() {
                    Some(n) => self.comment(*n, &m.text).await,
                    None => {
                        let title = if m.title.is_empty() {
                            core::open_title(now_s())
                        } else {
                            m.title.clone()
                        };
                        self.create(&title, &m.text).await
                    }
                },
                MsgKind::Close => {
                    for n in open {
                        if !(self.comment(n, &m.text).await && self.close(n).await) {
                            return false;
                        }
                    }
                    true
                }
            }
        }
    }

    /// Send queued messages in order. Without GITHUB_TOKEN they are only logged.
    async fn deliver(env: &Env, mut st: State) -> State {
        if st.outbox.is_empty() {
            return st;
        }
        let Some(tok) = secret(env, "GITHUB_TOKEN") else {
            for m in st.outbox.drain(..) {
                console_log!(
                    "watchdog alert (GITHUB_TOKEN not set, log only) {:?}: {}",
                    m.kind,
                    m.text
                );
            }
            return st;
        };
        let gh = Gh {
            base: var(env, "GITHUB_API_BASE").unwrap_or_else(|| "https://api.github.com".into()),
            repo: var(env, "GITHUB_REPO").unwrap_or_else(|| "ecfromthedc/fleet-alerts".into()),
            auth: format!("Bearer {tok}"),
        };
        while let Some(m) = st.outbox.first().cloned() {
            console_log!("watchdog alert {:?}: {}", m.kind, m.text);
            if gh.send(&m).await {
                st.outbox.remove(0);
                continue;
            }
            // Keep order: stop here and retry this one next tick, a few times at most.
            let first = &mut st.outbox[0];
            first.tries += 1;
            console_warn!("watchdog github: send failed (try {})", first.tries);
            if first.tries >= core::MSG_MAX_TRIES {
                st.outbox.remove(0);
            }
            break;
        }
        st
    }
}
