# Maybe Monetize

Best path: keep the add-on itself free, and monetize around it.

For this Anki niche, these options seem strongest:

## 1. Free Core + Paid Power Pack

Keep the current add-on free on AnkiWeb, then sell a "Pro" version or companion add-on outside AnkiWeb with advanced workflow features:

- batch templates / shared prompt packs
- premium workflow presets
- analytics and QA reports
- cloud sync / backup of prompts and workflows
- better model-cost controls
- deck-specific automation packs

Why this fits:

- Anki's official add-on docs support sharing on AnkiWeb and also sharing outside AnkiWeb via `.ankiaddon` packages with `manifest.json`, so premium builds can be distributed separately.

Source:

- https://addon-docs.ankiweb.net/sharing.html

## 2. Subscription for Hosted Features, Not for the Local Add-on

Charge monthly only for things that need your infrastructure:

- sync prompts/workflows across devices
- hosted usage dashboards
- team/shared libraries
- managed prompt updates
- optional "run in the cloud" queue
- one-click preset marketplace

This is usually easier for users to accept than paywalling a local add-on.

## 3. Sell Premium Prompt / Preset Packs

The add-on is already prompt-centric, which makes this a natural monetization path. Possible packs:

- Japanese learning packs
- grammar-note packs
- card-quality audit packs
- MLR-specific optimization packs
- profession-specific packs for medicine, law, languages, etc.

This is lower engineering effort than building a whole SaaS.

## 4. Patreon / Ko-fi Supporter Tier

Offer:

- early access builds
- exclusive prompt libraries
- monthly workflow packs
- priority bugfix voting
- office hours / setup help

This seems normal in the Anki ecosystem. There are community references to authors using Patreon and similar supporter perks, and AnkiWeb add-on pages often expose author contact/support links.

Sources:

- https://docs.ankiweb.net/addons.html
- https://forums.ankiweb.net/t/how-can-i-donate/13300

## 5. Paid Setup / Consulting

This is underrated. Offer paid help for:

- custom prompt design
- note-type-specific automation
- migration from messy decks
- institutional / school rollout
- custom add-on extensions

This works especially well for serious learners, educators, or organizations.

## What Not to Do First

Do not start with a paid-only add-on on AnkiWeb.

My inference from community discussion is that paid add-ons on or around AnkiWeb are possible, but community sentiment can get sensitive when official/free-Anki spaces feel too commercialized.

Source for community sentiment:

- https://forums.ankiweb.net/t/idea-for-new-anki-addon-platform/68264

## What I Would Do

- Make the current add-on free.
- Add a clear `Support / Upgrade` link in the UI and README.
- Sell a premium preset/prompt pack first.
- Then add one subscription-worthy hosted feature if users actually want sync or sharing.

## Simple Monetization Ladder

- `Free`: local AI automation
- `EUR 9-19` one-time: premium preset library
- `EUR 5-12/mo`: sync, cloud backups, shared prompt library
- `EUR 49-199`: custom setup / service
