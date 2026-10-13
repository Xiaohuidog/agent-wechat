use axum::Json;
use md5::{Digest, Md5};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::os::unix::fs::OpenOptionsExt;
use std::io::Write;
use crate::db::get_db;
use crate::sessions::manager::get_session;
use crate::tools::exec::{exec_command, ExecOptions};

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReplyRequest {
    request_key: String,
    chat_id: String,
    account_id: String,
    source_message_id: String,
    source_text: String,
    text: String,
}

pub async fn capabilities() -> Json<Value> {
    Json(json!({"nativeTextReply": std::path::Path::new("/opt/tools/native-reply").is_file()}))
}

fn failure(code: &str) -> Value {
    json!({"success": false, "status": "failed", "errorCode": code})
}

fn validate(input: &ReplyRequest) -> Result<(), &'static str> {
    if input.request_key.is_empty() || input.request_key.len() > 200 {
        return Err("REPLY_REQUEST_KEY_INVALID");
    }
    if !input.chat_id.ends_with("@chatroom") || input.chat_id.len() > 200
        || input.account_id.is_empty() || input.account_id.len() > 200
        || input.source_message_id.is_empty() || input.source_message_id.len() > 30
        || !input.source_message_id.chars().all(|c| c.is_ascii_digit())
        || input.source_text.trim().is_empty()
    {
        return Err("REPLY_SOURCE_INVALID");
    }
    if input.text.trim().is_empty() || input.text.chars().count() > 2000 {
        return Err("REPLY_TEXT_INVALID");
    }
    Ok(())
}

fn cached(input: &ReplyRequest, digest: &str) -> Option<Value> {
    let db = get_db();
    let found = db.query_row(
        "SELECT request_digest,result_json FROM native_reply_operations WHERE request_key=?1",
        [&input.request_key], |row| Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?)),
    ).ok()?;
    if found.0 != digest { return Some(failure("REPLY_IDEMPOTENCY_CONFLICT")); }
    Some(found.1.and_then(|v| serde_json::from_str(&v).ok())
        .unwrap_or_else(|| json!({"success": false, "status": "unknown", "errorCode": "REPLY_RESULT_UNKNOWN"})))
}

pub async fn send(Json(input): Json<ReplyRequest>) -> Json<Value> {
    if let Err(code) = validate(&input) { return Json(failure(code)); }
    let digest = format!("{:x}", Md5::digest(serde_json::to_vec(&input).unwrap_or_default()));
    if let Some(result) = cached(&input, &digest) { return Json(result); }
    let session = match get_session("default") {
        Some(value) if value.logged_in_user.as_deref() == Some(input.account_id.as_str()) => value,
        _ => return Json(failure("REPLY_ACCOUNT_CHANGED")),
    };
    let _guard = match tokio::time::timeout(std::time::Duration::from_secs(10),
        super::ui_lock::UI_OPERATION_LOCK.lock()).await {
        Ok(guard) => guard,
        Err(_) => return Json(failure("REPLY_UI_BUSY")),
    };
    if let Some(result) = cached(&input, &digest) { return Json(result); }
    // Persist dispatch intent before starting the helper. A crash cannot cause a duplicate send.
    {
        let db = get_db();
        if db.execute("INSERT INTO native_reply_operations(request_key,request_digest,status) VALUES (?1,?2,'sending')",
            rusqlite::params![input.request_key,digest]).is_err() {
            return Json(failure("REPLY_OPERATION_STORE_FAILED"));
        }
    }
    let path = std::env::temp_dir().join(format!("native-reply-{}.json", uuid::Uuid::new_v4()));
    let result = match std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&path) {
        Ok(mut file) => {
            if file.write_all(&serde_json::to_vec(&input).unwrap_or_default()).is_err() {
                failure("REPLY_PREPARATION_FAILED")
            } else {
                let output = exec_command("native-reply", &[path.to_str().unwrap_or_default()],
                    &ExecOptions { session: Some(session), timeout_ms: 150_000 }).await;
                serde_json::from_str::<Value>(&output.stdout).unwrap_or_else(|_|
                    json!({"success":false,"status":"unknown","errorCode":"REPLY_RESULT_UNKNOWN"}))
            }
        }
        Err(_) => failure("REPLY_PREPARATION_FAILED"),
    };
    let _ = std::fs::remove_file(path);
    let status = result.get("status").and_then(Value::as_str).unwrap_or("unknown");
    let db = get_db();
    if db.execute("UPDATE native_reply_operations SET status=?2,result_json=?3,updated_at=datetime('now') WHERE request_key=?1",
        rusqlite::params![input.request_key,status,result.to_string()]).is_err() {
        return Json(json!({"success":false,"status":"unknown","errorCode":"REPLY_RESULT_STORE_FAILED"}));
    }
    Json(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn request() -> ReplyRequest {
        ReplyRequest { request_key: "once".into(), chat_id:"group@chatroom".into(),
            account_id:"account".into(), source_message_id:"6088777209553577378".into(),
            source_text:"source".into(), text:"reply".into() }
    }
    #[test] fn ids_are_strings_and_text_is_bounded() {
        let mut r=request(); assert!(validate(&r).is_ok());
        r.source_message_id="6.088e18".into(); assert!(validate(&r).is_err());
        r=request();r.text="x".repeat(2001);assert!(validate(&r).is_err());
        r=request();r.text=" \n".into();assert!(validate(&r).is_err());
        r=request();r.chat_id="friend".into();assert!(validate(&r).is_err());
    }
}
