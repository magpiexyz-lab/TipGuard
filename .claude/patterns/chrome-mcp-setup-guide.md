# Chrome MCP Setup Guide for Google Ads

When Claude Code detects that Chrome MCP tools are not available, show
this guide to the user. Reference this file — do NOT inline a shortened
version (users need the full steps).

**Requirements:** Claude Code >= 2.0.73, Chrome extension >= 1.0.36,
direct Anthropic plan (Pro/Max/Team/Enterprise — not Bedrock/Vertex/Foundry).

---

## Step 1: Install the Claude in Chrome Extension

1. Open Google Chrome
2. Go to the Chrome Web Store and search for **"Claude"** by Anthropic
   (or visit https://chromewebstore.google.com/detail/claude/fcoeoabgfenejglbffodgkkbkcdhcgfn)
3. Click **"Add to Chrome"** → Confirm the installation
4. You should see the Claude icon appear in your Chrome toolbar (top-right)

## Step 2: Enable Chrome in Claude Code

1. In your Claude Code terminal, run `/chrome`
2. Select **"Enable by default"** — this saves the setting so Chrome MCP
   loads automatically on every future session
3. **Exit Claude Code** (type `/exit` or Ctrl-C) and **start a new session**
   — Chrome MCP tools only load at session startup, so they won't appear
   until you re-enter
4. **Restart Chrome** if this is your first time — Chrome must be restarted
   to detect the newly installed native messaging host config file

Alternatively, start a one-off session with `claude --chrome` (no restart
needed, but Chrome tools won't persist to future sessions).

## Step 3: Verify the Connection

1. In the new Claude Code session, run `/chrome` — it should show
   **"Connected"** status
2. Claude Code should now detect `mcp__claude-in-chrome__*` tools
3. If it shows "Chrome extension not detected", see Troubleshooting below

## Step 4: Log into Google Ads

1. In Chrome, go to https://ads.google.com
2. Log in with your Google account that has access to the team's MCC
3. Make sure you can see your **sub-account** (not the MCC top level)
   - Your campaigns should be visible under your sub-account
4. **Keep this Chrome tab open** — Claude Code will interact with it

## Step 5: Re-run Your Command

Once all steps are done, re-run the command that brought you here:
- `/distribute` — to create a campaign
- `/iterate --check` — to monitor a campaign
- `/iterate --cross` — to evaluate all MVPs (Team Lead only)

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Extension not visible in toolbar | Click the puzzle icon (Extensions) → Pin "Claude" |
| Enabled by default but no tools | Exit Claude Code and start a new session — tools load at startup only |
| `/chrome` shows "not detected" | Restart Chrome, then run `/chrome` → "Reconnect extension" |
| Still not detected after restart | Check `claude --version` is >= 2.0.73 and extension is >= 1.0.36 |
| Native messaging host missing | Run `/chrome` again — it re-installs the host config. Then restart Chrome. |
| Google Ads asks for account selection | Select your sub-account (not the MCC manager account) |
| "You don't have access" in Google Ads | Ask your team lead to add your Google account to the MCC |
