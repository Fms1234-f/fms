"""Facebook Marketplace selectors — ALL in one place.

Facebook changes its DOM often. When a step breaks, update the selector HERE;
no other module hard-codes Marketplace selectors.

Conventions:
- Prefer robust selectors: aria-labels, data-testid, placeholder text, role names.
- Each constant is a (strategy, value) tuple for Playwright: ("css"|"xpath"|"text"|"label"|"placeholder"|"role", value).
- URLs are absolute.
"""
from __future__ import annotations

# ------------------------------------------------------------------ URLs ---
LOGIN_URL = "https://www.facebook.com/login"
HOME_URL = "https://www.facebook.com/"
MARKETPLACE_URL = "https://www.facebook.com/marketplace/"
MKT_CREATE_ITEM_URL = "https://www.facebook.com/marketplace/create/item/"
MKT_YOUR_LISTINGS_URL = "https://www.facebook.com/marketplace/you/selling/"

# ------------------------------------------------------------------ login ---
# Facebook login page — Facebook serves several page variants, so each field
# has fallback selectors tried in order (first match wins).
LOGIN_EMAIL = ("css", "#email")
LOGIN_EMAIL_FALLBACKS = [
    ("css", "#email"),
    ("css", "input[name='email']"),
    ("css", "[data-testid='royal_email']"),
    ("css", "input[type='text'][autocomplete='username']"),
    ("placeholder", "Email address or phone number"),
    ("placeholder", "Email or phone number"),
]
LOGIN_PASS = ("css", "#pass")
LOGIN_PASS_FALLBACKS = [
    ("css", "#pass"),
    ("css", "input[name='pass']"),
    ("css", "[data-testid='royal_pass']"),
    ("css", "input[type='password']"),
    ("placeholder", "Password"),
]
LOGIN_BUTTON = ("css", "button[name='login']")
LOGIN_BUTTON_FALLBACKS = [
    ("css", "button[name='login']"),
    ("css", "[data-testid='royal_login_button']"),
    ("css", "button[type='submit']"),
    ("text", "Log in"),
    ("text", "Log In"),
]
# Logged-in indicator (profile link / nav)
LOGGED_IN_INDICATOR = ("css", "a[aria-label='Your profile'], a[aria-label*='Profile']")
# 2FA / checkpoint prompts
TWOFA_CODE_INPUT = ("css", "input[name='approvals_code'], input[aria-label*='code' i]")
TWOFA_SUBMIT = ("css", "button[type='submit']")
CHECKPOINT_CONTINUE = ("text", "Continue")

# ------------------------------------------------- create-listing form ---
# "Create new listing" -> "Item for sale" entry points (fallbacks in order)
CREATE_LISTING_BUTTON = ("css", "a[href='/marketplace/create/']")
ITEM_FOR_SALE_OPTION = ("text", "Item for sale")
# v0.2.44: FBM Robo style click-through — header Marketplace nav icon.
MKT_NAV_ICON = ("css", "a[aria-label='Marketplace']")
# v0.2.50: expand the "More details" section first (user's explicit order).
MORE_DETAILS = ("text", "More details")

# Form fields on /marketplace/create/item/
# v0.2.48: label-based (get_by_label handles aria-label, <label for>,
# wrapped labels). The old CSS aria-label* selectors stopped matching
# Facebook's current markup — the form renders but the Title input was
# never found (20s timeout on a visibly-loaded page).
# v0.2.59: REVERTED from placeholder — the floating "Title"/"Price" text is
# NOT a placeholder attribute (it's a Material-style floating label).
# get_by_label worked in v0.2.57; placeholder broke everything in v0.2.58.
F_TITLE = ("label", "Title")
# v0.2.63: Price has TWO "Price" texts in DOM (one without input!). Use XPath
# to find the span with "Price" that actually has a text input in its label.
F_PRICE = ("xpath",
           "//span[normalize-space(text())='Price']/ancestor::label[1]"
           "//input[@type='text']")
# v0.2.58: Category is a dropdown DIV (screenshot shows ▼ arrow), not an input.
# v0.2.67: Category is a combobox label. Use XPath for reliability.
F_CATEGORY = ("xpath",
              "//span[normalize-space(text())='Category']"
              "/ancestor::label[@role='combobox'][1]")
F_CONDITION_NEW = ("text", "New")
F_CONDITION_USED_LIKE_NEW = ("text", "Used - like new")
# v0.2.54: the Condition dropdown field itself (click to open the list).
# v0.2.58: it's a dropdown DIV with placeholder-like text, not a labeled input.
# v0.2.67: Condition is a combobox label (like Category). get_by_text finds
# the SPAN, not the clickable LABEL. Use XPath to get the label.
F_CONDITION_FIELD = ("xpath",
                     "//span[normalize-space(text())='Condition']"
                     "/ancestor::label[@role='combobox'][1]")
# v0.2.59: reverted — Description floating label is not a placeholder attr.
F_DESCRIPTION = ("label", "Description")
# v0.2.58: Availability dropdown (in More details). Options: "List as single
# item" / "List as in stock". User's product saves "list as stock".
F_AVAILABILITY_FIELD = ("text", "Availability")
F_AVAILABILITY = ("css", "[aria-label*='Availability' i]")
# v0.2.59: reverted — Location floating label is not a placeholder attr.
F_LOCATION = ("label", "Location")
F_LOCATION_FIRST_RESULT = ("css", "[role='listbox'] [role='option']:first-child")
F_TAGS = ("css", "input[aria-label*='tag' i], input[placeholder*='tag' i]")

# Photos / video
F_ADD_PHOTOS = ("css", "input[type='file'][accept*='image']")
F_ADD_VIDEO = ("css", "input[type='file'][accept*='video']")

# Publish
F_PUBLISH_BUTTON = ("css", "button[type='submit'], div[aria-label='Publish'][role='button']")  # legacy selector; keep existing callers unchanged
# v0.2.120: final Publish must be identified by its actual accessible label/text.
# Do not use generic button[type=submit] here: Facebook can render Next as submit.
F_FINAL_PUBLISH_BUTTON = ("css", "button[aria-label='Publish'], button:has-text('Publish'), [role='button'][aria-label='Publish'], div[aria-label='Publish'][role='button']")
F_NEXT_BUTTON = ("text", "Next")
F_DRAFT_SAVED_INDICATOR = ("text", "Your listing has been saved")

# Listing visibility (matches the real tool's "Hide From Friends" setting)
# v0.2.58: Hide from friends is a TOGGLE SWITCH (screenshot), not a checkbox.
# Find the switch near the "Hide from friends" text.
F_HIDE_FROM_FRIENDS = ("css", "[role='switch'][aria-label*='Hide from friends' i], "
                              "[role='switch'][aria-label*='Hide listing from friends' i]")

# Delivery options (real tool's product dialog checkboxes; best-effort text match)
F_DELIVERY_MEETUP = ("text", "Public meetup")
F_DELIVERY_PICKUP = ("text", "Door pickup")
F_DELIVERY_DROPOFF = ("text", "Door drop-off")

# ------------------------------------------------- delete / renew ---
# Best-effort: deletion/renewal UI drifts; update here when it breaks.
F_DELETE_LISTING_BUTTON = ("css", "div[aria-label='Delete'][role='button'], "
                                  "div[aria-label*='Delete listing' i][role='button']")
F_CONFIRM_DELETE_BUTTON = ("css", "div[aria-label='Delete'][role='button'], "
                                  "button[type='submit']")
# Delete Previous ONLY: the selling-page "Delete listing" confirmation
# dialog's Delete button. The old F_CONFIRM_DELETE_BUTTON matches the
# listing-page delete button (div[aria-label='Delete']); the selling-page
# dialog's Delete is a div[role='button'] with the text "Delete" and no
# aria-label — v0.2.205 only matched a native <button> inside the dialog
# and the 2026-11-06 live run skipped all 5 listings
# (delete_confirm_not_found) even though the dialog opened every time.
# All forms are tried so the dialog is confirmed whichever form
# Facebook renders. Do NOT change F_CONFIRM_DELETE_BUTTON — the other
# delete flows use it.
F_DELETE_PREVIOUS_CONFIRM_BUTTON = (
    "css", "div[aria-label='Delete'][role='button'], "
    "button[type='submit'], [role='dialog'] button:has-text('Delete'), "
    "[role='dialog'] [role='button']:has-text('Delete'), "
    "[role='alertdialog'] [role='button']:has-text('Delete')")
# Delete Previous ONLY: after the confirmation Delete is clicked,
# Facebook shows a "Did you sell this item?" survey dialog (radio
# options + Next) instead of closing the dialog. It must be closed
# (X) before the next listing, or it covers the page and blocks
# every "..." click for the rest of the run (2026-11-06 live run).
F_DELETE_PREVIOUS_SURVEY_DIALOG = (
    "css", "[role='dialog']:has-text('Did you sell this item?')")
F_DELETE_PREVIOUS_SURVEY_CLOSE_BUTTON = (
    "css", "[role='dialog']:has-text('Did you sell this item?') "
    "[aria-label='Close'][role='button'], "
    "[role='dialog']:has-text('Did you sell this item?') "
    "[aria-label='Close']")
F_RENEW_BUTTON = ("css", "div[aria-label*='Renew' i][role='button'], "
                         "span:has-text('Renew listing')")

# ------------------------------------------------- marketplace location ---
# Change the Marketplace location shown for the account (best-effort).
MKT_LOCATION_BUTTON = ("css", "[aria-label*='location' i][role='button'], "
                              "a[href*='/marketplace/'][aria-label*='ocation' i]")
MKT_LOCATION_INPUT = ("css", "input[aria-label*='Location' i], "
                             "input[placeholder*='Location' i]")

# ------------------------------------------------- "take action" flags ---
# Listings Facebook flags with "take action" (identity/phone verification)
# show a matching badge/banner on the selling page (best-effort).
F_TAKE_ACTION_BADGE = ("css", "[aria-label*='take action' i], "
                              "span:has-text('Take action')")

# ------------------------------------------------- draft & publish ---
# Best-effort: Facebook's draft UI drifts; update here when it breaks.
F_SAVE_DRAFT_BUTTON = ("css", "div[aria-label='Save draft'][role='button'], "
                              "button[aria-label*='Save draft' i]")
MKT_DRAFTS_URL = "https://www.facebook.com/marketplace/you/drafts/"
F_PUBLISH_DRAFT_BUTTON = ("css", "div[aria-label='Publish'][role='button'], "
                                 "button[type='submit']")
F_DISCARD_DRAFT_BUTTON = ("css", "div[aria-label*='Discard' i][role='button']")

# ------------------------------------------------- edit existing ---
# Relist/Edit: rewrite an existing (sold/out-of-stock) listing instead of
# creating a new one — bypasses new-listing caps on limited accounts.
def MKT_EDIT_URL(listing_id: str) -> str:
    return f"https://www.facebook.com/marketplace/edit/?listing_id={listing_id}"

SCR_MY_LISTING_LINKS = ("css", "a[href*='/marketplace/item/']")
F_SAVE_EDIT_BUTTON = ("css", "div[aria-label='Save'][role='button'], "
                             "button[type='submit']")
# Relist & Edit: the selling-page edit form's submit control is labelled
# "Update" (the create form uses "Save"). Tried first, Save is the fallback.
F_RELIST_EDIT_UPDATE_BUTTON = ("css", "div[aria-label='Update'][role='button'], "
                                   "button:has-text('Update')")
# Relist & Edit ONLY (2026-11-02): reach the edit form through the
# selling-page card's "..." menu, exactly as the user does by hand.
# The "..." button sits on the same card as the listing link, and the
# menu's "Edit listing" entry is a link. Automation cannot click the
# browser's native right-click context menu (browser UI, not page
# content), so the faithful equivalent is used: click "...", find the
# menu's "Edit listing" LINK, and open THAT link's destination in a new
# tab — the same edit form, in a new tab, reached through the menu, not
# by constructing an edit URL from the listing id.
F_RELIST_EDIT_CARD_MENU_BUTTON = ("css",
    "button[aria-label*='more' i], [role='button'][aria-label*='more' i], "
    "button[aria-label*='option' i], [role='button'][aria-label*='option' i], "
    "button[aria-label*='action' i], [role='button'][aria-label*='action' i], "
    "button[aria-label*='menu' i], [role='button'][aria-label*='menu' i], "
    "button[title*='more' i], [role='button'][title*='more' i], "
    "div[role='button']:has-text('...'), button:has-text('...')")
def _ci_contains(attr, word):
    return (f"contains(translate({attr},'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            f"'abcdefghijklmnopqrstuvwxyz'),'{word}')")


# Fragment: a menu button's accessible name/title, or its literal "..."
# text. Shared by the Relist & Edit card-ancestor xpath (browser.py) and
# the scoped selector below, so both use exactly the same definition.
_RELIST_MENU_NAME_PRED = " or ".join(
    [_ci_contains("@aria-label", w) for w in ("more", "option", "action", "menu")] +
    [_ci_contains("@title", w) for w in ("more", "option", "action", "menu")] +
    ["normalize-space(.)='...'"])
F_RELIST_EDIT_MENU_BUTTON_XPATH_PRED = (
    "(self::button or @role='button') and (" + _RELIST_MENU_NAME_PRED + ")")
# Relist & Edit ONLY (2026-11-05 correction): menu buttons excluding
# global/header/toolbar controls. Fallback discovery and card-token
# lookup use ONLY this collection, so an unrelated page button can
# never become a fake listing or consume a Min-Max slot.
F_RELIST_EDIT_CARD_MENU_BUTTON_SCOPED = (
    "xpath",
    "//*[" + F_RELIST_EDIT_MENU_BUTTON_XPATH_PRED +
    " and not(ancestor::header or ancestor::nav"
    " or ancestor::*[@role='banner']"
    " or ancestor::*[@role='navigation']"
    " or ancestor::*[@role='toolbar'])]")
F_RELIST_EDIT_MENU_EDIT_LINK = ("css", "a:has-text('Edit listing'), "
                                     "[role='menuitem']:has-text('Edit listing')")
# Delete Previous ONLY: the selling-page card menu's "Delete listing"
# entry — same shape as the Edit listing entry, but clicking it opens
# the delete confirmation dialog on the same page (no new tab).
F_DELETE_PREVIOUS_MENU_DELETE_LINK = ("css", "a:has-text('Delete listing'), "
                                      "[role='menuitem']:has-text('Delete listing')")
# The listing detail dialog ("Your listing") that opens when a card —
# not its "..." button — is clicked by mistake. Detected only so the
# menu step can close it and retry the "..." click once (2026-11-05).
# Exact text match: the sidebar says "Your listings" (plural).
F_RELIST_EDIT_DETAIL_DIALOG = ("xpath",
                               "//*[normalize-space()='Your listing']")

# ------------------------------------------------- scrap (read-only) ---
# Best-effort selectors for extracting a listing's public data.
SCR_TITLE = ("css", "h1")
SCR_PRICE = ("css", "span[dir='auto']")
SCR_DESCRIPTION = ("css", "div[data-testid='marketplace_pdp_description'] span, "
                           "div[dir='auto'] span")
SCR_PHOTOS = ("css", "img[src*='scontent']")
SCR_LOCATION = ("css", "span:has-text('Listed'), div[dir='auto']")
SCR_AVAILABILITY = ("text", "In stock")

# ------------------------------------------------------- misc / safety ---
# Signals that the account hit a wall (checked after actions)
SEL_LIMIT_REACHED = ("text", "You've reached the limit")
SEL_CONFIRM_IDENTITY = ("text", "Confirm your identity")
SEL_SOMETHING_WRONG = ("text", "Something's wrong")


def to_playwright(page_or_locator, selector: tuple[str, str]):
    """Convert a (strategy, value) tuple to a Playwright locator/query."""
    strategy, value = selector
    if strategy == "css":
        return page_or_locator.locator(value).first
    if strategy == "xpath":
        return page_or_locator.locator(f"xpath={value}").first
    if strategy == "text":
        return page_or_locator.get_by_text(value, exact=False).first
    if strategy == "label":
        return page_or_locator.get_by_label(value).first
    if strategy == "placeholder":
        return page_or_locator.get_by_placeholder(value).first
    if strategy == "role":
        return page_or_locator.get_by_role(value).first
    raise ValueError(f"Unknown selector strategy: {strategy}")
