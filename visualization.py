"""
Floor Plan Visualization Module
================================

Generates 2D floor plan images from detected rooms for visual verification.

Features:
- Color-coded rooms by type (living, wet area, corridor, etc.)
- Room labels with name and area
- Legend showing room type colors
- Scale bar for reference
- North arrow indicator
- Dark mode compatible styling

Author: AI Solutions Architect
Version: 1.1.0
"""

import io
import base64
import logging
from typing import Optional

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server use

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon, FancyArrowPatch
from matplotlib.collections import PatchCollection
import numpy as np

from config import RoomType


# Configure module logger
logger = logging.getLogger("construction_engine.visualization")


# =============================================================================
# ROOM COLOR PALETTE
# =============================================================================

# Color palette for room types (dark mode friendly)
ROOM_COLORS = {
    RoomType.TYPE_LIVING: "#4A90D9",   # Blue - Living rooms
    RoomType.TYPE_WET: "#26C6DA",      # Cyan - Wet areas (bath, WC)
    RoomType.TYPE_KITCHEN: "#FF9800",  # Orange - Kitchen
    RoomType.TYPE_HALLWAY: "#9575CD",  # Purple - Corridors
    RoomType.TYPE_STAIRS: "#78909C",   # Blue Grey - Stairs
    RoomType.TYPE_ELEVATOR: "#607D8B", # Grey - Elevator
    RoomType.TYPE_ENTRANCE: "#AB47BC", # Purple - Entrance
    RoomType.TYPE_OUTDOOR: "#66BB6A",  # Light green - Balcony/Terrace
    RoomType.TYPE_STORAGE: "#8D6E63",  # Brown - Storage
    RoomType.TYPE_UNKNOWN: "#BDBDBD",  # Grey - Unknown
}

# Turkish room type display names
ROOM_TYPE_NAMES = {
    RoomType.TYPE_LIVING: "Yaşam Alanı",
    RoomType.TYPE_WET: "Islak Hacim",
    RoomType.TYPE_KITCHEN: "Mutfak",
    RoomType.TYPE_HALLWAY: "Koridor/Hol",
    RoomType.TYPE_STAIRS: "Merdiven",
    RoomType.TYPE_ELEVATOR: "Asansör",
    RoomType.TYPE_ENTRANCE: "Giriş",
    RoomType.TYPE_OUTDOOR: "Balkon/Teras",
    RoomType.TYPE_STORAGE: "Depo",
    RoomType.TYPE_UNKNOWN: "Bilinmeyen",
}

# String-to-RoomType mapping for data-based rendering
_ROOM_TYPE_MAP = {rt.value: rt for rt in RoomType}


def generate_floor_plan_from_data(
    blocks_data: list,
    title: str = "Kat Planı",
    dark_mode: bool = True,
    dpi: int = 150
) -> str:
    """
    Generate a floor plan image from JSON/dict data (no Shapely polygons needed).
    
    Uses area and perimeter to estimate rectangular room dimensions,
    arranges rooms in a grid, and renders openings (doors/windows).
    
    Args:
        blocks_data: List of block dicts, each with 'rooms' list containing
                     name, area_m2, perimeter_m, room_type, openings
        title: Title for the image
        dark_mode: Dark mode styling
        dpi: Resolution
        
    Returns:
        Base64 encoded PNG image string
    """
    if dark_mode:
        plt.style.use('dark_background')
        bg_color = '#1E1E1E'
        text_color = '#FFFFFF'
        wall_color = '#FFFFFF'
        grid_color = '#333333'
    else:
        plt.style.use('default')
        bg_color = '#FFFFFF'
        text_color = '#000000'
        wall_color = '#000000'
        grid_color = '#CCCCCC'
    
    fig, ax = plt.subplots(1, 1, figsize=(14, 10), dpi=dpi)
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    room_types_used = set()
    has_openings = False
    
    # Collect all rooms across blocks
    all_rooms = []
    for block in blocks_data:
        block_name = block.get("name", "Blok")
        rooms = block.get("rooms", [])
        # Also check nested floors structure
        for floor in block.get("floors", []):
            rooms.extend(floor.get("rooms", []))
        for room in rooms:
            all_rooms.append({**room, "_block": block_name})
    
    if not all_rooms:
        plt.close(fig)
        return ""
    
    # Estimate rectangular dimensions from area and perimeter
    def estimate_dimensions(area, perimeter):
        half_p = perimeter / 2.0
        discriminant = half_p**2 - 4 * area
        if discriminant < 0:
            side = area**0.5
            return side, side
        sqrt_d = discriminant**0.5
        w = (half_p + sqrt_d) / 2.0
        h = (half_p - sqrt_d) / 2.0
        return max(w, 0.5), max(h, 0.5)
    
    # Grid layout
    gap = 0.3
    cols = max(1, int(len(all_rooms)**0.5) + 1)
    x_offset = 0.0
    y_offset = 0.0
    row_max_height = 0.0
    col_idx = 0
    
    for room_data in all_rooms:
        area = room_data.get("area_m2", 4.0)
        perimeter = room_data.get("perimeter_m", 8.0)
        room_type_str = room_data.get("room_type", "unknown")
        room_type = _ROOM_TYPE_MAP.get(room_type_str, RoomType.TYPE_UNKNOWN)
        room_color = ROOM_COLORS.get(room_type, ROOM_COLORS[RoomType.TYPE_UNKNOWN])
        room_types_used.add(room_type)
        
        w, h = estimate_dimensions(area, perimeter)
        
        # Draw room rectangle
        rect = plt.Rectangle(
            (x_offset, y_offset), w, h,
            facecolor=room_color, edgecolor=wall_color,
            linewidth=1.5, alpha=0.7
        )
        ax.add_patch(rect)
        
        # Room label
        label = f"{room_data.get('name', '?')}\n{area:.1f} m²"
        ax.text(
            x_offset + w / 2, y_offset + h / 2, label,
            ha='center', va='center', fontsize=8, fontweight='bold',
            color=text_color,
            bbox=dict(boxstyle='round,pad=0.2', facecolor=bg_color, alpha=0.7,
                      edgecolor=grid_color, linewidth=0.5)
        )
        
        # Draw openings along the bottom wall
        openings = room_data.get("openings", [])
        if openings:
            has_openings = True
            op_x = x_offset + 0.3
            for op in openings:
                op_width = op.get("width_m", 0.9)
                op_type = op.get("type", op.get("opening_type", "door"))
                if op_x + op_width > x_offset + w - 0.1:
                    break
                if op_type == "door":
                    ax.plot([op_x, op_x + op_width], [y_offset, y_offset],
                            color='#FFD54F', linewidth=3, linestyle='--', alpha=0.9)
                    arc = mpatches.Arc(
                        (op_x, y_offset), op_width * 1.4, op_width * 1.4,
                        angle=0, theta1=0, theta2=90,
                        color='#FFD54F', linewidth=1, linestyle=':', alpha=0.6)
                    ax.add_patch(arc)
                elif op_type == "window":
                    ax.plot([op_x, op_x + op_width], [y_offset, y_offset],
                            color='#00BCD4', linewidth=5, alpha=0.8, solid_capstyle='butt')
                    ax.plot([op_x, op_x + op_width], [y_offset, y_offset],
                            color=bg_color, linewidth=2, alpha=1.0, solid_capstyle='butt')
                else:
                    ax.plot([op_x, op_x + op_width], [y_offset, y_offset],
                            color='#E0E0E0', linewidth=3, linestyle='-.', alpha=0.8)
                op_x += op_width + 0.2
        
        row_max_height = max(row_max_height, h)
        col_idx += 1
        if col_idx >= cols:
            col_idx = 0
            x_offset = 0.0
            y_offset += row_max_height + gap
            row_max_height = 0.0
        else:
            x_offset += w + gap
    
    # Styling
    ax.set_aspect('equal')
    ax.autoscale()
    ax.set_title(title, fontsize=14, fontweight='bold', color=text_color, pad=20)
    ax.set_xlabel("X (metre)", fontsize=10, color=text_color)
    ax.set_ylabel("Y (metre)", fontsize=10, color=text_color)
    ax.tick_params(colors=text_color)
    ax.grid(True, linestyle='--', alpha=0.2, color=grid_color)
    for spine in ax.spines.values():
        spine.set_color(grid_color)
    
    # Legend
    if room_types_used:
        legend_handles = []
        for room_type in sorted(room_types_used, key=lambda x: x.value):
            color = ROOM_COLORS.get(room_type, ROOM_COLORS[RoomType.TYPE_UNKNOWN])
            name = ROOM_TYPE_NAMES.get(room_type, str(room_type.value))
            legend_handles.append(mpatches.Patch(color=color, label=name, alpha=0.7))
        if has_openings:
            legend_handles.append(plt.Line2D([0], [0], color='#FFD54F', linewidth=3, linestyle='--', label='Kapı'))
            legend_handles.append(plt.Line2D([0], [0], color='#00BCD4', linewidth=4, label='Pencere'))
        ax.legend(handles=legend_handles, loc='upper left', fontsize=8,
                  framealpha=0.8, facecolor=bg_color, edgecolor=grid_color, labelcolor=text_color)
    
    plt.tight_layout()
    
    buffer = io.BytesIO()
    fig.savefig(buffer, format='png', dpi=dpi, facecolor=bg_color, edgecolor='none', bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close(fig)
    buffer.close()
    logger.info(f"Generated data-based floor plan: {len(image_base64)} bytes")
    return image_base64


def generate_floor_plan_image(
    blocks: list,
    title: str = "Kat Planı Analizi",
    show_legend: bool = True,
    show_scale: bool = True,
    show_north: bool = True,
    dark_mode: bool = True,
    dpi: int = 150
) -> str:
    """
    Generate a 2D floor plan image from detected blocks and rooms.
    
    Args:
        blocks: List of DetectedBlock objects with rooms
        title: Title for the floor plan
        show_legend: Whether to show the room type legend
        show_scale: Whether to show the scale bar
        show_north: Whether to show the north arrow
        dark_mode: Use dark mode styling
        dpi: Image resolution (dots per inch)
        
    Returns:
        Base64 encoded PNG image string
    """
    # Set up matplotlib style
    if dark_mode:
        plt.style.use('dark_background')
        bg_color = '#1E1E1E'
        text_color = '#FFFFFF'
        wall_color = '#FFFFFF'
        grid_color = '#333333'
    else:
        plt.style.use('default')
        bg_color = '#FFFFFF'
        text_color = '#000000'
        wall_color = '#000000'
        grid_color = '#CCCCCC'
    
    # Create figure
    fig, ax = plt.subplots(1, 1, figsize=(12, 10), dpi=dpi)
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    # Collect all room polygons and their bounds
    all_coords = []
    room_patches = []
    room_types_used = set()
    
    for block in blocks:
        for idx, room in enumerate(block.rooms):
            if room.polygon and room.polygon.is_valid:
                # Get exterior coordinates
                coords = list(room.polygon.exterior.coords)
                if coords:
                    all_coords.extend(coords)
                    
                    # Create patch
                    room_color = ROOM_COLORS.get(room.room_type, ROOM_COLORS[RoomType.TYPE_UNKNOWN])
                    patch = MplPolygon(
                        coords,
                        closed=True,
                        facecolor=room_color,
                        edgecolor=wall_color,
                        linewidth=1.5,
                        alpha=0.7
                    )
                    ax.add_patch(patch)
                    room_types_used.add(room.room_type)
                    
                    # --- v1.2: Render Openings (Doors/Windows) ---
                    if hasattr(room, 'openings') and room.openings:
                        for opening in room.openings:
                            if hasattr(opening, 'location') and opening.location:
                                # Location is usually a LineString or pair of points
                                try:
                                    # Simple line representation for opening
                                    op_coords = list(opening.location.coords)
                                    if len(op_coords) >= 2:
                                        op_x, op_y = zip(*op_coords)
                                        if opening.opening_type == "door":
                                            # Draw dashed line for door
                                            ax.plot(op_x, op_y, color=wall_color, linewidth=2, linestyle='--')
                                            # Draw 'swing' arc if possible (simplified as a small arc)
                                        else:
                                            # Draw double line for window
                                            ax.plot(op_x, op_y, color='#00BCD4', linewidth=4, alpha=0.8) # Cyan window
                                except:
                                    pass

                    # Add room label
                    centroid = room.centroid
                    label_text = f"[{idx+1}] {room.name}\n{room.area_m2:.1f} m²"
                    ax.annotate(
                        label_text,
                        xy=centroid,
                        ha='center',
                        va='center',
                        fontsize=9,
                        fontweight='bold',
                        color=text_color,
                        bbox=dict(
                            boxstyle='round,pad=0.3',
                            facecolor=bg_color,
                            edgecolor=grid_color,
                            alpha=0.8,
                            linewidth=0.5
                        )
                    )
    
    # Set axis limits with padding
    if all_coords:
        xs, ys = zip(*all_coords)
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        
        # Add 10% padding
        x_padding = (x_max - x_min) * 0.15
        y_padding = (y_max - y_min) * 0.15
        
        ax.set_xlim(x_min - x_padding, x_max + x_padding)
        ax.set_ylim(y_min - y_padding, y_max + y_padding)
    
    # Equal aspect ratio
    ax.set_aspect('equal')
    
    # Grid
    ax.grid(True, linestyle='--', alpha=0.3, color=grid_color)
    
    # Title
    ax.set_title(title, fontsize=14, fontweight='bold', color=text_color, pad=20)
    
    # Axis labels
    ax.set_xlabel("X (metre)", fontsize=10, color=text_color)
    ax.set_ylabel("Y (metre)", fontsize=10, color=text_color)
    
    # Tick colors
    ax.tick_params(colors=text_color)
    for spine in ax.spines.values():
        spine.set_color(grid_color)
    
    # Legend
    if show_legend and room_types_used:
        legend_patches = []
        for room_type in sorted(room_types_used, key=lambda x: x.value):
            color = ROOM_COLORS.get(room_type, ROOM_COLORS[RoomType.TYPE_UNKNOWN])
            name = ROOM_TYPE_NAMES.get(room_type, str(room_type.value))
            patch = mpatches.Patch(color=color, label=name, alpha=0.7)
            legend_patches.append(patch)
        
        legend = ax.legend(
            handles=legend_patches,
            loc='upper left',
            fontsize=8,
            framealpha=0.8,
            facecolor=bg_color,
            edgecolor=grid_color,
            labelcolor=text_color
        )
    
    # Scale bar
    if show_scale and all_coords:
        _add_scale_bar(ax, x_min, y_min, x_max - x_min, text_color, bg_color)
    
    # North arrow
    if show_north and all_coords:
        _add_north_arrow(ax, x_max + x_padding * 0.3, y_max, text_color)
    
    # Tight layout
    plt.tight_layout()
    
    # Save to buffer
    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format='png',
        dpi=dpi,
        facecolor=bg_color,
        edgecolor='none',
        bbox_inches='tight'
    )
    buffer.seek(0)
    
    # Encode to base64
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    
    # Cleanup
    plt.close(fig)
    buffer.close()
    
    logger.info(f"Generated floor plan image: {len(image_base64)} bytes (base64)")
    
    return image_base64


def _add_scale_bar(ax, x_start: float, y_start: float, total_width: float, text_color: str, bg_color: str):
    """Add a scale bar to the plot."""
    # Determine appropriate scale length (1m, 2m, 5m, 10m, etc.)
    scale_options = [1, 2, 5, 10, 20, 50, 100]
    target_length = total_width * 0.15  # 15% of plot width
    
    scale_length = 1
    for opt in scale_options:
        if opt <= target_length:
            scale_length = opt
        else:
            break
    
    # Position at bottom left
    y_pos = y_start - total_width * 0.05
    
    # Draw scale bar
    ax.plot(
        [x_start, x_start + scale_length],
        [y_pos, y_pos],
        color=text_color,
        linewidth=3,
        solid_capstyle='butt'
    )
    
    # Scale bar end caps
    cap_height = total_width * 0.01
    ax.plot([x_start, x_start], [y_pos - cap_height, y_pos + cap_height], color=text_color, linewidth=2)
    ax.plot([x_start + scale_length, x_start + scale_length], [y_pos - cap_height, y_pos + cap_height], color=text_color, linewidth=2)
    
    # Scale label
    ax.annotate(
        f"{scale_length} m",
        xy=(x_start + scale_length / 2, y_pos - cap_height * 3),
        ha='center',
        va='top',
        fontsize=9,
        fontweight='bold',
        color=text_color
    )


def _add_north_arrow(ax, x_pos: float, y_pos: float, text_color: str):
    """Add a north arrow indicator to the plot."""
    arrow_length = 1.5
    
    # Arrow
    ax.annotate(
        '',
        xy=(x_pos, y_pos + arrow_length),
        xytext=(x_pos, y_pos),
        arrowprops=dict(
            arrowstyle='->',
            color=text_color,
            lw=2
        )
    )
    
    # N label
    ax.annotate(
        'N',
        xy=(x_pos, y_pos + arrow_length + 0.3),
        ha='center',
        va='bottom',
        fontsize=12,
        fontweight='bold',
        color=text_color
    )


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_room_color(room_type: RoomType) -> str:
    """Get the display color for a room type."""
    return ROOM_COLORS.get(room_type, ROOM_COLORS[RoomType.TYPE_UNKNOWN])


def get_room_type_name(room_type: RoomType) -> str:
    """Get the Turkish display name for a room type."""
    return ROOM_TYPE_NAMES.get(room_type, str(room_type.value))
