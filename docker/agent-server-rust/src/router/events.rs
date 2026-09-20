use axum::{
    extract::ws::{WebSocket, WebSocketUpgrade},
    response::IntoResponse,
};

pub async fn events_ws(ws: WebSocketUpgrade) -> impl IntoResponse {
    ws.on_upgrade(handle_events_ws)
}

async fn handle_events_ws(mut socket: WebSocket) {
    // Keep connection alive, send events as they come
    // TODO: Wire up to a broadcast channel for real-time events
    loop {
        match socket.recv().await {
            Some(Ok(_)) => continue,
            _ => break,
        }
    }
}
