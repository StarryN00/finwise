"""Backend adapters; task containers receive no application/database access."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid
from app.config import deepseek_claude_endpoint

BACKENDS = {'codex': 'Codex CLI', 'claude_code': 'Claude Code'}


class RetryableExecutionError(RuntimeError):
    """A temporary provider failure; the workflow can resume saved work."""


def runtime_identity(settings, backend=None):
    backend = backend or settings.autonomous_backend
    if backend not in BACKENDS:
        raise ValueError('不支持的自主执行器')
    return {'backend': backend, 'label': BACKENDS[backend],
            'model': settings.autonomous_claude_model if backend == 'claude_code' else settings.autonomous_model,
            'base_url': settings.autonomous_claude_base_url if backend == 'claude_code' else None,
            'execution_mode': settings.autonomous_execution_mode,
            'container_image': settings.autonomous_container_image if settings.autonomous_execution_mode == 'docker' else None,
            'max_rounds': settings.autonomous_max_rounds, 'timeout': settings.autonomous_timeout,
            'budget_usd': settings.autonomous_claude_budget_usd if backend == 'claude_code' else None}


def for_run(settings, identity):
    """Pin non-secret execution settings to a run; credentials stay server-side."""
    if not identity:
        return replace(settings, autonomous_backend='codex')  # Legacy runs used Codex.
    updates = {'autonomous_backend': identity['backend'],
               'autonomous_execution_mode': identity['execution_mode'],
               'autonomous_timeout': identity['timeout'], 'autonomous_max_rounds': identity['max_rounds']}
    if identity['backend'] == 'claude_code':
        if identity.get('base_url', settings.autonomous_claude_base_url).rstrip('/') != settings.autonomous_claude_base_url.rstrip('/'):
            raise ValueError('模型接口配置已变化，请建立新一轮任务，避免凭据与旧接口混用')
        updates.update(autonomous_claude_model=identity['model'], autonomous_claude_budget_usd=identity['budget_usd'])
    else:
        updates['autonomous_model'] = identity['model']
    if identity.get('container_image'):
        updates['autonomous_container_image'] = identity['container_image']
    return replace(settings, **updates)


def availability(settings, backend):
    label = BACKENDS[backend]
    if settings.autonomous_execution_mode == 'docker':
        if not shutil.which(settings.autonomous_docker_path):
            return False, '服务器尚未安装 Docker 执行工具'
        key = settings.autonomous_claude_api_key if backend == 'claude_code' else settings.autonomous_codex_api_key
        return bool(key), '服务器凭据已配置，执行时检查容器与授权' if key else label + ' 服务器凭据尚未配置'
    cli = settings.autonomous_claude_path if backend == 'claude_code' else settings.autonomous_codex_path
    return bool(shutil.which(cli)), '执行器已安装，执行时检查授权' if shutil.which(cli) else label + ' 未安装或路径无效'


def choices(settings):
    return [{'id': backend, 'label': label, 'model': runtime_identity(settings, backend)['model'],
             'available': availability(settings, backend)[0], 'message': availability(settings, backend)[1]}
            for backend, label in BACKENDS.items()]


def claude_result(path):
    terminal = None
    initial = {}
    with path.open() as stream:
        for line in stream:
            try: event = json.loads(line)
            except ValueError: continue
            if not isinstance(event, dict): continue
            if event.get('type') == 'system' and event.get('subtype') == 'init':
                initial = {key: event.get(key) for key in ('model', 'claude_code_version')}
            if event.get('type') == 'result': terminal = event
    if terminal is not None: terminal['_finwise_initial'] = initial
    return terminal


def claude_error(terminal, settings=None):
    text = str((terminal or {}).get('result', '')).lower()
    if 'not logged in' in text or 'authentication' in text or 'invalid api key' in text:
        if settings and deepseek_claude_endpoint(settings.autonomous_claude_base_url):
            return 'DeepSeek 授权无效；请检查 DeepSeek API Key，本模式不需要 Claude 账号登录'
        return 'Claude Code 授权无效；本机请运行 claude auth login，服务器请检查专用 API Key'
    if 'budget' in str((terminal or {}).get('subtype', '')):
        return 'Claude Code 已达到单次预算上限；本轮未通过，请调整部署预算后重试'
    return 'Claude Code 未完成有效执行；请检查授权、预算和执行日志'


def raise_claude_failure(terminal, settings):
    details = json.dumps(terminal or {}, ensure_ascii=False).lower()
    if any(marker in details for marker in ('rate_limit', 'rate limit', 'overloaded', 'econnreset',
                                            'connection error', 'timed out', 'status 429', 'status 503',
                                            '"status": 429', '"status": 503', '"status": 502')):
        raise RetryableExecutionError('模型服务暂时不可用，系统将保留进度后自动接续')
    raise RuntimeError(claude_error(terminal, settings))


def command_for(settings, workspace, final_path, *, container=False):
    if settings.autonomous_backend == 'claude_code':
        command = ['claude' if container else settings.autonomous_claude_path, '-p',
                   '--model', settings.autonomous_claude_model, '--output-format', 'stream-json', '--verbose',
                   '--no-session-persistence', '--setting-sources', '', '--disable-slash-commands',
                   '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                   '--settings', '{"disableAllHooks":true,"autoMemoryEnabled":false}',
                   '--permission-mode', 'dontAsk', '--tools', 'Bash,Read,Write,Edit,Glob,Grep',
                   '--allowedTools', 'Bash,Read,Write,Edit,Glob,Grep']
        if settings.autonomous_claude_budget_usd > 0:
            command += ['--max-budget-usd', str(settings.autonomous_claude_budget_usd)]
        # Bare mode intentionally ignores desktop subscription/keychain state.
        if container or settings.autonomous_claude_api_key:
            command.append('--bare')
        return command
    return ['codex' if container else settings.autonomous_codex_path, 'exec', '--ignore-user-config',
            '-m', settings.autonomous_model, '-s', 'danger-full-access' if container else 'workspace-write', '-c', 'approval_policy="never"',
            '--skip-git-repo-check', '--json', '-C', str(workspace), '-o', str(final_path), '-']


def child_environment(settings):
    env = {k: v for k, v in os.environ.items() if k in
           {'HOME', 'PATH', 'TMPDIR', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY'}}
    if settings.autonomous_backend == 'claude_code' and settings.autonomous_claude_api_key:
        env['ANTHROPIC_API_KEY'] = settings.autonomous_claude_api_key
        env['ANTHROPIC_BASE_URL'] = settings.autonomous_claude_base_url
        if deepseek_claude_endpoint(settings.autonomous_claude_base_url):
            # Internal utility calls must use DeepSeek too, not Claude model aliases.
            for name in ('ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL',
                         'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL'):
                env[name] = settings.autonomous_claude_model
            env['CLAUDE_CODE_EFFORT_LEVEL'] = 'max'
            env['CLAUDE_CODE_AUTO_COMPACT_WINDOW'] = '786432' if '[1m]' in settings.autonomous_claude_model else '153600'
    elif settings.autonomous_backend == 'codex' and settings.autonomous_codex_api_key:
        env['CODEX_API_KEY'] = settings.autonomous_codex_api_key
    return env


def container_command(settings, workspace, name, env):
    """Mount only this run, then overlay originals/tools/candidate read-only."""
    run_root = settings.database_path.parent / 'autonomous-runs'
    relative = workspace.resolve().relative_to(run_root.resolve())
    host = Path(settings.autonomous_host_run_root) / relative
    command = [settings.autonomous_docker_path, 'run', '--rm', '-i', '--init', '--name', name,
               '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--pids-limit', '256', '--memory', '2g', '--cpus', '2',
               '--user', f'{os.getuid()}:{os.getgid()}', '--workdir', '/workspace',
               '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m,mode=1777', '--env', 'HOME=/tmp/agent-home',
               '--env', 'PYTHONDONTWRITEBYTECODE=1',
               '--mount', f'type=bind,src={host},dst=/workspace']
    for item in ('sources', 'tools', 'manifest.json', 'context.json', 'CONTRACT.md', 'candidate'):
        source = workspace / item
        if source.exists():
            if source.is_symlink():
                raise ValueError('任务挂载不允许符号链接')
            command += ['--mount', f'type=bind,src={host/item},dst=/workspace/{item},readonly']
    for key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'CODEX_API_KEY', 'ANTHROPIC_MODEL',
                'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
                'CLAUDE_CODE_SUBAGENT_MODEL', 'CLAUDE_CODE_EFFORT_LEVEL', 'CLAUDE_CODE_AUTO_COMPACT_WINDOW'):
        if key in env:
            command += ['--env', key]  # Values never appear in process arguments or persisted metadata.
    # A host crash must not leave an unbounded remote agent process behind.
    command += [settings.autonomous_container_image, 'timeout', '--signal=TERM', '--kill-after=10',
                str(settings.autonomous_timeout), *command_for(settings, Path('/workspace'), Path('/workspace/final.md'), container=True)]
    return command


def execute(workspace, prompt, log_base, settings, heartbeat):
    settings.validate_runtime()
    available, message = availability(settings, settings.autonomous_backend)
    if not available:
        raise RuntimeError(message)
    log_base.with_suffix('.prompt.txt').write_text(prompt)
    write_identity = runtime_identity(settings)
    log_base.with_suffix('.runtime.json').write_text(json.dumps(write_identity, ensure_ascii=False))
    env = child_environment(settings)
    name = 'finwise-agent-' + uuid.uuid4().hex
    container = settings.autonomous_execution_mode == 'docker'
    command = container_command(settings, workspace, name, env) if container else command_for(settings, workspace, log_base.with_suffix('.final.md'))
    started = time.monotonic()
    with log_base.with_suffix('.jsonl').open('w') as out, log_base.with_suffix('.stderr').open('w') as err:
        proc = subprocess.Popen(command, cwd=workspace, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                text=True, start_new_session=True, env=env)
        try:
            proc.stdin.write(prompt); proc.stdin.close()
            while proc.poll() is None:
                heartbeat()
                if time.monotonic() - started > settings.autonomous_timeout:
                    raise TimeoutError('模型执行超时，可保留过程后重试')
                time.sleep(1)
            if proc.returncode:
                if settings.autonomous_backend == 'claude_code':
                    raise_claude_failure(claude_result(log_base.with_suffix('.jsonl')), settings)
                raise RuntimeError(f'{BACKENDS[settings.autonomous_backend]} 执行失败（退出码 {proc.returncode}），日志已保留')
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL); proc.wait()
            if container:
                # docker CLI termination alone does not stop its remote container.
                subprocess.run([settings.autonomous_docker_path, 'rm', '-f', name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)
            if settings.autonomous_backend == 'claude_code':
                terminal = claude_result(log_base.with_suffix('.jsonl'))
                if terminal:
                    # Retain reported usage for failures as well as successful calls.
                    write_identity['usage'] = {key: terminal.get(key) for key in ('total_cost_usd', 'usage', 'duration_ms', 'num_turns')}
                    write_identity['resolved_model'] = terminal['_finwise_initial'].get('model')
                    write_identity['cli_version'] = terminal['_finwise_initial'].get('claude_code_version')
                    write_identity['outcome'] = terminal.get('subtype')
                    log_base.with_suffix('.runtime.json').write_text(json.dumps(write_identity, ensure_ascii=False))
    if settings.autonomous_backend == 'claude_code':
        terminal = claude_result(log_base.with_suffix('.jsonl'))
        if not terminal or terminal.get('is_error') or terminal.get('subtype') != 'success':
            raise_claude_failure(terminal, settings)
        log_base.with_suffix('.final.md').write_text(str(terminal.get('result', '')))
