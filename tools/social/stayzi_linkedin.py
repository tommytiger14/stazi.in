#!/usr/bin/env python3
"""
Stayzi — publish queued posts to LinkedIn (personal profile or company page).

Sibling of stayzi_publish.py (Facebook / Instagram). Same queue idea, same
`hold` flag, same "write the ids back so nothing posts twice" behaviour.

LinkedIn has two posting APIs and which one you get depends on which product
your app was granted:

  ugc   (default)  POST /v2/ugcPosts + /v2/assets?action=registerUpload
                   Granted by the self-serve "Share on LinkedIn" product with
                   the w_member_social scope. Personal profile. Text + image.

  rest             POST /rest/posts + /rest/images + /rest/documents
                   Granted by the Community Management API (requires LinkedIn
                   approval). Company page. Text + image + document carousels.

Set LINKEDIN_API_MODE to pick. Document/carousel posts only work in rest mode.

Environment variables required:
  LINKEDIN_ACCESS_TOKEN   3-legged OAuth token (60 days, see setup doc)
  LINKEDIN_AUTHOR_URN     urn:li:person:xxxx  or  urn:li:organization:1234567
Optional:
  LINKEDIN_API_MODE       "ugc" (default) or "rest"
  LINKEDIN_VERSION        YYYYMM for rest mode, defaults to 202608
  DRY_RUN=1               validate and print, publish nothing

Usage:
  python stayzi_linkedin.py            # publish everything due
  python stayzi_linkedin.py --check    # credentials + queue check only
  python stayzi_linkedin.py --whoami   # print the person URN for this token
"""

import json, os, sys, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "linkedin_queue.json")

TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
AUTHOR = os.environ.get("LINKEDIN_AUTHOR_URN", "")
MODE = os.environ.get("LINKEDIN_API_MODE", "ugc").lower()
LI_VERSION = os.environ.get("LINKEDIN_VERSION", "202608")
DRY = os.environ.get("DRY_RUN") == "1"

API = "https://api.linkedin.com"


# ---------------------------------------------------------------- http helpers

def _headers(extra=None):
    h = {
        "Authorization": f"Bearer {TOKEN}",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    if MODE == "rest":
        h["LinkedIn-Version"] = LI_VERSION
    h.update(extra or {})
    return h


def _request(method, url, data=None, headers=None, raw=False):
    """Returns (parsed_body_or_bytes, response_headers)."""
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in _headers(headers).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
            hdrs = dict(r.headers)
            if raw or not body:
                return body, hdrs
            try:
                return json.loads(body.decode()), hdrs
            except json.JSONDecodeError:
                return body, hdrs
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url} -> HTTP {e.code}: {detail}") from None


def api_get(path, **params):
    url = f"{API}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    return _request("GET", url)[0]


def api_post(path, payload, query=""):
    url = f"{API}{path}{query}"
    data = json.dumps(payload).encode()
    return _request("POST", url, data=data,
                    headers={"Content-Type": "application/json"})


# ---------------------------------------------------------------- media upload

def fetch_bytes(url):
    """Pull the creative off stayzi.in (or wherever) so we can upload binary."""
    req = urllib.request.Request(url, headers={"User-Agent": "stayzi-publisher"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _put_binary(upload_url, blob, content_type):
    req = urllib.request.Request(upload_url, data=blob, method="PUT")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            if r.status not in (200, 201):
                raise RuntimeError(f"upload returned HTTP {r.status}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(f"binary upload -> HTTP {e.code}: {detail}") from None


def _content_type(url):
    lower = url.lower().split("?")[0]
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".pdf"):
        return "application/pdf"
    return "image/jpeg"


def upload_image(image_url):
    """Returns an asset/image URN usable in a post body."""
    blob = fetch_bytes(image_url)
    ctype = _content_type(image_url)

    if MODE == "rest":
        body, _ = api_post("/rest/images", {
            "initializeUploadRequest": {"owner": AUTHOR}
        }, query="?action=initializeUpload")
        value = body["value"]
        _put_binary(value["uploadUrl"], blob, ctype)
        return value["image"]

    # legacy assets flow
    body, _ = api_post("/v2/assets", {
        "registerUploadRequest": {
            "owner": AUTHOR,
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "serviceRelationships": [{
                "relationshipType": "OWNER",
                "identifier": "urn:li:userGeneratedContent",
            }],
        }
    }, query="?action=registerUpload")
    value = body["value"]
    upload_url = (value["uploadMechanism"]
                  ["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]
                  ["uploadUrl"])
    _put_binary(upload_url, blob, ctype)
    return value["asset"]


def upload_document(doc_url):
    if MODE != "rest":
        raise RuntimeError(
            "Document/carousel posts need LINKEDIN_API_MODE=rest "
            "(Community Management API). The self-serve Share on LinkedIn "
            "product cannot post documents.")
    blob = fetch_bytes(doc_url)
    body, _ = api_post("/rest/documents", {
        "initializeUploadRequest": {"owner": AUTHOR}
    }, query="?action=initializeUpload")
    value = body["value"]
    _put_binary(value["uploadUrl"], blob, "application/pdf")
    return value["document"]


# ---------------------------------------------------------------- publishing

def publish_rest(item):
    payload = {
        "author": AUTHOR,
        "commentary": item["text"],
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    if item.get("document_url"):
        payload["content"] = {"media": {
            "id": upload_document(item["document_url"]),
            "title": item.get("document_title", "Stayzi"),
        }}
    elif item.get("image_url"):
        media = {"id": upload_image(item["image_url"])}
        if item.get("alt_text"):
            media["altText"] = item["alt_text"]
        payload["content"] = {"media": media}

    body, headers = api_post("/rest/posts", payload)
    return headers.get("x-restli-id") or (body or {}).get("id")


def publish_ugc(item):
    if item.get("document_url"):
        raise RuntimeError("Document posts require rest mode — see upload_document")

    media_category = "NONE"
    media = []
    if item.get("image_url"):
        media_category = "IMAGE"
        entry = {"status": "READY", "media": upload_image(item["image_url"])}
        if item.get("alt_text"):
            entry["description"] = {"text": item["alt_text"]}
            entry["title"] = {"text": item.get("alt_title", "Stayzi")}
        media.append(entry)

    payload = {
        "author": AUTHOR,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": item["text"]},
                "shareMediaCategory": media_category,
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }
    if media:
        payload["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = media

    body, headers = api_post("/v2/ugcPosts", payload)
    return (body or {}).get("id") or headers.get("x-restli-id")


def publish(item):
    return publish_rest(item) if MODE == "rest" else publish_ugc(item)


def post_comment(post_urn, text):
    """First comment — where the stayzi.in link goes, so the body has no link."""
    encoded = urllib.parse.quote(post_urn, safe="")
    payload = {"actor": AUTHOR, "object": post_urn,
               "message": {"text": text}}
    path = ("/rest/socialActions" if MODE == "rest" else "/v2/socialActions")
    body, headers = api_post(f"{path}/{encoded}/comments", payload)
    return (body or {}).get("$URN") or (body or {}).get("id") \
        or headers.get("x-restli-id")


# ---------------------------------------------------------------- queue

def load_queue():
    if not os.path.exists(QUEUE):
        sys.exit(f"No queue file at {QUEUE}")
    with open(QUEUE, encoding="utf-8") as f:
        return json.load(f)


def save_queue(q):
    with open(QUEUE, "w", encoding="utf-8") as f:
        json.dump(q, f, indent=2, ensure_ascii=False)
        f.write("\n")


def is_due(item, now):
    when = item.get("publish_at")
    if not when:
        return True
    return datetime.fromisoformat(when.replace("Z", "+00:00")) <= now


# ---------------------------------------------------------------- checks

def whoami():
    """OpenID Connect userinfo — needs the 'openid profile' scopes."""
    info = api_get("/v2/userinfo")
    print(f"Name      : {info.get('name')}")
    print(f"Person URN: urn:li:person:{info.get('sub')}")
    return info


def check():
    missing = [k for k, v in [("LINKEDIN_ACCESS_TOKEN", TOKEN),
                              ("LINKEDIN_AUTHOR_URN", AUTHOR)] if not v]
    if missing:
        sys.exit("Missing environment variables: " + ", ".join(missing))

    if MODE not in ("ugc", "rest"):
        sys.exit(f"LINKEDIN_API_MODE must be 'ugc' or 'rest', got {MODE!r}")

    print(f"Mode      : {MODE}" + (f" (LinkedIn-Version {LI_VERSION})"
                                   if MODE == "rest" else ""))
    print(f"Author    : {AUTHOR}")

    try:
        whoami()
    except Exception as e:
        print(f"userinfo  : unavailable ({e.__class__.__name__}) — fine if the "
              f"token lacks the openid/profile scopes")

    # Token introspection tells us how many days are left before manual renewal.
    try:
        data = urllib.parse.urlencode({"client_id": os.environ.get("LINKEDIN_CLIENT_ID", ""),
                                       "client_secret": os.environ.get("LINKEDIN_CLIENT_SECRET", ""),
                                       "token": TOKEN}).encode()
        req = urllib.request.Request(
            "https://www.linkedin.com/oauth/v2/introspectToken", data=data,
            method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=30) as r:
            info = json.loads(r.read().decode())
        exp = info.get("expires_at")
        if exp:
            when = datetime.fromtimestamp(exp, timezone.utc)
            days = (when - datetime.now(timezone.utc)).days
            print(f"Token     : expires {when:%Y-%m-%d} ({days} days left)")
            print(f"Scopes    : {info.get('scope', 'unknown')}")
            if days < 14:
                print("  !! Renew the token — LinkedIn tokens do not "
                      "auto-refresh for self-serve apps.")
    except Exception:
        print("Token     : introspection skipped (set LINKEDIN_CLIENT_ID / "
              "LINKEDIN_CLIENT_SECRET to see the expiry)")

    queue = load_queue()
    pending = [i for i in queue if not i.get("published")]
    held = [i for i in pending if i.get("hold")]
    print(f"Queue     : {len(queue)} items, {len(pending)} unpublished, "
          f"{len(held)} on hold")
    for i in pending:
        flag = "  [ON HOLD]" if i.get("hold") else ""
        kind = ("document" if i.get("document_url")
                else "image" if i.get("image_url") else "text")
        print(f"  - {i.get('publish_at', 'immediate')}  [{kind}] "
              f"{i.get('name', '(unnamed)')}{flag}")


# ---------------------------------------------------------------- main

def main():
    if "--whoami" in sys.argv:
        whoami()
        return
    if "--check" in sys.argv:
        check()
        return

    if not (TOKEN and AUTHOR):
        sys.exit("Missing LINKEDIN_ACCESS_TOKEN / LINKEDIN_AUTHOR_URN")

    queue = load_queue()
    now = datetime.now(timezone.utc)
    published_any = False

    for item in queue:
        if item.get("published") or item.get("hold") or not is_due(item, now):
            continue

        name = item.get("name", "(unnamed)")
        print(f"\n--- {name}")

        if DRY:
            kind = ("document" if item.get("document_url")
                    else "image" if item.get("image_url") else "text")
            print(f"    DRY RUN — would post a {kind} post as {AUTHOR}")
            print(f"    {item['text'][:180]}...")
            if item.get("first_comment"):
                print(f"    + first comment: {item['first_comment'][:80]}...")
            continue

        try:
            urn = item.get("post_urn")
            if not urn:
                urn = publish(item)
                item["post_urn"] = urn
                print(f"    Posted    -> {urn}")

            if item.get("first_comment") and not item.get("comment_urn"):
                try:
                    item["comment_urn"] = post_comment(urn, item["first_comment"])
                    print(f"    Comment   -> {item['comment_urn']}")
                except Exception as e:
                    # A failed comment must not make us repost the post itself.
                    item["comment_error"] = str(e)
                    print(f"    Comment FAILED: {e}", file=sys.stderr)

            item["published"] = True
            item["published_at"] = now.isoformat()
            item.pop("error", None)
            published_any = True

        except Exception as e:
            item["error"] = str(e)
            print(f"    FAILED: {e}", file=sys.stderr)

        save_queue(queue)

    if not published_any and not DRY:
        print("Nothing due.")


if __name__ == "__main__":
    main()
