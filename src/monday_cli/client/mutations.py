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

# Add content to a doc from markdown
ADD_CONTENT_FROM_MARKDOWN = """
mutation AddContentFromMarkdown($docId: ID!, $markdown: String!) {
  add_content_to_doc_from_markdown(docId: $docId, markdown: $markdown) {
    success
    block_ids
    error
  }
}
"""

# Delete a document block
DELETE_DOC_BLOCK = """
mutation DeleteDocBlock($blockId: String!) {
  delete_doc_block(block_id: $blockId) {
    id
  }
}
"""

# Delete a document
DELETE_DOC = """
mutation DeleteDoc($docId: ID!) {
  delete_doc(docId: $docId)
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

# Move an item to another group on its own board
MOVE_ITEM_TO_GROUP = """
mutation MoveItemToGroup($itemId: ID!, $groupId: String!) {
  move_item_to_group(item_id: $itemId, group_id: $groupId) {
    id
    name
    group {
      id
      title
    }
    board {
      id
      name
    }
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

# Create a column (structure) on a board. `column_type` is a ColumnType enum value
# passed as an unquoted enum; `defaults` is a JSON string that seeds status/dropdown
# labels (validated by Monday against the column-type schema).
CREATE_COLUMN = """
mutation CreateColumn(
  $boardId: ID!,
  $title: String!,
  $columnType: ColumnType!,
  $defaults: JSON,
  $description: String,
  $columnId: String
) {
  create_column(
    board_id: $boardId
    title: $title
    column_type: $columnType
    defaults: $defaults
    description: $description
    id: $columnId
  ) {
    id
    title
    type
    description
    settings_str
  }
}
"""

# Rename a column.
CHANGE_COLUMN_TITLE = """
mutation ChangeColumnTitle($boardId: ID!, $columnId: String!, $title: String!) {
  change_column_title(board_id: $boardId, column_id: $columnId, title: $title) {
    id
    title
    type
  }
}
"""

# Change a column's title OR description (ColumnProperty is `title` | `description`).
# NOTE: this mutation does NOT add status/dropdown labels — see the Gotchas section.
CHANGE_COLUMN_METADATA = """
mutation ChangeColumnMetadata(
  $boardId: ID!,
  $columnId: String!,
  $columnProperty: ColumnProperty!,
  $value: String!
) {
  change_column_metadata(
    board_id: $boardId
    column_id: $columnId
    column_property: $columnProperty
    value: $value
  ) {
    id
    title
    description
    type
    settings_str
  }
}
"""

# Delete a column (destructive — removes the column and all its cell data).
DELETE_COLUMN = """
mutation DeleteColumn($boardId: ID!, $columnId: String!) {
  delete_column(board_id: $boardId, column_id: $columnId) {
    id
  }
}
"""

# Add a label to an existing status/dropdown column by writing a label value
# to a board item with create_labels_if_missing:true.
#
# VERIFIED live (see .genesis/VERIFIED_FINDINGS.md §"columns update label mechanisms"):
#   - value must be JSON-stringified {"label": "<LabelText>"}
#   - create_labels_if_missing:true causes Monday to add the label to the
#     column's label set if it does not already exist (idempotent for existing
#     labels); it also sets that item's cell to the written label (side-effect).
#   - Requires a real board item to write to; fetch one with GET_BOARD_FIRST_ITEM.
#
# NOTE: do NOT alter CHANGE_COLUMN_VALUE — items/subitems depend on it as-is.
CHANGE_COLUMN_VALUE_CREATE_LABELS = """
mutation ChangeColumnValueCreateLabels(
  $boardId: ID!, $itemId: ID!, $columnId: String!, $value: JSON!
) {
  change_column_value(
    board_id: $boardId
    item_id: $itemId
    column_id: $columnId
    value: $value
    create_labels_if_missing: true
  ) {
    id
  }
}
"""
