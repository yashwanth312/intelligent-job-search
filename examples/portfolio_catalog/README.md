# Example portfolio catalog

This folder is an **optional, advanced** feature and a working example of it.
You do not need it: a plain `profile.yaml` with a `projects:` list is enough.

## What a catalog is

A catalog lets the resume generator draw from projects you **plan** to build,
described as markdown specs, in addition to the built projects in your profile.
Each spec has YAML front matter (`id`, `name`, `tagline`, `skills.core /
supporting / touch`) followed by sections (problem, approach, target metrics,
reference bullets). The 15 specs here are infrastructure-flavoured examples.

Rules the pipeline enforces for catalog projects:

- They are scored for each job exactly like built projects, using the skill
  tags in the front matter (keys from `generation/skill_taxonomy.py`).
- Resume bullets for a catalog project may use **only that spec's target
  metrics**, copied exactly. Placeholders such as `N events/s` are left out.
- Stage 2 screening treats a catalog project that lands on a job's resume as
  built work, so only list projects you actually intend to build and be honest
  about their status before you send a resume.

## Use it

1. Copy a spec, rename it `NN-yourproject.md`, and edit the front matter and body.
2. Point your profile at it (paths are relative to `profile.yaml`):

   ```yaml
   portfolio_catalog:
     - id: yourproject          # must equal `id:` in the spec's front matter
       name: "YourProject"
       spec: examples/portfolio_catalog/01-yourproject.md
   ```

3. Check the picks with `python scripts/replay_project_scorer.py`.

`tests/test_project_scorer.py` loads these specs as fixtures, so they stay valid.
