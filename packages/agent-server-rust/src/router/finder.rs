use axum::{http::StatusCode, response::IntoResponse, Json};
use serde::{Deserialize, Serialize};

use crate::tools::finder_short_link::{resolve_short_link, FinderShortLinkError};

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
