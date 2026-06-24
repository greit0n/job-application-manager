# AI Agent Workflow

This app now generates application packets directly. External assistants should
usually work on the codebase, not on private application content.

## Product Flow

1. User completes sender profile.
2. User uploads one or more CV variants.
3. User clicks `Apply to job`.
4. The wizard stores the posting and confirms application basics.
5. Backend generation uses uploaded CV text as the only source of experience.
6. User reviews the packet, creates a Gmail draft, downloads a ZIP, and tracks
   the next action.

## Repository Rules For Assistants

- Keep the frontend build-free vanilla JS unless explicitly changed.
- Keep AI calls behind `services/ai_client.py::AIClient`.
- Keep generated PDFs faithful to the Bewerbungen rules.
- Preserve per-user scoping on every endpoint.
- Do not add third-party analytics or telemetry.
- Keep `AGENTS.md` and `CLAUDE.md` equivalent.
- Run tests and a privacy audit before commit, push, or deploy.

## Private Data

Never commit or paste into public tools:

- CV files.
- Generated letters or emails.
- Job postings.
- Gmail OAuth tokens.
- R2 keys.
- `.env` files.
- Database dumps.
- Screenshots or proof files.
- Real application histories.

## AI Generation Safety

When changing prompts or generation behavior:

- CV text remains the only source for experience, employers, education,
  credentials, and skills.
- Profile data supplies contact details, languages, availability, and
  preferences only.
- Do not invent missing experience.
- Do not mention AMS or that the applicant was told to apply.
- Keep application emails shorter than letters.
