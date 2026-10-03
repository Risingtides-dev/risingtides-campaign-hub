use anyhow::{bail, Context, Result};
use chrono::{DateTime, Duration, Local, LocalResult, NaiveDate, NaiveDateTime, TimeZone, Utc};
use clap::Parser;
use serde::Serialize;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration as StdDuration;
use wait_timeout::ChildExt;

mod gui;

const DEFAULT_USER_AGENT: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) \
AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

#[derive(Parser, Debug)]
#[command(
    name = "rt-yt-scraper",
    about = "Local TikTok account scraper for Rising Tides campaign post links"
)]
struct Args {
    /// TikTok account handle, profile URL, or multiple repeated --account values.
    #[arg(short = 'a', long = "account")]
    accounts: Vec<String>,

    /// File containing handles or profile URLs, separated by newlines, commas, or whitespace.
    #[arg(long = "accounts-file")]
    accounts_file: Option<PathBuf>,

    /// Only keep videos using one of these TikTok music/sound IDs. May be repeated.
    #[arg(long = "sound-id")]
    sound_ids: Vec<String>,

    /// Start of the scrape window in local time: YYYY-MM-DD, YYYY-MM-DD HH:MM, or YYYY-MM-DD HH:MM:SS.
    #[arg(long)]
    start: Option<String>,

    /// End of the scrape window in local time. Defaults to now.
    #[arg(long)]
    end: Option<String>,

    /// Look back this many hours when --start is omitted.
    #[arg(long, default_value_t = 36)]
    hours: i64,

    /// Maximum videos to ask yt-dlp for per account.
    #[arg(long, default_value_t = 50)]
    limit: usize,

    /// Parallel yt-dlp processes. Keep this low to avoid TikTok throttling.
    #[arg(long, default_value_t = 2)]
    workers: usize,

    /// Per-account yt-dlp timeout in seconds.
    #[arg(long, default_value_t = 180)]
    timeout_seconds: u64,

    /// Directory for scrape_report.json, post_links_by_song.txt, and post_links_copy_paste.txt.
    #[arg(long, default_value = "output/local-scraper")]
    output_dir: PathBuf,

    /// Print yt-dlp commands without executing them.
    #[arg(long)]
    dry_run: bool,

    /// Start the local scraper GUI server instead of running a scrape.
    #[arg(long)]
    gui: bool,

    /// Host for the local GUI server.
    #[arg(long, default_value = "127.0.0.1")]
    host: String,

    /// Port for the local GUI server.
    #[arg(long, default_value_t = 8787)]
    port: u16,
}

#[derive(Debug, Clone)]
pub(crate) struct YtDlp {
    program: String,
    prefix_args: Vec<String>,
}

#[derive(Debug, Clone)]
pub(crate) struct RunConfig {
    yt_dlp: YtDlp,
    start: DateTime<Local>,
    end: DateTime<Local>,
    limit: usize,
    timeout_seconds: u64,
    sound_ids: BTreeSet<String>,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct Video {
    url: String,
    song: String,
    artist: String,
    account: String,
    views: u64,
    likes: u64,
    upload_date: String,
    timestamp: String,
    music_id: String,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct AccountResult {
    account: String,
    profile_url: String,
    status: String,
    fetched: usize,
    kept: usize,
    error: String,
    videos: Vec<Video>,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SongGroup {
    key: String,
    song: String,
    artist: String,
    total_uses: usize,
    total_views: u64,
    total_likes: u64,
    accounts: Vec<String>,
    videos: Vec<Video>,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct ScrapeReport {
    generated_at: String,
    window_start: String,
    window_end: String,
    sound_ids: Vec<String>,
    accounts_total: usize,
    accounts_successful: usize,
    accounts_failed: usize,
    total_videos: usize,
    unique_songs: usize,
    accounts: Vec<AccountResult>,
    songs: Vec<SongGroup>,
}

#[derive(Default)]
struct SongAccumulator {
    song: String,
    artist: String,
    total_views: u64,
    total_likes: u64,
    accounts: BTreeSet<String>,
    videos: Vec<Video>,
}

fn main() -> Result<()> {
    let args = Args::parse();

    if args.gui {
        return gui::serve(gui::GuiOptions {
            host: args.host,
            port: args.port,
        });
    }

    let accounts = load_accounts(&args)?;
    if accounts.is_empty() {
        bail!("No accounts provided. Use --account or --accounts-file.");
    }

    let end = match args.end.as_deref() {
        Some(raw) => parse_local_datetime(raw).context("invalid --end")?,
        None => Local::now(),
    };
    let start = match args.start.as_deref() {
        Some(raw) => parse_local_datetime(raw).context("invalid --start")?,
        None => end - Duration::hours(args.hours),
    };
    if start > end {
        bail!("--start must be before --end");
    }

    let sound_ids = args
        .sound_ids
        .iter()
        .filter_map(|s| normalize_sound_id(s))
        .collect::<BTreeSet<_>>();

    let config = RunConfig {
        yt_dlp: detect_yt_dlp(),
        start,
        end,
        limit: args.limit,
        timeout_seconds: args.timeout_seconds,
        sound_ids,
    };

    if args.dry_run {
        for account in accounts {
            let cmd = build_yt_dlp_args(&config, &account);
            println!("{} {}", config.yt_dlp.program, shell_join(&cmd));
        }
        return Ok(());
    }

    let worker_count = args.workers.clamp(1, 8).min(accounts.len().max(1));
    eprintln!(
        "Scraping {} account(s), {} worker(s), window {} to {}",
        accounts.len(),
        worker_count,
        config.start.format("%Y-%m-%d %H:%M:%S"),
        config.end.format("%Y-%m-%d %H:%M:%S")
    );

    let results = scrape_accounts(accounts, config.clone(), worker_count, |_| {})?;
    let report = build_report(results, &config);
    write_outputs(&args.output_dir, &report)?;

    println!(
        "Done: {} videos across {} song(s). Wrote {}",
        report.total_videos,
        report.unique_songs,
        args.output_dir.display()
    );

    Ok(())
}

pub(crate) fn detect_yt_dlp() -> YtDlp {
    if let Ok(bin) = env::var("YT_DLP_BIN") {
        if !bin.trim().is_empty() {
            return YtDlp {
                program: bin,
                prefix_args: Vec::new(),
            };
        }
    }

    if Command::new("yt-dlp").arg("--version").output().is_ok() {
        return YtDlp {
            program: "yt-dlp".to_string(),
            prefix_args: Vec::new(),
        };
    }

    YtDlp {
        program: env::var("PYTHON").unwrap_or_else(|_| "python3".to_string()),
        prefix_args: vec!["-m".to_string(), "yt_dlp".to_string()],
    }
}

fn load_accounts(args: &Args) -> Result<Vec<String>> {
    let mut raw = args.accounts.clone();

    if let Some(path) = &args.accounts_file {
        let content = fs::read_to_string(path)
            .with_context(|| format!("failed to read accounts file {}", path.display()))?;
        for line in content.lines() {
            let line = line.split('#').next().unwrap_or("");
            raw.extend(
                line.split(|c: char| c == ',' || c.is_whitespace())
                    .filter(|part| !part.trim().is_empty())
                    .map(str::to_string),
            );
        }
    }

    let mut out = Vec::new();
    let mut seen = BTreeSet::new();
    for item in raw {
        if let Some(account) = normalize_account(&item) {
            if seen.insert(account.clone()) {
                out.push(account);
            }
        }
    }
    Ok(out)
}

pub(crate) fn normalize_account(input: &str) -> Option<String> {
    let trimmed = input.trim().trim_end_matches('/');
    if trimmed.is_empty() {
        return None;
    }

    if let Some(at_pos) = trimmed.find('@') {
        let candidate = trimmed[at_pos + 1..]
            .chars()
            .take_while(|c| c.is_ascii_alphanumeric() || *c == '_' || *c == '.')
            .collect::<String>();
        return (!candidate.is_empty()).then_some(candidate);
    }

    let username = trimmed
        .trim_start_matches('@')
        .chars()
        .take_while(|c| c.is_ascii_alphanumeric() || *c == '_' || *c == '.')
        .collect::<String>();
    (!username.is_empty()).then_some(username)
}

pub(crate) fn normalize_sound_id(input: &str) -> Option<String> {
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return None;
    }
    if trimmed.chars().all(|c| c.is_ascii_digit()) {
        return Some(trimmed.to_string());
    }

    let mut current = String::new();
    let mut groups = Vec::new();
    for ch in trimmed.chars() {
        if ch.is_ascii_digit() {
            current.push(ch);
        } else if !current.is_empty() {
            groups.push(std::mem::take(&mut current));
        }
    }
    if !current.is_empty() {
        groups.push(current);
    }

    groups.into_iter().rev().find(|g| g.len() >= 5)
}

pub(crate) fn parse_local_datetime(raw: &str) -> Result<DateTime<Local>> {
    let raw = raw.trim();
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"] {
        if let Ok(naive) = NaiveDateTime::parse_from_str(raw, fmt) {
            return localize_datetime(naive);
        }
    }
    if let Ok(date) = NaiveDate::parse_from_str(raw, "%Y-%m-%d") {
        let naive = date
            .and_hms_opt(0, 0, 0)
            .context("failed to build midnight timestamp")?;
        return localize_datetime(naive);
    }
    bail!("expected YYYY-MM-DD, YYYY-MM-DD HH:MM, or YYYY-MM-DD HH:MM:SS")
}

fn localize_datetime(naive: NaiveDateTime) -> Result<DateTime<Local>> {
    match Local.from_local_datetime(&naive) {
        LocalResult::Single(dt) => Ok(dt),
        LocalResult::Ambiguous(earliest, _) => Ok(earliest),
        LocalResult::None => bail!("local time does not exist: {naive}"),
    }
}

pub(crate) fn scrape_accounts<F>(
    accounts: Vec<String>,
    config: RunConfig,
    worker_count: usize,
    mut on_result: F,
) -> Result<Vec<AccountResult>>
where
    F: FnMut(&AccountResult),
{
    let queue = Arc::new(Mutex::new(VecDeque::from(accounts)));
    let config = Arc::new(config);
    let (tx, rx) = mpsc::channel();

    for _ in 0..worker_count {
        let queue = Arc::clone(&queue);
        let config = Arc::clone(&config);
        let tx = tx.clone();
        std::thread::spawn(move || loop {
            let account = {
                let mut guard = queue.lock().expect("queue lock poisoned");
                guard.pop_front()
            };
            let Some(account) = account else {
                break;
            };
            let result = scrape_account(&account, &config);
            if tx.send(result).is_err() {
                break;
            }
        });
    }
    drop(tx);

    let mut results = Vec::new();
    for result in rx {
        on_result(&result);
        eprintln!(
            "@{}: {} (fetched {}, kept {}){}",
            result.account,
            result.status,
            result.fetched,
            result.kept,
            if result.error.is_empty() {
                String::new()
            } else {
                format!(" - {}", result.error)
            }
        );
        results.push(result);
    }
    results.sort_by(|a, b| a.account.cmp(&b.account));
    Ok(results)
}

fn scrape_account(account: &str, config: &RunConfig) -> AccountResult {
    let profile_url = format!("https://www.tiktok.com/@{account}");
    let args = build_yt_dlp_args(config, account);

    let mut child = match Command::new(&config.yt_dlp.program)
        .args(&args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(err) => {
            return AccountResult {
                account: account.to_string(),
                profile_url,
                status: "error".to_string(),
                fetched: 0,
                kept: 0,
                error: format!("failed to start yt-dlp: {err}"),
                videos: Vec::new(),
            };
        }
    };

    let timeout = StdDuration::from_secs(config.timeout_seconds);
    match child.wait_timeout(timeout) {
        Ok(Some(_)) => {}
        Ok(None) => {
            let _ = child.kill();
            let output = child.wait_with_output();
            let stderr = output
                .ok()
                .map(|o| String::from_utf8_lossy(&o.stderr).trim().to_string())
                .unwrap_or_default();
            return AccountResult {
                account: account.to_string(),
                profile_url,
                status: "timeout".to_string(),
                fetched: 0,
                kept: 0,
                error: if stderr.is_empty() {
                    format!("timed out after {}s", config.timeout_seconds)
                } else {
                    stderr
                },
                videos: Vec::new(),
            };
        }
        Err(err) => {
            return AccountResult {
                account: account.to_string(),
                profile_url,
                status: "error".to_string(),
                fetched: 0,
                kept: 0,
                error: format!("failed waiting for yt-dlp: {err}"),
                videos: Vec::new(),
            };
        }
    }

    let output = match child.wait_with_output() {
        Ok(output) => output,
        Err(err) => {
            return AccountResult {
                account: account.to_string(),
                profile_url,
                status: "error".to_string(),
                fetched: 0,
                kept: 0,
                error: format!("failed to read yt-dlp output: {err}"),
                videos: Vec::new(),
            };
        }
    };

    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if !output.status.success() {
        return AccountResult {
            account: account.to_string(),
            profile_url,
            status: "error".to_string(),
            fetched: 0,
            kept: 0,
            error: first_line(&stderr),
            videos: Vec::new(),
        };
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    if stdout.trim().is_empty() {
        return AccountResult {
            account: account.to_string(),
            profile_url,
            status: "empty".to_string(),
            fetched: 0,
            kept: 0,
            error: if stderr.is_empty() {
                "yt-dlp returned no rows".to_string()
            } else {
                first_line(&stderr)
            },
            videos: Vec::new(),
        };
    }

    let (fetched, videos) = parse_yt_dlp_stdout(account, &stdout, config);
    let status = if videos.is_empty() { "empty" } else { "ok" };
    AccountResult {
        account: account.to_string(),
        profile_url,
        status: status.to_string(),
        fetched,
        kept: videos.len(),
        error: String::new(),
        videos,
    }
}

fn build_yt_dlp_args(config: &RunConfig, account: &str) -> Vec<String> {
    let mut args = config.yt_dlp.prefix_args.clone();
    args.extend([
        "--flat-playlist".to_string(),
        "--dump-json".to_string(),
        "--playlist-end".to_string(),
        config.limit.to_string(),
        "--user-agent".to_string(),
        env::var("TIKTOK_USER_AGENT").unwrap_or_else(|_| DEFAULT_USER_AGENT.to_string()),
        "--retries".to_string(),
        "3".to_string(),
        "--fragment-retries".to_string(),
        "3".to_string(),
        "--socket-timeout".to_string(),
        "30".to_string(),
    ]);

    if env::var("TIKTOK_IMPERSONATE").unwrap_or_else(|_| "0".to_string()) == "1" {
        let target = env::var("TIKTOK_IMPERSONATE_TARGET").unwrap_or_else(|_| "chrome".to_string());
        if !target.trim().is_empty() {
            args.extend(["--impersonate".to_string(), target]);
        }
    }

    if let Ok(cookies) = env::var("TIKTOK_COOKIES_FILE") {
        if !cookies.trim().is_empty() && Path::new(&cookies).exists() {
            args.extend(["--cookies".to_string(), cookies]);
        }
    }

    if let Ok(proxy) = env::var("TIKTOK_PROXY") {
        if !proxy.trim().is_empty() {
            args.extend(["--proxy".to_string(), proxy]);
        }
    }

    args.push(format!("https://www.tiktok.com/@{account}"));
    args
}

fn parse_yt_dlp_stdout(account: &str, stdout: &str, config: &RunConfig) -> (usize, Vec<Video>) {
    let mut fetched = 0;
    let mut videos = Vec::new();

    for line in stdout
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
    {
        let Ok(value) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        fetched += 1;

        let Some(video) = video_from_value(account, &value) else {
            continue;
        };

        if !is_in_window(&video, &value, config.start, config.end) {
            continue;
        }

        if !config.sound_ids.is_empty() {
            let Some(music_id) = normalize_sound_id(&video.music_id) else {
                continue;
            };
            if !config.sound_ids.contains(&music_id) {
                continue;
            }
        }

        videos.push(video);
    }

    (fetched, videos)
}

fn video_from_value(account: &str, value: &Value) -> Option<Video> {
    let url = json_string(value, "webpage_url")
        .or_else(|| json_string(value, "url"))
        .unwrap_or_default();
    if url.is_empty() {
        return None;
    }

    let song = json_string(value, "track")
        .or_else(|| json_string(value, "title"))
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "Unknown".to_string());

    let artist = json_string(value, "artist")
        .or_else(|| {
            value
                .get("artists")
                .and_then(Value::as_array)
                .and_then(|artists| artists.first())
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "Unknown".to_string());

    let posted = parse_video_datetime(value);
    let timestamp = posted
        .map(|dt| dt.format("%Y-%m-%dT%H:%M:%S%:z").to_string())
        .unwrap_or_default();

    Some(Video {
        url,
        song,
        artist,
        account: format!("@{account}"),
        views: json_u64(value, "view_count"),
        likes: json_u64(value, "like_count"),
        upload_date: json_string(value, "upload_date").unwrap_or_default(),
        timestamp,
        music_id: json_string(value, "music_id").unwrap_or_default(),
    })
}

fn is_in_window(video: &Video, raw: &Value, start: DateTime<Local>, end: DateTime<Local>) -> bool {
    let posted = if video.timestamp.is_empty() {
        parse_video_datetime(raw)
    } else {
        DateTime::parse_from_rfc3339(&video.timestamp)
            .ok()
            .map(|dt| dt.with_timezone(&Local))
    };

    match posted {
        Some(dt) => dt >= start && dt <= end,
        None => true,
    }
}

fn parse_video_datetime(value: &Value) -> Option<DateTime<Local>> {
    if let Some(ts) = value.get("timestamp") {
        let seconds = ts
            .as_i64()
            .or_else(|| ts.as_str().and_then(|s| s.parse::<i64>().ok()));
        if let Some(seconds) = seconds {
            if let Some(dt) = DateTime::<Utc>::from_timestamp(seconds, 0) {
                return Some(dt.with_timezone(&Local));
            }
        }
    }

    let upload = json_string(value, "upload_date")?;
    let date = NaiveDate::parse_from_str(&upload, "%Y%m%d").ok()?;
    let naive = date.and_hms_opt(0, 0, 0)?;
    localize_datetime(naive).ok()
}

fn json_string(value: &Value, key: &str) -> Option<String> {
    let v = value.get(key)?;
    if let Some(s) = v.as_str() {
        return Some(s.to_string());
    }
    if let Some(n) = v.as_i64() {
        return Some(n.to_string());
    }
    if let Some(n) = v.as_u64() {
        return Some(n.to_string());
    }
    None
}

fn json_u64(value: &Value, key: &str) -> u64 {
    value
        .get(key)
        .and_then(|v| {
            v.as_u64()
                .or_else(|| v.as_i64().and_then(|n| (n >= 0).then_some(n as u64)))
                .or_else(|| v.as_str().and_then(|s| s.parse::<u64>().ok()))
        })
        .unwrap_or(0)
}

pub(crate) fn build_report(
    mut account_results: Vec<AccountResult>,
    config: &RunConfig,
) -> ScrapeReport {
    let mut by_song: BTreeMap<String, SongAccumulator> = BTreeMap::new();

    for result in &account_results {
        for video in &result.videos {
            let key = format!("{} - {}", video.song.trim(), video.artist.trim());
            let entry = by_song.entry(key).or_default();
            entry.song = video.song.clone();
            entry.artist = video.artist.clone();
            entry.total_views += video.views;
            entry.total_likes += video.likes;
            entry.accounts.insert(video.account.clone());
            entry.videos.push(video.clone());
        }
    }

    let mut songs = by_song
        .into_iter()
        .map(|(key, mut acc)| {
            acc.videos.sort_by(|a, b| {
                b.views
                    .cmp(&a.views)
                    .then_with(|| a.account.cmp(&b.account))
            });
            SongGroup {
                key,
                song: acc.song,
                artist: acc.artist,
                total_uses: acc.videos.len(),
                total_views: acc.total_views,
                total_likes: acc.total_likes,
                accounts: acc.accounts.into_iter().collect(),
                videos: acc.videos,
            }
        })
        .collect::<Vec<_>>();

    songs.sort_by(|a, b| {
        b.total_views
            .cmp(&a.total_views)
            .then_with(|| a.key.cmp(&b.key))
    });

    account_results.sort_by(|a, b| a.account.cmp(&b.account));
    let accounts_failed = account_results
        .iter()
        .filter(|r| r.status == "error" || r.status == "timeout")
        .count();
    let accounts_successful = account_results.len().saturating_sub(accounts_failed);
    let total_videos = songs.iter().map(|s| s.total_uses).sum();
    let sound_ids = config.sound_ids.iter().cloned().collect::<Vec<_>>();

    ScrapeReport {
        generated_at: Local::now().format("%Y-%m-%dT%H:%M:%S%:z").to_string(),
        window_start: config.start.format("%Y-%m-%dT%H:%M:%S%:z").to_string(),
        window_end: config.end.format("%Y-%m-%dT%H:%M:%S%:z").to_string(),
        sound_ids,
        accounts_total: account_results.len(),
        accounts_successful,
        accounts_failed,
        total_videos,
        unique_songs: songs.len(),
        accounts: account_results,
        songs,
    }
}

pub(crate) fn write_outputs(output_dir: &Path, report: &ScrapeReport) -> Result<()> {
    fs::create_dir_all(output_dir)
        .with_context(|| format!("failed to create {}", output_dir.display()))?;

    let json_path = output_dir.join("scrape_report.json");
    fs::write(&json_path, serde_json::to_string_pretty(report)?)
        .with_context(|| format!("failed to write {}", json_path.display()))?;

    let detailed_path = output_dir.join("post_links_by_song.txt");
    fs::write(&detailed_path, render_detailed_report(report))
        .with_context(|| format!("failed to write {}", detailed_path.display()))?;

    let copy_path = output_dir.join("post_links_copy_paste.txt");
    fs::write(&copy_path, render_copy_paste(report))
        .with_context(|| format!("failed to write {}", copy_path.display()))?;

    Ok(())
}

fn render_detailed_report(report: &ScrapeReport) -> String {
    let mut out = String::new();
    out.push_str("POST LINKS GROUPED BY SONG\n");
    out.push_str(
        "================================================================================\n\n",
    );
    out.push_str(&format!("Generated: {}\n", report.generated_at));
    out.push_str(&format!(
        "Window: {} to {}\n",
        report.window_start, report.window_end
    ));
    out.push_str(&format!("Accounts processed: {}\n", report.accounts_total));
    out.push_str(&format!("Total videos: {}\n", report.total_videos));
    out.push_str(&format!("Unique songs: {}\n", report.unique_songs));
    if !report.sound_ids.is_empty() {
        out.push_str(&format!("Sound filters: {}\n", report.sound_ids.join(", ")));
    }
    out.push('\n');

    for song in &report.songs {
        out.push_str(
            "\n================================================================================\n",
        );
        out.push_str(&format!("SONG: {}\n", song.song));
        out.push_str(&format!("ARTIST: {}\n", song.artist));
        out.push_str(&format!("Total Uses: {}\n", song.total_uses));
        out.push_str(&format!("Accounts: {}\n", song.accounts.join(", ")));
        out.push_str(&format!(
            "Total Views: {}\n",
            format_number(song.total_views)
        ));
        out.push_str(&format!(
            "Total Likes: {}\n",
            format_number(song.total_likes)
        ));
        out.push_str(&format!("\nPost Links ({} videos):\n", song.videos.len()));
        out.push_str(
            "--------------------------------------------------------------------------------\n",
        );
        for (idx, video) in song.videos.iter().enumerate() {
            out.push_str(&format!("  {}. {}\n", idx + 1, video.url));
            out.push_str(&format!(
                "     Account: {} | Views: {} | Likes: {} | Music ID: {}\n",
                video.account,
                format_number(video.views),
                format_number(video.likes),
                if video.music_id.is_empty() {
                    "-"
                } else {
                    &video.music_id
                }
            ));
        }
    }

    out
}

fn render_copy_paste(report: &ScrapeReport) -> String {
    let mut out = String::new();
    out.push_str("POST LINKS - COPY/PASTE FORMAT\n");
    out.push_str(
        "================================================================================\n\n",
    );
    out.push_str(&format!("Generated: {}\n", report.generated_at));
    out.push_str(&format!(
        "Window: {} to {}\n",
        report.window_start, report.window_end
    ));
    out.push_str(&format!("Accounts processed: {}\n", report.accounts_total));
    out.push_str(&format!("Total videos: {}\n", report.total_videos));
    out.push_str(&format!("Unique songs: {}\n\n", report.unique_songs));

    for song in &report.songs {
        out.push_str(
            "\n================================================================================\n",
        );
        out.push_str(&format!("SONG: {} - {}\n", song.song, song.artist));
        out.push_str(&format!(
            "Total Uses: {} | Total Views: {}\n",
            song.total_uses,
            format_number(song.total_views)
        ));
        out.push_str(
            "================================================================================\n\n",
        );
        for video in &song.videos {
            out.push_str(&video.url);
            out.push('\n');
        }
        out.push('\n');
    }

    out
}

fn format_number(n: u64) -> String {
    let s = n.to_string();
    let mut out = String::new();
    for (idx, ch) in s.chars().rev().enumerate() {
        if idx > 0 && idx % 3 == 0 {
            out.push(',');
        }
        out.push(ch);
    }
    out.chars().rev().collect()
}

fn first_line(input: &str) -> String {
    input
        .lines()
        .next()
        .unwrap_or("unknown yt-dlp error")
        .trim()
        .chars()
        .take(300)
        .collect()
}

fn shell_join(args: &[String]) -> String {
    args.iter()
        .map(|arg| {
            if arg
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || "-_./:@=".contains(c))
            {
                arg.clone()
            } else {
                format!("'{}'", arg.replace('\'', "'\\''"))
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn account_normalization_handles_urls_and_handles() {
        assert_eq!(
            normalize_account("@foo.bar_1").as_deref(),
            Some("foo.bar_1")
        );
        assert_eq!(
            normalize_account("https://www.tiktok.com/@foo.bar_1/video/123").as_deref(),
            Some("foo.bar_1")
        );
    }

    #[test]
    fn sound_id_normalization_extracts_ids_from_urls() {
        assert_eq!(
            normalize_sound_id("https://www.tiktok.com/music/song-name-7340478123456789012")
                .as_deref(),
            Some("7340478123456789012")
        );
        assert_eq!(
            normalize_sound_id("7340478123456789012").as_deref(),
            Some("7340478123456789012")
        );
    }

    #[test]
    fn format_number_adds_grouping() {
        assert_eq!(format_number(0), "0");
        assert_eq!(format_number(1200), "1,200");
        assert_eq!(format_number(1234567), "1,234,567");
    }
}
