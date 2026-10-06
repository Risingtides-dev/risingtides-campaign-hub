//! HTTP/1 transport for the existing local GUI. Business handlers receive only
//! complete bounded bodies; the connection owns cancellation and admission.
use anyhow::{Context, Result};
use http_body_util::{BodyExt, Full};
use hyper::body::{Bytes, Incoming};
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Request as HttpRequest, Response as HttpResponse};
use hyper_util::rt::{TokioIo, TokioTimer};
use std::convert::Infallible;
use std::io::{self, Cursor, Read};
#[cfg(test)]
use std::net::ToSocketAddrs;
use std::net::{SocketAddr, TcpListener};
#[cfg(test)]
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;
use tiny_http::{Header, Method, Response};
use tokio::sync::{oneshot, watch, OwnedSemaphorePermit, Semaphore};
use tokio::task::JoinSet;
use tokio::time::{timeout_at, Instant};

type Reply = HttpResponse<Full<Bytes>>;
type BodyPolicy = fn(&Request, SocketAddr) -> bool;

#[derive(Clone, Copy)]
pub(super) struct Limits {
    pub(super) connections: usize,
    pub(super) body_bytes: usize,
    pub(super) ingress: Duration,
    pub(super) response: Duration,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            connections: 16,
            // Chat context includes a serialized run/report and its retained logs.
            body_bytes: 32 * 1024 * 1024,
            ingress: Duration::from_secs(30),
            response: Duration::from_secs(5),
        }
    }
}

pub(super) struct Request {
    method: Method,
    url: String,
    headers: Vec<Header>,
    body: Cursor<Vec<u8>>,
    reply: Option<oneshot::Sender<Reply>>,
    completed: Option<mpsc::Receiver<Result<(), String>>>,
    // Keep admission until BOTH the connection and its synchronous handler finish.
    _admission: Arc<OwnedSemaphorePermit>,
}

impl Request {
    pub(super) fn handler_admission(&self) -> Arc<OwnedSemaphorePermit> {
        self._admission.clone()
    }

    pub(super) fn method(&self) -> &Method {
        &self.method
    }
    pub(super) fn url(&self) -> &str {
        &self.url
    }
    pub(super) fn headers(&self) -> &[Header] {
        &self.headers
    }
    pub(super) fn as_reader(&mut self) -> &mut dyn Read {
        &mut self.body
    }

    pub(super) fn respond<R: Read>(mut self, response: Response<R>) -> io::Result<()> {
        let mut builder = HttpResponse::builder().status(response.status_code().0);
        for header in response.headers() {
            builder = builder.header(header.field.as_str().as_str(), header.value.as_str());
        }
        let mut body = Vec::new();
        response.into_reader().read_to_end(&mut body)?;
        let response = builder
            .body(Full::new(Bytes::from(body)))
            .map_err(io::Error::other)?;
        self.reply
            .take()
            .expect("one response")
            .send(response)
            .map_err(|_| io::Error::new(io::ErrorKind::BrokenPipe, "GUI connection closed"))?;
        // Match the existing synchronous API: return only after the owned
        // transport has written/closed, or its bounded write/cancellation fails.
        self.completed
            .take()
            .expect("dispatched request completion")
            .recv()
            .unwrap_or_else(|_| Err("GUI connection closed".into()))
            .map_err(io::Error::other)
    }
}

impl Drop for Request {
    fn drop(&mut self) {
        if let Some(reply) = self.reply.take() {
            // Preserve the previous unhandled/error response without reading ingress.
            let sent = reply.send(
                HttpResponse::builder()
                    .status(500)
                    .body(Full::new(Bytes::new()))
                    .expect("static response"),
            );
            if sent.is_ok() {
                // Only dispatched synchronous handlers have a completion.
                // Early refusals occur on the async owner and must never block it.
                if let Some(completed) = self.completed.take() {
                    let _ = completed.recv();
                }
            }
        }
    }
}

pub(super) struct Server {
    address: SocketAddr,
    requests: mpsc::Receiver<Request>,
    stop: Option<watch::Sender<bool>>,
    worker: Option<thread::JoinHandle<()>>,
    #[cfg(test)]
    peak_tasks: Arc<AtomicUsize>,
}

impl Server {
    #[cfg(test)]
    pub(super) fn bind(address: SocketAddr, policy: BodyPolicy) -> Result<Self> {
        Self::bind_with_limits(address, policy, Limits::default())
    }

    pub(super) fn bind_with_limits(
        address: SocketAddr,
        policy: BodyPolicy,
        limits: Limits,
    ) -> Result<Self> {
        let listener = TcpListener::bind(address).context("failed to start GUI server")?;
        let address = listener.local_addr()?;
        listener.set_nonblocking(true)?;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let (requests, receiver) = mpsc::sync_channel(limits.connections);
        let (stop, stopped) = watch::channel(false);
        #[cfg(test)]
        let peak_tasks = Arc::new(AtomicUsize::new(0));
        #[cfg(test)]
        let recorded_peak = peak_tasks.clone();
        let worker = thread::spawn(move || {
            runtime.block_on(async move {
                let Ok(listener) = tokio::net::TcpListener::from_std(listener) else {
                    return;
                };
                let permits = Arc::new(Semaphore::new(limits.connections));
                let mut stopped = stopped;
                let mut connections = JoinSet::new();
                loop {
                    // Reap before another accept, not only when select chooses join.
                    while connections.try_join_next().is_some() {}
                    tokio::select! {
                        _ = stopped.changed() => break,
                        _ = connections.join_next(), if !connections.is_empty() => {},
                        accepted = listener.accept() => {
                            let Ok((socket, _)) = accepted else { break };
                            let deadline = Instant::now() + limits.ingress;
                            while connections.try_join_next().is_some() {}
                            if connections.len() >= limits.connections {
                                drop(socket);
                                continue;
                            }
                            // No task, header parser, body reader or handler before admission.
                            let Ok(permit) = permits.clone().try_acquire_owned() else {
                                drop(socket);
                                continue;
                            };
                            let admission = Arc::new(permit);
                            let requests = requests.clone();
                            connections.spawn(connection(socket, address, policy, limits,
                                deadline, requests, admission));
                            #[cfg(test)]
                            recorded_peak.fetch_max(connections.len(), Ordering::SeqCst);
                        }
                    }
                }
                // Dropping a Hyper connection drops its owned socket, never drains a body.
                connections.abort_all();
                while connections.join_next().await.is_some() {}
            });
        });
        Ok(Self {
            address,
            requests: receiver,
            stop: Some(stop),
            worker: Some(worker),
            #[cfg(test)]
            peak_tasks,
        })
    }

    #[cfg(test)]
    pub(super) fn http(address: impl ToSocketAddrs) -> Result<Self> {
        let address = address
            .to_socket_addrs()?
            .next()
            .context("missing HTTP address")?;
        Self::bind(address, |_, _| true)
    }

    pub(super) fn server_addr(&self) -> SocketAddr {
        self.address
    }

    #[cfg(test)]
    pub(super) fn recv_timeout(&self, timeout: Duration) -> io::Result<Option<Request>> {
        match self.requests.recv_timeout(timeout) {
            Ok(request) => Ok(Some(request)),
            Err(mpsc::RecvTimeoutError::Timeout) => Ok(None),
            Err(mpsc::RecvTimeoutError::Disconnected) => Ok(None),
        }
    }

    #[cfg(test)]
    pub(super) fn peak_owned_tasks(&self) -> Arc<AtomicUsize> {
        self.peak_tasks.clone()
    }

    pub(super) fn incoming_requests(&self) -> impl Iterator<Item = Request> + '_ {
        std::iter::from_fn(|| self.requests.recv().ok())
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(true);
        }
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

#[derive(Clone, Copy)]
enum Phase {
    Headers,
    Body,
    Action,
    Response,
}

fn error(status: u16, message: &'static str) -> Reply {
    HttpResponse::builder()
        .status(status)
        .header("Content-Type", "application/json")
        .body(Full::new(Bytes::from(format!(
            r#"{{"error":"{message}"}}"#
        ))))
        .expect("static error response")
}

async fn receive(
    mut incoming: HttpRequest<Incoming>,
    address: SocketAddr,
    policy: BodyPolicy,
    limits: Limits,
    deadline: Instant,
    requests: mpsc::SyncSender<Request>,
    admission: Arc<OwnedSemaphorePermit>,
    phase: watch::Sender<Phase>,
    completion: Arc<ResponseCompletion>,
) -> Reply {
    let (reply, replied) = oneshot::channel();
    let mut headers = Vec::with_capacity(incoming.headers().len());
    for (name, value) in incoming.headers() {
        let Ok(header) = Header::from_bytes(name.as_str().as_bytes(), value.as_bytes()) else {
            phase.send_replace(Phase::Response);
            return error(400, "invalid request header");
        };
        headers.push(header);
    }
    let mut request = Request {
        method: incoming
            .method()
            .as_str()
            .parse()
            .expect("valid HTTP method"),
        url: incoming.uri().to_string(),
        headers,
        body: Cursor::new(Vec::new()),
        reply: Some(reply),
        completed: None,
        _admission: admission,
    };
    // The exact existing GUI guard/method/route policy runs before body polling.
    if policy(&request, address) {
        phase.send_replace(Phase::Body);
        if incoming
            .headers()
            .get(hyper::header::CONTENT_LENGTH)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<u64>().ok())
            .is_some_and(|size| size > limits.body_bytes as u64)
        {
            phase.send_replace(Phase::Response);
            return error(413, "request body too large");
        }
        let mut body = Vec::new();
        loop {
            if Instant::now() >= deadline {
                phase.send_replace(Phase::Response);
                return error(408, "request body timed out");
            }
            let frame = match timeout_at(deadline, incoming.body_mut().frame()).await {
                Ok(Some(Ok(frame))) => frame,
                Ok(None) => break,
                Ok(Some(Err(_))) => {
                    phase.send_replace(Phase::Response);
                    return error(400, "incomplete request body");
                }
                Err(_) => {
                    phase.send_replace(Phase::Response);
                    return error(408, "request body timed out");
                }
            };
            if let Ok(data) = frame.into_data() {
                if data.len() > limits.body_bytes.saturating_sub(body.len()) {
                    phase.send_replace(Phase::Response);
                    return error(413, "request body too large");
                }
                body.extend_from_slice(&data);
            }
        }
        if Instant::now() >= deadline {
            phase.send_replace(Phase::Response);
            return error(408, "request body timed out");
        }
        request.body = Cursor::new(body);
    }
    // Release the incoming body without any drain, including guard/method
    // denials. Hyper owns the connection and closes it after the response.
    drop(incoming);
    // Handlers retain their established longer Pi/proxy deadlines. Ingress
    // rejection never queues a request; guard/method denials queue no body.
    if Instant::now() >= deadline {
        phase.send_replace(Phase::Response);
        return error(408, "request ingress timed out");
    }
    let (complete, completed) = mpsc::sync_channel(1);
    *completion.sender.lock().expect("completion lock") = Some(complete);
    request.completed = Some(completed);
    phase.send_replace(Phase::Action);
    if let Err(error) = requests.try_send(request) {
        let mut refused = match error {
            mpsc::TrySendError::Full(request) | mpsc::TrySendError::Disconnected(request) => {
                request
            }
        };
        // Never wait synchronously on the asynchronous rejection path.
        refused.completed.take();
        drop(refused);
        phase.send_replace(Phase::Response);
        return self::error(503, "GUI busy");
    }
    let response = replied
        .await
        .unwrap_or_else(|_| error(500, "GUI request failed"));
    phase.send_replace(Phase::Response);
    response
}

async fn connection(
    socket: tokio::net::TcpStream,
    address: SocketAddr,
    policy: BodyPolicy,
    limits: Limits,
    deadline: Instant,
    requests: mpsc::SyncSender<Request>,
    admission: Arc<OwnedSemaphorePermit>,
) {
    let (phase, mut changed) = watch::channel(Phase::Headers);
    let completion = Arc::new(ResponseCompletion {
        sender: Mutex::new(None),
    });
    let finished = CompleteOnDrop(completion.clone());
    let service = service_fn(move |request| {
        let future = receive(
            request,
            address,
            policy,
            limits,
            deadline,
            requests.clone(),
            admission.clone(),
            phase.clone(),
            completion.clone(),
        );
        async move { Ok::<_, Infallible>(future.await) }
    });
    let mut builder = http1::Builder::new();
    builder
        .keep_alive(false)
        .max_headers(64)
        .max_buf_size(16 * 1024)
        .timer(TokioTimer::new())
        .header_read_timeout(limits.ingress);
    let mut connection = Box::pin(builder.serve_connection(TokioIo::new(socket), service));
    let mut result = Err("GUI connection timed out".to_string());
    let mut expires = Some(deadline);
    let mut response_deadline = None;
    loop {
        tokio::select! {
            completed = &mut connection => {
                result = completed.map_err(|_| "failed writing GUI response".to_string());
                break;
            },
            result = changed.changed() => {
                if result.is_err() { break; }
                expires = phase_deadline(*changed.borrow_and_update(), deadline,
                    limits.response, &mut response_deadline);
            }
            _ = async {
                if let Some(expires) = expires {
                    tokio::time::sleep_until(expires).await;
                } else {
                    std::future::pending::<()>().await;
                }
            } => {
                // A stale timer and the committed Action notification may be
                // ready together. Inspect the latest phase before cancellation.
                expires = phase_deadline(*changed.borrow_and_update(), deadline,
                    limits.response, &mut response_deadline);
                if expires.is_some_and(|expires| Instant::now() >= expires) {
                    break;
                }
            },
        }
    }
    // Finish socket ownership before acknowledging the synchronous handler.
    drop(connection);
    finished.0.finish(result);
}

// Response budget starts once and is never extended by another timer wake.
fn phase_deadline(
    phase: Phase,
    ingress: Instant,
    response: Duration,
    response_deadline: &mut Option<Instant>,
) -> Option<Instant> {
    match phase {
        Phase::Headers => Some(ingress),
        Phase::Body => Some(ingress + response),
        Phase::Action => None,
        Phase::Response => {
            Some(*response_deadline.get_or_insert_with(|| Instant::now() + response))
        }
    }
}

// Cancellation also acknowledges handlers, so they cannot remain blocked
// waiting for a connection task that has been aborted during server shutdown.
struct ResponseCompletion {
    sender: Mutex<Option<mpsc::SyncSender<Result<(), String>>>>,
}

impl ResponseCompletion {
    fn finish(&self, result: Result<(), String>) {
        if let Some(sender) = self.sender.lock().expect("completion lock").take() {
            let _ = sender.send(result);
        }
    }
}

struct CompleteOnDrop(Arc<ResponseCompletion>);

impl Drop for CompleteOnDrop {
    fn drop(&mut self) {
        self.0.finish(Err("GUI connection closed".into()));
    }
}
