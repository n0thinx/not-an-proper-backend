from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime

class ParseResultBase(BaseModel):
    filename: str
    platform: str
    parsed_data: Dict[str, Any]

class ParseResultCreate(ParseResultBase):
    file_path: str

class ParseResult(ParseResultBase):
    id: int
    user_id: int
    file_path: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class ParseSummary(BaseModel):
    filename: str
    platform: str
    version_data: Dict[str, Any]
    cpu_memory_data: Dict[str, Any]

class CPUMemoryData(BaseModel):
    cpu_max: str
    cpu_avg: str
    memory_usage_percent: str

class DeviceInventory(BaseModel):
    filename: str
    inventory: List[Dict[str, Any]]

class DeviceInterfaces(BaseModel):
    filename: str
    interfaces: List[Dict[str, Any]]