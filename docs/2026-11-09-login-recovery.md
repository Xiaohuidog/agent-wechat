# Login recovery and authentication observation, 2026-11-09

The production client was logged out while its session still contained an account identifier. A loading QR page could not be identified until QR decoding succeeded. The health monitor consequently terminated the waiting client after its unresponsive timeout. These monitor initiated exits are distinct from an unexpected client crash.

Changes:

- Identify the QR login page from its accessible label and transfer-files button, including while the image is loading. Clear stale QR data unless a fresh official login QR can be decoded.
- Use the existing locked, list-pruned health snapshot for authentication observations. Return unknown when the current UI cannot be identified rather than returning cached login as current. Preserve existing selected-chat context when the observation contains only the chat shell.
- Initialize the restart timer when monitoring starts without a client process. Previously a client absent at startup could remain absent indefinitely.

Validation: all 95 Rust tests passed and the release build passed. Production deployment at 2026-11-09 15:44:53 Asia/Shanghai produced binary SHA256 `749563752b234f7b5f17d012b345bcf080b0ff4fa4679644a5f9cea2f83b7b62`. The client started through the missing-process recovery path. Later observations retained PID 3564064 and reported logged_out / login_qr.

The current login QR still has not loaded. No usable QR was delivered and collection has not been accepted as recovered. Login-site HTTPS connectivity, disabled application proxy and available resources do not establish that the complete client login path works. Two bounded isolated-container probes ended before a usable comparison, with the second reporting exit 101 and no OOM; temporary containers were removed. Production profiles, failed-media history and alerts were preserved. Stop repeated trial changes and require fresh evidence before further environment changes.

Backups and deployment metadata are in `/var/lib/groupbot-app/incident-20261109/`. Recovery still requires a genuine production QR, user scan and phone confirmation, authoritative logged_in for the expected account, real collection/media verification, and natural alert resolution. Tests and short process stability do not prove that third-party client crashes are eliminated.
