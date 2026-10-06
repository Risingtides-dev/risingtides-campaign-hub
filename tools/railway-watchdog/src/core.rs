//! Pure, platform-free logic: reading Railway's answer, deciding which services to bring
//! back, rate limits, and the plain-English alert text. No I/O here, so it all runs under
//! plain `cargo test` on the host. The Worker glue in `lib.rs` asks Railway, calls
//! `decide`, performs the actions it returns, and delivers the queued messages.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};

pub const DEFAULT_COOLDOWN_S: i64 = 600;
pub const DEFAULT_MAX_TRIES: usize = 3;
pub const DEFAULT_WINDOW_S: i64 = 7200;
pub const DEFAULT_HEALTH_FAILS: u32 = 3;
pub const DEFAULT_MAX_ACTIONS_PER_HOUR: usize = 40;
/// Stop retrying one alert message after this many failed sends.
pub const MSG_MAX_TRIES: u8 = 3;
/// At most this many actions per run: each costs up to 3 Railway calls, and a Worker run on
/// Cloudflare's free plan may make only 50 outbound requests. The rest wait a minute.
pub const MAX_ACTIONS_PER_TICK: usize = 10;
/// Never let undelivered messages pile up without bound.
pub const MAX_OUTBOX: usize = 20;
/// Every alert issue carries this exact line, so later updates find the same issue.
pub const ISSUE_KEY_LINE: &str = "key: RAILWAY-WATCHDOG";

// ---------- config ----------

/// One Railway environment to look after (from the WATCH var, a JSON list).
#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
pub struct WatchEnv {
    /// Railway environment id.
    pub env: String,
    /// Service name -> health URL. A running service whose URL keeps failing gets restarted.
    #[serde(default)]
    pub health: BTreeMap<String, String>,
    /// Service names the watchdog must never touch.
    #[serde(default)]
    pub skip: Vec<String>,
}

pub fn is_id(s: &str) -> bool {
    !s.is_empty() && s.len() <= 64 && s.chars().all(|c| c.is_ascii_hexdigit() || c == '-')
}

pub fn parse_watch(s: &str) -> Result<Vec<WatchEnv>, String> {
    let v: Vec<WatchEnv> =
        serde_json::from_str(s).map_err(|e| format!("WATCH is not valid JSON: {e}"))?;
    if v.is_empty() {
        return Err("WATCH lists no environments".into());
    }
    for w in &v {
        if !is_id(&w.env) {
            return Err(format!("WATCH has a bad environment id: {:?}", w.env));
        }
        if let Some(u) = w
            .health
            .values()
            .find(|u| !u.starts_with("https://") && !u.starts_with("http://"))
        {
            return Err(format!("WATCH has a health URL that is not http(s): {u:?}"));
        }
    }
    Ok(v)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Limits {
    /// Wait at least this long between two actions on the same service.
    pub cooldown_s: i64,
    /// At most this many actions per service inside `window_s`; then a person is paged.
    pub max_tries: usize,
    pub window_s: i64,
    /// Restart a running service after this many failed health checks in a row.
    pub health_fails: u32,
    /// Hard ceiling on actions across everything, so a bug can never run up a bill.
    pub max_actions_per_hour: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Limits {
            cooldown_s: DEFAULT_COOLDOWN_S,
            max_tries: DEFAULT_MAX_TRIES,
            window_s: DEFAULT_WINDOW_S,
            health_fails: DEFAULT_HEALTH_FAILS,
            max_actions_per_hour: DEFAULT_MAX_ACTIONS_PER_HOUR,
        }
    }
}

/// Read the optional limit vars, clamped to sane ranges; anything missing or garbled keeps the default.
pub fn parse_limits(get: impl Fn(&str) -> Option<String>) -> Limits {
    let d = Limits::default();
    let num = |k: &str, lo: i64, hi: i64, dflt: i64| -> i64 {
        get(k)
            .and_then(|v| v.trim().parse::<i64>().ok())
            .map(|n| n.clamp(lo, hi))
            .unwrap_or(dflt)
    };
    Limits {
        cooldown_s: num("COOLDOWN_S", 60, 86_400, d.cooldown_s),
        max_tries: num("MAX_TRIES", 1, 20, d.max_tries as i64) as usize,
        window_s: num("WINDOW_S", 600, 7 * 86_400, d.window_s),
        health_fails: num("HEALTH_FAILS", 1, 60, d.health_fails as i64) as u32,
        max_actions_per_hour: num(
            "MAX_ACTIONS_PER_HOUR",
            1,
            500,
            d.max_actions_per_hour as i64,
        ) as usize,
    }
}

// ---------- what Railway reports ----------

/// One service in one watched environment, as Railway reports it this tick.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Svc {
    /// "<environment id>/<service id>": stable even if a service is renamed.
    pub key: String,
    pub env_id: String,
    pub service_id: String,
    pub name: String,
    /// "<project> / <environment>", for messages.
    pub place: String,
    /// Deployed from a Docker image (databases). Code services in the same environment
    /// wait for these to be up before they are brought back.
    pub image: bool,
    pub cron: bool,
    /// Status of the newest deployment (Railway omits it once every deployment is removed).
    pub latest: Option<String>,
    /// (deployment id, status) of the deployments Railway counts as active.
    pub active: Vec<(String, String)>,
    pub health_url: Option<String>,
}

fn s(v: &Value, k: &str) -> Option<String> {
    v.get(k).and_then(Value::as_str).map(str::to_string)
}

fn edges<'a>(v: &'a Value, k: &str) -> impl Iterator<Item = &'a Value> {
    v.get(k)
        .and_then(|x| x.get("edges"))
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|e| e.get("node"))
}

fn has_next_page(v: &Value, k: &str) -> bool {
    v.get(k)
        .and_then(|x| x.get("pageInfo"))
        .and_then(|p| p.get("hasNextPage"))
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

/// The cursor for the next page of projects, if Railway says there is one.
pub fn next_cursor(page: &Value) -> Option<String> {
    if !has_next_page(page, "projects") {
        return None;
    }
    page.get("projects")?
        .get("pageInfo")?
        .get("endCursor")?
        .as_str()
        .map(str::to_string)
}

/// What the watchdog could see this tick.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct View {
    pub services: Vec<Svc>,
    /// Watched environment ids Railway did not list (a typo, a deleted environment, or a
    /// token that cannot see them).
    pub missing: Vec<String>,
    /// Some list came back cut short (a nested page), so the view may be incomplete.
    pub truncated: bool,
}

/// Turn the pages of the `projects(workspaceId)` answer into the watched services.
pub fn collect(pages: &[Value], watch: &[WatchEnv]) -> View {
    let mut found = BTreeSet::new();
    let mut by_env: BTreeMap<String, Vec<Svc>> = BTreeMap::new();
    let mut truncated = false;
    for p in pages.iter().flat_map(|page| edges(page, "projects")) {
        let project = s(p, "name").unwrap_or_default();
        truncated |= has_next_page(p, "environments");
        for e in edges(p, "environments") {
            let Some(env_id) = s(e, "id") else { continue };
            let Some(w) = watch.iter().find(|w| w.env == env_id) else {
                continue;
            };
            found.insert(env_id.clone());
            truncated |= has_next_page(e, "serviceInstances");
            let place = format!("{project} / {}", s(e, "name").unwrap_or_default());
            for si in edges(e, "serviceInstances") {
                let (Some(service_id), Some(name)) = (s(si, "serviceId"), s(si, "serviceName"))
                else {
                    continue;
                };
                if w.skip.iter().any(|n| n == &name) {
                    continue;
                }
                let active = si
                    .get("activeDeployments")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .filter_map(|d| Some((s(d, "id")?, s(d, "status")?)))
                    .collect();
                by_env.entry(env_id.clone()).or_default().push(Svc {
                    key: format!("{env_id}/{service_id}"),
                    env_id: env_id.clone(),
                    service_id,
                    place: place.clone(),
                    image: si
                        .get("source")
                        .and_then(|x| x.get("image"))
                        .and_then(Value::as_str)
                        .is_some(),
                    cron: si.get("cronSchedule").and_then(Value::as_str).is_some(),
                    latest: si.get("latestDeployment").and_then(|d| s(d, "status")),
                    active,
                    health_url: w.health.get(&name).cloned(),
                    name,
                });
            }
        }
    }
    // Keep the WATCH order, so messages read in the order the operator listed things.
    let mut out = Vec::new();
    for w in watch {
        out.extend(by_env.remove(&w.env).unwrap_or_default());
    }
    let missing = watch
        .iter()
        .map(|w| w.env.clone())
        .filter(|e| !found.contains(e))
        .collect();
    View {
        services: out,
        missing,
        truncated,
    }
}

/// Pick the deployment that last actually ran (newest first): the one to restore.
/// Failed builds never ran; removed, crashed or live ones did.
pub fn last_ran(newest_first: &[(String, String)]) -> Option<String> {
    newest_first
        .iter()
        .find(|(_, st)| matches!(st.as_str(), "REMOVED" | "CRASHED" | "SUCCESS" | "SLEEPING"))
        .map(|(id, _)| id.clone())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    Up,
    /// A deploy is in flight: leave it alone.
    Starting,
    Down,
}

const UP: [&str; 2] = ["SUCCESS", "SLEEPING"];
const STARTING: [&str; 7] = [
    "QUEUED",
    "WAITING",
    "INITIALIZING",
    "BUILDING",
    "DEPLOYING",
    "NEEDS_APPROVAL",
    "REMOVING",
];

pub fn phase(s: &Svc) -> Phase {
    if s.active.iter().any(|(_, st)| UP.contains(&st.as_str())) {
        return Phase::Up;
    }
    match s.latest.as_deref() {
        Some(st) if UP.contains(&st) => Phase::Up,
        Some(st) if STARTING.contains(&st) => Phase::Starting,
        // A cron job exits between runs and a failed run shows as CRASHED, which is not
        // "stopped". Only a cron with nothing deployed (or a failed build) is down.
        Some(st) if s.cron => {
            if matches!(st, "REMOVED" | "FAILED") {
                Phase::Down
            } else {
                Phase::Up
            }
        }
        _ => Phase::Down,
    }
}

fn running_deployment(s: &Svc) -> Option<String> {
    s.active
        .iter()
        .find(|(_, st)| UP.contains(&st.as_str()))
        .map(|(id, _)| id.clone())
}

// ---------- spending cap ----------

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Billing {
    pub over_limit: bool,
    pub usage: Option<f64>,
    pub hard_limit: Option<f64>,
}

/// Read `workspace { customer { currentUsage usageLimit { hardLimit isOverLimit } } }`.
/// Returns a definite answer or None ("unknown"); it never guesses "not capped".
/// `usageLimit: null` is definite: the workspace has no limit set.
pub fn parse_billing(data: &Value) -> Option<Billing> {
    let c = data.get("workspace")?.get("customer")?;
    if !c.is_object() {
        return None;
    }
    let usage = c.get("currentUsage").and_then(Value::as_f64);
    match c.get("usageLimit")? {
        Value::Null => Some(Billing {
            over_limit: false,
            usage,
            hard_limit: None,
        }),
        lim => Some(Billing {
            over_limit: lim.get("isOverLimit")?.as_bool()?,
            usage,
            hard_limit: lim.get("hardLimit").and_then(Value::as_f64),
        }),
    }
}

// ---------- state (kept in the Durable Object) ----------

/// Alert after this many runs in a row that could not read Railway at all.
pub const READ_FAILS_ALERT: u32 = 5;
/// Alert after this many runs in a row where something was down but the cap was unreadable.
pub const BILLING_UNKNOWN_ALERT: u32 = 3;
/// Alert after this many runs in a row with an incomplete view of the watched services.
pub const BLIND_ALERT: u32 = 3;

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct State {
    /// Runs in a row that could not read Railway.
    #[serde(default)]
    pub read_fails: u32,
    /// Runs in a row where something was down and the spending cap could not be read.
    #[serde(default)]
    pub billing_unknown: u32,
    /// Runs in a row that saw no services, missed a watched environment, or got a cut-off list.
    #[serde(default)]
    pub blind: u32,
    /// Service key -> when the watchdog acted on it, inside the rolling window.
    #[serde(default)]
    pub tries: BTreeMap<String, Vec<i64>>,
    /// Service key -> failed health checks in a row.
    #[serde(default)]
    pub health_fails: BTreeMap<String, u32>,
    /// Services whose last-running deployment was already restored inside the window; the
    /// next try builds fresh instead of restoring the same thing again.
    #[serde(default)]
    pub restored: BTreeSet<String>,
    #[serde(default)]
    pub incident: Option<Incident>,
    /// Alert messages not yet delivered, oldest first.
    #[serde(default)]
    pub outbox: Vec<Msg>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Incident {
    pub opened_at: i64,
    /// Services that used up their tries in this incident (paged once each).
    #[serde(default)]
    pub gave_up: BTreeSet<String>,
    #[serde(default)]
    pub cap_noted: bool,
    #[serde(default)]
    pub budget_noted: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum MsgKind {
    /// Open the alert issue (or add to the one already open).
    Open,
    /// Add an update to the open alert issue.
    Comment,
    /// Say it is over and close the alert issue.
    Close,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Msg {
    pub kind: MsgKind,
    pub title: String,
    pub text: String,
    #[serde(default)]
    pub tries: u8,
}

impl State {
    fn push(&mut self, kind: MsgKind, title: String, text: String) {
        self.outbox.push(Msg {
            kind,
            title,
            text,
            tries: 0,
        });
        if self.outbox.len() > MAX_OUTBOX {
            let extra = self.outbox.len() - MAX_OUTBOX;
            self.outbox.drain(0..extra);
        }
    }

    /// Open the incident if needed (queuing an Open), else queue a Comment.
    fn report(&mut self, now: i64, text: String) {
        if self.incident.is_none() {
            self.incident = Some(Incident {
                opened_at: now,
                ..Default::default()
            });
            self.push(MsgKind::Open, open_title(now), text);
        } else {
            self.push(MsgKind::Comment, String::new(), text);
        }
    }
}

// ---------- the decision ----------

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Action {
    /// Bring a stopped service back. `restore`: redeploy the deployment that last ran, from
    /// its already-built image (exactly what was serving). Otherwise build its latest source.
    Revive {
        key: String,
        env_id: String,
        service_id: String,
        name: String,
        restore: bool,
    },
    /// Restart a running service whose health check keeps failing.
    Restart {
        key: String,
        deployment_id: String,
        name: String,
    },
}

pub struct Inputs<'a> {
    pub now: i64,
    pub view: &'a View,
    /// Service key -> did its health URL answer 2xx this tick. Only services that are up
    /// and have a URL are checked.
    pub health: &'a BTreeMap<String, bool>,
    /// None when Railway would not say. Unknown is treated as "maybe capped": no actions.
    pub billing: Option<Billing>,
}

/// A run could not read Railway at all (network, auth, bad config). Nothing is decided;
/// after READ_FAILS_ALERT runs in a row, a person is told, once per streak.
pub fn record_read_failure(mut st: State, now: i64, err: &str) -> State {
    st.read_fails = st.read_fails.saturating_add(1);
    if st.read_fails == READ_FAILS_ALERT {
        st.report(now, read_fail_text(err, st.read_fails));
    }
    st
}

// ---------- one run at a time (the lease, held in the Durable Object) ----------

/// How long a run may hold the lease. A run stops starting new work well before this
/// (see `RUN_DEADLINE_MS` in the glue), and the next scheduled run is 60 s later.
pub const LEASE_TTL_S: i64 = 90;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Lease {
    pub owner: String,
    pub until: i64,
}

/// Grant the lease to `owner` unless someone else holds an unexpired one.
pub fn lease_take(cur: Option<&Lease>, owner: &str, now: i64, ttl: i64) -> Option<Lease> {
    match cur {
        Some(l) if l.until > now && l.owner != owner => None,
        _ => Some(Lease {
            owner: owner.to_string(),
            until: now + ttl,
        }),
    }
}

/// Does `owner` still hold the lease? A run that lost it must not act or save.
pub fn lease_held(cur: Option<&Lease>, owner: &str, now: i64) -> bool {
    matches!(cur, Some(l) if l.owner == owner && l.until > now)
}

/// Is anything wrong enough that the glue should spend an API call on the spending cap?
pub fn needs_attention(view: &View, health: &BTreeMap<String, bool>) -> bool {
    view.services.iter().any(|s| phase(s) == Phase::Down) || health.values().any(|ok| !ok)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Why {
    Down,
    Unhealthy(u32),
}

pub fn decide(inp: &Inputs, lim: &Limits, mut st: State) -> (State, Vec<Action>) {
    let now = inp.now;
    let services = inp.view.services.as_slice();
    // This run read Railway, so the read-failure streak is over.
    st.read_fails = 0;

    // Seeing nothing is not the same as everything being fine.
    let blind = services.is_empty() || !inp.view.missing.is_empty() || inp.view.truncated;
    if blind {
        st.blind = st.blind.saturating_add(1);
        if st.blind == BLIND_ALERT {
            st.report(now, blind_text(inp.view));
        }
    } else {
        st.blind = 0;
    }

    for v in st.tries.values_mut() {
        v.retain(|t| now - *t < lim.window_s);
    }
    st.tries.retain(|_, v| !v.is_empty());
    let tried = st.tries.clone();
    st.restored.retain(|k| tried.contains_key(k));

    let phases: BTreeMap<&str, Phase> = services
        .iter()
        .map(|s| (s.key.as_str(), phase(s)))
        .collect();
    for s in services {
        if phases[s.key.as_str()] != Phase::Up {
            st.health_fails.remove(&s.key);
            continue;
        }
        match inp.health.get(&s.key) {
            Some(true) => {
                st.health_fails.remove(&s.key);
            }
            Some(false) => *st.health_fails.entry(s.key.clone()).or_insert(0) += 1,
            None => {}
        }
    }
    st.health_fails
        .retain(|k, _| services.iter().any(|s| &s.key == k));
    let fails = |st: &State, k: &str| st.health_fails.get(k).copied().unwrap_or(0);

    let all_ok = !blind
        && services
            .iter()
            .all(|s| phases[s.key.as_str()] == Phase::Up && fails(&st, &s.key) == 0);
    if all_ok {
        st.billing_unknown = 0;
        if let Some(inc) = st.incident.take() {
            st.push(
                MsgKind::Close,
                String::new(),
                resolved_text(inc.opened_at, now),
            );
        }
        return (st, vec![]);
    }

    let sick: Vec<(&Svc, Why)> = services
        .iter()
        .filter_map(|s| match phases[s.key.as_str()] {
            Phase::Down => Some((s, Why::Down)),
            Phase::Up if fails(&st, &s.key) >= lim.health_fails => {
                Some((s, Why::Unhealthy(fails(&st, &s.key))))
            }
            _ => None,
        })
        .collect();
    if sick.is_empty() {
        // Only deploys in flight, a short health blip, or an incomplete view: wait.
        st.billing_unknown = 0;
        return (st, vec![]);
    }

    // Fail closed: if Railway will not say whether the workspace is over its spending cap,
    // restart nothing. Restarting into a cap is exactly what this tool must never do.
    let Some(billing) = inp.billing else {
        st.billing_unknown = st.billing_unknown.saturating_add(1);
        if st.billing_unknown == BILLING_UNKNOWN_ALERT {
            st.report(now, billing_unknown_text(sick.len()));
        }
        return (st, vec![]);
    };
    st.billing_unknown = 0;

    // Never fight a spending cap: redeploying would only be stopped again or run up the bill.
    if billing.over_limit {
        let noted = st.incident.as_ref().map(|i| i.cap_noted).unwrap_or(false);
        if !noted {
            st.report(now, cap_text(billing, sick.len()));
            if let Some(i) = st.incident.as_mut() {
                i.cap_noted = true;
            }
        }
        return (st, vec![]);
    }

    let gave_up: BTreeSet<String> = st
        .incident
        .as_ref()
        .map(|i| i.gave_up.clone())
        .unwrap_or_default();
    let used_this_hour: usize = st
        .tries
        .values()
        .flatten()
        .filter(|t| now - **t < 3600)
        .count();
    let mut budget = lim.max_actions_per_hour.saturating_sub(used_this_hour);
    let mut notes = Vec::new();
    let mut newly_gave_up = Vec::new();
    let mut budget_hit = false;
    let mut actions = Vec::new();

    for (s, why) in sick {
        // Code services come back only after the databases in their environment are up
        // (unless a database has been given up on, so one broken image cannot block the rest).
        let db_pending = services.iter().any(|d| {
            d.image
                && d.env_id == s.env_id
                && d.key != s.key
                && phases[d.key.as_str()] != Phase::Up
                && !gave_up.contains(&d.key)
        });
        if !s.image && db_pending {
            continue;
        }
        let tries = st.tries.get(&s.key).map(Vec::len).unwrap_or(0);
        if tries >= lim.max_tries {
            if !gave_up.contains(&s.key) {
                newly_gave_up.push(s.key.clone());
                notes.push(gave_up_text(s, lim));
            }
            continue;
        }
        if let Some(last) = st.tries.get(&s.key).and_then(|v| v.last()) {
            if now - last < lim.cooldown_s {
                continue;
            }
        }
        if actions.len() >= MAX_ACTIONS_PER_TICK {
            break;
        }
        if budget == 0 {
            budget_hit = true;
            break;
        }
        budget -= 1;
        let action = match (why, running_deployment(s)) {
            (Why::Unhealthy(_), Some(deployment_id)) => {
                st.health_fails.remove(&s.key);
                Action::Restart {
                    key: s.key.clone(),
                    deployment_id,
                    name: s.name.clone(),
                }
            }
            _ => Action::Revive {
                key: s.key.clone(),
                env_id: s.env_id.clone(),
                service_id: s.service_id.clone(),
                name: s.name.clone(),
                restore: !st.restored.contains(&s.key),
            },
        };
        let restore = matches!(action, Action::Revive { restore: true, .. });
        if restore {
            st.restored.insert(s.key.clone());
        }
        st.tries.entry(s.key.clone()).or_default().push(now);
        notes.push(action_text(s, why, restore, tries + 1, lim));
        actions.push(action);
    }

    let budget_noted = st
        .incident
        .as_ref()
        .map(|i| i.budget_noted)
        .unwrap_or(false);
    if budget_hit && !budget_noted {
        notes.push(format!(
            "The watchdog has hit its safety limit of {} restarts in an hour, so it is pausing. \
             It will carry on as older restarts age out. If this keeps happening, something bigger is wrong.",
            lim.max_actions_per_hour
        ));
    }
    if !notes.is_empty() {
        st.report(now, notes.join("\n\n"));
    }
    if let Some(i) = st.incident.as_mut() {
        i.budget_noted |= budget_hit;
        i.gave_up.extend(newly_gave_up);
    }
    (st, actions)
}

// ---------- plain-English text ----------

pub fn open_title(now: i64) -> String {
    format!(
        "Railway services stopped - watchdog is bringing them back ({})",
        fmt_et(now)
    )
}

pub fn issue_body(text: &str) -> String {
    format!("{ISSUE_KEY_LINE}\n\n{text}")
}

/// True if any line of `body` is exactly the key line.
pub fn body_has_key(body: &str) -> bool {
    body.lines()
        .any(|l| l.trim_end_matches('\r') == ISSUE_KEY_LINE)
}

fn action_text(s: &Svc, why: Why, restore: bool, attempt: usize, lim: &Limits) -> String {
    let what = match why {
        Why::Down => {
            if restore {
                "was not running. Brought back the exact version that was running before."
                    .to_string()
            } else {
                "was still not running. Started a fresh build of its latest code.".to_string()
            }
        }
        Why::Unhealthy(n) => {
            format!("was running, but its health check failed {n} times in a row. Restarted it.")
        }
    };
    format!(
        "**{}** ({}) {what} (Try {attempt} of {} in {} hours.)",
        s.name,
        s.place,
        lim.max_tries,
        lim.window_s / 3600
    )
}

fn gave_up_text(s: &Svc, lim: &Limits) -> String {
    format!(
        "**{}** ({}) is still down after {} tries. The watchdog is stopping for now so it does not \
         loop. A person needs to look at it in the Railway dashboard. The watchdog will try again \
         in about {} hours.",
        s.name,
        s.place,
        lim.max_tries,
        lim.window_s / 3600
    )
}

fn money(v: Option<f64>) -> String {
    v.map(|x| format!("${x:.2}"))
        .unwrap_or_else(|| "unknown".into())
}

fn cap_text(b: Billing, down: usize) -> String {
    format!(
        "Railway says this workspace is **over its spending cap** (used {} of a {} hard limit). \
         When that happens Railway shuts services down, and restarting them would only be stopped \
         again. {down} service(s) are down. The watchdog is **not** restarting anything. A Railway \
         workspace admin needs to raise the limit (Workspace settings, Usage). Once Railway says \
         the workspace is under its cap again, the watchdog brings everything back on its own.",
        money(b.usage),
        money(b.hard_limit)
    )
}

fn read_fail_text(err: &str, runs: u32) -> String {
    format!(
        "The watchdog **cannot read Railway** ({runs} checks in a row, about {runs} minutes). \
         While this lasts it cannot see or fix anything. Last error: `{err}`. Check that \
         RAILWAY_TOKEN is still valid and that the Railway API is up."
    )
}

fn billing_unknown_text(down: usize) -> String {
    format!(
        "{down} service(s) are down, but Railway will not say whether the workspace is over its \
         spending cap. The watchdog is **not** restarting anything, because restarting into a \
         cap is the one thing it must never do. A person needs to check the Railway dashboard \
         (Workspace settings, Usage). If the token cannot read billing, give it one that can."
    )
}

fn blind_text(view: &View) -> String {
    let what = if view.services.is_empty() {
        "it **cannot see any services**".to_string()
    } else if !view.missing.is_empty() {
        format!(
            "Railway is not listing {} watched environment(s): {}",
            view.missing.len(),
            view.missing.join(", ")
        )
    } else {
        "Railway's list came back cut short".to_string()
    };
    format!(
        "The watchdog's view is incomplete: {what}. It will not say \"everything is fine\" \
         until it can see every watched environment. Check the WATCH list and that the token \
         can see these projects."
    )
}

fn resolved_text(opened_at: i64, now: i64) -> String {
    let mins = ((now - opened_at).max(0) + 59) / 60;
    format!(
        "Everything is running again. The trouble started {} and was fixed by {} (about {mins} minutes).",
        fmt_et(opened_at),
        fmt_et(now)
    )
}

// ---------- US Eastern time without a tz database ----------

/// Days since 1970-01-01 -> (year, month 1-12, day 1-31). Howard Hinnant's algorithm.
pub fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

pub fn days_from_civil(y: i64, m: u32, d: u32) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y.rem_euclid(400);
    let m = m as i64;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d as i64 - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// 0 = Sunday.
fn weekday(days: i64) -> u32 {
    (days + 4).rem_euclid(7) as u32
}

/// Day-of-month of the n-th Sunday (n >= 1) of y/m.
fn nth_sunday(y: i64, m: u32, n: u32) -> u32 {
    let first = days_from_civil(y, m, 1);
    let wd = weekday(first);
    1 + (7 - wd) % 7 + 7 * (n - 1)
}

/// US Eastern DST (since 2007): 2nd Sunday of March 07:00 UTC .. 1st Sunday of Nov 06:00 UTC.
pub fn is_edt(epoch: i64) -> bool {
    let (y, _, _) = civil_from_days(epoch.div_euclid(86_400));
    let start = days_from_civil(y, 3, nth_sunday(y, 3, 2)) * 86_400 + 7 * 3600;
    let end = days_from_civil(y, 11, nth_sunday(y, 11, 1)) * 86_400 + 6 * 3600;
    epoch >= start && epoch < end
}

/// e.g. "Tue Oct 6, 7:43 AM EDT".
pub fn fmt_et(epoch: i64) -> String {
    let edt = is_edt(epoch);
    let local = epoch + if edt { -4 * 3600 } else { -5 * 3600 };
    let days = local.div_euclid(86_400);
    let secs = local.rem_euclid(86_400);
    let (_, m, d) = civil_from_days(days);
    const WD: [&str; 7] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const MO: [&str; 12] = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    let (h24, min) = (secs / 3600, (secs % 3600) / 60);
    let (h12, ampm) = match h24 {
        0 => (12, "AM"),
        1..=11 => (h24, "AM"),
        12 => (12, "PM"),
        _ => (h24 - 12, "PM"),
    };
    format!(
        "{} {} {}, {}:{:02} {} {}",
        WD[weekday(days) as usize],
        MO[(m - 1) as usize],
        d,
        h12,
        min,
        ampm,
        if edt { "EDT" } else { "EST" }
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const T0: i64 = 1_791_287_000; // Tue Oct 6 2026, ~7:43 AM EDT
    /// Railway said: not over the cap (no limit set).
    const OK: Option<Billing> = Some(Billing {
        over_limit: false,
        usage: None,
        hard_limit: None,
    });

    fn svc(name: &str, image: bool, latest: Option<&str>, active: &[(&str, &str)]) -> Svc {
        Svc {
            key: format!("env1/{name}"),
            env_id: "env1".into(),
            service_id: format!("id-{name}"),
            name: name.into(),
            place: "campaign-hub / production".into(),
            image,
            cron: false,
            latest: latest.map(str::to_string),
            active: active
                .iter()
                .map(|(a, b)| (a.to_string(), b.to_string()))
                .collect(),
            health_url: None,
        }
    }
    fn up(name: &str, image: bool) -> Svc {
        svc(name, image, Some("SUCCESS"), &[("dep-1", "SUCCESS")])
    }
    fn down(name: &str, image: bool) -> Svc {
        svc(name, image, None, &[])
    }
    fn run(
        now: i64,
        svcs: &[Svc],
        health: &[(&str, bool)],
        billing: Option<Billing>,
        st: State,
    ) -> (State, Vec<Action>) {
        let h: BTreeMap<String, bool> = health
            .iter()
            .map(|(k, v)| (format!("env1/{k}"), *v))
            .collect();
        let view = View {
            services: svcs.to_vec(),
            ..View::default()
        };
        decide(
            &Inputs {
                now,
                view: &view,
                health: &h,
                billing,
            },
            &Limits::default(),
            st,
        )
    }
    fn names(a: &[Action]) -> Vec<String> {
        a.iter()
            .map(|a| match a {
                Action::Revive { name, restore, .. } => format!(
                    "revive:{name}:{}",
                    if *restore { "restore" } else { "fresh" }
                ),
                Action::Restart { name, .. } => format!("restart:{name}"),
            })
            .collect()
    }

    // Review fix (1): an unreadable spending cap fails closed.
    #[test]
    fn unknown_billing_with_a_down_service_restarts_nothing_and_alerts_once() {
        let s = [down("Postgres", true)];
        let mut st = State::default();
        for i in 0..(BILLING_UNKNOWN_ALERT as i64 + 3) {
            let (n, a) = run(T0 + 60 * i, &s, &[], None, st);
            assert!(a.is_empty(), "unreadable cap must fail closed, got {a:?}");
            st = n;
        }
        assert!(
            st.tries.is_empty(),
            "no tries spent while the cap is unknown"
        );
        assert_eq!(st.outbox.len(), 1, "alerted once per streak");
        assert!(st.outbox[0]
            .text
            .contains("will not say whether the workspace is over"));
        // The cap becomes readable and is fine: it acts.
        let (_, a) = run(T0 + 600, &s, &[], OK, st);
        assert_eq!(names(&a), ["revive:Postgres:restore"]);
    }

    #[test]
    fn unknown_billing_with_everything_up_is_quiet() {
        let (st, a) = run(T0, &[up("Postgres", true)], &[], None, State::default());
        assert!(a.is_empty());
        assert_eq!(st, State::default());
    }

    // Review fix (2): an empty or partial view never counts as "everything is fine".
    #[test]
    fn seeing_no_services_never_closes_an_incident_and_alerts() {
        let (st, _) = run(T0, &[down("Postgres", true)], &[], OK, State::default());
        assert!(st.incident.is_some());
        let mut st = st;
        for i in 1..=(BLIND_ALERT as i64 + 2) {
            let (n, a) = run(T0 + 60 * i, &[], &[], OK, st);
            assert!(a.is_empty());
            assert!(
                n.incident.is_some(),
                "an empty view is not 'everything is fine'"
            );
            st = n;
        }
        assert!(!st.outbox.iter().any(|m| m.kind == MsgKind::Close));
        let blind: Vec<_> = st
            .outbox
            .iter()
            .filter(|m| m.text.contains("cannot see any services"))
            .collect();
        assert_eq!(blind.len(), 1, "alerted once per streak");
    }

    #[test]
    fn a_missing_or_cut_off_environment_blocks_closing_but_not_fixing() {
        let h = BTreeMap::new();
        let view = View {
            services: vec![down("Postgres", true)],
            missing: vec!["env-gone".into()],
            truncated: false,
        };
        let inp = |now, v| Inputs {
            now,
            view: v,
            health: &h,
            billing: OK,
        };
        let (st, a) = decide(&inp(T0, &view), &Limits::default(), State::default());
        assert_eq!(
            names(&a),
            ["revive:Postgres:restore"],
            "visible services still get fixed"
        );
        let up_view = View {
            services: vec![up("Postgres", true)],
            ..view.clone()
        };
        let (st, _) = decide(&inp(T0 + 60, &up_view), &Limits::default(), st);
        let (st, _) = decide(&inp(T0 + 120, &up_view), &Limits::default(), st);
        assert!(st.incident.is_some(), "a missing environment keeps it open");
        assert!(st.outbox.iter().any(|m| m.text.contains("env-gone")));
        let cut = View {
            services: vec![up("Postgres", true)],
            missing: vec![],
            truncated: true,
        };
        let (st, _) = decide(&inp(T0 + 180, &cut), &Limits::default(), st);
        assert!(st.incident.is_some(), "a cut-off list keeps it open");
        let full = View {
            services: vec![up("Postgres", true)],
            ..View::default()
        };
        let (st, _) = decide(&inp(T0 + 240, &full), &Limits::default(), st);
        assert!(st.incident.is_none(), "a full, healthy view closes it");
    }

    // Review fix (4): repeated Railway read failures page a person.
    #[test]
    fn repeated_read_failures_alert_once_then_clear() {
        let mut st = State::default();
        for i in 0..(READ_FAILS_ALERT as i64 + 3) {
            st = record_read_failure(st, T0 + 60 * i, "HTTP 401: Not Authorized");
        }
        assert_eq!(st.outbox.len(), 1, "alerted once per streak");
        assert!(st.outbox[0].text.contains("cannot read Railway"));
        assert!(st.outbox[0].text.contains("HTTP 401"));
        let (st, _) = run(T0 + 900, &[up("Postgres", true)], &[], None, st);
        assert_eq!(st.read_fails, 0);
        assert!(st.incident.is_none());
        assert_eq!(st.outbox.last().unwrap().kind, MsgKind::Close);
    }

    // Review fix (3): two overlapping runs. The lease admits one; the decision is saved
    // before acting, so the next run sees the try and does not repeat it.
    #[test]
    fn overlapping_runs_cannot_both_act() {
        let s = [down("Postgres", true)];
        // Durable Object storage, simulated: one lease slot and one saved state.
        let mut lease: Option<Lease> = None;
        let mut saved = State::default();

        // Run A and run B start at the same moment.
        let a = lease_take(lease.as_ref(), "A", T0, LEASE_TTL_S).expect("A gets the lease");
        lease = Some(a);
        assert!(
            lease_take(lease.as_ref(), "B", T0, LEASE_TTL_S).is_none(),
            "B is refused while A holds it"
        );

        // A decides, saves BEFORE acting, then acts.
        let (st_a, acts_a) = run(T0, &s, &[], OK, saved.clone());
        assert!(lease_held(lease.as_ref(), "A", T0 + 5));
        saved = st_a;
        assert_eq!(names(&acts_a), ["revive:Postgres:restore"]);

        // A crashes without releasing. B retries before the lease runs out: still refused.
        assert!(lease_take(lease.as_ref(), "B", T0 + 60, LEASE_TTL_S).is_none());
        // After it runs out, B takes over, loads the saved state, and does not repeat A.
        let b = lease_take(lease.as_ref(), "B", T0 + LEASE_TTL_S, LEASE_TTL_S).unwrap();
        lease = Some(b);
        let (_, acts_b) = run(T0 + LEASE_TTL_S, &s, &[], OK, saved.clone());
        assert!(
            acts_b.is_empty(),
            "inside the cooldown: no second restart, got {acts_b:?}"
        );
        // A, waking up late, no longer holds the lease, so it may not act or save.
        assert!(!lease_held(lease.as_ref(), "A", T0 + LEASE_TTL_S + 1));
    }

    #[test]
    fn all_running_is_quiet_and_writes_nothing() {
        let (st, a) = run(
            T0,
            &[up("Postgres", true), up("app", false)],
            &[("app", true)],
            OK,
            State::default(),
        );
        assert!(a.is_empty());
        assert_eq!(st, State::default());
    }

    #[test]
    fn phases() {
        assert_eq!(phase(&up("x", false)), Phase::Up);
        assert_eq!(phase(&down("x", false)), Phase::Down);
        // A newer deploy failed but the older one still serves: up, leave it alone.
        assert_eq!(
            phase(&svc("x", false, Some("FAILED"), &[("d", "SUCCESS")])),
            Phase::Up
        );
        // A newer deploy failed and nothing serves: down.
        assert_eq!(phase(&svc("x", false, Some("FAILED"), &[])), Phase::Down);
        assert_eq!(
            phase(&svc("x", false, Some("CRASHED"), &[("d", "CRASHED")])),
            Phase::Down
        );
        assert_eq!(
            phase(&svc("x", false, Some("BUILDING"), &[("d", "BUILDING")])),
            Phase::Starting
        );
        assert_eq!(
            phase(&svc("x", false, Some("REMOVING"), &[])),
            Phase::Starting
        );
        let mut cron = svc("backup", false, Some("CRASHED"), &[]);
        cron.cron = true;
        assert_eq!(
            phase(&cron),
            Phase::Up,
            "a failed cron run is not a stopped service"
        );
        cron.latest = None;
        assert_eq!(phase(&cron), Phase::Down);
        cron.latest = Some("REMOVED".into());
        assert_eq!(phase(&cron), Phase::Down);
    }

    #[test]
    fn workspace_stop_brings_databases_back_first_then_code() {
        // This morning's outage: every deployment removed.
        let s0 = [
            down("Postgres", true),
            down("app", false),
            down("Backup CRON", false),
        ];
        let (st, a) = run(T0, &s0, &[], OK, State::default());
        assert_eq!(
            names(&a),
            ["revive:Postgres:restore"],
            "code waits for the database"
        );
        assert_eq!(st.outbox.len(), 1);
        assert_eq!(st.outbox[0].kind, MsgKind::Open);
        assert!(st.outbox[0]
            .text
            .contains("**Postgres** (campaign-hub / production) was not running"));

        // Next minute: database still starting -> nothing.
        let s1 = [
            svc("Postgres", true, Some("DEPLOYING"), &[("p", "DEPLOYING")]),
            down("app", false),
            down("Backup CRON", false),
        ];
        let (st, a) = run(T0 + 60, &s1, &[], OK, st);
        assert!(a.is_empty());

        // Database up -> both code services come back in one tick, one comment.
        let s2 = [
            up("Postgres", true),
            down("app", false),
            down("Backup CRON", false),
        ];
        let (st, a) = run(T0 + 120, &s2, &[], OK, st);
        assert_eq!(
            names(&a),
            ["revive:app:restore", "revive:Backup CRON:restore"]
        );
        assert_eq!(st.outbox.len(), 2);
        assert_eq!(st.outbox[1].kind, MsgKind::Comment);

        // All up -> incident closes with the duration.
        let s3 = [
            up("Postgres", true),
            up("app", false),
            up("Backup CRON", false),
        ];
        let (st, a) = run(T0 + 300, &s3, &[], OK, st);
        assert!(a.is_empty());
        assert!(st.incident.is_none());
        let last = st.outbox.last().unwrap();
        assert_eq!(last.kind, MsgKind::Close);
        assert!(last.text.contains("about 5 minutes"), "{}", last.text);
    }

    #[test]
    fn retries_are_spaced_then_fresh_build_then_pages_a_person() {
        let lim = Limits::default();
        let s = [down("app", false)];
        let (st, a) = run(T0, &s, &[], OK, State::default());
        assert_eq!(names(&a), ["revive:app:restore"]);
        // Inside the cooldown: nothing.
        let (st, a) = run(T0 + lim.cooldown_s - 1, &s, &[], OK, st);
        assert!(a.is_empty());
        // Second try is a fresh build of the latest code.
        let (st, a) = run(T0 + lim.cooldown_s, &s, &[], OK, st);
        assert_eq!(names(&a), ["revive:app:fresh"]);
        let (st, a) = run(T0 + 2 * lim.cooldown_s, &s, &[], OK, st);
        assert_eq!(names(&a), ["revive:app:fresh"]);
        // Out of tries: no action, one page.
        let (st, a) = run(T0 + 3 * lim.cooldown_s, &s, &[], OK, st);
        assert!(a.is_empty());
        assert!(st
            .outbox
            .last()
            .unwrap()
            .text
            .contains("A person needs to look"));
        let n = st.outbox.len();
        let (st, a) = run(T0 + 4 * lim.cooldown_s, &s, &[], OK, st);
        assert!(a.is_empty());
        assert_eq!(st.outbox.len(), n, "paged once, not every minute");
        // The window rolls: as the oldest try ages out, one more try is allowed.
        let (st, a) = run(T0 + lim.window_s, &s, &[], OK, st);
        assert_eq!(names(&a), ["revive:app:fresh"]);
        // Once every try has aged out, it starts over with a restore.
        let (_, a) = run(T0 + 2 * lim.cooldown_s + 2 * lim.window_s, &s, &[], OK, st);
        assert_eq!(names(&a), ["revive:app:restore"]);
    }

    #[test]
    fn spending_cap_means_no_restarts_and_one_page_with_numbers() {
        let b = Billing {
            over_limit: true,
            usage: Some(100.42),
            hard_limit: Some(100.0),
        };
        let s = [down("Postgres", true), down("app", false)];
        let (st, a) = run(T0, &s, &[], Some(b), State::default());
        assert!(a.is_empty());
        assert_eq!(st.outbox.len(), 1);
        assert!(
            st.outbox[0]
                .text
                .contains("used $100.42 of a $100.00 hard limit"),
            "{}",
            st.outbox[0].text
        );
        assert!(st.tries.is_empty(), "no tries spent while capped");
        let (st, a) = run(T0 + 60, &s, &[], Some(b), st);
        assert!(a.is_empty());
        assert_eq!(st.outbox.len(), 1, "cap is paged once");
        // Cap raised: it brings things back without waiting.
        let ok = Billing {
            over_limit: false,
            ..b
        };
        let (_, a) = run(T0 + 120, &s, &[], Some(ok), st);
        assert_eq!(names(&a), ["revive:Postgres:restore"]);
    }

    #[test]
    fn failing_health_check_restarts_after_a_streak() {
        let s = [up("Postgres", true), up("app", false)];
        let mut st = State::default();
        for i in 0..(DEFAULT_HEALTH_FAILS as i64 - 1) {
            let (n, a) = run(T0 + 60 * i, &s, &[("app", false)], OK, st);
            assert!(a.is_empty(), "no restart on a short blip");
            st = n;
        }
        assert!(st.outbox.is_empty(), "a short blip pages nobody");
        let (st, a) = run(T0 + 600, &s, &[("app", false)], OK, st);
        assert_eq!(names(&a), ["restart:app"]);
        assert!(st.outbox[0]
            .text
            .contains("health check failed 3 times in a row"));
        // Recovers: incident closes.
        let (st, _) = run(T0 + 660, &s, &[("app", true)], OK, st);
        assert!(st.incident.is_none());
        assert_eq!(st.outbox.last().unwrap().kind, MsgKind::Close);
    }

    #[test]
    fn a_stop_after_a_health_restart_still_restores_first() {
        let lim = Limits::default();
        let mut st = State::default();
        let s = [up("app", false)];
        for i in 0..DEFAULT_HEALTH_FAILS as i64 {
            st = run(T0 + 60 * i, &s, &[("app", false)], OK, st).0;
        }
        assert_eq!(
            st.tries.get("env1/app").map(Vec::len),
            Some(1),
            "the restart counted as a try"
        );
        let (_, a) = run(
            T0 + lim.cooldown_s + 200,
            &[down("app", false)],
            &[],
            OK,
            st,
        );
        assert_eq!(names(&a), ["revive:app:restore"]);
    }

    #[test]
    fn a_blip_that_recovers_resets_the_streak() {
        let s = [up("app", false)];
        let (st, _) = run(T0, &s, &[("app", false)], OK, State::default());
        let (st, _) = run(T0 + 60, &s, &[("app", false)], OK, st);
        let (st, _) = run(T0 + 120, &s, &[("app", true)], OK, st);
        assert_eq!(st, State::default());
    }

    #[test]
    fn a_broken_database_given_up_on_does_not_block_code_services_forever() {
        let lim = Limits::default();
        let s = [down("Postgres", true), down("app", false)];
        let mut st = State::default();
        let mut t = T0;
        for _ in 0..lim.max_tries {
            let (n, a) = run(t, &s, &[], OK, st);
            assert_eq!(a.len(), 1);
            st = n;
            t += lim.cooldown_s;
        }
        let (st, a) = run(t, &s, &[], OK, st);
        assert!(a.is_empty(), "this tick records the give-up");
        let (_, a) = run(t + 60, &s, &[], OK, st);
        assert_eq!(names(&a), ["revive:app:restore"]);
    }

    #[test]
    fn hourly_safety_limit_caps_total_actions() {
        let lim = Limits {
            max_actions_per_hour: 2,
            ..Limits::default()
        };
        let s = View {
            services: vec![down("a", true), down("b", true), down("c", true)],
            ..View::default()
        };
        let h = BTreeMap::new();
        let (st, a) = decide(
            &Inputs {
                now: T0,
                view: &s,
                health: &h,
                billing: OK,
            },
            &lim,
            State::default(),
        );
        assert_eq!(a.len(), 2);
        assert!(st
            .outbox
            .iter()
            .any(|m| m.text.contains("safety limit of 2 restarts")));
        let n = st.outbox.len();
        let (st, a) = decide(
            &Inputs {
                now: T0 + 60,
                view: &s,
                health: &h,
                billing: OK,
            },
            &lim,
            st,
        );
        assert!(a.is_empty());
        assert_eq!(st.outbox.len(), n, "the limit is paged once");
    }

    #[test]
    fn one_run_never_does_more_than_ten_actions() {
        let many: Vec<Svc> = (0..15).map(|i| down(&format!("db{i}"), true)).collect();
        let (st, a) = run(T0, &many, &[], OK, State::default());
        assert_eq!(a.len(), MAX_ACTIONS_PER_TICK);
        let (_, a) = run(T0 + 60, &many, &[], OK, st);
        assert_eq!(a.len(), 5, "the rest go a minute later");
    }

    #[test]
    fn outbox_is_bounded() {
        let mut st = State::default();
        for i in 0..(MAX_OUTBOX + 5) {
            st.push(MsgKind::Comment, String::new(), format!("m{i}"));
        }
        assert_eq!(st.outbox.len(), MAX_OUTBOX);
        assert_eq!(st.outbox[0].text, "m5");
    }

    #[test]
    fn collect_reads_railway_and_keeps_watch_order() {
        let data = json!({"projects": {"edges": [
            {"node": {"name": "content-lab", "environments": {"edges": [
                {"node": {"id": "e2", "name": "production", "serviceInstances": {"edges": [
                    {"node": {"serviceId": "s3", "serviceName": "lab", "cronSchedule": null, "source": {"image": null},
                              "latestDeployment": {"status": "SUCCESS"}, "activeDeployments": [{"id": "d3", "status": "SUCCESS"}]}}
                ]}}}
            ]}}},
            {"node": {"name": "campaign-hub", "environments": {"edges": [
                {"node": {"id": "e1", "name": "production", "serviceInstances": {"edges": [
                    {"node": {"serviceId": "s1", "serviceName": "Postgres", "cronSchedule": null,
                              "source": {"image": "ghcr.io/railwayapp-templates/postgres-ssl:17"},
                              "latestDeployment": null, "activeDeployments": []}},
                    {"node": {"serviceId": "s2", "serviceName": "Backup CRON", "cronSchedule": "0 0 * * *", "source": {"image": null},
                              "latestDeployment": {"status": "SUCCESS"}, "activeDeployments": []}},
                    {"node": {"serviceId": "s9", "serviceName": "scratch", "cronSchedule": null, "source": {"image": null},
                              "latestDeployment": null, "activeDeployments": []}}
                ]}}},
                {"node": {"id": "e9", "name": "testing", "serviceInstances": {"edges": []}}}
            ]}}}
        ]}});
        let watch = parse_watch(
            r#"[{"env":"e1","health":{"Postgres":"https://x/health"},"skip":["scratch"]},{"env":"e2"},{"env":"e404"}]"#,
        )
        .unwrap();
        let view = collect(&[data], &watch);
        let (svcs, missing) = (&view.services, &view.missing);
        assert!(!view.truncated);
        let got: Vec<(&str, bool, bool, Phase)> = svcs
            .iter()
            .map(|s| (s.name.as_str(), s.image, s.cron, phase(s)))
            .collect();
        assert_eq!(
            got,
            [
                ("Postgres", true, false, Phase::Down),
                ("Backup CRON", false, true, Phase::Up),
                ("lab", false, false, Phase::Up)
            ]
        );
        assert_eq!(svcs[0].key, "e1/s1");
        assert_eq!(svcs[0].place, "campaign-hub / production");
        assert_eq!(svcs[0].health_url.as_deref(), Some("https://x/health"));
        assert_eq!(missing, &["e404"]);
    }

    #[test]
    fn last_ran_skips_failed_builds() {
        let l = |v: &[(&str, &str)]| {
            last_ran(
                &v.iter()
                    .map(|(a, b)| (a.to_string(), b.to_string()))
                    .collect::<Vec<_>>(),
            )
        };
        // Campaign Hub this morning: three deploys failed because the database was gone.
        assert_eq!(
            l(&[
                ("f3", "FAILED"),
                ("f2", "FAILED"),
                ("f1", "FAILED"),
                ("ok", "REMOVED")
            ])
            .as_deref(),
            Some("ok")
        );
        assert_eq!(l(&[("f", "FAILED")]), None);
        assert_eq!(l(&[]), None);
    }

    #[test]
    fn config_parsing() {
        assert!(parse_watch("[]").is_err());
        assert!(parse_watch("nope").is_err());
        assert!(parse_watch(r#"[{"env":"not an id!"}]"#).is_err());
        assert!(parse_watch(r#"[{"env":"abc-123","health":{"x":"ftp://y"}}]"#).is_err());
        assert!(parse_watch(r#"[{"env":"abc-123"}]"#).is_ok());
        let l = parse_limits(|k| match k {
            "COOLDOWN_S" => Some("5".into()),
            "MAX_TRIES" => Some("junk".into()),
            "HEALTH_FAILS" => Some(" 4 ".into()),
            _ => None,
        });
        assert_eq!(l.cooldown_s, 60, "clamped up to the minimum");
        assert_eq!(l.max_tries, DEFAULT_MAX_TRIES);
        assert_eq!(l.health_fails, 4);
    }

    #[test]
    fn billing_parse() {
        let b = parse_billing(&json!({"workspace": {"customer": {"currentUsage": 12.5,
            "usageLimit": {"softLimit": 100, "hardLimit": 100, "isOverLimit": true}}}}))
        .unwrap();
        assert_eq!(
            b,
            Billing {
                over_limit: true,
                usage: Some(12.5),
                hard_limit: Some(100.0)
            }
        );
        let none = parse_billing(
            &json!({"workspace": {"customer": {"currentUsage": 0, "usageLimit": null}}}),
        )
        .unwrap();
        assert!(!none.over_limit, "no limit set is a definite 'not capped'");
        assert!(parse_billing(&json!({})).is_none());
        // Anything half-answered is unknown, never "not capped".
        assert!(parse_billing(&json!({"workspace": {"customer": null}})).is_none());
        assert!(parse_billing(&json!({"workspace": {"customer": {"currentUsage": 1}}})).is_none());
        assert!(parse_billing(
            &json!({"workspace": {"customer": {"usageLimit": {"hardLimit": 100}}}})
        )
        .is_none());
        assert!(parse_billing(
            &json!({"workspace": {"customer": {"usageLimit": {"isOverLimit": "yes"}}}})
        )
        .is_none());
    }

    #[test]
    fn pagination_and_cut_off_lists() {
        let page = |name: &str, more: bool, env_more: bool| {
            json!({"projects": {
                "pageInfo": {"hasNextPage": more, "endCursor": format!("after-{name}")},
                "edges": [{"node": {"name": name, "environments": {
                    "pageInfo": {"hasNextPage": env_more},
                    "edges": [{"node": {"id": format!("e-{name}"), "name": "production",
                        "serviceInstances": {"pageInfo": {"hasNextPage": false}, "edges": []}}}]}}}]}})
        };
        assert_eq!(
            next_cursor(&page("a", true, false)).as_deref(),
            Some("after-a")
        );
        assert_eq!(next_cursor(&page("b", false, false)), None);
        let watch = parse_watch(r#"[{"env":"e-a"},{"env":"e-b"}]"#).unwrap();
        let v = collect(&[page("a", true, false), page("b", false, false)], &watch);
        assert!(v.missing.is_empty(), "environments on page 2 are found");
        assert!(!v.truncated);
        let v = collect(&[page("a", false, true)], &watch);
        assert!(
            v.truncated,
            "a nested list with more pages is reported as cut off"
        );
    }

    #[test]
    fn issue_key_and_time() {
        assert!(body_has_key(&issue_body("hello")));
        assert!(!body_has_key("key: RAILWAY-WATCHDOG-OTHER"));
        assert_eq!(fmt_et(1_791_287_027), "Tue Oct 6, 7:43 AM EDT");
        assert_eq!(fmt_et(1_796_000_000), "Sun Nov 29, 7:53 PM EST");
    }
}

/// Dry run against a real Railway answer, read-only. Save the Worker's `projects` query result
/// to a file, then: SNAPSHOT=/path/to.json WATCH="$(...)" cargo test dry_run -- --ignored --nocapture
#[cfg(test)]
mod dry_run {
    use super::*;

    #[test]
    #[ignore]
    fn dry_run() {
        let snap: Value = serde_json::from_str(
            &std::fs::read_to_string(std::env::var("SNAPSHOT").unwrap()).unwrap(),
        )
        .unwrap();
        let data = snap.get("data").unwrap_or(&snap);
        let watch = parse_watch(&std::env::var("WATCH").unwrap()).unwrap();
        let view = collect(std::slice::from_ref(data), &watch);
        for s in &view.services {
            println!(
                "{:?}\t{}\t{}{}",
                phase(s),
                s.place,
                s.name,
                if s.image { " (database)" } else { "" }
            );
        }
        println!(
            "missing environments: {:?}, cut off: {}",
            view.missing, view.truncated
        );
        let h = BTreeMap::new();
        // Assume "not capped" so the dry run shows what it would restart.
        let ok = Some(Billing {
            over_limit: false,
            usage: None,
            hard_limit: None,
        });
        let (_, actions) = decide(
            &Inputs {
                now: 0,
                view: &view,
                health: &h,
                billing: ok,
            },
            &Limits::default(),
            State::default(),
        );
        println!("would do: {actions:?}");
    }
}
