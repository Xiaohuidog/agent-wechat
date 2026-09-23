use crate::ia::types::Session;
use std::collections::HashMap;
use tokio::process::Command;

#[derive(Debug)]
pub struct CommandResult {
    pub stdout: String,
    pub stderr: String,
    pub exit_code: i32,
}

pub struct ExecOptions {
    pub session: Option<Session>,
    pub timeout_ms: u64,
}

impl Default for ExecOptions {
    fn default() -> Self {
        Self {
            session: None,
            timeout_ms: 60_000,
        }
    }
}

/// Execute a command with fixed arguments (no shell interpolation).
///
/// If a session is provided, the command runs with that session's
/// DISPLAY and DBUS_SESSION_BUS_ADDRESS environment.
pub async fn exec_command(
    command: &str,
    args: &[&str],
    options: &ExecOptions,
) -> CommandResult {
    let mut env: HashMap<String, String> = std::env::vars().collect();
    env.insert("QT_ACCESSIBILITY".into(), "1".into());
    env.insert("QT_LINUX_ACCESSIBILITY_ALWAYS_ON".into(), "1".into());

    if let Some(session) = &options.session {
        env.insert("DISPLAY".into(), session.display.clone());
        env.insert(
            "DBUS_SESSION_BUS_ADDRESS".into(),
            session.dbus_address.clone().unwrap_or_default(),
        );
        env.insert("HOME".into(), format!("/home/{}", session.linux_user));
    } else {
        env.entry("DISPLAY".into())
            .or_insert_with(|| ":99".into());
    }

    let timeout = std::time::Duration::from_millis(options.timeout_ms);

    let result = tokio::time::timeout(timeout, async {
        let output = Command::new(command)
            .args(args)
            .envs(&env)
            .output()
            .await;

        match output {
            Ok(out) => CommandResult {
                stdout: String::from_utf8_lossy(&out.stdout).trim().to_string(),
                stderr: String::from_utf8_lossy(&out.stderr).trim().to_string(),
                exit_code: out.status.code().unwrap_or(1),
            },
            Err(err) => CommandResult {
                stdout: String::new(),
                stderr: err.to_string(),
                exit_code: 1,
            },
        }
    })
    .await;

    match result {
        Ok(r) => r,
        Err(_) => CommandResult {
            stdout: String::new(),
            stderr: "Command timed out".to_string(),
            exit_code: 1,
        },
    }
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;

    #[tokio::test]
    async fn timed_out_command_does_not_leave_a_child_running() {
        let directory = tempfile::tempdir().unwrap();
        let pid_path = directory.path().join("child.pid");
        let script = "import os,sys,time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)";
        let result = exec_command(
            "python3",
            &["-c", script, pid_path.to_str().unwrap()],
            &ExecOptions { timeout_ms: 500, ..Default::default() },
        ).await;
        assert_eq!(result.stderr, "Command timed out");
        let pid: u32 = std::fs::read_to_string(&pid_path).unwrap().parse().unwrap();
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        let alive = std::path::Path::new(&format!("/proc/{pid}")).exists();
        if alive {
            let _ = std::process::Command::new("kill").arg(pid.to_string()).status();
        }
        assert!(!alive, "timed-out child process {pid} was left running");
    }
}
