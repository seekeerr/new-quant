# REGISTER_TASK_FIX_REPORT

**File:** `pipeline/register_task.ps1`
**Scope:** parsing/syntax repair only. No redesign, no functional change, no
scheduling-behavior change.
**Result:** **PowerShell syntax validation: PASS**

---

## 1. Root cause

The script did not parse under Windows PowerShell 5.1. The cause was **non-ASCII
Unicode punctuation embedded in the file** — not documentation leaking into code,
and not a structural bug. Two characters were present:

| Codepoint | Char | Name | Lines |
|---|---|---|---|
| U+2014 | `—` | em-dash | 2, 32, 66, 69 |
| U+2013 | `–` | en-dash | 5, 45, 69 |

Three of these sat **inside executable string literals**:

- line 32: `Write-Host "Task '$TaskName' not found — nothing to do."`
- line 66: `"validate/health). Data only — never trades or rebalances."`
- line 69: `Write-Host "Registered task '$TaskName' — Mon–Fri at $LocalTime local."`

When Windows PowerShell 5.1 reads a UTF-8 file under its default (cp1252)
codepage, each multi-byte em/en-dash is decoded as stray bytes. That corrupts the
enclosing string, which is exactly why the reported errors appeared:

- **Missing string terminator** — the mangled bytes broke the closing `"` of the
  line-66 string.
- **Unexpected token 'never'** — `never` is the first word *after* the em-dash on
  line 66; once the string broke, the parser saw bare tokens.
- **Missing closing ')'` / Missing closing '}'** / **ParserError** — cascade from
  the broken string inside the `Register-ScheduledTask ... -Description ( ... )`
  expression and the surrounding block.

## 2. Fix applied

Replaced every non-ASCII punctuation character with its ASCII equivalent:

- `—` (U+2014)  ->  `-`
- `–` (U+2013)  ->  `-`

Nothing else was touched. No cmdlets, parameters, values, control flow, trigger
definition, settings, principal, or task name were changed. The replacements
occur only in comments and in display/description strings, so runtime behavior and
the scheduler configuration are identical.

No other non-ASCII categories were present (no smart quotes, ellipsis, or arrows).

## 3. Verification

```
non-ASCII characters remaining : 0
```

Syntax-only parse (no execution) via the PowerShell AST parser:

```powershell
$tokens=$null; $errors=$null
[System.Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
# -> Parser: 0 errors
```

`ParseFile` performs a pure syntax/parse check; it does **not** execute the script,
so no scheduled task was created, modified, or run during validation.

**PowerShell syntax validation: PASS**
