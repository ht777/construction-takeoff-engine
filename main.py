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
    Form, Depends, BackgroundTasks, Query, Body
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, delete, update

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
    DetectedBlock, DetectedRoom, DetectedOpening, ProcessingWarning
)
from visualization import generate_floor_plan_image


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


class BulkCopyRequest(BaseModel):
    """Request model for bulk copying opening configurations."""
    source_block: str
    source_room: str
    target_block: str
    target_rooms: list[str]


class UpdateRoomRequest(BaseModel):
    """Request model for manual room updates (v1.2)."""
    room_type: Optional[str] = None
    openings: Optional[list[dict]] = None


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


class OpeningResponse(BaseModel):
    """Detailed opening info (v1.2)."""
    width_m: float
    height_m: float
    opening_type: str
    location: Optional[tuple[float, float]] = None


class RoomResponse(BaseModel):
    """Room data in response."""
    name: str
    room_type: str
    area_m2: float
    perimeter_m: float
    wall_area_m2: float
    opening_count: int
    openings: list[OpeningResponse] = []  # v1.2
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
    
    # v1.1: Floor plan visualization
    floor_plan_image: Optional[str] = None  # Base64 encoded PNG
    
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
                
                pose_result = await db.execute(
                    text("SELECT description FROM ref_poses WHERE code = :code"),
                    {"code": pose_code}
                )
                pose_row = pose_result.first()
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
                openings=[
                    OpeningResponse(
                        width_m=o.width_m,
                        height_m=o.height_m,
                        opening_type=o.opening_type,
                        location=o.location
                    ) for o in room.openings
                ],
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
    
    # v1.1: Generate floor plan visualization
    floor_plan_b64 = None
    try:
        floor_plan_b64 = await run_in_threadpool(
            generate_floor_plan_image,
            result.blocks,
            project_name
        )
        logger.info(f"Generated floor plan image for {project_name}")
    except Exception as e:
        logger.warning(f"Failed to generate floor plan image: {e}")
    
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
        floor_plan_image=floor_plan_b64,
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
        
        # v1.1: Save project to database for history
        logger.info(f"💾 STARTING DATABASE SAVE for project: {project_name}")
        try:
            # Serializing detected geometry for Inspector (v1.2)
            detected_geometry = {}
            for block in result.blocks:
                detected_geometry[block.name] = {}
                for room in block.rooms:
                    detected_geometry[block.name][room.name] = {
                        "room_type": room.room_type.value,
                        "area_m2": room.area_m2,
                        "perimeter_m": room.perimeter_m,
                        "wall_length_m": room.wall_length_m,
                        "openings": [
                            {"width_m": o.width_m, "height_m": o.height_m, "type": o.opening_type}
                            for o in room.openings
                        ]
                    }

            # Create Project record
            project_record = Project(
                id=uuid.UUID(analysis_id),
                user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),  # Default user for MVP
                name=project_name,
                description=f"Analiz: {project_name}",
                meta_data={
                    "project_stats": {
                        "total_area_m2": float(response.summary.get("total_area_m2", 0)),
                        "block_count": int(response.summary.get("block_count", 0)),
                        "room_count": int(response.summary.get("room_count", 0)),
                        "floor_height_m": float(floor_height_m)
                    },
                    "detected_geometry": detected_geometry,
                    "floor_plan_image": response.floor_plan_image  # v1.2: Store image for history (via response, not local var)
                },
                original_filename=file.filename,
                file_hash=result.file_hash,
                status="completed",
                warnings=[{"type": str(w.warning_type), "message": str(w.message)} for w in result.warnings],
                processed_at=datetime.now(timezone.utc)
            )
            db.add(project_record)
            
            # Create Quantity records for each room/material
            calculator = QuantityCalculator(floor_height_m=floor_height_m)
            for block in result.blocks:
                for room in block.rooms:
                    materials = calculator.calculate_room_quantities(room)
                    
                    for mat in materials:
                        qty_record = Quantity(
                            id=uuid.uuid4(),
                            project_id=uuid.UUID(analysis_id),
                            block_name=block.name,
                            floor_name="Zemin Kat",  # Default for MVP
                            room_name=room.name,
                            room_type=room.room_type.value,
                            area_m2=Decimal(str(room.area_m2)),
                            perimeter_m=Decimal(str(room.perimeter_m)),
                            wall_area_m2=Decimal(str(room.wall_length_m * floor_height_m)),
                            opening_count=len(room.openings),
                            pose_code=mat["pose_code"],
                            pose_category=mat["category"],
                            quantity=Decimal(str(mat["quantity"])),
                            unit=mat["unit"]
                        )
                        db.add(qty_record)
            
            logger.info("📡 Committing to database...")
            await db.commit()
            logger.info(f"✅ SUCCESSFULLY SAVED project {analysis_id}")
        except Exception as save_error:
            logger.error(f"❌ DATABASE SAVE ERROR: {str(save_error)}")
            import traceback
            logger.error(traceback.format_exc())
            # Don't fail the request if save fails - analysis result is still valid
            await db.rollback()
        
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


@app.post("/projects/{project_id}/rooms/update")
async def update_room_details(
    project_id: uuid.UUID,
    block_name: str = Body(..., embed=True),
    room_name: str = Body(..., embed=True),
    update_data: UpdateRoomRequest = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Update room details (Type, Openings) and recalculate quantities.
    
    Used by "The Inspector" (v1.2) for manual corrections.
    """
    # 1. Fetch Project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Get Geometry from Metadata
    meta_data = dict(project.meta_data) # Copy dict
    detected_geometry = meta_data.get("detected_geometry", {})
    
    if block_name not in detected_geometry or room_name not in detected_geometry[block_name]:
        raise HTTPException(status_code=404, detail="Room geometry not found in metadata")

    room_data = detected_geometry[block_name][room_name]

    # 3. Update Geometry
    if update_data.room_type:
        room_data["room_type"] = update_data.room_type
    
    if update_data.openings is not None:
        room_data["openings"] = update_data.openings

    # Recalculate wall length based on new openings
    try:
        openings = [
            DetectedOpening(
                width_m=float(o["width_m"]), 
                height_m=float(o.get("height_m", 2.1)), 
                location=(0,0), 
                opening_type=o["type"]
            )
            for o in room_data["openings"]
        ]
        total_opening_width = sum(o.width_m for o in openings)
        perimeter = float(room_data["perimeter_m"])
        room_data["wall_length_m"] = max(0.0, perimeter - total_opening_width)
    except Exception as e:
        logger.error(f"Error recalculating wall length: {e}")
        # Continue with old wall length if fails
        openings = []

    # Save updated geometry back to metadata
    detected_geometry[block_name][room_name] = room_data
    meta_data["detected_geometry"] = detected_geometry
    meta_data["has_manual_overrides"] = True
    
    # Force update metadata
    # SQLAlchemy requires explicit reassignment or flag modification for JSONB
    project.meta_data = meta_data 
    
    # 4. Re-calculate Quantities
    # Create Dummy DetectedRoom
    from geometry_engine import DetectedRoom, RoomType
    
    try:
        dummy_room = DetectedRoom(
            name=room_name,
            room_type=RoomType(room_data["room_type"]),
            polygon=None, #/ Calculator doesn't use geometry directly
            area_m2=float(room_data["area_m2"]),
            perimeter_m=float(room_data["perimeter_m"]),
            wall_length_m=float(room_data["wall_length_m"]),
            openings=openings
        )
        
        # Calculate
        floor_height = meta_data["project_stats"].get("floor_height_m", 2.8)
        calculator = QuantityCalculator(floor_height_m=floor_height)
        new_quantities = calculator.calculate_room_quantities(dummy_room)
        
        # 5. Update Database Records
        # Delete old quantities for this room
        await db.execute(
            delete(Quantity).where(
                Quantity.project_id == project_id,
                Quantity.block_name == block_name,
                Quantity.room_name == room_name
            )
        )
        
        # Insert new quantities
        for mat in new_quantities:
            qty_record = Quantity(
                id=uuid.uuid4(),
                project_id=project_id,
                block_name=block_name,
                floor_name="Zemin Kat",
                room_name=room_name,
                room_type=dummy_room.room_type.value,
                area_m2=Decimal(str(dummy_room.area_m2)),
                perimeter_m=Decimal(str(dummy_room.perimeter_m)),
                wall_area_m2=Decimal(str(dummy_room.wall_length_m * floor_height)),
                opening_count=len(dummy_room.openings),
                pose_code=mat["pose_code"],
                pose_category=mat["category"],
                quantity=Decimal(str(mat["quantity"])),
                unit=mat["unit"],
                is_manual_override=True 
            )
            db.add(qty_record)
            
        await db.commit()
        return {"status": "success", "message": "Room updated successfully"}
        
    except Exception as e:
        logger.exception(f"Failed to update room {room_name}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@app.delete("/projects/{project_id}/rooms")
async def delete_room(
    project_id: uuid.UUID,
    block_name: str = Query(..., description="Block name"),
    room_name: str = Query(..., description="Room name"),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a room and its quantities from the project.
    """
    try:
        # 1. Fetch Project
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # 2. Update Metadata (Remove from geometry)
        meta_data = dict(project.meta_data)
        detected_geometry = meta_data.get("detected_geometry", {})
        
        if block_name in detected_geometry and room_name in detected_geometry[block_name]:
            del detected_geometry[block_name][room_name]
            meta_data["detected_geometry"] = detected_geometry
            meta_data["has_manual_overrides"] = True
            project.meta_data = meta_data

        # 3. Delete Quantities
        await db.execute(
            delete(Quantity).where(
                Quantity.project_id == project_id,
                Quantity.block_name == block_name,
                Quantity.room_name == room_name
            )
        )
        
        await db.commit()
        return {"status": "success", "message": "Room deleted successfully"}
        
    except Exception as e:
        logger.exception(f"Failed to delete room {room_name}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


@app.post("/projects/{project_id}/rooms/bulk-copy")
async def bulk_copy_openings(
    project_id: uuid.UUID,
    copy_data: BulkCopyRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Copy openings configuration from one room to multiple other rooms.
    
    Used for bulk distributing window/door settings in "The Inspector".
    """
    # 1. Fetch Project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Get Source Openings
    meta_data = dict(project.meta_data)
    detected_geometry = meta_data.get("detected_geometry", {})
    
    source_room_data = detected_geometry.get(copy_data.source_block, {}).get(copy_data.source_room)
    if not source_room_data:
        raise HTTPException(status_code=404, detail="Source room data not found")
    
    source_openings = source_room_data.get("openings", [])
    
    # 3. Apply to Target Rooms
    updated_rooms_count = 0
    from geometry_engine import DetectedRoom, RoomType, QuantityCalculator, DetectedOpening
    floor_height = meta_data["project_stats"].get("floor_height_m", 2.8)
    calculator = QuantityCalculator(floor_height_m=floor_height)
    
    for room_name in copy_data.target_rooms:
        if room_name not in detected_geometry.get(copy_data.target_block, {}):
            continue
            
        target_room_data = detected_geometry[copy_data.target_block][room_name]
        target_room_data["openings"] = source_openings # Clone openings
        
        # Recalculate wall length
        try:
            openings_objs = [
                DetectedOpening(
                    width_m=float(o["width_m"]), 
                    height_m=float(o.get("height_m", 2.1)), 
                    location=(0,0), 
                    opening_type=o["type"]
                )
                for o in source_openings
            ]
            total_opening_width = sum(o.width_m for o in openings_objs)
            perimeter = float(target_room_data["perimeter_m"])
            target_room_data["wall_length_m"] = max(0.0, perimeter - total_opening_width)
            
            # Re-calculate quantities
            dummy_room = DetectedRoom(
                name=room_name,
                room_type=RoomType(target_room_data["room_type"]),
                polygon=None,
                area_m2=float(target_room_data["area_m2"]),
                perimeter_m=float(target_room_data["perimeter_m"]),
                wall_length_m=float(target_room_data["wall_length_m"]),
                openings=openings_objs
            )
            new_quantities = calculator.calculate_room_quantities(dummy_room)
            
            # Delete and Re-insert
            await db.execute(
                delete(Quantity).where(
                    Quantity.project_id == project_id,
                    Quantity.block_name == copy_data.target_block,
                    Quantity.room_name == room_name
                )
            )
            
            for mat in new_quantities:
                qty_record = Quantity(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    block_name=copy_data.target_block,
                    floor_name="Zemin Kat",
                    room_name=room_name,
                    room_type=dummy_room.room_type.value,
                    area_m2=Decimal(str(dummy_room.area_m2)),
                    perimeter_m=Decimal(str(dummy_room.perimeter_m)),
                    wall_area_m2=Decimal(str(dummy_room.wall_length_m * floor_height)),
                    opening_count=len(dummy_room.openings),
                    pose_code=mat["pose_code"],
                    pose_category=mat["category"],
                    quantity=Decimal(str(mat["quantity"])),
                    unit=mat["unit"],
                    is_manual_override=True 
                )
                db.add(qty_record)
                
            updated_rooms_count += 1
        except Exception as e:
            logger.error(f"Failed to copy openings to {room_name}: {e}")

    # 4. Finalize
    project.meta_data = meta_data
    await db.commit()
    
    return {
        "status": "success", 
        "message": f"Copied openings to {updated_rooms_count} rooms.",
        "updated_rooms": updated_rooms_count
    }


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
# v1.1 PROJECT HISTORY ENDPOINTS
# =============================================================================

class ProjectListItem(BaseModel):
    """Project summary for list view."""
    id: str
    name: str
    created_at: str
    status: str
    total_area_m2: Optional[float] = 0
    room_count: Optional[int] = 0
    block_count: Optional[int] = 0


class ProjectListResponse(BaseModel):
    """Projects list response with pagination."""
    projects: list[ProjectListItem]
    total: int
    limit: int
    offset: int


@app.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db)
):
    """
    List all saved projects with pagination.
    
    Returns project summaries ordered by date (newest first).
    """
    try:
        # Build query
        query = """
            SELECT id, name, created_at, status, meta_data
            FROM projects
            WHERE status = 'completed'
        """
        params = {"limit": limit, "offset": offset}
        
        if search:
            query += " AND name ILIKE :search"
            params["search"] = f"%{search}%"
        
        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        
        result = await db.execute(text(query), params)
        rows = result.all()
        logger.info(f"🔍 Found {len(rows)} projects in list query")
        
        # Count total
        count_query = "SELECT COUNT(*) FROM projects WHERE status = 'completed'"
        if search:
            count_query += " AND name ILIKE :search"
        count_result = await db.execute(text(count_query), {"search": f"%{search}%"} if search else {})
        total = count_result.scalar() or 0
        logger.info(f"🔍 Total projects count: {total}")
        
        projects = []
        for row in rows:
            meta = row.meta_data or {}
            stats = meta.get("project_stats", {})
            projects.append(ProjectListItem(
                id=str(row.id),
                name=row.name,
                created_at=row.created_at.isoformat() if row.created_at else "",
                status=row.status or "unknown",
                total_area_m2=stats.get("total_area_m2", 0),
                room_count=stats.get("room_count", 0),
                block_count=stats.get("block_count", 0)
            ))
        
        return ProjectListResponse(
            projects=projects,
            total=total or 0,
            limit=limit,
            offset=offset
        )
    except Exception as e:
        logger.error(f"Error listing projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Load a specific project with all quantities.
    
    Reconstructs the full AnalysisResponse format for frontend compatibility.
    """
    try:
        # Get project
        project_result = await db.execute(
            text("SELECT * FROM projects WHERE id = :id"),
            {"id": project_id}
        )
        project = project_result.first()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get quantities
        qty_result = await db.execute(
            text("""
                SELECT q.*, rp.description as pose_description
                FROM quantities q
                LEFT JOIN ref_poses rp ON q.pose_code = rp.code
                WHERE q.project_id = :project_id
                ORDER BY q.block_name, q.floor_name, q.room_name
            """),
            {"project_id": project_id}
        )
        quantities = qty_result.all()
        
        # Reconstruct blocks structure
        blocks_dict = {}
        for qty in quantities:
            block_name = qty.block_name
            floor_name = qty.floor_name
            room_name = qty.room_name
            
            if block_name not in blocks_dict:
                blocks_dict[block_name] = {"name": block_name, "floors": {}, "total_area_m2": 0}
            
            if floor_name not in blocks_dict[block_name]["floors"]:
                blocks_dict[block_name]["floors"][floor_name] = {"name": floor_name, "rooms": {}}
            
            # Retrieve geometric data from meta_data if available
            meta = project.meta_data or {}
            geom_data = meta.get("detected_geometry", {}).get(block_name, {}).get(room_name, {})
            
            if room_name not in blocks_dict[block_name]["floors"][floor_name]["rooms"]:
                blocks_dict[block_name]["floors"][floor_name]["rooms"][room_name] = {
                    "name": room_name,
                    "room_type": geom_data.get("room_type") or qty.room_type or "unknown",
                    "area_m2": float(qty.area_m2) if qty.area_m2 else geom_data.get("area_m2", 0),
                    "perimeter_m": float(qty.perimeter_m) if qty.perimeter_m else geom_data.get("perimeter_m", 0),
                    "wall_area_m2": float(qty.wall_area_m2) if qty.wall_area_m2 else geom_data.get("wall_area_m2", 0),
                    "opening_count": qty.opening_count or len(geom_data.get("openings", [])),
                    "openings": geom_data.get("openings", []), # v1.2: Restore openings for Inspector
                    "materials": []
                }
                blocks_dict[block_name]["total_area_m2"] += float(qty.area_m2) if qty.area_m2 else geom_data.get("area_m2", 0)
            
            # Add material to room
            blocks_dict[block_name]["floors"][floor_name]["rooms"][room_name]["materials"].append({
                "pose_code": qty.pose_code,
                "category": qty.pose_category,
                "quantity": float(qty.quantity) if qty.quantity else 0,
                "unit": qty.unit,
                "description": qty.pose_description or qty.pose_code
            })
        
        # Convert to list structure
        blocks_response = []
        for block_name, block_data in blocks_dict.items():
            floors_list = []
            for floor_name, floor_data in block_data["floors"].items():
                rooms_list = list(floor_data["rooms"].values())
                floors_list.append({
                    "name": floor_name,
                    "rooms": rooms_list,
                    "total_area_m2": sum(r["area_m2"] for r in rooms_list)
                })
            blocks_response.append({
                "name": block_name,
                "floors": floors_list,
                "total_area_m2": block_data["total_area_m2"]
            })
        
        # Aggregate BOM
        bom_dict = {}
        for qty in quantities:
            code = qty.pose_code
            if code not in bom_dict:
                bom_dict[code] = {
                    "pose_code": code,
                    "description": qty.pose_description or code,
                    "category": qty.pose_category,
                    "unit": qty.unit,
                    "total_quantity": 0,
                    "recipe_breakdown": qty.recipe_breakdown or []
                }
            bom_dict[code]["total_quantity"] += float(qty.quantity) if qty.quantity else 0
        
        bom_summary = sorted(bom_dict.values(), key=lambda x: (x["category"], x["pose_code"]))
        
        # Get meta stats
        meta = project.meta_data or {}
        stats = meta.get("project_stats", {})
        
        return {
            "status": "success",
            "project_id": str(project.id),
            "project_name": project.name,
            "summary": {
                "total_area_m2": meta.get("project_stats", {}).get("total_area_m2", 0),
                "block_count": meta.get("project_stats", {}).get("block_count", 0),
                "room_count": meta.get("project_stats", {}).get("room_count", 0),
                "floor_height_m": meta.get("project_stats", {}).get("floor_height_m", 2.8)
            },
            "blocks": blocks_response,
            "bom_summary": bom_summary,
            "floor_plan_image": meta.get("floor_plan_image"),  # v1.2: Retrieve stored image
            "warnings": project.warnings or []
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a project and all associated quantities.
    """
    try:
        # Check if project exists
        check_result = await db.execute(
            text("SELECT id FROM projects WHERE id = :id"),
            {"id": project_id}
        )
        if not check_result.fetchone():
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Delete project (quantities will cascade)
        await db.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": project_id}
        )
        await db.commit()
        
        logger.info(f"Deleted project {project_id}")
        return {"status": "success", "message": "Project deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting project {project_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


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
        port=8088,
        reload=True,
        log_level="info"
    )
