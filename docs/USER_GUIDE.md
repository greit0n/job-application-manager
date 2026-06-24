# User Guide

## Open The App

Open `https://jobs.fezle.io` and sign in. The app is server-backed: profiles,
applications, and document metadata live in Postgres; CVs, postings, generated
PDFs, ZIPs, and proof files live in Cloudflare R2.

## First-Time Setup

On first login, complete the required sender details:

- Name.
- Address.
- Phone.
- Email.

Then upload at least one CV variant in the `CVs` tab. The generated letter and
email are grounded in the uploaded CV text, so a readable CV is required before
document generation.

## Apply To A Job

Use `Apply to job` for the main workflow:

1. Drop the posting by pasting text, pasting a URL, or uploading a PDF/image.
2. Confirm company, role, language, source, location, salary, deadline, channel,
   and recipient details.
3. Generate the packet. Keep `Auto-pick best CV` unless you want to force a CV.
4. Review the packet, copy the email, create a Gmail draft, download the ZIP, or
   mark the application as applied.

If you edit the generated letter or email, use `Save edits`. The app regenerates
the stored PDF/TXT packet files so ZIP downloads and Gmail drafts use the latest
text.

## Gmail Drafts

Gmail integration creates or updates drafts only. It does not send emails.

Connect Gmail when prompted, then use `Create Gmail draft` from the packet review.
The draft is created in your Gmail account with the generated email and current
packet attachments. Review and send it from Gmail.

## Manage Applications

Open an application to manage:

- Status.
- Next action.
- Follow-up date.
- Recipient name and email.
- Application channel.
- Selected CV.
- Company, role, source, URL, deadline, salary, and notes.

The dashboard `Needs attention` queue is action-based. It highlights missing
packets, ready-to-send applications, follow-ups, interviews, and offers.

## Documents And Proofs

Each application stores its posting, generated letter, generated email, ZIP, and
proof files. Upload proof files such as confirmation screenshots, interview
invitations, rejection messages, and offers.

Do not commit real CVs, postings, letters, screenshots, exports, `.env` files,
OAuth tokens, database dumps, or R2 keys to the repository.
