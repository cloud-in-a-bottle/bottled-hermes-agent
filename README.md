# bottled-hermes-agent

Hermes Agent packaged for Cloud in a Bottle. Provides the Hermes web dashboard behind Cloud in a Bottle owner SSO, with the gateway running for messaging platform integration.

## What's included

- Hermes dashboard (web UI) on the app's subdomain, auto-authenticated for the zone owner
- Hermes gateway for Telegram/Discord/Slack/WhatsApp/Signal messaging
- Persistent storage for memory, skills, sessions, and config

## Setup

1. Deploy via the Cloud in a Bottle dashboard or CLI
2. Visit the app subdomain to access the Hermes dashboard
3. Configure your LLM provider API key in the dashboard Settings page
4. Optionally configure messaging platform tokens for gateway integration

## Configuration

All Hermes config lives in the app's persistent data directory. The dashboard provides a web UI for managing settings, API keys, skills, and sessions.
