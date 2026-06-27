"""AX 树序列化单元测试。"""

from agent.core.page_state import prune_snapshot, serialize_page_state, snapshot_to_text


def test_prune_snapshot_drops_meaningless_leaf():
    snapshot = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {"role": "StaticText", "name": ""},
            {"role": "button", "name": "OK"},
        ],
    }
    pruned = prune_snapshot(snapshot)
    assert pruned["role"] == "WebArea"
    assert len(pruned["children"]) == 1
    assert pruned["children"][0]["role"] == "button"


def test_prune_snapshot_depth_limit():
    snapshot = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {
                "role": "generic",
                "name": "",
                "children": [
                    {"role": "button", "name": "Deep"},
                ],
            }
        ],
    }
    pruned = prune_snapshot(snapshot, max_depth=1)
    # 根节点 depth=0，子节点 depth=1 可保留；孙节点 depth=2 被裁剪
    assert pruned["children"][0].get("children") is None


def test_snapshot_to_text_format():
    node = {
        "role": "WebArea",
        "name": "TPT",
        "children": [
            {
                "role": "radiogroup",
                "name": "segmented control",
                "children": [
                    {"role": "radio", "name": "密码登录", "checked": True},
                ],
            },
            {"role": "textbox", "name": "请输入用户名", "required": True, "value": "15700078644"},
            {"role": "button", "name": "立即登录"},
        ],
    }
    text = snapshot_to_text(node)
    lines = text.splitlines()
    assert lines[0] == '- WebArea "TPT"'
    assert '  - radiogroup "segmented control"' in lines
    assert '    - radio "密码登录" [checked]' in lines
    assert '  - textbox "请输入用户名" [required, value="15700078644"]' in lines
    assert '  - button "立即登录"' in lines


def test_serialize_page_state_empty():
    assert serialize_page_state(None) == ""
    assert serialize_page_state({}) == ""


def test_serialize_page_state_preserves_value():
    snapshot = {
        "role": "textbox",
        "name": "用户名",
        "value": "admin",
    }
    text = serialize_page_state(snapshot)
    assert 'value="admin"' in text
