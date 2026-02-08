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
    RoomType.TYPE_OUTDOOR: "Balkon/Teras",
    RoomType.TYPE_STORAGE: "Depo",
    RoomType.TYPE_UNKNOWN: "Bilinmeyen",
}


# =============================================================================
# VISUALIZATION FUNCTIONS
# =============================================================================

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
        for room in block.rooms:
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
                    
                    # Add room label
                    centroid = room.centroid
                    label_text = f"{room.name}\n{room.area_m2:.1f} m²"
                    ax.annotate(
                        label_text,
                        xy=centroid,
                        ha='center',
                        va='center',
                        fontsize=8,
                        fontweight='bold',
                        color=text_color,
                        bbox=dict(
                            boxstyle='round,pad=0.3',
                            facecolor=bg_color,
                            edgecolor='none',
                            alpha=0.7
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
