# Makefile — Shortcuts for running experiment workflows
#
# Run `make` or `make help` to see available commands.

.DEFAULT_GOAL := help

.PHONY: help validate distribute verify-local test-e2e deploy setup-prod migrate clean clean-all supabase-start supabase-stop sync-verify lint-template lint-template-tests lint-template-full

help: ## Show this help message
	@echo "Usage: make <command>"
	@echo ""
	@echo "Commands:"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'
	@echo ""
	@echo "AI skills (run in Claude Code):"
	@echo "  /bootstrap       Scaffold the full MVP from experiment.yaml"
	@echo "  /change ...      Make a change (e.g., /change fix the signup button)"
	@echo "  /iterate         Review metrics and get recommendations"
	@echo "  /retro           Run a retrospective and file feedback"
	@echo "  /distribute      Generate distribution campaign config from experiment.yaml"
	@echo "  /verify          Run E2E tests and fix failures"
	@echo "  /deploy          Deploy to Vercel + Supabase (first-time setup)"
	@echo "  /review          Automated review-fix loop (maintainers only)"

sync-verify: ## Sync VERIFY commands from state-registry.json to state files
	@bash .claude/scripts/sync-verify-to-state-files.sh

sync-archetype-summaries: ## Sync canonical Summary Lines from archetype-behavior-check.md to embedding files
	@python3 scripts/sync-archetype-summaries.py --apply

test-verify-semantics: ## Behavioral tests for review skill VERIFY semantics (#928 regression guard)
	@python3 .claude/scripts/tests/test_verify_semantics.py

# CI-ONLY: python3 scripts/ci-check-graduation-atomicity.py, bash .claude/scripts/stack-knowledge-audit.sh, python3 scripts/print-stack-knowledge-files.py, python3 scripts/lint-verification-snippets.py, bash .claude/scripts/synthetic-regression-injection.sh
# (validators that require PR context, run on a schedule, or are CI shims —
# parsed by scripts/consistency-check.sh Check 20. print-stack-knowledge-files.py
# is a pure path-enumeration shim consumed only by .github/workflows/stack-knowledge-validate.yml.
# lint-verification-snippets.py requires shellcheck; runs only in the CI workflow that installs it.
# synthetic-regression-injection.sh creates a sandbox via .runs/_test, mutates files, and runs the
# linter against it — meant for the falsification-tests CI workflow only, not local fast lint.)
lint-template: ## Fast: run validators against .claude/ content (~1-3s; no validator unit tests)
	@echo "== lint-template: running all CI-bound template validators =="
	@echo "-- validate-frontmatter --"
	@python3 scripts/validate-frontmatter.py
	@echo "-- validate-semantics --"
	@python3 scripts/validate-semantics.py
	@echo "-- validate-convergence-config --"
	@python3 scripts/validate-convergence-config.py
	@echo "-- consistency-check --"
	@bash scripts/consistency-check.sh
	@echo "-- ci-check-stack-knowledge --"
	@python3 scripts/ci-check-stack-knowledge.py
	@echo "-- validate-stack-knowledge (per-file) --"
	@files=$$(find .claude/stacks -type f -name '*.md' ! -name '*.archive.md' | sort); \
	if [ -n "$$files" ]; then \
	  python3 scripts/validate-stack-knowledge.py $$files; \
	else \
	  echo "  (no live stack files — skipped)"; \
	fi
	@echo "-- state-registry drift + cross-file coherence (DRIFT_DECLARED_VS_PROSE | CROSS_FILE_CONTRADICTION) --"
	@OUTPUT=$$(bash .claude/scripts/verify-linter.sh 2>&1); \
	echo "$$OUTPUT" | grep -E '^(DRIFT_DECLARED_VS_PROSE|CROSS_FILE_CONTRADICTION)' || true; \
	if echo "$$OUTPUT" | grep -qE '^(DRIFT_DECLARED_VS_PROSE|CROSS_FILE_CONTRADICTION)'; then \
	  echo "FAIL: template coherence violations detected (see above)"; \
	  exit 1; \
	else \
	  echo "  no drift, no cross-file contradictions"; \
	fi
	@echo "-- test-template-coherence (#1128 evidence-channel regression guard) --"
	@bash scripts/test-template-coherence.sh
	@echo "-- check-worktree-ownership-pattern (#1200 recurrence guard) --"
	@python3 .claude/scripts/check-worktree-ownership-pattern.py
	@echo ""
	@echo "== All CI-bound template validators passed. Safe to push .claude/ edits. =="

lint-template-tests: ## Slow: run pytest on validator unit tests (~27s; include when scripts/ changes)
	@echo "== lint-template-tests: running pytest scripts/ =="
	@python3 -m pytest scripts/ -v --tb=short

lint-template-full: lint-template lint-template-tests ## Full local mirror of CI (both targets)

validate: ## Check experiment.yaml for valid YAML, TODOs, name format, and structure
	@echo "Validating experiment/experiment.yaml..."
	@if [ ! -f experiment/experiment.yaml ]; then \
		echo "Error: experiment/experiment.yaml not found. Copy the example: cp experiment/experiment.example.yaml experiment/experiment.yaml"; \
		exit 1; \
	fi
	@command -v python3 >/dev/null 2>&1 || { \
		echo "Error: Python3 is required for validation but was not found."; \
		echo "Fix: install Python3 from https://python.org (or: brew install python3)"; \
		exit 1; \
	}
	@python3 -c "import yaml" 2>/dev/null || { \
		echo "Error: PyYAML is not installed (needed for YAML validation)."; \
		echo "Fix: run 'pip3 install pyyaml' (if that fails: 'pip3 install --user pyyaml' or 'brew install python-pyyaml')"; \
		exit 1; \
	}
	@python3 -c "import yaml; yaml.safe_load(open('experiment/experiment.yaml'))" 2>/dev/null || { \
		echo "Error: experiment/experiment.yaml has invalid YAML syntax."; \
		echo "Check for indentation errors or missing colons."; \
		exit 1; \
	}
	@# Exclude YAML comment lines (^<whitespace>#) before checking for TODO so the
	@# template preamble sentence "Replace every TODO value…" does not trip a false
	@# positive. Inline comments on value lines (e.g., `name: foo  # TODO`) and
	@# block-literal continuations still match. Line numbers reflect the original
	@# file so users see the real placeholder locations. (#1053)
	@NON_COMMENT_TODOS=$$(awk '!/^[[:space:]]*#/ && /TODO/ { printf "%d:%s\n", NR, $$0 }' experiment/experiment.yaml); \
	if [ -n "$$NON_COMMENT_TODOS" ]; then \
		echo ""; \
		echo "Found TODO placeholders that need to be filled in:"; \
		echo "$$NON_COMMENT_TODOS"; \
		echo ""; \
		echo "Replace every TODO before running make bootstrap."; \
		exit 1; \
	fi
	@# validate-experiment.py checks: name format, archetype structure, required fields, stack files, testing warning, assumes
	@STACK_WARN=0; \
	python3 scripts/validate-experiment.py || STACK_WARN=$$?; \
	if [ "$$STACK_WARN" -ne 0 ] && [ "$$STACK_WARN" -ne 2 ]; then echo "Experiment validation failed — fix the errors above in experiment/experiment.yaml, then re-run 'make validate'."; exit 1; fi; \
	if [ -f experiment/EVENTS.yaml ]; then \
		python3 scripts/validate-events.py || exit 1; \
		echo "experiment/EVENTS.yaml looks good — valid structure."; \
	else \
		echo "Warning: experiment/EVENTS.yaml not found — /bootstrap will fail. Ensure experiment/EVENTS.yaml exists in the experiment/ folder."; \
	fi; \
	python3 scripts/validate-semantics.py || { echo "Semantic validation failed — fix the errors above, then re-run 'make validate'."; exit 1; }; \
	if [ "$$STACK_WARN" -eq 2 ]; then \
		echo "Validation passed with warnings — review the issues above. These are non-blocking but should be addressed before /bootstrap."; \
	else \
		echo "Validation passed — experiment.yaml and experiment/EVENTS.yaml look good."; \
	fi; \
	if [ -f package.json ]; then \
		echo "Note: project is already bootstrapped. Open Claude Code and run /change to make changes."; \
	fi

distribute: ## Validate experiment/ads.yaml (valid YAML, schema, budget limits)
	@if [ ! -f experiment/ads.yaml ]; then echo "No experiment/ads.yaml found. Run /distribute in Claude Code to generate it."; exit 0; fi; \
	python3 -c "import yaml; yaml.safe_load(open('experiment/ads.yaml'))" 2>/dev/null || { echo "Error: experiment/ads.yaml has invalid YAML syntax."; exit 1; }; \
	python3 -c "import sys, yaml; sys.path.insert(0, 'scripts'); from validators import check_ads_for_distribute; raw = yaml.safe_load(open('experiment/ads.yaml')); data = raw if isinstance(raw, dict) else {}; errors = check_ads_for_distribute(data, 'experiment/ads.yaml'); [print(e) for e in errors]; budget = data.get('budget', {}) if isinstance(data.get('budget', {}), dict) else {}; sys.exit(1) if errors else print('experiment/ads.yaml looks good — valid ' + str(data.get('channel', 'google-ads')) + ' schema.' + ((' CAP OVERRIDE ACTIVE (approved by ' + str(budget.get('cap_override_approved_by')) + '): total $$' + str(budget.get('total_budget_cents', 0) // 100) + '.') if budget.get('cap_override_approved_by') else ''))"

playbook-docx: ## Generate the team playbook docx from google-ads.md (OUT=<path> to override; default .runs/google-ads-playbook.docx)
	@test -x .venv-docx/bin/python || { echo "Creating .venv-docx (one-time)..."; python3 -m venv .venv-docx && .venv-docx/bin/pip -q install python-docx; }
	@mkdir -p .runs
	@.venv-docx/bin/python scripts/generate_playbook_docx.py --repo . --out "$(or $(OUT),.runs/google-ads-playbook.docx)"

supabase-start: ## Start local Supabase (delegates to ensure-supabase-start.sh for skill-ownership tracking)
	@bash .claude/scripts/ensure-supabase-start.sh

supabase-stop: ## Stop local Supabase
	-npx supabase stop

verify-local: ## Verify the app works locally (install, test, cleanup)
	@bash scripts/verify-local.sh

test-e2e: ## Run E2E / integration tests
	@if [ -f playwright.config.ts ]; then \
		npx playwright test; \
	elif [ -f vitest.config.ts ]; then \
		npx vitest run; \
	else \
		echo "No test configuration found — run '/change add tests' to set up testing"; \
	fi

# Default: Vercel. Update this target if you change stack.hosting.
deploy: ## Deploy to Vercel (first run will prompt to link project)
	@if [ ! -f package.json ]; then \
		echo "Error: No package.json found. Run /bootstrap first."; \
		exit 1; \
	fi
	@if [ -f experiment/experiment.yaml ]; then \
		HOSTING=$$(python3 -c "import yaml; d=yaml.safe_load(open('experiment/experiment.yaml')); print(next((s.get('hosting','') for s in d.get('stack',{}).get('services',[]) if isinstance(s,dict)),d.get('stack',{}).get('hosting','')))" 2>/dev/null); \
		ARCHETYPE=$$(python3 -c "import yaml; d=yaml.safe_load(open('experiment/experiment.yaml')); print(d.get('type','web-app'))" 2>/dev/null); \
		if [ -z "$$HOSTING" ] && [ "$$ARCHETYPE" = "cli" ]; then \
			echo "CLI archetype detected. Use 'npm publish' to publish to npm, or create a GitHub Release."; \
			echo "For the marketing surface (if configured): run '/deploy' in Claude Code."; \
			exit 1; \
		fi; \
		if [ -n "$$HOSTING" ] && [ "$$HOSTING" != "vercel" ]; then \
			echo "Warning: stack.hosting is '$$HOSTING', but this Makefile only supports Vercel."; \
			echo "Use the /deploy skill in Claude Code — it reads your hosting stack file and handles any provider."; \
			echo "Or deploy directly from your terminal using your hosting provider's CLI."; \
			exit 1; \
		fi; \
	fi
	@echo "Deploying to Vercel..."
	npx vercel deploy --prod
	@echo "Checking deployment health..."
	@DEPLOY_URL=$$(npx vercel inspect --json 2>/dev/null | python3 -c "import sys,json; print('https://'+json.load(sys.stdin).get('alias',[''])[0])" 2>/dev/null); \
	if [ -n "$$DEPLOY_URL" ] && curl -sf "$$DEPLOY_URL/api/health" > /dev/null 2>&1; then \
		echo "Health check passed: $$DEPLOY_URL/api/health"; \
	else \
		echo "Warning: Could not verify health endpoint. Check your deployment manually."; \
	fi
	@echo ""
	@echo "Note: 'make deploy' does not create .runs/deploy-manifest.json."
	@echo "The /teardown and /iterate skills require this manifest. For full lifecycle"
	@echo "support (teardown, iterate, distribute), use the /deploy skill in Claude Code instead."

setup-prod: ## Link Vercel + Supabase for production debugging
	@if [ ! -f package.json ]; then \
		echo "Error: No package.json found. Run /bootstrap first."; \
		exit 1; \
	fi
	@echo "Linking Vercel project..."
	@npx vercel link || { echo "Error: run 'npx vercel login' first, then retry."; exit 1; }
	@echo ""
	@echo "Linking Supabase project..."
	@if [ ! -f experiment/experiment.yaml ]; then \
		echo "Error: experiment/experiment.yaml not found."; exit 1; \
	fi
	@REF=$$(python3 -c "import yaml; d=yaml.safe_load(open('experiment/experiment.yaml')); print(d.get('supabase_project_ref',''))" 2>/dev/null); \
	if [ -n "$$REF" ]; then \
		npx supabase link --project-ref "$$REF"; \
	else \
		echo "Enter your Supabase project ref (Dashboard → Settings → General → Reference ID):"; \
		read -r REF; \
		npx supabase link --project-ref "$$REF"; \
	fi
	@echo ""
	@echo "Done. Claude Code can now debug production issues directly."

migrate: ## Push pending migrations to remote Supabase database
	@if [ ! -f package.json ]; then \
		echo "Error: No package.json found. Run /bootstrap first."; \
		exit 1; \
	fi
	@if [ ! -d supabase/migrations ]; then \
		echo "Error: supabase/migrations/ not found. No migrations to push."; \
		exit 1; \
	fi
	@if [ -z "$$(ls -A supabase/migrations/ 2>/dev/null)" ]; then \
		echo "No migration files in supabase/migrations/. Nothing to push."; \
		exit 0; \
	fi
	@echo "Pushing migrations to remote Supabase..."
	npx supabase db push
	@echo "Migrations applied successfully."

# Default artifacts for all archetypes. Update if you change stack.framework or stack.ui.
# DO NOT delete .claude/commands/, .claude/patterns/, .claude/stacks/,
# .claude/archetypes/, .claude/hooks/, .claude/scripts/, .claude/agents/,
# .claude/procedures/, .claude/orchestration/ — these are template-owned.
clean: ## Remove generated files (lets you re-run bootstrap)
	rm -rf node_modules .next out                          # framework/nextjs
	rm -rf dist                                            # framework/hono, framework/commander
	rm -f .nvmrc package.json package-lock.json tsconfig.json next.config.ts next-env.d.ts eslint.config.mjs  # framework/nextjs
	rm -f components.json tailwind.config.ts .eslintrc.json eslint.config.mjs postcss.config.mjs  # ui/shadcn
	rm -rf src                                             # all generated app code
	rm -f .env.example                                     # all stacks
	rm -rf e2e playwright.config.ts test-results playwright-report blob-report  # testing/playwright
	rm -rf tests vitest.config.ts                          # testing/vitest
	rm -rf public docs                                     # bootstrap-generated assets and docs
	rm -rf public/images                                   # images/fal
	rm -rf .runs .verify-baseline                          # skill execution state
	rm -rf .vercel                                         # Vercel CLI config
	rm -f vercel.json tsconfig.tsbuildinfo                 # deploy and build config
	rm -f externals-decisions.json run-skill.sh            # bootstrap artifacts
	rm -f .gitleaks.toml                                   # bootstrap-generated config
	rm -f .env.local .env                                  # runtime credentials
	@echo "Cleaned. You can now open Claude Code and run /bootstrap again."
	@echo "Note: experiment/experiment.yaml, experiment/EVENTS.yaml, and supabase/ were NOT removed. Use 'make clean-all' for a full reset."

clean-all: ## Remove everything including migrations (full reset)
	@echo "This will delete ALL generated files including database migrations."
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || { echo "Cancelled."; exit 1; }
	$(MAKE) clean
	rm -rf supabase
	@echo "Full reset complete. You can now open Claude Code and run /bootstrap again."
