# Job Application Manager

A private, local-first job application tracker that runs as a single static HTML file. It helps job seekers manage applications, CV variants, proof files, profile notes, backups, and AI-ready application context without creating accounts or running a backend.

## What It Does

- Track applications by company, role, status, date, source, salary, location, URL, CV variant, and notes.
- Upload CV PDFs from the app and store them privately in the browser.
- Upload proof files such as confirmation screenshots, saved emails, interview documents, and offer letters.
- Maintain a reusable candidate profile for cover letters, interview prep, and assistant prompts.
- Export and import a full private backup, including uploaded CVs and proof files.
- Use `AGENTS.md` and `CLAUDE.md` as assistant instructions for Codex, Claude, or similar tools.

## Quick Start

1. Open `index.html` in your browser.
2. Go to `Profile` and add your background, skills, preferences, and contact details.
3. Go to `CVs` and upload one or more CV PDFs.
4. Go to `Tracker` and add your applications.
5. Use `Backup` to export a private JSON backup whenever you want.

No install step is required. There is no build process, server, login, or database.

## Privacy Model

This project is designed for local-first use.

- Application data is stored in browser `localStorage`.
- Uploaded CVs and proof files are stored in browser IndexedDB.
- Nothing is uploaded by the app.
- Exported backups can contain private documents and should be treated as sensitive personal data.
- Do not commit backups, CVs, screenshots, or application documents to a public repository.

## GitHub Template Usage

Use this repository as a template, then keep your private data out of Git:

1. Click `Use this template` on GitHub.
2. Clone your new repository.
3. Open `index.html`.
4. Add your profile, CVs, and applications from the UI.
5. Export backups to a private location outside the repository.

The `.gitignore` is intentionally strict about private files.

## GitHub Pages

The app can be hosted on GitHub Pages because it is fully static:

1. Push the repository to GitHub.
2. Open repository settings.
3. Enable Pages from the default branch.
4. Open the published URL.

Browser storage is scoped to the Pages URL. If you move between local files and GitHub Pages, export a backup from one location and import it in the other.

## AI Assistant Workflow

The repo includes:

- `AGENTS.md` for Codex-style agents.
- `CLAUDE.md` for Claude-style agents.
- `docs/AI_AGENT_WORKFLOW.md` for safe usage patterns.

Recommended workflow:

1. Keep your profile updated in the app.
2. Open an application detail view.
3. Copy the generated AI brief.
4. Paste the brief and a job posting into your assistant.
5. Ask for a tailored cover letter, follow-up email, or interview prep.

Assistants should never invent experience, credentials, employers, or compensation history.

## Screenshot

Add your own screenshot after you customize the app. Do not include personal application data in public screenshots.

## Development

The app is intentionally dependency-free:

- `index.html` contains the HTML, CSS, and JavaScript.
- Browser APIs used: `localStorage`, IndexedDB, FileReader, Blob URLs, and the Clipboard API.
- No npm packages are required.

## License

MIT. See `LICENSE`.
