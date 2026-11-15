# Hosting Sentinel as a product (Phase 6)

End state: a public URL where anyone signs in with GitHub, installs the
Sentinel GitHub App on their repos (public or private), and from then on every
PR gets an automatic risk review - a comment on the PR and a live entry on
their dashboard. No terminal, no webhook setup, no tokens.

Three one-time steps: deploy the server, create the GitHub App, connect them.

## 1. Deploy the server (Render free tier)

1. Push this repo to GitHub (done if you're reading this on github.com).
2. https://dashboard.render.com > **New > Blueprint** > pick this repo.
   `render.yaml` provisions the service; `SENTINEL_WEBHOOK_SECRET` and
   `SENTINEL_SESSION_SECRET` are auto-generated.
3. In the service's **Environment** tab fill the LLM provider vars (same values
   as your local `.env` - e.g. the Groq block) and
   `SENTINEL_BASE_URL=https://<your-service>.onrender.com`.
4. Wait for deploy; `https://<your-service>.onrender.com/healthz` should return
   `{"ok": true}`.

Free-tier caveat: the instance sleeps after ~15 min idle and cold-starts in
~30-60s. A webhook that arrives mid-wake can be missed (GitHub retries are
manual - "Redeliver" in the App's Advanced tab). Fine for a demo/portfolio;
use a $7 instance for real traffic.

## 2. Create the GitHub App

GitHub > **Settings > Developer settings > GitHub Apps > New GitHub App**:

| Field | Value |
|---|---|
| App name | `sentinel-review-<yourname>` (must be globally unique) |
| Homepage URL | `https://<your-service>.onrender.com` |
| Callback URL | `https://<your-service>.onrender.com/auth/callback` |
| ☑ Request user authorization (OAuth) during installation | checked |
| Webhook URL | `https://<your-service>.onrender.com/webhook/github` |
| Webhook secret | the `SENTINEL_WEBHOOK_SECRET` value from Render |
| Repository permissions | **Pull requests: Read & write** · **Contents: Read-only** · **Metadata: Read-only** (automatic) |
| Subscribe to events | **Pull request** |
| Where can this app be installed? | **Any account** |

After creating:

- note the **App ID** (top of the app page)
- **Generate a private key** (downloads a `.pem`)
- **Generate a new client secret** and note the **Client ID**

## 3. Connect them

Back in Render's Environment tab:

```
SENTINEL_GITHUB_APP_ID=<App ID>
SENTINEL_GITHUB_CLIENT_ID=<Client ID>
SENTINEL_GITHUB_CLIENT_SECRET=<client secret>
SENTINEL_GITHUB_APP_PRIVATE_KEY=<paste the .pem contents>
```

(Render keeps multi-line values; if your host doesn't, replace newlines with
`\n` - Sentinel un-escapes them.)

Save; the service redeploys. Done.

## Using it

1. Open `https://<your-service>.onrender.com` > **Sign in with GitHub**.
2. Install the app: `https://github.com/apps/<app-name>` > **Install** >
   choose repos. (Install first, then sign in, works too - signing in syncs
   your installations.)
3. Open any PR in an installed repo. Within a minute: Sentinel's risk comment
   on the PR, and the review on your dashboard (which live-refreshes).

Multi-tenant by construction: each review runs with that installation's
short-lived token (never a personal token), and each signed-in user sees only
repos their installations cover.

## Local development of hub mode

Hub mode works locally too: set the Phase 6 vars in `.env` with
`SENTINEL_BASE_URL=http://localhost:8787`, point the GitHub App's callback at
`http://localhost:8787/auth/callback`, run `sentinel serve --port 8787`, and
tunnel webhooks with:

```bash
gh webhook forward --repo=<owner>/<repo> --events=pull_request --url=http://localhost:8787/webhook/github
```

Without any Phase 6 vars, `sentinel serve` stays in Phase 5 local mode: open
dashboard, plain webhook, your own `GITHUB_TOKEN` for comments.
