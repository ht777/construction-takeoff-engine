"""
Geometry Engine for Construction Quantity Takeoff
==================================================

Core CAD processing module with:
- ODA File Converter wrapper (DWG -> DXF)
- DBSCAN clustering for multi-block detection
- Gap healing with configurable thresholds
- Point-in-polygon text matching
- Intelligent material assignment

2026 Architecture Notes:
- All geometry flattened to 2D (Z-axis ignored as per spec)
- Unit normalization to meters
- Graceful degradation with warning collection

Author: AI Solutions Architect
Version: 1.0.0 (MVP)
"""

import os
import re
import tempfile
import subprocess
import hashlib
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum

import ezdxf
from ezdxf.entities import DXFEntity, LWPolyline, Polyline, Line, Circle, Arc, Text, MText
from ezdxf.math import Vec2, Vec3

import numpy as np
from shapely.geometry import (
    Point, LineString, Polygon, MultiPolygon,
    MultiLineString, GeometryCollection, box
)
from shapely.ops import polygonize, unary_union, linemerge
from shapely.validation import make_valid

from sklearn.cluster import DBSCAN

from config import (
    GEOMETRY, ODA_CONVERTER, RoomType,
    ROOM_KEYWORDS, ROOM_MATERIALS, TURKISH_CHAR_MAP,
    MaterialAssignment
)


# Configure module logger
logger = logging.getLogger("construction_engine.geometry")


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ProcessingWarning:
    """Warning generated during CAD processing."""
    warning_type: str  # "unclosed_polygon", "unknown_room", "conversion_error"
    message: str
    location: Optional[tuple[float, float]] = None  # X, Y coordinates
    entity_handle: Optional[str] = None


@dataclass
class DetectedOpening:
    """Door or window opening detected in a wall."""
    width_m: float
    location: tuple[float, float]
    opening_type: str  # "door" or "window" (heuristic based on width)


@dataclass
class DetectedRoom:
    """A room detected from the CAD file."""
    name: str
    room_type: RoomType
    polygon: Polygon
    area_m2: float
    perimeter_m: float
    wall_length_m: float  # Perimeter minus openings
    openings: list[DetectedOpening] = field(default_factory=list)
    centroid: tuple[float, float] = field(default_factory=lambda: (0.0, 0.0))
    
    def __post_init__(self):
        if self.polygon and self.polygon.is_valid:
            self.centroid = (self.polygon.centroid.x, self.polygon.centroid.y)


@dataclass
class DetectedBlock:
    """A building block/island detected via clustering."""
    name: str
    rooms: list[DetectedRoom] = field(default_factory=list)
    total_area_m2: float = 0.0
    bounding_box: Optional[tuple[float, float, float, float]] = None  # minx, miny, maxx, maxy


@dataclass
class ProcessingResult:
    """Complete result from CAD processing."""
    success: bool
    blocks: list[DetectedBlock] = field(default_factory=list)
    warnings: list[ProcessingWarning] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    file_hash: Optional[str] = None


# =============================================================================
# ODA FILE CONVERTER WRAPPER
# =============================================================================

class ODAConverter:
    """
    Wrapper for ODA File Converter CLI.
    
    Converts DWG files to DXF format for parsing with ezdxf.
    Implements automatic path detection with fallbacks.
    """
    
    def __init__(self):
        self.converter_path = ODA_CONVERTER.get_converter_path()
        self.output_version = ODA_CONVERTER.output_version
        self.timeout = ODA_CONVERTER.timeout_seconds
    
    @property
    def is_available(self) -> bool:
        """Check if ODA File Converter is available."""
        return self.converter_path is not None
    
    def convert_dwg_to_dxf(self, dwg_path: Path) -> tuple[Optional[Path], Optional[str]]:
        """
        Convert DWG file to DXF using ODA File Converter.
        
        Args:
            dwg_path: Path to input DWG file
            
        Returns:
            Tuple of (dxf_path, error_message)
            If successful, error_message is None
            If failed, dxf_path is None
        """
        if not self.is_available:
            return None, "ODA File Converter not found. Please install from https://www.opendesign.com/guestfiles/oda_file_converter"
        
        if not dwg_path.exists():
            return None, f"Input file not found: {dwg_path}"
        
        # Create temp directory for conversion
        temp_dir = Path(tempfile.mkdtemp(prefix="cad_convert_"))
        input_dir = temp_dir / "input"
        output_dir = temp_dir / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        
        try:
            # Copy input file to temp input directory
            import shutil
            temp_input = input_dir / dwg_path.name
            shutil.copy2(dwg_path, temp_input)
            
            # Build ODA command
            # ODAFileConverter <Input Folder> <Output Folder> <Output_version> <Output_type> <Recurse> <Audit>
            cmd = [
                str(self.converter_path),
                str(input_dir),
                str(output_dir),
                self.output_version,  # ACAD2018
                "DXF",                # Output format
                "0",                  # No recurse
                "1",                  # Audit and fix
            ]
            
            logger.info(f"Running ODA conversion: {' '.join(cmd)}")
            
            # Execute conversion
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(temp_dir),
            )
            
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown conversion error"
                logger.error(f"ODA conversion failed: {error_msg}")
                return None, f"DWG conversion failed: {error_msg}"
            
            # Find output DXF file
            dxf_files = list(output_dir.glob("*.dxf"))
            if not dxf_files:
                return None, "No DXF file generated after conversion"
            
            output_dxf = dxf_files[0]
            
            # Move to a persistent temp location
            final_dxf = Path(tempfile.gettempdir()) / f"converted_{dwg_path.stem}.dxf"
            shutil.move(str(output_dxf), str(final_dxf))
            
            logger.info(f"DWG converted successfully: {final_dxf}")
            return final_dxf, None
            
        except subprocess.TimeoutExpired:
            return None, f"DWG conversion timed out after {self.timeout} seconds"
        except Exception as e:
            logger.exception("DWG conversion error")
            return None, f"DWG conversion error: {str(e)}"
        finally:
            # Cleanup temp directories
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass


# =============================================================================
# UNIT NORMALIZER
# =============================================================================

class UnitNormalizer:
    """
    Converts CAD units to meters for consistent calculations.
    
    Supports: mm, cm, m, inch, feet
    Default: cm (most common in Turkish architectural drawings)
    """
    
    def __init__(self, drawing_unit: str = "cm"):
        self.drawing_unit = drawing_unit.lower()
        self.factor = GEOMETRY.UNIT_FACTORS.get(self.drawing_unit, 0.01)
        logger.info(f"Unit normalizer initialized: {drawing_unit} -> factor {self.factor}")
    
    def to_meters(self, value: float) -> float:
        """Convert a length value to meters."""
        return value * self.factor
    
    def to_square_meters(self, value: float) -> float:
        """Convert an area value to square meters."""
        return value * (self.factor ** 2)
    
    def normalize_point(self, x: float, y: float) -> tuple[float, float]:
        """Normalize a 2D point to meters."""
        return (x * self.factor, y * self.factor)
    
    def normalize_polygon(self, polygon: Polygon) -> Polygon:
        """Scale a polygon to meters."""
        if polygon.is_empty:
            return polygon
        
        coords = [(x * self.factor, y * self.factor) for x, y in polygon.exterior.coords]
        holes = [
            [(x * self.factor, y * self.factor) for x, y in hole.coords]
            for hole in polygon.interiors
        ]
        return Polygon(coords, holes)


# =============================================================================
# TEXT NORMALIZER
# =============================================================================

class TextNormalizer:
    """
    Normalizes CAD text for room identification.
    
    - Turkish character normalization (İ->I, Ş->S, etc.)
    - Uppercase conversion
    - Whitespace normalization
    - Special character removal
    """
    
    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for matching."""
        if not text:
            return ""
        
        # Turkish character normalization
        normalized = text.translate(TURKISH_CHAR_MAP)
        
        # Uppercase
        normalized = normalized.upper()
        
        # Remove special characters except spaces and dots
        normalized = re.sub(r'[^A-Z0-9\s\.]', '', normalized)
        
        # Normalize whitespace
        normalized = ' '.join(normalized.split())
        
        return normalized.strip()


# =============================================================================
# MATERIAL MAPPER
# =============================================================================

class MaterialMapper:
    """
    Intelligent room type detection and material assignment.
    
    Maps room names (from CAD text) to room types using keyword matching.
    Assigns default materials based on room type.
    """
    
    def __init__(self):
        self.text_normalizer = TextNormalizer()
        self._build_keyword_index()
    
    def _build_keyword_index(self):
        """Build reverse index for fast keyword lookup."""
        self.keyword_to_type: dict[str, RoomType] = {}
        
        for room_type, keywords in ROOM_KEYWORDS.items():
            for keyword in keywords:
                normalized = self.text_normalizer.normalize(keyword)
                self.keyword_to_type[normalized] = room_type
    
    def detect_room_type(self, room_name: str) -> RoomType:
        """
        Detect room type from room name.
        
        Uses keyword matching with priority:
        1. Exact match on full name
        2. Partial match (keyword in name)
        3. Fallback to TYPE_UNKNOWN
        
        Args:
            room_name: Original room name from CAD
            
        Returns:
            Detected RoomType
        """
        if not room_name:
            return RoomType.TYPE_UNKNOWN
        
        normalized = self.text_normalizer.normalize(room_name)
        
        # Priority 1: Check if normalized name starts with a keyword
        for keyword, room_type in self.keyword_to_type.items():
            if normalized.startswith(keyword):
                logger.debug(f"Room '{room_name}' matched keyword '{keyword}' -> {room_type}")
                return room_type
        
        # Priority 2: Check if any keyword is contained in the name
        for keyword, room_type in self.keyword_to_type.items():
            if keyword in normalized:
                logger.debug(f"Room '{room_name}' contains keyword '{keyword}' -> {room_type}")
                return room_type
        
        # Fallback
        logger.warning(f"Unknown room type for '{room_name}', defaulting to TYPE_UNKNOWN")
        return RoomType.TYPE_UNKNOWN
    
    def get_materials(self, room_type: RoomType) -> MaterialAssignment:
        """Get default material assignment for a room type."""
        return ROOM_MATERIALS.get(room_type, ROOM_MATERIALS[RoomType.TYPE_UNKNOWN])
    
    def process_room(self, room_name: str) -> tuple[RoomType, MaterialAssignment]:
        """
        Complete room processing: detect type and assign materials.
        
        Args:
            room_name: Room name from CAD file
            
        Returns:
            Tuple of (RoomType, MaterialAssignment)
        """
        room_type = self.detect_room_type(room_name)
        materials = self.get_materials(room_type)
        return room_type, materials


# =============================================================================
# GEOMETRY HEALER
# =============================================================================

class GeometryHealer:
    """
    Heals common CAD geometry issues.
    
    Features:
    - Gap closing for small gaps (<15cm)
    - Opening detection for medium gaps (70-250cm)
    - Polygon validation and repair
    - Multi-polygon dissolution
    """
    
    def __init__(self, unit_normalizer: UnitNormalizer):
        self.normalizer = unit_normalizer
        self.gap_threshold = GEOMETRY.GAP_HEAL_MAX  # 15cm in meters
        self.opening_min = GEOMETRY.OPENING_MIN      # 70cm
        self.opening_max = GEOMETRY.OPENING_MAX      # 250cm
    
    def heal_polyline(
        self,
        coords: list[tuple[float, float]],
        is_closed: bool
    ) -> tuple[Optional[Polygon], list[DetectedOpening], Optional[ProcessingWarning]]:
        """
        Heal a polyline and convert to polygon.
        
        Logic:
        1. If closed -> create polygon directly
        2. If gap < 15cm -> close and treat as drawing error
        3. If gap 70-250cm -> treat as door/window opening
        4. If gap > 250cm -> cannot heal, return warning
        
        Args:
            coords: List of (x, y) tuples in METERS
            is_closed: Whether the polyline was marked as closed in CAD
            
        Returns:
            Tuple of (polygon, openings, warning)
        """
        if len(coords) < 3:
            return None, [], ProcessingWarning(
                warning_type="insufficient_points",
                message=f"Polyline has only {len(coords)} points, need at least 3"
            )
        
        openings: list[DetectedOpening] = []
        
        # Check if already closed or needs closing
        start = coords[0]
        end = coords[-1]
        gap_distance = ((end[0] - start[0])**2 + (end[1] - start[1])**2) ** 0.5
        
        if is_closed or gap_distance < 0.001:
            # Already closed
            try:
                polygon = Polygon(coords)
                if not polygon.is_valid:
                    polygon = make_valid(polygon)
                    if isinstance(polygon, GeometryCollection):
                        # Extract largest polygon from collection
                        polygons = [g for g in polygon.geoms if isinstance(g, Polygon)]
                        if polygons:
                            polygon = max(polygons, key=lambda p: p.area)
                        else:
                            return None, [], ProcessingWarning(
                                warning_type="invalid_geometry",
                                message="Could not create valid polygon"
                            )
                return polygon, [], None
            except Exception as e:
                return None, [], ProcessingWarning(
                    warning_type="polygon_creation_error",
                    message=str(e)
                )
        
        # Gap analysis
        if gap_distance < self.gap_threshold:
            # Small gap (< 15cm) - drawing error, just close it
            logger.debug(f"Healing small gap of {gap_distance*100:.1f}cm")
            coords_closed = coords + [coords[0]]
            try:
                polygon = Polygon(coords_closed)
                if not polygon.is_valid:
                    polygon = make_valid(polygon)
                return polygon, [], None
            except Exception as e:
                return None, [], ProcessingWarning(
                    warning_type="heal_failed",
                    message=f"Failed to heal small gap: {e}"
                )
        
        elif self.opening_min <= gap_distance <= self.opening_max:
            # Medium gap (70-250cm) - door or window opening
            opening_type = "door" if gap_distance >= 0.75 else "window"
            midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
            
            openings.append(DetectedOpening(
                width_m=gap_distance,
                location=midpoint,
                opening_type=opening_type
            ))
            
            logger.debug(f"Detected {opening_type} opening: {gap_distance*100:.1f}cm")
            
            # Close virtually for area calculation
            coords_closed = coords + [coords[0]]
            try:
                polygon = Polygon(coords_closed)
                if not polygon.is_valid:
                    polygon = make_valid(polygon)
                return polygon, openings, None
            except Exception as e:
                return None, openings, ProcessingWarning(
                    warning_type="heal_failed",
                    message=f"Failed to close opening gap: {e}"
                )
        
        else:
            # Large gap (> 250cm) - cannot determine intent
            return None, [], ProcessingWarning(
                warning_type="unclosed_polygon",
                message=f"Gap of {gap_distance*100:.1f}cm is too large to heal automatically",
                location=((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
            )
    
    def attempt_polygon_merge(
        self,
        lines: list[LineString]
    ) -> tuple[list[Polygon], list[ProcessingWarning]]:
        """
        Attempt to create polygons from disconnected lines.
        
        Uses shapely's polygonize to find enclosed areas.
        
        Args:
            lines: List of LineString geometries
            
        Returns:
            Tuple of (polygons, warnings)
        """
        warnings = []
        
        if not lines:
            return [], []
        
        try:
            # Merge lines where possible
            merged = linemerge(lines)
            
            # Create union of all lines
            all_lines = unary_union(lines)
            
            # Polygonize to find enclosed areas
            polygons = list(polygonize(all_lines))
            
            # Filter out tiny polygons (< 1m²)
            valid_polygons = [
                p for p in polygons
                if p.is_valid and p.area >= GEOMETRY.MIN_ROOM_AREA_M2
            ]
            
            logger.info(f"Polygonize found {len(valid_polygons)} valid polygons from {len(lines)} lines")
            
            return valid_polygons, warnings
            
        except Exception as e:
            warnings.append(ProcessingWarning(
                warning_type="polygonize_error",
                message=f"Failed to create polygons from lines: {e}"
            ))
            return [], warnings


# =============================================================================
# CAD PROCESSOR - MAIN CLASS
# =============================================================================

class CadProcessor:
    """
    Main CAD processing engine.
    
    Orchestrates the complete workflow:
    1. File validation and conversion (DWG -> DXF)
    2. Entity extraction from DXF
    3. Unit normalization
    4. DBSCAN clustering for block detection
    5. Polygon extraction with gap healing
    6. Text-in-polygon matching for room identification
    7. Material assignment via MaterialMapper
    
    2026 Design Notes:
    - All geometry flattened to 2D (Z=0)
    - Graceful degradation with comprehensive warnings
    - Thread-safe design for async FastAPI
    """
    
    def __init__(self, drawing_unit: str = "cm"):
        """
        Initialize CAD processor.
        
        Args:
            drawing_unit: Unit of the CAD drawing (mm, cm, m)
        """
        self.drawing_unit = drawing_unit
        self.normalizer = UnitNormalizer(drawing_unit)
        self.healer = GeometryHealer(self.normalizer)
        self.material_mapper = MaterialMapper()
        self.oda_converter = ODAConverter()
        
        # Processing state
        self.warnings: list[ProcessingWarning] = []
        self.stats: dict[str, Any] = {}
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file for deduplication."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def _extract_polyline_coords(
        self,
        entity: LWPolyline | Polyline
    ) -> tuple[list[tuple[float, float]], bool]:
        """
        Extract 2D coordinates from a polyline entity.
        
        Flattens Z-axis to 0 as per specification.
        
        Returns:
            Tuple of (coords, is_closed)
        """
        is_closed = entity.closed if hasattr(entity, 'closed') else False
        
        if isinstance(entity, LWPolyline):
            # LWPolyline stores 2D points directly
            coords = [(p[0], p[1]) for p in entity.get_points()]
        else:
            # 3D Polyline - flatten Z
            coords = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        
        # Normalize to meters
        coords = [self.normalizer.normalize_point(x, y) for x, y in coords]
        
        return coords, is_closed
    
    def _extract_line_coords(self, entity: Line) -> tuple[tuple[float, float], tuple[float, float]]:
        """Extract start and end points from a line entity."""
        start = self.normalizer.normalize_point(entity.dxf.start.x, entity.dxf.start.y)
        end = self.normalizer.normalize_point(entity.dxf.end.x, entity.dxf.end.y)
        return start, end
    
    def _extract_text_info(
        self,
        entity: Text | MText
    ) -> tuple[str, tuple[float, float]]:
        """
        Extract text content and position from text entity.
        
        Returns:
            Tuple of (text_content, (x, y) position in meters)
        """
        if isinstance(entity, MText):
            content = entity.plain_text()
            pos = entity.dxf.insert
        else:
            content = entity.dxf.text
            pos = entity.dxf.insert
        
        normalized_pos = self.normalizer.normalize_point(pos.x, pos.y)
        return content, normalized_pos
    
    def _cluster_entities(
        self,
        entity_centroids: list[tuple[float, float]]
    ) -> list[list[int]]:
        """
        Cluster entity centroids using DBSCAN to detect separate blocks.
        
        Args:
            entity_centroids: List of (x, y) centroid positions
            
        Returns:
            List of clusters, each containing indices of entities
        """
        if len(entity_centroids) < GEOMETRY.DBSCAN_MIN_SAMPLES:
            # Not enough entities for clustering, treat as single block
            return [list(range(len(entity_centroids)))]
        
        # Convert to numpy array for DBSCAN
        points = np.array(entity_centroids)
        
        # Run DBSCAN
        clustering = DBSCAN(
            eps=GEOMETRY.DBSCAN_EPS,
            min_samples=GEOMETRY.DBSCAN_MIN_SAMPLES
        ).fit(points)
        
        # Group by cluster label
        clusters: dict[int, list[int]] = {}
        for idx, label in enumerate(clustering.labels_):
            if label == -1:
                # Noise - create individual cluster
                label = max(clusters.keys(), default=-1) + 1000 + idx
            
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(idx)
        
        logger.info(f"DBSCAN found {len(clusters)} clusters from {len(entity_centroids)} entities")
        
        return list(clusters.values())
    
    def _identify_block_name(
        self,
        texts: list[tuple[str, tuple[float, float]]],
        cluster_bounds: tuple[float, float, float, float]
    ) -> str:
        """
        Identify block name from text entities within cluster bounds.
        
        Looks for patterns like "A BLOK", "B BLOK", "1. BLOK", "ANA BINA"
        
        Args:
            texts: List of (text, position) tuples
            cluster_bounds: (minx, miny, maxx, maxy) of cluster
            
        Returns:
            Block name or default "Blok X"
        """
        minx, miny, maxx, maxy = cluster_bounds
        bounding_box = box(minx, miny, maxx, maxy)
        
        # Block naming patterns
        block_patterns = [
            r'([A-Z])\s*BLOK',           # "A BLOK"
            r'BLOK\s*([A-Z0-9]+)',        # "BLOK A" or "BLOK 1"
            r'(\d+)\.\s*BLOK',            # "1. BLOK"
            r'ANA\s*BINA',                # "ANA BINA"
            r'BUILDING\s*([A-Z0-9]+)',    # "BUILDING A"
        ]
        
        for text, pos in texts:
            point = Point(pos[0], pos[1])
            if bounding_box.contains(point) or bounding_box.buffer(5).contains(point):
                normalized_text = TextNormalizer.normalize(text)
                
                for pattern in block_patterns:
                    match = re.search(pattern, normalized_text)
                    if match:
                        if "ANA" in normalized_text:
                            return "Ana Bina"
                        group = match.group(1) if match.lastindex else ""
                        return f"{group} Blok" if group else "Ana Blok"
        
        return ""  # Will be assigned default name later
    
    def _identify_floor_name(
        self,
        texts: list[tuple[str, tuple[float, float]]],
        polygon: Polygon
    ) -> str:
        """
        Identify floor name from text near the polygon.
        
        Looks for patterns like "ZEMIN KAT", "1. KAT", "BODRUM"
        """
        floor_patterns = [
            (r'ZEMIN\s*KAT', "Zemin Kat"),
            (r'(\d+)\.\s*KAT', lambda m: f"{m.group(1)}. Kat"),
            (r'BODRUM\s*(\d*)', lambda m: f"Bodrum {m.group(1) or ''}".strip()),
            (r'CATI\s*KATI', "Çatı Katı"),
            (r'TERAS\s*KATI', "Teras Katı"),
            (r'GROUND\s*FLOOR', "Zemin Kat"),
            (r'FLOOR\s*(\d+)', lambda m: f"{m.group(1)}. Kat"),
        ]
        
        # Check texts within extended polygon bounds
        bounds = polygon.bounds
        search_box = box(bounds[0] - 5, bounds[1] - 5, bounds[2] + 5, bounds[3] + 5)
        
        for text, pos in texts:
            point = Point(pos[0], pos[1])
            if search_box.contains(point):
                normalized = TextNormalizer.normalize(text)
                
                for pattern, result in floor_patterns:
                    match = re.search(pattern, normalized)
                    if match:
                        if callable(result):
                            return result(match)
                        return result
        
        return "Zemin Kat"  # Default
    
    def process_file(self, file_path: Path) -> ProcessingResult:
        """
        Process a CAD file (DWG or DXF).
        
        Complete workflow:
        1. Convert DWG to DXF if needed
        2. Parse DXF entities
        3. Cluster to detect blocks
        4. Extract and heal polygons
        5. Match rooms to text labels
        6. Assign materials
        
        Args:
            file_path: Path to CAD file
            
        Returns:
            ProcessingResult with blocks, rooms, and warnings
        """
        self.warnings = []
        self.stats = {
            "total_entities": 0,
            "polylines_processed": 0,
            "lines_processed": 0,
            "texts_found": 0,
            "rooms_detected": 0,
            "blocks_detected": 0,
        }
        
        logger.info(f"Processing CAD file: {file_path}")
        
        # Calculate file hash
        try:
            file_hash = self._calculate_file_hash(file_path)
        except Exception as e:
            file_hash = None
            self.warnings.append(ProcessingWarning(
                warning_type="hash_error",
                message=f"Could not calculate file hash: {e}"
            ))
        
        # Step 1: Handle file format
        dxf_path = file_path
        temp_dxf = False
        
        if file_path.suffix.lower() == ".dwg":
            logger.info("DWG file detected, converting to DXF...")
            converted_path, error = self.oda_converter.convert_dwg_to_dxf(file_path)
            
            if error:
                self.warnings.append(ProcessingWarning(
                    warning_type="conversion_error",
                    message=error
                ))
                return ProcessingResult(
                    success=False,
                    warnings=self.warnings,
                    stats=self.stats,
                    file_hash=file_hash
                )
            
            dxf_path = converted_path
            temp_dxf = True
        
        try:
            # Step 2: Parse DXF
            doc = ezdxf.readfile(str(dxf_path))
            msp = doc.modelspace()
            
            # Collect all geometry entities
            polylines: list[tuple[list[tuple[float, float]], bool, tuple[float, float]]] = []  # coords, is_closed, centroid
            lines: list[LineString] = []
            texts: list[tuple[str, tuple[float, float]]] = []
            entity_centroids: list[tuple[float, float]] = []
            
            for entity in msp:
                self.stats["total_entities"] += 1
                
                # Process polylines (primary source of room boundaries)
                if isinstance(entity, (LWPolyline, Polyline)):
                    try:
                        coords, is_closed = self._extract_polyline_coords(entity)
                        if len(coords) >= 3:
                            centroid = (
                                sum(c[0] for c in coords) / len(coords),
                                sum(c[1] for c in coords) / len(coords)
                            )
                            polylines.append((coords, is_closed, centroid))
                            entity_centroids.append(centroid)
                            self.stats["polylines_processed"] += 1
                    except Exception as e:
                        self.warnings.append(ProcessingWarning(
                            warning_type="entity_error",
                            message=f"Failed to process polyline: {e}",
                            entity_handle=entity.dxf.handle
                        ))
                
                # Process individual lines (for polygonize fallback)
                elif isinstance(entity, Line):
                    try:
                        start, end = self._extract_line_coords(entity)
                        line = LineString([start, end])
                        lines.append(line)
                        centroid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
                        entity_centroids.append(centroid)
                        self.stats["lines_processed"] += 1
                    except Exception as e:
                        pass  # Lines are secondary, don't warn
                
                # Process text entities
                elif isinstance(entity, (Text, MText)):
                    try:
                        content, pos = self._extract_text_info(entity)
                        if content.strip():
                            texts.append((content.strip(), pos))
                            self.stats["texts_found"] += 1
                    except Exception as e:
                        pass  # Text errors are non-critical
            
            logger.info(f"Parsed {self.stats['polylines_processed']} polylines, {self.stats['lines_processed']} lines, {self.stats['texts_found']} texts")
            
            # Step 3: Cluster entities to detect blocks
            if entity_centroids:
                cluster_indices = self._cluster_entities(entity_centroids)
            else:
                cluster_indices = []
            
            self.stats["blocks_detected"] = len(cluster_indices)
            
            # Step 4-7: Process each cluster as a block
            blocks: list[DetectedBlock] = []
            
            for cluster_idx, indices in enumerate(cluster_indices):
                # Get entities in this cluster
                cluster_polylines = [
                    polylines[i] for i in indices 
                    if i < len(polylines)
                ]
                
                # Calculate cluster bounding box
                all_coords = []
                for coords, _, _ in cluster_polylines:
                    all_coords.extend(coords)
                
                if not all_coords:
                    continue
                
                minx = min(c[0] for c in all_coords)
                miny = min(c[1] for c in all_coords)
                maxx = max(c[0] for c in all_coords)
                maxy = max(c[1] for c in all_coords)
                cluster_bounds = (minx, miny, maxx, maxy)
                
                # Identify block name
                block_name = self._identify_block_name(texts, cluster_bounds)
                if not block_name:
                    block_name = f"Blok {cluster_idx + 1}" if len(cluster_indices) > 1 else "Ana Bina"
                
                # Process polylines into rooms
                rooms: list[DetectedRoom] = []
                
                for coords, is_closed, centroid in cluster_polylines:
                    # Heal geometry
                    polygon, openings, warning = self.healer.heal_polyline(coords, is_closed)
                    
                    if warning:
                        warning.location = centroid
                        self.warnings.append(warning)
                    
                    if polygon is None or polygon.is_empty:
                        continue
                    
                    # Skip tiny polygons
                    if polygon.area < GEOMETRY.MIN_ROOM_AREA_M2:
                        continue
                    
                    # TASK 2A FIX: Skip thin rectangles (likely walls or columns)
                    # Calculate minimum width using minimum rotated rectangle
                    try:
                        min_rect = polygon.minimum_rotated_rectangle
                        if min_rect and not min_rect.is_empty:
                            # Get width and height of the minimum bounding rectangle
                            rect_coords = list(min_rect.exterior.coords)
                            edge1 = ((rect_coords[0][0] - rect_coords[1][0])**2 + 
                                     (rect_coords[0][1] - rect_coords[1][1])**2) ** 0.5
                            edge2 = ((rect_coords[1][0] - rect_coords[2][0])**2 + 
                                     (rect_coords[1][1] - rect_coords[2][1])**2) ** 0.5
                            min_width = min(edge1, edge2)
                            
                            # If minimum width < 0.5m (50cm), it's likely a wall
                            if min_width < 0.5:
                                logger.debug(f"Skipping thin polygon (width={min_width*100:.1f}cm) - likely wall")
                                continue
                    except Exception:
                        pass  # If calculation fails, proceed with the polygon
                    
                    # Find room name via point-in-polygon
                    room_name = "Bilinmeyen Oda"
                    for text, text_pos in texts:
                        point = Point(text_pos[0], text_pos[1])
                        if polygon.contains(point):
                            room_name = text
                            break
                    
                    # Detect room type and materials
                    room_type, _ = self.material_mapper.process_room(room_name)
                    
                    # Calculate wall length (perimeter minus openings)
                    perimeter = polygon.length
                    opening_length = sum(o.width_m for o in openings)
                    wall_length = max(0, perimeter - opening_length)
                    
                    # Create room object
                    room = DetectedRoom(
                        name=room_name,
                        room_type=room_type,
                        polygon=polygon,
                        area_m2=round(polygon.area, 4),
                        perimeter_m=round(perimeter, 4),
                        wall_length_m=round(wall_length, 4),
                        openings=openings,
                    )
                    
                    rooms.append(room)
                    self.stats["rooms_detected"] += 1
                
                # Create block
                block = DetectedBlock(
                    name=block_name,
                    rooms=rooms,
                    total_area_m2=sum(r.area_m2 for r in rooms),
                    bounding_box=cluster_bounds
                )
                blocks.append(block)
            
            logger.info(f"Processing complete: {len(blocks)} blocks, {self.stats['rooms_detected']} rooms")
            
            return ProcessingResult(
                success=True,
                blocks=blocks,
                warnings=self.warnings,
                stats=self.stats,
                file_hash=file_hash
            )
        
        except ezdxf.DXFError as e:
            logger.error(f"DXF parsing error: {e}")
            self.warnings.append(ProcessingWarning(
                warning_type="dxf_parse_error",
                message=str(e)
            ))
            return ProcessingResult(
                success=False,
                warnings=self.warnings,
                stats=self.stats,
                file_hash=file_hash
            )
        
        except Exception as e:
            logger.exception("Unexpected error during CAD processing")
            self.warnings.append(ProcessingWarning(
                warning_type="unexpected_error",
                message=str(e)
            ))
            return ProcessingResult(
                success=False,
                warnings=self.warnings,
                stats=self.stats,
                file_hash=file_hash
            )
        
        finally:
            # Cleanup temp DXF if created
            if temp_dxf and dxf_path.exists():
                try:
                    dxf_path.unlink()
                    logger.debug(f"Cleaned up temp DXF: {dxf_path}")
                except:
                    pass


# =============================================================================
# QUANTITY CALCULATOR
# =============================================================================

class QuantityCalculator:
    """
    Calculates BOM quantities from detected rooms.
    
    Applies material recipes based on room type and dimensions.
    """
    
    def __init__(self, floor_height_m: float = GEOMETRY.DEFAULT_FLOOR_HEIGHT_M):
        self.floor_height = floor_height_m
        self.material_mapper = MaterialMapper()
    
    def calculate_room_quantities(
        self,
        room: DetectedRoom
    ) -> list[dict]:
        """
        Calculate all material quantities for a room.
        
        Args:
            room: DetectedRoom object
            
        Returns:
            List of quantity dictionaries with pose_code, quantity, unit, category
        """
        quantities = []
        materials = self.material_mapper.get_materials(room.room_type)
        
        # Floor materials
        if materials.floor_pose:
            quantities.append({
                "pose_code": materials.floor_pose,
                "category": "floor",
                "quantity": round(room.area_m2, 4),
                "unit": "m²",
                "description": f"Zemin - {room.name}"
            })
        
        # Wall materials
        if materials.wall_pose:
            # Wall area = perimeter * height - openings
            wall_area = room.wall_length_m * self.floor_height
            # Apply to both sides of wall for paint/plaster
            wall_area_both_sides = wall_area * 2
            
            quantities.append({
                "pose_code": materials.wall_pose,
                "category": "wall",
                "quantity": round(wall_area_both_sides, 4),
                "unit": "m²",
                "description": f"Duvar - {room.name}"
            })
        
        # Ceiling materials
        if materials.ceiling_pose:
            quantities.append({
                "pose_code": materials.ceiling_pose,
                "category": "ceiling",
                "quantity": round(room.area_m2, 4),
                "unit": "m²",
                "description": f"Tavan - {room.name}"
            })
        
        # Additional materials (e.g., waterproofing for wet areas)
        for additional_pose in materials.additional_poses:
            quantities.append({
                "pose_code": additional_pose,
                "category": "additional",
                "quantity": round(room.area_m2, 4),
                "unit": "m²",
                "description": f"Ek Malzeme - {room.name}"
            })
        
        # TASK 2B FIX: Add skirting boards (süpürgelik) if floor material exists
        if materials.floor_pose:
            # Skirting quantity = perimeter minus openings (wall_length_m)
            quantities.append({
                "pose_code": "25.116.1100",  # Süpürgelik standard pose
                "category": "additional",
                "quantity": round(room.wall_length_m, 4),
                "unit": "mt",
                "description": f"Süpürgelik - {room.name}"
            })
        
        # TASK 2B FIX: Add door and window items from openings
        for opening in room.openings:
            if opening.opening_type == "door":
                # Door item - count as 1 piece
                quantities.append({
                    "pose_code": "25.048.1003",  # Çelik Kapı (standard interior door)
                    "category": "additional",
                    "quantity": 1.0,
                    "unit": "adet",
                    "description": f"Kapı - {room.name}"
                })
            elif opening.opening_type == "window":
                # Window item - area = width * floor_height (assumed window height)
                window_area = opening.width_m * self.floor_height
                quantities.append({
                    "pose_code": "25.035.1002",  # PVC Pencere Doğraması
                    "category": "additional",
                    "quantity": round(window_area, 4),
                    "unit": "m²",
                    "description": f"Pencere - {room.name}"
                })
        
        return quantities
    
    def calculate_block_summary(
        self,
        block: DetectedBlock
    ) -> dict:
        """
        Calculate aggregated quantities for an entire block.
        
        Args:
            block: DetectedBlock object
            
        Returns:
            Summary dictionary with total quantities by pose
        """
        aggregated: dict[str, dict] = {}
        
        for room in block.rooms:
            room_quantities = self.calculate_room_quantities(room)
            
            for qty in room_quantities:
                pose = qty["pose_code"]
                if pose not in aggregated:
                    aggregated[pose] = {
                        "pose_code": pose,
                        "category": qty["category"],
                        "total_quantity": 0,
                        "unit": qty["unit"],
                        "rooms": []
                    }
                
                aggregated[pose]["total_quantity"] += qty["quantity"]
                aggregated[pose]["rooms"].append(qty["description"])
        
        return {
            "block_name": block.name,
            "total_area_m2": block.total_area_m2,
            "room_count": len(block.rooms),
            "quantities": list(aggregated.values())
        }


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def process_cad_file(
    file_path: str | Path,
    drawing_unit: str = "cm",
    floor_height_m: float = 2.80
) -> ProcessingResult:
    """
    Convenience function to process a CAD file.
    
    Args:
        file_path: Path to DWG or DXF file
        drawing_unit: Unit of the drawing (mm, cm, m)
        floor_height_m: Floor height for wall calculations
        
    Returns:
        ProcessingResult with all detected blocks and rooms
    """
    processor = CadProcessor(drawing_unit=drawing_unit)
    return processor.process_file(Path(file_path))
