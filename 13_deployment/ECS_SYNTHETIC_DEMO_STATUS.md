# Linux Synthetic Demo Deployment State

Updated: 2026-10-23

Status: **PARTIALLY_DEPLOYED**

## Live environment

- Public URL: `https://psynova.top`; `www.psynova.top` redirects to the apex.
- ECS address: `47.253.252.178`; inbound TCP 80/443 are reachable.
- Nginx, Backend, LLM, RAG, CAT, Safety, and `certbot.timer` are active. Nginx config validation passes.
- Let’s Encrypt certificate is valid through 2027-01-21. HTTP redirects to HTTPS.
- MySQL 8.0.46 is loopback-only. Schema `smhai_school_demo` is at `20261016_0024` with 66 base tables.
- FastAPI is bound to `127.0.0.1:8088`; MySQL is bound to `127.0.0.1:3306`. External TCP probes to both ports fail.
- UFW reports inactive; nftables and firewalld services are inactive. The configured ECS security group admits only 80/443; external probes confirm 3306/8088 are closed.

## Acceptance evidence

- Public HTTPS verifier authenticated all 8 synthetic accounts across two schools and four roles. CSRF enforcement, cross-role denial, cross-school denial, and session survival after Backend restart passed. The verifier reports that response bodies and credentials were not logged.
- One real DeepSeek education request passed through Backend, Input Safety, RAG, DeepSeek, and Output Safety. It completed with 3 evidence citations, persisted in MySQL, logged no answer text, and passed the safe-output checks.
- The browser loaded the public login page at desktop and 390×844 viewports. The login form rendered in both.
- The protected Backend overlay was installed from a hash-verified root snapshot and reached `HTTP_VERIFIED`; the existing database was not changed by the overlay.

## Remaining verification

- Automated submission of account credentials through the local browser UI was not completed. The execution review rejected transferring decrypted synthetic account credentials from ECS to local Chrome with `blocked by policy`; no credentials were exported. Public HTTPS API login was verified instead.
- CAT service readiness is confirmed, but a CAT user workflow was not exercised in this deployment pass.

## Source control

- Branch: `xiajiadi/linux-credentials-20261022`
- Local commits: `29f92ec` (Safety timeout) and `73f537f` (pinned recovery overlay)
- No Git push was performed.
