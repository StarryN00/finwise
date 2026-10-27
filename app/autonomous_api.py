"""Authenticated scope APIs; model output and local workspace paths are never inputs."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from typing import Literal
import os
import stat
from app.auth import authorize_api, identity
from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed
from app.bookkeeping_profile import EnterpriseRules

router=APIRouter(prefix='/api/v1/autonomous',dependencies=[Depends(authorize_api)])
class ScopeInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    scope: Scope
class StartInput(ScopeInput):
    retry: bool=False
    recheck: StrictBool=False
class ExecutorInput(ScopeInput):
    backend: Literal['codex', 'claude_code']
class AnswerInput(ScopeInput):
    run_id: str
    finding_id: str
    text: str=Field(min_length=1,max_length=10000)
class ProcessInput(ScopeInput):
    run_id: str
class MaterialsCompleteInput(ProcessInput):
    note: str=Field(default='',max_length=10000)
class DecisionInput(MaterialsCompleteInput):
    finding_id: str
    option_id: str
    acknowledged: StrictBool

class InvoiceMatchItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    finding_id: str
    invoice_ids: list[str] = Field(default_factory=list, max_length=200)
    note: str = Field(default='', max_length=10000)

class InvoiceMatchInput(ProcessInput):
    items: list[InvoiceMatchItem] = Field(min_length=1, max_length=50)
    acknowledged: StrictBool


@router.post('/invoice-matching')
def match_invoices(body: InvoiceMatchInput, request: Request):
    actor = identity(request)
    job = request.app.state.service.autonomous.match_invoices(
        body.scope, actor['user_id'], actor['role'], body.run_id,
        [item.model_dump() for item in body.items], body.acknowledged)
    return {'run_id': job['object_id'], 'status': job['status']}

class TravelPolicyInput(ScopeInput):
    enabled: StrictBool
    expected_version: int = Field(ge=0, strict=True)
    source_note: str = Field(min_length=1, max_length=10000)


class BookkeepingProfileInput(ScopeInput):
    mode: Literal['ORIGINAL', 'AGENCY_SIMPLE']
    expected_version: int = Field(ge=0, strict=True)
    cost_ratio: str | None = Field(default=None, max_length=8, pattern=r'^(0(?:\.\d{1,4})?|1(?:\.0{1,4})?)$')
    source_note: str = Field(default='', max_length=1000)
    enterprise_rules: EnterpriseRules | None = None


@router.post('/bookkeeping-profile')
def save_bookkeeping_profile(body: BookkeepingProfileInput, request: Request):
    actor = identity(request)
    policy, job, changed = request.app.state.service.autonomous.save_bookkeeping_profile(
        body.scope, actor['user_id'], actor['role'], mode=body.mode,
        expected_version=body.expected_version, cost_ratio=body.cost_ratio, source_note=body.source_note,
        enterprise_rules=(body.enterprise_rules.model_dump(exclude_none=True)
                          if body.enterprise_rules is not None else None))
    return {'profile': policy, 'changed': changed, 'run_id': job['object_id'] if job else None,
            'status': job['status'] if job else 'SAVED'}


@router.post('/travel-policy')
def save_travel_policy(body: TravelPolicyInput, request: Request):
    actor = identity(request)
    policy, job = request.app.state.service.autonomous.save_travel_policy(
        body.scope, actor['user_id'], actor['role'], enabled=body.enabled,
        expected_version=body.expected_version, source_note=body.source_note)
    return {'policy': policy, 'run_id': job['object_id'] if job else None,
            'status': job['status'] if job else 'SAVED'}


def read_process_document(folder, relative):
    """Read a bounded regular file through pinned directory descriptors."""
    directory = document = None
    try:
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        parts = relative.split('/')
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory); directory = child
        document = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(document)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            return None
        return os.read(document, 400000).decode('utf-8', errors='replace')[:100000]
    except OSError:
        return None
    finally:
        if document is not None: os.close(document)
        if directory is not None: os.close(directory)

@router.post('/materials-complete')
def materials_complete(body:MaterialsCompleteInput,request:Request):
    actor=identity(request)
    job=request.app.state.service.autonomous.materials_complete(body.scope,actor['user_id'],actor['role'],body.run_id,body.note.strip())
    return {'run_id':job['object_id'],'status':job['status']}

@router.post('/decision')
def decision(body:DecisionInput,request:Request):
    actor=identity(request)
    job=request.app.state.service.autonomous.choose(body.scope,actor['user_id'],actor['role'],body.run_id,
        body.finding_id,body.option_id,body.acknowledged,body.note.strip())
    return {'run_id':job['object_id'],'status':job['status']}

@router.post('/start')
def start(body:StartInput,request:Request):
    actor=identity(request)
    job=request.app.state.service.autonomous.enqueue(body.scope,actor['user_id'],actor['role'],retry=body.retry,recheck=body.recheck)
    return {'run_id':job['object_id'],'status':job['status']}

@router.post('/executor')
def executor(body:ExecutorInput,request:Request):
    actor=identity(request)
    workflow=request.app.state.service.autonomous
    previous=workflow.selected_backend(body.scope)
    job=workflow.select_backend(body.scope,actor['user_id'],actor['role'],body.backend)
    return {'backend':body.backend,'changed':previous!=body.backend,
            'run_id':job['object_id'] if job else None,'status':job['status'] if job else 'WAITING_INPUT'}

@router.post('/cancel')
def cancel(body:ScopeInput,request:Request):
    actor=identity(request)
    job=request.app.state.service.autonomous.cancel(body.scope,actor['user_id'],actor['role'])
    return {'run_id':job['object_id'],'status':job['status']}

@router.post('/answer')
def answer(body:AnswerInput,request:Request):
    actor=identity(request)
    if not body.text.strip(): raise PreconditionFailed('请填写具体业务说明')
    job=request.app.state.service.autonomous.answer(body.scope,actor['user_id'],actor['role'],body.run_id,body.finding_id,body.text.strip())
    return {'run_id':job['object_id'],'status':job['status']}

@router.post('/process')
def process(body:ProcessInput,request:Request):
    service=request.app.state.service
    job=service.store.get_object(body.run_id,body.scope)
    if job['object_type']!='AutonomousMonthlyRun': raise PreconditionFailed('不是月度自主处理任务')
    from pathlib import Path
    root=service.store.database.settings.database_path.parent/'autonomous-runs'/job['object_id']
    folder=Path(job['data'].get('folder',''))
    if folder.parent.resolve()!=root.resolve(): return {'events':job['data']['events'],'documents':{}}
    docs={}
    for relative in ('executor/work/plan.md','executor/work/process.md'):
        content=read_process_document(folder,relative)
        if content is not None: docs[relative]=content
    return {'events':job['data']['events'],'documents':docs}
