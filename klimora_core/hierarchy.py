from __future__ import annotations
from .schema import Model

def validate_hierarchy(m: Model) -> list[str]:
    errors=[]
    nodes={n.id:n for n in m.nodes}
    for n in m.nodes:
        if n.parent == n.id:
            errors.append(f'node {n.id}: cannot parent itself')
        if n.parent is not None and n.parent not in nodes:
            errors.append(f'node {n.id}: unknown parent {n.parent}')
    for nid in nodes:
        seen=set(); cur=nid
        while cur is not None:
            if cur in seen:
                errors.append(f'hierarchy cycle detected at node {nid}')
                break
            seen.add(cur); cur=nodes[cur].parent if cur in nodes else None
    return errors

def ancestors(m: Model, node_id: str, include_self: bool=False) -> list[str]:
    nodes={n.id:n for n in m.nodes}
    if node_id not in nodes: raise KeyError(node_id)
    out=[]; cur=node_id if include_self else nodes[node_id].parent
    while cur is not None:
        out.append(cur); cur=nodes[cur].parent
    return out

def descendants(m: Model, node_id: str, include_self: bool=False) -> list[str]:
    nodes={n.id:n for n in m.nodes}
    if node_id not in nodes: raise KeyError(node_id)
    out=[node_id] if include_self else []
    frontier=[node_id]
    while frontier:
        p=frontier.pop(0)
        for n in m.nodes:
            if n.parent==p:
                out.append(n.id); frontier.append(n.id)
    return out

def rollup_node_map(m: Model, leaf_node: str, target_node: str) -> bool:
    if leaf_node == target_node: return True
    return target_node in ancestors(m, leaf_node)
