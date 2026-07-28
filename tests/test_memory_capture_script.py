from pathlib import Path
import json
import subprocess
import sys
import zipfile


def script_path() -> Path:
    return Path(__file__).resolve().parents[1] / 'scripts' / 'memory_capture.py'


def run_script(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, str(script_path()), '--workspace', str(tmp_path), *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def run_command(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, str(script_path()), *args],
        cwd=cwd or repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def test_bootstrap_creates_missing_memory_files(tmp_path: Path):
    result = run_script(tmp_path, '--generated-at', '2026-03-24T09:30:00+08:00')

    assert result.returncode == 0
    assert (tmp_path / 'SESSION-STATE.md').exists()
    assert (tmp_path / 'working-buffer.md').exists()
    capture_path = tmp_path / 'memory-capture.md'
    assert capture_path.exists()
    capture_text = capture_path.read_text(encoding='utf-8')
    assert 'Generated at: 2026-03-24T09:30:00+08:00' in capture_text
    assert '候选决策' in capture_text


def test_bootstrap_preserves_existing_state_files(tmp_path: Path):
    session_state = tmp_path / 'SESSION-STATE.md'
    working_buffer = tmp_path / 'working-buffer.md'
    session_state.write_text('# SESSION-STATE.md\n\ncustom session\n', encoding='utf-8')
    working_buffer.write_text('# working-buffer.md\n\ncustom buffer\n', encoding='utf-8')

    result = run_script(tmp_path, '--generated-at', '2026-03-24T10:00:00+08:00')

    assert result.returncode == 0
    assert session_state.read_text(encoding='utf-8') == '# SESSION-STATE.md\n\ncustom session\n'
    assert working_buffer.read_text(encoding='utf-8') == '# working-buffer.md\n\ncustom buffer\n'


def test_bootstrap_preserves_existing_memory_capture_file(tmp_path: Path):
    capture_path = tmp_path / 'memory-capture.md'
    capture_path.write_text('# memory-capture.md\n\nkeep me\n', encoding='utf-8')

    result = run_script(tmp_path, '--generated-at', '2026-03-26T09:00:00+08:00')

    assert result.returncode == 0
    assert capture_path.read_text(encoding='utf-8') == '# memory-capture.md\n\nkeep me\n'
    assert 'memory-capture.md: kept' in result.stdout


def test_bootstrap_refresh_capture_overwrites_existing_memory_capture_file(tmp_path: Path):
    capture_path = tmp_path / 'memory-capture.md'
    capture_path.write_text('# memory-capture.md\n\nold content\n', encoding='utf-8')

    result = run_command(
        'bootstrap',
        '--workspace',
        str(tmp_path),
        '--generated-at',
        '2026-03-26T09:05:00+08:00',
        '--refresh-capture',
    )

    assert result.returncode == 0
    capture_text = capture_path.read_text(encoding='utf-8')
    assert 'Generated at: 2026-03-26T09:05:00+08:00' in capture_text
    assert '候选决策' in capture_text
    assert 'memory-capture.md: refreshed' in result.stdout


def test_bootstrap_subcommand_creates_missing_memory_files(tmp_path: Path):
    result = run_command(
        'bootstrap',
        '--workspace',
        str(tmp_path),
        '--generated-at',
        '2026-03-24T11:00:00+08:00',
    )

    assert result.returncode == 0
    assert (tmp_path / 'SESSION-STATE.md').exists()
    assert (tmp_path / 'working-buffer.md').exists()
    assert (tmp_path / 'memory-capture.md').exists()


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
    assert (tmp_path / 'SESSION-STATE.md').exists()
    assert (tmp_path / 'working-buffer.md').exists()
    capture_text = (tmp_path / 'memory-capture.md').read_text(encoding='utf-8')
    assert '## Capture metadata' in capture_text
    assert 'session_started_at: 2026-04-14T09:00:00+08:00' in capture_text
    assert 'project: memory-system' in capture_text
    assert 'source_session: session-42' in capture_text
    assert 'scope_tags: repo:agent-memory-system-guide, feature:local-memory-mvp' in capture_text
    assert 'candidate_document_id: memory-system__session-42__202604140900000800' in capture_text
    assert 'stability: review' in capture_text
    assert 'Session start: ready' in result.stdout


def test_export_creates_archive_with_manifest(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    memory_dir = workspace / 'memory'
    attachments_dir = workspace / 'attachments'
    memory_dir.mkdir(parents=True)
    attachments_dir.mkdir()
    (workspace / 'MEMORY.md').write_text('# MEMORY\n', encoding='utf-8')
    (workspace / 'SESSION-STATE.md').write_text('# SESSION\n', encoding='utf-8')
    (workspace / 'working-buffer.md').write_text('# BUFFER\n', encoding='utf-8')
    (workspace / 'memory-capture.md').write_text('# CAPTURE\n', encoding='utf-8')
    (memory_dir / '2026-03-25.md').write_text('# daily\n', encoding='utf-8')
    (attachments_dir / 'note.txt').write_text('evidence\n', encoding='utf-8')
    backup_path = tmp_path / 'backup.zip'

    result = run_command(
        'export',
        '--workspace',
        str(workspace),
        '--output',
        str(backup_path),
        '--generated-at',
        '2026-03-25T09:00:00+08:00',
    )

    assert result.returncode == 0
    assert backup_path.exists()
    with zipfile.ZipFile(backup_path) as archive:
        names = set(archive.namelist())
        assert 'manifest.json' in names
        assert 'MEMORY.md' in names
        assert 'SESSION-STATE.md' in names
        assert 'working-buffer.md' in names
        assert 'memory-capture.md' in names
        assert 'memory/2026-03-25.md' in names
        assert 'attachments/note.txt' in names
        manifest = archive.read('manifest.json').decode('utf-8')
    assert '"generated_at": "2026-03-25T09:00:00+08:00"' in manifest
    assert '"MEMORY.md"' in manifest


def test_import_restores_files_and_backs_up_existing_state(tmp_path: Path):
    source_workspace = tmp_path / 'source'
    source_memory_dir = source_workspace / 'memory'
    source_memory_dir.mkdir(parents=True)
    (source_workspace / 'MEMORY.md').write_text('# MEMORY\n\nrestored\n', encoding='utf-8')
    (source_workspace / 'SESSION-STATE.md').write_text('# SESSION\n\nrestored\n', encoding='utf-8')
    (source_workspace / 'working-buffer.md').write_text('# BUFFER\n\nrestored\n', encoding='utf-8')
    (source_memory_dir / '2026-03-25.md').write_text('# daily restored\n', encoding='utf-8')
    archive_path = tmp_path / 'memory-backup.zip'
    export_result = run_command(
        'export',
        '--workspace',
        str(source_workspace),
        '--output',
        str(archive_path),
        '--generated-at',
        '2026-03-25T09:30:00+08:00',
    )
    assert export_result.returncode == 0

    target_workspace = tmp_path / 'target'
    target_workspace.mkdir()
    (target_workspace / 'MEMORY.md').write_text('# MEMORY\n\nexisting\n', encoding='utf-8')
    (target_workspace / 'SESSION-STATE.md').write_text('# SESSION\n\nexisting\n', encoding='utf-8')

    result = run_command(
        'import',
        '--workspace',
        str(target_workspace),
        '--input',
        str(archive_path),
        '--generated-at',
        '2026-03-25T10:00:00+08:00',
    )

    assert result.returncode == 0
    assert (target_workspace / 'MEMORY.md').read_text(encoding='utf-8') == '# MEMORY\n\nrestored\n'
    assert (target_workspace / 'SESSION-STATE.md').read_text(encoding='utf-8') == '# SESSION\n\nrestored\n'
    assert (target_workspace / 'working-buffer.md').read_text(encoding='utf-8') == '# BUFFER\n\nrestored\n'
    assert (target_workspace / 'memory' / '2026-03-25.md').read_text(encoding='utf-8') == '# daily restored\n'

    backups = sorted(target_workspace.glob('memory-import-backup-*.zip'))
    assert backups
    with zipfile.ZipFile(backups[0]) as archive:
        names = set(archive.namelist())
        assert 'manifest.json' in names
        assert 'MEMORY.md' in names
        assert 'SESSION-STATE.md' in names
        assert archive.read('MEMORY.md').decode('utf-8') == '# MEMORY\n\nexisting\n'


def test_import_preserves_extra_supported_files_by_default(tmp_path: Path):
    source_workspace = tmp_path / 'source'
    source_memory_dir = source_workspace / 'memory'
    source_memory_dir.mkdir(parents=True)
    (source_workspace / 'MEMORY.md').write_text('# MEMORY\n\nrestored\n', encoding='utf-8')
    (source_memory_dir / '2026-03-25.md').write_text('# daily restored\n', encoding='utf-8')
    archive_path = tmp_path / 'memory-backup.zip'

    export_result = run_command(
        'export',
        '--workspace',
        str(source_workspace),
        '--output',
        str(archive_path),
        '--generated-at',
        '2026-03-26T10:00:00+08:00',
    )
    assert export_result.returncode == 0

    target_workspace = tmp_path / 'target'
    target_memory_dir = target_workspace / 'memory'
    target_memory_dir.mkdir(parents=True)
    (target_workspace / 'MEMORY.md').write_text('# MEMORY\n\nexisting\n', encoding='utf-8')
    extra_note = target_memory_dir / '2026-03-20.md'
    extra_note.write_text('# extra daily note\n', encoding='utf-8')

    result = run_command(
        'import',
        '--workspace',
        str(target_workspace),
        '--input',
        str(archive_path),
        '--generated-at',
        '2026-03-26T10:05:00+08:00',
    )

    assert result.returncode == 0
    assert extra_note.exists()
    assert 'Import mode: conservative' in result.stdout


def test_import_clean_removes_extra_supported_files_before_restore(tmp_path: Path):
    source_workspace = tmp_path / 'source'
    source_memory_dir = source_workspace / 'memory'
    source_memory_dir.mkdir(parents=True)
    (source_workspace / 'MEMORY.md').write_text('# MEMORY\n\nrestored\n', encoding='utf-8')
    (source_memory_dir / '2026-03-25.md').write_text('# daily restored\n', encoding='utf-8')
    archive_path = tmp_path / 'memory-backup.zip'

    export_result = run_command(
        'export',
        '--workspace',
        str(source_workspace),
        '--output',
        str(archive_path),
        '--generated-at',
        '2026-03-26T10:10:00+08:00',
    )
    assert export_result.returncode == 0

    target_workspace = tmp_path / 'target'
    target_memory_dir = target_workspace / 'memory'
    attachments_dir = target_workspace / 'attachments'
    target_memory_dir.mkdir(parents=True)
    attachments_dir.mkdir()
    (target_workspace / 'MEMORY.md').write_text('# MEMORY\n\nexisting\n', encoding='utf-8')
    extra_note = target_memory_dir / '2026-03-20.md'
    extra_note.write_text('# extra daily note\n', encoding='utf-8')
    extra_attachment = attachments_dir / 'old.txt'
    extra_attachment.write_text('old\n', encoding='utf-8')

    result = run_command(
        'import',
        '--workspace',
        str(target_workspace),
        '--input',
        str(archive_path),
        '--generated-at',
        '2026-03-26T10:15:00+08:00',
        '--clean',
    )

    assert result.returncode == 0
    assert not extra_note.exists()
    assert not extra_attachment.exists()
    assert (target_workspace / 'memory' / '2026-03-25.md').exists()
    assert 'Import mode: clean' in result.stdout

    backups = sorted(target_workspace.glob('memory-import-backup-*.zip'))
    assert backups
    with zipfile.ZipFile(backups[0]) as archive:
        assert archive.read('memory/2026-03-20.md').decode('utf-8') == '# extra daily note\n'
        assert archive.read('attachments/old.txt').decode('utf-8') == 'old\n'


def test_report_prints_workspace_summary(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'MEMORY.md').write_text('# MEMORY\n', encoding='utf-8')
    (workspace / 'working-buffer.md').write_text('# BUFFER\n', encoding='utf-8')
    (workspace / 'memory-capture.md').write_text('# CAPTURE\n', encoding='utf-8')
    memory_dir = workspace / 'memory'
    memory_dir.mkdir()
    (memory_dir / '2026-03-24.md').write_text('# day 1\n', encoding='utf-8')
    (memory_dir / '2026-03-25.md').write_text('# day 2\n', encoding='utf-8')
    attachments_dir = workspace / 'attachments'
    attachments_dir.mkdir()
    (attachments_dir / 'proof.txt').write_text('data\n', encoding='utf-8')

    result = run_command(
        'report',
        '--workspace',
        str(workspace),
    )

    assert result.returncode == 0
    stdout = result.stdout
    assert 'Supported files:' in stdout
    assert 'MEMORY.md: present' in stdout
    assert 'SESSION-STATE.md: missing' in stdout
    assert 'memory: 2 daily note(s)' in stdout
    assert 'attachments: 1 attachment(s)' in stdout
    assert 'Latest daily note: memory/2026-03-25.md' in stdout
    assert 'Warnings:' in stdout
    assert '  - Missing supported file: SESSION-STATE.md' in stdout


def test_report_writes_markdown_output_file(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'MEMORY.md').write_text('# MEMORY\n', encoding='utf-8')
    (workspace / 'SESSION-STATE.md').write_text('# SESSION\n', encoding='utf-8')
    (workspace / 'working-buffer.md').write_text('# BUFFER\n', encoding='utf-8')
    (workspace / 'memory-capture.md').write_text('# CAPTURE\n', encoding='utf-8')
    memory_dir = workspace / 'memory'
    memory_dir.mkdir()
    (memory_dir / '2026-03-25.md').write_text('# day 1\n', encoding='utf-8')
    attachments_dir = workspace / 'attachments'
    attachments_dir.mkdir()
    (attachments_dir / 'proof.txt').write_text('good\n', encoding='utf-8')

    report_path = tmp_path / 'workspace-report.md'

    result = run_command(
        'report',
        '--workspace',
        str(workspace),
        '--output',
        str(report_path),
    )

    assert result.returncode == 0
    assert report_path.exists()
    markdown = report_path.read_text(encoding='utf-8')
    assert '# Memory workspace report' in markdown
    assert '## Supported files' in markdown
    assert '- `MEMORY.md`: present' in markdown
    assert '## Latest daily note' in markdown
    assert '- memory/2026-03-25.md' in markdown
    assert '## Warnings' in markdown
    assert '- none' in markdown


def test_report_prints_json_summary(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'MEMORY.md').write_text('# MEMORY\n', encoding='utf-8')
    (workspace / 'working-buffer.md').write_text('# BUFFER\n', encoding='utf-8')
    (workspace / 'memory-capture.md').write_text('# CAPTURE\n', encoding='utf-8')
    memory_dir = workspace / 'memory'
    memory_dir.mkdir()
    (memory_dir / '2026-03-25.md').write_text('# day 2\n', encoding='utf-8')
    attachments_dir = workspace / 'attachments'
    attachments_dir.mkdir()
    (attachments_dir / 'proof.txt').write_text('data\n', encoding='utf-8')

    result = run_command(
        'report',
        '--workspace',
        str(workspace),
        '--json',
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload['workspace'] == str(workspace.resolve())
    assert payload['supported_files']['SESSION-STATE.md'] is False
    assert payload['memory_note_count'] == 1
    assert payload['attachments_count'] == 1
    assert payload['latest_daily_note'] == 'memory/2026-03-25.md'
    assert 'Missing supported file: SESSION-STATE.md' in payload['warnings']


def test_report_json_can_write_markdown_output_file(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'MEMORY.md').write_text('# MEMORY\n', encoding='utf-8')
    (workspace / 'SESSION-STATE.md').write_text('# SESSION\n', encoding='utf-8')
    (workspace / 'working-buffer.md').write_text('# BUFFER\n', encoding='utf-8')
    (workspace / 'memory-capture.md').write_text('# CAPTURE\n', encoding='utf-8')
    memory_dir = workspace / 'memory'
    memory_dir.mkdir()
    (memory_dir / '2026-03-25.md').write_text('# day 1\n', encoding='utf-8')
    attachments_dir = workspace / 'attachments'
    attachments_dir.mkdir()
    (attachments_dir / 'proof.txt').write_text('good\n', encoding='utf-8')

    report_path = tmp_path / 'workspace-report.md'

    result = run_command(
        'report',
        '--workspace',
        str(workspace),
        '--json',
        '--output',
        str(report_path),
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload['latest_daily_note'] == 'memory/2026-03-25.md'
    assert report_path.exists()
    markdown = report_path.read_text(encoding='utf-8')
    assert '# Memory workspace report' in markdown


def test_report_ignores_non_daily_markdown_files_in_memory_directory(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'MEMORY.md').write_text('# MEMORY\n', encoding='utf-8')
    (workspace / 'SESSION-STATE.md').write_text('# SESSION\n', encoding='utf-8')
    (workspace / 'working-buffer.md').write_text('# BUFFER\n', encoding='utf-8')
    (workspace / 'memory-capture.md').write_text('# CAPTURE\n', encoding='utf-8')
    memory_dir = workspace / 'memory'
    memory_dir.mkdir()
    (memory_dir / '2026-03-24.md').write_text('# day 1\n', encoding='utf-8')
    (memory_dir / '2026-03-25.md').write_text('# day 2\n', encoding='utf-8')
    (memory_dir / 'index.md').write_text('# not a daily note\n', encoding='utf-8')
    attachments_dir = workspace / 'attachments'
    attachments_dir.mkdir()
    (attachments_dir / 'proof.txt').write_text('good\n', encoding='utf-8')

    result = run_command(
        'report',
        '--workspace',
        str(workspace),
    )

    assert result.returncode == 0
    stdout = result.stdout
    assert 'memory: 2 daily note(s)' in stdout
    assert 'Latest daily note: memory/2026-03-25.md' in stdout


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
    assert payload['workspace'] == str(workspace.resolve())
    assert payload['checks']['local_recovery']['status'] == 'warn'
    assert 'Missing supported file: SESSION-STATE.md' in payload['checks']['local_recovery']['warnings']
    assert 'obsidian' not in payload['checks']


def test_doctor_checks_obsidian_only_when_explicitly_requested(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    for name in ['MEMORY.md', 'SESSION-STATE.md', 'working-buffer.md', 'memory-capture.md']:
        (workspace / name).write_text(f'# {name}\n', encoding='utf-8')
    (workspace / 'memory').mkdir()
    (workspace / 'memory' / '2026-04-14.md').write_text('# day\n', encoding='utf-8')
    (workspace / 'attachments').mkdir()
    (workspace / 'attachments' / 'proof.txt').write_text('ok\n', encoding='utf-8')

    vault = tmp_path / 'vault'
    vault.mkdir()

    result = run_command(
        'doctor',
        '--workspace',
        str(workspace),
        '--json',
        '--obsidian-vault',
        str(vault),
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload['checks']['local_recovery']['status'] == 'ok'
    assert payload['checks']['obsidian']['status'] == 'ok'
    assert payload['checks']['obsidian']['warnings'] == []


def test_distill_summarizes_candidate_memory_with_scope_metadata(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'memory-capture.md').write_text(
        (
            '# memory-capture.md\n\n'
            '> Generated at: 2026-04-14T09:00:00+08:00\n\n'
            '## Capture metadata\n'
            '- session_started_at: 2026-04-14T09:00:00+08:00\n'
            '- project: memory-system\n'
            '- scope_tags: repo:agent-memory-system-guide, feature:distill\n'
            '- source_session: session-77\n'
            '- candidate_document_id:\n'
            '- stability: stable\n\n'
            '## 候选决策\n'
            '- report 和 doctor 都保留本地优先，不检查未启用后端\n'
            '\n'
            '## 候选踩坑\n'
            '- 不要把 daily notes 的临时信息直接写入 MEMORY.md\n'
            '\n'
            '## 候选长期记忆\n'
            '- 需要先读 SESSION-STATE.md 再读 recent daily notes\n'
            '\n'
            '## 候选标签\n'
            '- workflow\n'
            '- local-memory\n'
            '\n'
            '## 候选稳定性\n'
            '- stable\n'
            '\n'
            '## 只留在当前恢复层\n'
            '- 下一步先补 distill 命令的 README 示例\n'
            '\n'
            '## 明日续接\n'
            '- 如果中断，先跑 pytest -q\n'
        ),
        encoding='utf-8',
    )

    result = run_command(
        'distill',
        '--workspace',
        str(workspace),
        '--json',
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload['metadata']['project'] == 'memory-system'
    assert payload['metadata']['source_session'] == 'session-77'
    assert payload['metadata']['scope_tags'] == [
        'repo:agent-memory-system-guide',
        'feature:distill',
        'workflow',
        'local-memory',
    ]
    assert payload['metadata']['stability'] == 'stable'
    assert len(payload['suggested_memory']) == 3
    assert payload['suggested_memory'][0]['bucket'] == '候选决策'
    assert payload['suggested_memory'][0]['text'] == 'report 和 doctor 都保留本地优先，不检查未启用后端'
    assert payload['recovery_only'] == ['下一步先补 distill 命令的 README 示例']
    assert payload['follow_up'] == ['如果中断，先跑 pytest -q']


def test_distill_ignores_template_placeholder_lines(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'memory-capture.md').write_text(
        (
            '# memory-capture.md\n\n'
            '> Generated at: 2026-04-14T09:00:00+08:00\n\n'
            '## Capture metadata\n'
            '- session_started_at: 2026-04-14T09:00:00+08:00\n'
            '- project: \n'
            '- scope_tags: \n'
            '- source_session: \n'
            '- candidate_document_id:\n'
            '- stability: review\n\n'
            '## 候选决策\n'
            '- 这次有没有新的长期决策？\n'
            '\n'
            '## 候选踩坑\n'
            '- 这次有没有下次大概率还会踩的坑？\n'
            '\n'
            '## 候选长期记忆\n'
            '- 哪些事实会持续影响后续协作？\n'
            '\n'
            '## 候选标签\n'
            '- 这次记忆属于哪个项目、主题或阶段？\n'
            '\n'
            '## 候选稳定性\n'
            '- `volatile`、`review`、`stable` 里，当前更接近哪一类？\n'
            '\n'
            '## 只留在当前恢复层\n'
            '- 哪些内容只需要写进 `SESSION-STATE.md` 或 `working-buffer.md`？\n'
            '\n'
            '## 明日续接\n'
            '- 如果现在中断，下一步最该做什么？\n'
        ),
        encoding='utf-8',
    )

    result = run_command(
        'distill',
        '--workspace',
        str(workspace),
        '--json',
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload['suggested_memory'] == []
    assert payload['recovery_only'] == []
    assert payload['follow_up'] == []


def test_distill_writes_markdown_report_with_bucketed_sections(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'memory-capture.md').write_text(
        (
            '# memory-capture.md\n\n'
            '> Generated at: 2026-04-14T09:00:00+08:00\n\n'
            '## Capture metadata\n'
            '- session_started_at: 2026-04-14T09:00:00+08:00\n'
            '- project: memory-system\n'
            '- scope_tags: repo:agent-memory-system-guide, feature:distill\n'
            '- source_session: session-77\n'
            '- candidate_document_id: memory-system__session-77__202604140900000800\n'
            '- stability: stable\n\n'
            '## 候选决策\n'
            '- report 和 doctor 都保留本地优先，不检查未启用后端\n'
            '\n'
            '## 候选踩坑\n'
            '- 不要把 daily notes 的临时信息直接写入 MEMORY.md\n'
            '\n'
            '## 候选长期记忆\n'
            '- 需要先读 SESSION-STATE.md 再读 recent daily notes\n'
            '\n'
            '## 候选标签\n'
            '- workflow\n'
            '\n'
            '## 候选稳定性\n'
            '- stable\n'
            '\n'
            '## 只留在当前恢复层\n'
            '- 下一步先补 distill 命令的 README 示例\n'
            '\n'
            '## 明日续接\n'
            '- 如果中断，先跑 pytest -q\n'
        ),
        encoding='utf-8',
    )
    output_path = tmp_path / 'distill-report.md'

    result = run_command(
        'distill',
        '--workspace',
        str(workspace),
        '--output',
        str(output_path),
    )

    assert result.returncode == 0
    assert output_path.exists()
    markdown = output_path.read_text(encoding='utf-8')
    assert '# Memory capture distill' in markdown
    assert '- Document ID: `memory-system__session-77__202604140900000800`' in markdown
    assert '## Suggested memory' in markdown
    assert '### 候选决策' in markdown
    assert '### 候选踩坑' in markdown
    assert '### 候选长期记忆' in markdown
    assert '## Recovery only' in markdown
    assert '## Follow up' in markdown


def test_apply_creates_memory_file_and_writes_distilled_entry(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'memory-capture.md').write_text(
        (
            '# memory-capture.md\n\n'
            '> Generated at: 2026-04-14T09:00:00+08:00\n\n'
            '## Capture metadata\n'
            '- session_started_at: 2026-04-14T09:00:00+08:00\n'
            '- project: memory-system\n'
            '- scope_tags: repo:agent-memory-system-guide, feature:apply\n'
            '- source_session: session-88\n'
            '- candidate_document_id: memory-system__session-88__202604140900000800\n'
            '- stability: stable\n\n'
            '## 候选决策\n'
            '- report 和 doctor 都保留本地优先，不检查未启用后端\n'
            '\n'
            '## 候选踩坑\n'
            '- 不要把 daily notes 的临时信息直接写入 MEMORY.md\n'
            '\n'
            '## 候选长期记忆\n'
            '- 需要先读 SESSION-STATE.md 再读 recent daily notes\n'
            '\n'
            '## 候选标签\n'
            '- workflow\n'
            '\n'
            '## 候选稳定性\n'
            '- stable\n'
            '\n'
            '## 只留在当前恢复层\n'
            '- 下一步先补 apply 命令示例\n'
            '\n'
            '## 明日续接\n'
            '- 如果中断，先跑 pytest -q\n'
        ),
        encoding='utf-8',
    )

    result = run_command(
        'apply',
        '--workspace',
        str(workspace),
    )

    assert result.returncode == 0
    memory_text = (workspace / 'MEMORY.md').read_text(encoding='utf-8')
    assert '# MEMORY.md' in memory_text
    assert '## Distilled Memory Entries' in memory_text
    assert 'memory-system__session-88__202604140900000800' in memory_text
    assert '### 候选决策' in memory_text
    assert '### 候选踩坑' in memory_text
    assert '### 候选长期记忆' in memory_text
    assert '下一步先补 apply 命令示例' not in memory_text
    assert 'Applied distilled memory: 1 entry added, 0 skipped' in result.stdout


def test_apply_is_idempotent_for_same_candidate_document_id(tmp_path: Path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    capture_text = (
        '# memory-capture.md\n\n'
        '> Generated at: 2026-04-14T09:00:00+08:00\n\n'
        '## Capture metadata\n'
        '- session_started_at: 2026-04-14T09:00:00+08:00\n'
        '- project: memory-system\n'
        '- scope_tags: repo:agent-memory-system-guide, feature:apply\n'
        '- source_session: session-88\n'
        '- candidate_document_id: memory-system__session-88__202604140900000800\n'
        '- stability: stable\n\n'
        '## 候选决策\n'
        '- report 和 doctor 都保留本地优先，不检查未启用后端\n'
        '\n'
        '## 候选踩坑\n'
        '- 不要把 daily notes 的临时信息直接写入 MEMORY.md\n'
        '\n'
        '## 候选长期记忆\n'
        '- 需要先读 SESSION-STATE.md 再读 recent daily notes\n'
        '\n'
        '## 候选标签\n'
        '- workflow\n'
        '\n'
        '## 候选稳定性\n'
        '- stable\n'
        '\n'
        '## 只留在当前恢复层\n'
        '- 下一步先补 apply 命令示例\n'
        '\n'
        '## 明日续接\n'
        '- 如果中断，先跑 pytest -q\n'
    )
    (workspace / 'memory-capture.md').write_text(capture_text, encoding='utf-8')

    first = run_command('apply', '--workspace', str(workspace))
    second = run_command('apply', '--workspace', str(workspace))

    assert first.returncode == 0
    assert second.returncode == 0
    memory_text = (workspace / 'MEMORY.md').read_text(encoding='utf-8')
    assert memory_text.count('memory-system__session-88__202604140900000800') == 1
    assert 'Applied distilled memory: 0 entries added, 1 skipped' in second.stdout
