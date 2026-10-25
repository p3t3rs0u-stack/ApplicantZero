# Hackathon submission – Aaltoes prompthack / Velho challenge

## Project name
Applicant Zero

(alternatives: "Velho Applies", "The Applicant That Never Sleeps")

## One-line pitch (≤90 chars)
An AI agent that applies to routine jobs, offering Velho in place of the hire.

## Description

**The problem**
Every ad for an accounting assistant or office coordinator is a company saying in public: "we have repetitive work and we're about to pay ~€55k a year for it." It's the warmest sales lead there is, yet nobody sells to it, because qualifying and reaching each one takes hours.

**What we built**
Applicant Zero applies for the job, with Velho as the applicant:
1. **Finds** routine office roles on Duunitori. In our run, 63 of 154 ads were a fit.
2. **Analyses** each role task by task. Example: 65 % automatable, ~€38k/year saved.
3. **Writes** a surprising application, "the applicant who works 24/7 and never takes sick leave", plus a one-page proposal built from the ad's own task list.
4. **Fills** the real application form in ~6 s across 5 different ATS systems: the CV, the logo as the photo, every field and every consent box.
5. **Reaches** the decision-maker. It finds and ranks the CEO/CFO, then drafts a Gmail email and a LinkedIn message.

A human always presses send. No guessed emails, no auto-submit, no LinkedIn automation.

**How it works and what's AI**
Python pipeline, with Claude reasoning at every step:
1. **Search:** Playwright scrapes Duunitori listings into SQLite.
2. **Analysis:** Claude Opus, with structured outputs, turns each ad into per-task automation estimates, a yearly saving and a 0–100 fit score.
3. **Writing:** Opus writes the cover letter in the ad's language. fpdf2 renders the one-page proposal.
4. **Form filling:** a JS collector extracts each field's label, question context and accepted file types. Claude Sonnet maps our profile onto forms it has never seen, and Playwright fills them in parallel tabs. Submit buttons are hard-blocked.
5. **Outreach:** Claude with web search finds and ranks decision-makers. Each email is kept only if it appears on the cited source page.

Local Flask dashboard. Under €0.25 per lead.

**What's next**
Pilot with Velho and measure meetings against cold outreach. Add the Työmarkkinatori API, reply tracking and CRM export. Then open it to any automation company: every hiring ad becomes an inbound lead.

## Screenshots (first = cover)

1. **demo/1_lista.png**: 154 job ads scanned and scored. 63 are routine work Velho can take over.
2. **demo/2_arvio.png**: Claude breaks the role into tasks: 65 % automatable, ~€38k/year saved.
3. **demo/3_pdf.png**: Every application comes with a one-page proposal built from the ad's own task list.
4. **demo/4_lomake.png**: The real application form, filled in ~6 s with the Velho logo as the photo. A human presses send.
5. **demo/5_johto.png**: After applying, the agent finds and ranks the decision-makers and drafts their messages.

## Links
- Demo: (local app – show live, or add video link)
- Repo: (GitHub URL after push)
- Video: (optional 60–90 s screen recording)
- Slides: –
