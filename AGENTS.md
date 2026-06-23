# Job Application Manager - Agent Instructions

## Purpose

This repository is a public, generic, local-first job application manager. It is not tied to one candidate, country, employer, job board, or folder convention.

Agents should help users manage application data, reason about CV variants, write application materials, prepare for interviews, and keep private data out of Git.

## Core Product Rules

- The app is `index.html`, a dependency-free static browser app.
- Users manage CVs and proof files from inside the app.
- Users are not required to put CVs, screenshots, or application files into repository folders.
- Structured data is stored in `localStorage` under `jobApplicationManager:v1`.
- Uploaded files are stored in IndexedDB under `jobApplicationManager:v1`.
- Exported backup JSON files can contain private CVs and proof files.
- Never commit real CVs, proof files, backups, screenshots, application documents, or personal profile exports.

## Privacy Rules

- Treat all candidate data, CVs, proof files, and application notes as private.
- Do not publish real application history, contact details, salary notes, screenshots, or correspondence.
- Before publishing, search the repo for personal names, contact details, real employer names, private filenames, and exported backups.
- If a user provides private material for drafting, use it only for the requested output.
- Do not invent experience, credentials, employers, projects, education, language levels, compensation, or availability.

## How To Help With Applications

When a user provides a job post or application target:

1. Extract company, role, location, salary, source, application URL, deadline, tasks, and requirements.
2. Compare the role against the candidate profile and uploaded CV variant notes.
3. Recommend the best CV variant by name, with a short reason.
4. Draft role-specific application text only from the user's real background.
5. Flag missing information instead of guessing.
6. Suggest concise tracker notes that can be pasted into the app.

## Cover Letter Guidance

- Match the language and tone requested by the user.
- Keep the text specific to the role and company.
- Show a clear bridge between job requirements and the candidate's actual experience.
- Do not overstate gaps. Frame transferable experience honestly.
- Keep email bodies shorter than full cover letters.
- Do not mention that the user was instructed, referred by an agency, or required to apply unless the user explicitly wants that.

## Interview Preparation Guidance

When a user reports an interview:

1. Summarize the company and role from the provided posting or notes.
2. Build likely questions and concise answer outlines.
3. Include a self-introduction, motivation, strengths, gap framing, salary expectations, availability, remote or office preference, and questions to ask the employer.
4. Use the candidate's real experience and profile.
5. Prepare practical reminders, but avoid generic filler.

## App Editing Rules

If editing the app:

- Keep it static and dependency-free unless the user explicitly changes the project direction.
- Keep private storage browser-only.
- Preserve export/import compatibility where practical.
- Maintain responsive layout for mobile and desktop.
- Do not add tracking, analytics, external API calls, or remote storage by default.
- Keep `AGENTS.md` and `CLAUDE.md` equivalent unless the user asks for tool-specific divergence.

## Publishing Checklist

Before committing or pushing:

- Confirm no private PDFs, images, screenshots, backups, or application packages are tracked.
- Search for private names, contact details, real employers, private job-board references, and local machine paths.
- Confirm `.gitignore` excludes private data.
- Confirm `index.html` opens without a build step.
- Confirm the README explains the privacy model clearly.
