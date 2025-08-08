import os
import json
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from collections import Counter

from app.database import get_db
from app.models.user import User
from app.models.parse_result import ParseResult
from app.schemas.parser import (
    ParseResult as ParseResultSchema,
    ParseSummary,
    CPUMemoryData,
    DeviceInventory,
    DeviceInterfaces
)
from app.utils.auth import get_current_active_user
from app.utils.parser import parse_network_file
from app.config import settings

router = APIRouter(prefix="/parser", tags=["parser"])
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = [".txt", ".log"]

@router.post("/upload", response_model=List[ParseResultSchema])
async def upload_files(
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Upload and parse network device files."""
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded"
        )
    
    # Create user upload directory
    user_upload_dir = os.path.join(settings.upload_dir, str(current_user.id))
    os.makedirs(user_upload_dir, exist_ok=True)
    
    parsed_results = []
    
    for uploaded_file in files:
        # Check file extension
        file_extension = os.path.splitext(uploaded_file.filename)[1].lower()
        if file_extension not in ALLOWED_EXTENSIONS:
            logger.warning(f"Skipping unsupported file extension: {uploaded_file.filename}")
            continue
        
        # Save uploaded file
        file_path = os.path.join(user_upload_dir, uploaded_file.filename)
        with open(file_path, "wb") as f:
            content = await uploaded_file.read()
            f.write(content)
        
        # Read and parse file content
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                file_content = f.read()
        except Exception as e:
            logger.error(f"Error reading file {uploaded_file.filename}: {e}")
            continue
        
        # Parse the network file
        parsed_data = parse_network_file(file_content, uploaded_file.filename)
        
        # Save to database
        db_parse_result = ParseResult(
            user_id=current_user.id,
            filename=uploaded_file.filename,
            platform=parsed_data["platform"],
            parsed_data=parsed_data["data"],
            file_path=file_path
        )
        db.add(db_parse_result)
        db.commit()
        db.refresh(db_parse_result)
        
        parsed_results.append(db_parse_result)
        logger.info(f"Successfully parsed and saved: {uploaded_file.filename}")
    
    return parsed_results

@router.get("/results", response_model=List[ParseResultSchema])
def get_parse_results(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all parse results for the current user."""
    results = db.query(ParseResult).filter(ParseResult.user_id == current_user.id).all()
    return results

@router.get("/results/{result_id}", response_model=ParseResultSchema)
def get_parse_result(
    result_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get a specific parse result."""
    result = db.query(ParseResult).filter(
        ParseResult.id == result_id,
        ParseResult.user_id == current_user.id
    ).first()
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parse result not found"
        )
    
    return result

@router.delete("/results/{result_id}")
def delete_parse_result(
    result_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete a specific parse result."""
    result = db.query(ParseResult).filter(
        ParseResult.id == result_id,
        ParseResult.user_id == current_user.id
    ).first()
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parse result not found"
        )
    
    # Delete file from filesystem
    try:
        if os.path.exists(result.file_path):
            os.remove(result.file_path)
    except Exception as e:
        logger.warning(f"Could not delete file {result.file_path}: {e}")
    
    # Delete from database
    db.delete(result)
    db.commit()
    
    return {"message": "Parse result deleted successfully"}

@router.get("/summary", response_model=List[ParseSummary])
def get_summary(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get summary view of all parsed devices."""
    results = db.query(ParseResult).filter(ParseResult.user_id == current_user.id).all()
    
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No parse results found"
        )
    
    summaries = []
    for result in results:
        version_data = {}
        cpu_memory_data = result.parsed_data.get("Calculated_CPU_Memory", {})
        
        # Extract version data based on platform
        if result.platform == "cisco_ios":
            version_list = result.parsed_data.get("show version", [])
        elif result.platform == "cisco_nxos":
            version_list = result.parsed_data.get("show version", [])
        elif result.platform == "aruba_aoscx":
            version_list = result.parsed_data.get("show system", [])
        elif result.platform in ["huawei_vrp", "huawei_yunshan"]:
            version_list = result.parsed_data.get("display version", [])
        else:
            version_list = []
        
        if version_list and isinstance(version_list, list) and version_list:
            version_data = version_list[0]
            # Clean up string values
            for key, value in version_data.items():
                if isinstance(value, str):
                    version_data[key] = value.strip()
        
        version_data['platform_name'] = result.platform
        
        summaries.append(ParseSummary(
            filename=result.filename,
            platform=result.platform,
            version_data=version_data,
            cpu_memory_data=cpu_memory_data
        ))
    
    return summaries

@router.get("/cpu-memory", response_model=Dict[str, CPUMemoryData])
def get_cpu_memory_usage(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get CPU and Memory usage for all devices."""
    results = db.query(ParseResult).filter(ParseResult.user_id == current_user.id).all()
    
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No parse results found"
        )
    
    cpu_memory_data = {}
    for result in results:
        calculated_data = result.parsed_data.get("Calculated_CPU_Memory", {})
        cpu_memory_data[result.filename] = CPUMemoryData(
            cpu_max=calculated_data.get("cpu_max", "N/A"),
            cpu_avg=calculated_data.get("cpu_avg", "N/A"),
            memory_usage_percent=str(calculated_data.get("memory_usage_percent", "N/A"))
        )
    
    return cpu_memory_data

@router.get("/inventory", response_model=List[DeviceInventory])
def get_inventory(
    hostname: str = Query(None, description="Filter by hostname"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get inventory information for devices."""
    query = db.query(ParseResult).filter(ParseResult.user_id == current_user.id)
    
    if hostname:
        query = query.filter(ParseResult.filename == hostname)
    
    results = query.all()
    
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No parse results found"
        )
    
    inventory_data = []
    for result in results:
        inventory = []
        
        if result.platform == "cisco_ios":
            inventory = result.parsed_data.get("show inventory", [])
        elif result.platform == "cisco_nxos":
            inventory = result.parsed_data.get("show inventory", [])
        elif result.platform == "aruba_aoscx":
            inventory = result.parsed_data.get("show inventory", [])
        elif result.platform in ["huawei_vrp", "huawei_yunshan"]:
            inventory = result.parsed_data.get("display device", [])
        
        inventory_data.append(DeviceInventory(
            filename=result.filename,
            inventory=inventory
        ))
    
    return inventory_data

@router.get("/interfaces", response_model=Dict[str, Any])
def get_interfaces(
    hostname: str = Query(None, description="Filter by hostname"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get interface information for devices with statistics."""
    query = db.query(ParseResult).filter(ParseResult.user_id == current_user.id)
    
    if hostname:
        query = query.filter(ParseResult.filename == hostname)
    
    results = query.all()
    
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No parse results found"
        )
    
    interface_data = []
    link_status_counts = Counter()
    speed_counts = Counter()
    
    for result in results:
        interfaces = []
        
        if result.platform == "cisco_ios":
            interfaces = result.parsed_data.get("show interfaces", [])
        elif result.platform == "cisco_nxos":
            interfaces = result.parsed_data.get("show interface", [])
        elif result.platform == "aruba_aoscx":
            interfaces = result.parsed_data.get("show interface", [])
        elif result.platform in ["huawei_vrp", "huawei_yunshan"]:
            interfaces = result.parsed_data.get("display interface", [])
        
        interface_data.append(DeviceInterfaces(
            filename=result.filename,
            interfaces=interfaces
        ))
        
        # Count statistics
        for iface in interfaces:
            link_status = iface.get("link_status", iface.get("status", "unknown")).lower() or "unknown"
            speed = iface.get("speed", iface.get("bandwidth", "unknown")).lower() or "unknown"
            
            link_status_counts[link_status] += 1
            speed_counts[speed] += 1
    
    return {
        "interface_data": interface_data,
        "hostnames": [result.filename for result in results],
        "selected_hostname": hostname,
        "link_status_stats": {
            "labels": list(link_status_counts.keys()),
            "values": list(link_status_counts.values())
        },
        "speed_stats": {
            "labels": list(speed_counts.keys()),
            "values": list(speed_counts.values())
        }
    }

@router.get("/download/{result_id}")
def download_json(
    result_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Download parsed JSON output for a specific result."""
    result = db.query(ParseResult).filter(
        ParseResult.id == result_id,
        ParseResult.user_id == current_user.id
    ).first()
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parse result not found"
        )
    
    # Create temporary JSON file
    temp_json_path = f"/tmp/{result.filename}_{result.id}_parsed.json"
    
    try:
        with open(temp_json_path, "w", encoding="utf-8") as f:
            json.dump({
                "filename": result.filename,
                "platform": result.platform,
                "parsed_data": result.parsed_data,
                "created_at": result.created_at.isoformat()
            }, f, indent=4)
        
        return FileResponse(
            temp_json_path,
            media_type="application/json",
            filename=f"{result.filename}_parsed.json"
        )
    except Exception as e:
        logger.error(f"Error creating JSON file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creating download file"
        )