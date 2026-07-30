# Given-Auth Matcher

Canonical classification of behavior `given` preconditions as
auth-requiring / auth-free / unknown. Used wherever template code needs to
decide "does this behavior need `e2e/.auth.json` to verify?"

> **Single source of truth.** Both `.claude/procedures/wire.md` (test
> scaffolding) and `.claude/procedures/behavior-verifier.md` (runtime
> verification) MUST consume the classification from this file. Do not
> duplicate the phrase lists anywhere else. The drift test at
> `.claude/scripts/tests/test_given_auth_matcher.py` (case T4) scans the
> repo for stray occurrences of the auth phrases and fails if they
> appear outside this file.

## Inputs

- `given`: the string content of a behavior's `given` field (from
  `experiment/experiment.yaml` → `behaviors[].given`)

## Output

```typescript
{
  result: boolean,              // true if auth is required
  matched_phrase: string | null, // the phrase that matched, for diagnostics
  unmatched: boolean            // true when no known phrase matched (fail-closed)
}
```

## Phrase lists

### Auth-required phrases

Substring match (lowercase). When any appears in the `given` text, auth is
required:

```javascript
const AUTH_PHRASES = [
  "logged-in user",
  "authenticated user",
  "user on dashboard",
];
```

### Auth-free phrases (explicit whitelist)

Phrases that explicitly denote no auth. When any appears, auth is NOT
required:

```javascript
const NON_AUTH_PHRASES = [
  "anonymous visitor",
  "new user",
  "unauthenticated user",
];
```

## Classification function

```javascript
function requiresAuth(given) {
  const g = (given || "").toLowerCase();

  // Helper: word-boundary substring match. Prevents "authenticated user"
  // from matching "unauthenticated user" via naive includes(). The
  // delimiters are word boundaries: start of string OR non-alphanumeric
  // character on either side of the phrase.
  const matches = (phrase) => {
    const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`(^|[^a-z0-9])${escaped}([^a-z0-9]|$)`, "i");
    return re.test(g);
  };

  // Explicit non-auth check FIRST. Rationale: negative specificity
  // (e.g., "unauthenticated user") must override positive matches that
  // would otherwise capture a substring (e.g., "authenticated user").
  // Word-boundary regex above already prevents the substring case, but
  // checking non-auth first is an additional guard for corpora we
  // haven't anticipated.
  for (const p of NON_AUTH_PHRASES) {
    if (matches(p)) {
      return { result: false, matched_phrase: p, unmatched: false };
    }
  }

  // Auth-required check
  for (const p of AUTH_PHRASES) {
    if (matches(p)) {
      return { result: true, matched_phrase: p, unmatched: false };
    }
  }

  // Neither list matched — fail closed.
  // Rationale: the safer default for an unrecognized phrase is to demand
  // auth. A false "required" produces a SKIPPED verdict (no user-visible
  // correctness regression); a false "optional" would silently run the
  // verifier in demo mode and likely produce a spurious FAIL that masks
  // the real issue (phrase not in whitelist). Callers should surface the
  // `unmatched_given_phrase` diagnostic in their trace so a maintainer
  // can extend the phrase lists.
  return { result: true, matched_phrase: null, unmatched: true };
}
```

## Python port (for test + gate code)

Some callers (e.g., test fixtures, `review-verdict-gate.md` corrections
script) are Python. The behavior is identical — match the JS implementation
byte-for-byte:

```python
import re

AUTH_PHRASES = [
    "logged-in user",
    "authenticated user",
    "user on dashboard",
]

NON_AUTH_PHRASES = [
    "anonymous visitor",
    "new user",
    "unauthenticated user",
]


def _matches(phrase: str, given_lower: str) -> bool:
    """Word-boundary match. Prevents 'authenticated user' from matching
    'unauthenticated user' via naive substring check. Boundaries are
    start-of-string or any non-alphanumeric character.
    """
    pattern = rf"(^|[^a-z0-9]){re.escape(phrase)}([^a-z0-9]|$)"
    return re.search(pattern, given_lower) is not None


def requires_auth(given):
    g = (given or "").lower()
    # Check NON_AUTH first so negative specifiers override positives.
    for p in NON_AUTH_PHRASES:
        if _matches(p, g):
            return {"result": False, "matched_phrase": p, "unmatched": False}
    for p in AUTH_PHRASES:
        if _matches(p, g):
            return {"result": True, "matched_phrase": p, "unmatched": False}
    return {"result": True, "matched_phrase": None, "unmatched": True}
```

## Drift guard

Any file outside this one that contains the literal string
`"logged-in user"`, `"authenticated user"`, `"user on dashboard"`,
`"anonymous visitor"`, `"new user"`, or `"unauthenticated user"` is
suspect:

- `.claude/procedures/wire.md` → must reference THIS file rather than
  inline the list
- `.claude/procedures/behavior-verifier.md` → must reference THIS file
- `.claude/scripts/tests/test_given_auth_matcher.py` → test fixtures
  **may** inline the phrases (they're tests of this file's behavior)

The drift test enforces these exemptions via an explicit allowlist.

## Extension protocol

Adding a new phrase:

1. Add the lowercase phrase to the appropriate list above (this file only).
2. Run `python3 -m unittest .claude.scripts.tests.test_given_auth_matcher` —
   all tests should pass (the drift test exempts this file).
3. If the new phrase changes behavior for an existing behavior's trace,
   re-run `/verify` on the sample app and confirm the change is intentional.

Removing a phrase requires the same steps plus a search-and-replace of
any behavior whose `given` used it.

## Rationale — why not regex?

Substring match is deliberate:
- Phrases are human-authored product descriptions, not structured identifiers
- Case-insensitive substring match tolerates harmless variation
  ("A logged-in user ..." vs "for logged-in users, ...")
- Regex adds complexity without adding discrimination power in observed
  corpus (see `experiment/experiment.yaml` samples across template projects)

If a future phrase requires structure (e.g., "logged-in user with role admin"),
add it as a separate substring at the MORE SPECIFIC phrase first so it
takes precedence in the linear scan.
