"""Scoped experimental monthly processing endpoints; never formal posting."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from app.auth import authorize_api, identity
from app.ontology.contracts import Scope

router=APIRouter(prefix='/api/v1/monthly',dependencies=[Depends(authorize_api)])

class StartMonthly(BaseModel):
    model_config=ConfigDict(extra='forbid')
    scope: Scope
    source_ids: list[str]=Field(min_length=1,max_length=20)

@router.post('/start')
def start(body:StartMonthly,request:Request):
    actor=identity(request)
    run=request.app.state.monthly_agent.enqueue(body.scope,body.source_ids,actor['user_id'],actor['role'])
    return {'run_id':run['object_id'],'status':run['status'],'formal_balance_impact':False}

@router.get('/runs')
def runs(request:Request):
    scope=Scope.model_validate(dict(request.query_params))
    return request.app.state.monthly_agent.view(scope)
