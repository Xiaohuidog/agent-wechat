# Media identity and browser lifecycle

The image helper validates the requested stable chat ID against the current chat
list before navigating. Two chats with the same display name remain ambiguous;
never disable that guard. Accessibility projections at the same visual bounds
are deduplicated, and message bodies are excluded from navigation candidates.

Historical image mode requires a source thumbnail and validates the native
high-resolution cache against the requested file stem. It must never fall back
to copying an arbitrary viewer image or selecting the newest image.

The Finder browser starts on demand. Health polling does not extend its idle
lifetime. After five idle minutes, the helper closes both browser context and
Playwright driver; the persistent profile remains available for the next request.
The single-threaded bridge performs maintenance between requests, and active
requests are protected from idle cleanup.

Run the image/browser regression tests with Python 3.12, Pillow and pytest:

```sh
python -m pytest docker/tools/test_image_download.py docker/tools/test_finder_browser.py -q
```

The media workflow also runs locked Rust tests and builds a Linux amd64 release
on Ubuntu 22.04. Its artifact includes the executable and SHA-256. The workflow
has read-only repository permissions and contains no deployment or message-send
step. A passing build does not establish real WeChat media acceptance.

## 1105改 delivery status

The Linux runtime passed 87 Rust tests and was built in an authorized isolated
container after GitHub Actions remained unavailable. The deployed binary SHA-256
is `0a7a3d9b0cb39c1a37e8d25f537805a6c672072187a4d48590fcc3702271ef62`.
The source runtime is unchanged from `ed68d118c636a570bf5ce4dada205e45315a565e`;
subsequent workflow cleanup changes only CI configuration.

The GroupBot dashboard has verified full playback of two recovered Channels
videos (12.19 and 16.648005 seconds). Four historical images remain unresolved:
the current account has no image decoding key and the extractor has no profile
for the current WeChat build. Three messages have source-MD5-matched encrypted
cache files. Do not mark these messages ready, acknowledge them, or bypass
identity checks to clear the dashboard count.

## 1105 new-image retrieval fix

New image localId 7408 failed before UI retrieval because no exact cache identity
was available. Loading its verified chat created a hardlink entry. The image
locator then overshot viewport edges using a fixed three-wheel step; switching
to one wheel for every search also failed after many newer text messages. The
fix uses coarse search only while no image row is exposed and fine adjustment
once a row is available. Existing source/cache identity checks remain in place.

For a latest image with no cache target, the Agent now prepares only the verified
chat, with account and draft guards, then re-reads the exact cache identity for
up to two seconds. It does not infer a filename. A changed latest image stops
this request. Historical image handling and notification rules are unchanged.

Verification: 37 image-helper tests and 87 Linux Rust tests passed. The recovered
image was opened from its real dashboard card at full 1080x1826 resolution,
583858 bytes. Production binary SHA-256:
`508fd5628201c09a1193d1f99d6cd5b053a2fb1572e32222d1154aa728fa7264`.
The WeChat PID remained unchanged across the Agent binary deployment. Fresh post-deployment acceptance passed at 2026-11-05 10:21 CST:
Group Test record `c5525822dd6e` (localId 274) completed its first Agent attempt
from 10:20:17 to 10:20:22 without manual retries. The same dashboard operation
became ready at 10:20:30, and its fullscreen original decoded at 800x1131,
327607 bytes. Resource SHA-256:
`f09a38c669ef4589a260c715cec5b7265301e62a0a8fcc41b6c049d703338b14`.
This verifies both automatic acquisition and actual dashboard original-image
viewing for the new sample. No recovered resource key was stored; current resource DB decoding
support remains unresolved.
