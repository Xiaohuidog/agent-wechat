use axum::{
    extract::Path,
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use base64::Engine;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::db::get_db;
use crate::sessions::manager::get_session;
use crate::tools::exec::{exec_command, ExecOptions};
use crate::tools::wechat_chats;
use crate::tools::wechat_keys::get_stored_keys;
use crate::tools::wechat_media::get_video_download_cache_target;

const ACTIVE_TIMEOUT: &str = "-10 minutes";
const MAX_ATTEMPTS: i64 = 2;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateRequest {
    idempotency_key: String,
    chat_id: String,
    local_id: i64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Operation {
    id: String,
    idempotency_key: String,
    chat_id: String,
    local_id: i64,
    state: String,
    attempts: i64,
    error_code: Option<String>,
    size_bytes: Option<i64>,
    created_at: String,
    updated_at: String,
    completed_at: Option<String>,
}

fn validate(input: &CreateRequest) -> Result<(), &'static str> {
    if input.idempotency_key.is_empty() || input.idempotency_key.len() > 200 {
        return Err("VIDEO_DOWNLOAD_IDEMPOTENCY_KEY_INVALID");
    }
    if !input.chat_id.ends_with("@chatroom")
        || input.chat_id.len() > 200
        || input.chat_id.chars().any(char::is_control)
        || input.local_id < 0
    {
        return Err("VIDEO_DOWNLOAD_MESSAGE_ID_INVALID");
    }
    Ok(())
}

fn load_operation(id: &str) -> Option<Operation> {
    let db = get_db();
    db.query_row(
        "SELECT id, idempotency_key, chat_id, local_id, state, attempts,
                error_code, size_bytes, created_at, updated_at, completed_at
         FROM video_download_operations WHERE id=?1",
        [id],
        |row| {
            Ok(Operation {
                id: row.get(0)?,
                idempotency_key: row.get(1)?,
                chat_id: row.get(2)?,
                local_id: row.get(3)?,
                state: row.get(4)?,
                attempts: row.get(5)?,
                error_code: row.get(6)?,
                size_bytes: row.get(7)?,
                created_at: row.get(8)?,
                updated_at: row.get(9)?,
                completed_at: row.get(10)?,
            })
        },
    )
    .ok()
}

fn update_state(id: &str, state: &str, error_code: Option<&str>) {
    let db = get_db();
    if let Err(error) = db.execute(
        "UPDATE video_download_operations
         SET state=?2, error_code=?3, updated_at=datetime('now') WHERE id=?1",
        rusqlite::params![id, state, error_code],
    ) {
        tracing::error!("[video-download:{id}] state update failed: {error}");
    }
}

fn finish_ready(id: &str, size_bytes: i64) {
    let db = get_db();
    if let Err(error) = db.execute(
        "UPDATE video_download_operations
         SET state='ready', error_code=NULL, size_bytes=?2,
             completed_at=datetime('now'), updated_at=datetime('now') WHERE id=?1",
        rusqlite::params![id, size_bytes],
    ) {
        tracing::error!("[video-download:{id}] completion update failed: {error}");
    }
}

fn schedule(id: String) {
    tokio::spawn(async move { run(id).await });
}

async fn run(id: String) {
    let _guard = super::ui_lock::UI_OPERATION_LOCK.lock().await;
    let claimed = {
        let db = get_db();
        db.execute(
            "UPDATE video_download_operations
             SET state='dispatching', attempts=attempts+1, error_code=NULL,
                 updated_at=datetime('now')
             WHERE id=?1 AND attempts < ?3 AND (
                 state IN ('queued','failed')
                 OR (state IN ('dispatching','locating','triggering','validating')
                     AND updated_at <= datetime('now', ?2))
             )",
            rusqlite::params![id, ACTIVE_TIMEOUT, MAX_ATTEMPTS],
        )
        .unwrap_or(0)
    };
    if claimed != 1 {
        return;
    }
    let Some(operation) = load_operation(&id) else {
        return;
    };
    update_state(&id, "locating", None);

    let Some(session) = get_session("default") else {
        update_state(&id, "failed", Some("SOURCE_SESSION_UNAVAILABLE"));
        return;
    };
    let Some(account_dir) = session.logged_in_user.clone() else {
        update_state(&id, "failed", Some("SOURCE_LOGIN_REQUIRED"));
        return;
    };
    let keys = {
        let db = get_db();
        get_stored_keys(&db, &session.id, &account_dir)
    };
    let Some(chat) = wechat_chats::get_chat_by_username(&account_dir, &keys, &operation.chat_id)
    else {
        update_state(&id, "failed", Some("VIDEO_CHAT_NOT_FOUND"));
        return;
    };
    let Some(target) = get_video_download_cache_target(
        &account_dir,
        &keys,
        &operation.chat_id,
        operation.local_id,
    ) else {
        update_state(&id, "failed", Some("VIDEO_CACHE_IDENTITY_UNAVAILABLE"));
        return;
    };
    let temporary_thumb = format!("/tmp/agent-video-{id}.jpg");
    let thumb = target.video_dir.join(format!("{}_thumb.jpg", target.stem));
    let cover = target.video_dir.join(format!("{}.jpg", target.stem));
    if let Some(source) = [thumb, cover].into_iter().find(|path| path.is_file()) {
        if std::fs::copy(&source, &temporary_thumb).is_err() {
            update_state(&id, "failed", Some("VIDEO_THUMBNAIL_WRITE_FAILED"));
            return;
        }
    }
    let local_id_string = operation.local_id.to_string();
    let video_dir_string = target.video_dir.to_string_lossy().to_string();
    let args = [
        "--chat-id",
        operation.chat_id.as_str(),
        "--chat-name",
        chat.name.as_str(),
        "--local-id",
        local_id_string.as_str(),
        "--video-dir",
        video_dir_string.as_str(),
        "--stem",
        target.stem.as_str(),
        "--thumbnail",
        temporary_thumb.as_str(),
    ];
    update_state(&id, "triggering", None);
    let options = ExecOptions {
        session: Some(session),
        timeout_ms: 120_000,
    };
    let result = exec_command("/opt/tools/video-download", &args, &options).await;
    let _ = std::fs::remove_file(&temporary_thumb);
    if result.exit_code != 0 {
        let code = serde_json::from_str::<serde_json::Value>(&result.stdout)
            .ok()
            .and_then(|value| value.get("errorCode")?.as_str().map(str::to_string))
            .unwrap_or_else(|| "VIDEO_DOWNLOAD_UI_FAILED".to_string());
        update_state(&id, "failed", Some(&code));
        return;
    }
    update_state(&id, "validating", None);
    let media = super::messages::resolve_media(&operation.chat_id, operation.local_id).await;
    let size = if media.media_type == "video"
        && media.format == "mp4"
        && media.filename == format!("msg_{}.mp4", operation.local_id)
    {
        media
            .data
            .as_deref()
            .and_then(|encoded| {
                base64::engine::general_purpose::STANDARD
                    .decode(encoded)
                    .ok()
            })
            .filter(|bytes| bytes.len() >= 12 && &bytes[4..8] == b"ftyp")
            .map(|bytes| bytes.len() as i64)
            .unwrap_or(0)
    } else {
        0
    };
    if size > 0 {
        finish_ready(&id, size);
    } else {
        update_state(&id, "failed", Some("VIDEO_DOWNLOAD_OUTPUT_INVALID"));
    }
}

pub async fn create(Json(input): Json<CreateRequest>) -> Response {
    if let Err(code) = validate(&input) {
        return (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(serde_json::json!({"error": code})),
        )
            .into_response();
    }
    let id = Uuid::new_v4().to_string();
    let operation_id = {
        let db = get_db();
        if let Err(error) = db.execute(
            "INSERT INTO video_download_operations(id, idempotency_key, chat_id, local_id, state)
             VALUES (?1,?2,?3,?4,'queued') ON CONFLICT(idempotency_key) DO NOTHING",
            rusqlite::params![id, input.idempotency_key, input.chat_id, input.local_id],
        ) {
            tracing::error!("video download insert failed: {error}");
            return StatusCode::INTERNAL_SERVER_ERROR.into_response();
        }
        db.query_row(
            "SELECT id FROM video_download_operations WHERE idempotency_key=?1",
            [&input.idempotency_key],
            |row| row.get::<_, String>(0),
        )
        .unwrap_or_default()
    };
    let Some(mut operation) = load_operation(&operation_id) else {
        return StatusCode::INTERNAL_SERVER_ERROR.into_response();
    };
    if operation.chat_id != input.chat_id || operation.local_id != input.local_id {
        return (
            StatusCode::CONFLICT,
            Json(serde_json::json!({"error": "VIDEO_DOWNLOAD_IDEMPOTENCY_CONFLICT"})),
        )
            .into_response();
    }
    if operation.state == "failed" && operation.attempts < MAX_ATTEMPTS {
        update_state(&operation.id, "queued", None);
        operation = load_operation(&operation_id).unwrap_or(operation);
    } else if operation.state != "ready"
        && operation.attempts < MAX_ATTEMPTS
        && operation.updated_at
            <= (chrono::Utc::now() - chrono::Duration::minutes(10))
                .format("%Y-%m-%d %H:%M:%S")
                .to_string()
    {
        update_state(&operation.id, "queued", None);
        operation = load_operation(&operation_id).unwrap_or(operation);
    }
    schedule(operation_id);
    Json(operation).into_response()
}

pub async fn get(Path(id): Path<String>) -> Response {
    match load_operation(&id) {
        Some(operation) => Json(operation).into_response(),
        None => StatusCode::NOT_FOUND.into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn video_operation_only_accepts_group_message_identity() {
        let valid = CreateRequest {
            idempotency_key: "video-group-34".into(),
            chat_id: "53250352594@chatroom".into(),
            local_id: 34,
        };
        assert_eq!(validate(&valid), Ok(()));
        let invalid = CreateRequest {
            chat_id: "someone".into(),
            ..valid
        };
        assert_eq!(validate(&invalid), Err("VIDEO_DOWNLOAD_MESSAGE_ID_INVALID"));
    }
}
