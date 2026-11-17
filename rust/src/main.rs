// (c) 2026 Sunny Chase - Lion Studios. All rights reserved. Proprietary.
//! The Epstein Files - Lion Studios: the studio's server as one static binary. axum over SQLite; the front end (static/) is embedded.
//! Settings (environment): EFILES_HOST (127.0.0.1), EFILES_PORT (8670), EFILES_DB (efiles.db), EFILES_DATA (data/), EFILES_CACHE (cache/),
//! EFILES_ROOT (the folder that holds efiles.db, data/ and suppressed.json; default: the working directory).
//! Page images: a production's own image file when the page has one, else a pdftoppm render of its PDF page, cached under EFILES_CACHE.
mod api;
mod db;

use axum::{
    body::Body,
    extract::{Path, Query, State as AxState},
    http::{header, HeaderValue, Method, Request, StatusCode},
    response::Response,
    routing::get,
    Router,
};
use db::Db;
use rust_embed::RustEmbed;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Instant;

#[derive(RustEmbed)]
#[folder = "../static/"]
#[exclude = "*.gz"]
struct Static;

pub struct State {
    pub db: Db,
    pub root: PathBuf,
    pub cache: PathBuf,
    pub dash: Mutex<Option<(Instant, Value)>>,
    pub ins: Mutex<Option<(Instant, Value)>>,
    pub globe: Mutex<HashMap<String, (Instant, Value)>>,
    pub look: Mutex<HashMap<String, Value>>,
    pub render: Mutex<()>,
}
type S = Arc<State>;

fn jresp(v: Value, code: StatusCode) -> Response {
    let b = serde_json::to_vec(&v).unwrap_or_default();
    Response::builder().status(code).header(header::CONTENT_TYPE, "application/json; charset=utf-8").header(header::CACHE_CONTROL, "no-store").body(Body::from(b)).unwrap()
}
fn out(r: api::R) -> Response {
    match r { Ok(v) => jresp(v, StatusCode::OK), Err(m) => jresp(json!({"error": m.chars().take(200).collect::<String>()}), StatusCode::INTERNAL_SERVER_ERROR) }
}
/// run a blocking query function on the blocking pool
async fn run<F: FnOnce(&State) -> api::R + Send + 'static>(st: S, f: F) -> Response {
    match tokio::task::spawn_blocking(move || f(&st)).await { Ok(r) => out(r), Err(e) => jresp(json!({"error": e.to_string()}), StatusCode::INTERNAL_SERVER_ERROR) }
}

macro_rules! route_q { ($f:ident) => { |AxState(st): AxState<S>, Query(q): Query<api::Q>| async move { run(st, move |s| api::$f(s, &q)).await } }; }
macro_rules! route_0 { ($f:ident) => { |AxState(st): AxState<S>| async move { run(st, |s| api::$f(s)).await } }; }
macro_rules! route_id { ($f:ident) => { |AxState(st): AxState<S>, Path(id): Path<i64>| async move { run(st, move |s| api::$f(s, id)).await } }; }

async fn entity(AxState(st): AxState<S>, Path(id): Path<i64>, Query(q): Query<api::Q>) -> Response { run(st, move |s| api::api_entity(s, id, &q)).await }
async fn notebook(AxState(st): AxState<S>, Query(q): Query<api::Q>, req: Request<Body>) -> Response {
    let m = req.method().clone();
    let body = match axum::body::to_bytes(req.into_body(), 1 << 20).await { Ok(b) => String::from_utf8_lossy(&b).into_owned(), Err(_) => String::new() };
    match m { Method::GET => run(st, |s| api::notebook_get(s)).await, Method::POST => run(st, move |s| api::notebook_post(s, &body)).await, Method::DELETE => run(st, move |s| api::notebook_delete(s, &q)).await, _ => jresp(json!({"error": "method"}), StatusCode::METHOD_NOT_ALLOWED) }
}
async fn image(AxState(st): AxState<S>, Path(name): Path<String>, thumb: bool) -> Response {
    let Some(pid) = name.strip_suffix(".png").and_then(|s| s.parse::<i64>().ok()) else { return jresp(json!({"error": "not found"}), StatusCode::NOT_FOUND) };
    let (dpi, prefix) = if thumb { (28, "thumb-") } else { (110, "") };
    let r = tokio::task::spawn_blocking(move || api::page_png(&st, pid, dpi, prefix)).await;
    match r {
        Ok(Ok(Some((path, ct)))) => match tokio::fs::read(&path).await {
            Ok(b) => Response::builder().status(StatusCode::OK).header(header::CONTENT_TYPE, ct).header(header::CACHE_CONTROL, "public, max-age=86400").body(Body::from(b)).unwrap(),
            Err(_) => jresp(json!({"error": "no image for this page"}), StatusCode::NOT_FOUND),
        },
        Ok(Ok(None)) => jresp(json!({"error": "no image for this page"}), StatusCode::NOT_FOUND),
        Ok(Err(m)) => jresp(json!({"error": m}), StatusCode::INTERNAL_SERVER_ERROR),
        Err(e) => jresp(json!({"error": e.to_string()}), StatusCode::INTERNAL_SERVER_ERROR),
    }
}
async fn page_img(st: AxState<S>, p: Path<String>) -> Response { image(st, p, false).await }
async fn thumb_img(st: AxState<S>, p: Path<String>) -> Response { image(st, p, true).await }

async fn static_file(path: &str) -> Response {
    let p = if path.is_empty() || path == "/" { "index.html" } else { path.trim_start_matches('/') };
    match Static::get(p) {
        Some(f) => { let mime = mime_guess::from_path(p).first_or_octet_stream(); let cache = if p == "index.html" { "no-cache" } else { "public, max-age=3600" };
            Response::builder().status(StatusCode::OK).header(header::CONTENT_TYPE, HeaderValue::from_str(mime.as_ref()).unwrap()).header(header::CACHE_CONTROL, cache).body(Body::from(f.data.into_owned())).unwrap() }
        None => jresp(json!({"error": "not found"}), StatusCode::NOT_FOUND),
    }
}
async fn index() -> Response { static_file("index.html").await }
async fn fallback(req: Request<Body>) -> Response { let p = req.uri().path().to_string(); static_file(&p).await }

#[tokio::main]
async fn main() {
    let env = |k: &str, d: &str| std::env::var(k).unwrap_or_else(|_| d.to_string());
    let root = PathBuf::from(env("EFILES_ROOT", "."));
    let dbp = env("EFILES_DB", root.join("efiles.db").to_string_lossy().as_ref());
    let cache = PathBuf::from(env("EFILES_CACHE", root.join("cache").to_string_lossy().as_ref())); let _ = std::fs::create_dir_all(&cache);
    let host = env("EFILES_HOST", "127.0.0.1"); let port = env("EFILES_PORT", "8670");
    let st: S = Arc::new(State { db: Db::open(&dbp), root, cache, dash: Mutex::new(None), ins: Mutex::new(None), globe: Mutex::new(HashMap::new()), look: Mutex::new(HashMap::new()), render: Mutex::new(()) });
    let app = Router::new()
        .route("/", get(index))
        .route("/api/stats", get(route_0!(api_stats)))
        .route("/api/search", get(route_q!(api_search)))
        .route("/api/entities", get(route_q!(api_entities)))
        .route("/api/entity/:id", get(entity))
        .route("/api/graph", get(route_q!(api_graph)))
        .route("/api/path", get(route_q!(api_path)))
        .route("/api/doc/:id", get(route_id!(api_doc)))
        .route("/api/page/:id", get(route_id!(api_page)))
        .route("/api/redactions", get(route_0!(api_redactions)))
        .route("/api/timeline", get(route_q!(api_timeline)))
        .route("/api/notebook", get(notebook).post(notebook).delete(notebook))
        .route("/api/lookup", get(route_q!(api_lookup)))
        .route("/api/dashboard", get(route_q!(api_dashboard)))
        .route("/api/insights", get(route_q!(api_insights)))
        .route("/api/globe", get(route_q!(api_globe)))
        .route("/api/globe/point", get(route_q!(api_globe_point)))
        .route("/api/money", get(route_q!(api_money)))
        .route("/api/money/summary", get(route_0!(api_money_summary)))
        .route("/api/flights", get(route_0!(api_flights)))
        .route("/api/timeline2", get(route_q!(api_timeline2)))
        .route("/api/emails", get(route_q!(api_emails)))
        .route("/api/photos", get(route_q!(api_photos)))
        .route("/api/figures", get(route_q!(api_figures)))
        .route("/api/themes", get(route_0!(api_themes)))
        .route("/api/documents", get(route_0!(api_documents)))
        .route("/page/:name", get(page_img))
        .route("/thumb/:name", get(thumb_img))
        .fallback(fallback)
        .with_state(st);
    let addr = format!("{host}:{port}");
    println!("{} on http://{addr} (db {dbp})", api::PRODUCT);
    let listener = tokio::net::TcpListener::bind(&addr).await.expect("bind");
    axum::serve(listener, app).await.expect("serve");
}
