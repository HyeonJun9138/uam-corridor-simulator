from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


Point = Tuple[float, float]


def link_id(start_id: str, end_id: str) -> str:
    return f"{start_id}->{end_id}"


@dataclass(frozen=True)
class RouteNode:
    id: str
    col: int
    row: int
    x_m: float
    y_m: float
    role: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "col": self.col,
            "row": self.row,
            "x": self.x_m,
            "y": self.y_m,
            "role": self.role,
        }


@dataclass(frozen=True)
class RouteLink:
    id: str
    start_id: str
    end_id: str
    length_m: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "start_id": self.start_id,
            "end_id": self.end_id,
            "length_m": self.length_m,
        }


@dataclass
class RouteGeometry:
    node_ids: List[str]
    link_ids: List[str]
    points: List[Point]
    cumulative_m: List[float]
    node_progress_m: List[float]
    total_length_m: float

    def _sample_point(self, progress_m: float) -> Point:
        if not self.points:
            return 0.0, 0.0
        if len(self.points) == 1 or self.total_length_m <= 1e-9:
            return self.points[-1]

        s = min(max(float(progress_m), 0.0), self.total_length_m)
        hi = 0
        while hi < len(self.cumulative_m) and self.cumulative_m[hi] < s:
            hi += 1

        if hi <= 0:
            return self.points[0]

        if hi >= len(self.points):
            return self.points[-1]

        s0 = self.cumulative_m[hi - 1]
        s1 = self.cumulative_m[hi]
        p0 = self.points[hi - 1]
        p1 = self.points[hi]
        if s1 <= s0 + 1e-9:
            return p1

        t = (s - s0) / (s1 - s0)
        x = p0[0] + (p1[0] - p0[0]) * t
        y = p0[1] + (p1[1] - p0[1]) * t
        return x, y

    def sample(self, progress_m: float) -> Tuple[float, float, float]:
        if not self.points:
            return 0.0, 0.0, 0.0
        if len(self.points) == 1 or self.total_length_m <= 1e-9:
            x, y = self.points[-1]
            return x, y, 0.0

        s = min(max(float(progress_m), 0.0), self.total_length_m)
        x, y = self._sample_point(s)
        base_step = self.total_length_m / max(len(self.points) - 1, 1)
        tangent_step = max(10.0, min(80.0, base_step * 1.5))
        prev_x, prev_y = self._sample_point(max(0.0, s - tangent_step))
        next_x, next_y = self._sample_point(min(self.total_length_m, s + tangent_step))
        heading = math.atan2(next_y - prev_y, next_x - prev_x)
        return x, y, heading

    def active_link_index(self, progress_m: float) -> int:
        if len(self.node_progress_m) <= 1:
            return 0
        s = min(max(float(progress_m), 0.0), self.total_length_m)
        for idx in range(len(self.node_progress_m) - 1):
            if s < self.node_progress_m[idx + 1] - 1e-9:
                return idx
        return len(self.node_progress_m) - 2


def build_route_grid(
    path_length_m: float,
    row_count: int = 3,
    row_gap_m: float = 1200.0,
    spacing_m: float = 5000.0,
) -> Dict[str, RouteNode]:
    rows = max(1, int(row_count))
    cols = max(2, int(round(float(path_length_m) / max(float(spacing_m), 1.0))) + 1)
    x_positions = [float(path_length_m) * col / max(cols - 1, 1) for col in range(cols)]
    center_row = (rows - 1) / 2.0

    nodes: Dict[str, RouteNode] = {}
    for col, x_m in enumerate(x_positions):
        for row in range(rows):
            y_m = (row - center_row) * float(row_gap_m)
            role = "start" if col == 0 else "end" if col == cols - 1 else "mid"
            node = RouteNode(
                id=f"N{col}_{row}",
                col=col,
                row=row,
                x_m=float(x_m),
                y_m=float(y_m),
                role=role,
            )
            nodes[node.id] = node
    return nodes


def default_straight_link_pairs(nodes_by_id: Dict[str, RouteNode]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    if not nodes_by_id:
        return pairs
    cols = max(node.col for node in nodes_by_id.values()) + 1
    rows = max(node.row for node in nodes_by_id.values()) + 1
    for row in range(rows):
        for col in range(cols - 1):
            start_id = f"N{col}_{row}"
            end_id = f"N{col + 1}_{row}"
            if start_id in nodes_by_id and end_id in nodes_by_id:
                pairs.append((start_id, end_id))
    return pairs


def validate_link_pair(
    start_id: str,
    end_id: str,
    nodes_by_id: Dict[str, RouteNode],
) -> bool:
    start = nodes_by_id.get(start_id)
    end = nodes_by_id.get(end_id)
    if start is None or end is None:
        return False
    if end.col != start.col + 1:
        return False
    return True


def build_links(
    nodes_by_id: Dict[str, RouteNode],
    pairs: Iterable[Tuple[str, str]],
) -> Dict[str, RouteLink]:
    links: Dict[str, RouteLink] = {}
    for start_id, end_id in pairs:
        if not validate_link_pair(start_id, end_id, nodes_by_id):
            continue
        start = nodes_by_id[start_id]
        end = nodes_by_id[end_id]
        dist = math.hypot(end.x_m - start.x_m, end.y_m - start.y_m)
        key = link_id(start_id, end_id)
        links[key] = RouteLink(
            id=key,
            start_id=start_id,
            end_id=end_id,
            length_m=float(dist),
        )
    return links


def build_adjacency(links_by_id: Dict[str, RouteLink]) -> Dict[str, List[str]]:
    adj: Dict[str, List[str]] = {}
    for link in links_by_id.values():
        adj.setdefault(link.start_id, []).append(link.end_id)
    for dests in adj.values():
        dests.sort()
    return adj


def reachable_end_nodes(
    start_id: str,
    nodes_by_id: Dict[str, RouteNode],
    adjacency: Dict[str, List[str]],
) -> List[str]:
    if start_id not in nodes_by_id:
        return []

    out: List[str] = []
    seen = set()

    def dfs(node_id: str):
        if node_id in seen:
            return
        seen.add(node_id)
        node = nodes_by_id[node_id]
        if node.role == "end":
            out.append(node_id)
            return
        for nxt in adjacency.get(node_id, []):
            dfs(nxt)

    dfs(start_id)
    return sorted(out, key=lambda node_id: nodes_by_id[node_id].row)


def shortest_path(
    start_id: str,
    end_id: str,
    nodes_by_id: Dict[str, RouteNode],
    links_by_id: Dict[str, RouteLink],
    adjacency: Dict[str, List[str]],
) -> Optional[List[str]]:
    if start_id not in nodes_by_id or end_id not in nodes_by_id:
        return None

    cols = sorted({node.col for node in nodes_by_id.values()})
    dist: Dict[str, float] = {start_id: 0.0}
    prev: Dict[str, str] = {}

    for col in cols:
        col_nodes = [node.id for node in nodes_by_id.values() if node.col == col]
        for node_id in col_nodes:
            base = dist.get(node_id)
            if base is None:
                continue
            for nxt in adjacency.get(node_id, []):
                edge = links_by_id.get(link_id(node_id, nxt))
                if edge is None:
                    continue
                cand = base + edge.length_m
                if cand < dist.get(nxt, math.inf):
                    dist[nxt] = cand
                    prev[nxt] = node_id

    if end_id not in dist:
        return None

    path = [end_id]
    cursor = end_id
    while cursor != start_id:
        cursor = prev[cursor]
        path.append(cursor)
    path.reverse()
    return path


def enumerate_complete_paths(
    nodes_by_id: Dict[str, RouteNode],
    adjacency: Dict[str, List[str]],
    max_paths: int = 256,
) -> List[List[str]]:
    starts = sorted(
        [node.id for node in nodes_by_id.values() if node.role == "start"],
        key=lambda node_id: nodes_by_id[node_id].row,
    )
    out: List[List[str]] = []

    def dfs(path: List[str]):
        if len(out) >= max_paths:
            return
        node_id = path[-1]
        node = nodes_by_id[node_id]
        if node.role == "end":
            out.append(list(path))
            return
        for nxt in adjacency.get(node_id, []):
            path.append(nxt)
            dfs(path)
            path.pop()

    for start_id in starts:
        dfs([start_id])
        if len(out) >= max_paths:
            break
    return out


def build_route_geometry(
    node_ids: Sequence[str],
    nodes_by_id: Dict[str, RouteNode],
    samples_per_segment: int = 24,
) -> RouteGeometry:
    if not node_ids:
        return RouteGeometry([], [], [], [], [], 0.0)

    ctrl = [(nodes_by_id[node_id].x_m, nodes_by_id[node_id].y_m) for node_id in node_ids]
    if len(ctrl) == 1:
        point = ctrl[0]
        return RouteGeometry(
            node_ids=list(node_ids),
            link_ids=[],
            points=[point],
            cumulative_m=[0.0],
            node_progress_m=[0.0],
            total_length_m=0.0,
        )

    points: List[Point] = [ctrl[0]]
    node_progress_idx = [0]

    for idx in range(len(ctrl) - 1):
        p0 = ctrl[idx - 1] if idx > 0 else ctrl[idx]
        p1 = ctrl[idx]
        p2 = ctrl[idx + 1]
        p3 = ctrl[idx + 2] if idx + 2 < len(ctrl) else ctrl[idx + 1]

        for step in range(1, max(2, samples_per_segment) + 1):
            t = step / max(2, samples_per_segment)
            points.append(_catmull_rom_point(p0, p1, p2, p3, t))
        node_progress_idx.append(len(points) - 1)

    cumulative = [0.0]
    for idx in range(1, len(points)):
        prev = points[idx - 1]
        cur = points[idx]
        cumulative.append(cumulative[-1] + math.hypot(cur[0] - prev[0], cur[1] - prev[1]))

    node_progress = [cumulative[idx] for idx in node_progress_idx]
    link_ids = [link_id(node_ids[idx], node_ids[idx + 1]) for idx in range(len(node_ids) - 1)]

    return RouteGeometry(
        node_ids=list(node_ids),
        link_ids=link_ids,
        points=points,
        cumulative_m=cumulative,
        node_progress_m=node_progress,
        total_length_m=cumulative[-1],
    )


def geometry_preview_dict(
    geometry: RouteGeometry,
    start_id: Optional[str] = None,
    end_id: Optional[str] = None,
) -> dict:
    return {
        "start_id": start_id or (geometry.node_ids[0] if geometry.node_ids else None),
        "end_id": end_id or (geometry.node_ids[-1] if geometry.node_ids else None),
        "node_ids": list(geometry.node_ids),
        "link_ids": list(geometry.link_ids),
        "points": [[float(x), float(y)] for x, y in geometry.points],
        "length_m": float(geometry.total_length_m),
    }


def _catmull_rom_point(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    t2 = t * t
    t3 = t2 * t
    x = 0.5 * (
        (2.0 * p1[0])
        + (-p0[0] + p2[0]) * t
        + (2.0 * p0[0] - 5.0 * p1[0] + 4.0 * p2[0] - p3[0]) * t2
        + (-p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0]) * t3
    )
    y = 0.5 * (
        (2.0 * p1[1])
        + (-p0[1] + p2[1]) * t
        + (2.0 * p0[1] - 5.0 * p1[1] + 4.0 * p2[1] - p3[1]) * t2
        + (-p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1]) * t3
    )
    return float(x), float(y)
