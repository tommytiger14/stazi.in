#!/usr/bin/env python3
"""
Stayzi — publish queued posts to a Facebook Page and an Instagram Business account
via the Meta Graph API.

Reads queue.json, publishes every post whose `publish_at` is due and that has not
already been published, then writes the queue back with ids and timestamps.

Environment variables required:
  META_ACCESS_TOKEN   long-lived Page access token
  FB_PAGE_ID          numeric Facebook Page id
  IG_USER_ID          numeric Instagram Business account id
Optional:
  GRAPH_VERSION       defaults to v26.0
  DRY_RUN=1           validate and print, publish nothing

A queue entry with "hold": true is skipped no matter what its date says. Use it for
posts whose facts you have not confirmed yet.

Usage:
  python stayzi_publish.py            # publish everything due
  python stayzi_publish.py --check    # credentials + queue check only
"""

import json, os, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "queue.json")
GRAPH = f"https://graph.facebook.com/{os.environ.get('GRAPH_VERSION', 'v26.0')}"
TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
DRY = os.environ.get("DRY_RUN") == "1"


# ---------------------------------------------------------------- http helpers

def _call(method, path, params):
    url = f"{GRAPH}/{path}"
    params = {**params, "access_token": TOKEN}
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {body}") from None


def get(path, **params):
    return _call("GET", path, params)


def post(path, **params):
    return _call("POST", path, params)


# ---------------------------------------------------------------- publishing

def publish_facebook(image_url, caption):
    """Photo post to the Page feed. Returns the post id."""
    r = post(f"{FB_PAGE_ID}/photos", url=image_url, caption=caption, published="true")
    return r.get("post_id") or r.get("id")


def publish_instagram(image_url, caption):
    """Two-step: create a media container, wait for it, then publish it."""
    container = post(f"{IG_USER_ID}/media", image_url=image_url, caption=caption)["id"]

    # Container processing is async. Poll until FINISHED (usually a few seconds).
    for attempt in range(30):
        status = get(container, fields="status_code,status").get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"IG container {container} failed: "
                               f"{get(container, fields='status').get('status')}")
        time.sleep(3)
    else:
        raise RuntimeError(f"IG container {container} not ready after 90s")

    return post(f"{IG_USER_ID}/media_publish", creation_id=container)["id"]


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

def check():
    missing = [k for k, v in
               [("META_ACCESS_TOKEN", TOKEN), ("FB_PAGE_ID", FB_PAGE_ID),
                ("IG_USER_ID", IG_USER_ID)] if not v]
    if missing:
        sys.exit("Missing environment variables: " + ", ".join(missing))

    page = get(FB_PAGE_ID, fields="name,id")
    print(f"Facebook Page : {page['name']} ({page['id']})")

    ig = get(IG_USER_ID, fields="username,id")
    print(f"Instagram     : @{ig['username']} ({ig['id']})")

    # Token lifetime — a long-lived Page token normally has no expiry.
    info = get("debug_token", input_token=TOKEN).get("data", {})
    exp = info.get("expires_at", 0)
    print("Token expires : " +
          ("never" if exp in (0, None)
           else datetime.fromtimestamp(exp, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")))
    print("Scopes        : " + ", ".join(info.get("scopes", [])) or "unknown")

    queue = load_queue()
    pending = [i for i in queue if not i.get("published")]
    held = [i for i in pending if i.get("hold")]
    print(f"Queue         : {len(queue)} items, {len(pending)} unpublished, "
          f"{len(held)} on hold")
    for i in pending:
        flag = "  [ON HOLD]" if i.get("hold") else ""
        print(f"  - {i.get('publish_at', 'immediate')}  {i.get('name', '(unnamed)')}{flag}")


# ---------------------------------------------------------------- main

def main():
    if "--check" in sys.argv:
        check()
        return

    if not (TOKEN and FB_PAGE_ID and IG_USER_ID):
        sys.exit("Missing META_ACCESS_TOKEN / FB_PAGE_ID / IG_USER_ID")

    queue = load_queue()
    now = datetime.now(timezone.utc)
    published_any = False

    for item in queue:
        if item.get("published") or item.get("hold") or not is_due(item, now):
            continue

        name = item.get("name", "(unnamed)")
        image = item["image_url"]
        targets = item.get("platforms", ["facebook", "instagram"])
        results = item.setdefault("results", {})

        print(f"\n--- {name}")
        if DRY:
            print(f"    DRY RUN — would post to {', '.join(targets)}: {image}")
            continue

        try:
            if "facebook" in targets and "facebook" not in results:
                results["facebook"] = publish_facebook(image, item["fb_caption"])
                print(f"    Facebook  -> {results['facebook']}")

            if "instagram" in targets and "instagram" not in results:
                ig_caption = item["ig_caption"]
                tags = item.get("hashtags", "")
                if tags:
                    ig_caption = f"{ig_caption}\n.\n.\n{tags}"
                results["instagram"] = publish_instagram(image, ig_caption)
                print(f"    Instagram -> {results['instagram']}")

            item["published"] = True
            item["published_at"] = now.isoformat()
            published_any = True

        except Exception as e:
            item["error"] = str(e)
            print(f"    FAILED: {e}", file=sys.stderr)

        save_queue(queue)

    if not published_any and not DRY:
        print("Nothing due.")


if __name__ == "__main__":
    main()
