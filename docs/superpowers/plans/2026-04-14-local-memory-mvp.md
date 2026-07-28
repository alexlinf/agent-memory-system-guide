# Local Memory MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a session-start entrypoint, structured capture metadata, and a scoped doctor command that strengthens the local recovery layer without introducing a new external memory backend.

**Architecture:** Extend `scripts/memory_capture.py` with two new user-facing commands: `session-start` for eager local recovery-layer initialization and `doctor` for health checks that default to the active local layer. Keep the data model file-first by enriching `memory-capture.md` with lightweight structured metadata instead of introducing a database or auto-writing `MEMORY.md`.

**Tech Stack:** Python 3 standard library, pytest, Markdown templates and READMEs

---

### Task 1: Cover the new CLI surface with failing tests

**Files:**
- Modify: `tests/test_memory_capture_script.py`
- Test: `tests/test_memory_capture_script.py`

- [ ] **Step 1: Write the failing test for `session-start`**

```python
def test_session_start_creates_recovery_files_and_structured_capture_metadata(tmp_path: Path):
    result = run_command(
        'session-start',
        '--workspace',
        str(tmp_path),
        '--generated-at',
        '2026-04-14T09:00:00+08:00',
        '--session-id',
        'session-42',
        '--project',
        'memory-system',
        '--scope-tag',
        'repo:agent-memory-system-guide',
        '--scope-tag',
        'feature:local-memory-mvp',
    )

    assert result.returncode == 0
    capture_text = (tmp_path / 'memory-capture.md').read_text(encoding='utf-8')
    assert 'session_started_at: 2026-04-14T09:00:00+08:00' in capture_text
    assert 'project: memory-system' in capture_text
    assert 'source_session: session-42' in capture_text
    assert 'scope_tags: repo:agent-memory-system-guide, feature:local-memory-mvp' in capture_text
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `pytest tests/test_memory_capture_script.py -k session_start -v`
Expected: FAIL because `session-start` is not a supported command yet.

- [ ] **Step 3: Write the failing test for `doctor` default scope**

```python
def test_doctor_checks_local_layer_only_by_default(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'MEMORY.md').write_text('# MEMORY\n', encoding='utf-8')

    result = run_command(
        'doctor',
        '--workspace',
        str(workspace),
        '--json',
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload['checks']['local_recovery']['status'] == 'warn'
    assert 'obsidian' not in payload['checks']
```

- [ ] **Step 4: Run the focused test and verify it fails**

Run: `pytest tests/test_memory_capture_script.py -k doctor -v`
Expected: FAIL because `doctor` is not a supported command yet.

- [ ] **Step 5: Commit**

```bash
git add tests/test_memory_capture_script.py
git commit -m "test: cover local memory MVP cli behavior"
```

### Task 2: Implement the new command paths in `memory_capture.py`

**Files:**
- Modify: `scripts/memory_capture.py`
- Test: `tests/test_memory_capture_script.py`

- [ ] **Step 1: Implement argument parsing and metadata rendering**

```python
SUBCOMMANDS = {"bootstrap", "session-start", "export", "import", "report", "doctor"}

def add_capture_metadata_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session-id", help="Optional session identifier for the current run.")
    parser.add_argument("--project", help="Optional project or repo scope for the capture sheet.")
    parser.add_argument(
        "--scope-tag",
        action="append",
        default=[],
        help="Repeatable scope tag used to label the current session.",
    )
```

- [ ] **Step 2: Implement the new capture sheet body**

```python
def build_capture_content(...):
    scope_tags = ", ".join(metadata.scope_tags) if metadata.scope_tags else ""
    return (
        "# memory-capture.md\n\n"
        f"> Generated at: {generated_at}\n\n"
        "## Capture metadata\n"
        f"- session_started_at: {metadata.session_started_at}\n"
        f"- project: {metadata.project}\n"
        f"- scope_tags: {scope_tags}\n"
        f"- source_session: {metadata.source_session}\n"
        "- candidate_document_id:\n"
        "- stability: review\n\n"
        f"{template}"
    )
```

- [ ] **Step 3: Implement `session-start` and `doctor` handlers**

```python
def handle_session_start(args: argparse.Namespace, repo_root: Path) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    generated_at = args.generated_at or iso_now()
    create_bootstrap_files(
        workspace,
        generated_at,
        repo_root,
        metadata=capture_metadata_from_args(args, generated_at),
        refresh_capture=args.refresh_capture,
    )
    print("Session start: ready")
    return 0
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `pytest tests/test_memory_capture_script.py -k "session_start or doctor" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/memory_capture.py tests/test_memory_capture_script.py
git commit -m "feat: add session-start and doctor commands"
```

### Task 3: Update templates and docs for the new workflow

**Files:**
- Modify: `templates/memory-capture.md`
- Modify: `README.md`
- Modify: `README_CN.md`
- Modify: `README_EN.md`
- Modify: `SKILL.md`
- Modify: `tests/test_memory_capture_contract.py`

- [ ] **Step 1: Add the new structured prompts to the capture template**

```markdown
## 候选标签
- 这次记忆属于哪个项目、主题或阶段？

## 候选稳定性
- `volatile`、`review`、`stable` 里，当前更接近哪一类？
```

- [ ] **Step 2: Document `session-start` and `doctor`**

```text
python3 scripts/memory_capture.py session-start --workspace /path/to/workspace
python3 scripts/memory_capture.py doctor --workspace /path/to/workspace
```

- [ ] **Step 3: Extend the contract tests**

```python
assert 'session-start' in readme_text
assert 'doctor' in readme_text
assert '候选标签' in template_text
assert '候选稳定性' in template_text
```

- [ ] **Step 4: Run docs/contract tests and verify they pass**

Run: `pytest tests/test_memory_capture_contract.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add templates/memory-capture.md README.md README_CN.md README_EN.md SKILL.md tests/test_memory_capture_contract.py
git commit -m "docs: describe local memory MVP workflow"
```

### Task 4: Full verification

**Files:**
- Modify: none
- Test: `tests/test_memory_capture_script.py`
- Test: `tests/test_memory_capture_contract.py`

- [ ] **Step 1: Run the script test suite**

Run: `pytest tests/test_memory_capture_script.py -v`
Expected: PASS

- [ ] **Step 2: Run the contract test suite**

Run: `pytest tests/test_memory_capture_contract.py tests/test_memory_recovery_contract.py -v`
Expected: PASS

- [ ] **Step 3: Run the full test suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 4: Review git diff for accidental scope creep**

Run: `git diff --stat`
Expected: Only the planned script, template, doc, and test files changed

- [ ] **Step 5: Commit**

```bash
git add scripts/memory_capture.py templates/memory-capture.md README.md README_CN.md README_EN.md SKILL.md tests/test_memory_capture_script.py tests/test_memory_capture_contract.py docs/superpowers/plans/2026-04-14-local-memory-mvp.md
git commit -m "feat: strengthen local memory MVP workflow"
```
