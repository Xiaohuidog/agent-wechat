use std::fs::{File, OpenOptions, TryLockError};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use crate::ia::identify_states;
use crate::ia::selectors::query_selector;
use crate::sessions::manager::get_session;
use crate::tools::a11y::get_health_a11y_desktop;
use crate::tools::exec::{exec_command, ExecOptions};
use crate::tools::screenshot::capture_screenshot;
use crate::tools::wechat_db::find_wechat_pid;

/// How often to run the health scan (in seconds).
const SCAN_INTERVAL_SECS: u64 = 1;

/// Kill WeChat if no IA state has been identified for this long (in seconds).
const UNRESPONSIVE_TIMEOUT_SECS: u64 = 60;

/// Delay before restarting WeChat after a crash (in seconds).
const RESTART_DELAY_SECS: u64 = 3;

/// If WeChat crashes this many times within RAPID_WINDOW_SECS, back off.
const MAX_RAPID_RESTARTS: u32 = 5;
const RAPID_WINDOW_SECS: u64 = 60;
const BACKOFF_DELAY_SECS: u64 = 30;

/// Global flag to pause health monitoring during active execution loops.
static MONITORING_PAUSED: AtomicBool = AtomicBool::new(false);

/// Pause health monitoring (call when an execution loop starts).
pub fn pause_monitoring() {
    MONITORING_PAUSED.store(true, Ordering::Relaxed);
}

/// Resume health monitoring (call when an execution loop ends).
pub fn resume_monitoring() {
    MONITORING_PAUSED.store(false, Ordering::Relaxed);
}

/// Retain the same flock as external native media tools for the whole probe.
fn try_health_probe_lock(path: &Path) -> std::io::Result<Option<File>> {
    let file = OpenOptions::new().read(true).write(true).create(true).truncate(false).open(path)?;
    match file.try_lock() {
        Ok(()) => Ok(Some(file)),
        Err(TryLockError::WouldBlock) => Ok(None),
        Err(TryLockError::Error(error)) => Err(error),
    }
}

/// Spawn WeChat process for the given session using the shared launch script.
fn spawn_wechat(session: &crate::ia::types::Session) {
    // Use DBUS_SESSION_BUS_ADDRESS from our own environment (inherited from
    // entrypoint.sh) rather than the DB value. The entrypoint's D-Bus session
    // is the one AT-SPI is connected to, so WeChat must use it for a11y to work.
    let result = std::process::Command::new("/opt/tools/launch-wechat")
        .env("DISPLAY", &session.display)
        .env("WECHAT_HOME", format!("/home/{}", session.linux_user))
        .env("WECHAT_USER", &session.linux_user)
        .spawn();

    match result {
        Ok(_) => tracing::info!("[health] Spawned WeChat for session '{}'", session.name),
        Err(e) => tracing::error!("[health] Failed to spawn WeChat: {}", e),
    }
}

/// Spawn the background health monitor task.
///
/// Every second, it checks the default session's WeChat process by running
/// a11y → identify. If WeChat has crashed, it restarts it. If no IA state
/// has been identified for more than 60 seconds, it kills and restarts it.
pub fn spawn_health_monitor() {
    tokio::spawn(async move {
        tracing::info!("[health] WeChat health monitor started");

        let mut last_identified = Instant::now();
        let mut was_running = false;
        let mut expected_exit = None;
        let mut restart_count: u32 = 0;
        let mut window_start = Instant::now();
        let mut waiting_restart_since: Option<Instant> = Some(Instant::now());
        let mut last_saved_account_attempt: Option<Instant> = None;

        loop {
            tokio::time::sleep(std::time::Duration::from_secs(SCAN_INTERVAL_SECS)).await;

            // Skip if monitoring is paused (an execution loop is active)
            if MONITORING_PAUSED.load(Ordering::Relaxed) {
                last_identified = Instant::now();
                continue;
            }

            // Only monitor the default session
            let session = match get_session("default") {
                Some(s) if s.status == "running" => s,
                _ => {
                    last_identified = Instant::now();
                    continue;
                }
            };

            // Check if WeChat process is even running
            let wechat_pid = match find_wechat_pid() {
                Some(pid) => {
                    if !was_running {
                        tracing::info!("[health] WeChat process found (pid={})", pid);
                        was_running = true;
                        waiting_restart_since = None;
                    }
                    pid
                }
                None => {
                    if was_running {
                        if expected_exit.take().is_some() {
                            tracing::info!("[health] WeChat exited after watchdog termination, restarting");
                        } else {
                            tracing::warn!("[health] WeChat exited unexpectedly, restarting");
                        }
                        was_running = false;
                        waiting_restart_since = Some(Instant::now());
                    }

                    // Handle restart with crash loop protection
                    if let Some(since) = waiting_restart_since {
                        // Check crash loop
                        if window_start.elapsed().as_secs() > RAPID_WINDOW_SECS {
                            restart_count = 0;
                            window_start = Instant::now();
                        }

                        let delay = if restart_count >= MAX_RAPID_RESTARTS {
                            if since.elapsed().as_secs() == RESTART_DELAY_SECS {
                                tracing::warn!(
                                    "[health] Crash loop detected ({} restarts in {}s), backing off to {}s",
                                    restart_count, RAPID_WINDOW_SECS, BACKOFF_DELAY_SECS
                                );
                            }
                            BACKOFF_DELAY_SECS
                        } else {
                            RESTART_DELAY_SECS
                        };

                        if since.elapsed().as_secs() >= delay {
                            spawn_wechat(&session);
                            restart_count += 1;
                            waiting_restart_since = None;
                        }
                    }

                    last_identified = Instant::now();
                    continue;
                }
            };

            let lock_path = std::env::var_os("GROUPBOT_UI_LOCK_FILE")
                .map(std::path::PathBuf::from)
                .unwrap_or_else(|| "/data/groupbot-ui.lock".into());
            let _probe_lock = match try_health_probe_lock(&lock_path) {
                Ok(Some(lock)) => lock,
                Ok(None) => {
                    last_identified = Instant::now();
                    continue;
                }
                Err(error) => {
                    tracing::warn!("[health] UI probe lock unavailable: {}", error.kind());
                    last_identified = Instant::now();
                    continue;
                }
            };

            // Run a11y + identify to see if we can detect any state
            let exec_options = ExecOptions {
                session: Some(session.clone()),
                timeout_ms: 10_000,
            };

            let a11y = match get_health_a11y_desktop(&exec_options).await {
                Ok(tree) => tree,
                Err(_) => {
                    // a11y failed — count as unresponsive, don't reset timer
                    if check_and_kill(wechat_pid, &last_identified) {
                        expected_exit = Some(wechat_pid);
                    }
                    continue;
                }
            };

            let screenshot = capture_screenshot(&exec_options)
                .await
                .unwrap_or_default();
            let identified = identify_states(&a11y, &screenshot);

            if identified.main_window.as_ref().is_some_and(|state| state.state_id == "login_account")
                && identified.popup.is_none()
                && last_saved_account_attempt.is_none_or(|at| at.elapsed() >= Duration::from_secs(30))
            {
                if let Some(bounds) = query_selector(
                    &a11y,
                    r#"push-button[name=/^(Log In|Open WeChat|Enter Weixin)$/]"#,
                ).and_then(|button| button.bounds.as_ref()) {
                    let x = (bounds.x + bounds.width / 2.0).round().to_string();
                    let y = (bounds.y + bounds.height / 2.0).round().to_string();
                    last_saved_account_attempt = Some(Instant::now());
                    let result = exec_command("/opt/tools/click", &[&x, &y], &exec_options).await;
                    if result.exit_code != 0 {
                        tracing::warn!("[health] saved-account entry click failed");
                    }
                }
            }

            if identified.main_window.is_some() {
                // State identified — WeChat is responsive
                last_identified = Instant::now();
            } else {
                // No state identified — check timeout
                if check_and_kill(wechat_pid, &last_identified) {
                    expected_exit = Some(wechat_pid);
                }
            }
        }
    });
}

/// If time since last identified state exceeds the timeout, kill the WeChat process.
fn check_and_kill(wechat_pid: i64, last_identified: &Instant) -> bool {
    let elapsed = last_identified.elapsed();
    if elapsed.as_secs() >= UNRESPONSIVE_TIMEOUT_SECS {
        tracing::warn!(
            "[health] WeChat (pid={}) unresponsive for {}s, killing process",
            wechat_pid,
            elapsed.as_secs()
        );

        let result = std::process::Command::new("kill")
            .args(["-9", &wechat_pid.to_string()])
            .output();

        match result {
            Ok(output) if output.status.success() => {
                tracing::info!(
                    "[health] Killed WeChat pid={}, will restart automatically",
                    wechat_pid
                );
                true
            }
            Ok(output) => {
                tracing::warn!(
                    "[health] kill returned non-zero for pid={}: {}",
                    wechat_pid,
                    String::from_utf8_lossy(&output.stderr)
                );
                false
            }
            Err(e) => {
                tracing::error!("[health] Failed to kill WeChat pid={}: {}", wechat_pid, e);
                false
            }
        }
    } else {
        tracing::debug!(
            "[health] WeChat unresponsive for {}s (threshold: {}s)",
            elapsed.as_secs(),
            UNRESPONSIVE_TIMEOUT_SECS
        );
        false
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn health_probe_respects_external_ui_lock_and_releases_it() {
        let path = std::env::temp_dir().join(format!("health-lock-{}", uuid::Uuid::new_v4()));
        let owner = try_health_probe_lock(&path).unwrap().unwrap();
        assert!(try_health_probe_lock(&path).unwrap().is_none());
        drop(owner);
        assert!(try_health_probe_lock(&path).unwrap().is_some());
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn health_identification_does_not_require_virtualized_list_children() {
        fn prune(node: &mut crate::ia::types::A11yNode) {
            if node.role == "list" { node.children = None; return; }
            if let Some(children) = &mut node.children { for child in children { prune(child); } }
        }
        let mut tree = serde_json::from_str(include_str!("../ia/states/test_fixtures/chat_view.json")).unwrap();
        prune(&mut tree);
        assert!(identify_states(&tree, "").main_window.is_some());
    }
}
