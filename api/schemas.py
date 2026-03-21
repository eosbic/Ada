from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from datetime import datetime
from typing import List, Dict

class EmpresaCreate(BaseModel):
    nombre: str
    sector: Optional[str] = None

class EmpresaResponse(BaseModel):
    id: UUID
    nombre: str
    sector: Optional[str]
    created_at: datetime

class WorkflowCreate(BaseModel):
    name: str
    trigger_event: str
    actions: List[Dict]