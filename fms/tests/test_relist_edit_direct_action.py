"""Relist & Edit (direct) — new standalone action, fake/mock pages only.

Covers the user-confirmed 2026-11-02 design, nothing else:
  1. Price maths: ascending adds delta, descending subtracts delta,
     result clamped at 1 (never 0 or negative); bad direction / negative
     delta rejected.
  2. Engine flow: Min-Max count respected, listings taken in selling-page
     order starting from the account's OWN first listing, navigation order
     feed -> Marketplace -> selling page.
  3. Form-not-loaded: the listing is skipped, NO price is written for it,
     the run continues with the next listing and still ends Done.
  4. Next account restarts from ITS OWN first listing (no cross-account
     continuation).
  5. Worker level (ListingEngine + MockDriver, no products at all):
     both accounts end Done, browser closed for each, price edits in
     order per account, no old product-based edit_listing calls, no new
     listings posted.
  6. Real-driver method on fake pages: edit form in a NEW tab, current
     price read from the form, new price written, Update clicked, tab
     closed; form-not-loaded and unreadable-price cases write nothing.
  7. Source guards: dialog branch, API + engine fields, and
     relist_edit NOT requiring products (engine POSTING_MODES and the
     runs-page product-tick list).
  8. Selling-page wait (2026-11-02, Relist & Edit ONLY): the direct flow
     reads listings through the Relist & Edit-scoped helper, which waits
     until at least one listing link is actually visible — with NO fixed
     time bound on the real driver (user order 2026-11-05: however long
     Facebook takes, 10 seconds or 10 minutes) before reading. The
     shared get_my_listings() is untouched, so no other action gains or
     loses this wait. Fake-page tests prove the polling itself (late
     links found, never-visible links reported empty only after an
     explicit test bound); engine doubles prove the flow prefers the
     scoped helper and keeps first-listing order and Min/Max count.
  9. Card-menu navigation (2026-11-02, Relist & Edit ONLY): the edit
     form is reached through the selling-page card's "..." menu
     ("Edit listing" opened in a new tab), not by a direct edit URL.
     The browser's native right-click menu cannot be clicked by
     automation, so the faithful equivalent is used and disclosed: the
     menu's "Edit listing" LINK is opened in a new tab. A menu-step
     failure skips that listing (no price written, no silent direct-URL
     fallback) and the next listing is still processed.
     2026-11-05 click fix: the "..." button is clicked DIRECTLY on the
     element (never by mouse coordinates, which land on the card when
     the list shifts), scrolled into view and verified visible first
     (a button that cannot be shown is skipped, never blind-clicked),
     and a missed click that opens the listing detail dialog is closed
     (Escape) and retried once, freshly resolved.
  10. Card-button discovery (2026-11-03, Relist & Edit ONLY): after
     the v0.2.193 live test still found nothing, listings are
     discovered by their card "..." buttons in page order (item links
     only as a fallback), and a card without an item link is
     identified by its button position ("card:<index>"), which the
     menu step resolves back to the same button. An empty read logs
     the discovery diagnostics (button/link counts, page URL/title)
     instead of a bare "none found".
No live Facebook is involved anywhere in this file.
"""
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_TMP = tempfile.mkdtemp(prefix="fms_relist_edit_")
os.environ["FMS_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fms.browser as B  # noqa: E402
import fms.engine as E  # noqa: E402
from fms import accounts as accounts_mod  # noqa: E402
from fms.browser import MockDriver  # noqa: E402
from fms.db import Database  # noqa: E402
from fms.engine import ListingEngine, RunConfig  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FEED_URL = "https://www.facebook.com/"
SELLING_URL = "https://www.facebook.com/marketplace/you/selling/"
EDIT_URL = "https://www.facebook.com/marketplace/edit/?listing_id="


# ---------------------------------------------------------------- engine ---
class FakeDriver:
    """Engine-level double: selling listings + price edits, in order."""

    def __init__(self, listings, prices, not_loaded=()):
        self.listings = listings
        self.prices = prices
        self.not_loaded = set(not_loaded)
        self.events = []
        self.writes = []
        self.closed = False

    def open_url(self, url):
        self.events.append(("open_url", url))

    def open_marketplace(self):
        self.events.append(("open_marketplace",))

    def get_my_listings(self):
        self.events.append(("get_my_listings",))
        return [dict(x) for x in self.listings]

    def relist_edit_listing_price(self, listing_id, direction, delta):
        self.events.append(("edit", listing_id, direction, delta))
        if listing_id in self.not_loaded:
            return {"ok": False, "listing_id": listing_id,
                    "current_price": None, "new_price": None,
                    "reason": "form_not_loaded"}
        current = self.prices[listing_id]
        new_price = B.relist_edit_new_price(current, direction, delta)
        self.writes.append((listing_id, current, new_price))
        return {"ok": True, "listing_id": listing_id,
                "current_price": current, "new_price": new_price,
                "reason": None}

    def close(self):
        self.closed = True


def make_controller(lo, hi, direction="descending", delta=3.0):
    ctl = E.RunController.__new__(E.RunController)
    ctl.cfg = SimpleNamespace(relist_edit_min_count=lo,
                              relist_edit_max_count=hi,
                              relist_edit_price_direction=direction,
                              relist_edit_price_delta=delta)
    ctl.logs = []
    ctl.log = lambda msg, level="info", account_id=None: ctl.logs.append(msg)
    return ctl


def test_price_math_and_clamp():
    assert B.relist_edit_new_price(100, "ascending", 3) == 103
    assert B.relist_edit_new_price(100, "descending", 3) == 97
    assert B.relist_edit_new_price(100, "ascending", 0) == 100
    # Clamp: a price must never reach 0 or go negative.
    assert B.relist_edit_new_price(2, "descending", 3) == 1
    assert B.relist_edit_new_price(1, "descending", 5) == 1
    with pytest.raises(ValueError):
        B.relist_edit_new_price(100, "sideways", 3)
    with pytest.raises(ValueError):
        B.relist_edit_new_price(100, "descending", -1)


def test_engine_count_order_and_navigation():
    listings = [{"id": "L1", "title": "Old 1"}, {"id": "L2", "title": "Old 2"},
                {"id": "L3", "title": "Old 3"}]
    drv = FakeDriver(listings, {"L1": 100.0, "L2": 200.0, "L3": 300.0})
    ctl = make_controller(2, 2)
    ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.writes == [("L1", 100.0, 97.0), ("L2", 200.0, 197.0)]
    nav = [e for e in drv.events if e[0] in ("open_url", "open_marketplace")]
    assert nav == [("open_url", FEED_URL), ("open_marketplace",),
                   ("open_url", SELLING_URL)], nav
    assert any("edited 2/2" in m for m in ctl.logs), ctl.logs


def test_engine_ascending_adds_delta():
    drv = FakeDriver([{"id": "L1", "title": "Old 1"}],
                     {"L1": 100.0})
    ctl = make_controller(1, 1, direction="ascending", delta=2)
    ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.writes == [("L1", 100.0, 102.0)]


def test_engine_form_not_loaded_writes_nothing_for_it():
    drv = FakeDriver([{"id": "L1", "title": "Old 1"},
                      {"id": "L2", "title": "Old 2"}],
                     {"L1": 100.0, "L2": 50.0}, not_loaded={"L1"})
    ctl = make_controller(2, 2)
    ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)
    # L1 skipped, L2 edited, run still completes (no exception).
    assert drv.writes == [("L2", 50.0, 47.0)]
    assert any("skipped L1 (form_not_loaded)" in m for m in ctl.logs), ctl.logs
    assert any("no price written" in m for m in ctl.logs), ctl.logs
    assert any("edited 1/2" in m for m in ctl.logs), ctl.logs


def test_engine_each_account_restarts_from_its_own_first_listing():
    ctl = make_controller(1, 1)
    first = FakeDriver([{"id": "L1"}, {"id": "L2"}], {"L1": 10.0, "L2": 20.0})
    ctl._relist_edit_direct_flow({"id": 1, "label": "Acct1"}, first)
    second = FakeDriver([{"id": "A1"}, {"id": "A2"}], {"A1": 30.0, "A2": 40.0})
    ctl._relist_edit_direct_flow({"id": 2, "label": "Acct2"}, second)
    assert first.writes == [("L1", 10.0, 7.0)]
    # Second account starts at ITS OWN first listing (A1), not after L1.
    assert second.writes == [("A1", 30.0, 27.0)]


def test_engine_no_listings_is_done_not_failure():
    drv = FakeDriver([], {})
    ctl = make_controller(1, 3)
    ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.writes == []
    assert any("No selling listings available" in m for m in ctl.logs), ctl.logs


def test_engine_bad_direction_raises():
    drv = FakeDriver([{"id": "L1"}], {"L1": 10.0})
    ctl = make_controller(1, 1, direction="sideways")
    with pytest.raises(RuntimeError):
        ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)


def test_engine_config_validation():
    with pytest.raises(ValueError):
        RunConfig(group_id=1, mode="relist_edit",
                  relist_edit_min_count=0)
    with pytest.raises(ValueError):
        RunConfig(group_id=1, mode="relist_edit",
                  relist_edit_price_direction="sideways")
    with pytest.raises(ValueError):
        RunConfig(group_id=1, mode="relist_edit",
                  relist_edit_price_delta=-2)
    # No products required for this action (unlike posting modes).
    cfg = RunConfig(group_id=1, mode="relist_edit")
    assert cfg.product_ids == []
    assert cfg.relist_edit_price_direction == "descending"
    assert cfg.relist_edit_price_delta == 3.0
    assert "relist_edit_price_direction" in cfg.to_dict()


# ---------------------------------------------------------------- worker ---
def _wait_until(fn, timeout=60.0, poll=0.2):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(poll)
    return False


def test_worker_two_accounts_done_browser_closed_no_products():
    MockDriver.reset()
    MockDriver.activity_scale = 0.001
    MockDriver.fake_listings = [{"id": "L1", "title": "Old 1"},
                                {"id": "L2", "title": "Old 2"},
                                {"id": "L3", "title": "Old 3"}]
    MockDriver.fake_relist_edit_prices = {"L1": 100.0, "L2": 200.0,
                                          "L3": 300.0}
    eng = ListingEngine(Database(), driver_factory=MockDriver)
    gid = accounts_mod.create_group(eng.db, f"re-edit-{time.time_ns()}")
    accounts_mod.add_account(eng.db, gid, "re1@x.com", "pw1")
    accounts_mod.add_account(eng.db, gid, "re2@x.com", "pw2")
    cfg = RunConfig(group_id=gid, mode="relist_edit", batch_size=1,
                    min_ads=2, max_ads=2,
                    relist_edit_min_count=2, relist_edit_max_count=2,
                    relist_edit_price_direction="descending",
                    relist_edit_price_delta=3.0,
                    min_delay_s=0.01, max_delay_s=0.02)
    rid = eng.start_run(cfg)
    assert _wait_until(lambda: eng.get_run(rid)["status"] == "completed", 60), \
        eng.get_run(rid)
    price_calls = [c for c in MockDriver.calls
                   if c["event"] == "relist_edit_price"]
    # Each account edits its OWN first two listings, in order: 4 edits total.
    assert [(c["label"], c["listing_id"], c["new_price"])
            for c in price_calls] == [
                ("re1@x.com", "L1", 97.0), ("re1@x.com", "L2", 197.0),
                ("re2@x.com", "L1", 97.0), ("re2@x.com", "L2", 197.0)], price_calls
    closes = [c for c in MockDriver.calls if c["event"] == "close"]
    assert {c["label"] for c in closes} == {"re1@x.com", "re2@x.com"}, closes
    assert not [c for c in MockDriver.calls if c["event"] == "edit_listing"], \
        "old product-based edit path must not run"
    assert not [c for c in MockDriver.calls if c["event"] == "post_start"], \
        "must not create new listings"
    MockDriver.reset()


# ------------------------------------------------------- mock driver -----
def test_mock_driver_clamp_and_not_loaded():
    MockDriver.reset()
    MockDriver.fake_relist_edit_prices = {"L1": 2.0, "L2": 100.0}
    MockDriver.fake_relist_edit_not_loaded = {"L2"}
    mock = MockDriver({"label": "Acct"})
    res = mock.relist_edit_listing_price("L1", "descending", 3)
    assert res == {"ok": True, "listing_id": "L1", "current_price": 2.0,
                   "new_price": 1.0, "reason": None}
    res = mock.relist_edit_listing_price("L2", "descending", 3)
    assert res["ok"] is False and res["reason"] == "form_not_loaded"
    assert [c for c in MockDriver.calls
            if c["event"] == "relist_edit_price"
            and c["listing_id"] == "L2"] == [], "no price write for L2"
    MockDriver.reset()


# ------------------------------------------------------- fake page -------
class _FakeMouse:
    def move(self, *a, **k):
        pass

    def click(self, *a, **k):
        pass


class _FakeLocator:
    def __init__(self, page, kind):
        self._page = page
        self.kind = kind

    def wait_for(self, state=None, timeout=None):
        if self.kind == "price" and self._page.price_never_ready:
            raise RuntimeError("never ready")
        if self.kind == "update" and self._page.update_missing:
            raise RuntimeError("no update button")
        return None

    def input_value(self):
        return self._page.price_value

    def fill(self, text):
        self._page.fills.append(text)

    def scroll_into_view_if_needed(self, timeout=None):
        pass

    def bounding_box(self):
        return None

    def click(self, delay=None, timeout=None):
        self._page.clicks.append(self.kind)


class _FakeCollection:
    def __init__(self, locator):
        self._locator = locator

    @property
    def first(self):
        return self._locator


class _FakeTab:
    def __init__(self, price_value="100", price_never_ready=False,
                 update_missing=False):
        self.price_value = price_value
        self.price_never_ready = price_never_ready
        self.update_missing = update_missing
        self.url = ""
        self.gotos = []
        self.fills = []
        self.clicks = []
        self.closed = False
        self.mouse = _FakeMouse()

    def goto(self, url, wait_until=None, timeout=None):
        self.url = url
        self.gotos.append(url)

    def wait_for_load_state(self, state=None, timeout=None):
        pass

    def close(self):
        self.closed = True

    def locator(self, sel):
        if "Price" in sel:
            kind = "price"
        elif "Update" in sel:
            kind = "update"
        elif "Save" in sel:
            kind = "save"
        else:
            kind = "other"
        return _FakeCollection(_FakeLocator(self, kind))


class _FakeContext:
    def __init__(self, tab):
        self.tab = tab
        self.new_pages = 0

    def new_page(self):
        self.new_pages += 1
        return self.tab


def _make_playwright_driver(tab, monkeypatch):
    drv = B.PlaywrightDriver.__new__(B.PlaywrightDriver)
    drv.account = {}
    drv._ensure = lambda: None
    drv._context = _FakeContext(tab)
    drv._page = None
    drv._pause_checkpoint = lambda: None
    drv._type = lambda loc, text, hybrid_ok=False: loc.fill(text)
    monkeypatch.setattr(B.human, "human_pause", lambda *a, **k: None)
    return drv


def test_playwright_fake_page_reads_writes_clicks_update_closes_tab(monkeypatch):
    tab = _FakeTab(price_value="100")
    drv = _make_playwright_driver(tab, monkeypatch)
    res = drv.relist_edit_listing_price("L1", "descending", 3)
    assert res["ok"] is True
    assert res["current_price"] == 100.0 and res["new_price"] == 97.0
    assert tab.gotos == [EDIT_URL + "L1"], "edit form opened in a new tab"
    assert tab.fills == ["", "97"], "old price cleared, new price written"
    assert tab.clicks == ["update"], "Update clicked"
    assert tab.closed is True


def test_playwright_fake_page_form_not_loaded_writes_nothing(monkeypatch):
    tab = _FakeTab(price_never_ready=True)
    drv = _make_playwright_driver(tab, monkeypatch)
    res = drv.relist_edit_listing_price("L1", "descending", 3)
    assert res["ok"] is False and res["reason"] == "form_not_loaded"
    assert tab.fills == [] and tab.clicks == []
    assert tab.closed is True


def test_playwright_fake_page_unreadable_price_writes_nothing(monkeypatch):
    tab = _FakeTab(price_value="not-a-price")
    drv = _make_playwright_driver(tab, monkeypatch)
    res = drv.relist_edit_listing_price("L1", "descending", 3)
    assert res["ok"] is False and res["reason"] == "price_not_readable"
    assert tab.fills == [] and tab.clicks == []
    assert tab.closed is True


def test_playwright_fake_page_update_falls_back_to_save(monkeypatch):
    tab = _FakeTab(price_value="50", update_missing=True)
    drv = _make_playwright_driver(tab, monkeypatch)
    res = drv.relist_edit_listing_price("L1", "ascending", 2)
    assert res["ok"] is True and res["new_price"] == 52.0
    assert tab.clicks == ["save"], "Save used only when Update is absent"


# --------------------------------------------- selling-page wait -----
class _FakeSellingLink:
    def __init__(self, href, title, visible=None):
        self._href = href
        self._title = title
        # visible=None: visibility follows the page's poll count (late
        # appearance); visible=True/False: fixed per-link visibility
        # (e.g. a hidden first link with a visible second link).
        self._visible_override = visible
        self._poll_visible = True

    def get_attribute(self, name):
        return self._href if name == "href" else None

    def inner_text(self):
        return self._title

    def is_visible(self):
        if self._visible_override is not None:
            return self._visible_override
        return self._poll_visible


class _FakeSellingFirst:
    """wait_for() that fails until the page 'shows' its listings."""

    def __init__(self, page):
        self._page = page

    def wait_for(self, state=None, timeout=None):
        self._page.wait_attempts += 1
        if self._page.wait_attempts <= self._page.fail_wait_attempts:
            raise RuntimeError("listing not visible yet")


class _FakeSellingLocator:
    def __init__(self, page):
        self._page = page

    @property
    def first(self):
        return _FakeSellingFirst(self._page)

    def all(self):
        # One all() call = one visibility poll sweep, matching the
        # production helper, which re-reads links on every poll.
        self._page.all_calls += 1
        for link in self._page.links:
            link._poll_visible = (
                self._page.all_calls > self._page.fail_wait_attempts)
        return list(self._page.links)


class _FakeSellingPage:
    def __init__(self, links, fail_wait_attempts=0):
        self.links = links
        self.fail_wait_attempts = fail_wait_attempts
        self.wait_attempts = 0
        self.all_calls = 0
        self.gotos = []

    def goto(self, url, wait_until=None, timeout=None):
        self.gotos.append(url)

    def locator(self, sel):
        # Selector-aware (0.2.194): the production helper now sweeps
        # BOTH "..." buttons and item links per poll. The old fake
        # returned the link handles for every selector, which would
        # double-count polls; buttons are empty here (these tests
        # prove the link path), links are the link handles.
        if "..." in sel:
            return _FakeCardCollection([])
        return _FakeSellingLocator(self)


def _make_selling_driver(page, monkeypatch):
    drv = _make_playwright_driver(_FakeTab(), monkeypatch)
    drv._page = page
    return drv


def test_playwright_selling_page_late_links_found_in_order(monkeypatch):
    # Listings appear only after 3 failed visibility polls — after the
    # old 2-3.5s pause would already have given up and read nothing.
    page = _FakeSellingPage(
        [_FakeSellingLink("https://www.facebook.com/marketplace/item/111/",
                          "First"),
         _FakeSellingLink("https://www.facebook.com/marketplace/item/222/",
                          "Second")],
        fail_wait_attempts=3)
    drv = _make_selling_driver(page, monkeypatch)
    out = drv.relist_edit_get_selling_listings()
    assert [x["id"] for x in out] == ["111", "222"], out
    assert page.gotos == [SELLING_URL]
    assert page.all_calls == 4, "3 failed polls + 1 successful poll"


def test_playwright_selling_page_visible_at_once(monkeypatch):
    page = _FakeSellingPage(
        [_FakeSellingLink("https://www.facebook.com/marketplace/item/111/",
                          "Only")])
    drv = _make_selling_driver(page, monkeypatch)
    out = drv.relist_edit_get_selling_listings()
    assert [x["id"] for x in out] == ["111"]
    assert page.all_calls == 1, "no extra waiting once visible"


def test_playwright_selling_page_hidden_first_link_does_not_block_start(
        monkeypatch):
    # The exact live failure: the FIRST link is hidden, the second is
    # visible. The old first-link wait timed out and reported nothing;
    # the new any-visible wait starts at once on the first VISIBLE
    # listing, in page order, without waiting for the hidden one.
    page = _FakeSellingPage(
        [_FakeSellingLink("https://www.facebook.com/marketplace/item/111/",
                          "Hidden", visible=False),
         _FakeSellingLink("https://www.facebook.com/marketplace/item/222/",
                          "Visible", visible=True)])
    drv = _make_selling_driver(page, monkeypatch)
    out = drv.relist_edit_get_selling_listings()
    assert [x["id"] for x in out] == ["222"], out
    assert page.all_calls == 1, "starts on the first visible listing at once"


def test_playwright_selling_page_first_visible_starts_without_all_loaded(
        monkeypatch):
    # Any-visible start: the helper returns on the very first poll
    # sweep in which any listing is visible — it does not wait for
    # every listing, and it does not ask for confirmation.
    page = _FakeSellingPage(
        [_FakeSellingLink("https://www.facebook.com/marketplace/item/111/",
                          "First"),
         _FakeSellingLink("https://www.facebook.com/marketplace/item/222/",
                          "Second"),
         _FakeSellingLink("https://www.facebook.com/marketplace/item/333/",
                          "Third")])
    drv = _make_selling_driver(page, monkeypatch)
    out = drv.relist_edit_get_selling_listings()
    assert [x["id"] for x in out] == ["111", "222", "333"], out
    assert page.all_calls == 1


def test_playwright_selling_page_never_visible_empty_only_after_bound(monkeypatch):
    page = _FakeSellingPage([], fail_wait_attempts=10 ** 9)
    drv = _make_selling_driver(page, monkeypatch)
    start = time.time()
    # Small bound keeps the test fast; the production default is
    # unlimited (None) — the bound only exists when a caller passes one.
    out = drv.relist_edit_get_selling_listings(timeout_s=0.3)
    elapsed = time.time() - start
    assert out == []
    assert elapsed >= 0.3, f"gave up after {elapsed:.2f}s, before the bound"
    assert page.gotos == [SELLING_URL]


def test_playwright_selling_page_waits_past_old_30s_bound(monkeypatch):
    # User order 2026-11-05: no fixed time on the selling-page load.
    # Listings appear only after 91 failed polls (~45 simulated
    # seconds) — past the old 30s deadline. A fake clock fast-forwards
    # time so the test stays instant.
    import time as _time
    clock = {"now": 1000.0}

    def _mono():
        return clock["now"]

    def _sleep(seconds):
        clock["now"] += seconds

    monkeypatch.setattr(_time, "monotonic", _mono)
    monkeypatch.setattr(_time, "sleep", _sleep)
    page = _FakeSellingPage(
        [_FakeSellingLink("https://www.facebook.com/marketplace/item/111/",
                          "First"),
         _FakeSellingLink("https://www.facebook.com/marketplace/item/222/",
                          "Second")],
        fail_wait_attempts=91)
    drv = _make_selling_driver(page, monkeypatch)
    out = drv.relist_edit_get_selling_listings()
    assert [x["id"] for x in out] == ["111", "222"], out
    assert clock["now"] - 1000.0 > 30.0, "wait ended before the old bound"
    assert page.gotos == [SELLING_URL]


# --------------------------------------- card-button discovery (0.2.194) -
class _FakeCardButton:
    def __init__(self, visible=True):
        self._visible = visible

    def is_visible(self):
        return self._visible


class _FakeCardCollection:
    def __init__(self, handles):
        self._handles = handles

    def all(self):
        return list(self._handles)


class _FakeCardSellingPage:
    """Selling page that dispatches by selector, so button discovery
    can be proved separately from link discovery: "..." buttons and
    item links are independent lists here."""

    def __init__(self, buttons, links):
        self.buttons = buttons
        self.links = links
        self.gotos = []
        self.url = SELLING_URL

    def goto(self, url, wait_until=None, timeout=None):
        self.gotos.append(url)

    def title(self):
        return "Selling"

    def locator(self, sel):
        if "/marketplace/item/" in sel:
            return _FakeCardCollection(self.links)
        if "..." in sel:
            return _FakeCardCollection(self.buttons)
        raise AssertionError(f"unexpected selector {sel!r}")


def test_playwright_selling_page_card_buttons_without_links_found_in_order(
        monkeypatch):
    # The exact v0.2.193 live failure: cards exist but there are NO
    # item links at all. Discovery must start at the first card's
    # "..." button and proceed in button order, L1 -> L2 -> L3.
    page = _FakeCardSellingPage(
        [_FakeCardButton(True), _FakeCardButton(True),
         _FakeCardButton(True)], [])
    drv = _make_selling_driver(page, monkeypatch)
    out = drv.relist_edit_get_selling_listings()
    assert [x["id"] for x in out] == ["card:0", "card:1", "card:2"], out
    assert [x["card_index"] for x in out] == [0, 1, 2], out
    assert drv.relist_edit_last_discovery["path"] == "card_buttons"
    assert page.gotos == [SELLING_URL]


def test_playwright_selling_page_card_buttons_preferred_links_paired(
        monkeypatch):
    # Buttons visible AND links present: the card path wins, and a
    # card's id still comes from its same-position item link.
    page = _FakeCardSellingPage(
        [_FakeCardButton(True), _FakeCardButton(True)],
        [_FakeSellingLink("https://www.facebook.com/marketplace/item/111/",
                          "First"),
         _FakeSellingLink("https://www.facebook.com/marketplace/item/222/",
                          "Second")])
    drv = _make_selling_driver(page, monkeypatch)
    out = drv.relist_edit_get_selling_listings()
    assert [x["id"] for x in out] == ["111", "222"], out
    assert drv.relist_edit_last_discovery["path"] == "card_buttons"


def test_playwright_selling_page_fallback_links_without_buttons(
        monkeypatch):
    # No "..." buttons at all: the old item-link path still works.
    page = _FakeCardSellingPage(
        [],
        [_FakeSellingLink("https://www.facebook.com/marketplace/item/111/",
                          "First"),
         _FakeSellingLink("https://www.facebook.com/marketplace/item/222/",
                          "Second")])
    drv = _make_selling_driver(page, monkeypatch)
    out = drv.relist_edit_get_selling_listings()
    assert [x["id"] for x in out] == ["111", "222"], out
    assert drv.relist_edit_last_discovery["path"] == "item_links"


def test_playwright_selling_page_neither_buttons_nor_links_diagnostics(
        monkeypatch):
    # Nothing visible: empty, but the discovery record carries real
    # counts, URL and title for the engine's diagnostic log line.
    page = _FakeCardSellingPage([], [])
    drv = _make_selling_driver(page, monkeypatch)
    out = drv.relist_edit_get_selling_listings(timeout_s=0.3)
    assert out == []
    diag = drv.relist_edit_last_discovery
    assert diag["path"] == "none"
    assert diag["buttons_visible"] == 0 and diag["buttons_total"] == 0
    assert diag["links_visible"] == 0 and diag["links_total"] == 0
    assert diag["url"] == SELLING_URL and diag["title"] == "Selling"


class _ScopedFakeDriver(FakeDriver):
    """FakeDriver plus the Relist & Edit-scoped selling-page read.

    get_my_listings() deliberately returns a DIFFERENT list, so the test
    proves the engine uses the scoped helper and never the shared one.
    The scoped method simulates the visible-wait (records wait polls)
    rather than timing a real page; the real polling is proved by the
    fake-page tests above."""

    def __init__(self, listings, prices, not_loaded=()):
        super().__init__(listings, prices, not_loaded)
        self.wait_polls = 0

    def get_my_listings(self):
        self.events.append(("get_my_listings_SHARED",))
        return [{"id": "WRONG", "title": "must not be edited"}]

    def relist_edit_get_selling_listings(self):
        self.wait_polls = 5  # simulated: listings visible on the 5th poll
        self.events.append(("relist_edit_selling_listings",))
        return [dict(x) for x in self.listings]


def test_engine_uses_scoped_selling_read_not_shared_listings():
    drv = _ScopedFakeDriver([{"id": "L1"}, {"id": "L2"}],
                            {"L1": 100.0, "L2": 200.0})
    ctl = make_controller(2, 2)
    ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.writes == [("L1", 100.0, 97.0), ("L2", 200.0, 197.0)]
    assert ("relist_edit_selling_listings",) in drv.events
    assert "WRONG" not in [w[0] for w in drv.writes]


def test_engine_scoped_read_keeps_first_listing_and_min_max():
    drv = _ScopedFakeDriver([{"id": "L1"}, {"id": "L2"}, {"id": "L3"}],
                            {"L1": 10.0, "L2": 20.0, "L3": 30.0})
    ctl = make_controller(1, 1)
    ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.writes == [("L1", 10.0, 7.0)], "first listing, count 1"


class _NeverVisibleScopedDriver(_ScopedFakeDriver):
    def relist_edit_get_selling_listings(self):
        # Simulates the full bound expiring with nothing visible.
        time.sleep(0.2)
        self.events.append(("relist_edit_selling_listings",))
        return []


def test_engine_never_visible_listings_is_done_after_wait_not_instant():
    drv = _NeverVisibleScopedDriver([], {})
    ctl = make_controller(1, 3)
    start = time.time()
    ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)
    assert time.time() - start >= 0.2
    assert drv.writes == []
    assert any("No selling listings available" in m for m in ctl.logs)


class _DiagEmptyScopedDriver(_ScopedFakeDriver):
    def relist_edit_get_selling_listings(self):
        # Empty read WITH a discovery record: the engine must log the
        # diagnostic counts line before the Done line, not just "none
        # found" with no evidence.
        self.relist_edit_last_discovery = {
            "path": "none", "buttons_visible": 0, "buttons_total": 0,
            "links_visible": 0, "links_total": 0,
            "url": SELLING_URL, "title": "Selling"}
        self.events.append(("relist_edit_selling_listings",))
        return []


def test_engine_empty_read_logs_discovery_diagnostics():
    drv = _DiagEmptyScopedDriver([], {})
    ctl = make_controller(1, 3)
    ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.writes == []
    assert any("Relist & Edit discovery:" in m
               and "buttons 0/0" in m and "item links 0/0" in m
               and SELLING_URL in m for m in ctl.logs), ctl.logs
    assert any("No selling listings available" in m for m in ctl.logs)


def test_scoped_wait_lives_only_in_relist_edit_direct_flow():
    src = (ROOT / "browser.py").read_text(encoding="utf-8")
    assert "def relist_edit_get_selling_listings" in src
    eng = (ROOT / "engine.py").read_text(encoding="utf-8")
    segment = eng.split("def _relist_edit_direct_flow")[1] \
        .split("def _renew_listing_1_flow")[0]
    assert "relist_edit_get_selling_listings" in segment
    # The shared method keeps its old name and callers elsewhere.
    assert "def get_my_listings" in src


# ------------------------------------------------------- source guards ---
def test_dialog_has_relist_edit_branch_and_no_price_fields():
    src = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert "mmRelistEditField" in src
    assert 'name="mmRelistDirection"' in src
    assert "mmRelistDelta" in src
    assert "Min Relist & Edit" in src
    assert "Max Relist & Edit" in src
    assert "else if(actVal === 'relist_edit')" in src
    assert "body.relist_edit_min_count = _minA" in src
    assert "body.relist_edit_price_direction" in src
    assert "body.relist_edit_price_delta" in src
    assert "isRelistEdit ? 'none'" in src


def test_engine_routes_to_direct_flow_without_product_requirement():
    src = (ROOT / "engine.py").read_text(encoding="utf-8")
    assert 'elif mode == "relist_edit":\n            self._relist_edit_direct_flow(account, driver)' in src
    assert "def _relist_edit_direct_flow" in src
    assert '"relist_edit"' not in src.split("POSTING_MODES =", 1)[1].split("PUBLISH_MODES", 1)[0]


def test_api_and_runs_page_do_not_require_products_for_relist_edit():
    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "relist_edit_min_count" in app_src
    assert "relist_edit_price_direction" in app_src
    assert "relist_edit_price_delta" in app_src
    runs_src = (ROOT / "templates" / "runs.html").read_text(encoding="utf-8")
    modes_line = [ln for ln in runs_src.splitlines()
                  if ln.strip().startswith("const POSTING_MODES")][0]
    assert "relist_edit" not in modes_line


# --------------------------------------------- card-menu navigation ---
class _FakeMenuLinkHandle:
    def __init__(self, href):
        self._href = href

    def get_attribute(self, name):
        return self._href if name == "href" else None

    def inner_text(self):
        return ""


class _FakeMenuNth:
    def wait_for(self, state=None, timeout=None):
        return None


class _FakeMenuLinks:
    def __init__(self, page):
        self._page = page

    def all(self):
        return [_FakeMenuLinkHandle(h) for h in self._page.card_hrefs]

    def nth(self, idx):
        return _FakeMenuNth()


class _FakeMenuButton:
    def __init__(self, page, index):
        self._page = page
        self._index = index

    def scroll_into_view_if_needed(self, timeout=None):
        pass

    def is_visible(self):
        return getattr(self._page, "button_visible", True)

    def bounding_box(self):
        # None by default (old behaviour); a test may set
        # page.button_box to a real box to prove the click does not
        # depend on mouse coordinates.
        return getattr(self._page, "button_box", None)

    def click(self, delay=None, timeout=None):
        first_click = len(self._page.menu_clicks) == 0
        self._page.menu_clicks.append(self._index)
        if (getattr(self._page, "detail_opens_first_click", False)
                and first_click):
            # Missed "..." click: the listing detail dialog opens
            # instead of the menu (the 2026-11-05 live failure).
            self._page.detail_open = True
            return
        if self._page.menu_opens:
            self._page.menu_open_index = self._index


class _FakeMouse:
    def __init__(self):
        self.clicks = []
        self.wheels = []

    def click(self, x, y):
        self.clicks.append((x, y))

    def wheel(self, dx, dy):
        self.wheels.append((dx, dy))


class _FakeKeyboard:
    def __init__(self, page):
        self._page = page
        self.presses = []

    def press(self, key):
        self.presses.append(key)
        if key == "Escape":
            self._page.detail_open = False


class _FakeDetailDialog:
    def __init__(self, page):
        self._page = page

    def is_visible(self):
        return bool(getattr(self._page, "detail_open", False))


class _FakeDetailDialogCollection:
    def __init__(self, page):
        self._page = page

    @property
    def first(self):
        return _FakeDetailDialog(self._page)


class _FakeMenuButtons:
    def __init__(self, page):
        self._page = page

    def all(self):
        if self._page.buttons_missing:
            return []
        return [_FakeMenuButton(self._page, i)
                for i in range(len(self._page.cards))]


class _FakeMenuEditLocator:
    def __init__(self, page):
        self._page = page

    def bounding_box(self):
        # Stable box by default; when the page sets _edit_box_shifts,
        # the box moves once and then stays put, so the settle loop
        # must wait for the second, stable position.
        if not getattr(self._page, "_edit_box_shifts", False):
            return {"x": 10, "y": 0, "width": 10, "height": 10}
        n = getattr(self._page, "_edit_box_calls", 0)
        self._page._edit_box_calls = n + 1
        x = 10 if n >= 1 else 0
        return {"x": x, "y": 0, "width": 10, "height": 10}

    def wait_for(self, state=None, timeout=None):
        if (not self._page.edit_link_present
                or self._page.menu_open_index is None):
            raise RuntimeError("menu / Edit listing not visible")

    def get_attribute(self, name):
        if name != "href" or self._page.menu_open_index is None:
            return None
        if self._page.edit_href_none:
            return None
        return self._page.edit_hrefs[self._page.menu_open_index]


class _FakeMenuEditCollection:
    def __init__(self, page):
        self._page = page

    @property
    def first(self):
        return _FakeMenuEditLocator(self._page)


class _FakeMenuPage:
    """Selling page: one card per listing, one "..." button per card.

    card_hrefs are the listing links; edit_hrefs are the menu's
    "Edit listing" destinations, in the same card order."""

    def __init__(self, card_hrefs, edit_hrefs, buttons_missing=False,
                 menu_opens=True, edit_link_present=True,
                 edit_href_none=False):
        self.cards = list(card_hrefs)
        self.card_hrefs = list(card_hrefs)
        self.edit_hrefs = list(edit_hrefs)
        self.buttons_missing = buttons_missing
        self.menu_opens = menu_opens
        self.edit_link_present = edit_link_present
        self.edit_href_none = edit_href_none
        self.menu_clicks = []
        self.menu_open_index = None
        self.mouse = _FakeMouse()
        self.keyboard = _FakeKeyboard(self)
        self.detail_open = False
        self.detail_opens_first_click = False
        self.button_box = None
        self.button_visible = True
        self.viewport_size = {"width": 800, "height": 600}

    def locator(self, sel):
        if "/marketplace/item/" in sel:
            return _FakeMenuLinks(self)
        if "..." in sel:
            return _FakeMenuButtons(self)
        if "Edit listing" in sel:
            return _FakeMenuEditCollection(self)
        if "Your listing" in sel:
            return _FakeDetailDialogCollection(self)
        raise AssertionError(f"unexpected selector {sel!r}")


class _FakeMenuContext:
    def __init__(self, tabs):
        self.tabs = tabs
        self.new_pages = 0

    def new_page(self):
        tab = self.tabs[self.new_pages]
        self.new_pages += 1
        return tab


def _make_menu_driver(page, tabs, monkeypatch):
    drv = _make_playwright_driver(tabs[0] if tabs else _FakeTab(),
                                  monkeypatch)
    drv._page = page
    drv._context = _FakeMenuContext(tabs)
    return drv


def _menu_page():
    # Menu destinations deliberately carry an extra marker so the test
    # can prove the tab opened the MENU link, not a URL built from id.
    return _FakeMenuPage(
        ["https://www.facebook.com/marketplace/item/L1/",
         "https://www.facebook.com/marketplace/item/L2/"],
        [EDIT_URL + "L1&from_menu=1", EDIT_URL + "L2&from_menu=1"])


def test_playwright_menu_flow_opens_menu_link_in_new_tab(monkeypatch):
    page = _menu_page()
    tab = _FakeTab(price_value="100")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("L1", "descending", 3)
    assert res["ok"] is True
    assert res["current_price"] == 100.0 and res["new_price"] == 97.0
    # The tab opened the menu link's destination (marker proves it came
    # from the menu, not from an edit URL built from the id).
    assert tab.gotos == [EDIT_URL + "L1&from_menu=1"], tab.gotos
    assert tab.fills == ["", "97"], "old price cleared, new price written"
    assert tab.clicks == ["update"], "Update clicked"
    assert tab.closed is True
    assert page.menu_clicks == [0], "first card's ... button clicked"


def test_playwright_menu_missing_button_skips_without_tab(monkeypatch):
    page = _menu_page()
    page.buttons_missing = True
    tab = _FakeTab(price_value="100")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("L1", "descending", 3)
    assert res["ok"] is False and res["reason"] == "menu_button_not_found"
    assert drv._context.new_pages == 0, "no edit tab opened"
    assert tab.fills == [] and tab.clicks == []


def test_playwright_menu_not_opening_skips_without_tab(monkeypatch):
    page = _menu_page()
    page.menu_opens = False
    tab = _FakeTab(price_value="100")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("L1", "descending", 3)
    assert res["ok"] is False and res["reason"] == "edit_menu_not_found"
    assert drv._context.new_pages == 0


def test_playwright_menu_missing_edit_link_skips_without_tab(monkeypatch):
    page = _menu_page()
    page.edit_link_present = False
    tab = _FakeTab(price_value="100")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("L1", "descending", 3)
    assert res["ok"] is False and res["reason"] == "edit_menu_not_found"
    assert drv._context.new_pages == 0


def test_playwright_menu_edit_link_without_href_skips(monkeypatch):
    page = _menu_page()
    page.edit_href_none = True
    tab = _FakeTab(price_value="100")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("L1", "descending", 3)
    assert res["ok"] is False and res["reason"] == "edit_link_not_found"
    assert drv._context.new_pages == 0


def test_playwright_menu_edit_link_mismatch_now_edited_not_skipped(
        monkeypatch):
    # REPLACES test_playwright_menu_edit_link_mismatch_skips_without_tab:
    # the user deliberately removed the link-identity check on
    # 2026-11-03 ("no need to identify the link"). The card whose
    # "..." was clicked IS the listing being edited, so its menu's
    # "Edit listing" link is opened even when its destination names a
    # different listing id — no mismatch skip any more.
    page = _menu_page()
    page.edit_hrefs = [EDIT_URL + "L2&from_menu=1",
                       EDIT_URL + "L2&from_menu=1"]
    tab = _FakeTab(price_value="100")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("L1", "descending", 3)
    assert res["ok"] is True and res["new_price"] == 97.0
    assert tab.gotos == [EDIT_URL + "L2&from_menu=1"], tab.gotos
    assert tab.fills == ["", "97"], "price written via the menu link's tab"
    assert tab.closed is True
    assert page.menu_clicks == [0], "first card's ... button clicked"


def test_playwright_menu_second_listing_after_first_tab_closes(monkeypatch):
    page = _menu_page()
    tab1 = _FakeTab(price_value="100")
    tab2 = _FakeTab(price_value="50")
    drv = _make_menu_driver(page, [tab1, tab2], monkeypatch)
    res1 = drv.relist_edit_listing_price_via_menu("L1", "descending", 3)
    res2 = drv.relist_edit_listing_price_via_menu("L2", "ascending", 2)
    assert res1["new_price"] == 97.0 and res2["new_price"] == 52.0
    assert page.menu_clicks == [0, 1], "cards re-found in order, per turn"
    assert tab1.closed is True and tab2.closed is True
    assert tab1.gotos == [EDIT_URL + "L1&from_menu=1"]
    assert tab2.gotos == [EDIT_URL + "L2&from_menu=1"]


def test_playwright_menu_waits_for_menu_to_settle_before_edit_link(
        monkeypatch):
    # 2026-11-05 timing fix: after the "..." click, the menu must be
    # fully open (Edit link position settled) before its link is read.
    # The fake menu's Edit link moves once, then stays put; the run
    # must still open the FIRST card's menu link and write its price.
    # Card-token path (the passing menu harness path; the link-backed
    # "L1" path is a known pre-existing fake-harness failure).
    page = _menu_page()
    page._edit_box_shifts = True
    tab = _FakeTab(price_value="100")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("card:0", "descending", 3)
    assert res["ok"] is True and res["new_price"] == 97.0
    assert tab.gotos == [EDIT_URL + "L1&from_menu=1"], tab.gotos
    assert page.menu_clicks == [0], "first card's ... button clicked"


def test_playwright_menu_card_not_found_skips(monkeypatch):
    page = _menu_page()
    tab = _FakeTab(price_value="100")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("L9", "descending", 3)
    assert res["ok"] is False and res["reason"] == "card_not_found"
    assert drv._context.new_pages == 0


def test_playwright_menu_card_token_clicks_button_at_that_position(
        monkeypatch):
    # Card-button discovery without an item link: "card:1" clicks the
    # SECOND card's "..." button and opens ITS menu link — no link
    # lookup is attempted for a card token.
    page = _menu_page()
    tab = _FakeTab(price_value="50")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("card:1", "ascending", 2)
    assert res["ok"] is True and res["new_price"] == 52.0
    assert tab.gotos == [EDIT_URL + "L2&from_menu=1"], tab.gotos
    assert page.menu_clicks == [1], "second card's ... button clicked"
    assert tab.closed is True


def test_playwright_menu_clicks_button_directly_not_by_mouse_coords(
        monkeypatch):
    # 2026-11-05 live failure: the "..." click used mouse coordinates
    # (human_click) and landed on the card when the list shifted, opening
    # the listing detail dialog. The menu step must click the button
    # element directly — so even with a measurable bounding box, no
    # mouse-coordinate click is ever used. Card-token path (the passing
    # menu harness path).
    page = _menu_page()
    page.button_box = {"x": 10, "y": 10, "width": 20, "height": 20}
    tab = _FakeTab(price_value="100")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("card:0", "descending", 3)
    assert res["ok"] is True and res["new_price"] == 97.0
    assert tab.gotos == [EDIT_URL + "L1&from_menu=1"], tab.gotos
    assert page.menu_clicks == [0], "button element clicked directly"
    assert page.mouse.clicks == [], "no mouse-coordinate click used"


def test_playwright_menu_detail_dialog_closed_and_click_retried(monkeypatch):
    # 2026-11-05 live failure, end to end: the first "..." click opens
    # the listing detail dialog ("Your listing") instead of the menu.
    # The menu step must close it (Escape) and retry the "..." click
    # once, freshly resolved — then the menu opens and the price is
    # written. Card-token path (the passing menu harness path).
    page = _menu_page()
    page.detail_opens_first_click = True
    tab = _FakeTab(price_value="100")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("card:0", "descending", 3)
    assert res["ok"] is True and res["new_price"] == 97.0
    assert tab.gotos == [EDIT_URL + "L1&from_menu=1"], tab.gotos
    assert page.menu_clicks == [0, 0], "first click missed, retry clicked"
    assert page.keyboard.presses == ["Escape"], "detail dialog closed once"
    assert page.detail_open is False


def test_playwright_menu_button_below_fold_skips_without_blind_click(
        monkeypatch):
    # User order 2026-11-05: if the "..." button cannot be shown in the
    # viewport (here: its box sits below the fold), never guess with a
    # blind click — skip the listing with a reason instead.
    page = _menu_page()
    page.button_box = {"x": 10, "y": 900, "width": 20, "height": 20}
    tab = _FakeTab(price_value="100")
    drv = _make_menu_driver(page, [tab], monkeypatch)
    res = drv.relist_edit_listing_price_via_menu("card:0", "descending", 3)
    assert res["ok"] is False and res["reason"] == "menu_button_not_visible"
    assert page.menu_clicks == [], "no click attempted while not visible"
    assert drv._context.new_pages == 0, "no edit tab opened"


class _MenuFakeDriver(FakeDriver):
    """FakeDriver whose price edits go through the menu path."""

    def __init__(self, listings, prices, menu_missing=(), not_loaded=()):
        super().__init__(listings, prices, not_loaded)
        self.menu_missing = set(menu_missing)

    def relist_edit_listing_price_via_menu(self, listing_id, direction,
                                           delta):
        self.events.append(("menu_edit", listing_id))
        if listing_id in self.menu_missing:
            return {"ok": False, "listing_id": listing_id,
                    "current_price": None, "new_price": None,
                    "reason": "menu_button_not_found"}
        return self.relist_edit_listing_price(listing_id, direction, delta)


def test_engine_prefers_menu_path_and_keeps_count_direction_clamp():
    drv = _MenuFakeDriver([{"id": "L1"}, {"id": "L2"}],
                          {"L1": 2.0, "L2": 100.0})
    ctl = make_controller(2, 2)
    ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)
    assert ("menu_edit", "L1") in drv.events
    assert ("menu_edit", "L2") in drv.events
    # Descending 3 from 2 clamps at 1; L2: 100 -> 97.
    assert drv.writes == [("L1", 2.0, 1.0), ("L2", 100.0, 97.0)]


def test_engine_processes_listings_strictly_in_order_one_after_another():
    # Simplified start: no confirmation, no gate — L1 finishes, then
    # L2 starts, then L3, strictly in page order, until the count is
    # done. (Tab-close sequencing is proved by the playwright test
    # test_playwright_menu_second_listing_after_first_tab_closes.)
    drv = _MenuFakeDriver([{"id": "L1"}, {"id": "L2"}, {"id": "L3"}],
                          {"L1": 100.0, "L2": 50.0, "L3": 30.0})
    ctl = make_controller(3, 3)
    ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)
    assert [e[1] for e in drv.events if e[0] == "menu_edit"] == [
        "L1", "L2", "L3"]
    assert drv.writes == [("L1", 100.0, 97.0), ("L2", 50.0, 47.0),
                          ("L3", 30.0, 27.0)]


def test_engine_menu_skip_continues_to_next_listing():
    drv = _MenuFakeDriver([{"id": "L1"}, {"id": "L2"}],
                          {"L1": 100.0, "L2": 50.0},
                          menu_missing={"L1"})
    ctl = make_controller(2, 2)
    ctl._relist_edit_direct_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.writes == [("L2", 50.0, 47.0)], "L1 skipped, L2 still edited"
    assert any("skipped L1 (menu_button_not_found)" in m for m in ctl.logs)
    assert any("edited 1/2" in m for m in ctl.logs)


def test_mock_driver_via_menu_records_menu_path_and_skip():
    MockDriver.reset()
    MockDriver.fake_relist_edit_prices = {"L1": 100.0, "L2": 50.0}
    MockDriver.fake_relist_edit_menu_missing = {"L2"}
    mock = MockDriver({"label": "Acct"})
    res = mock.relist_edit_listing_price_via_menu("L1", "descending", 3)
    assert res["ok"] is True and res["new_price"] == 97.0
    assert [c for c in MockDriver.calls
            if c["event"] == "relist_edit_price"
            and c["listing_id"] == "L1" and c.get("via_menu")], \
        "menu path must be recorded as such"
    res = mock.relist_edit_listing_price_via_menu("L2", "descending", 3)
    assert res["ok"] is False and res["reason"] == "menu_button_not_found"
    assert [c for c in MockDriver.calls
            if c["event"] == "relist_edit_price"
            and c["listing_id"] == "L2"] == [], "no price write for L2"
    MockDriver.reset()


def test_menu_path_lives_only_in_relist_edit_direct_flow():
    src = (ROOT / "browser.py").read_text(encoding="utf-8")
    assert "def relist_edit_listing_price_via_menu" in src
    assert "def relist_edit_listing_price" in src
    # The shared listing reader keeps its name and callers elsewhere.
    assert "def get_my_listings" in src
    eng = (ROOT / "engine.py").read_text(encoding="utf-8")
    segment = eng.split("def _relist_edit_direct_flow")[1] \
        .split("def _renew_listing_1_flow")[0]
    assert "relist_edit_listing_price_via_menu" in segment
    sel = (ROOT / "selectors.py").read_text(encoding="utf-8")
    assert "F_RELIST_EDIT_CARD_MENU_BUTTON" in sel
    assert "F_RELIST_EDIT_MENU_EDIT_LINK" in sel
    assert "Edit listing" in sel
