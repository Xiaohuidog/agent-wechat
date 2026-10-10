use axum::{
    extract::{Path, Query},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Deserialize;
use tokio_util::sync::CancellationToken;

use crate::context::create_context;
use crate::db::queries::{upsert_finder_message_source, FinderMessageSource};
use crate::db::get_db;
use crate::execution::run_execution_loop;
use crate::ia::types::{MediaResult, Message, SendResult, SubscriptionEvent};
use crate::plans::send_message::{SendMessageParams, SendMessagePlan};
use crate::tools::wechat_db::{find_wechat_pid, list_account_dbs};
use crate::tools::wechat_keys::{extract_keys_async, get_stored_keys, get_image_keys, store_keys};
use crate::tools::wechat_media::{get_message_file_media, get_message_media};
use crate::tools::wechat_messages;
use crate::sessions::manager::get_session;

#[derive(Deserialize)]
pub struct ListParams {
    #[serde(default = "default_limit")]
    limit: i64,
    #[serde(default)]
    offset: i64,
}

fn default_limit() -> i64 {
    50
}

pub async fn list_messages(
    Path(chat_id): Path<String>,
    Query(params): Query<ListParams>,
) -> Response {
    let session = match get_session("default") {
        Some(s) => s,
        None => return Json(Vec::<Message>::new()).into_response(),
    };
    let logged_in_user = match &session.logged_in_user {
        Some(u) => u.clone(),
        None => return Json(Vec::<Message>::new()).into_response(),
    };

    let mut keys = {
        let db = get_db();
        get_stored_keys(&db, &session.id, &logged_in_user)
    };

    // Lazy key extraction: if message_*.db files exist on disk without stored keys, re-extract
    let on_disk = list_account_dbs(&logged_in_user);
    let has_missing_message_db = on_disk.iter().any(|name| {
        name.starts_with("message_")
            && name.ends_with(".db")
            && !name.contains("fts")
            && !name.contains("resource")
            && !keys.contains_key(name.as_str())
    });
    if has_missing_message_db {
        if let Some(pid) = find_wechat_pid() {
            let extracted = extract_keys_async(pid).await;
            if !extracted.is_empty() {
                let db = get_db();
                store_keys(&db, &session.id, &logged_in_user, &extracted);
                keys = get_stored_keys(&db, &session.id, &logged_in_user);
            }
        }
    }

    if !keys.keys().any(|k| k.starts_with("message_") && k.ends_with(".db") && !k.contains("fts") && !k.contains("resource")) {
        return Json(Vec::<Message>::new()).into_response();
    }

    let collected = wechat_messages::list_messages(
        &logged_in_user,
        &keys,
        &chat_id,
        params.limit,
        params.offset,
    );

    {
        let mut db = get_db();
        let transaction = match db.transaction() {
            Ok(transaction) => transaction,
            Err(error) => {
                tracing::error!("[finder-source] failed to start storage transaction: {error}");
                return (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({"error": "FINDER_SOURCE_STORE_FAILED"})),
                )
                    .into_response();
            }
        };
        for item in &collected {
            let Some(source) = &item.finder_source else {
                continue;
            };
            let input = FinderMessageSource {
                session_id: &session.id,
                account_dir: &logged_in_user,
                chat_id: &chat_id,
                local_id: item.message.local_id,
                server_id: item.message.server_id,
                object_id: &source.object_id,
                object_nonce_id: &source.object_nonce_id,
                raw_xml: &source.raw_xml,
            };
            if let Err(error) = upsert_finder_message_source(&transaction, &input) {
                tracing::error!(
                    "[finder-source] failed to store source for local_id={}: {error}",
                    item.message.local_id
                );
                return (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({"error": "FINDER_SOURCE_STORE_FAILED"})),
                )
                    .into_response();
            }
        }
        if let Err(error) = transaction.commit() {
            tracing::error!("[finder-source] failed to commit source records: {error}");
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({"error": "FINDER_SOURCE_STORE_FAILED"})),
            )
                .into_response();
        }
    }

    Json(
        collected
            .into_iter()
            .map(|item| item.message)
            .collect::<Vec<_>>(),
    )
    .into_response()
}

pub async fn resolve_media(chat_id: &str, local_id: i64) -> MediaResult {
    let session = match get_session("default") {
        Some(s) => s,
        None => {
            return MediaResult {
                media_type: "unsupported".to_string(),
                data: None,
                url: None,
                format: String::new(),
                filename: String::new(),
            }
        }
    };
    let logged_in_user = match &session.logged_in_user {
        Some(u) => u.clone(),
        None => {
            return MediaResult {
                media_type: "unsupported".to_string(),
                data: None,
                url: None,
                format: String::new(),
                filename: String::new(),
            }
        }
    };

    let mut keys = {
        let db = get_db();
        get_stored_keys(&db, &session.id, &logged_in_user)
    };

    if let Some(file_media) = get_message_file_media(&logged_in_user, &keys, chat_id, local_id) {
        return file_media;
    }

    // Lazy key extraction: if media_*.db files exist on disk without stored keys, extract them
    let on_disk = list_account_dbs(&logged_in_user);
    let has_missing_media = on_disk.iter().any(|name| {
        name.starts_with("media_") && name.ends_with(".db") && !keys.contains_key(name.as_str())
    });
    if has_missing_media {
        if let Some(pid) = find_wechat_pid() {
            let extracted = extract_keys_async(pid).await;
            if !extracted.is_empty() {
                let db = get_db();
                store_keys(&db, &session.id, &logged_in_user, &extracted);
                keys = get_stored_keys(&db, &session.id, &logged_in_user);
            }
        }
    }

    let mut image_keys = {
        let db = get_db();
        get_image_keys(&db, &session.id, &logged_in_user)
    };

    // A UI preview is already a readable JPEG saved by the image downloader.
    // Return it before retrying image-key extraction, which can block on a
    // WeChat build whose offsets are not known yet.
    let cached_media = get_message_media(
        &logged_in_user,
        &keys,
        chat_id,
        local_id,
        image_keys.clone(),
    );
    if should_return_cached_media(&cached_media) {
        return cached_media;
    }

    // The regular database keys can already be present after login while the
    // image AES key is still missing. Retry extraction before returning an
    // empty image payload so existing .dat files can be decrypted.
    if image_keys.is_none() {
        if let Some(pid) = find_wechat_pid() {
            let extracted = extract_keys_async(pid).await;
            if !extracted.is_empty() {
                let db = get_db();
                store_keys(&db, &session.id, &logged_in_user, &extracted);
                image_keys = get_image_keys(&db, &session.id, &logged_in_user);
                keys = get_stored_keys(&db, &session.id, &logged_in_user);
            }
        }
    }

    get_message_media(
        &logged_in_user,
        &keys,
        chat_id,
        local_id,
        image_keys,
    )
}

fn should_return_cached_media(media: &MediaResult) -> bool {
    media.data.is_some() || matches!(media.media_type.as_str(), "image" | "file")
}

pub async fn get_media(Path((chat_id, local_id)): Path<(String, i64)>) -> Json<MediaResult> {
    Json(resolve_media(&chat_id, local_id).await)
}

#[cfg(test)]
mod file_media_tests {
    use super::should_return_cached_media;
    use crate::ia::types::MediaResult;

    #[test]
    fn pending_file_skips_unrelated_image_key_extraction() {
        let file = MediaResult {
            media_type: "file".into(),
            data: None,
            url: None,
            format: "pdf".into(),
            filename: "项目说明.pdf".into(),
        };

        assert!(should_return_cached_media(&file));
    }
}

#[derive(Deserialize)]
pub struct SendParams {
    #[serde(rename = "chatId")]
    chat_id: String,
    #[serde(rename = "chatName")]
    chat_name: Option<String>,
    text: Option<String>,
    image: Option<ImageInput>,
    file: Option<FileInput>,
}

#[derive(Deserialize)]
pub struct ImageInput {
    data: String,
    #[serde(rename = "mimeType")]
    mime_type: String,
}

#[derive(Deserialize)]
pub struct FileInput {
    data: String,
    filename: String,
}

pub async fn send_message(Json(input): Json<SendParams>) -> Json<SendResult> {
    if input.text.is_none() && input.image.is_none() && input.file.is_none() {
        return Json(SendResult {
            success: false,
            error: Some("No text, image, or file provided".to_string()),
        });
    }

    let session = match get_session("default") {
        Some(s) => s,
        None => {
            return Json(SendResult {
                success: false,
                error: Some("No session available".to_string()),
            })
        }
    };

    if session.logged_in_user.is_none() {
        return Json(SendResult {
            success: false,
            error: Some("NOT_LOGGED_IN".to_string()),
        });
    }

    // Decode base64 image to temp file
    let mut image_path: Option<String> = None;
    let mut image_mime: Option<String> = None;
    if let Some(ref img) = input.image {
        let ext = match img.mime_type.as_str() {
            "image/jpeg" => ".jpg",
            "image/gif" => ".gif",
            _ => ".png",
        };
        let path = format!("/tmp/send_image_{}{}", std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_millis(), ext);
        if let Ok(bytes) = base64::Engine::decode(&base64::engine::general_purpose::STANDARD, &img.data) {
            if std::fs::write(&path, &bytes).is_ok() {
                image_mime = Some(img.mime_type.clone());
                image_path = Some(path);
            }
        }
    }

    // Stage the upload under its exact filename so WeChat uses that name for the file card.
    let mut file_path: Option<String> = None;
    if let Some(ref f) = input.file {
        let bytes = match base64::Engine::decode(&base64::engine::general_purpose::STANDARD, &f.data) {
            Ok(bytes) => bytes,
            Err(e) => {
                return Json(SendResult {
                    success: false,
                    error: Some(format!("Failed to decode base64 file data: {e}")),
                });
            }
        };
        match stage_outbound_file(&f.filename, &bytes) {
            Ok(path) => { file_path = Some(path.to_string_lossy().into_owned()); }
            Err(error) => {
                return Json(SendResult { success: false, error: Some(error) });
            }
        }
    }

    let mut context = {
        let db = get_db();
        create_context(session, &db)
    };

    let plan = SendMessagePlan;
    let params = SendMessageParams {
        chat_id: input.chat_id,
        chat_name: input.chat_name,
        message: input.text,
        image_path: image_path.clone(),
        image_mime,
        file_path: file_path.clone(),
    };
    let cancel = CancellationToken::new();
    let noop_emit = |_: SubscriptionEvent| {};

    let (result, _plan_state) =
        run_execution_loop(&plan, &params, &mut context, &noop_emit, cancel).await;

    // Clean up temp files
    if let Some(p) = &image_path {
        let _ = std::fs::remove_file(p);
    }
    if let Some(p) = &file_path {
        let _ = std::fs::remove_file(p);
        if let Some(parent) = std::path::Path::new(p).parent() {
            let _ = std::fs::remove_dir(parent);
        }
    }

    Json(SendResult {
        success: result.success,
        error: result.error,
    })
}


fn stage_outbound_file(filename: &str, bytes: &[u8]) -> Result<std::path::PathBuf, String> {
    if filename.is_empty()
        || matches!(filename, "." | "..")
        || filename.len() > 240
        || filename.contains('/')
        || filename.contains('\\')
        || filename.chars().any(char::is_control)
    {
        return Err("Invalid outbound filename".to_string());
    }
    let directory = std::env::temp_dir().join(format!("send_file_{}", uuid::Uuid::new_v4()));
    std::fs::create_dir(&directory)
        .map_err(|error| format!("Failed to create temp directory: {error}"))?;
    let path = directory.join(filename);
    if let Err(error) = std::fs::write(&path, bytes) {
        let _ = std::fs::remove_dir(&directory);
        return Err(format!("Failed to write temp file: {error}"));
    }
    Ok(path)
}

#[cfg(test)]
mod outbound_filename_tests {
    use super::stage_outbound_file;

    #[test]
    fn staged_file_keeps_the_uploaded_unicode_filename() {
        let path = stage_outbound_file("《创始人行动手册》.pdf", b"%PDF-1.4").unwrap();
        assert_eq!(path.file_name().unwrap(), "《创始人行动手册》.pdf");
        assert_eq!(std::fs::read(&path).unwrap(), b"%PDF-1.4");
        std::fs::remove_dir_all(path.parent().unwrap()).unwrap();
    }
}
