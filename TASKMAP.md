# PYRESEC Next-Moves Task Map

## Priority 1 — Website tightening (active)
- [x] Fix Swagger UI blank page (CSP was blocking Swagger's CDN assets)
- [x] Fix / repurpose broken **Pay $500 USDC — x402** button (x402 is API-only; replaced with a working in-page x402 instructions panel)
- [x] Document domain options and update all canonical/OpenGraph/meta URLs to the real production Cloud Run URL
- [x] Audit and fix all broken links/images (nanoclonesystems.com link, missing `social-preview.png`)

## Priority 2 — First live outbound
- [ ] Approve the UMAprotocol lead in Telegram and verify Resend delivery

## Priority 3 — Content engine
- [ ] Generate the first case study with `scripts/content_engine.py` and post to X/Farcaster/LinkedIn

## Priority 4 — Pipeline validation
- [ ] Dry-run the 8 AM `git_scraper.py` run to preview the next day's lead batch

## Priority 5 — Growth
- [ ] Add a second lead source (e.g., HackerOne directory, DeFiLlama protocol list, x402 Bazaar listing)
