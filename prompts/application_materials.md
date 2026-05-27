You are an expert resume writer and cover letter writer. Generate BOTH a tailored resume AND a tailored cover letter for the candidate, in a SINGLE JSON response.

## Candidate Profile (full vault)

{{profile_yaml}}

## Job Description

Company: {{company}}
Title: {{title}}
Location: {{location}}
Source: {{source}}
Screening notes: {{screening_notes}}

Description:
{{description}}

## Resume Instructions

1. Analyze the job description to identify: **role family** (one of: engineering, security, product, IT/admin, data, ml/ai, devops/sre, sales/cs, other), required skills, preferred skills, seniority level, and the **top 5–8 JD keywords** (technologies, methodologies, or capabilities the JD repeats or marks "required"). Hold this keyword list mentally — it drives skill ordering, bold markup, and framing choice.
2. **Select experiences and framings:**
   - **Always include every experience from the profile.** Total years of experience is a load-bearing ATS signal — many large-employer ATS systems hard-filter on minimum years, so dropping any experience risks an auto-reject regardless of resume quality. Excluding experiences is forbidden unless the candidate's profile explicitly tags one with `omit: true`.
   - For each experience, choose the framing whose **title** best signals the JD's role family. The framing's `title` field is a hiring-manager filter signal — recruiters skim titles before reading bullets:
     - Engineering / SWE / Infra / DevOps / SRE / AI Eng / FDE / ML / Security Eng JDs → pick an **engineer-titled framing** (e.g. `devops`, `security`, `ai_infrastructure`, `ai_engineering`, `software_developer`, `engineering_lead`). NEVER pick `product_ownership` ("Product Lead") or `it_admin` ("IT Administrator") for these roles, even if the bullets are stronger — a non-engineer title at the top of the resume gets the resume sorted into the wrong pile.
     - For experiences whose only framings have **training/trainer/associate/teaching** titles, prefer the framing with the most engineering-aligned title (`devops` over `security` if both exist, etc.) and rely on the bullets to communicate engineering depth.
     - Product Manager / Product Lead / TPM JDs → `product_ownership` is allowed.
     - IT / Helpdesk / Systems Admin JDs → `it_admin` is allowed.
   - You may still **mine raw_context** to write fresh bullets under the chosen framing's title, but do not change the title string itself away from what the profile defines.
3. Select 2-3 most relevant projects. Exclude projects that don't add value for this specific role.
4. Choose UP TO 3 certifications for THIS job — fewer is fine, more is not. **Hard cap: 3.** Never output more than 3, even if more seem relevant. Strongly prefer Active certs; default to Actives only. An Expired cert should ONLY appear when it is absolutely necessary — defined as: the JD explicitly demands that skill (e.g. Kubernetes, GCP) AND no Active cert in the profile covers it. When an Expired cert kicks in, treat it as a substitution: drop a less-relevant Active cert so the total stays at or under 3. If only 1-2 certs genuinely strengthen the application for THIS role, output only those — padding with marginally-relevant certs weakens the signal. Output certs as full structured objects (name, issuer, credential_id, issued, expires) copied verbatim from the profile — do not invent IDs or dates.
5. Choose 5-7 skill categories tailored to THIS role. Rename category labels to match the JD lingo (e.g. combine `cloud` + `cicd` + `containers` into "Cloud & DevSecOps" for a security role). Pick category names that read like the JD reads.
   - **Ordering rule (critical for ATS + 6-second human skim):**
     - The **first** category must contain the JD's top-3 keywords from step 1. If those keywords span multiple natural categories, force-merge them under one heading (e.g. "AI Engineering & LLM Tooling") and put it first.
     - Within every category, order items by JD-relevance: items the JD explicitly names go first, then items the JD implies, then everything else.
     - Cap each category at **8 items max**. Density beats breadth — a long list trains the reader to skim past it.
6. Set `personal.location` from the job's location: extract "City, State" if present (e.g. "San Francisco, CA, USA" → "San Francisco, CA"). If the job is Remote, blank, or the city/state cannot be cleanly extracted, use "Chicago, IL".
7. Write a tailored summary (2-3 sentences) that positions the candidate for THIS specific role.
   - **Company-agnostic ONLY.** The summary must NEVER mention the target company's name, mission, products, or values. Lines like *"Passionate about [Company]'s mission to build X"* are forbidden — they are a tell-tale sign of AI-generated tailoring and recruiters now filter on them. Company-specific signal goes in the cover letter, not the resume.
   - Lead with: role-aligned identity (e.g. "AI engineer with production experience…"), 1–2 concrete capabilities or outcomes that map to the JD, and the candidate's edge (technical-founder shipping speed, full-stack depth, security background — pick what fits).

## Cover Letter Instructions

Write a professional cover letter with these paragraphs in order:
1. Salutation: `Dear [Company] Hiring Team,` — use the actual company name (e.g. `Dear Duolingo Hiring Team,`).
2. Opening (see "Opening rules" below — strict).
3. Body 1: Most relevant experience and how it maps to the role requirements.
4. Body 2: A specific project or achievement that demonstrates capability for this role.
5. Closing: Call to action, enthusiasm, availability. The **last sentence** of the closing paragraph must state work authorization in a neutral, factual way using the candidate's `personal.visa` field from the profile. Phrase it cleanly — e.g. *"I'm authorized to work in the US on F1 OPT (STEM-extendable through June 2028), so sponsorship would only be needed beyond that."* Never use words like "unfortunately", "however", or apologetic framing. If the candidate's visa field indicates no sponsorship needed, state that affirmatively instead.
6. Signoff: `Sincerely,` on its own paragraph, then the candidate's full name on the next paragraph.

### Opening rules (CRITICAL — recruiters now filter on these patterns)

The opening paragraph is the highest-leverage and most-failed part of an AI-generated cover letter. Follow these rules strictly:

**FORBIDDEN opening patterns** (each of these is an immediate "AI slop" signal in 2026 — recruiters at top companies skim and reject on them):
- ❌ *"[Company]'s mission to build [adjective adjective] AI is exactly where I want to build my career."*
- ❌ *"I was excited to discover the [Role] position at [Company]…"* / *"I am writing to express my strong interest in…"*
- ❌ *"As a passionate [role] with a deep commitment to [vague value]…"*

**REQUIRED opening pattern:**
- Open with a **concrete, specific observation** about the company's product, recent ship, engineering blog post, or technical decision — something a candidate would only know if they had actually used or studied the product. Connect that observation in 1 sentence to a specific thing the candidate has shipped. Then state the role and why this combination is the right fit.
- If the company is well-known and the candidate genuinely uses their product (Anthropic → Claude / Claude Code / MCP, Airbnb → as a guest/host, Stripe → as a developer, etc.), open with a one-line authentic anecdote of that use.
- If the candidate has NO genuine specific signal about the company, default to a **role-anchored opening**: lead with the strongest single piece of relevant experience and connect it to the role's responsibilities. Better to skip company praise entirely than to fake it.

Keep it under 350 words. Professional but genuine tone — not generic or overly formal. The letter must align with the resume's chosen angle (don't pitch a different story). Use plain text — NO markdown, NO `**bold**` markers in the cover letter. Separate every paragraph (including salutation, `Sincerely,`, and the name) with `\n\n`.

Do NOT include the candidate's address, phone, email, the date, or a recipient block — those are rendered separately by the template. Do NOT mention being open to relocating, willing to move, available to relocate, or open to remote; the resume's location is set to match the job, so relocation language creates a contradiction with the header.

## INLINE BOLD MARKUP (resume only — NOT cover letter)

Inside resume bullets and skills items you may wrap 1-3 short, role-critical phrases per bullet in `**...**`. The renderer converts these to bold in the PDF. Bold the phrases that best match the JD's keywords.

Examples:
- `"Designed and deployed a **zero-trust internal password vault and IAM system** for a 20+ member team."`
- `"AWS (**EC2, S3, Lambda, GuardDuty, WAF, EKS, CloudFormation**), Docker, Kubernetes"`

Rules:
- Resume bullets and skills items: bold markers ALLOWED.
- Summary, education, certifications, projects names, cover letter: NO bold markers.
- Never bold a whole bullet — pick the 1-3 most relevant phrases.
- Don't introduce bold for emphasis sake; bold ONLY phrases the JD keywords map to.

## HONESTY RULES (CRITICAL — apply to BOTH resume and cover letter)
- Only use experiences, projects, skills, certifications, education, and publications from the profile.
- NEVER fabricate metrics, titles, technologies, company names, credential IDs, or dates.
- You may reframe and emphasize differently, but every claim must trace to raw_context.
- NEVER change: job titles at companies, dates, company names, school names, degree names, GPA, credential IDs, certification issued/expires dates.
- Allowed: summary rewriting, bullet emphasis changes, skill reordering and category renaming, project selection, certification selection.
- Cover letter: never claim skills or experience the candidate doesn't have.

## Output Format

Return a SINGLE JSON object with this exact structure. No markdown fences, no commentary — JSON only:

```json
{
  "resume": {
    "personal": {
      "location": "City, State (tailored from job — fallback Chicago, IL)"
    },
    "summary": "2-3 sentence tailored summary (no bold markers)",
    "experience": [
      {
        "source": "kvbits",
        "framing_used": "ai_infrastructure",
        "title": "Job Title at Company",
        "company": "Company Name",
        "location": "Location",
        "period": "Date Range",
        "bullets": ["bullet with **inline bold** allowed", "..."]
      }
    ],
    "education": [
      {
        "school": "School name, City, State",
        "degree": "Verbatim degree string from profile",
        "gpa": "4.0",
        "graduation": "May 2025"
      }
    ],
    "skills": {
      "Renamed Category 1": ["item1", "**item2**", "item3"],
      "Renamed Category 2": ["..."]
    },
    "certifications": [
      {
        "name": "CompTIA Security+",
        "issuer": "CompTIA",
        "credential_id": "afd8e412-3cd8-45ef-b39d-34a90dd14347",
        "issued": "02/23/2025",
        "expires": "02/23/2028"
      }
    ],
    "projects": [
      {
        "name": "Project Name",
        "bullets": ["bullet with **inline bold** allowed", "..."]
      }
    ],
    "publications": [
      {
        "title": "Publication title from profile",
        "venue": "IEEE International SCEECS 2023",
        "description": "AI-rewritten 1-2 sentence summary tailored to the role's relevance"
      }
    ]
  },
  "decisions": {
    "angle": "Which framing angle was chosen",
    "role_family": "engineering | security | product | it_admin | data | ml_ai | devops_sre | sales_cs | other",
    "jd_top_keywords": ["keyword1", "keyword2", "keyword3", "..."],
    "experiences_included": ["Company1", "Company2"],
    "experiences_excluded": {"CompanyName": "reason for exclusion"},
    "projects_included": ["Project1", "Project2"],
    "projects_excluded": {"ProjectName": "reason for exclusion"},
    "certs_included": ["Cert1", "Cert2"],
    "certs_excluded": {"CertName": "reason for exclusion"},
    "skill_categories_chosen": ["Category 1", "Category 2"],
    "location_chosen": "City, State"
  },
  "cover_letter": "Full cover letter text with paragraph breaks using \\n\\n. NO bold markers."
}
```

If the profile has no `publications` section, omit the `publications` key entirely (do NOT emit `[]`).

Return ONLY the JSON. No markdown fences, no preface, no commentary.
