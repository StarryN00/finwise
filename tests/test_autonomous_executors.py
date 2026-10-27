from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess

import pytest

from app.config import Settings
from app.autonomous_executors import child_environment, command_for, container_command, execute, for_run, runtime_identity, claude_error


@pytest.fixture
def settings(tmp_path):
    return Settings(root=Path(__file__).resolve().parents[1], database_path=tmp_path/'finwise.db', storage_path=tmp_path/'artifacts')


def test_backend_and_model_are_pinned_without_credentials(settings):
    configured=replace(settings, autonomous_claude_api_key='private-key')
    identity=runtime_identity(configured, 'claude_code')
    changed=replace(configured, autonomous_claude_model='opus', autonomous_backend='codex')
    pinned=for_run(changed,identity)
    assert pinned.autonomous_backend=='claude_code' and pinned.autonomous_claude_model=='sonnet'
    assert 'private-key' not in json.dumps(identity)
    assert for_run(changed,None).autonomous_backend=='codex'
    assert identity['base_url']=='https://api.anthropic.com'
    with pytest.raises(ValueError,match='接口配置已变化'):
        for_run(replace(changed,autonomous_claude_base_url='https://api.deepseek.com/anthropic'),identity)


def test_deepseek_route_reuses_only_deepseek_key(tmp_path,monkeypatch):
    for name in ('FINWISE_CLAUDE_API_KEY','FINWISE_CLAUDE_BASE_URL','FINWISE_DEEPSEEK_API_KEY','ANTHROPIC_API_KEY'):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('FINWISE_DEEPSEEK_API_KEY','deepseek-key')
    monkeypatch.setenv('ANTHROPIC_API_KEY','anthropic-key')
    monkeypatch.setenv('FINWISE_CLAUDE_API_KEY','')
    monkeypatch.setenv('FINWISE_CLAUDE_BASE_URL','https://api.deepseek.com/anthropic')
    s=Settings.from_env(tmp_path)
    assert s.autonomous_claude_api_key=='deepseek-key'
    monkeypatch.setenv('FINWISE_CLAUDE_BASE_URL','https://api.anthropic.com')
    assert Settings.from_env(tmp_path).autonomous_claude_api_key=='anthropic-key'
    monkeypatch.delenv('ANTHROPIC_API_KEY')
    monkeypatch.setenv('FINWISE_CLAUDE_BASE_URL','https://api.deepseek.com.evil.test/anthropic')
    assert not Settings.from_env(tmp_path).autonomous_claude_api_key
    with pytest.raises(ValueError,match='URL 不得包含凭据'):
        replace(s,autonomous_claude_base_url='https://api.deepseek.com/anthropic?key=private').validate_runtime()


def test_deepseek_internal_models_and_container_environment(settings):
    s=replace(settings,autonomous_backend='claude_code',autonomous_claude_model='deepseek-v4-pro[1m]',
              autonomous_claude_base_url='https://api.deepseek.com/anthropic',autonomous_claude_api_key='deepseek-key')
    env=child_environment(s)
    assert env['ANTHROPIC_API_KEY']=='deepseek-key'
    for name in ('ANTHROPIC_MODEL','ANTHROPIC_DEFAULT_OPUS_MODEL','ANTHROPIC_DEFAULT_SONNET_MODEL',
                 'ANTHROPIC_DEFAULT_HAIKU_MODEL','CLAUDE_CODE_SUBAGENT_MODEL'):
        assert env[name]=='deepseek-v4-pro[1m]'
    assert env['CLAUDE_CODE_AUTO_COMPACT_WINDOW']=='786432'
    workspace=settings.database_path.parent/'autonomous-runs'/'test';workspace.mkdir(parents=True)
    cmd=container_command(replace(s,autonomous_host_run_root='/srv/autonomous-runs'),workspace,'test',env)
    assert 'ANTHROPIC_DEFAULT_HAIKU_MODEL' in cmd and 'deepseek-key' not in ' '.join(cmd)
    assert 'DeepSeek 授权无效' in claude_error({'result':'Not logged in'},s)


def test_claude_runs_without_interactive_or_host_plugins(settings, tmp_path):
    s=replace(settings, autonomous_backend='claude_code', autonomous_claude_api_key='key')
    args=command_for(s,tmp_path,tmp_path/'final')
    assert '-p' in args and '--bare' in args
    assert args[args.index('--permission-mode')+1]=='dontAsk'
    assert args[args.index('--mcp-config')+1]=='{"mcpServers":{}}'
    assert args[args.index('--setting-sources')+1]==''
    assert '--dangerously-skip-permissions' not in args
    # Desktop subscription login is permitted only in development local mode.
    assert '--bare' not in command_for(replace(s,autonomous_claude_api_key=''),tmp_path,tmp_path/'final')


def test_no_cost_ceiling_by_default_but_explicit_limits_still_work(settings,tmp_path):
    s=replace(settings,autonomous_backend='claude_code')
    s.validate_runtime()
    assert s.autonomous_claude_budget_usd==0
    assert '--max-budget-usd' not in command_for(s,tmp_path,tmp_path/'final')
    limited=command_for(replace(s,autonomous_claude_budget_usd=12.5),tmp_path,tmp_path/'final')
    assert limited[limited.index('--max-budget-usd')+1]=='12.5'
    for invalid in (-1,float('nan'),float('inf')):
        with pytest.raises(ValueError,match='预算'):
            replace(s,autonomous_claude_budget_usd=invalid).validate_runtime()


def test_child_gets_only_selected_provider_credential(settings, monkeypatch):
    monkeypatch.setenv('DATABASE_PASSWORD','never-pass')
    monkeypatch.setenv('FINWISE_DEEPSEEK_API_KEY','never-pass')
    monkeypatch.setenv('ANTHROPIC_API_KEY','ambient-key')
    s=replace(settings,autonomous_backend='claude_code',autonomous_claude_api_key='selected-key',autonomous_codex_api_key='other-key')
    env=child_environment(s)
    assert env['ANTHROPIC_API_KEY']=='selected-key'
    assert not {'DATABASE_PASSWORD','FINWISE_DEEPSEEK_API_KEY','CODEX_API_KEY'} & env.keys()
    assert 'ANTHROPIC_API_KEY' not in child_environment(settings)


def test_production_requires_containers_auth_and_host_mapping(settings):
    with pytest.raises(ValueError,match='任务隔离'):
        replace(settings,autonomous_enabled=True,environment='production').validate_runtime()
    with pytest.raises(ValueError,match='绝对任务目录'):
        replace(settings,autonomous_enabled=True,autonomous_execution_mode='docker').validate_runtime()
    s=replace(settings,autonomous_enabled=True,environment='production',autonomous_execution_mode='docker',
              autonomous_host_run_root='/srv/finwise/autonomous-runs')
    s.validate_runtime()  # Autonomous-only deployments do not require unused DeepSeek credentials.
    with pytest.raises(ValueError,match='认证'):
        replace(s,require_auth=False).validate_runtime()


def test_container_has_only_task_mounts_and_readonly_evidence(settings):
    workspace=settings.database_path.parent/'autonomous-runs'/'run'/'lease'/'review-1'
    workspace.mkdir(parents=True)
    for name in ('sources','tools','candidate'): (workspace/name).mkdir()
    for name in ('manifest.json','context.json','CONTRACT.md'): (workspace/name).write_text('{}')
    s=replace(settings,autonomous_backend='claude_code',autonomous_execution_mode='docker',autonomous_host_run_root='/srv/finwise/autonomous-runs')
    cmd=container_command(s,workspace,'test',{'ANTHROPIC_API_KEY':'secret'})
    text=' '.join(cmd)
    assert '/srv/finwise/autonomous-runs/run/lease/review-1' in text
    assert 'dst=/workspace/candidate,readonly' in text and 'dst=/workspace/sources,readonly' in text
    assert '--read-only' in cmd and '--cap-drop' in cmd
    assert 'finwise.db' not in text and 'secret' not in text and 'docker.sock' not in text
    assert '--env' in cmd and 'ANTHROPIC_API_KEY' in cmd
    with pytest.raises(ValueError): container_command(s,workspace.parent.parent.parent.parent,'test',{})


def test_claude_zero_exit_with_error_result_is_rejected(settings,tmp_path):
    cli=tmp_path/'fake-claude'
    cli.write_text('#!/bin/sh\ncat >/dev/null\nprintf \'{"type":"result","subtype":"error_max_budget_usd","is_error":true,"total_cost_usd":5.01}\\n\'\n')
    cli.chmod(0o755)
    s=replace(settings,autonomous_backend='claude_code',autonomous_claude_path=str(cli))
    with pytest.raises(RuntimeError,match='预算上限'):
        execute(tmp_path,'prompt',tmp_path/'worker',s,lambda:None)
    assert json.loads((tmp_path/'worker.runtime.json').read_text())['usage']['total_cost_usd']==5.01


def test_temporary_model_failure_can_retry_but_auth_failure_cannot(settings):
    from app.autonomous_executors import RetryableExecutionError,raise_claude_failure
    with pytest.raises(RetryableExecutionError):
        raise_claude_failure({'errors':['rate_limit_error']},settings)
    with pytest.raises(RuntimeError) as error:
        raise_claude_failure({'result':'invalid api key'},settings)
    assert not isinstance(error.value,RetryableExecutionError)


def test_cancel_stops_child_and_cleans_remote_container(settings,tmp_path,monkeypatch):
    work=settings.database_path.parent/'autonomous-runs'/'run'/'lease'/'executor';work.mkdir(parents=True)
    s=replace(settings,autonomous_execution_mode='docker',autonomous_host_run_root=str(settings.database_path.parent/'autonomous-runs'),autonomous_codex_api_key='key')
    class Child:
        pid=12
        stdin=type('Input',(),{'write':lambda *_:None,'close':lambda *_:None})()
        def poll(self): return None
        def wait(self,timeout): return 0
    removed=[];killed=[]
    monkeypatch.setattr(subprocess,'Popen',lambda *_args,**_kwargs:Child())
    monkeypatch.setattr(subprocess,'run',lambda cmd,**kwargs:removed.append(cmd))
    monkeypatch.setattr(os,'killpg',lambda pid,signal:killed.append(pid))
    def cancel(): raise RuntimeError('任务已暂停')
    with pytest.raises(RuntimeError,match='暂停'):execute(work,'prompt',tmp_path/'worker',s,cancel)
    assert killed==[12] and removed[0][1:3]==['rm','-f']


def test_host_must_not_follow_agent_output_links_before_review(tmp_path,monkeypatch,settings):
    from app import autonomous_runtime as runtime
    secret=tmp_path/'application-secret';secret.write_text('server-private')
    def worker(workspace,prompt,logs,settings,heartbeat):
        (workspace/'work'/'outside').symlink_to(secret)
    monkeypatch.setattr(runtime,'execute',worker)
    with pytest.raises(ValueError,match='链接或特殊文件'):
        runtime.run(tmp_path/'run',{'period':'2026-08','sources':[]},{},{},settings,lambda:None,lambda *_:None)
    assert not (tmp_path/'run'/'review-1').exists()


def test_special_files_and_hardlinks_are_rejected(tmp_path):
    from app.autonomous_runtime import assert_safe_tree
    root=tmp_path/'output';root.mkdir()
    source=tmp_path/'secret';source.write_text('private')
    os.link(source,root/'hardlink')
    with pytest.raises(ValueError,match='链接或特殊文件'):assert_safe_tree(root)
    (root/'hardlink').unlink();os.mkfifo(root/'pipe')
    with pytest.raises(ValueError,match='链接或特殊文件'):assert_safe_tree(root)


def test_live_process_document_reads_only_regular_files_without_following_links(tmp_path):
    from app.autonomous_api import read_process_document
    folder=tmp_path/'run';work=folder/'executor'/'work';work.mkdir(parents=True)
    plan=work/'plan.md';plan.write_text('plan'*50000)
    assert len(read_process_document(folder,'executor/work/plan.md'))==100000
    plan.unlink();plan.symlink_to(tmp_path/'not-present')
    assert read_process_document(folder,'executor/work/plan.md') is None
    plan.unlink();os.mkfifo(plan)
    assert read_process_document(folder,'executor/work/plan.md') is None
    plan.unlink();work.rmdir();work.symlink_to(tmp_path)
    assert read_process_document(folder,'executor/work/plan.md') is None
