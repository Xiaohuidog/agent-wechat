use super::Plan;
use crate::ia::actions;
use crate::ia::selectors::query_selector;
use crate::ia::types::*;
use crate::tools::chat_select::{open_chat, OpenChatResult};
use crate::tools::exec::{exec_command, ExecOptions};

pub struct SendMessagePlan;

pub struct SendMessageParams {
    pub chat_id: String,
    pub chat_name: Option<String>,
    pub message: Option<String>,
    pub image_path: Option<String>,
    pub image_mime: Option<String>,
    pub file_path: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::{confirmation_can_finish, opened_chat_matches, A11yNode};

    #[test]
    fn sent_message_is_confirmed_even_when_editor_controls_are_temporarily_missing() {
        assert!(confirmation_can_finish(true, false, false));
        assert!(!confirmation_can_finish(false, true, false));
    }

    #[test]
    fn image_send_is_confirmed_by_disabled_send_button() {
        assert!(confirmation_can_finish(false, true, true));
    }

    #[test]
    fn stale_chat_window_is_not_accepted_as_target() {
        let tree = A11yNode {
            role: "desktop-frame".into(),
            name: "main".into(),
            bounds: None,
            states: None,
            children: Some(vec![A11yNode {
                role: "frame".into(),
                name: "群测试".into(),
                bounds: None,
                states: None,
                children: None,
            }]),
        };

        assert!(opened_chat_matches(&tree, "群测试"));
        assert!(!opened_chat_matches(&tree, "uncle篮球队"));
    }
}

pub enum SendMessagePhase {
    Opening,
    Focusing,
    Inputting,
    Confirming,
    Done,
}

pub struct SendMessagePlanState {
    pub phase: SendMessagePhase,
    pub open_result: Option<OpenChatResult>,
    pub open_attempts: u8,
    pub confirm_attempts: u32,
    pub send_retries: u8,
}

fn find_edit_and_send_button(a11y: &A11yNode) -> Option<(&A11yNode, &A11yNode)> {
    let send_btn = query_selector(a11y, r#"push-button[name="Send(S)"]"#)?;
    // Find sibling EDITABLE text node via parent
    // Since we don't have parent refs in the tree-based approach,
    // we search the tree for the pattern
    find_edit_near_send(a11y, send_btn)
}

fn find_edit_near_send<'a>(
    root: &'a A11yNode,
    _send_btn: &A11yNode,
) -> Option<(&'a A11yNode, &'a A11yNode)> {
    // Walk tree looking for a parent that has both an EDITABLE text and Send(S) button
    find_edit_send_pair(root)
}

fn find_edit_send_pair(node: &A11yNode) -> Option<(&A11yNode, &A11yNode)> {
    if let Some(children) = &node.children {
        let send_btn = children.iter().find(|c| {
            c.role == "push-button" && c.name == "Send(S)"
        });
        let edit_node = children.iter().find(|c| {
            c.role == "text"
                && c.states
                    .as_ref()
                    .map(|s| s.iter().any(|st| st == "EDITABLE"))
                    .unwrap_or(false)
        });

        if let (Some(edit), Some(send)) = (edit_node, send_btn) {
            return Some((edit, send));
        }

        // Recurse
        for child in children {
            if let Some(result) = find_edit_send_pair(child) {
                return Some(result);
            }
        }
    }
    None
}

fn contains_message(node: &A11yNode, message: &str) -> bool {
    if node.name == message {
        return true;
    }
    node.children
        .as_ref()
        .map(|children| children.iter().any(|child| contains_message(child, message)))
        .unwrap_or(false)
}

fn opened_chat_matches(node: &A11yNode, chat_name: &str) -> bool {
    let expected = chat_name.trim();
    if expected.is_empty() {
        return false;
    }
    if node.role == "frame"
        && (node.name == expected || node.name.starts_with(&format!("{expected}(")))
    {
        return true;
    }
    node.children
        .as_ref()
        .map(|children| children.iter().any(|child| opened_chat_matches(child, expected)))
        .unwrap_or(false)
}

fn confirmation_can_finish(
    message_visible: bool,
    send_button_disabled: bool,
    has_non_text_payload: bool,
) -> bool {
    if has_non_text_payload {
        send_button_disabled
    } else {
        message_visible
    }
}

#[async_trait::async_trait]
impl Plan for SendMessagePlan {
    type PlanState = SendMessagePlanState;
    type Params = SendMessageParams;

    fn id(&self) -> &str { "send_message" }

    fn initial_plan_state(&self) -> SendMessagePlanState {
        SendMessagePlanState {
            phase: SendMessagePhase::Opening,
            open_result: None,
            open_attempts: 0,
            confirm_attempts: 0,
            send_retries: 0,
        }
    }

    fn is_goal_reached(&self, _state: &AppState, plan_state: &SendMessagePlanState) -> bool {
        matches!(plan_state.phase, SendMessagePhase::Done)
    }

    async fn select_action(
        &self,
        state: &AppState,
        params: &SendMessageParams,
        identified: &IdentifiedStates,
        plan_state: &mut SendMessagePlanState,
        a11y: &A11yNode,
        _session_id: &str,
    ) -> Option<SelectedAction> {
        let main_state_id = identified.main_window.as_ref().map(|m| m.state_id.as_str());

        // Dismiss popups
        if state.popup.is_some() && identified.popup.is_some() {
            return Some(SelectedAction {
                action: actions::dismiss_popup(),
                frame: identified.main_window.as_ref().and_then(|m| m.frame.clone()),
            });
        }

        loop {
            match &plan_state.phase {
                SendMessagePhase::Opening => {
                    if main_state_id != Some("chat") && main_state_id != Some("chat_open") {
                        return None;
                    }

                    let chat_list_item = query_selector(a11y, r#"list[name="Chats"] > list-item"#);
                    let click_xy = chat_list_item.and_then(|item| {
                        item.bounds.as_ref().map(|b| (
                            (b.x + b.width / 2.0).round(),
                            (b.y + b.height / 2.0).round(),
                        ))
                    });

                    let force = main_state_id == Some("chat");
                    let result = open_chat(
                        &params.chat_id,
                        force,
                        click_xy,
                        params.chat_name.as_deref(),
                    )
                    .await;

                    if !result.ok {
                        return None;
                    }

                    let skipped = result.skipped.unwrap_or(false);
                    plan_state.open_result = Some(result);
                    plan_state.phase = SendMessagePhase::Focusing;

                    if !skipped {
                        return Some(SelectedAction {
                            action: actions::wait_short(),
                            frame: identified.main_window.as_ref().and_then(|m| m.frame.clone()),
                        });
                    }
                    continue;
                }

                SendMessagePhase::Focusing => {
                    if main_state_id != Some("chat_open") {
                        return None;
                    }

                    if let Some(chat_name) = params.chat_name.as_deref() {
                        if !opened_chat_matches(a11y, chat_name) {
                            if plan_state.open_attempts < 2 {
                                plan_state.open_attempts += 1;
                                plan_state.phase = SendMessagePhase::Opening;
                                return Some(SelectedAction {
                                    action: actions::wait_short(),
                                    frame: identified.main_window.as_ref().and_then(|m| m.frame.clone()),
                                });
                            }
                            return None;
                        }
                    }

                    let found = find_edit_and_send_button(a11y);
                    let (edit_node, _) = match found {
                        Some(f) => f,
                        None => return None,
                    };

                    plan_state.phase = SendMessagePhase::Inputting;

                    let is_focused = edit_node
                        .states
                        .as_ref()
                        .map(|s| s.iter().any(|st| st == "FOCUSED"))
                        .unwrap_or(false);

                    if is_focused {
                        continue;
                    }

                    if let Some(bounds) = &edit_node.bounds {
                        return Some(SelectedAction {
                            action: actions::click_bounds(bounds),
                            frame: identified.main_window.as_ref().and_then(|m| m.frame.clone()),
                        });
                    }
                    return None;
                }

                SendMessagePhase::Inputting => {
                    if find_edit_and_send_button(a11y).is_none() {
                        return None;
                    }

                    plan_state.phase = SendMessagePhase::Confirming;

                    // File
                    if let Some(fp) = &params.file_path {
                        exec_command("paste-file", &[fp], &ExecOptions::default()).await;
                        return Some(SelectedAction {
                            action: actions::sequence(vec![
                                Action::Wait { ms: 500 },
                                Action::Key { combo: "Return".to_string() },
                            ]),
                            frame: identified.main_window.as_ref().and_then(|m| m.frame.clone()),
                        });
                    }

                    // Image
                    if let Some(ip) = &params.image_path {
                        let mut args: Vec<&str> = vec![ip];
                        if let Some(mime) = &params.image_mime {
                            args.push(mime);
                        }
                        exec_command("paste-image", &args, &ExecOptions::default()).await;
                        return Some(SelectedAction {
                            action: actions::sequence(vec![
                                Action::Wait { ms: 500 },
                                Action::Key { combo: "Return".to_string() },
                            ]),
                            frame: identified.main_window.as_ref().and_then(|m| m.frame.clone()),
                        });
                    }

                    // Text
                    if let Some(msg) = &params.message {
                        plan_state.phase = SendMessagePhase::Confirming;
                        return Some(SelectedAction {
                            action: actions::sequence(vec![
                                Action::Type { text: msg.clone(), selector: None },
                                Action::Wait { ms: 100 },
                                Action::Key { combo: "Return".to_string() },
                            ]),
                            frame: identified.main_window.as_ref().and_then(|m| m.frame.clone()),
                        });
                    }

                    return None;
                }

                SendMessagePhase::Confirming => {
                    let message_visible = params
                        .message
                        .as_deref()
                        .map(|message| contains_message(a11y, message))
                        .unwrap_or(false);

                    let send_button_disabled = find_edit_and_send_button(a11y)
                        .and_then(|(_, send_btn)| send_btn.states.as_ref())
                        .map(|states| states.iter().any(|state| state == "DISABLED"))
                        .unwrap_or(false);

                    let has_non_text_payload =
                        params.image_path.is_some() || params.file_path.is_some();
                    if confirmation_can_finish(
                        message_visible,
                        send_button_disabled,
                        has_non_text_payload,
                    ) {
                        plan_state.phase = SendMessagePhase::Done;
                        return Some(SelectedAction {
                            action: actions::wait_short(),
                            frame: identified.main_window.as_ref().and_then(|m| m.frame.clone()),
                        });
                    }

                    plan_state.confirm_attempts += 1;
                    if plan_state.confirm_attempts >= 10 {
                        if params.message.is_some() && plan_state.send_retries < 1 {
                            plan_state.send_retries += 1;
                            plan_state.confirm_attempts = 0;
                            plan_state.phase = SendMessagePhase::Inputting;
                            return Some(SelectedAction {
                                action: actions::wait_short(),
                                frame: identified.main_window.as_ref().and_then(|m| m.frame.clone()),
                            });
                        }
                        return None;
                    }

                    return Some(SelectedAction {
                        action: actions::wait_short(),
                        frame: identified.main_window.as_ref().and_then(|m| m.frame.clone()),
                    });
                }

                SendMessagePhase::Done => return None,
            }
        }
    }
}
