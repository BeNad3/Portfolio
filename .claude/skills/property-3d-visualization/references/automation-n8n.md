# Automating the agency workflow with n8n

Automate the plumbing, never the judgement. The three human gates (dossier questions, layout
approval, final QA/disclosure) stay in the flow as approval steps. Build with the vendored
`n8n-*` skills: start at `using-n8n-mcp-skills`, then `n8n-workflow-patterns`,
`n8n-node-configuration`, `n8n-validation-expert`, `n8n-error-handling`.

## Workflows (one sub-workflow each, see `n8n-subworkflows`)

1. **Intake** (Webhook / Form Trigger) — client uploads photos, plan, measurements, brief →
   create `<project>/00_input/` in storage (Drive / S3 / NAS), strip GPS EXIF from photos
   (privacy), keep a copy of originals, notify the studio.
2. **Analysis draft** (AI Agent node, `n8n-agents`) — vision model reads the plan and photos and
   drafts `property_dossier.json` + `analysis_report.md` with evidence tags and an Unknowns list.
   Output is a **draft**: it goes to a human.
3. **Clarification gate** — email/Slack the Unknowns and Conflicts to the client as one grouped
   question (Wait node "on webhook call" / form resume). Answers are merged into the dossier.
4. **Render job** (Execute Command or HTTP to a render worker) — on the render machine:
   ```bash
   blender -b -P build_shell.py -- 01_analysis/property_dossier.json --out 02_blender/shell.blend --clay-render 02_blender/clay
   python photo_match_overlay.py --photo ... --render ... --out 02_blender/qa/P1.png
   ```
   Fail the run (and alert) if any camera's verdict is `fail`. Later stages open the designer's
   approved `design_vN.blend` and run `photoreal_setup.py` + the final render; use `SplitInBatches`
   over cameras (batch pattern) and a queue if several projects run at once.
5. **QA + delivery gate** — post contact sheet (before/after pairs + overlay sheets) for approval;
   on approval: upscale, add disclosure text, generate alt text, deliver the package, archive.
6. **Status & billing** — scheduled task: project status digest, overdue approvals, render time log.

## Rules

- Credentials in n8n credentials, never in node parameters or code nodes (`n8n-self-hosting` → security).
- Every external call has retry + an error workflow (`n8n-error-handling`); a failed render never
  silently delivers an older image.
- Store the dossier and every approval with a timestamp: that record is what proves the images are
  honest if a buyer or an MLS asks.
- Paid APIs (cloud image models, 3D generation) need an explicit per-project budget and a manual
  approval node before the first paid call.
