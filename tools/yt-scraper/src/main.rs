use anyhow::{bail, Context, Result};
use chrono::{DateTime, Duration, Local, LocalResult, NaiveDate, NaiveDateTime, TimeZone, Utc};
use clap::Parser;
use serde::Serialize;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::env;
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration as StdDuration, Instant};
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

// Reading only after wait_timeout can fill either pipe and prevent child exit.
// Each reader checks readiness instead of blocking in read_to_end, so inherited
// descendant handles cannot keep a reader alive beyond the account deadline.
trait OutputPipe: Read + Send + 'static {
    fn read_ready(&self) -> io::Result<bool>;
}

#[cfg(unix)]
impl<T: Read + Send + std::os::fd::AsRawFd + 'static> OutputPipe for T {
    fn read_ready(&self) -> io::Result<bool> {
        #[repr(C)]
        struct PollFd {
            fd: std::os::raw::c_int,
            events: std::os::raw::c_short,
            revents: std::os::raw::c_short,
        }
        #[cfg(any(target_os = "linux", target_os = "android"))]
        type Nfds = std::os::raw::c_ulong;
        #[cfg(not(any(target_os = "linux", target_os = "android")))]
        type Nfds = std::os::raw::c_uint;
        extern "C" {
            fn poll(fds: *mut PollFd, nfds: Nfds, timeout: std::os::raw::c_int)
                -> std::os::raw::c_int;
        }
        let mut fd = PollFd {
            fd: self.as_raw_fd(),
            events: 1, // POLLIN; poll also reports EOF/error readiness.
            revents: 0,
        };
        // The descriptor remains owned by this reader; poll does not change it.
        let result = unsafe { poll(&mut fd, 1, 0) };
        if result < 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(result > 0)
        }
    }
}

#[cfg(windows)]
impl<T: Read + Send + std::os::windows::io::AsRawHandle + 'static> OutputPipe for T {
    fn read_ready(&self) -> io::Result<bool> {
        #[link(name = "kernel32")]
        extern "system" {
            fn PeekNamedPipe(
                handle: *mut std::ffi::c_void,
                buffer: *mut std::ffi::c_void,
                buffer_size: u32,
                read: *mut u32,
                available: *mut u32,
                remaining: *mut u32,
            ) -> i32;
        }
        let mut available = 0;
        // Peek only; Read owns consumption. A broken pipe is EOF-ready.
        let result = unsafe {
            PeekNamedPipe(
                self.as_raw_handle(),
                std::ptr::null_mut(),
                0,
                std::ptr::null_mut(),
                &mut available,
                std::ptr::null_mut(),
            )
        };
        if result != 0 {
            Ok(available > 0)
        } else {
            let error = io::Error::last_os_error();
            if error.raw_os_error() == Some(109) {
                Ok(true)
            } else {
                Err(error)
            }
        }
    }
}

fn drain_pipe(
    mut pipe: impl OutputPipe,
    deadline: Instant,
    cancelled: Arc<AtomicBool>,
) -> mpsc::Receiver<io::Result<(Vec<u8>, bool)>> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut buffer = [0u8; 8192];
        let result = loop {
            if cancelled.load(Ordering::Relaxed) || Instant::now() >= deadline {
                break Ok((bytes, false));
            }
            match pipe.read_ready() {
                Ok(false) => std::thread::sleep(StdDuration::from_millis(10)),
                Ok(true) => match pipe.read(&mut buffer) {
                    Ok(0) => break Ok((bytes, true)),
                    Ok(count) => bytes.extend_from_slice(&buffer[..count]),
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                    Err(error) => break Err(error),
                },
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(error) => break Err(error),
            }
        };
        let _ = tx.send(result);
    });
    rx
}

fn receive_pipe(
    rx: mpsc::Receiver<io::Result<(Vec<u8>, bool)>>,
    deadline: Instant,
) -> io::Result<(Vec<u8>, bool)> {
    rx.recv_timeout(
        deadline.saturating_duration_since(Instant::now()) + StdDuration::from_millis(100),
    )
    .map_err(|error| io::Error::new(io::ErrorKind::TimedOut, error))?
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
    let deadline = Instant::now() + timeout;
    let cancelled = Arc::new(AtomicBool::new(false));
    let stdout_rx = drain_pipe(
        child.stdout.take().expect("stdout is piped"),
        deadline,
        Arc::clone(&cancelled),
    );
    let stderr_rx = drain_pipe(
        child.stderr.take().expect("stderr is piped"),
        deadline,
        Arc::clone(&cancelled),
    );
    let status = match child.wait_timeout(timeout) {
        Ok(Some(status)) => Some(status),
        Ok(None) => {
            let _ = child.kill();
            // Reap the owned child without waiting on descendant pipe handles.
            let _ = child.wait_timeout(StdDuration::from_secs(1));
            None
        }
        Err(err) => {
            cancelled.store(true, Ordering::Relaxed);
            let _ = child.kill();
            let _ = child.wait_timeout(StdDuration::from_secs(1));
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
    };

    let stdout = receive_pipe(stdout_rx, deadline);
    let stderr = receive_pipe(stderr_rx, deadline);
    cancelled.store(true, Ordering::Relaxed);
    let incomplete = matches!(&stdout, Ok((_, false))) || matches!(&stderr, Ok((_, false)));
    if status.is_none() || incomplete {
        let stderr = stderr
            .ok()
            .map(|(bytes, _)| {
                redact_proxy_values(&String::from_utf8_lossy(&bytes), &args)
                    .trim()
                    .to_string()
            })
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
    let output = match stdout.and_then(|(stdout, _)| {
        stderr.map(|(stderr, _)| std::process::Output {
            status: status.expect("completed child"),
            stdout,
            stderr,
        })
    }) {
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

    let stderr = redact_proxy_values(&String::from_utf8_lossy(&output.stderr), &args)
        .trim()
        .to_string();
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

fn redact_proxy_values(message: &str, args: &[String]) -> String {
    let mut proxies = args
        .iter()
        .enumerate()
        .filter_map(|(index, arg)| {
            if arg == "--proxy" {
                args.get(index + 1).map(String::as_str)
            } else {
                arg.strip_prefix("--proxy=")
            }
        })
        .filter(|proxy| !proxy.is_empty())
        .collect::<Vec<_>>();
    // Longer values first so a shorter proxy cannot expose a longer one's query.
    proxies.sort_unstable_by_key(|proxy| std::cmp::Reverse(proxy.len()));
    proxies
        .into_iter()
        .fold(message.to_string(), |message, proxy| {
            message.replace(proxy, "[redacted]")
        })
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
    let mut redact_next = false;
    args.iter()
        .map(|arg| {
            let arg = if redact_next {
                redact_next = false;
                "[redacted]"
            } else if arg == "--proxy" {
                redact_next = true;
                arg.as_str()
            } else if arg.starts_with("--proxy=") {
                "--proxy=[redacted]"
            } else {
                arg.as_str()
            };
            if arg
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || "-_./:@=".contains(c))
            {
                arg.to_string()
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

    #[test]
    fn dry_run_hides_proxy_url_without_changing_yt_dlp_arguments() {
        let proxy = "http://synthetic-user:synthetic-password@proxy.invalid:10001/path?token=synthetic-query#synthetic-fragment";
        // This process has a test-owned environment; never read a real proxy.
        env::set_var("TIKTOK_PROXY", proxy);
        let config = RunConfig {
            yt_dlp: YtDlp {
                program: "yt-dlp".to_string(),
                prefix_args: Vec::new(),
            },
            start: Local::now(),
            end: Local::now(),
            limit: 50,
            timeout_seconds: 180,
            sound_ids: BTreeSet::new(),
        };
        let args = build_yt_dlp_args(&config, "synthetic-account");
        env::remove_var("TIKTOK_PROXY");
        let original_args = args.clone();
        let proxy_position = args.iter().position(|arg| arg == "--proxy").unwrap();
        assert_eq!(args[proxy_position + 1], proxy);
        let diagnostic = format!("{} {}", config.yt_dlp.program, shell_join(&args));
        assert!(diagnostic.contains("--proxy '[redacted]'"), "{diagnostic}");
        for sensitive in [
            "synthetic-user",
            "synthetic-password",
            "proxy.invalid",
            "synthetic-query",
            "synthetic-fragment",
        ] {
            assert!(!diagnostic.contains(sensitive), "{diagnostic}");
        }
        assert!(diagnostic.ends_with("https://www.tiktok.com/@synthetic-account"));
        assert_eq!(args, original_args);
        assert_eq!(args[proxy_position + 1], proxy);
    }

    #[test]
    fn diagnostics_hide_all_separate_and_inline_proxy_values() {
        let args = [
            "--proxy",
            "socks5://first-user:first-pass@first.invalid/?key=first-query",
            "--dump-json",
            "--proxy=https://second-user:second-pass@second.invalid/?key=second-query",
            "--proxy",
            "not-a-url-but-still-private",
            "--socket-timeout",
            "30",
        ]
        .map(str::to_string)
        .to_vec();
        let original_args = args.clone();
        assert_eq!(
            shell_join(&args),
            "--proxy '[redacted]' --dump-json '--proxy=[redacted]' --proxy '[redacted]' --socket-timeout 30"
        );
        assert_eq!(args, original_args);
    }

    #[test]
    fn diagnostics_preserve_non_proxy_arguments_and_shell_quoting() {
        let args = [
            "--dump-json",
            "--user-agent",
            "two words",
            "--socket-timeout",
            "30",
            "https://www.tiktok.com/@synthetic-account",
        ]
        .map(str::to_string)
        .to_vec();
        assert_eq!(
            shell_join(&args),
            "--dump-json --user-agent 'two words' --socket-timeout 30 https://www.tiktok.com/@synthetic-account"
        );
    }
    fn fake_scrape(
        script: &str,
        proxy: Option<&str>,
        extra_args: &[&str],
        timeout: u64,
    ) -> AccountResult {
        let dir = env::temp_dir().join(format!(
            "rt-yt-scraper-error-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&dir).unwrap();
        let script_path = dir.join("fake-yt-dlp.py");
        let argv_path = dir.join("actual-argv.json");
        let header = "import json, pathlib, sys, time\npathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n";
        fs::write(&script_path, format!("{header}{script}")).unwrap();
        if let Some(proxy) = proxy {
            env::set_var("TIKTOK_PROXY", proxy);
        } else {
            env::remove_var("TIKTOK_PROXY");
        }
        let mut prefix_args = vec![
            "-B".to_string(),
            script_path.to_string_lossy().to_string(),
            argv_path.to_string_lossy().to_string(),
        ];
        prefix_args.extend(extra_args.iter().map(|arg| arg.to_string()));
        let config = RunConfig {
            yt_dlp: YtDlp {
                program: "/usr/bin/python3".to_string(),
                prefix_args,
            },
            start: Local::now() - Duration::hours(1),
            end: Local::now() + Duration::hours(1),
            limit: 50,
            timeout_seconds: timeout,
            sound_ids: BTreeSet::new(),
        };
        let expected_args = build_yt_dlp_args(&config, "synthetic-account");
        let result = scrape_account("synthetic-account", &config);
        env::remove_var("TIKTOK_PROXY");
        let actual_args: Vec<String> =
            serde_json::from_str(&fs::read_to_string(&argv_path).unwrap()).unwrap();
        fs::remove_dir_all(dir).unwrap();
        assert_eq!(
            actual_args,
            expected_args[2..],
            "actual child argv must remain exact"
        );
        result
    }

    const SYNTHETIC_ERROR_PROXY: &str = "http://synthetic-error-user:synthetic-error-pass@proxy.invalid:10001/path?token=synthetic-error-query#synthetic-error-fragment";

    fn assert_error_redacted(result: &AccountResult, expected: &str) {
        assert_eq!(result.error, expected);
        let json = serde_json::to_string(result).unwrap();
        for private in [
            "synthetic-error-user",
            "synthetic-error-pass",
            "proxy.invalid",
            "synthetic-error-query",
            "synthetic-error-fragment",
        ] {
            assert!(!json.contains(private), "{json}");
        }
    }

    #[test]
    fn failed_process_redacts_proxy_before_display_and_serialization() {
        let result = fake_scrape("proxy = sys.argv[sys.argv.index('--proxy') + 1]\nsys.stderr.write('failure via ' + proxy + '; retry later\\nsecondary detail\\n')\nsys.exit(7)\n", Some(SYNTHETIC_ERROR_PROXY), &[], 5);
        assert_eq!(result.status, "error");
        assert_eq!((result.fetched, result.kept), (0, 0));
        assert_error_redacted(&result, "failure via [redacted]; retry later");
    }

    #[test]
    fn timeout_redacts_proxy_and_retains_multiline_context() {
        let result = fake_scrape("proxy = sys.argv[sys.argv.index('--proxy') + 1]\nsys.stderr.write('timeout via ' + proxy + '\\nretry context\\n')\nsys.stderr.flush()\ntime.sleep(5)\n", Some(SYNTHETIC_ERROR_PROXY), &[], 1);
        assert_eq!(result.status, "timeout");
        assert_eq!((result.fetched, result.kept), (0, 0));
        assert_error_redacted(&result, "timeout via [redacted]\nretry context");
    }

    #[test]
    fn empty_success_redacts_proxy_warning_without_changing_status() {
        let result = fake_scrape("proxy = sys.argv[sys.argv.index('--proxy') + 1]\nsys.stderr.write('warning via ' + proxy + '\\nsecond detail\\n')\n", Some(SYNTHETIC_ERROR_PROXY), &[], 5);
        assert_eq!(result.status, "empty");
        assert_eq!((result.fetched, result.kept), (0, 0));
        assert_error_redacted(&result, "warning via [redacted]");
    }

    #[test]
    fn failed_process_redacts_complete_proxy_before_first_line_limit() {
        let proxy = format!("{SYNTHETIC_ERROR_PROXY}{}", "x".repeat(400));
        let result = fake_scrape("proxy = sys.argv[sys.argv.index('--proxy') + 1]\nsys.stderr.write('failure via ' + proxy + '; retry later\\n')\nsys.exit(7)\n", Some(&proxy), &[], 5);
        assert_eq!(result.status, "error");
        assert_error_redacted(&result, "failure via [redacted]; retry later");
    }

    #[test]
    fn repeated_inline_proxy_values_redact_longest_first_and_skip_empty() {
        let result = fake_scrape("sys.stderr.write('using http://synthetic-error-user:synthetic-error-pass@proxy.invalid/path?token=synthetic-error-query and http://synthetic-error-user:synthetic-error-pass@proxy.invalid/path; retry later\\n')\nsys.exit(7)\n", None, &["--proxy=http://synthetic-error-user:synthetic-error-pass@proxy.invalid/path", "--proxy", "http://synthetic-error-user:synthetic-error-pass@proxy.invalid/path?token=synthetic-error-query", "--proxy="], 5);
        assert_eq!(result.status, "error");
        assert_error_redacted(&result, "using [redacted] and [redacted]; retry later");
    }

    #[test]
    fn no_proxy_failure_preserves_useful_error_and_empty_proxy_does_not_replace() {
        let result = fake_scrape("sys.stderr.write('connection refused; retry later\\nsecondary detail\\n')\nsys.exit(7)\n", None, &["--proxy=", "--proxy", ""], 5);
        assert_eq!(result.status, "error");
        assert_eq!(result.error, "connection refused; retry later");
    }

    #[test]
    fn no_proxy_timeout_preserves_existing_timeout_fallback() {
        let result = fake_scrape("time.sleep(5)\n", None, &[], 1);
        assert_eq!(result.status, "timeout");
        assert_eq!(result.error, "timed out after 1s");
    }

    #[test]
    fn successful_rows_preserve_data_and_ignore_proxy_warning() {
        let result = fake_scrape("proxy = sys.argv[sys.argv.index('--proxy') + 1]\nsys.stderr.write('warning via ' + proxy + '\\n')\nprint(json.dumps({'webpage_url': 'https://www.tiktok.com/@synthetic-account/video/12345', 'title': 'Synthetic song', 'artist': 'Synthetic artist', 'timestamp': int(time.time()), 'view_count': 12}))\n", Some(SYNTHETIC_ERROR_PROXY), &[], 5);
        assert_eq!(result.status, "ok");
        assert_eq!((result.fetched, result.kept), (1, 1));
        assert!(result.error.is_empty());
        assert_eq!(
            result.videos[0].url,
            "https://www.tiktok.com/@synthetic-account/video/12345"
        );
        assert_eq!(result.videos[0].views, 12);
    }

    #[test]
    fn large_stdout_is_drained_before_waiting_for_child_exit() {
        let result = fake_scrape("print(json.dumps({'webpage_url': 'https://www.tiktok.com/@synthetic-account/video/12345', 'title': 'x' * 1048576, 'timestamp': int(time.time()), 'view_count': 12}))\n", None, &[], 1);
        assert_eq!(result.status, "ok", "a successful child must not time out on a full stdout pipe");
        assert_eq!((result.fetched, result.kept), (1, 1));
        assert!(result.error.is_empty());
        assert_eq!(result.videos[0].url, "https://www.tiktok.com/@synthetic-account/video/12345");
        assert_eq!(result.videos[0].views, 12);
    }

    #[test]
    fn large_stderr_is_drained_before_waiting_for_child_exit() {
        let result = fake_scrape("sys.stderr.write('warning via ' + sys.argv[sys.argv.index('--proxy') + 1] + '\\n' + 'x' * 1048576)\nsys.stderr.flush()\nprint(json.dumps({'webpage_url': 'https://www.tiktok.com/@synthetic-account/video/12345', 'timestamp': int(time.time()), 'view_count': 12}))\n", Some(SYNTHETIC_ERROR_PROXY), &[], 1);
        assert_eq!(result.status, "ok", "a successful child must not time out on a full stderr pipe");
        assert_eq!((result.fetched, result.kept), (1, 1));
        assert!(result.error.is_empty());
        assert_eq!(result.videos[0].url, "https://www.tiktok.com/@synthetic-account/video/12345");
        assert_eq!(result.videos[0].views, 12);
    }


    #[cfg(unix)]
    #[test]
    fn inherited_descendant_pipes_do_not_extend_the_account_deadline() {
        let started = Instant::now();
        let result = fake_scrape("import os\nif os.fork() == 0:\n    time.sleep(3)\n    os._exit(0)\nprint(json.dumps({'webpage_url': 'https://www.tiktok.com/@synthetic-account/video/12345', 'timestamp': int(time.time())}), flush=True)\nos._exit(0)\n", None, &[], 1);
        assert_eq!(result.status, "timeout", "incomplete inherited output must not be reported as a completed scrape");
        assert_eq!((result.fetched, result.kept), (0, 0));
        assert_eq!(result.error, "timed out after 1s");
        assert!(started.elapsed() < StdDuration::from_millis(2500), "must not wait for the test-owned descendant's three-second lifetime");
    }

    #[test]
    fn large_stderr_timeout_retains_redacted_context_and_the_deadline() {
        let started = Instant::now();
        let result = fake_scrape("sys.stderr.write('timeout via ' + sys.argv[sys.argv.index('--proxy') + 1] + '\\n' + 'x' * 1048576)\nsys.stderr.flush()\ntime.sleep(5)\n", Some(SYNTHETIC_ERROR_PROXY), &[], 1);
        assert_eq!(result.status, "timeout");
        assert_eq!((result.fetched, result.kept), (0, 0));
        assert!(result.error.starts_with("timeout via [redacted]\n"));
        assert!(result.error.len() > 1048576, "the active reader must drain output larger than the pipe");
        assert!(!serde_json::to_string(&result).unwrap().contains("synthetic-error-pass"));
        assert!(started.elapsed() < StdDuration::from_millis(2500));
    }

}
