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
