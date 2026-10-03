use crate::{
    build_report, detect_yt_dlp, normalize_account, normalize_sound_id, parse_local_datetime,
    scrape_accounts, write_outputs, RunConfig, ScrapeReport,
};
use anyhow::{anyhow, bail, Context, Result};
use chrono::{Duration, Local};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::env;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration as StdDuration;
use tiny_http::{Header, Method, Request, Response, Server, StatusCode};
use wait_timeout::ChildExt;

#[derive(Debug, Clone)]
pub(crate) struct GuiOptions {
    pub(crate) host: String,
    pub(crate) port: u16,
}

#[derive(Clone)]
struct GuiState {
    runs: Arc<Mutex<BTreeMap<String, RunRecord>>>,
    chat_history: Arc<Mutex<Vec<Value>>>,
    base_url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RunRequest {
    #[serde(default)]
    accounts_text: String,
    #[serde(default)]
    sound_ids_text: String,
    #[serde(default)]
    start: String,
    #[serde(default)]
    end: String,
    #[serde(default)]
    hours: Option<i64>,
    #[serde(default)]
    limit: Option<usize>,
    #[serde(default)]
    workers: Option<usize>,
    #[serde(default)]
    timeout_seconds: Option<u64>,
    #[serde(default)]
    output_dir: String,
}

#[derive(Debug, Clone, Serialize)]
struct RunRecord {
    id: String,
    created_at: String,
    status: String,
    progress: String,
    output_dir: String,
    accounts_total: usize,
    accounts_completed: usize,
    videos_kept: usize,
    unique_songs: usize,
    request: RunRequest,
    logs: Vec<String>,
    report: Option<ScrapeReport>,
    error: String,
}

#[derive(Debug)]
struct PreparedRun {
    request: RunRequest,
    accounts: Vec<String>,
    config: RunConfig,
    workers: usize,
    output_dir: PathBuf,
}

#[derive(Debug, Deserialize)]
struct ChatRequest {
    message: String,
    #[serde(default)]
    context: Option<Value>,
}

#[derive(Debug, Serialize)]
struct ChatResponse {
    reply: String,
    run_id: Option<String>,
    request: Option<RunRequest>,
    tool_call: Option<Value>,
}

#[derive(Debug, Deserialize)]
struct ToolCallRequest {
    name: String,
    #[serde(default)]
    arguments: Value,
}

#[derive(Debug, Deserialize)]
struct McpRequest {
    #[serde(default)]
    jsonrpc: String,
    #[serde(default)]
    id: Value,
    method: String,
    #[serde(default)]
    params: Value,
}

pub(crate) fn serve(options: GuiOptions) -> Result<()> {
    let addr = format!("{}:{}", options.host, options.port);
    let server = Server::http(&addr).map_err(|e| anyhow!("failed to start GUI server: {e}"))?;
    let browser_host = if options.host == "0.0.0.0" {
        "127.0.0.1".to_string()
    } else {
        options.host.clone()
    };
    let state = GuiState {
        runs: Arc::new(Mutex::new(BTreeMap::new())),
        chat_history: Arc::new(Mutex::new(Vec::new())),
        base_url: format!("http://{}:{}", browser_host, options.port),
    };

    println!("Local scraper GUI: http://{addr}");
    println!("Tool endpoint:      http://{addr}/api/tools/call");
    println!("MCP-like endpoint:  http://{addr}/api/mcp");

    for request in server.incoming_requests() {
        let request_state = state.clone();
        std::thread::spawn(move || {
            if let Err(err) = handle_request(request, request_state) {
                eprintln!("GUI request failed: {err}");
            }
        });
    }

    Ok(())
}

fn handle_request(mut request: Request, state: GuiState) -> Result<()> {
    let method = request.method().clone();
    let url = request.url().to_string();
    let path_string = url
        .split('?')
        .next()
        .unwrap_or("/")
        .trim_end_matches('/')
        .to_string();
    let path = if path_string.is_empty() {
        "/"
    } else {
        path_string.as_str()
    };

    if method == Method::Options {
        return respond_empty(request, 204);
    }

    match (method, path) {
        (Method::Get, "/") => respond_html(request, INDEX_HTML),
        (Method::Get, p) if p.starts_with("/api/hub/") => proxy_hub(request, &url),
        (Method::Get, "/api/state") => {
            let runs = list_runs(&state);
            respond_json(request, 200, &json!({ "runs": runs }))
        }
        (Method::Post, "/api/runs") => {
            let body = read_body(&mut request)?;
            let run_request: RunRequest =
                serde_json::from_str(&body).context("invalid run request JSON")?;
            match start_run(state, run_request) {
                Ok(record) => respond_json(request, 201, &record),
                Err(err) => respond_json(request, 400, &json!({ "error": err.to_string() })),
            }
        }
        (Method::Post, "/api/chat") => {
            let body = read_body(&mut request)?;
            let chat: ChatRequest = serde_json::from_str(&body).context("invalid chat JSON")?;
            let response = handle_chat(state, chat);
            respond_json(request, 200, &response)
        }
        (Method::Get, "/api/tools") => respond_json(request, 200, &tool_list()),
        (Method::Post, "/api/tools/call") => {
            let body = read_body(&mut request)?;
            let call: ToolCallRequest =
                serde_json::from_str(&body).context("invalid tool call JSON")?;
            match call_tool(state, &call.name, call.arguments) {
                Ok(value) => respond_json(request, 200, &value),
                Err(err) => respond_json(request, 400, &json!({ "error": err.to_string() })),
            }
        }
        (Method::Post, "/api/mcp") => {
            let body = read_body(&mut request)?;
            let mcp: McpRequest = serde_json::from_str(&body).context("invalid MCP JSON")?;
            let response = handle_mcp(state, mcp);
            respond_json(request, 200, &response)
        }
        (Method::Get, p) if p.starts_with("/api/runs/") => {
            let id = p.trim_start_matches("/api/runs/");
            match get_run(&state, id) {
                Some(record) => respond_json(request, 200, &record),
                None => respond_json(request, 404, &json!({ "error": "run not found" })),
            }
        }
        _ => respond_json(request, 404, &json!({ "error": "not found" })),
    }
}

fn start_run(state: GuiState, request: RunRequest) -> Result<RunRecord> {
    let id = format!("{}", Local::now().timestamp_millis());
    let prepared = prepare_run(request, &id)?;

    let record = RunRecord {
        id: id.clone(),
        created_at: Local::now().format("%Y-%m-%dT%H:%M:%S%:z").to_string(),
        status: "queued".to_string(),
        progress: "Queued".to_string(),
        output_dir: prepared.output_dir.display().to_string(),
        accounts_total: prepared.accounts.len(),
        accounts_completed: 0,
        videos_kept: 0,
        unique_songs: 0,
        request: prepared.request.clone(),
        logs: Vec::new(),
        report: None,
        error: String::new(),
    };

    {
        let mut runs = state.runs.lock().expect("runs lock poisoned");
        runs.insert(id.clone(), record.clone());
    }

    let run_state = state.clone();
    std::thread::spawn(move || {
        update_run(&run_state, &id, |run| {
            run.status = "running".to_string();
            run.progress = "Starting yt-dlp workers".to_string();
        });

        let output_dir = prepared.output_dir.clone();
        let result = scrape_accounts(
            prepared.accounts,
            prepared.config.clone(),
            prepared.workers,
            |account_result| {
                update_run(&run_state, &id, |run| {
                    run.accounts_completed += 1;
                    run.videos_kept += account_result.kept;
                    run.progress = format!(
                        "{}/{} accounts complete",
                        run.accounts_completed, run.accounts_total
                    );
                    run.logs.push(format!(
                        "@{}: {} ({} kept / {} fetched){}",
                        account_result.account,
                        account_result.status,
                        account_result.kept,
                        account_result.fetched,
                        if account_result.error.is_empty() {
                            String::new()
                        } else {
                            format!(" - {}", account_result.error)
                        }
                    ));
                    if run.logs.len() > 80 {
                        run.logs.remove(0);
                    }
                });
            },
        )
        .and_then(|results| {
            let report = build_report(results, &prepared.config);
            write_outputs(&output_dir, &report)?;
            Ok(report)
        });

        match result {
            Ok(report) => update_run(&run_state, &id, |run| {
                run.status = "done".to_string();
                run.progress = "Done".to_string();
                run.videos_kept = report.total_videos;
                run.unique_songs = report.unique_songs;
                run.report = Some(report);
            }),
            Err(err) => update_run(&run_state, &id, |run| {
                run.status = "error".to_string();
                run.progress = "Failed".to_string();
                run.error = err.to_string();
                run.logs.push(format!("ERROR: {err}"));
            }),
        }
    });

    Ok(record)
}

fn prepare_run(mut request: RunRequest, run_id: &str) -> Result<PreparedRun> {
    let accounts = parse_accounts(&request.accounts_text);
    if accounts.is_empty() {
        bail!("Add at least one TikTok account handle or profile URL.");
    }

    let sound_ids = parse_sound_ids(&request.sound_ids_text);
    request.limit = Some(request.limit.unwrap_or(50).clamp(1, 500));
    request.workers = Some(request.workers.unwrap_or(2).clamp(1, 8));
    request.timeout_seconds = Some(request.timeout_seconds.unwrap_or(180).clamp(30, 1800));
    request.hours = Some(request.hours.unwrap_or(36).clamp(1, 24 * 90));
    let workers = request.workers.unwrap_or(2).clamp(1, 8);

    let end = if request.end.trim().is_empty() {
        Local::now()
    } else {
        parse_local_datetime(&request.end).context("invalid end time")?
    };
    let start = if request.start.trim().is_empty() {
        end - Duration::hours(request.hours.unwrap_or(36))
    } else {
        parse_local_datetime(&request.start).context("invalid start time")?
    };
    if start > end {
        bail!("Start time must be before end time.");
    }

    let base_output = if request.output_dir.trim().is_empty() {
        PathBuf::from("output/local-scraper")
    } else {
        PathBuf::from(request.output_dir.trim())
    };
    let output_dir = base_output.join(run_id);
    request.output_dir = base_output.display().to_string();

    let config = RunConfig {
        yt_dlp: detect_yt_dlp(),
        start,
        end,
        limit: request.limit.unwrap_or(50),
        timeout_seconds: request.timeout_seconds.unwrap_or(180),
        sound_ids,
    };

    Ok(PreparedRun {
        request,
        accounts,
        config,
        workers,
        output_dir,
    })
}

fn handle_chat(state: GuiState, chat: ChatRequest) -> ChatResponse {
    match run_pi_agent(state, chat) {
        Ok(response) => response,
        Err(err) => ChatResponse {
            reply: format!("Pi LLM error: {err}"),
            run_id: None,
            request: None,
            tool_call: None,
        },
    }
}

fn run_pi_agent(state: GuiState, chat: ChatRequest) -> Result<ChatResponse> {
    let backend = env::var("PI_AGENT_BACKEND").unwrap_or_else(|_| "pi".to_string());
    if backend != "openai" {
        return run_pi_cli_agent(&state, &chat);
    }
    run_openai_agent(state, chat)
}

fn run_pi_cli_agent(state: &GuiState, chat: &ChatRequest) -> Result<ChatResponse> {
    let pi_path = resolve_pi_command().ok_or_else(|| {
        anyhow!(
            "could not find Pi CLI. Set PI_AGENT_COMMAND or install /Users/risingtidesdev/bin/pi"
        )
    })?;
    let context = build_agent_context(state, chat.context.clone());
    let prompt = format!(
        "User message:\n{}\n\nLive GUI/context JSON:\n{}\n\nLocal HTTP tools Pi may call with bash/curl:\n- GET {}/api/state\n- GET {}/api/tools\n- POST {}/api/tools/call with JSON {{\"name\":\"scrape.list_runs\",\"arguments\":{{}}}}\n- POST {}/api/tools/call with scrape.start / scrape.get_run / scrape.copy_links\n- GET {}/api/hub/api/campaigns\n- GET {}/api/hub/api/internal/groups\n- GET {}/api/hub/api/scrape-tasks/queue?limit=20\n\nUse those endpoints when you need fresh data or when the user asks you to inspect failures, queues, campaigns, groups, links, or runs. Do not edit files. Do not pretend you checked a tool if you did not.",
        chat.message,
        serde_json::to_string(&context)?,
        state.base_url,
        state.base_url,
        state.base_url,
        state.base_url,
        state.base_url,
        state.base_url,
        state.base_url,
    );

    let mut command = Command::new(pi_path);
    command
        .current_dir(env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
        .arg("-p")
        .arg("--no-context-files")
        .arg("--no-extensions")
        .arg("--no-skills")
        .arg("--no-prompt-templates")
        .arg("--no-themes")
        .arg("--tools")
        .arg("bash,read,grep,find,ls")
        .arg("--system-prompt")
        .arg(pi_system_prompt());

    if let Ok(provider) = env::var("PI_AGENT_PROVIDER") {
        if !provider.trim().is_empty() {
            command.arg("--provider").arg(provider);
        }
    }
    if let Ok(model) = env::var("PI_AGENT_MODEL") {
        if !model.trim().is_empty() {
            command.arg("--model").arg(model);
        }
    }
    if let Ok(thinking) = env::var("PI_AGENT_THINKING") {
        if !thinking.trim().is_empty() {
            command.arg("--thinking").arg(thinking);
        }
    }

    command
        .arg(prompt)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = command.spawn().context("failed to launch Pi CLI")?;
    let timeout = env::var("PI_AGENT_TIMEOUT_SECONDS")
        .ok()
        .and_then(|raw| raw.parse::<u64>().ok())
        .unwrap_or(120)
        .clamp(15, 600);
    let status = match child
        .wait_timeout(StdDuration::from_secs(timeout))
        .context("failed waiting for Pi CLI")?
    {
        Some(status) => status,
        None => {
            let _ = child.kill();
            let _ = child.wait();
            bail!("Pi CLI timed out after {timeout}s");
        }
    };
    let output = child
        .wait_with_output()
        .context("failed collecting Pi CLI output")?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if !status.success() {
        bail!(
            "Pi CLI exited with {}. {}{}",
            status,
            stdout,
            if stderr.is_empty() {
                String::new()
            } else {
                format!("\n{stderr}")
            }
        );
    }

    let reply = if stdout.is_empty() { stderr } else { stdout };
    let reply = if reply.is_empty() {
        "Pi returned no text.".to_string()
    } else {
        reply
    };
    remember_chat(state, &chat.message, &reply);
    Ok(ChatResponse {
        reply,
        run_id: None,
        request: None,
        tool_call: None,
    })
}

fn resolve_pi_command() -> Option<String> {
    if let Ok(path) = env::var("PI_AGENT_COMMAND") {
        if !path.trim().is_empty() {
            return Some(path);
        }
    }
    let local = "/Users/risingtidesdev/bin/pi";
    if std::path::Path::new(local).exists() {
        return Some(local.to_string());
    }
    env::var("PATH").ok().and_then(|path| {
        path.split(':')
            .map(|dir| std::path::Path::new(dir).join("pi"))
            .find(|candidate| candidate.exists())
            .map(|candidate| candidate.display().to_string())
    })
}

fn run_openai_agent(state: GuiState, chat: ChatRequest) -> Result<ChatResponse> {
    let api_key = match env::var("OPENAI_API_KEY") {
        Ok(key) if !key.trim().is_empty() => key,
        _ => {
            return Ok(ChatResponse {
                reply: "Pi is not connected to an LLM in this process. Restart the GUI with OPENAI_API_KEY set, and optionally PI_AGENT_MODEL. I will not fake agent behavior with a keyword parser.".to_string(),
                run_id: None,
                request: None,
                tool_call: None,
            });
        }
    };

    let mut messages = vec![json!({
        "role": "system",
        "content": pi_system_prompt()
    })];

    let context = build_agent_context(&state, chat.context.clone());
    messages.push(json!({
        "role": "system",
        "content": format!("Live local tool context as JSON:\n{}", serde_json::to_string(&context)?)
    }));

    {
        let history = state
            .chat_history
            .lock()
            .expect("chat history lock poisoned");
        let keep_from = history.len().saturating_sub(16);
        messages.extend(history[keep_from..].iter().cloned());
    }

    messages.push(json!({
        "role": "user",
        "content": chat.message
    }));

    let mut run_id = None;
    let mut run_request = None;
    let mut last_tool_call = None;

    for _ in 0..3 {
        let completion = openai_chat_completion(&api_key, &messages, Some(agent_tools()))?;
        let message = completion
            .get("choices")
            .and_then(Value::as_array)
            .and_then(|choices| choices.first())
            .and_then(|choice| choice.get("message"))
            .cloned()
            .ok_or_else(|| anyhow!("OpenAI response did not contain a message"))?;

        let tool_calls = message
            .get("tool_calls")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();

        if tool_calls.is_empty() {
            let reply = message
                .get("content")
                .and_then(Value::as_str)
                .unwrap_or("")
                .trim()
                .to_string();
            let reply = if reply.is_empty() {
                "Pi did not return text.".to_string()
            } else {
                reply
            };
            remember_chat(&state, &chat.message, &reply);
            return Ok(ChatResponse {
                reply,
                run_id,
                request: run_request,
                tool_call: last_tool_call,
            });
        }

        messages.push(message);
        for call in tool_calls {
            let tool_id = call
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or("tool_call");
            let name = call
                .get("function")
                .and_then(|f| f.get("name"))
                .and_then(Value::as_str)
                .unwrap_or("");
            let args_raw = call
                .get("function")
                .and_then(|f| f.get("arguments"))
                .and_then(Value::as_str)
                .unwrap_or("{}");
            let args: Value = serde_json::from_str(args_raw).unwrap_or_else(|_| json!({}));
            last_tool_call = Some(json!({ "name": name, "arguments": args.clone() }));
            let result = call_agent_tool(&state, name, args);
            if let Some(id) = result
                .get("run")
                .and_then(|run| run.get("id"))
                .and_then(Value::as_str)
            {
                run_id = Some(id.to_string());
            }
            if let Some(request) = result
                .get("run")
                .and_then(|run| run.get("request"))
                .cloned()
                .and_then(|value| serde_json::from_value(value).ok())
            {
                run_request = Some(request);
            }
            messages.push(json!({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": serde_json::to_string(&result)?
            }));
        }
    }

    let reply = "Pi used tools but did not finish a final response. Ask again and I will continue from the current run/context.".to_string();
    remember_chat(&state, &chat.message, &reply);
    Ok(ChatResponse {
        reply,
        run_id,
        request: run_request,
        tool_call: last_tool_call,
    })
}

fn pi_system_prompt() -> &'static str {
    "You are Pi, a real LLM agent embedded in a local Rust yt-dlp scraper GUI for Rising Tides campaign operations. \
You are not a keyword parser. Talk like an operational teammate: concise, direct, and useful. \
You can inspect Campaign Hub data, internal groups, untracked post queues, local scrape runs, run logs, and failures using tools. \
You may start a scrape only when the user clearly asks to start/run/scrape and the required accounts are known. \
For questions like checking active campaigns, old campaigns, queue status, paid/internal post links, or failures, inspect data and answer; do not ask for TikTok handles unless the user is trying to start a scrape without a source. \
Define current active campaigns as active-status Campaign Hub rows where completion_status is not completed. \
When failures exist, call them out with likely causes and next action. \
If data is missing, say what is missing and which tool/source was checked."
}

fn remember_chat(state: &GuiState, user: &str, assistant: &str) {
    let mut history = state
        .chat_history
        .lock()
        .expect("chat history lock poisoned");
    history.push(json!({ "role": "user", "content": user }));
    history.push(json!({ "role": "assistant", "content": assistant }));
    if history.len() > 40 {
        let excess = history.len() - 40;
        history.drain(0..excess);
    }
}

fn openai_chat_completion(
    api_key: &str,
    messages: &[Value],
    tools: Option<Value>,
) -> Result<Value> {
    let model = env::var("PI_AGENT_MODEL").unwrap_or_else(|_| "gpt-4o-mini".to_string());
    let mut body = json!({
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "tool_choice": "auto",
    });
    if let Some(tools) = tools {
        body["tools"] = tools;
    }

    let response = ureq::post("https://api.openai.com/v1/chat/completions")
        .set("Authorization", &format!("Bearer {api_key}"))
        .set("Content-Type", "application/json")
        .timeout(StdDuration::from_secs(60))
        .send_json(body);

    match response {
        Ok(resp) => resp
            .into_json::<Value>()
            .context("failed to decode OpenAI response JSON"),
        Err(ureq::Error::Status(code, resp)) => {
            let body = resp.into_string().unwrap_or_default();
            bail!("OpenAI API returned {code}: {body}");
        }
        Err(err) => Err(anyhow!("OpenAI API request failed: {err}")),
    }
}

fn build_agent_context(state: &GuiState, ui_context: Option<Value>) -> Value {
    let campaigns =
        hub_get_json("/api/campaigns").unwrap_or_else(|err| json!({ "error": err.to_string() }));
    let groups = hub_get_json("/api/internal/groups")
        .unwrap_or_else(|err| json!({ "error": err.to_string() }));
    let creators = hub_get_json("/api/internal/creators")
        .unwrap_or_else(|err| json!({ "error": err.to_string() }));
    let queue = hub_get_json("/api/scrape-tasks/queue?limit=20")
        .unwrap_or_else(|err| json!({ "error": err.to_string() }));
    let runs = list_runs(state);

    json!({
        "hub": {
            "campaigns": compact_campaigns(&campaigns),
            "campaigns_returned": campaigns.as_array().map(|items| items.len()).unwrap_or(0),
            "current_active_campaigns": compact_current_campaigns(&campaigns),
            "groups": compact_groups(&groups),
            "internal_creator_count": creators.as_array().map(|items| items.len()).unwrap_or(0),
            "untracked_queue": compact_queue(&queue),
        },
        "local_scraper": {
            "runs": runs.into_iter().take(10).collect::<Vec<_>>(),
        },
        "ui": ui_context.unwrap_or(Value::Null),
    })
}

fn hub_get_json(path: &str) -> Result<Value> {
    let base =
        env::var("CAMPAIGN_HUB_API_URL").unwrap_or_else(|_| "http://localhost:5055".to_string());
    let target = format!("{}{}", base.trim_end_matches('/'), path);
    match ureq::get(&target)
        .set("Accept", "application/json")
        .timeout(StdDuration::from_secs(30))
        .call()
    {
        Ok(resp) => resp.into_json::<Value>().context("invalid Hub JSON"),
        Err(ureq::Error::Status(code, resp)) => {
            let body = resp.into_string().unwrap_or_default();
            bail!("Hub returned {code} for {target}: {body}");
        }
        Err(err) => Err(anyhow!("Hub request failed for {target}: {err}")),
    }
}

fn compact_campaigns(value: &Value) -> Value {
    let Some(items) = value.as_array() else {
        return value.clone();
    };
    Value::Array(
        items
            .iter()
            .take(60)
            .map(compact_campaign)
            .collect::<Vec<_>>(),
    )
}

fn compact_current_campaigns(value: &Value) -> Value {
    let Some(items) = value.as_array() else {
        return value.clone();
    };
    Value::Array(
        items
            .iter()
            .filter(|item| {
                item.get("status")
                    .and_then(Value::as_str)
                    .unwrap_or("active")
                    == "active"
                    && item
                        .get("completion_status")
                        .and_then(Value::as_str)
                        .unwrap_or("none")
                        != "completed"
            })
            .take(40)
            .map(compact_campaign)
            .collect::<Vec<_>>(),
    )
}

fn compact_campaign(item: &Value) -> Value {
    json!({
        "slug": item.get("slug"),
        "title": item.get("title"),
        "artist": item.get("artist"),
        "song": item.get("song"),
        "start_date": item.get("start_date"),
        "status": item.get("status"),
        "completion_status": item.get("completion_status"),
        "creator_count": item.get("creator_count"),
        "views": item.pointer("/stats/total_views"),
        "live_posts": item.pointer("/stats/live_posts"),
    })
}

fn compact_groups(value: &Value) -> Value {
    let Some(items) = value.as_array() else {
        return value.clone();
    };
    Value::Array(
        items
            .iter()
            .take(40)
            .map(|item| {
                json!({
                    "slug": item.get("slug"),
                    "title": item.get("title"),
                    "kind": item.get("kind"),
                    "member_count": item.get("member_count"),
                })
            })
            .collect::<Vec<_>>(),
    )
}

fn compact_queue(value: &Value) -> Value {
    let campaigns = value
        .get("campaigns")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .take(20)
                .map(|campaign| {
                    let videos = campaign
                        .get("videos")
                        .and_then(Value::as_array)
                        .map(|videos| {
                            videos
                                .iter()
                                .take(5)
                                .map(|video| {
                                    json!({
                                        "account": video.get("account"),
                                        "url": video.get("url"),
                                        "views": video.get("views"),
                                        "likes": video.get("likes"),
                                        "timestamp": video.get("timestamp"),
                                        "match_strategy": video.get("match_strategy"),
                                    })
                                })
                                .collect::<Vec<_>>()
                        })
                        .unwrap_or_default();
                    json!({
                        "slug": campaign.get("slug"),
                        "title": campaign.get("title"),
                        "artist": campaign.get("artist"),
                        "song": campaign.get("song"),
                        "untracked_count": campaign.get("untracked_count"),
                        "sample_videos": videos,
                    })
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();

    json!({
        "total_untracked": value.get("total_untracked"),
        "campaigns": campaigns,
    })
}

fn agent_tools() -> Value {
    json!([
        {
            "type": "function",
            "function": {
                "name": "hub_list_current_campaigns",
                "description": "List current active campaigns, excluding completed Campaign Hub rows.",
                "parameters": {
                    "type": "object",
                    "properties": { "limit": { "type": "integer", "minimum": 1, "maximum": 100 } }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "hub_get_campaign",
                "description": "Get full Campaign Hub detail for one campaign slug.",
                "parameters": {
                    "type": "object",
                    "properties": { "slug": { "type": "string" } },
                    "required": ["slug"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "hub_list_internal_groups",
                "description": "List internal creator groups and member counts.",
                "parameters": { "type": "object", "properties": {} }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "hub_get_internal_group",
                "description": "Get members for an internal group by slug.",
                "parameters": {
                    "type": "object",
                    "properties": { "slug": { "type": "string" } },
                    "required": ["slug"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "hub_get_untracked_queue",
                "description": "Inspect untracked paid/internal post links from Campaign Hub's scrape-task queue.",
                "parameters": {
                    "type": "object",
                    "properties": { "limit": { "type": "integer", "minimum": 1, "maximum": 100 } }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "scrape_list_runs",
                "description": "List local scraper GUI runs with status, counts, logs, and errors.",
                "parameters": { "type": "object", "properties": {} }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "scrape_get_run",
                "description": "Get one local scraper run by id, including logs and report if available.",
                "parameters": {
                    "type": "object",
                    "properties": { "id": { "type": "string" } },
                    "required": ["id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "scrape_start",
                "description": "Start a local yt-dlp scrape. Use only when the user clearly asks to start/run/scrape.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "accounts_text": { "type": "string" },
                        "sound_ids_text": { "type": "string" },
                        "hours": { "type": "integer" },
                        "start": { "type": "string" },
                        "end": { "type": "string" },
                        "limit": { "type": "integer" },
                        "workers": { "type": "integer" },
                        "timeout_seconds": { "type": "integer" },
                        "output_dir": { "type": "string" }
                    },
                    "required": ["accounts_text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "scrape_copy_links",
                "description": "Return copy/paste links for a completed local scrape run.",
                "parameters": {
                    "type": "object",
                    "properties": { "id": { "type": "string" } },
                    "required": ["id"]
                }
            }
        }
    ])
}

fn call_agent_tool(state: &GuiState, name: &str, arguments: Value) -> Value {
    match call_agent_tool_result(state, name, arguments) {
        Ok(value) => value,
        Err(err) => json!({ "error": err.to_string() }),
    }
}

fn call_agent_tool_result(state: &GuiState, name: &str, arguments: Value) -> Result<Value> {
    match name {
        "hub_list_current_campaigns" => {
            let limit = arguments
                .get("limit")
                .and_then(Value::as_u64)
                .unwrap_or(40)
                .clamp(1, 100) as usize;
            let campaigns = hub_get_json("/api/campaigns")?;
            let items = compact_current_campaigns(&campaigns);
            let items = items
                .as_array()
                .map(|items| Value::Array(items.iter().take(limit).cloned().collect()))
                .unwrap_or(items);
            Ok(json!({
                "returned_rows": campaigns.as_array().map(|items| items.len()).unwrap_or(0),
                "current_active": items,
            }))
        }
        "hub_get_campaign" => {
            let slug = required_string(&arguments, "slug")?;
            hub_get_json(&format!("/api/campaign/{slug}"))
        }
        "hub_list_internal_groups" => hub_get_json("/api/internal/groups"),
        "hub_get_internal_group" => {
            let slug = required_string(&arguments, "slug")?;
            hub_get_json(&format!("/api/internal/groups/{slug}"))
        }
        "hub_get_untracked_queue" => {
            let limit = arguments
                .get("limit")
                .and_then(Value::as_u64)
                .unwrap_or(20)
                .clamp(1, 100);
            hub_get_json(&format!("/api/scrape-tasks/queue?limit={limit}"))
        }
        "scrape_list_runs" => Ok(json!({ "runs": list_runs(state) })),
        "scrape_get_run" => {
            let id = required_string(&arguments, "id")?;
            let run = get_run(state, &id).ok_or_else(|| anyhow!("run not found"))?;
            Ok(json!({ "run": run }))
        }
        "scrape_start" => {
            let request: RunRequest =
                serde_json::from_value(arguments).context("invalid scrape_start arguments")?;
            let record = start_run(state.clone(), request)?;
            Ok(json!({ "run": record }))
        }
        "scrape_copy_links" => {
            let id = required_string(&arguments, "id")?;
            let run = get_run(state, &id).ok_or_else(|| anyhow!("run not found"))?;
            let Some(report) = run.report else {
                bail!("run has no report yet");
            };
            Ok(json!({ "text": render_links_only(&report) }))
        }
        _ => bail!("unknown agent tool: {name}"),
    }
}

fn required_string(arguments: &Value, key: &str) -> Result<String> {
    arguments
        .get(key)
        .and_then(Value::as_str)
        .map(str::to_string)
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| anyhow!("missing required string argument {key}"))
}

fn call_tool(state: GuiState, name: &str, arguments: Value) -> Result<Value> {
    match name {
        "scrape.start" => {
            let request: RunRequest =
                serde_json::from_value(arguments).context("invalid scrape.start arguments")?;
            let record = start_run(state, request)?;
            Ok(json!({ "run": record }))
        }
        "scrape.list_runs" => Ok(json!({ "runs": list_runs(&state) })),
        "scrape.get_run" => {
            let id = arguments
                .get("id")
                .and_then(Value::as_str)
                .ok_or_else(|| anyhow!("scrape.get_run requires string argument id"))?;
            let run = get_run(&state, id).ok_or_else(|| anyhow!("run not found"))?;
            Ok(json!({ "run": run }))
        }
        "scrape.copy_links" => {
            let id = arguments
                .get("id")
                .and_then(Value::as_str)
                .ok_or_else(|| anyhow!("scrape.copy_links requires string argument id"))?;
            let run = get_run(&state, id).ok_or_else(|| anyhow!("run not found"))?;
            let Some(report) = run.report else {
                bail!("run has no report yet");
            };
            Ok(json!({ "text": render_links_only(&report) }))
        }
        _ => bail!("unknown tool: {name}"),
    }
}

fn handle_mcp(state: GuiState, request: McpRequest) -> Value {
    let id = request.id.clone();
    let result = match request.method.as_str() {
        "initialize" => Ok(json!({
            "protocolVersion": "2024-11-05",
            "serverInfo": { "name": "rt-yt-scraper", "version": "0.1.0" },
            "capabilities": { "tools": {} }
        })),
        "tools/list" => Ok(tool_list()),
        "tools/call" => {
            let name = request
                .params
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("");
            let args = request
                .params
                .get("arguments")
                .cloned()
                .unwrap_or_else(|| json!({}));
            call_tool(state, name, args)
        }
        _ => Err(anyhow!("unsupported method {}", request.method)),
    };

    match result {
        Ok(value) => json!({
            "jsonrpc": if request.jsonrpc.is_empty() { "2.0" } else { &request.jsonrpc },
            "id": id,
            "result": value
        }),
        Err(err) => json!({
            "jsonrpc": if request.jsonrpc.is_empty() { "2.0" } else { &request.jsonrpc },
            "id": id,
            "error": { "code": -32602, "message": err.to_string() }
        }),
    }
}

fn tool_list() -> Value {
    json!({
        "tools": [
            {
                "name": "scrape.start",
                "description": "Start a local yt-dlp account scrape.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "accounts_text": { "type": "string" },
                        "sound_ids_text": { "type": "string" },
                        "hours": { "type": "integer" },
                        "start": { "type": "string" },
                        "end": { "type": "string" },
                        "limit": { "type": "integer" },
                        "workers": { "type": "integer" },
                        "timeout_seconds": { "type": "integer" },
                        "output_dir": { "type": "string" }
                    },
                    "required": ["accounts_text"]
                }
            },
            {
                "name": "scrape.list_runs",
                "description": "List GUI scrape runs.",
                "input_schema": { "type": "object", "properties": {} }
            },
            {
                "name": "scrape.get_run",
                "description": "Get one scrape run by ID.",
                "input_schema": {
                    "type": "object",
                    "properties": { "id": { "type": "string" } },
                    "required": ["id"]
                }
            },
            {
                "name": "scrape.copy_links",
                "description": "Return copy/paste links for a completed run.",
                "input_schema": {
                    "type": "object",
                    "properties": { "id": { "type": "string" } },
                    "required": ["id"]
                }
            }
        ]
    })
}

fn list_runs(state: &GuiState) -> Vec<RunRecord> {
    let runs = state.runs.lock().expect("runs lock poisoned");
    runs.values().rev().cloned().collect()
}

fn get_run(state: &GuiState, id: &str) -> Option<RunRecord> {
    let runs = state.runs.lock().expect("runs lock poisoned");
    runs.get(id).cloned()
}

fn update_run<F>(state: &GuiState, id: &str, update: F)
where
    F: FnOnce(&mut RunRecord),
{
    let mut runs = state.runs.lock().expect("runs lock poisoned");
    if let Some(run) = runs.get_mut(id) {
        update(run);
    }
}

fn parse_accounts(input: &str) -> Vec<String> {
    let mut out = Vec::new();
    for item in split_human_list(input) {
        if let Some(account) = normalize_account(&item) {
            if !out.contains(&account) {
                out.push(account);
            }
        }
    }
    out
}

fn parse_sound_ids(input: &str) -> std::collections::BTreeSet<String> {
    split_human_list(input)
        .into_iter()
        .filter_map(|item| normalize_sound_id(&item))
        .collect()
}

fn split_human_list(input: &str) -> Vec<String> {
    input
        .lines()
        .flat_map(|line| {
            line.split('#')
                .next()
                .unwrap_or("")
                .split(|c: char| c == ',' || c == ';' || c.is_whitespace())
        })
        .map(str::trim)
        .filter(|part| !part.is_empty())
        .map(str::to_string)
        .collect()
}

fn render_links_only(report: &ScrapeReport) -> String {
    let mut out = String::new();
    for song in &report.songs {
        out.push_str(&format!("{} - {}\n", song.song, song.artist));
        out.push_str(&"=".repeat(72));
        out.push('\n');
        for video in &song.videos {
            out.push_str(&video.url);
            out.push('\n');
        }
        out.push('\n');
    }
    out
}

fn proxy_hub(request: Request, url: &str) -> Result<()> {
    let base =
        env::var("CAMPAIGN_HUB_API_URL").unwrap_or_else(|_| "http://localhost:5055".to_string());
    let suffix = url.trim_start_matches("/api/hub");
    let target = format!("{}{}", base.trim_end_matches('/'), suffix);

    match ureq::get(&target).set("Accept", "application/json").call() {
        Ok(resp) => {
            let status = resp.status();
            let body = resp.into_string().unwrap_or_else(|_| "{}".to_string());
            let response = Response::from_string(body)
                .with_status_code(StatusCode(status))
                .with_header(header("Content-Type", "application/json"))
                .with_header(header("Access-Control-Allow-Origin", "*"));
            request
                .respond(response)
                .map_err(|e| anyhow!(e.to_string()))
        }
        Err(err) => respond_json(
            request,
            502,
            &json!({
                "error": "Campaign Hub API unavailable",
                "target": target,
                "detail": err.to_string()
            }),
        ),
    }
}

fn read_body(request: &mut Request) -> Result<String> {
    let mut body = String::new();
    request
        .as_reader()
        .read_to_string(&mut body)
        .context("failed reading request body")?;
    Ok(body)
}

fn respond_html(request: Request, body: &str) -> Result<()> {
    let response = Response::from_string(body)
        .with_status_code(StatusCode(200))
        .with_header(header("Content-Type", "text/html; charset=utf-8"))
        .with_header(header("Access-Control-Allow-Origin", "*"));
    request
        .respond(response)
        .map_err(|e| anyhow!(e.to_string()))
}

fn respond_json<T: Serialize>(request: Request, status: u16, value: &T) -> Result<()> {
    let body = serde_json::to_string(value)?;
    let response = Response::from_string(body)
        .with_status_code(StatusCode(status))
        .with_header(header("Content-Type", "application/json"))
        .with_header(header("Access-Control-Allow-Origin", "*"))
        .with_header(header("Access-Control-Allow-Headers", "Content-Type"))
        .with_header(header("Access-Control-Allow-Methods", "GET, POST, OPTIONS"));
    request
        .respond(response)
        .map_err(|e| anyhow!(e.to_string()))
}

fn respond_empty(request: Request, status: u16) -> Result<()> {
    let response = Response::empty(StatusCode(status))
        .with_header(header("Access-Control-Allow-Origin", "*"))
        .with_header(header("Access-Control-Allow-Headers", "Content-Type"))
        .with_header(header("Access-Control-Allow-Methods", "GET, POST, OPTIONS"));
    request
        .respond(response)
        .map_err(|e| anyhow!(e.to_string()))
}

fn header(name: &str, value: &str) -> Header {
    Header::from_bytes(name.as_bytes(), value.as_bytes()).expect("valid static header")
}

const INDEX_HTML: &str = r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Pi Scrape Workbench</title>
  <style>
    :root {
      --agent: #0c0f14;
      --agent-2: #151923;
      --field: #1b202b;
      --paper: #eef1f3;
      --surface: #fbfcfd;
      --surface-2: #f5f7f8;
      --line: #d8dee3;
      --line-strong: #b8c2ca;
      --text: #171b21;
      --muted: #66717d;
      --accent: #0e7a6f;
      --accent-soft: #d9f0ec;
      --blue: #2463a6;
      --amber: #9a6200;
      --bad: #b33a3a;
      --good: #207047;
      --shadow: 0 18px 42px rgba(16, 24, 32, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--paper);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    button, input, textarea { font: inherit; letter-spacing: 0; }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(390px, 40vw) minmax(0, 1fr);
    }
    .agent-pane {
      background: var(--agent);
      color: #f5f7f8;
      padding: 22px;
      display: flex;
      flex-direction: column;
      min-height: 100vh;
      border-right: 1px solid #06080b;
    }
    .ops-pane {
      min-width: 0;
      padding: 22px;
      overflow: auto;
    }
    .topline, .panel-head, .run-top, .brief-row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }
    h1, h2, h3 { margin: 0; letter-spacing: 0; }
    h1 { font-size: 22px; line-height: 1.12; }
    h2 { font-size: 14px; line-height: 1.2; }
    h3 { font-size: 13px; line-height: 1.2; }
    .muted { color: var(--muted); font-size: 12px; }
    .agent-pane .muted { color: #aab2bd; }
    .status {
      border: 1px solid rgba(255,255,255,.14);
      background: rgba(255,255,255,.06);
      color: #d7f4ee;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 760;
      padding: 5px 8px;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .agent-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 16px;
    }
    .agent-stat {
      border: 1px solid rgba(255,255,255,.1);
      background: rgba(255,255,255,.055);
      border-radius: 8px;
      padding: 10px;
      min-width: 0;
    }
    .agent-stat b {
      display: block;
      font-size: 15px;
      line-height: 1;
      color: #ffffff;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .agent-stat span {
      display: block;
      margin-top: 6px;
      color: #aab2bd;
      font-size: 10px;
      font-weight: 760;
      text-transform: uppercase;
    }
    .messages {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 10px;
      overflow: auto;
      padding: 18px 0;
      min-height: 280px;
    }
    .msg {
      border: 1px solid rgba(255,255,255,.1);
      background: rgba(255,255,255,.06);
      border-radius: 8px;
      padding: 11px 12px;
      font-size: 13px;
      line-height: 1.4;
      white-space: pre-wrap;
    }
    .msg.user {
      background: #e8fbf6;
      color: #0f2724;
      border-color: transparent;
      align-self: flex-end;
      max-width: 92%;
    }
    .quickbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }
    .chat-form {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      padding-top: 12px;
      border-top: 1px solid rgba(255,255,255,.1);
    }
    .chat-form input {
      height: 44px;
      border: 1px solid rgba(255,255,255,.13);
      border-radius: 8px;
      background: rgba(255,255,255,.08);
      color: #fff;
      padding: 0 12px;
      outline: none;
      min-width: 0;
    }
    .chat-form input:focus { border-color: #55c8bb; }
    .btn {
      border: 1px solid transparent;
      border-radius: 8px;
      background: var(--accent);
      color: white;
      font-size: 12px;
      font-weight: 760;
      padding: 9px 12px;
      cursor: pointer;
      white-space: nowrap;
    }
    .btn.secondary {
      color: var(--text);
      background: #fff;
      border-color: var(--line);
    }
    .btn.ghost {
      color: #e9f6f3;
      background: transparent;
      border-color: rgba(255,255,255,.16);
    }
    .btn:disabled { opacity: .55; cursor: not-allowed; }
    .ops-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 14px;
      margin-bottom: 14px;
    }
    .ops-grid {
      display: grid;
      grid-template-columns: minmax(340px, .9fr) minmax(460px, 1.1fr);
      gap: 14px;
      align-items: start;
      margin-top: 16px;
    }
    .surface {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 15px;
      min-width: 0;
    }
    .surface + .surface { margin-top: 14px; }
    .stack { display: flex; flex-direction: column; gap: 10px; }
    .tabs {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin: 12px 0;
    }
    .tab {
      border: 1px solid var(--line);
      background: #fff;
      color: #343942;
      border-radius: 999px;
      padding: 6px 9px;
      font-size: 12px;
      cursor: pointer;
    }
    .tab.active {
      background: var(--accent-2);
      border-color: #9cd5c8;
      color: #07554d;
      font-weight: 760;
    }
    .list {
      display: flex;
      flex-direction: column;
      gap: 7px;
      max-height: 430px;
      overflow: auto;
    }
    .item {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 10px;
      cursor: pointer;
    }
    .item:hover, .item.selected { border-color: #73bfb3; box-shadow: 0 0 0 3px rgba(14,122,111,.1); }
    .item-title {
      font-size: 13px;
      font-weight: 760;
      line-height: 1.25;
    }
    .item-meta {
      font-size: 12px;
      color: var(--muted);
      margin-top: 3px;
    }
    .grid-4 {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 9px;
    }
    .metric {
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 8px;
      padding: 10px;
      min-width: 0;
    }
    .metric-value {
      font-size: 20px;
      line-height: 1;
      font-weight: 780;
    }
    .metric-label {
      margin-top: 5px;
      font-size: 10px;
      font-weight: 760;
      color: #7b8089;
      text-transform: uppercase;
    }
    label {
      display: block;
      color: #434852;
      font-size: 11px;
      font-weight: 760;
      margin-bottom: 5px;
      text-transform: uppercase;
    }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--text);
      padding: 9px 10px;
      font-size: 13px;
      outline: none;
    }
    input:focus, textarea:focus {
      border-color: #72bdb2;
      box-shadow: 0 0 0 3px rgba(20, 124, 114, .12);
    }
    textarea {
      min-height: 92px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 12px;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 9px;
    }
    .field { margin-bottom: 10px; }
    .pill {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
      padding: 4px 8px;
      font-size: 11px;
      color: #444a52;
      gap: 5px;
    }
    .pill.good { border-color: #aedcc1; background: #eef8f1; color: var(--good); }
    .pill.bad { border-color: #efc6c6; background: #fff0f0; color: var(--bad); }
    .pill.warn { border-color: #ead19e; background: #fff7e8; color: var(--amber); }
    .empty {
      border: 1px dashed var(--line-strong);
      border-radius: 8px;
      background: rgba(255,255,255,.55);
      color: #747984;
      text-align: center;
      padding: 18px;
      font-size: 13px;
    }
    .run, .song {
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 8px;
      padding: 10px;
      cursor: pointer;
    }
    .run.selected { border-color: #72bdb2; box-shadow: 0 0 0 3px rgba(20,124,114,.11); }
    .run-id { font-size: 12px; font-weight: 780; }
    .run-status {
      font-size: 10px;
      font-weight: 780;
      text-transform: uppercase;
      border-radius: 999px;
      padding: 4px 7px;
      background: #edf5ff;
      color: #245f9e;
    }
    .run-status.done { background: #eef8f1; color: var(--good); }
    .run-status.error { background: #fff0f0; color: var(--bad); }
    .brief {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-2);
      padding: 12px;
    }
    .brief-row {
      border-bottom: 1px solid var(--line);
      padding: 8px 0;
      font-size: 12px;
    }
    .brief-row:first-child { padding-top: 0; }
    .brief-row:last-child { border-bottom: 0; padding-bottom: 0; }
    .brief-row span:first-child {
      color: var(--muted);
      font-weight: 760;
      text-transform: uppercase;
      font-size: 10px;
    }
    .brief-row span:last-child {
      color: var(--text);
      text-align: right;
      max-width: 68%;
      overflow-wrap: anywhere;
    }
    details {
      border-top: 1px solid var(--line);
      margin-top: 12px;
      padding-top: 12px;
    }
    summary {
      cursor: pointer;
      color: #34404b;
      font-size: 12px;
      font-weight: 760;
    }
    .log {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #111318;
      color: #d8dce4;
      padding: 10px;
      min-height: 86px;
      max-height: 170px;
      overflow: auto;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 11px;
      white-space: pre-wrap;
    }
    .links a {
      color: #116b62;
      font-size: 12px;
      word-break: break-all;
    }
    .links {
      list-style: none;
      margin: 8px 0 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 5px;
      max-height: 160px;
      overflow: auto;
    }
    @media (max-width: 1100px) {
      .app { grid-template-columns: 1fr; }
      .agent-pane { min-height: 46vh; }
      .ops-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 720px) {
      .ops-pane, .agent-pane { padding: 14px; }
      .grid-4, .form-grid { grid-template-columns: 1fr; }
      .topline, .panel-head, .run-top, .ops-header { display: block; }
      .agent-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app">
    <section class="agent-pane">
      <div class="topline">
        <div>
          <h1>Pi Scrape Agent</h1>
          <div class="muted">Command surface for Campaign Hub scrapes</div>
        </div>
        <span class="status" id="agentStatus">ready</span>
      </div>
      <div class="agent-grid" id="agentStats">
        <div class="agent-stat"><b>-</b><span>Hub</span></div>
        <div class="agent-stat"><b>0</b><span>Runs</span></div>
        <div class="agent-stat"><b>-</b><span>Brief</span></div>
      </div>
      <div class="messages" id="messages"></div>
      <div class="quickbar">
        <button class="btn ghost" type="button" data-prompt="show active campaigns">Active campaigns</button>
        <button class="btn ghost" type="button" data-prompt="show internal groups">Internal groups</button>
        <button class="btn ghost" type="button" data-prompt="show untracked queue">Untracked queue</button>
        <button class="btn ghost" type="button" data-prompt="start the selected run">Start selected</button>
      </div>
      <form class="chat-form" id="chatForm">
        <input id="chatInput" placeholder="Ask Pi to show campaigns, select one, or start a scrape" />
        <button class="btn" id="sendChatBtn" type="submit">Send</button>
      </form>
    </section>

    <main class="ops-pane">
      <div class="ops-header">
        <div>
          <h1>Scrape Control Plane</h1>
          <div class="muted" id="hubStatus">Campaign Hub API not loaded.</div>
        </div>
        <div class="topline">
          <span class="pill" id="hubPill">offline</span>
          <button class="btn secondary" id="loadHubBtn">Sync Hub</button>
        </div>
      </div>
      <div class="grid-4" id="hubMetrics"></div>

      <div class="ops-grid">
        <section>
          <div class="surface">
            <div class="panel-head">
              <div>
                <h2>Live Context</h2>
                <div class="muted">Campaigns, internal groups, and untracked links from Hub.</div>
              </div>
            </div>
            <div class="tabs">
              <button class="tab active" data-source-tab="campaigns">Campaigns</button>
              <button class="tab" data-source-tab="internal">Internal</button>
              <button class="tab" data-source-tab="queue">Queue</button>
            </div>
            <div id="sourceList" class="list"></div>
          </div>

          <div class="surface">
            <div class="panel-head">
              <div>
                <h2>Selected Scrape Brief</h2>
                <div class="muted" id="draftSource">No source selected.</div>
              </div>
              <button class="btn" id="startRunBtn">Start Run</button>
            </div>
            <div class="brief" id="briefPanel" style="margin-top:12px"></div>
            <details>
              <summary>Manual scrape parameters</summary>
              <div class="field" style="margin-top:12px">
                <label>Accounts</label>
                <textarea id="accounts" placeholder="@creator_one&#10;@creator_two"></textarea>
              </div>
              <div class="field">
                <label>Sound IDs</label>
                <textarea id="sounds" placeholder="7340478123456789012"></textarea>
              </div>
              <div class="form-grid">
                <div class="field">
                  <label>Hours</label>
                  <input id="hours" type="number" min="1" value="36" />
                </div>
                <div class="field">
                  <label>Limit</label>
                  <input id="limit" type="number" min="1" max="500" value="50" />
                </div>
                <div class="field">
                  <label>Workers</label>
                  <input id="workers" type="number" min="1" max="8" value="2" />
                </div>
                <div class="field">
                  <label>Start</label>
                  <input id="start" placeholder="YYYY-MM-DD HH:MM" />
                </div>
                <div class="field">
                  <label>End</label>
                  <input id="end" placeholder="now" />
                </div>
                <div class="field">
                  <label>Output</label>
                  <input id="output" value="output/local-scraper" />
                </div>
              </div>
            </details>
          </div>
        </section>

        <section>
          <div class="surface">
            <div class="grid-4" id="runMetrics"></div>
          </div>
          <div class="surface">
            <div class="panel-head">
              <h2>Runs</h2>
              <button class="btn secondary" id="refreshRunsBtn">Refresh</button>
            </div>
            <div class="stack" id="runs" style="margin-top:12px"></div>
          </div>
          <div class="surface">
            <div class="panel-head">
              <h2>Selected Run</h2>
              <button class="btn secondary" id="copyLinksBtn">Copy Links</button>
            </div>
            <div id="details" style="margin-top:12px"></div>
          </div>
        </section>
      </div>
    </main>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    const fmt = (n) => Number(n || 0).toLocaleString();
    let state = { runs: [] };
    let selectedRunId = null;
    let selectedSource = null;
    let selectedSourceTab = "campaigns";
    let hub = { loaded: false, error: "", campaigns: [], groups: [], internalCreators: [], queue: { campaigns: [], total_untracked: 0 } };

    async function api(path, options = {}) {
      const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || body.detail || res.statusText);
      return body;
    }
    const hubFetch = (path) => api(`/api/hub${path}`);

    async function loadHub(options = {}) {
      $("hubStatus").textContent = "Loading Campaign Hub data...";
      $("hubPill").textContent = "loading";
      $("hubPill").className = "pill warn";
      const results = await Promise.allSettled([
        hubFetch("/api/campaigns"),
        hubFetch("/api/internal/groups"),
        hubFetch("/api/internal/creators"),
        hubFetch("/api/scrape-tasks/queue?limit=20"),
      ]);
      hub.campaigns = results[0].status === "fulfilled" && Array.isArray(results[0].value) ? results[0].value : [];
      hub.groups = results[1].status === "fulfilled" && Array.isArray(results[1].value) ? results[1].value : [];
      hub.internalCreators = results[2].status === "fulfilled" && Array.isArray(results[2].value) ? results[2].value : [];
      hub.queue = results[3].status === "fulfilled" ? results[3].value : { campaigns: [], total_untracked: 0 };
      const failed = results.filter((r) => r.status === "rejected");
      hub.loaded = failed.length < results.length;
      hub.error = failed.map((r) => r.reason?.message || String(r.reason)).join("; ");
      renderHub();
      if (hub.loaded && !options.silent) {
        addMessage("Pi", `Loaded ${hub.campaigns.length} campaigns, ${hub.groups.length} internal groups, and ${hub.internalCreators.length} internal creators from Campaign Hub.`);
      } else if (!hub.loaded && !options.silent) {
        addMessage("Pi", "I could not reach Campaign Hub through the local proxy. Start Flask on port 5055 or set CAMPAIGN_HUB_API_URL before launching this GUI.");
      }
      return hub.loaded;
    }

    function renderHub() {
      $("hubStatus").textContent = hub.loaded ? "Real data loaded through /api/hub." : (hub.error || "Campaign Hub API not loaded.");
      $("hubPill").textContent = hub.loaded ? "live" : "offline";
      $("hubPill").className = `pill ${hub.loaded ? "good" : "bad"}`;
      $("hubMetrics").innerHTML = [
        ["Active", activeCampaigns().length],
        ["Returned", returnedCampaignRows().length],
        ["Groups", hub.groups.length],
        ["Untracked", hub.queue?.total_untracked || 0],
      ].map(([label, value]) => metric(label, value)).join("");
      renderSourceList();
      renderBrief();
      updateAgentStats();
    }

    function renderSourceList() {
      document.querySelectorAll("[data-source-tab]").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.sourceTab === selectedSourceTab);
      });
      const target = $("sourceList");
      if (!hub.loaded) {
        target.innerHTML = `<div class="empty">Sync Campaign Hub data to give Pi real campaign, internal, and queue context.</div>`;
        return;
      }
      if (selectedSourceTab === "campaigns") {
        const campaigns = activeCampaigns().slice(0, 90);
        target.innerHTML = campaigns.length ? campaigns.map((c) => `
          <div class="item ${selectedSource?.slug === c.slug ? "selected" : ""}" data-campaign="${esc(c.slug)}">
            <div class="item-title">${esc(c.title || c.slug)}</div>
            <div class="item-meta">${esc(c.artist || "")} - ${esc(c.song || "")} - ${c.creator_count || 0} creators - ${esc(c.start_date || "")} - ${esc(c.completion_status || "none")}</div>
          </div>
        `).join("") : `<div class="empty">No current active campaigns returned.</div>`;
        document.querySelectorAll("[data-campaign]").forEach((node) => {
          node.addEventListener("click", () => hydrateCampaign(node.dataset.campaign));
        });
      } else if (selectedSourceTab === "internal") {
        target.innerHTML = hub.groups.length ? hub.groups.map((g) => `
          <div class="item ${selectedSource?.slug === g.slug ? "selected" : ""}" data-group="${esc(g.slug)}">
            <div class="item-title">${esc(g.title || g.slug)}</div>
            <div class="item-meta">${g.member_count || 0} members - ${esc(g.kind || "group")}</div>
          </div>
        `).join("") : `<div class="empty">No internal groups returned.</div>`;
        document.querySelectorAll("[data-group]").forEach((node) => {
          node.addEventListener("click", () => hydrateGroup(node.dataset.group));
        });
      } else {
        const campaigns = hub.queue?.campaigns || [];
        target.innerHTML = campaigns.length ? campaigns.map((c) => `
          <div class="item" data-queue-campaign="${esc(c.slug)}">
            <div class="item-title">${esc(c.title || c.slug)}</div>
            <div class="item-meta">${c.untracked_count || 0} untracked - ${esc(c.artist || "")} - ${esc(c.song || "")}</div>
          </div>
        `).join("") : `<div class="empty">Scrape Tasks queue is empty or unavailable.</div>`;
        document.querySelectorAll("[data-queue-campaign]").forEach((node) => {
          node.addEventListener("click", () => hydrateCampaign(node.dataset.queueCampaign));
        });
      }
    }

    async function hydrateCampaign(slug) {
      const c = await hubFetch(`/api/campaign/${encodeURIComponent(slug)}`);
      const accounts = (c.creators || [])
        .filter((cr) => (cr.status || "active") === "active" && String(cr.platform || "tiktok").toLowerCase().includes("tiktok"))
        .map((cr) => cr.username ? `@${String(cr.username).replace(/^@/, "")}` : "")
        .filter(Boolean);
      const sounds = [c.sound_id, ...(c.additional_sounds || [])].filter(Boolean);
      $("accounts").value = accounts.join("\n");
      $("sounds").value = sounds.join("\n");
      $("start").value = c.start_date || "";
      $("draftSource").textContent = `Campaign: ${c.title || slug}`;
      selectedSource = { type: "campaign", slug, title: c.title || slug, accounts, sounds, start: c.start_date || "", detail: c };
      selectedSourceTab = "campaigns";
      renderSourceList();
      renderBrief();
      addMessage("Pi", `Hydrated ${accounts.length} creator accounts and ${sounds.length} sound IDs from ${c.title || slug}.`);
    }

    async function hydrateGroup(slug) {
      const g = await hubFetch(`/api/internal/groups/${encodeURIComponent(slug)}`);
      const accounts = (g.members || []).map((u) => `@${String(u).replace(/^@/, "")}`);
      $("accounts").value = accounts.join("\n");
      $("start").value = "";
      $("draftSource").textContent = `Internal group: ${g.title || slug}`;
      selectedSource = { type: "internal group", slug, title: g.title || slug, accounts, sounds: readList("sounds"), start: "", detail: g };
      selectedSourceTab = "internal";
      renderSourceList();
      renderBrief();
      addMessage("Pi", `Hydrated ${accounts.length} internal accounts from ${g.title || slug}. Add one or more sound IDs before running.`);
    }

    async function refreshRuns() {
      state = await api("/api/state");
      if (!selectedRunId && state.runs.length) selectedRunId = state.runs[0].id;
      if (selectedRunId && !state.runs.some((run) => run.id === selectedRunId)) selectedRunId = state.runs[0]?.id || null;
      renderRuns();
      updateAgentStats();
    }

    function renderRuns() {
      const run = currentRun();
      $("runMetrics").innerHTML = [
        ["Runs", state.runs.length],
        ["Accounts", run?.accounts_total || 0],
        ["Videos", run?.videos_kept || 0],
        ["Songs", run?.unique_songs || 0],
      ].map(([label, value]) => metric(label, value)).join("");
      $("runs").innerHTML = state.runs.length ? state.runs.map((r) => `
        <div class="run ${r.id === selectedRunId ? "selected" : ""}" data-run="${r.id}">
          <div class="run-top">
            <span class="run-id">${esc(r.id)}</span>
            <span class="run-status ${esc(r.status)}">${esc(r.status)}</span>
          </div>
          <div class="item-meta">${esc(r.progress)} - ${r.accounts_completed}/${r.accounts_total} accounts - ${fmt(r.videos_kept)} videos</div>
        </div>
      `).join("") : `<div class="empty">No runs yet.</div>`;
      document.querySelectorAll("[data-run]").forEach((node) => node.addEventListener("click", () => {
        selectedRunId = node.dataset.run;
        renderRuns();
      }));
      renderDetails();
    }

    function renderDetails() {
      const run = currentRun();
      if (!run) {
        $("details").innerHTML = `<div class="empty">Start a run to see results.</div>`;
        return;
      }
      const songs = run.report?.songs || [];
      $("details").innerHTML = `
        <div class="muted">${esc(run.output_dir)} - ${esc(run.created_at)}</div>
        ${run.error ? `<div class="item-meta" style="color:var(--bad);margin:8px 0">${esc(run.error)}</div>` : ""}
        <div class="log" style="margin:10px 0">${esc((run.logs || []).join("\n") || run.progress)}</div>
        <div class="stack">
          ${songs.length ? songs.map((song) => `
            <div class="song">
              <div class="run-top">
                <div>
                  <div class="item-title">${esc(song.song)} - ${esc(song.artist)}</div>
                  <div class="item-meta">${song.total_uses} posts - ${fmt(song.total_views)} views</div>
                </div>
                <button class="btn secondary song-copy" data-song="${esc(song.key)}">Copy</button>
              </div>
              <ul class="links">
                ${song.videos.slice(0, 12).map((v) => `<li><a href="${attr(v.url)}" target="_blank" rel="noreferrer">${esc(v.url)}</a></li>`).join("")}
              </ul>
            </div>
          `).join("") : `<div class="empty">${run.status === "done" ? "No matching videos in this run." : "Results will appear when the run completes."}</div>`}
        </div>
      `;
      document.querySelectorAll(".song-copy").forEach((btn) => btn.addEventListener("click", async () => {
        const song = songs.find((s) => s.key === btn.dataset.song);
        await navigator.clipboard.writeText((song?.videos || []).map((v) => v.url).join("\n"));
        btn.textContent = "Copied";
        setTimeout(() => btn.textContent = "Copy", 1000);
      }));
    }

    function renderBrief() {
      const accounts = readList("accounts");
      const sounds = readList("sounds");
      if (selectedSource) {
        selectedSource.accounts = accounts;
        selectedSource.sounds = sounds;
      }
      const sourceLabel = selectedSource ? `${selectedSource.type}: ${selectedSource.title}` : "No source selected";
      const ready = accounts.length > 0 && sounds.length > 0;
      $("briefPanel").innerHTML = `
        <div class="brief-row"><span>Source</span><span>${esc(sourceLabel)}</span></div>
        <div class="brief-row"><span>Accounts</span><span>${accounts.length ? `${accounts.length} loaded` : "missing"}</span></div>
        <div class="brief-row"><span>Sound IDs</span><span>${sounds.length ? `${sounds.length} loaded` : "missing"}</span></div>
        <div class="brief-row"><span>Window</span><span>${esc($("start").value || `${$("hours").value || 36} hours`)} to ${esc($("end").value || "now")}</span></div>
        <div class="brief-row"><span>Runner</span><span>${esc($("workers").value || 2)} workers - limit ${esc($("limit").value || 50)} - ${ready ? "ready" : "not ready"}</span></div>
      `;
      $("startRunBtn").disabled = !accounts.length;
      updateAgentStats();
    }

    function currentRun() {
      return state.runs.find((r) => r.id === selectedRunId) || state.runs[0] || null;
    }

    function draftRequest() {
      return {
        accounts_text: $("accounts").value,
        sound_ids_text: $("sounds").value,
        start: $("start").value,
        end: $("end").value === "now" ? "" : $("end").value,
        hours: Number($("hours").value || 36),
        limit: Number($("limit").value || 50),
        workers: Number($("workers").value || 2),
        timeout_seconds: 180,
        output_dir: $("output").value || "output/local-scraper",
      };
    }

    async function startRun() {
      const accounts = readList("accounts");
      if (!accounts.length) {
        addMessage("Pi", "There is no selected account list yet. Ask me to select a campaign or internal group first.");
        return;
      }
      $("startRunBtn").disabled = true;
      try {
        const run = await api("/api/runs", { method: "POST", body: JSON.stringify(draftRequest()) });
        selectedRunId = run.id;
        addMessage("Pi", `Started run ${run.id} with ${run.accounts_total} account(s).`);
        await refreshRuns();
      } catch (error) {
        addMessage("Pi", error.message);
      } finally {
        renderBrief();
      }
    }

    function setPiBusy(isBusy) {
      $("agentStatus").textContent = isBusy ? "thinking" : "ready";
      $("chatInput").disabled = isBusy;
      $("sendChatBtn").disabled = isBusy;
      document.querySelectorAll("[data-prompt]").forEach((btn) => {
        btn.disabled = isBusy;
      });
    }

    async function sendChat(message) {
      addMessage("You", message, true);
      setPiBusy(true);
      try {
        const response = await api("/api/chat", { method: "POST", body: JSON.stringify({ message, context: chatContext() }) });
        addMessage("Pi", response.reply);
        if (response.request) {
          $("accounts").value = response.request.accounts_text || $("accounts").value;
          $("sounds").value = response.request.sound_ids_text || $("sounds").value;
          $("hours").value = response.request.hours || $("hours").value;
          $("limit").value = response.request.limit || $("limit").value;
          $("workers").value = response.request.workers || $("workers").value;
          selectedSource = { type: "manual", slug: "manual", title: "Manual scrape request", accounts: readList("accounts"), sounds: readList("sounds") };
          $("draftSource").textContent = "Manual scrape request";
          renderBrief();
        }
        if (response.run_id) {
          selectedRunId = response.run_id;
          await refreshRuns();
        }
      } catch (error) {
        addMessage("Pi", error.message);
      } finally {
        setPiBusy(false);
      }
    }

    function activeCampaigns() {
      return returnedCampaignRows().filter((c) => (c.completion_status || "none") !== "completed");
    }

    function returnedCampaignRows() {
      return hub.campaigns.filter((c) => (c.status || "active") === "active");
    }

    function chatContext() {
      return {
        selected_source: selectedSource,
        source_tab: selectedSourceTab,
        draft: draftRequest(),
        hub_summary: {
          current_active_campaigns: activeCampaigns().length,
          returned_campaign_rows: returnedCampaignRows().length,
          groups: hub.groups.length,
          internal_creators: hub.internalCreators.length,
          untracked: hub.queue?.total_untracked || 0,
        },
        current_run: currentRun(),
      };
    }

    function readList(id) {
      return String($(id)?.value || "").split(/[\s,;]+/).map((v) => v.trim()).filter(Boolean);
    }

    function updateAgentStats() {
      const brief = selectedSource ? `${readList("accounts").length} acct` : "-";
      $("agentStats").innerHTML = `
        <div class="agent-stat"><b>${hub.loaded ? "live" : "-"}</b><span>Hub</span></div>
        <div class="agent-stat"><b>${state.runs.length}</b><span>Runs</span></div>
        <div class="agent-stat"><b>${esc(brief)}</b><span>Brief</span></div>
      `;
    }

    function metric(label, value) {
      return `<div class="metric"><div class="metric-value">${fmt(value)}</div><div class="metric-label">${esc(label)}</div></div>`;
    }

    function addMessage(who, text, user = false) {
      const node = document.createElement("div");
      node.className = `msg ${user ? "user" : ""}`;
      node.textContent = `${who}: ${text}`;
      $("messages").appendChild(node);
      $("messages").scrollTop = $("messages").scrollHeight;
    }

    function esc(value) {
      return String(value || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    }

    function attr(value) { return esc(value).replace(/`/g, "&#96;"); }

    document.querySelectorAll("[data-source-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        selectedSourceTab = btn.dataset.sourceTab;
        renderSourceList();
      });
    });
    document.querySelectorAll("[data-prompt]").forEach((btn) => {
      btn.addEventListener("click", () => sendChat(btn.dataset.prompt));
    });
    ["accounts", "sounds", "start", "end", "hours", "limit", "workers", "output"].forEach((id) => {
      $(id).addEventListener("input", renderBrief);
    });
    $("loadHubBtn").addEventListener("click", () => loadHub());
    $("refreshRunsBtn").addEventListener("click", refreshRuns);
    $("startRunBtn").addEventListener("click", startRun);
    $("copyLinksBtn").addEventListener("click", async () => {
      const run = currentRun();
      if (!run) return;
      const payload = await api("/api/tools/call", { method: "POST", body: JSON.stringify({ name: "scrape.copy_links", arguments: { id: run.id } }) }).catch((error) => ({ text: error.message }));
      await navigator.clipboard.writeText(payload.text || "");
      $("copyLinksBtn").textContent = "Copied";
      setTimeout(() => $("copyLinksBtn").textContent = "Copy Links", 1000);
    });
    $("chatForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = $("chatInput");
      const message = input.value.trim();
      if (!message) return;
      input.value = "";
      await sendChat(message);
    });

    addMessage("Pi", "Ready. Ask me to check active campaigns, show internal groups, inspect the untracked queue, or select a source for a scrape.");
    renderHub();
    refreshRuns();
    loadHub({ silent: true }).then((ok) => {
      if (ok) addMessage("Pi", `Hub synced. I can see ${activeCampaigns().length} current active campaigns from ${returnedCampaignRows().length} returned campaign rows, plus ${hub.groups.length} internal groups and ${hub.internalCreators.length} internal creators.`);
    });
    setInterval(refreshRuns, 1800);
  </script>
</body>
</html>"#;
