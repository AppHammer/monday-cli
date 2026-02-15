"""GraphQL mutation templates for Monday.com API."""

# Create item on a board
CREATE_ITEM = """
mutation CreateItem($boardId: ID!, $groupId: String, $itemName: String!, $columnValues: JSON) {
  create_item(
    board_id: $boardId
    group_id: $groupId
    item_name: $itemName
    column_values: $columnValues
  ) {
    id
    name
    created_at
  }
}
"""

# Create update on item (works for items and subitems)
CREATE_UPDATE = """
mutation CreateUpdate($itemId: ID!, $body: String!) {
  create_update(item_id: $itemId, body: $body) {
    id
    body
    created_at
  }
}
"""

# Create subitem
CREATE_SUBITEM = """
mutation CreateSubitem($parentItemId: ID!, $itemName: String!, $columnValues: JSON) {
  create_subitem(
    parent_item_id: $parentItemId
    item_name: $itemName
    column_values: $columnValues
  ) {
    id
    name
    board {
      id
    }
  }
}
"""

# Change column value (for status updates)
CHANGE_COLUMN_VALUE = """
mutation ChangeColumnValue($boardId: ID!, $itemId: ID!, $columnId: String!, $value: JSON!) {
  change_column_value(
    board_id: $boardId
    item_id: $itemId
    column_id: $columnId
    value: $value
  ) {
    id
    name
  }
}
"""

# Create document in a doc column
CREATE_DOC = """
mutation CreateDoc($itemId: ID!, $columnId: String!) {
  create_doc(location: { board: { item_id: $itemId, column_id: $columnId } }) {
    id
  }
}
"""

# Create document block (add content to doc)
CREATE_DOC_BLOCK = """
mutation CreateDocBlock($docId: ID!, $type: DocBlockContentType!, $content: JSON!) {
  create_doc_block(doc_id: $docId, type: $type, content: $content) {
    id
    type
    content
  }
}
"""

# Create group on a board
CREATE_GROUP = """
mutation CreateGroup($boardId: ID!, $groupName: String!, $groupColor: String) {
  create_group(
    board_id: $boardId
    group_name: $groupName
    group_color: $groupColor
  ) {
    id
    title
    color
  }
}
"""

# Delete group from a board
DELETE_GROUP = """
mutation DeleteGroup($boardId: ID!, $groupId: String!) {
  delete_group(
    board_id: $boardId
    group_id: $groupId
  ) {
    id
    deleted
  }
}
"""

# Delete item (works for both items and subitems)
DELETE_ITEM = """
mutation DeleteItem($itemId: ID!) {
  delete_item(
    item_id: $itemId
  ) {
    id
  }
}
"""
