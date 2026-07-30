# Model Bakeoff

Independent comprehensive comparison of fal.ai image models across all 7 template image slots (+ mockup).

**Not part of the template build.** Sandbox for model selection research.

## Scenario
Inkwell — AI email copilot. Brand colors: #2D4A7C (deep navy) + #E8A87C (warm orange) + #F5F0EB (cream) + #2D2D2D (charcoal).

## Run

```bash
cd scripts/bakeoff
npm install
FAL_KEY=$(cat ~/.fal/key) npm run run
```

## Output

Images: `.runs/model-bakeoff/images/{slot}/{model_safe_name}/v{N}.{ext}`
Metadata: `.runs/model-bakeoff/candidates.json`
Reports: `.runs/model-bakeoff/REPORT.md` (written separately after scoring)
