"""Delete Previous — selling-page menu workflow (user brief 2026-11-06).

Same menu workflow as Relist & Edit, except the menu's "Delete listing"
entry is clicked IN PLACE (no new tab) and the delete confirmation
dialog is confirmed. Covers only this action, nothing else:
  1. Real-driver method on fake selling pages: "..." button resolved
     fresh, menu opened, "Delete listing" clicked, confirm dialog
     clicked, dialog closes = deleted. Link-backed ids and card-token
     ids ("card:<index>") both work.
  2. Menu-step failures skip with a reason and delete NOTHING: menu
     never opens, "Delete listing" entry missing, confirm dialog never
     appears. No silent direct-URL fallback (the old delete_listing
     is never called from the menu path).
  3. Menu closed by itself is retried once before skipping; a stale
     menu left open by the previous listing is closed (Escape) before
     this listing's turn, so it can never lend its Delete entry to the
     next listing.
  4. Engine flow: Min-Max delete count respected, listings taken in
     selling-page order starting from the account's OWN first listing,
     navigation order feed -> Marketplace -> selling page; a skipped
     listing does not stop the run and the account still ends Done.
  5. Config + dialog + API guards: only "Min delete" / "Max delete"
     boxes (no price fields, no direction, no delta), the run body
     carries delete_previous_min/max_count, and the mode needs no
     products.
No live Facebook is involved anywhere in this file.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_TMP = tempfile.mkdtemp(prefix="fms_delete_previous_")
os.environ["FMS_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fms.browser as B  # noqa: E402
import fms.engine as E  # noqa: E402
from fms.engine import RunConfig  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FEED_URL = "https://www.facebook.com/"
SELLING_URL = "https://www.facebook.com/marketplace/you/selling/"


# ---------------------------------------------------------------- engine ---
class FakeDriver:
    """Engine-level double: selling listings + menu deletes, in order."""

    def __init__(self, listings, not_deleted=()):
        self.listings = listings
        self.not_deleted = set(not_deleted)
        self.events = []
        self.deletes = []
        self.closed = False
        self.relist_edit_last_discovery = {
            "path": "card_buttons", "buttons_visible": len(listings),
            "buttons_total": len(listings), "links_visible": 0,
            "links_total": 0, "url": SELLING_URL, "title": "Selling"}

    def open_url(self, url):
        self.events.append(("open_url", url))

    def open_marketplace(self):
        self.events.append(("open_marketplace",))

    def get_my_listings(self):
        self.events.append(("get_my_listings",))
        return [dict(x) for x in self.listings]

    def relist_edit_get_selling_listings(self, timeout_s=None):
        self.events.append(("relist_edit_get_selling_listings",))
        return [dict(x) for x in self.listings]

    def delete_previous_listing_via_menu(self, listing_id):
        self.events.append(("delete", listing_id))
        if listing_id in self.not_deleted:
            return {"ok": False, "listing_id": listing_id,
                    "reason": "delete_menu_not_found"}
        self.deletes.append(listing_id)
        return {"ok": True, "listing_id": listing_id, "reason": None}

    def close(self):
        self.closed = True


def make_controller(lo, hi):
    ctl = E.RunController.__new__(E.RunController)
    ctl.cfg = SimpleNamespace(delete_previous_min_count=lo,
                              delete_previous_max_count=hi)
    ctl.logs = []
    ctl.log = lambda msg, level="info", account_id=None: ctl.logs.append(msg)
    ctl.run_id = 1
    ctl.db = _FakeDB()
    return ctl


class _FakeDB:
    """Records _record_deleted inserts (link-backed deletes only)."""

    def __init__(self):
        self.executes = []

    def execute(self, sql, params=()):
        self.executes.append((sql, params))


def test_engine_count_order_and_navigation():
    listings = [{"id": "L1", "title": "Old 1"}, {"id": "L2", "title": "Old 2"},
                {"id": "L3", "title": "Old 3"}]
    drv = FakeDriver(listings)
    ctl = make_controller(2, 2)
    ctl._delete_previous_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.deletes == ["L1", "L2"]
    nav = [e for e in drv.events if e[0] in ("open_url", "open_marketplace")]
    assert nav == [("open_url", FEED_URL), ("open_marketplace",),
                   ("open_url", SELLING_URL)], nav
    assert any("deleted 2/2" in m for m in ctl.logs), ctl.logs


def test_engine_each_account_restarts_from_its_own_first_listing():
    ctl = make_controller(1, 1)
    first = FakeDriver([{"id": "L1"}, {"id": "L2"}])
    ctl._delete_previous_flow({"id": 1, "label": "Acct1"}, first)
    second = FakeDriver([{"id": "A1"}, {"id": "A2"}])
    ctl._delete_previous_flow({"id": 2, "label": "Acct2"}, second)
    assert first.deletes == ["L1"]
    # Second account starts at ITS OWN first listing (A1), not after L1.
    assert second.deletes == ["A1"]


def test_engine_skip_does_not_stop_run():
    drv = FakeDriver([{"id": "L1"}, {"id": "L2"}], not_deleted={"L1"})
    ctl = make_controller(2, 2)
    ctl._delete_previous_flow({"id": 9, "label": "Acct"}, drv)
    # L1 skipped, L2 deleted, run still completes (no exception).
    assert drv.deletes == ["L2"]
    assert any("skipped L1 (delete_menu_not_found)" in m for m in ctl.logs), ctl.logs
    assert any("nothing deleted" in m for m in ctl.logs), ctl.logs
    assert any("deleted 1/2" in m for m in ctl.logs), ctl.logs


def test_engine_no_listings_is_done_not_failure():
    drv = FakeDriver([])
    ctl = make_controller(1, 3)
    ctl._delete_previous_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.deletes == []
    assert any("No selling listings available to delete" in m for m in ctl.logs), ctl.logs


def test_engine_records_link_backed_deletes_in_db():
    drv = FakeDriver([{"id": "L1", "title": "Old 1"},
                      {"id": "L2", "title": "Old 2"}])
    ctl = make_controller(2, 2)
    ctl._delete_previous_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.deletes == ["L1", "L2"]
    recorded = [p[3] for _, p in ctl.db.executes]
    assert recorded == ["L1", "L2"], "each deleted id recorded as deleted"


def test_engine_card_token_deletes_record_nothing():
    drv = FakeDriver([{"id": "card:0"}, {"id": "card:1"}])
    ctl = make_controller(2, 2)
    ctl._delete_previous_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.deletes == ["card:0", "card:1"]
    assert ctl.db.executes == [], "card tokens have no Facebook id to record"


def test_engine_requires_menu_driver():
    class _NoMenuDriver(FakeDriver):
        delete_previous_listing_via_menu = None

    drv = _NoMenuDriver([{"id": "L1"}])
    ctl = make_controller(1, 1)
    ctl._delete_previous_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.deletes == []
    assert any("requires a menu-capable browser driver" in m for m in ctl.logs), ctl.logs


def test_engine_config_validation():
    with pytest.raises(ValueError):
        RunConfig(group_id=1, mode="delete_previous",
                  delete_previous_min_count=0, delete_previous_max_count=3)
    with pytest.raises(ValueError):
        RunConfig(group_id=1, mode="delete_previous",
                  delete_previous_min_count=3, delete_previous_max_count=2)
    cfg = RunConfig(group_id=1, mode="delete_previous",
                    delete_previous_min_count=1, delete_previous_max_count=3)
    assert cfg.delete_previous_min_count == 1
    assert cfg.delete_previous_max_count == 3


def test_engine_routes_to_menu_flow_without_product_requirement():
    assert "delete_previous" in E.MODES
    assert "delete_previous" not in E.POSTING_MODES
    src = (ROOT / "engine.py").read_text(encoding="utf-8")
    assert 'elif mode == "delete_previous":\n            self._delete_previous_flow(account, driver)' in src
    assert "def _delete_previous_flow" in src


def test_dialog_has_only_min_max_delete_and_no_price_fields():
    src = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert "isDeletePrevious" in src
    assert "'Min delete'" in src
    assert "'Max delete'" in src
    assert "else if(actVal === 'delete_previous')" in src
    assert "body.delete_previous_min_count = _minA" in src
    assert "body.delete_previous_max_count = _maxA" in src
    assert "isDeletePrevious ? 'none'" in src


def test_api_carries_delete_previous_counts():
    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "delete_previous_min_count" in app_src
    assert "delete_previous_max_count" in app_src


# ------------------------------------------------------- fake selling page ---
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
            # Escape also closes an open action menu and the delete
            # confirmation dialog — unless the page says Escape does
            # not close the dialog (models a dialog that stays up).
            self._page.menu_open_index = None
            if getattr(self._page, "escape_closes_confirm", True):
                self._page.confirm_open = False


class _FakeMenuLinkHandle:
    def __init__(self, href):
        self._href = href

    def get_attribute(self, name):
        return self._href if name == "href" else None


class _FakeMenuNth:
    def __init__(self, page, index):
        self._page = page
        self._index = index

    def locator(self, sel):
        return _FakeButtonCollection(self._page, self._index)

    def wait_for(self, state=None, timeout=None):
        return None


class _FakeMenuLinks:
    def __init__(self, page):
        self._page = page

    def all(self):
        return [_FakeMenuLinkHandle(h) for h in self._page.card_hrefs]

    def nth(self, idx):
        return _FakeMenuNth(self._page, idx)


class _FakeDeleteButton:
    def __init__(self, page, index):
        self._page = page
        self._index = index

    def scroll_into_view_if_needed(self, timeout=None):
        pass

    def wait_for(self, state=None, timeout=None):
        return None

    def is_visible(self):
        return getattr(self._page, "button_visible", True)

    def bounding_box(self):
        return getattr(self._page, "button_box", None)

    def click(self, delay=None, timeout=None):
        if getattr(self._page, "confirm_open", False):
            # The delete confirmation dialog is a modal overlay: it
            # covers the page, so no "..." button can receive the
            # click (Playwright's actionability check) — the click
            # times out.
            self._page.menu_clicks.append(self._index)
            raise RuntimeError("click timeout: element covered by dialog")
        if getattr(self._page, "detail_open", False):
            # The listing detail dialog is a modal overlay too: it
            # covers the page the same way.
            self._page.menu_clicks.append(self._index)
            raise RuntimeError(
                "click timeout: element covered by detail dialog")
        first_click = len(self._page.menu_clicks) == 0
        self._page.menu_clicks.append(self._index)
        if getattr(self._page, "fail_clicks_first", 0) > 0:
            self._page.fail_clicks_first -= 1
            if getattr(self._page, "fail_clicks_open_menu", False):
                self._page.menu_open_index = self._index
                self._page.menu_card_index = self._index
            raise RuntimeError("click timeout")
        if (getattr(self._page, "detail_opens_first_click", False)
                and first_click):
            # Missed "..." click: the listing detail dialog opens
            # instead of the menu.
            self._page.detail_open = True
            return
        if getattr(self._page, "detail_opens_every_click", False):
            # Every "..." click misses and opens the listing detail
            # instead of the menu (2026-11-06 live run, card:3).
            self._page.detail_open = True
            return
        if self._page.menu_opens:
            self._page.menu_open_index = self._index
            self._page.menu_card_index = self._index


class _FakeButtonCollection:
    def __init__(self, page, index):
        self._page = page
        self._index = index

    def count(self):
        return 1

    @property
    def first(self):
        return _FakeDeleteButton(self._page, self._index)

    def locator(self, sel):
        return self


class _FakeDeleteButtons:
    def __init__(self, page):
        self._page = page

    def all(self):
        if self._page.buttons_missing:
            return []
        return [_FakeDeleteButton(self._page, i)
                for i in range(len(self._page.cards))]


class _FakeDeleteLink:
    def __init__(self, page):
        self._page = page

    def bounding_box(self):
        return {"x": 10, "y": 0, "width": 10, "height": 10}

    def wait_for(self, state=None, timeout=None):
        if getattr(self._page, "close_menu_once_before_wait", False):
            # The menu opened, then closed by itself while Facebook
            # re-rendered the list — the Delete entry is gone this time.
            # One-shot: the retry's wait finds the menu again.
            self._page.close_menu_once_before_wait = False
            self._page.menu_open_index = None
            raise RuntimeError("menu / Delete listing not visible")
        if (not self._page.delete_link_present
                or self._page.menu_open_index is None):
            raise RuntimeError("menu / Delete listing not visible")

    def is_visible(self):
        if (not self._page.delete_link_present
                or self._page.menu_open_index is None):
            return False
        after = getattr(self._page, "delete_visible_after", 0)
        if after > 0:
            self._page.delete_visible_after = after - 1
            return False
        return True

    def click(self, delay=None, timeout=None):
        self._page.delete_clicks.append(self._page.menu_open_index)
        # Clicking a menu entry closes the menu and opens the
        # confirmation dialog.
        self._page.menu_open_index = None
        if self._page.confirm_opens:
            self._page.confirm_open = True


class _FakeDeleteLinkCollection:
    def __init__(self, page):
        self._page = page

    @property
    def first(self):
        return _FakeDeleteLink(self._page)


class _FakeConfirmButton:
    def __init__(self, page):
        self._page = page

    def wait_for(self, state=None, timeout=None):
        if not self._page.confirm_open:
            raise RuntimeError("confirm dialog not visible")

    def is_visible(self):
        return bool(self._page.confirm_open)

    def click(self, delay=None, timeout=None):
        self._page.confirm_clicks.append(True)
        # Confirming deletes the card whose menu was open and closes
        # the dialog (Facebook re-renders the list).
        self._page.confirm_open = False
        idx = self._page.menu_card_index
        if idx is not None and 0 <= idx < len(self._page.cards):
            self._page.deleted.append(self._page.cards.pop(idx))


class _FakeHiddenSubmitButton:
    """An earlier match the confirm selector catches but that is
    never visible — e.g. the search form's submit button at the top
    of the selling page. The dialog is rendered last in <body>, so
    .first locks onto this hidden element and wait_for() times out
    even though the dialog's Delete is right there, visible — the
    0/5 (v0.2.205) and 0/4 (v0.2.206) live runs."""

    def wait_for(self, state=None, timeout=None):
        raise RuntimeError("hidden submit never visible")

    def is_visible(self):
        return False

    def click(self, delay=None, timeout=None):
        raise RuntimeError("hidden submit never visible")


class _FakeConfirmCollection:
    def __init__(self, page):
        self._page = page

    @property
    def first(self):
        if getattr(self._page, "hidden_submit_before_dialog", False):
            return _FakeHiddenSubmitButton()
        return _FakeConfirmButton(self._page)

    def all(self):
        out = []
        if getattr(self._page, "hidden_submit_before_dialog", False):
            out.append(_FakeHiddenSubmitButton())
        out.append(_FakeConfirmButton(self._page))
        return out


class _FakeConfirmMissingButton:
    """Confirm button the selector does NOT match: the dialog may be
    open, but this button is invisible to the lookup — models the
    2026-11-06 live run, where the dialog's Delete was a
    div[role=button] with no aria-label and the old selector missed it."""

    def wait_for(self, state=None, timeout=None):
        raise RuntimeError("confirm dialog not visible")

    def is_visible(self):
        return False

    def click(self, delay=None, timeout=None):
        raise RuntimeError("confirm dialog not visible")


class _FakeConfirmMissingCollection:
    def __init__(self, page):
        self._page = page

    @property
    def first(self):
        return _FakeConfirmMissingButton()

    def all(self):
        return [_FakeConfirmMissingButton()]


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


class _FakeDeletePage:
    """Selling page: one card per listing, one "..." button per card."""

    def __init__(self, card_ids, card_hrefs=None, buttons_missing=False,
                 menu_opens=True, delete_link_present=True,
                 confirm_opens=True, confirm_form="aria_label_div"):
        self.cards = list(card_ids)
        self.card_hrefs = list(card_hrefs or
                               [f"https://www.facebook.com/marketplace/item/{i}/"
                                for i in card_ids])
        self.buttons_missing = buttons_missing
        self.menu_opens = menu_opens
        self.delete_link_present = delete_link_present
        self.confirm_opens = confirm_opens
        # Shape of the dialog's Delete button. "aria_label_div" is the
        # old shape (div[aria-label='Delete'][role='button']).
        # "div_role_button" is the live shape (2026-11-06): a
        # div[role=button] with the text "Delete" and no aria-label,
        # inside [role='dialog'] — only matched when the selector
        # carries the dialog div[role=button] alternative.
        self.confirm_form = confirm_form
        self.menu_clicks = []
        self.delete_clicks = []
        self.confirm_clicks = []
        self.deleted = []
        self.menu_open_index = None
        self.menu_card_index = None
        self.confirm_open = False
        self.mouse = _FakeMouse()
        self.keyboard = _FakeKeyboard(self)
        self.detail_open = False
        self.detail_opens_first_click = False
        self.detail_opens_every_click = False
        self.hidden_submit_before_dialog = False
        self.button_box = None
        self.button_visible = True
        self.viewport_size = {"width": 800, "height": 600}

    def locator(self, sel):
        if "/marketplace/item/" in sel:
            return _FakeMenuLinks(self)
        if "..." in sel:
            return _FakeDeleteButtons(self)
        if "Delete listing" in sel:
            return _FakeDeleteLinkCollection(self)
        if "aria-label='Delete'" in sel:
            if getattr(self, "confirm_form", "aria_label_div") == "div_role_button":
                # Live dialog shape: only the dialog div[role=button]
                # alternative matches this button. Without it the
                # confirm wait times out (delete_confirm_not_found).
                if "[role='dialog'] [role='button']:has-text('Delete')" in sel:
                    return _FakeConfirmCollection(self)
                return _FakeConfirmMissingCollection(self)
            return _FakeConfirmCollection(self)
        if "Your listing" in sel:
            return _FakeDetailDialogCollection(self)
        raise AssertionError(f"unexpected selector {sel!r}")


class _FakeContext:
    def __init__(self):
        self.pages = []


def _make_delete_driver(page, monkeypatch):
    drv = B.PlaywrightDriver.__new__(B.PlaywrightDriver)
    drv.account = {}
    drv._ensure = lambda: None
    drv._context = _FakeContext()
    drv._page = page
    drv._pause_checkpoint = lambda: None
    drv._type = lambda loc, text, hybrid_ok=False: loc.fill(text)
    monkeypatch.setattr(B.human, "human_pause", lambda *a, **k: None)
    return drv


def _delete_page():
    return _FakeDeletePage(["card:0", "card:1"])


# ------------------------------------------------------------ driver tests ---
def test_delete_previous_happy_path_deletes_first_card(monkeypatch):
    page = _delete_page()
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res == {"ok": True, "listing_id": "card:0", "reason": None}
    assert page.deleted == ["card:0"]
    assert page.menu_clicks == [0], "first card's ... button clicked"
    assert page.delete_clicks == [0], "menu's Delete listing clicked"
    assert page.confirm_clicks == [True], "confirm Delete clicked"
    assert page.menu_open_index is None and not page.confirm_open


def test_delete_previous_link_backed_deletes_by_id(monkeypatch):
    page = _FakeDeletePage(["L1", "L2"])
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("L1")
    assert res["ok"] is True
    assert page.deleted == ["L1"]
    assert page.menu_clicks == [0]


def test_delete_previous_menu_not_opening_skips(monkeypatch):
    page = _delete_page()
    page.menu_opens = False
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res["ok"] is False and res["reason"] == "delete_menu_not_found"
    assert page.deleted == []
    assert page.delete_clicks == [] and page.confirm_clicks == []


def test_delete_previous_missing_delete_link_skips(monkeypatch):
    page = _delete_page()
    page.delete_link_present = False
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res["ok"] is False and res["reason"] == "delete_menu_not_found"
    assert page.deleted == []


def test_delete_previous_menu_closed_by_itself_retried(monkeypatch):
    page = _delete_page()
    page.close_menu_once_before_wait = True
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res["ok"] is True
    assert page.deleted == ["card:0"]
    assert page.menu_clicks == [0, 0], "menu retried once, then deleted"


def test_delete_previous_stale_menu_closed_before_turn(monkeypatch):
    page = _delete_page()
    page.menu_open_index = 0  # stale menu from the previous listing
    page.menu_card_index = 0
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:1")
    assert res["ok"] is True
    assert page.deleted == ["card:1"], "this listing deleted, not the stale one"
    assert page.keyboard.presses == ["Escape"], "stale menu closed first"
    assert page.menu_clicks == [1], "only this listing's ... button clicked"


def test_delete_previous_confirm_missing_skips(monkeypatch):
    page = _delete_page()
    page.confirm_opens = False
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res["ok"] is False and res["reason"] == "delete_confirm_not_found"
    assert page.deleted == []
    assert page.delete_clicks == [0], "Delete entry clicked, no confirm came"
    assert page.keyboard.presses == ["Escape"], "open dialog closed on skip"


def test_delete_previous_confirm_div_role_button_in_dialog_deletes(monkeypatch):
    # Live shape (2026-11-06 run, 0/5): the dialog's Delete is a
    # div[role=button] with text "Delete" and no aria-label, inside
    # [role='dialog'] — the v0.2.205 selector missed it on every listing.
    page = _FakeDeletePage(["card:0", "card:1"],
                           confirm_form="div_role_button")
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res == {"ok": True, "listing_id": "card:0", "reason": None}
    assert page.deleted == ["card:0"]
    assert page.confirm_clicks == [True], "dialog div Delete clicked"


def test_delete_previous_click_throws_but_menu_opened_deletes(monkeypatch):
    page = _delete_page()
    page.fail_clicks_first = 1
    page.fail_clicks_open_menu = True
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res["ok"] is True
    assert page.deleted == ["card:0"]
    assert page.menu_clicks == [0], "one click, menu opened despite the throw"


def test_delete_previous_slow_rendering_menu_found(monkeypatch):
    page = _delete_page()
    page.delete_visible_after = 2
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res["ok"] is True
    assert page.deleted == ["card:0"]


def test_delete_previous_stale_confirm_closed_before_turn(monkeypatch):
    page = _delete_page()
    page.confirm_open = True  # stale dialog from the previous listing
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res["ok"] is True
    assert page.deleted == ["card:0"]
    assert page.keyboard.presses == ["Escape"], "stale dialog closed first"
    assert page.menu_clicks == [0], "only this listing's ... button clicked"


def test_delete_previous_confirm_blocking_menu_click_honest_reason(monkeypatch):
    page = _delete_page()
    page.confirm_open = True  # dialog stays up: Escape does not close it
    page.escape_closes_confirm = False
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res["ok"] is False and res["reason"] == "confirm_dialog_open"
    assert page.deleted == []
    assert page.menu_clicks == [0, 0, 0], "three attempts, all blocked"


def test_confirm_selector_covers_dialog_button_form():
    from fms import selectors as S
    sel = S.F_DELETE_PREVIOUS_CONFIRM_BUTTON[1]
    assert "[role='dialog'] button:has-text('Delete')" in sel
    assert "[role='dialog'] [role='button']:has-text('Delete')" in sel
    assert "[role='alertdialog'] [role='button']:has-text('Delete')" in sel
    assert "div[aria-label='Delete'][role='button']" in sel
    src = (ROOT / "browser.py").read_text(encoding="utf-8")
    assert "F_DELETE_PREVIOUS_CONFIRM_BUTTON" in src
    # The old selector is untouched — the other delete flows use it.
    assert "F_CONFIRM_DELETE_BUTTON" in src


def test_delete_previous_detail_dialog_closed_and_retried(monkeypatch):
    page = _delete_page()
    page.detail_opens_first_click = True
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res["ok"] is True
    assert page.deleted == ["card:0"]
    assert "Escape" in page.keyboard.presses
    assert page.menu_clicks == [0, 0], (
        "detail closed and retried inside the menu loop — the "
        "main-flow retry must not be spent on it")
    assert not page.detail_open


def test_delete_previous_confirm_hidden_earlier_match_still_deletes(monkeypatch):
    # 2026-11-06 live runs (0/5 on v0.2.205, 0/4 on v0.2.206): the
    # dialog's Delete is visible, but .first locks onto an earlier
    # hidden match (the search form's submit button) and the visible
    # wait times out. The confirm lookup must take the first VISIBLE
    # match, not the first match.
    page = _delete_page()
    page.hidden_submit_before_dialog = True
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res == {"ok": True, "listing_id": "card:0", "reason": None}
    assert page.deleted == ["card:0"]
    assert page.confirm_clicks == [True], (
        "dialog Delete clicked, not the hidden submit")


def test_delete_previous_detail_always_opening_closes_at_skip(monkeypatch):
    # 2026-11-06 live run (card:3): every "..." click opens the
    # listing detail ("View listing") instead of the menu, and the
    # run left it open on screen. The skip must end with the detail
    # closed, never left open behind the run.
    page = _delete_page()
    page.detail_opens_every_click = True
    drv = _make_delete_driver(page, monkeypatch)
    res = drv.delete_previous_listing_via_menu("card:0")
    assert res["ok"] is False and res["reason"] == "menu_button_not_found"
    assert page.deleted == []
    assert not page.detail_open, "detail must not stay open after the skip"
    assert "Escape" in page.keyboard.presses
