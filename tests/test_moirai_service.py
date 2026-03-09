import shutil
from pathlib import Path

import pytest

from agentkit.tools.moirai.moirai import MoiraiService


def _make_workspace() -> Path:
    base = Path('.pytest-moirai-work')
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


@pytest.mark.asyncio
async def test_moirai_pause_approve_resume():
    ws = _make_workspace()
    try:
        svc = MoiraiService(workspace_root=str(ws))

        run = await svc.create_flow(
            name='demo-flow',
            goal='test resumable flow',
            steps=[
                {
                    'id': 'write',
                    'name': 'Write file',
                    'kind': 'write_file',
                    'params': {'path': 'tmp/demo.txt', 'content': 'hello'},
                },
                {
                    'id': 'gate',
                    'name': 'Manual gate',
                    'kind': 'note',
                    'require_approval': True,
                    'params': {'text': 'need approval to continue'},
                },
            ],
        )

        out1 = await svc.run_until_pause(run_id=run['run_id'])
        assert out1['status'] == 'waiting_approval'
        assert out1['cursor'] == 1

        approved = await svc.approve_step(run_id=run['run_id'], approved=True, note='safe')
        assert approved['status'] == 'paused'

        out2 = await svc.resume_flow(run_id=run['run_id'])
        assert out2['status'] == 'completed'
        assert out2['cursor'] == 2
        assert len(out2['events']) >= 4

    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_moirai_retry_and_cancel():
    ws = _make_workspace()
    try:
        svc = MoiraiService(workspace_root=str(ws))
        run = await svc.create_flow(
            name='retry-flow',
            goal='retry and cancel',
            default_retries=1,
            steps=[
                {
                    'id': 'bad-cmd',
                    'kind': 'execute_command',
                    'params': {'command': '___definitely_not_a_real_command___'},
                },
                {
                    'id': 'after',
                    'kind': 'note',
                    'params': {'text': 'after bad command'},
                },
            ],
        )

        first = await svc.run_until_pause(run_id=run['run_id'])
        assert first['status'] == 'failed'
        assert first['steps'][0]['attempts'] == 2

        reset = await svc.retry_from_step(run_id=run['run_id'], step_index=0)
        assert reset['status'] == 'paused'
        assert reset['cursor'] == 0

        cancelled = await svc.cancel_flow(run_id=run['run_id'], reason='manual stop')
        assert cancelled['status'] == 'cancelled'
        assert cancelled['cancel_reason'] == 'manual stop'

    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_moirai_list_and_get():
    ws = _make_workspace()
    try:
        svc = MoiraiService(workspace_root=str(ws))

        created = await svc.create_flow(
            name='list-flow',
            goal='list/get',
            steps=[{'kind': 'note', 'params': {'text': 'hello'}}],
        )
        got = await svc.get_flow(run_id=created['run_id'])
        assert got['run_id'] == created['run_id']

        listed = await svc.list_flows(limit=10)
        assert listed['total'] >= 1
        assert any(item['run_id'] == created['run_id'] for item in listed['items'])
    finally:
        shutil.rmtree(ws, ignore_errors=True)

@pytest.mark.asyncio
async def test_moirai_verify_file_exists_step():
    ws = _make_workspace()
    try:
        svc = MoiraiService(workspace_root=str(ws))
        run = await svc.create_flow(
            name='verify-flow',
            goal='verify primitives',
            steps=[
                {
                    'kind': 'write_file',
                    'params': {'path': 'tmp/a.txt', 'content': 'hello'},
                },
                {
                    'kind': 'verify_file_exists',
                    'params': {'path': 'tmp/a.txt'},
                },
            ],
            auto_start=True,
        )
        assert run['status'] == 'completed'
        assert run['cursor'] == 2
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_moirai_mcp_call_step(monkeypatch):
    ws = _make_workspace()
    try:
        svc = MoiraiService(workspace_root=str(ws))

        class DummyManager:
            async def unified_call(self, service_name, tool_name, args):
                return {'service': service_name, 'tool': tool_name, 'args': args, 'ok': True}

        monkeypatch.setattr('agentkit.mcp.mcp_manager.get_mcp_manager', lambda: DummyManager())

        run = await svc.create_flow(
            name='mcp-flow',
            goal='call mcp',
            steps=[
                {
                    'kind': 'mcp_call',
                    'params': {
                        'service_name': 'computer_control',
                        'tool_name': 'fs_action',
                        'args': {'action': 'list', 'path': '.'},
                    },
                }
            ],
            auto_start=True,
        )

        assert run['status'] == 'completed'
        out = run['steps'][0]['output']
        assert out['ok'] is True
        assert out['service_name'] == 'computer_control'
    finally:
        shutil.rmtree(ws, ignore_errors=True)

@pytest.mark.asyncio
async def test_moirai_auto_risk_gate_for_mcp_process_call():
    ws = _make_workspace()
    try:
        svc = MoiraiService(workspace_root=str(ws))
        run = await svc.create_flow(
            name='risk-gate',
            goal='risk gating',
            steps=[
                {
                    'kind': 'mcp_call',
                    'params': {
                        'service_name': 'computer_control',
                        'tool_name': 'process_action',
                        'args': {'action': 'run_async', 'command': 'echo hi'},
                    },
                }
            ],
        )
        assert run['steps'][0]['require_approval'] is True
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_moirai_create_download_pipeline_template():
    ws = _make_workspace()
    try:
        svc = MoiraiService(workspace_root=str(ws))
        run = await svc.create_download_pipeline(
            name='ubuntu-download',
            source_url='https://ubuntu.com/download',
            target_dir='downloads/ubuntu',
            client_command='BitComet.exe',
            process_name='BitComet',
            auto_start=False,
        )
        assert run['name'] == 'ubuntu-download'
        assert run['status'] == 'paused'
        assert any(s['kind'] == 'mcp_call' for s in run['steps'])
        assert any(s['kind'] == 'verify_command' for s in run['steps'])
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_moirai_verify_command_failure_is_reported():
    ws = _make_workspace()
    try:
        svc = MoiraiService(workspace_root=str(ws))
        run = await svc.create_flow(
            name='verify-command-fail',
            goal='verify command failure path',
            steps=[
                {
                    'kind': 'verify_command',
                    'params': {'command': 'cmd /c echo hello', 'expect_contains': '__missing_token__'},
                }
            ],
            auto_start=True,
        )
        assert run['status'] == 'failed'
        assert run['last_error']
    finally:
        shutil.rmtree(ws, ignore_errors=True)

@pytest.mark.asyncio
async def test_moirai_create_web_task_pipeline_template():
    ws = _make_workspace()
    try:
        svc = MoiraiService(workspace_root=str(ws))
        run = await svc.create_web_task_pipeline(
            name='web-task',
            start_url='https://example.com',
            target_text='Login',
            success_hint='Dashboard',
            auto_start=False,
        )
        assert run['name'] == 'web-task'
        assert run['status'] == 'paused'
        assert any(s['id'] == 'snapshot_target' for s in run['steps'])
        assert any(s['id'] == 'manual_verify_gate' for s in run['steps'])
    finally:
        shutil.rmtree(ws, ignore_errors=True)

@pytest.mark.asyncio
async def test_moirai_create_visual_text_pipeline_template():
    ws = _make_workspace()
    try:
        svc = MoiraiService(workspace_root=str(ws))
        run = await svc.create_visual_text_pipeline(
            name='visual-click',
            target_text='Download',
            success_hint='Opened',
            auto_start=False,
        )
        assert run['name'] == 'visual-click'
        assert run['status'] == 'paused'
        assert any(s['id'] == 'ocr_scan' for s in run['steps'])
        assert any(s['id'] == 'click_text' for s in run['steps'])
    finally:
        shutil.rmtree(ws, ignore_errors=True)

@pytest.mark.asyncio
async def test_moirai_create_general_web_agent_pipeline_template():
    ws = _make_workspace()
    try:
        svc = MoiraiService(workspace_root=str(ws))
        run = await svc.create_general_web_agent_pipeline(
            name='general-web-task',
            start_url='https://example.com',
            target_text='Download',
            success_hint='Completed',
            auto_start=False,
        )
        assert run['name'] == 'general-web-task'
        assert run['status'] == 'paused'
        assert any(s['id'] == 'execute_target_with_fallback' for s in run['steps'])
    finally:
        shutil.rmtree(ws, ignore_errors=True)

