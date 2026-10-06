//! railway-watchdog: brings stopped Railway services back on its own.
//! It runs on Cloudflare, outside Railway, because on 2026-10-06 Railway stopped every service
//! in the workspace at once; anything running inside Railway would have stopped too.
//! All decisions live in `core` (pure, unit-tested on the host). This file is only the
//! Cloudflare Worker glue: the Railway API, health checks, the Durable Object, and alerts.
//!
//! One run at a time, and nothing acted on before it is saved:
//!   1. take the lease from the `Brain` Durable Object (refused if another run holds it);
//!   2. read Railway, decide;
//!   3. save the decision to the Brain (refused if the lease was lost) -- only then act;
//!   4. deliver alerts, save again, release the lease.
//!
//! Durable Object storage is strongly consistent, unlike KV, so a later run always sees
//! the tries an earlier run recorded. KV (binding WATCHDOG) holds only:
//!
//! - `paused`: any non-empty value pauses all actions (alerts still drain)
//! - `state`: a read-only copy of the saved state, for people (`wrangler kv key get`)

pub mod core;

#[cfg(target_arch = "wasm32")]
mod worker_glue {
    use crate::core::{self, Action, Billing, Inputs, Msg, MsgKind, State as Brain};
    use futures_util::future::{select, Either};
    use serde::Deserialize;
    use serde_json::{json, Value};
    use std::collections::BTreeMap;
    use std::time::Duration;
    use worker::*;

    const HTTP_TIMEOUT: Duration = Duration::from_secs(10);
    const UA: &str = "railway-watchdog/0.1";
    /// Stop starting new work this long into a run, well inside the lease and before the
    /// next scheduled run a minute later.
    const RUN_DEADLINE_MS: u64 = 40_000;
    /// At most this many pages of projects (25 each) per run; more counts as a cut-off view.
    const MAX_PAGES: usize = 8;

    fn now_ms() -> u64 {
        Date::now().as_millis()
    }

    fn now_s() -> i64 {
        (now_ms() / 1000) as i64
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
        // Never throw: Cloudflare may retry a failed scheduled run. (A retry would still be
        // safe: the lease and the saved tries stop it from repeating an action.)
        if let Err(e) = tick(&env).await {
            console_error!("watchdog tick failed: {e}");
        }
    }

    // ---------- the Brain: one Durable Object holding the state and the lease ----------

    #[durable_object(fetch)]
    pub struct WatchdogBrain {
        state: State,
    }

    impl DurableObject for WatchdogBrain {
        fn new(state: State, _env: Env) -> Self {
            Self { state }
        }

        /// POST /begin {owner} -> 200 <saved state JSON> | 409 (another run holds the lease)
        /// POST /commit {owner, state} -> 200 | 409 (lease lost: do not act)
        /// POST /end {owner} -> 200
        /// Each handler only awaits storage, so the Durable Object's input gate makes the
        /// read-check-write of the lease atomic.
        async fn fetch(&self, mut req: Request) -> Result<Response> {
            let body: Value = req.json().await.unwrap_or(Value::Null);
            let owner = body["owner"].as_str().unwrap_or_default().to_string();
            if owner.is_empty() {
                return Response::error("owner required", 400);
            }
            let store = self.state.storage();
            let now = now_s();
            let lease: Option<core::Lease> = store
                .get::<String>("lease")
                .await?
                .and_then(|s| serde_json::from_str(&s).ok());
            match req.path().as_str() {
                "/begin" => {
                    match core::lease_take(lease.as_ref(), &owner, now, core::LEASE_TTL_S) {
                        None => Response::error("lease held by another run", 409),
                        Some(l) => {
                            store.put("lease", serde_json::to_string(&l)?).await?;
                            let saved = store.get::<String>("state").await?.unwrap_or_default();
                            Response::ok(saved)
                        }
                    }
                }
                "/commit" => {
                    if !core::lease_held(lease.as_ref(), &owner, now) {
                        return Response::error("lease lost", 409);
                    }
                    store.put("state", body["state"].to_string()).await?;
                    Response::ok("saved")
                }
                "/end" => {
                    if lease.map(|l| l.owner == owner).unwrap_or(false) {
                        store.delete("lease").await?;
                    }
                    Response::ok("released")
                }
                _ => Response::error("not found", 404),
            }
        }
    }

    async fn brain(env: &Env, path: &str, body: Value) -> Result<(u16, String)> {
        let stub = env
            .durable_object("BRAIN")?
            .id_from_name("watchdog")?
            .get_stub()?;
        let mut init = RequestInit::new();
        init.with_method(Method::Post)
            .with_body(Some(wasm_bindgen::JsValue::from_str(&body.to_string())));
        let req = Request::new_with_init(&format!("https://brain{path}"), &init)?;
        let mut resp = stub.fetch_with_request(req).await?;
        let text = resp.text().await.unwrap_or_default();
        Ok((resp.status_code(), text))
    }

    /// Save `st` while still holding the lease. False means: do not act.
    async fn commit(env: &Env, owner: &str, st: &Brain) -> bool {
        match brain(env, "/commit", json!({ "owner": owner, "state": st })).await {
            Ok((200, _)) => true,
            Ok((code, why)) => {
                console_warn!("watchdog: save refused ({code} {why}); not acting");
                false
            }
            Err(e) => {
                console_warn!("watchdog: save failed ({e}); not acting");
                false
            }
        }
    }

    async fn tick(env: &Env) -> Result<()> {
        let started = now_ms();
        let owner = format!("{started:x}-{:x}", (js_sys::Math::random() * 1e15) as u64);
        let (code, saved) = brain(env, "/begin", json!({ "owner": owner })).await?;
        if code == 409 {
            console_log!("watchdog: another run is still going; skipping this one");
            return Ok(());
        }
        if code != 200 {
            return Err(Error::RustError(format!("brain /begin: HTTP {code}")));
        }
        let old: Brain = if saved.trim().is_empty() {
            Brain::default()
        } else {
            match serde_json::from_str(&saved) {
                Ok(s) => s,
                Err(e) => {
                    // Fail closed: without the saved tries we cannot respect the limits.
                    console_error!("watchdog: saved state unreadable ({e}); doing nothing");
                    let _ = brain(env, "/end", json!({ "owner": owner })).await;
                    return Ok(());
                }
            }
        };

        let kv = env.kv("WATCHDOG")?;
        let paused = kv
            .get("paused")
            .text()
            .await
            .ok()
            .flatten()
            .map(|v| !v.trim().is_empty())
            .unwrap_or(false);
        let (st, actions) = if paused {
            console_log!("watchdog paused (KV key 'paused' is set): no actions");
            (old.clone(), vec![])
        } else {
            check(env, old.clone()).await
        };

        // Save the decision BEFORE acting, so an overlapping or retried run sees these tries.
        let mut saved_st = old.clone();
        if st != old || !actions.is_empty() {
            if !commit(env, &owner, &st).await {
                return Ok(());
            }
            saved_st = st.clone();
        }

        if !actions.is_empty() {
            let rw = Railway::new(env).expect("actions imply a token");
            for a in &actions {
                if now_ms() - started > RUN_DEADLINE_MS {
                    // Already counted as a try, so the limits stay conservative.
                    console_warn!("watchdog: run deadline reached; skipping {a:?}");
                    continue;
                }
                let out = act(&rw, a).await;
                console_log!("watchdog action {a:?}: {out}");
            }
        }

        let delivered = deliver(env, saved_st.clone(), started).await;
        if delivered != saved_st && commit(env, &owner, &delivered).await {
            saved_st = delivered;
        }
        if saved_st != old {
            // A copy for people to read; never read back by the watchdog.
            let _ = kv
                .put("state", serde_json::to_string(&saved_st)?)?
                .execute()
                .await;
        }
        let _ = brain(env, "/end", json!({ "owner": owner })).await;
        Ok(())
    }

    /// Look at Railway and decide. A failed read decides nothing and counts toward an alert.
    async fn check(env: &Env, st: Brain) -> (Brain, Vec<Action>) {
        let Some(rw) = Railway::new(env) else {
            // The intended "not armed yet" state: say so, change nothing.
            console_warn!("watchdog: RAILWAY_TOKEN is not set; watching nothing");
            return (st, vec![]);
        };
        let now = now_s();
        let Some(ws) = var(env, "WORKSPACE_ID").filter(|w| core::is_id(w)) else {
            return (
                core::record_read_failure(st, now, "WORKSPACE_ID is missing or malformed"),
                vec![],
            );
        };
        let watch = match core::parse_watch(&var(env, "WATCH").unwrap_or_default()) {
            Ok(w) => w,
            Err(e) => return (core::record_read_failure(st, now, &e), vec![]),
        };
        let mut pages = Vec::new();
        let mut after: Option<String> = None;
        let mut truncated = false;
        loop {
            match rw.query(&services_query(&ws, after.as_deref())).await {
                Ok(page) => {
                    after = core::next_cursor(&page);
                    pages.push(page);
                }
                Err(e) => {
                    console_warn!("watchdog: could not read Railway: {e}");
                    return (core::record_read_failure(st, now, &e), vec![]);
                }
            }
            if after.is_none() {
                break;
            }
            if pages.len() >= MAX_PAGES {
                truncated = true;
                break;
            }
        }
        let mut view = core::collect(&pages, &watch);
        view.truncated |= truncated;
        if !view.missing.is_empty() || view.truncated {
            console_error!(
                "watchdog: incomplete view (missing {:?}, cut off {})",
                view.missing,
                view.truncated
            );
        }

        let mut health = BTreeMap::new();
        for s in view
            .services
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

        let billing = if core::needs_attention(&view, &health) {
            rw.billing(&ws).await
        } else {
            None
        };
        let limits = core::parse_limits(|k| var(env, k));
        let inp = Inputs {
            now,
            view: &view,
            health: &health,
            billing,
        };
        core::decide(&inp, &limits, st)
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
                                Err(e) => console_warn!(
                                    "watchdog: restoring {id} failed ({e}); building latest instead"
                                ),
                            }
                        }
                        None => {
                            console_log!(
                                "watchdog: no earlier deployment to restore; building latest"
                            )
                        }
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

    fn services_query(ws: &str, after: Option<&str>) -> String {
        let after = after
            .map(|c| format!(r#", after: {}"#, Value::String(c.to_string())))
            .unwrap_or_default();
        format!(
            r#"{{ projects(workspaceId: "{ws}", first: 25{after}) {{ pageInfo {{ hasNextPage endCursor }}
            edges {{ node {{ name environments {{ pageInfo {{ hasNextPage }} edges {{ node {{ id name
            serviceInstances {{ pageInfo {{ hasNextPage }} edges {{ node {{ serviceId serviceName cronSchedule
            source {{ image }} latestDeployment {{ status }} activeDeployments {{ id status }} }} }} }} }} }} }} }} }} }} }}"#
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

        /// None means unknown, and unknown means "restart nothing" (see core::decide).
        async fn billing(&self, ws: &str) -> Option<Billing> {
            let q = format!(
                r#"{{ workspace(workspaceId: "{ws}") {{ customer {{ currentUsage usageLimit {{ hardLimit isOverLimit }} }} }} }}"#
            );
            match self.query(&q).await {
                Ok(d) => {
                    let b = core::parse_billing(&d);
                    if b.is_none() {
                        console_warn!("watchdog: Railway's spending-cap answer was incomplete");
                    }
                    b
                }
                Err(e) => {
                    console_warn!("watchdog: could not read the spending cap ({e})");
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
    async fn deliver(env: &Env, mut st: Brain, started: u64) -> Brain {
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
            if now_ms() - started > RUN_DEADLINE_MS {
                break;
            }
            console_log!("watchdog alert {:?}: {}", m.kind, m.text);
            if gh.send(&m).await {
                st.outbox.remove(0);
                continue;
            }
            // Keep order: stop here and retry this one next run, a few times at most.
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
