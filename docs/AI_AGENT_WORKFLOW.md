# AI Agent Workflow

This guide explains how to use the app with Codex, Claude, or another assistant without leaking private data.

## Recommended Flow

1. Fill out the candidate profile in the app.
2. Upload CV variants in the app.
3. Add the target application.
4. Open the application detail view.
5. Copy the AI brief.
6. Paste the brief and the job posting into the assistant.
7. Ask for the specific output you need.

Useful requests:

- "Recommend the best CV variant and explain why."
- "Draft a concise application email."
- "Draft a one-page cover letter."
- "Prepare interview questions and answer outlines."
- "Summarize this posting into tracker notes."
- "Identify gaps I should be honest about."

## Safe Assistant Instructions

Tell the assistant:

- Use only the profile and job posting provided.
- Do not invent experience, employers, credentials, salary history, or language levels.
- Mark missing information as a question.
- Keep private data out of public commits, issues, pull requests, and screenshots.
- Keep application emails concise.
- Use a confident but honest tone.

## What Not To Share Publicly

Do not publish:

- CV files.
- Backup JSON files.
- Confirmation screenshots.
- Interview invitations.
- Rejection or offer letters.
- Private contact details.
- Salary negotiation notes.
- Real application histories.

## Working With This Repository

When an assistant edits the repository:

- Keep the app static and dependency-free.
- Keep data storage local to the browser.
- Keep `AGENTS.md` and `CLAUDE.md` equivalent unless tool-specific instructions are requested.
- Run a privacy audit before committing.
- Do not add real user data to sample files.

## Prompt Template

```text
I am applying for this role. Use the candidate profile and application context below.

Tasks:
1. Recommend the best CV variant.
2. Draft a concise application email.
3. Draft tracker notes.
4. List interview prep points.

Rules:
- Do not invent experience.
- Ask about missing information.
- Keep the tone specific and professional.

Candidate and application brief:
[paste app brief here]

Job posting:
[paste job posting here]
```
