import importlib.machinery
import importlib.util
import pathlib


MODULE_PATH = pathlib.Path(__file__).with_name("finder-browser")
LOADER = importlib.machinery.SourceFileLoader("finder_browser", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
finder_browser = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(finder_browser)


def test_accepts_only_official_share_pages():
    assert finder_browser.trusted_share_url("https://weixin.qq.com/sph/AbCdEf123")
    assert finder_browser.trusted_share_url(
        "https://channels.weixin.qq.com/finder-preview/pages/sph?id=abc"
    )
    assert finder_browser.trusted_share_url("https://example.com/sph/abc") is None
    assert finder_browser.trusted_share_url("http://weixin.qq.com/sph/abc") is None
    assert finder_browser.trusted_share_url("https://user@weixin.qq.com/sph/abc") is None


def test_resolves_only_success_payloads_without_remote_message():
    assert finder_browser.resolved_share_url(
        {"errCode": 0, "data": {"shortUrl": "https://weixin.qq.com/sph/AbCdEf123"}}
    ) == "https://weixin.qq.com/sph/AbCdEf123"
    assert finder_browser.resolved_share_url(
        {"errCode": 300330, "errMsg": "sensitive remote detail"}
    ) is None
    assert finder_browser.resolved_share_url(
        {"errCode": 0, "data": {"shortUrl": "https://example.com/not-trusted"}}
    ) is None


def test_remote_error_code_requires_integer():
    assert finder_browser.remote_error_code({"errCode": 0}) == 0
    assert finder_browser.remote_error_code({"errcode": 300330}) == 300330
    assert finder_browser.remote_error_code({"errCode": "0"}) is None


def test_show_maps_minimized_browser_before_activation(monkeypatch):
    calls = []
    monkeypatch.setattr(finder_browser.subprocess, "run", lambda command, **kwargs: calls.append(command))
    browser = finder_browser.FinderBrowser.__new__(finder_browser.FinderBrowser)
    browser._page = type("Page", (), {"url": finder_browser.POST_LIST_URL})()
    browser._minimized = True
    browser.status = lambda: "login_required"

    assert browser.show() == "login_required"
    assert calls == [["xdotool", "search", "--class", "chromium", "windowmap", "windowactivate", "%@"]]
    assert browser._minimized is False
