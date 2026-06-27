"""页面 AX 树序列化。

将 Playwright accessibility.snapshot() 输出裁剪并序列化为 YAML 风格文本，
与上游 ai_ui_recorder 的 snapshot-utils.js 格式保持一致。
"""

from __future__ import annotations

from typing import Any


# 无意义叶子节点 role，无 name/value/children 时丢弃
_MEANINGLESS_ROLES = {
    "none",
    "generic",
    "presentation",
    "LineBreak",
    "InlineTextBox",
    "StaticText",
}

# 需要输出的属性键
_EXPORTED_ATTRS = {
    "checked",
    "pressed",
    "expanded",
    "selected",
    "disabled",
    "required",
    "level",
    "value",
}


def _has_meaningful_content(node: dict) -> bool:
    """节点是否有意义保留。"""
    role = node.get("role", "")
    name = node.get("name", "")
    value = node.get("value")
    children = node.get("children")

    if role in _MEANINGLESS_ROLES and not name and not value and not children:
        return False
    return True


def _is_truthy(value: Any) -> bool:
    """属性值是否应输出。"""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (int, float)):
        return True
    return bool(value)


def prune_snapshot(node: dict | None, max_depth: int = 8, current_depth: int = 0) -> dict | None:
    """裁剪 AX 快照树。

    - 超过 max_depth 返回 None（丢弃）。
    - 无意义叶子节点返回 None。
    - 只保留有值属性。
    """
    if node is None:
        return None
    if current_depth > max_depth:
        return None

    role = node.get("role", "")
    name = node.get("name", "")
    value = node.get("value")
    children = node.get("children")

    if not _has_meaningful_content(node):
        return None

    pruned: dict[str, Any] = {"role": role}
    if name:
        pruned["name"] = name

    for attr in _EXPORTED_ATTRS:
        if attr == "value":
            continue
        val = node.get(attr)
        if _is_truthy(val):
            pruned[attr] = val

    # value 单独处理：字符串/数字等直接值
    if _is_truthy(value):
        pruned["value"] = value

    if children:
        pruned_children: list[dict] = []
        for child in children:
            pruned_child = prune_snapshot(child, max_depth, current_depth + 1)
            if pruned_child is not None:
                pruned_children.append(pruned_child)
        if pruned_children:
            pruned["children"] = pruned_children

    return pruned


def _format_attrs(node: dict) -> str:
    """将节点属性格式化为 [checked, value="..."] 形式。"""
    parts: list[str] = []
    for attr in _EXPORTED_ATTRS:
        if attr == "value":
            continue
        val = node.get(attr)
        if _is_truthy(val):
            parts.append(attr)

    value = node.get("value")
    if _is_truthy(value):
        parts.append(f'value="{value}"')

    if not parts:
        return ""
    return " [" + ", ".join(parts) + "]"


def snapshot_to_text(node: dict, indent: int = 0) -> str:
    """将裁剪后的 AX 快照序列化为 YAML 风格文本。"""
    role = node.get("role", "")
    name = node.get("name", "")
    attrs = _format_attrs(node)

    name_part = f' "{name}"' if name else ""
    line = "  " * indent + f"- {role}{name_part}{attrs}"
    lines = [line]

    for child in node.get("children", []):
        lines.append(snapshot_to_text(child, indent + 1))

    return "\n".join(lines)


def serialize_page_state(snapshot: dict | None, max_depth: int = 8) -> str:
    """将 Playwright accessibility.snapshot() 输出序列化为 AX 文本。"""
    if not snapshot:
        return ""
    pruned = prune_snapshot(snapshot, max_depth=max_depth)
    if not pruned:
        return ""
    return snapshot_to_text(pruned)
