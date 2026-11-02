//! Rust arm of the Tier-1 client bench (CASE-MATRIX.md, amendment of 2 November 2026).
//!
//! rmcp leaves the authorization-code flow to the application, which drives `OAuthState`:
//! `start_authorization` with the challenge the resource answered with, the user agent, then
//! `handle_callback_url` with the redirect. The driver does exactly that and plays the user
//! agent: it makes the unauthenticated request whose 401 carries the challenge, follows the
//! authorization URL one hop, and hands the whole callback URL back, so the SDK reads code,
//! state and iss itself. It decides no outcome; score.py reads the server's request log.

use std::time::Duration;

use rmcp::transport::auth::{AuthorizationRequest, OAuthState};
use serde_json::{json, Value};

const BENCH: &str = "http://127.0.0.1:8765";
const REDIRECT: &str = "http://127.0.0.1:8766/callback";

fn requested() -> String {
    format!("{BENCH}/tenant-a/mcp")
}

/// The rmcp version this binary was built against, read from the lockfile beside it.
fn rmcp_version() -> String {
    let lock = std::fs::read_to_string("/w/Cargo.lock").unwrap_or_default();
    let mut lines = lock.lines();
    while let Some(line) = lines.next() {
        if line.trim() == "name = \"rmcp\"" {
            if let Some(v) = lines.next() {
                return v.trim().trim_start_matches("version = ").trim_matches('"').to_string();
            }
        }
    }
    "unknown".into()
}

/// Source files of the crate naming `needle` (the C1 count).
fn source_occurrences(needle: &str, version: &str) -> usize {
    fn walk(dir: &std::path::Path, needle: &str, n: &mut usize) {
        if let Ok(entries) = std::fs::read_dir(dir) {
            for e in entries.flatten() {
                let p = e.path();
                if p.is_dir() {
                    walk(&p, needle, n);
                } else if p.extension().is_some_and(|x| x == "rs") {
                    if std::fs::read_to_string(&p).is_ok_and(|s| s.contains(needle)) {
                        *n += 1;
                    }
                }
            }
        }
    }
    let registry = std::path::Path::new("/w/.cargo/registry/src");
    let mut n = 0;
    if let Ok(indexes) = std::fs::read_dir(registry) {
        for index in indexes.flatten() {
            walk(&index.path().join(format!("rmcp-{version}")).join("src"), needle, &mut n);
        }
    }
    n
}

struct Outcome {
    authorization_url: Option<String>,
    callback: Option<String>,
    error: Option<String>,
}

async fn run_case(user_agent: &reqwest::Client) -> Outcome {
    let mut o = Outcome { authorization_url: None, callback: None, error: None };
    let result: Result<(), String> = async {
        // The request an application makes first; its 401 carries the challenge.
        let first = user_agent
            .post(requested())
            .header("content-type", "application/json")
            .header("accept", "application/json, text/event-stream")
            .body(r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}"#)
            .send()
            .await
            .map_err(|e| format!("initial request: {e}"))?;
        let challenge = first
            .headers()
            .get("www-authenticate")
            .and_then(|h| h.to_str().ok())
            .map(str::to_owned);

        let mut state = OAuthState::new(requested(), None).await.map_err(|e| format!("{e:?}"))?;
        let mut request = AuthorizationRequest::new(REDIRECT)
            .with_client_name("tier1-bench")
            .with_initial_scope_selection();
        if let Some(c) = challenge {
            request = request.with_challenge(c);
        }
        state.start_authorization(request).await.map_err(|e| format!("{e:?}"))?;
        let url = state.get_authorization_url().await.map_err(|e| format!("{e:?}"))?;
        o.authorization_url = Some(url.clone());

        // The user agent: request the authorization URL and keep the redirect it answers with.
        let res = user_agent.get(&url).send().await.map_err(|e| format!("user agent: {e}"))?;
        let location = res
            .headers()
            .get("location")
            .and_then(|h| h.to_str().ok())
            .map(str::to_owned)
            .ok_or("the authorization endpoint answered with no redirect")?;
        o.callback = Some(location.clone());
        state.handle_callback_url(&location).await.map_err(|e| format!("{e:?}"))?;
        Ok(())
    }
    .await;
    if let Err(e) = result {
        o.error = Some(e.chars().take(300).collect());
    }
    o
}

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    let version = rmcp_version();
    let c1 = source_occurrences("protected_resources", &version);
    let bench = reqwest::Client::new();
    let user_agent = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(10))
        .build()
        .expect("client");
    let cases: Vec<String> = serde_json::from_str(
        &bench.get(format!("{BENCH}/__cases")).send().await.unwrap().text().await.unwrap(),
    )
    .unwrap();
    for id in cases {
        bench.post(format!("{BENCH}/__case?id={id}")).send().await.unwrap();
        let o = match tokio::time::timeout(Duration::from_secs(20), run_case(&user_agent)).await {
            Ok(o) => o,
            Err(_) => Outcome { authorization_url: None, callback: None, error: Some("bench timeout".into()) },
        };
        let log: Value = serde_json::from_str(
            &bench.get(format!("{BENCH}/__log")).send().await.unwrap().text().await.unwrap(),
        )
        .unwrap();
        let mut rec = json!({
            "implementation": "rust-sdk", "package": "rmcp", "version": version, "level": "flow",
            "case_id": id, "requested_identifier": requested(),
            "callback_channel": "OAuthState::handle_callback_url (the whole callback URL)",
            "authorization_url": o.authorization_url, "callback": o.callback,
            "connect_error": o.error, "finish_error": null,
            "log": log["log"],
            "run_at": format!("unix:{}", std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)),
        });
        if id == "C1" {
            rec["c1_source_occurrences"] = json!(c1);
        }
        println!("{rec}");
    }
}
