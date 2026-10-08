use axum::{extract::Path, http::StatusCode, response::IntoResponse, Json};
use serde::{Deserialize, Serialize};

use crate::db::{get_db, queries::finder_message_xml};
use crate::sessions::manager::get_session;
use crate::tools::wechat_messages::finder_media_url;
use crate::tools::finder_short_link::{
    browser_status, resolve_short_link, show_browser, FinderShortLinkError,
};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ShortLinkInput {
    object_id: String,
    object_nonce_id: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ShortLinkOutput<'a> {
    object_id: &'a str,
    short_url: String,
}

pub async fn short_link(Json(input): Json<ShortLinkInput>) -> impl IntoResponse {
    match resolve_short_link(&input.object_id, &input.object_nonce_id).await {
        Ok(short_url) => (
            StatusCode::OK,
            Json(
                serde_json::to_value(ShortLinkOutput {
                    object_id: &input.object_id,
                    short_url,
                })
                .expect("short-link response must serialize"),
            ),
        ),
        Err(error) => {
            let status = match error {
                FinderShortLinkError::InvalidObjectId | FinderShortLinkError::InvalidNonceId => {
                    StatusCode::UNPROCESSABLE_ENTITY
                }
                FinderShortLinkError::SessionUnavailable => StatusCode::SERVICE_UNAVAILABLE,
                _ => StatusCode::BAD_GATEWAY,
            };
            (status, Json(serde_json::json!({"error": error.code()})))
        }
    }
}

pub async fn media_source(Path((chat_id, local_id, kind)): Path<(String, i64, String)>) -> impl IntoResponse {
    if kind != "cover" && kind != "playable" {
        return (StatusCode::UNPROCESSABLE_ENTITY, Json(serde_json::json!({"error": "FINDER_MEDIA_KIND_INVALID"})));
    }
    let Some(session) = get_session("default") else {
        return (StatusCode::SERVICE_UNAVAILABLE, Json(serde_json::json!({"error": "FINDER_SESSION_UNAVAILABLE"})));
    };
    let Some(account_dir) = session.logged_in_user.as_deref() else {
        return (StatusCode::SERVICE_UNAVAILABLE, Json(serde_json::json!({"error": "FINDER_SESSION_UNAVAILABLE"})));
    };
    let source = {
        let db = get_db();
        finder_message_xml(&db, &session.id, account_dir, &chat_id, local_id)
    };
    let Ok(Some(xml)) = source else {
        return (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "FINDER_MEDIA_SOURCE_NOT_FOUND"})));
    };
    let Some(url) = finder_media_url(&xml, &kind) else {
        return (StatusCode::UNPROCESSABLE_ENTITY, Json(serde_json::json!({"error": "FINDER_MEDIA_SOURCE_INVALID"})));
    };
    (StatusCode::OK, Json(serde_json::json!({"url": url})))
}

pub async fn session_status() -> impl IntoResponse {
    browser_response(browser_status().await)
}

pub async fn show_session() -> impl IntoResponse {
    browser_response(show_browser().await)
}

fn browser_response(
    result: Result<crate::tools::finder_short_link::FinderBrowserStatus, FinderShortLinkError>,
) -> (StatusCode, Json<serde_json::Value>) {
    match result {
        Ok(status) => (
            StatusCode::OK,
            Json(serde_json::to_value(status).expect("browser status must serialize")),
        ),
        Err(_) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({"status": "unavailable"})),
        ),
    }
}
