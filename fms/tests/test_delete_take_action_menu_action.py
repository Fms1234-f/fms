"""Delete Take Action Listings — selling-page menu workflow (user brief 2026-11-07).

The SAME menu workflow as Delete Previous, except ONLY listings Facebook
flagged with a 'take action' banner ("Confirm your identity to publish
this and any future listings", user photo 2026-11-07) are deleted — one
by one, in selling-page order, until the Min-Max count for this account
is done. Covers only this action, nothing else:
  1. Engine flow: flagged listings only (from get_take_action_listings),
     Min-Max count respected, listings taken in selling-page order
     starting from the account's OWN first flagged listing, navigation
     order feed -> Marketplace -> selling page.
  2. An account with NO flagged listings is marked Done at once
     (browser closed, next account) — not an error, never waits.
  3. A skipped listing does not stop the run and the account still
     ends Done. No silent direct-URL fallback (the old delete_listing
     is never called from the menu path).
  4. Config + dialog + API guards: only "Min delete take action
     listings" / "Max delete take action listings" boxes (no price
     fields, no direction, no delta), the run body carries
     delete_take_action_min/max_count, and the mode needs no products.
No live Facebook is involved anywhere in this file.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_TMP = tempfile.mkdtemp(prefix="fms_delete_take_action_")
os.environ["FMS_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fms.browser as B  # noqa: E402
import fms.engine as E  # noqa: E402
from fms import selectors as S  # noqa: E402
from fms.engine import RunConfig  # noqa: E402
from fms.selectors import F_TAKE_ACTION_BADGE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FEED_URL = "https://www.facebook.com/"
SELLING_URL = "https://www.facebook.com/marketplace/you/selling/"


# ---------------------------------------------------------------- engine ---
class FakeDriver:
    """Engine-level double: flagged listings + menu deletes, in order."""

    def __init__(self, flagged, not_deleted=()):
        self.flagged = flagged
        self.not_deleted = set(not_deleted)
        self.events = []
        self.deletes = []
        self.closed = False

    def open_url(self, url):
        self.events.append(("open_url", url))

    def open_marketplace(self):
        self.events.append(("open_marketplace",))

    def get_take_action_listings(self):
        self.events.append(("get_take_action_listings",))
        return [dict(x) for x in self.flagged]

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
    ctl.cfg = SimpleNamespace(delete_take_action_min_count=lo,
                              delete_take_action_max_count=hi)
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


def test_engine_deletes_only_flagged_in_order_and_navigation():
    flagged = [{"id": "F1", "title": "Flagged 1"},
               {"id": "F2", "title": "Flagged 2"},
               {"id": "F3", "title": "Flagged 3"}]
    drv = FakeDriver(flagged)
    ctl = make_controller(2, 2)
    ctl._delete_take_action_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.deletes == ["F1", "F2"]
    nav = [e for e in drv.events if e[0] in ("open_url", "open_marketplace")]
    assert nav == [("open_url", FEED_URL), ("open_marketplace",),
                   ("open_url", SELLING_URL)], nav
    assert ("get_take_action_listings",) in drv.events
    assert any("deleted 2/2" in m for m in ctl.logs), ctl.logs


def test_engine_each_account_restarts_from_its_own_first_flagged():
    ctl = make_controller(1, 1)
    first = FakeDriver([{"id": "F1"}, {"id": "F2"}])
    ctl._delete_take_action_flow({"id": 1, "label": "Acct1"}, first)
    second = FakeDriver([{"id": "G1"}, {"id": "G2"}])
    ctl._delete_take_action_flow({"id": 2, "label": "Acct2"}, second)
    assert first.deletes == ["F1"]
    # Second account starts at ITS OWN first flagged listing (G1).
    assert second.deletes == ["G1"]


def test_engine_skip_does_not_stop_run():
    drv = FakeDriver([{"id": "F1"}, {"id": "F2"}], not_deleted={"F1"})
    ctl = make_controller(2, 2)
    ctl._delete_take_action_flow({"id": 9, "label": "Acct"}, drv)
    # F1 skipped, F2 deleted, run still completes (no exception).
    assert drv.deletes == ["F2"]
    assert any("skipped F1 (delete_menu_not_found)" in m for m in ctl.logs), ctl.logs
    assert any("nothing deleted" in m for m in ctl.logs), ctl.logs
    assert any("deleted 1/2" in m for m in ctl.logs), ctl.logs


def test_engine_no_flagged_is_done_not_failure():
    drv = FakeDriver([])
    ctl = make_controller(1, 3)
    ctl._delete_take_action_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.deletes == []
    assert any("No 'take action' listings available to delete" in m for m in ctl.logs), ctl.logs


def test_engine_count_clamped_when_fewer_flagged_than_want():
    drv = FakeDriver([{"id": "F1"}, {"id": "F2"}])
    ctl = make_controller(3, 3)
    ctl._delete_take_action_flow({"id": 9, "label": "Acct"}, drv)
    # Only 2 flagged exist; both deleted, run ends Done (no error).
    assert drv.deletes == ["F1", "F2"]
    assert any("deleted 2/2" in m for m in ctl.logs), ctl.logs


def test_engine_records_link_backed_deletes_in_db():
    drv = FakeDriver([{"id": "F1", "title": "Flagged 1"},
                      {"id": "F2", "title": "Flagged 2"}])
    ctl = make_controller(2, 2)
    ctl._delete_take_action_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.deletes == ["F1", "F2"]
    recorded = [p[3] for _, p in ctl.db.executes]
    assert recorded == ["F1", "F2"], "each deleted id recorded as deleted"


def test_engine_requires_menu_driver():
    class _NoMenuDriver(FakeDriver):
        delete_previous_listing_via_menu = None

    drv = _NoMenuDriver([{"id": "F1"}])
    ctl = make_controller(1, 1)
    ctl._delete_take_action_flow({"id": 9, "label": "Acct"}, drv)
    assert drv.deletes == []
    assert any("requires a menu-capable browser driver" in m for m in ctl.logs), ctl.logs


def test_engine_config_validation():
    with pytest.raises(ValueError):
        RunConfig(group_id=1, mode="delete_take_action",
                  delete_take_action_min_count=0, delete_take_action_max_count=3)
    with pytest.raises(ValueError):
        RunConfig(group_id=1, mode="delete_take_action",
                  delete_take_action_min_count=3, delete_take_action_max_count=2)
    cfg = RunConfig(group_id=1, mode="delete_take_action",
                    delete_take_action_min_count=1, delete_take_action_max_count=3)
    assert cfg.delete_take_action_min_count == 1
    assert cfg.delete_take_action_max_count == 3


def test_engine_routes_to_menu_flow_without_product_requirement():
    assert "delete_take_action" in E.MODES
    assert "delete_take_action" not in E.POSTING_MODES
    src = (ROOT / "engine.py").read_text(encoding="utf-8")
    assert 'elif mode == "delete_take_action":\n            self._delete_take_action_flow(account, driver)' in src
    assert "def _delete_take_action_flow" in src
    # The old direct delete is gone from the standalone flow: no
    # delete_listing call inside _delete_take_action_flow.
    start = src.index("    def _delete_take_action_flow")
    nxt = src.index("\n    def ", start + 10)
    assert "delete_listing(" not in src[start:nxt]


def test_dialog_has_only_min_max_delete_take_action_and_no_price_fields():
    src = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert "isDeleteTakeAction" in src
    assert "'Min delete take action listings'" in src
    assert "'Max delete take action listings'" in src
    assert "else if(actVal === 'delete_take_action')" in src
    assert "body.delete_take_action_min_count = _minA" in src
    assert "body.delete_take_action_max_count = _maxA" in src
    assert "isDeleteTakeAction ? 'none'" in src


def test_api_carries_delete_take_action_counts():
    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "delete_take_action_min_count" in app_src
    assert "delete_take_action_max_count" in app_src


def test_badge_selector_matches_identity_banner():
    # The flag's visible banner reads "Confirm your identity to publish
    # this and any future listings" (user photo 2026-11-07) — the
    # discovery selector must match that text, not only "Take action".
    assert "Confirm your identity" in F_TAKE_ACTION_BADGE[1]
    assert "Take action" in F_TAKE_ACTION_BADGE[1]


# ------------------------------------------------------- fake selling page ---
class _FakeLinkHandle:
    """An item link whose visibility flips on after N polls."""

    def __init__(self, page):
        self.page = page

    def is_visible(self):
        self.page.polls += 1
        if self.page.polls > self.page.max_polls:
            raise AssertionError("waited too long for a visible listing")
        return self.page.polls >= self.page.visible_after


class _FakeLinksCollection:
    def __init__(self, page):
        self.page = page

    def all(self):
        return [_FakeLinkHandle(self.page) for _ in self.page.link_ids]


class _FakeBadge:
    """A 'take action' banner on one card."""

    def __init__(self, listing_id):
        self.listing_id = listing_id

    def locator(self, sel):
        return _FakeCardLink(self.listing_id)


class _FakeCardLink:
    def __init__(self, listing_id):
        self.listing_id = listing_id
        self.first = self

    def get_attribute(self, name):
        return f"https://www.facebook.com/marketplace/item/{self.listing_id}/"

    def inner_text(self):
        return f"TITLE {self.listing_id} £2"


class _FakeBadgeCollection:
    def __init__(self, page):
        self.page = page

    def all(self):
        # Badges only exist once the cards have rendered.
        if self.page.polls < self.page.visible_after:
            return []
        return [_FakeBadge(i) for i in self.page.flagged_ids]


class _FakeEmptyCollection:
    def all(self):
        return []


class _FakeTakeActionPage:
    """Selling page where listings render late: item links are invisible
    for the first N visibility checks, then appear with their banners."""

    def __init__(self, flagged_ids, visible_after=3):
        self.flagged_ids = list(flagged_ids)
        self.link_ids = list(flagged_ids)
        self.visible_after = visible_after
        self.polls = 0
        self.max_polls = 50

    def goto(self, url, wait_until=None, timeout=None):
        return None

    def locator(self, sel):
        if sel == S.SCR_MY_LISTING_LINKS[1]:
            return _FakeLinksCollection(self)
        if sel == S.F_TAKE_ACTION_BADGE[1]:
            return _FakeBadgeCollection(self)
        if sel == "xpath=" + S.F_RELIST_EDIT_CARD_MENU_BUTTON_SCOPED[1]:
            return _FakeEmptyCollection()
        raise AssertionError(f"unexpected selector {sel!r}")


def _make_take_action_driver(page, monkeypatch):
    drv = B.PlaywrightDriver.__new__(B.PlaywrightDriver)
    drv.account = {}
    drv._ensure = lambda: None
    drv._page = page
    monkeypatch.setattr(B.human, "human_pause", lambda *a, **k: None)
    return drv


def test_driver_waits_for_visible_listing_before_scanning_badges(monkeypatch):
    # 2026-11-07 live behaviour: the selling page renders its cards
    # asynchronously. The old code scanned for banners 1.5–3s after
    # domcontentloaded and read an empty page, reporting "no flagged
    # listings" while they were still loading. The discovery must poll
    # until the first listing is actually visible, then scan.
    page = _FakeTakeActionPage(["111", "222"], visible_after=3)
    drv = _make_take_action_driver(page, monkeypatch)
    flagged = drv.get_take_action_listings()
    assert [f["id"] for f in flagged] == ["111", "222"]
    assert page.polls >= 3, "waited for the listings to become visible"


def test_driver_finds_all_flagged_not_just_first(monkeypatch):
    # S.to_playwright appends .first, so .all() on it returns one
    # element only — the scan could never return more than one flagged
    # listing, and Min-Max above 1 could never be met. The direct
    # locator must return every flagged card on the page.
    page = _FakeTakeActionPage(["111", "222", "333"], visible_after=1)
    drv = _make_take_action_driver(page, monkeypatch)
    flagged = drv.get_take_action_listings()
    assert [f["id"] for f in flagged] == ["111", "222", "333"]
