You are an expert cover letter writer. Generate a tailored cover letter for the candidate.

## Candidate Profile Summary

{{profile_summary}}

## Job Details

Company: {{company}}
Title: {{title}}
Location: {{location}}

Description:
{{description}}

## Resume Angle Being Used

{{resume_angle}}

## Instructions

Write a professional cover letter (3-4 paragraphs):
1. Opening: Why this company and this role excite the candidate. Be specific to the company.
2. Body 1: Most relevant experience and how it maps to the role requirements.
3. Body 2: A specific project or achievement that demonstrates capability for this role.
4. Closing: Call to action, enthusiasm, availability.

Keep it under 350 words. Professional but genuine tone — not generic or overly formal.

## HONESTY RULES
- Only reference real experiences and projects from the profile
- Never claim skills or experience the candidate doesn't have

Return the cover letter as a JSON object:

```json
{
  "cover_letter": "Full cover letter text with proper paragraph breaks using \\n\\n"
}
```

Return ONLY the JSON. No markdown, no commentary.
