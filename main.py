"""
FastAPI Main Application for Construction Quantity Takeoff Engine
==================================================================

Production-ready API with:
- File upload endpoint for DWG/DXF
- Complete BOM calculation
- Excel-ready JSON output
- Health check and admin endpoints
- v1.1: Interactive Material Selection

2026 Architecture Notes:
- Async-first design for high concurrency
- Comprehensive error handling with graceful degradation
- Structured logging for production monitoring
- CORS enabled for frontend integration

Author: AI Solutions Architect
Version: 1.1.0 (Material Selection)
"""

import uuid
import logging
import logging.config
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
from decimal import Decimal
import tempfile
import shutil
import time

from fastapi import (
    FastAPI, HTTPException, UploadFile, File, 
    Form, Depends, BackgroundTasks, Query
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from config import API, LOGGING_CONFIG, GEOMETRY, RoomType, ROOM_MATERIALS
from database import (
    get_db, init_database, RecipeEngine,
    Project, Quantity, RefPose,
    # v1.1: Material Selection helpers
    get_poses_by_category, get_all_pose_categories,
    get_poses_for_surface_type, get_pose_by_code, get_all_poses_simple
)
from geometry_engine import (
    CadProcessor, QuantityCalculator, ProcessingResult,
    DetectedBlock, DetectedRoom, ProcessingWarning
)


# =============================================================================
# LOGGING SETUP
# =============================================================================

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("construction_engine.api")


# =============================================================================
# PYDANTIC MODELS (Request/Response)
# =============================================================================

class GeoLocation(BaseModel):
    """Geographic location metadata."""
    sehir: str = Field(..., description="City name", example="Istanbul")
    ilce: str = Field(..., description="District name", example="Kadikoy")
    deprem_bolgesi: int = Field(1, ge=1, le=5, description="Earthquake zone (1-5)")


class StructuralParams(BaseModel):
    """Structural parameters for the project."""
    yapi_sistemi: str = Field("Betonarme", description="Construction system")
    beton_sinifi: str = Field("C30", description="Concrete class")
    demir_orani: int = Field(120, description="Steel ratio (kg/m³)")
    kat_yuksekligi_cm: int = Field(280, description="Floor height in cm")
    temel_tipi: str = Field("Radye", description="Foundation type")


class EconomicParams(BaseModel):
    """Economic parameters for cost calculation."""
    fiyat_donemi: str = Field("2026-Q1", description="Price period")
    para_birimi: str = Field("TRY", description="Currency code")
    kar_orani: int = Field(25, ge=0, le=100, description="Profit margin %")


class ProjectMetaData(BaseModel):
    """Complete project metadata (N8N automation ready)."""
    geo_location: GeoLocation
    structural_params: StructuralParams
    economic_params: EconomicParams
    project_stats: dict = Field(default_factory=lambda: {
        "blok_sayisi": 0,
        "toplam_insaat_alani": 0
    })


class AnalyzeRequest(BaseModel):
    """Request model for file analysis (when using JSON body)."""
    drawing_unit: str = Field("cm", description="Drawing unit: mm, cm, or m")
    meta_data: ProjectMetaData


class WarningResponse(BaseModel):
    """Warning item in response."""
    type: str
    message: str
    location: Optional[tuple[float, float]] = None


class MaterialBreakdown(BaseModel):
    """Material breakdown from recipe."""
    material: str
    quantity: float
    unit: str
    waste_included: bool = True


class RoomQuantity(BaseModel):
    """Quantity calculation for a single room."""
    pose_code: str
    description: str
    category: str  # floor, wall, ceiling, additional
    quantity: float
    unit: str
    recipe_breakdown: list[MaterialBreakdown] = []


class RoomResponse(BaseModel):
    """Room data in response."""
    name: str
    room_type: str
    area_m2: float
    perimeter_m: float
    wall_area_m2: float
    opening_count: int
    materials: list[RoomQuantity]


class FloorResponse(BaseModel):
    """Floor data in response."""
    name: str
    rooms: list[RoomResponse]
    total_area_m2: float


class BlockResponse(BaseModel):
    """Block data in response."""
    name: str
    floors: list[FloorResponse]
    total_area_m2: float
    room_count: int


class BOMSummaryItem(BaseModel):
    """Aggregated BOM item for summary."""
    pose_code: str
    description: str
    category: str
    total_quantity: float
    unit: str
    recipe_breakdown: list[MaterialBreakdown] = []


class AnalysisResponse(BaseModel):
    """Complete analysis response (Excel-ready JSON)."""
    project_id: str
    project_name: str
    calculated_at: str
    file_hash: Optional[str]
    
    summary: dict = Field(default_factory=dict)
    blocks: list[BlockResponse]
    bom_summary: list[BOMSummaryItem]
    
    warnings: list[WarningResponse]
    stats: dict


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    database: str
    oda_converter: str


class PoseResponse(BaseModel):
    """Reference pose info."""
    code: str
    description: str
    category: str
    unit: str
    default_unit_price: dict


# =============================================================================
# v1.1 MODELS: Material Selection
# =============================================================================

class AssignedMaterial(BaseModel):
    """Material assigned to a surface type."""
    pose_code: str
    pose_name: str
    surface_type: str  # floor, wall, ceiling


class DetectedRoomInfo(BaseModel):
    """Detected room info for material override UI."""
    room_id: str
    room_name: str
    room_type: str
    area_m2: float
    perimeter_m: float
    assigned_materials: dict[str, AssignedMaterial]  # surface_type -> material


class MaterialOverride(BaseModel):
    """Single material override for a room."""
    room_id: str
    surface_type: str  # floor, wall, ceiling
    new_pose_code: str


class RecalculateRequest(BaseModel):
    """Request to recalculate BOM with material overrides."""
    analysis_id: str
    overrides: list[MaterialOverride]
    floor_height_cm: int = 280


class PoseListResponse(BaseModel):
    """List of poses for dropdown population."""
    poses: list[dict]
    total: int


class ExtendedAnalysisResponse(BaseModel):
    """Extended analysis response with detected rooms for v1.1."""
    project_id: str
    project_name: str
    calculated_at: str
    file_hash: Optional[str]
    
    summary: dict = Field(default_factory=dict)
    blocks: list[BlockResponse]
    bom_summary: list[BOMSummaryItem]
    
    # v1.1: Detected rooms for material override
    detected_rooms: list[DetectedRoomInfo] = []
    analysis_id: str  # For recalculation cache lookup
    
    warnings: list[WarningResponse]
    stats: dict


# =============================================================================
# v1.1: ANALYSIS CACHE (In-Memory)
# =============================================================================

# Cache structure: {analysis_id: {"result": ProcessingResult, "created_at": timestamp, "params": {...}}}
# TTL: 1 hour
ANALYSIS_CACHE: dict[str, dict] = {}
CACHE_TTL_SECONDS = 3600  # 1 hour


def cleanup_expired_cache():
    """Remove expired cache entries."""
    current_time = time.time()
    expired_keys = [
        key for key, value in ANALYSIS_CACHE.items()
        if current_time - value.get("created_at", 0) > CACHE_TTL_SECONDS
    ]
    for key in expired_keys:
        del ANALYSIS_CACHE[key]


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

app = FastAPI(
    title=API.title,
    version=API.version,
    description=API.description,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=API.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# STARTUP / SHUTDOWN EVENTS
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize database and check dependencies on startup."""
    logger.info("🚀 Starting Construction Quantity Takeoff Engine...")
    
    try:
        # Initialize database (creates tables and seeds data)
        init_database()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        # Continue anyway - database might already exist
    
    # Check ODA converter availability
    from geometry_engine import ODAConverter
    oda = ODAConverter()
    if oda.is_available:
        logger.info(f"✅ ODA File Converter found: {oda.converter_path}")
    else:
        logger.warning("⚠️ ODA File Converter not found - DWG support disabled")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("🛑 Shutting down Construction Quantity Takeoff Engine...")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def decimal_to_float(obj: Any) -> Any:
    """Convert Decimal objects to float for JSON serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(i) for i in obj]
    return obj


async def save_upload_file(upload_file: UploadFile) -> Path:
    """Save uploaded file to temp directory and return path."""
    suffix = Path(upload_file.filename).suffix.lower()
    
    # Validate extension
    if suffix not in [".dwg", ".dxf"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {suffix}. Allowed: .dwg, .dxf"
        )
    
    # Create temp file
    temp_file = Path(tempfile.gettempdir()) / f"upload_{uuid.uuid4()}{suffix}"
    
    try:
        with open(temp_file, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
        return temp_file
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save uploaded file: {e}"
        )
    finally:
        upload_file.file.close()


async def build_analysis_response(
    result: ProcessingResult,
    project_name: str,
    floor_height_m: float,
    db: AsyncSession
) -> AnalysisResponse:
    """
    Build complete analysis response from processing result.
    
    Includes recipe breakdowns for all poses.
    """
    project_id = str(uuid.uuid4())
    calculator = QuantityCalculator(floor_height_m=floor_height_m)
    recipe_engine = RecipeEngine(db)
    
    # Convert warnings
    warnings = [
        WarningResponse(
            type=w.warning_type,
            message=w.message,
            location=w.location
        )
        for w in result.warnings
    ]
    
    # Aggregated BOM
    aggregated_bom: dict[str, dict] = {}
    
    # Process blocks
    blocks_response: list[BlockResponse] = []
    total_area = 0.0
    total_rooms = 0
    
    for block in result.blocks:
        # Group rooms by floor (for now, all in one floor)
        floor_rooms: list[RoomResponse] = []
        
        for room in block.rooms:
            # Calculate quantities for room
            room_quantities = calculator.calculate_room_quantities(room)
            
            # Build material list with recipe breakdowns
            materials: list[RoomQuantity] = []
            
            for qty in room_quantities:
                pose_code = qty["pose_code"]
                
                # Get pose description
                pose_result = await db.execute(
                    text("SELECT description FROM ref_poses WHERE code = :code"),
                    {"code": pose_code}
                )
                pose_row = pose_result.fetchone()
                pose_desc = pose_row.description if pose_row else pose_code
                
                # Get recipe breakdown
                recipe_materials = await recipe_engine.calculate_materials(
                    pose_code, 
                    qty["quantity"]
                )
                
                breakdown = [
                    MaterialBreakdown(
                        material=m["material"],
                        quantity=round(m["quantity"], 4),
                        unit=m["unit"],
                        waste_included=m["waste_included"]
                    )
                    for m in recipe_materials
                ]
                
                material_qty = RoomQuantity(
                    pose_code=pose_code,
                    description=pose_desc,
                    category=qty["category"],
                    quantity=round(qty["quantity"], 4),
                    unit=qty["unit"],
                    recipe_breakdown=breakdown
                )
                materials.append(material_qty)
                
                # Aggregate to BOM
                if pose_code not in aggregated_bom:
                    aggregated_bom[pose_code] = {
                        "pose_code": pose_code,
                        "description": pose_desc,
                        "category": qty["category"],
                        "total_quantity": 0,
                        "unit": qty["unit"],
                        "recipes": {}  # material -> total
                    }
                
                aggregated_bom[pose_code]["total_quantity"] += qty["quantity"]
                
                # Aggregate recipes
                for m in recipe_materials:
                    mat_key = m["material"]
                    if mat_key not in aggregated_bom[pose_code]["recipes"]:
                        aggregated_bom[pose_code]["recipes"][mat_key] = {
                            "material": mat_key,
                            "quantity": 0,
                            "unit": m["unit"]
                        }
                    aggregated_bom[pose_code]["recipes"][mat_key]["quantity"] += m["quantity"]
            
            # Calculate wall area
            wall_area = room.wall_length_m * floor_height_m * 2
            
            room_response = RoomResponse(
                name=room.name,
                room_type=room.room_type.value,
                area_m2=room.area_m2,
                perimeter_m=room.perimeter_m,
                wall_area_m2=round(wall_area, 4),
                opening_count=len(room.openings),
                materials=materials
            )
            floor_rooms.append(room_response)
            total_rooms += 1
        
        # Create floor (single floor for now)
        floor = FloorResponse(
            name="Zemin Kat",
            rooms=floor_rooms,
            total_area_m2=sum(r.area_m2 for r in floor_rooms)
        )
        
        block_response = BlockResponse(
            name=block.name,
            floors=[floor],
            total_area_m2=block.total_area_m2,
            room_count=len(block.rooms)
        )
        blocks_response.append(block_response)
        total_area += block.total_area_m2
    
    # Build BOM summary
    bom_summary: list[BOMSummaryItem] = []
    for pose_data in aggregated_bom.values():
        breakdown = [
            MaterialBreakdown(
                material=m["material"],
                quantity=round(m["quantity"], 4),
                unit=m["unit"]
            )
            for m in pose_data["recipes"].values()
        ]
        
        bom_summary.append(BOMSummaryItem(
            pose_code=pose_data["pose_code"],
            description=pose_data["description"],
            category=pose_data["category"],
            total_quantity=round(pose_data["total_quantity"], 4),
            unit=pose_data["unit"],
            recipe_breakdown=breakdown
        ))
    
    # Sort BOM by category then pose code
    bom_summary.sort(key=lambda x: (x.category, x.pose_code))
    
    return AnalysisResponse(
        project_id=project_id,
        project_name=project_name,
        calculated_at=datetime.now(timezone.utc).isoformat(),
        file_hash=result.file_hash,
        summary={
            "total_area_m2": round(total_area, 2),
            "block_count": len(result.blocks),
            "room_count": total_rooms,
            "floor_height_m": floor_height_m
        },
        blocks=blocks_response,
        bom_summary=bom_summary,
        warnings=warnings,
        stats=result.stats
    )


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/", response_model=HealthResponse)
async def root():
    """Root endpoint - returns API health status."""
    from geometry_engine import ODAConverter
    oda = ODAConverter()
    
    return HealthResponse(
        status="healthy",
        version=API.version,
        database="connected",
        oda_converter="available" if oda.is_available else "not_found"
    )


@app.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """Detailed health check with database connection test."""
    from geometry_engine import ODAConverter
    oda = ODAConverter()
    
    # Test database connection
    db_status = "connected"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)[:50]}"
    
    return HealthResponse(
        status="healthy" if db_status == "connected" else "degraded",
        version=API.version,
        database=db_status,
        oda_converter="available" if oda.is_available else "not_found"
    )


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_cad_file(
    file: UploadFile = File(..., description="DWG or DXF file to analyze"),
    drawing_unit: str = Form("cm", description="Drawing unit: mm, cm, or m"),
    project_name: str = Form("Yeni Proje", description="Project name"),
    floor_height_cm: int = Form(280, description="Floor height in cm"),
    db: AsyncSession = Depends(get_db)
):
    """
    Analyze a CAD file and return Bill of Materials.
    
    This endpoint:
    1. Accepts DWG or DXF file upload
    2. Converts DWG to DXF if needed (using ODA File Converter)
    3. Parses geometry and detects rooms
    4. Assigns materials based on room type
    5. Calculates quantities and recipe breakdowns
    6. Returns Excel-ready JSON
    
    **Drawing Units:**
    - `mm`: Millimeters
    - `cm`: Centimeters (default, most common in Turkey)
    - `m`: Meters
    
    **Floor Height:**
    - Used for wall area calculations
    - Default: 280 cm
    """
    logger.info(f"Received file: {file.filename}, unit: {drawing_unit}")
    
    # Validate drawing unit
    if drawing_unit not in ["mm", "cm", "m"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid drawing_unit: {drawing_unit}. Must be mm, cm, or m"
        )
    
    # Save uploaded file
    temp_file = await save_upload_file(file)
    
    try:
        # Process CAD file
        floor_height_m = floor_height_cm / 100.0
        processor = CadProcessor(drawing_unit=drawing_unit)
        
        # CRITICAL: Run CPU-bound CAD processing in thread pool
        # to prevent blocking the async event loop
        result = await run_in_threadpool(processor.process_file, temp_file)
        
        if not result.success and not result.blocks:
            # Total failure
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "CAD file processing failed",
                    "warnings": [
                        {"type": w.warning_type, "message": w.message}
                        for w in result.warnings
                    ]
                }
            )
        
        # Build response
        response = await build_analysis_response(
            result=result,
            project_name=project_name,
            floor_height_m=floor_height_m,
            db=db
        )
        
        # v1.1: Cache result for recalculation
        analysis_id = response.project_id
        ANALYSIS_CACHE[analysis_id] = {
            "result": result,
            "created_at": time.time(),
            "params": {
                "drawing_unit": drawing_unit,
                "floor_height_m": floor_height_m,
                "project_name": project_name
            }
        }
        logger.info(f"Cached analysis {analysis_id} for recalculation")
        
        # Cleanup expired cache entries
        cleanup_expired_cache()
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during analysis")
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}"
        )
    finally:
        # Cleanup temp file
        try:
            temp_file.unlink()
        except:
            pass


@app.get("/poses", response_model=list[PoseResponse])
async def list_poses(
    category: Optional[str] = Query(None, description="Filter by category"),
    db: AsyncSession = Depends(get_db)
):
    """
    List all reference poses (ÇŞB construction codes).
    
    Optionally filter by category (Beton, Duvar, Boya, Kaplama, etc.)
    """
    query = "SELECT code, description, category, unit, default_unit_price FROM ref_poses WHERE is_active = true"
    params = {}
    
    if category:
        query += " AND category = :category"
        params["category"] = category
    
    query += " ORDER BY category, code"
    
    result = await db.execute(text(query), params)
    rows = result.fetchall()
    
    return [
        PoseResponse(
            code=row.code,
            description=row.description,
            category=row.category,
            unit=row.unit,
            default_unit_price=decimal_to_float(row.default_unit_price or {})
        )
        for row in rows
    ]


@app.get("/poses/{pose_code}/recipes")
async def get_pose_recipes(
    pose_code: str,
    quantity: float = Query(1.0, description="Quantity to calculate materials for"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get recipe breakdown for a specific pose.
    
    Calculate raw materials needed for the given quantity.
    """
    recipe_engine = RecipeEngine(db)
    
    # Check if pose exists
    pose_result = await db.execute(
        text("SELECT description, unit FROM ref_poses WHERE code = :code"),
        {"code": pose_code}
    )
    pose = pose_result.fetchone()
    
    if not pose:
        raise HTTPException(status_code=404, detail=f"Pose not found: {pose_code}")
    
    # Calculate materials
    materials = await recipe_engine.calculate_materials(pose_code, quantity)
    
    return {
        "pose_code": pose_code,
        "description": pose.description,
        "quantity": quantity,
        "unit": pose.unit,
        "materials": decimal_to_float(materials)
    }


@app.get("/room-types")
async def list_room_types():
    """
    List all room types with their default material assignments.
    
    Useful for understanding the automatic material assignment logic.
    """
    room_types = []
    
    for room_type in RoomType:
        materials = ROOM_MATERIALS.get(room_type)
        if materials:
            room_types.append({
                "type": room_type.value,
                "name": room_type.name.replace("TYPE_", "").title(),
                "materials": {
                    "floor": materials.floor_pose,
                    "wall": materials.wall_pose,
                    "ceiling": materials.ceiling_pose,
                    "additional": materials.additional_poses
                }
            })
    
    return room_types


# =============================================================================
# v1.1: MATERIAL SELECTION ENDPOINTS
# =============================================================================

@app.get("/poses/categories", response_model=list[str])
async def get_pose_categories():
    """
    Get all available pose categories for filtering.
    
    Returns a list of distinct categories from the RefPose table.
    """
    try:
        categories = get_all_pose_categories()
        return categories
    except Exception as e:
        logger.error(f"Error fetching categories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/poses/by-surface/{surface_type}", response_model=PoseListResponse)
async def get_poses_by_surface(surface_type: str):
    """
    Get poses suitable for a surface type.
    
    Args:
        surface_type: 'floor', 'wall', or 'ceiling'
    
    Returns:
        List of poses with their details
    """
    valid_types = ["floor", "wall", "ceiling"]
    if surface_type.lower() not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid surface type: {surface_type}. Must be one of: {valid_types}"
        )
    
    try:
        poses = get_poses_for_surface_type(surface_type)
        return PoseListResponse(poses=poses, total=len(poses))
    except Exception as e:
        logger.error(f"Error fetching poses for surface {surface_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/poses/all", response_model=PoseListResponse)
async def get_all_poses_endpoint():
    """
    Get all active poses for dropdown population.
    
    Returns all poses in simple format for UI dropdowns.
    """
    try:
        poses = get_all_poses_simple()
        return PoseListResponse(poses=poses, total=len(poses))
    except Exception as e:
        logger.error(f"Error fetching all poses: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/recalculate")
async def recalculate_bom(
    request: RecalculateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Recalculate BOM with material overrides.
    
    This endpoint:
    1. Retrieves cached analysis result
    2. Applies material overrides
    3. Recalculates quantities with new materials
    4. Returns updated BOM
    
    **Note:** Analysis must have been performed recently (cache TTL: 1 hour)
    """
    # Cleanup expired cache entries
    cleanup_expired_cache()
    
    # Find cached analysis
    cache_entry = ANALYSIS_CACHE.get(request.analysis_id)
    if not cache_entry:
        raise HTTPException(
            status_code=404,
            detail="Analysis not found or expired. Please re-analyze the file."
        )
    
    cached_result: ProcessingResult = cache_entry["result"]
    cached_params = cache_entry["params"]
    
    floor_height_m = request.floor_height_cm / 100.0
    calculator = QuantityCalculator(floor_height_m=floor_height_m)
    
    # Build override map: room_id + surface_type -> pose_code
    override_map = {
        f"{o.room_id}_{o.surface_type}": o.new_pose_code
        for o in request.overrides
    }
    
    # Recalculate with overrides
    aggregated_bom: dict[str, dict] = {}
    
    for block in cached_result.blocks:
        for room in block.rooms:
            room_id = f"room_{hash(room.name) % 10000}"
            
            # Get base quantities
            room_quantities = calculator.calculate_room_quantities(room)
            
            for qty in room_quantities:
                original_pose = qty["pose_code"]
                surface_type = qty.get("surface_type", "unknown")
                
                # Check if override exists for this room + surface
                override_key = f"{room_id}_{surface_type}"
                pose_code = override_map.get(override_key, original_pose)
                
                # Fetch pose details
                pose_info = get_pose_by_code(pose_code)
                if not pose_info:
                    pose_info = {"code": pose_code, "description": pose_code, "unit": qty["unit"], "category": "Unknown"}
                
                # Aggregate
                if pose_code not in aggregated_bom:
                    aggregated_bom[pose_code] = {
                        "pose_code": pose_code,
                        "description": pose_info["description"],
                        "category": pose_info.get("category", "Unknown"),
                        "unit": qty["unit"],
                        "total_quantity": 0
                    }
                aggregated_bom[pose_code]["total_quantity"] += qty["quantity"]
    
    # Build response
    bom_list = [
        {
            "pose_code": item["pose_code"],
            "description": item["description"],
            "category": item["category"] if item["category"] != "Unknown" else "FLOOR",
            "total_quantity": round(item["total_quantity"], 4),
            "unit": item["unit"],
            "recipe_breakdown": []  # Empty for recalculated results
        }
        for item in sorted(aggregated_bom.values(), key=lambda x: (x["category"], x["pose_code"]))
    ]
    
    return {
        "status": "success",
        "analysis_id": request.analysis_id,
        "overrides_applied": len(request.overrides),
        "bom_summary": bom_list,
        "recalculated_at": datetime.now(timezone.utc).isoformat()
    }


# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

@app.post("/init-db")
async def initialize_database():
    """
    Initialize/reset the database.
    
    WARNING: This will recreate all tables and reseed reference data.
    Use only for development/testing.
    """
    try:
        init_database()
        return {"status": "success", "message": "Database initialized successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database initialization failed: {e}"
        )


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
