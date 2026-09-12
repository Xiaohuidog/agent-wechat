use reqwest::{header, Client, Url};
use serde::Serialize;
use serde_json::Value;
use std::{path::Path, sync::OnceLock, time::Duration};

const SHORT_LINK_API: &str =
    "https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/post/get_object_short_link";
const MAX_RESPONSE_BYTES: u64 = 1024 * 1024;
const MAX_COOKIE_BYTES: usize = 32 * 1024;

static CLIENT: OnceLock<Client> = OnceLock::new();

#[derive(Debug, PartialEq)]
pub enum FinderShortLinkError {
    InvalidObjectId,
    InvalidNonceId,
    SessionUnavailable,
    RequestFailed,
    ResponseInvalid,
    RemoteRejected,
    LinkMissing,
}

impl FinderShortLinkError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::InvalidObjectId => "FINDER_OBJECT_ID_INVALID",
            Self::InvalidNonceId => "FINDER_NONCE_ID_INVALID",
            Self::SessionUnavailable => "FINDER_SESSION_UNAVAILABLE",
            Self::RequestFailed => "FINDER_SHORT_LINK_REQUEST_FAILED",
            Self::ResponseInvalid => "FINDER_SHORT_LINK_RESPONSE_INVALID",
            Self::RemoteRejected => "FINDER_SHORT_LINK_REMOTE_REJECTED",
            Self::LinkMissing => "FINDER_SHORT_LINK_MISSING",
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ShortLinkRequest<'a> {
    export_id: &'a str,
    nonce_id: &'a str,
    scene: u8,
}

fn valid_object_id(value: &str) -> bool {
    (6..=32).contains(&value.len())
        && !value.starts_with('0')
        && value.bytes().all(|byte| byte.is_ascii_digit())
}

fn valid_nonce_id(value: &str) -> bool {
    (6..=512).contains(&value.len())
        && value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric()
                || matches!(byte, b'_' | b'.' | b'~' | b'+' | b'/' | b'=' | b'-')
        })
}

fn valid_cookie(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_COOKIE_BYTES
        && value.bytes().all(|byte| !byte.is_ascii_control())
        && value.split(';').all(|part| {
            let Some((name, cookie_value)) = part.trim().split_once('=') else {
                return false;
            };
            !name.is_empty()
                && !cookie_value.is_empty()
                && name
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
        })
}

fn read_secret_file(name: &str) -> Option<String> {
    let path = std::env::var(name).ok()?;
    std::fs::read_to_string(Path::new(&path)).ok()
}

fn cookie_header() -> Result<String, FinderShortLinkError> {
    let value = read_secret_file("FINDER_COOKIE_FILE")
        .or_else(|| std::env::var("FINDER_COOKIE").ok())
        .or_else(|| {
            read_secret_file("FINDER_SESSION_INFO_FILE")
                .or_else(|| std::env::var("FINDER_SESSION_INFO").ok())
                .map(|value| format!("sessionInfo={}", value.trim()))
        })
        .map(|value| value.trim().to_string())
        .filter(|value| valid_cookie(value))
        .ok_or(FinderShortLinkError::SessionUnavailable)?;
    Ok(value)
}

fn client() -> Result<&'static Client, FinderShortLinkError> {
    if let Some(client) = CLIENT.get() {
        return Ok(client);
    }
    let created = Client::builder()
        .timeout(Duration::from_secs(15))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| FinderShortLinkError::RequestFailed)?;
    let _ = CLIENT.set(created);
    CLIENT.get().ok_or(FinderShortLinkError::RequestFailed)
}

fn trusted_link(value: &str) -> Option<String> {
    let parsed = Url::parse(value.trim()).ok()?;
    if parsed.scheme() != "https"
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || !matches!(parsed.port(), None | Some(443))
    {
        return None;
    }
    let trusted = matches!(
        (parsed.host_str(), parsed.path()),
        (Some("weixin.qq.com"), path) if path.starts_with("/sph/")
    ) || matches!(
        (parsed.host_str(), parsed.path()),
        (Some("channels.weixin.qq.com"), path)
            if path.starts_with("/finder-preview/pages/sph")
    );
    trusted.then(|| value.trim().to_string())
}

fn parse_response(payload: &Value) -> Result<String, FinderShortLinkError> {
    let error_code = payload
        .get("errCode")
        .or_else(|| payload.get("errcode"))
        .and_then(Value::as_i64)
        .ok_or(FinderShortLinkError::ResponseInvalid)?;
    if error_code != 0 {
        return Err(FinderShortLinkError::RemoteRejected);
    }
    let data = payload.get("data").and_then(Value::as_object);
    for name in ["shortUrl", "short_url", "url"] {
        if let Some(link) = payload
            .get(name)
            .and_then(Value::as_str)
            .or_else(|| {
                data.and_then(|value| value.get(name))
                    .and_then(Value::as_str)
            })
            .and_then(trusted_link)
        {
            return Ok(link);
        }
    }
    Err(FinderShortLinkError::LinkMissing)
}

pub async fn resolve_short_link(
    object_id: &str,
    nonce_id: &str,
) -> Result<String, FinderShortLinkError> {
    if !valid_object_id(object_id) {
        return Err(FinderShortLinkError::InvalidObjectId);
    }
    if !valid_nonce_id(nonce_id) {
        return Err(FinderShortLinkError::InvalidNonceId);
    }
    let cookie = header::HeaderValue::from_str(&cookie_header()?)
        .map_err(|_| FinderShortLinkError::SessionUnavailable)?;
    let response = client()?
        .post(SHORT_LINK_API)
        .header(header::ACCEPT, "application/json, text/plain, */*")
        .header(header::CONTENT_TYPE, "application/json;charset=UTF-8")
        .header(header::COOKIE, cookie)
        .header(header::ORIGIN, "https://channels.weixin.qq.com")
        .header(
            header::REFERER,
            "https://channels.weixin.qq.com/platform/post/list?",
        )
        .header("x-requested-with", "XMLHttpRequest")
        .json(&ShortLinkRequest {
            export_id: object_id,
            nonce_id,
            scene: 40,
        })
        .send()
        .await
        .map_err(|_| FinderShortLinkError::RequestFailed)?;
    if !response.status().is_success()
        || response.content_length().unwrap_or(0) > MAX_RESPONSE_BYTES
    {
        return Err(FinderShortLinkError::RequestFailed);
    }
    let body = response
        .bytes()
        .await
        .map_err(|_| FinderShortLinkError::RequestFailed)?;
    if body.len() as u64 > MAX_RESPONSE_BYTES {
        return Err(FinderShortLinkError::ResponseInvalid);
    }
    let payload: Value =
        serde_json::from_slice(&body).map_err(|_| FinderShortLinkError::ResponseInvalid)?;
    parse_response(&payload)
}

#[cfg(test)]
mod tests {
    use super::{
        parse_response, trusted_link, valid_cookie, valid_nonce_id, valid_object_id,
        FinderShortLinkError,
    };
    use serde_json::json;

    #[test]
    fn validates_exact_finder_identity() {
        assert!(valid_object_id("14726213509764749552"));
        assert!(valid_nonce_id(
            "11529959359054593652_4_20_13_1_1789211747091905_504lish"
        ));
        assert!(!valid_object_id("012345"));
        assert!(!valid_nonce_id("bad cookie"));
    }

    #[test]
    fn accepts_cookie_headers_without_control_characters() {
        assert!(valid_cookie("sessionInfo=abc123; token=def-456"));
        assert!(!valid_cookie("sessionInfo="));
        assert!(!valid_cookie("sessionInfo=abc\r\nInjected=yes"));
        assert!(!valid_cookie("invalid"));
    }

    #[test]
    fn accepts_only_official_short_links() {
        assert_eq!(
            trusted_link("https://weixin.qq.com/sph/AbCdEf1234"),
            Some("https://weixin.qq.com/sph/AbCdEf1234".to_string())
        );
        assert_eq!(
            trusted_link("https://channels.weixin.qq.com/finder-preview/pages/sph?id=AbCd"),
            Some("https://channels.weixin.qq.com/finder-preview/pages/sph?id=AbCd".to_string())
        );
        assert_eq!(trusted_link("https://example.com/sph/AbCd"), None);
    }

    #[test]
    fn parses_success_without_exposing_remote_messages() {
        assert_eq!(
            parse_response(&json!({
                "errCode": 0,
                "data": {"shortUrl": "https://weixin.qq.com/sph/AbCdEf1234"}
            })),
            Ok("https://weixin.qq.com/sph/AbCdEf1234".to_string())
        );
        assert_eq!(
            parse_response(&json!({"errCode": 300330, "errMsg": "private"})),
            Err(FinderShortLinkError::RemoteRejected)
        );
    }
}
